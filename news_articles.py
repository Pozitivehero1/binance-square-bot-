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
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import urlparse
import requests
from runtime import resolve_state_file, atomic_write_json, write_status
from publisher import publish
from news_evidence import source_has_event, draft_reasons
from deepseek_primary import configured
import ai_provider


def request_candidates(**kwargs):
    """Use the production DeepSeek-first chain, including configured free AI fallbacks."""
    return ai_provider.request_candidates(**kwargs)

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
    """Use the production AI chain while retaining strict news evidence validation."""
    if not source_has_event(item):
        log.info("News skipped: RSS item has no specific event")
        return None
    result = request_candidates(
        system_prompt=(
            "Ты независимый русскоязычный редактор криптоновостей. "
            "Используй исключительно факты из headline и description. "
            "Не придумывай факты, числа, причины, цитаты, сделки или прогнозы. "
            "При нехватке сведений не заполняй текст общими фразами. Не сообщай читателю о входных данных, промпте или недостающих полях: просто опусти неизвестные детали. Отсутствие деталей в RSS не означает, что они не раскрыты: такого утверждения делать нельзя без прямого подтверждения. "
            "Напиши оригинальную содержательную новость длиной 180–1000 символов; краткий факт не растягивай до статьи. "
            "Основной текст только на русском, английский допустим в названиях. "
            "Укажи подходящий cashtag вида $BTC из входных данных. "
            "Верни ровно один JSON-объект с массивом candidates, "
            "в котором один элемент с полями title (русский заголовок) и text "
            "(текст новости), evidence_quote (дословный фрагмент исходного headline/description с конкретным событием, минимум 25 символов). Никакого Markdown и текста вне JSON."
        ),
        user_payload={"headline": item["title"], "description": item["summary"],
                      "tickers": tickers,
                      "output_schema": {"candidates": [{"title": "Заголовок", "text": "Статья", "evidence_quote": "Exact source event"}]}},
        temperature=0.5, max_tokens=1200, timeout=25,
    )
    rejected = {"length": 0, "cashtag": 0, "unsafe": 0, "evidence": 0}
    for row in result.candidates:
        title, body = str(row.get("title", "")).strip(), str(row.get("text", "")).strip()
        if not 15 <= len(title) <= 130 or not 180 <= len(body) <= 1200:
            rejected["length"] += 1
            continue
        if not any("$" + ticker in body.upper() for ticker in tickers):
            rejected["cashtag"] += 1
            continue
        if re.search(r"https?://|(?:гарантированн|точно вырастет|без риска)", body, re.I):
            rejected["unsafe"] += 1
            continue
        reasons = draft_reasons(body, str(row.get("evidence_quote") or ""), item)
        if reasons:
            rejected["evidence"] += 1
            log.info("News evidence rejected: %s", ", ".join(reasons))
            continue
        source_name = urlparse(item["link"]).hostname or "источник"
        body += "\n\nИсточник: " + source_name
        item["verified_evidence_quote"] = row["evidence_quote"]
        item["writer_source"] = str(result.provider or "unknown")
        log.info("News AI draft valid provider=%s chars=%d", result.provider, len(body))
        return title, body
    log.info(
        "News AI returned no eligible draft: provider=%s candidates=%d rejected=%s",
        result.provider, len(result.candidates), rejected,
    )
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
    if not (configured() or ai_provider.has_ai_provider()):
        log.warning("News lane unavailable: no AI author configured")
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
    # The AI chain can fail across all providers; avoid repeated attempts on outages.
    # Persist a short retry delay after a provider failure to avoid repeatedly
    # spending requests on the same outage. Market posts still use their own
    # independent fallback providers.
    provider_retry_at = state.get("provider_retry_at", "")
    if provider_retry_at:
        try:
            if now < datetime.fromisoformat(provider_retry_at):
                log.info("News lane provider retry backoff active until %s", provider_retry_at)
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
                try:
                    draft = _draft(item, tickers)
                except RuntimeError:
                    # All configured AI providers failed. Avoid retrying the same chain every 20 minutes.
                    state["provider_retry_at"] = (now + timedelta(minutes=60)).isoformat()
                    atomic_write_json(resolve_state_file("NEWS_STATE_FILE", "news_articles.json"), state)
                    raise
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
            state.pop("provider_retry_at", None)
            atomic_write_json(resolve_state_file("NEWS_STATE_FILE", "news_articles.json"), state)
            # Successful news publication must be visible to run telemetry and
            # the same 2h/6h/24h performance tracking as ordinary posts.
            write_status("published", "Binance Square news article with RSS cover published",
                         lane="news", post_id=result.post_id, symbol=tickers[0])
            try:
                from performance_store import record_publication
                record_publication(
                    post_id=result.post_id, symbol=tickers[0],
                    market_symbol=tickers[0] + "USDT", text=draft[1],
                    lane="NEWS", direction="observation",
                    content_format="news_article", visual_style="rss_cover",
                    event_class="news", writer_source=item.get("writer_source", "unknown"),
                    fact_package={"source_url": item["link"], "headline": item["title"],
                                  "description": item["summary"], "evidence_quote": item.get("verified_evidence_quote", "")},
                )
            except Exception:
                log.exception("News published but performance tracking failed")
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
