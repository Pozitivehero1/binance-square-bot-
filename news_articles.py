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
from deepseek_primary import configured, endpoint

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

def _parse_news_completion(payload):
    """Accept a JSON object or a fenced JSON object, never arbitrary proxy prose."""
    try:
        message = payload["choices"][0]["message"]
        value = message.get("content") or ""
        if isinstance(value, dict):
            return value
        if not isinstance(value, str):
            return None
        value = value.strip()
        if value.startswith("```"):
            value = re.sub(r"^\x60{3}(?:json)?\\s*|\\s*\x60{3}$", "", value, flags=re.I).strip()
        try:
            decoded = json.loads(value)
        except (ValueError, TypeError):
            # Some proxies wrap a valid JSON object in a one-line preamble.
            offset = value.find("{")
            if offset < 0:
                return None
            decoded, _ = json.JSONDecoder().raw_decode(value[offset:])
        return decoded if isinstance(decoded, dict) else None
    except (KeyError, IndexError, TypeError, ValueError):
        return None


def _draft(item, tickers):
    payload = {
        "model": os.getenv("DEEPSEEK_MODEL", "deepseek-chat"),
        "messages": [
            {"role": "system", "content": (
                "Ты независимый редактор криптоновостей. Пиши по-русски: "
                "английские слова допустимы лишь в собственных названиях компаний и проектов. "
                "Создай оригинальную новостную статью на 500–1000 символов по имеющимся фактам. "
                "Если данных мало, честно сообщи об этом; не дополняй домыслами. "
                "Не придумывай цифры, цитаты, даты, причины, прогнозы, сделки или инсайды. "
                "Отделяй факт от вывода и не копируй английский заголовок дословно. "
                "Содержательно используй указанный cashtag вида $BTC. "
                "Ответ строго один JSON-объект с полями title и text, без Markdown."
            )},
            {"role": "user", "content": json.dumps({"headline": item["title"],
                "description": item["summary"], "tickers": tickers}, ensure_ascii=False)},
        ],
        "response_format": {"type": "json_object"}, "temperature": 0.5,
        "max_tokens": 1000, "stream": False,
    }
    response = requests.post(
        endpoint(), json=payload, timeout=(5, 18), allow_redirects=False,
        headers={"Authorization": "Bearer " + os.environ["DEEPSEEK_API_KEY"]},
    )
    response.raise_for_status()
    try:
        result = _parse_news_completion(response.json())
    except (ValueError, TypeError):
        result = None
    if not result:
        log.warning("News proxy returned invalid or missing JSON content (HTTP %s)", response.status_code)
        return None
    title, body = str(result.get("title", "")).strip(), str(result.get("text", "")).strip()
    if not 15 <= len(title) <= 130 or not 450 <= len(body) <= 2000:
        return None
    if not any("$" + ticker in body.upper() for ticker in tickers):
        return None
    if re.search(r"https?://|(?:гарантированн|точно вырастет|без риска)", body, re.I):
        return None
    return title, body

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
        except (requests.RequestException, ValueError, KeyError, TypeError, OSError) as exc:
            log.warning("News draft failed: %s", type(exc).__name__)
            # A broken proxy should not consume the full cron window.
            if isinstance(exc, (requests.HTTPError, ValueError)):
                break
    log.info("News lane no article published; AI attempts=%s rejected=%s", attempts, rejected)
    return False
