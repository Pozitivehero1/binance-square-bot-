"""Optional news article lane within the existing cron workflow."""
from __future__ import annotations
import hashlib
import html
import json
import logging
import os
import re
import tempfile
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import urlparse
import requests
from runtime import resolve_state_file, atomic_write_json
from publisher import publish
from deepseek_primary import configured, request_candidates

log = logging.getLogger(__name__)
FEEDS = (
    "https://cointelegraph.com/rss",
    "https://decrypt.co/feed",
)
SYMBOLS = {
    "bitcoin": "BTC", "btc": "BTC", "ethereum": "ETH", "ether": "ETH",
    "solana": "SOL", "xrp": "XRP", "ripple": "XRP", "bnb": "BNB",
    "dogecoin": "DOGE", "cardano": "ADA", "ada": "ADA", "chainlink": "LINK",
    "avalanche": "AVAX", "polkadot": "DOT", "tron": "TRX",
}
MEDIA = "{http://search.yahoo.com/mrss/}content"
THUMB = "{http://search.yahoo.com/mrss/}thumbnail"

def _load():
    path = resolve_state_file("NEWS_STATE_FILE", "news_articles.json")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"seen": {}, "last_news_at": ""}

def _fetch():
    entries = []
    for feed in FEEDS:
        try:
            response = requests.get(feed, timeout=9, headers={"User-Agent": "SquareNewsEditor/1.0"})
            response.raise_for_status()
            root = ET.fromstring(response.content[:2_000_000])
            for item in root.findall(".//item")[:18]:
                title = html.unescape(re.sub(r"<[^>]+>", "", item.findtext("title") or "")).strip()
                link = (item.findtext("link") or "").strip()
                desc = html.unescape(re.sub(r"<[^>]+>", " ", item.findtext("description") or "")).strip()
                date = item.findtext("pubDate") or ""
                try:
                    age = (datetime.now(timezone.utc) - parsedate_to_datetime(date).astimezone(timezone.utc)).total_seconds()
                except (ValueError, TypeError, OverflowError):
                    continue
                if not 0 <= age <= 18 * 3600 or not title or not link:
                    continue
                image = ""
                for tag in (item.find(THUMB), item.find(MEDIA), item.find("enclosure")):
                    if tag is not None and tag.get("url", "").startswith("https://"):
                        image = tag.get("url", "")
                        break
                entries.append({"title": title, "link": link, "summary": desc[:700],
                                "image": image, "age": age})
        except (requests.RequestException, ET.ParseError) as exc:
            log.warning("News feed unavailable: %s (%s)", feed, type(exc).__name__)
    return sorted(entries, key=lambda x: x["age"])

def _ticker(item):
    text = (item["title"] + " " + item["summary"]).lower()
    found = [v for k, v in SYMBOLS.items() if re.search(r"(?<![a-z])" + re.escape(k) + r"(?![a-z])", text)]
    return list(dict.fromkeys(found))[:3]

def _draft(item, tickers):
    """Use the proven DeepSeek candidate protocol, not a separate fragile JSON shape."""
    result = request_candidates(
        system_prompt=(
            "Ты независимый русскоязычный редактор криптоновостей. "
            "Используй исключительно факты из headline и description. "
            "Не придумывай факты, числа, причины, цитаты, сделки или прогнозы. "
            "При нехватке сведений не заполняй текст общими фразами. "
            "Напиши оригинальную содержательную новость длиной 450–1000 символов. "
            "Основной текст только на русском, английский допустим в названиях. "
            "Укажи подходящий cashtag вида $BTC из входных данных. "
            "Верни ровно один JSON-объект с массивом candidates, "
            "в котором один элемент с полями title (русский заголовок) и text "
            "(текст новости). Никакого Markdown и текста вне JSON."
        ),
        user_payload={"headline": item["title"], "description": item["summary"],
                      "tickers": tickers,
                      "output_schema": {"candidates": [{"title": "Заголовок", "text": "Статья"}]}},
        temperature=0.5, max_tokens=1200, timeout=25,
    )
    for row in result.candidates:
        title, body = str(row.get("title", "")).strip(), str(row.get("text", "")).strip()
        if not 15 <= len(title) <= 130 or not 450 <= len(body) <= 2000:
            continue
        if not any("$" + ticker in body.upper() for ticker in tickers):
            continue
        if re.search(r"https?://|(?:гарантированн|точно вырастет|без риска)", body, re.I):
            continue
        log.info("News AI draft valid provider=%s chars=%d", result.provider, len(body))
        return title, body
    log.info("News AI returned candidates without eligible title/body")
    return None

def _cover(url, directory):
    if not url or urlparse(url).scheme != "https":
        return None
    try:
        r = requests.get(url, timeout=9, stream=True, allow_redirects=False)
        r.raise_for_status()
        if not r.headers.get("Content-Type", "").lower().startswith("image/"):
            return None
        data = b""
        for chunk in r.iter_content(32768):
            data += chunk
            if len(data) > 4_000_000:
                return None
        from PIL import Image
        from io import BytesIO
        im = Image.open(BytesIO(data))
        im.verify()
        path = Path(directory) / "news_cover.jpg"
        Image.open(BytesIO(data)).convert("RGB").save(path, "JPEG", quality=85)
        return str(path)
    except (requests.RequestException, OSError, ValueError):
        return None

def maybe_publish_news():
    """Return True only when an article is confirmed published; otherwise fall back to market."""
    if os.getenv("ENABLE_NEWS_ARTICLES", "0") != "1":
        log.info("News lane disabled")
        return False
    if not configured():
        log.warning("News lane unavailable: DeepSeek not configured")
        return False
    # Always inspect the news lane when enabled; cooldown and deduplication
    # decide eligibility rather than a silent random 75% skip.
    state = _load()
    seen = state.get("seen", {})
    now = datetime.now(timezone.utc)
    last = state.get("last_news_at", "")
    try:
        if (now - datetime.fromisoformat(last)).total_seconds() < 3 * 3600:
            log.info("News lane cooldown active (last=%s)", last)
            return False
    except (ValueError, TypeError):
        pass
    items = _fetch()
    log.info("News lane RSS entries=%d", len(items))
    rejected = {"seen": 0, "ticker": 0, "image": 0, "draft": 0, "cover": 0}
    attempts = 0
    max_attempts = max(1, min(5, int(os.getenv("NEWS_MAX_DRAFT_ATTEMPTS", "3"))))
    for item in items:
        key = hashlib.sha256(item["link"].encode()).hexdigest()
        tickers = _ticker(item)
        if key in seen:
            rejected["seen"] += 1
            continue
        if not tickers:
            rejected["ticker"] += 1
            continue
        if not item["image"]:
            rejected["image"] += 1
            continue
        if attempts >= max_attempts:
            log.info("News lane AI budget reached: %s/%s", attempts, max_attempts)
            break
        # Check the feed's cover before spending a model request.
        try:
            with tempfile.TemporaryDirectory() as directory:
                cover = _cover(item["image"], directory)
                if not cover:
                    rejected["cover"] += 1
                    continue
                attempts += 1
                draft = _draft(item, tickers)
                if not draft:
                    rejected["draft"] += 1
                    continue
                result = publish(draft[1], image_path=cover, article_title=draft[0])
                if not result:
                    log.warning("News article not confirmed: %s", result.stderr[:200])
                    # Ambiguous remote sends must never be retried.
                    if "unresolved send" in result.stderr or "timeout" in result.stderr:
                        return False
                    rejected["draft"] += 1
                    continue
            seen[key] = now.isoformat()
            state["seen"] = dict(list(seen.items())[-500:])
            state["last_news_at"] = now.isoformat()
            atomic_write_json(resolve_state_file("NEWS_STATE_FILE", "news_articles.json"), state)
            log.info("News article published id=%s ticker=%s", result.post_id, tickers)
            return True
        except requests.Timeout:
            log.warning("News draft timed out; stop news attempts this run")
            break
        except (requests.RequestException, ValueError, KeyError, TypeError, OSError, RuntimeError) as exc:
            log.warning("News draft failed: %s", type(exc).__name__)
            # A broken proxy should not consume the full cron window.
            if isinstance(exc, (requests.HTTPError, ValueError, RuntimeError)):
                break
    log.info("News lane no article published; AI attempts=%s rejected=%s", attempts, rejected)
    return False
