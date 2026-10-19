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

def _draft(item, tickers):
    payload = {
        "model": os.getenv("DEEPSEEK_MODEL", "deepseek-chat"),
        "messages": [
            {"role": "system", "content": (
                "Ты независимый русскоязычный редактор криптоновостей Binance Square. "
                "Напиши оригинальную содержательную статью 900-1800 символов по данным новости. "
                "Не копируй исходные формулировки. Не выдумывай цифры, цитаты, даты, "
                "причинно-следственные связи или прогнозы. Разделяй факты и интерпретацию. "
                "Добавь органично связанные тикеры в формате $BTC. "
                "Не вставляй ссылки на источник в опубликованный текст. "
                "Заверши содержательным вопросом только если он уместен. "
                "Верни JSON с полями title и text." )},
            {"role": "user", "content": json.dumps({"headline": item["title"],
                "description": item["summary"], "tickers": tickers}, ensure_ascii=False)},
        ],
        "response_format": {"type": "json_object"}, "temperature": 0.75,
        "max_tokens": 1100, "stream": False,
    }
    r = requests.post(endpoint(), json=payload, timeout=25, allow_redirects=False,
                      headers={"Authorization": "Bearer " + os.environ["DEEPSEEK_API_KEY"]})
    r.raise_for_status()
    result = json.loads(r.json()["choices"][0]["message"]["content"])
    title, body = str(result.get("title", "")).strip(), str(result.get("text", "")).strip()
    if not 15 <= len(title) <= 130 or not 650 <= len(body) <= 2800:
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
    if os.getenv("ENABLE_NEWS_ARTICLES", "0") != "1" or not configured():
        return False
    import random
    if random.random() >= float(os.getenv("NEWS_SLOT_PROBABILITY", "0.25")):
        return False
    state = _load()
    seen = state.get("seen", {})
    now = datetime.now(timezone.utc)
    last = state.get("last_news_at", "")
    try:
        if (now - datetime.fromisoformat(last)).total_seconds() < 3 * 3600:
            return False
    except (ValueError, TypeError):
        pass
    for item in _fetch():
        key = hashlib.sha256(item["link"].encode()).hexdigest()
        tickers = _ticker(item)
        if not tickers or key in seen or not item["image"]:
            continue
        # Use the image supplied by the news feed as requested. The URL must
        # still be HTTPS and the response must be a bounded valid image.
        try:
            draft = _draft(item, tickers)
            if not draft:
                continue
            with tempfile.TemporaryDirectory() as directory:
                cover = _cover(item["image"], directory)
                if not cover:
                    continue
                result = publish(draft[1], image_path=cover, article_title=draft[0])
                if not result:
                    log.warning("News article not confirmed: %s", result.stderr[:200])
                    return False
            seen[key] = now.isoformat()
            state["seen"] = dict(list(seen.items())[-500:])
            state["last_news_at"] = now.isoformat()
            atomic_write_json(resolve_state_file("NEWS_STATE_FILE", "news_articles.json"), state)
            log.info("News article published id=%s ticker=%s", result.post_id, tickers)
            return True
        except (requests.RequestException, ValueError, KeyError, TypeError, OSError) as exc:
            log.warning("News draft failed: %s", type(exc).__name__)
    return False
