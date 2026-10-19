"""Read public Square creator profile for editorial inspiration (no private API)."""
from __future__ import annotations
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse
import logging
import re
import requests
import time

LOG = logging.getLogger(__name__)
CREATORS = ("cryptonexus_btc",)
BASE = "https://www.binance.com"
_CACHE = {"at": 0.0, "topics": []}

class _ProfileParser(HTMLParser):
    """Extract creator posts from linked excerpts or enclosing article blocks."""
    def __init__(self):
        super().__init__()
        self.links = []
        self.active = None
        self.article = None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "article" and self.article is None:
            self.article = {"url": "", "text": ""}
        if tag == "a" and self.active is None and re.search(r"/square/post/\d+", attrs.get("href", "")):
            url = urljoin(BASE, attrs["href"])
            self.active = {"url": url, "text": ""}
            if self.article is not None and not self.article["url"]:
                self.article["url"] = url

    def handle_data(self, data):
        if self.active is not None:
            self.active["text"] += data + " "
        if self.article is not None:
            self.article["text"] += data + " "

    def handle_endtag(self, tag):
        if tag == "a" and self.active is not None:
            if len(self.active["text"].strip()) >= 55:
                self.links.append(self.active)
            self.active = None
        if tag == "article" and self.article is not None:
            if self.article["url"] and len(self.article["text"].strip()) >= 70:
                self.links.append(self.article)
            self.article = None

def recent_creator_topics(limit=8):
    """Best effort; returns empty when Binance blocks requests or renders via JS."""
    if time.monotonic() - _CACHE["at"] < 3600:
        return _CACHE["topics"][:limit]
    result = []
    for handle in CREATORS:
        try:
            r = requests.get(f"{BASE}/en/square/profile/{handle}", timeout=8,
                             headers={"User-Agent": "Mozilla/5.0 (compatible; SquareEditorial/1.0)"},
                             allow_redirects=False)
            r.raise_for_status()
            parser = _ProfileParser()
            parser.feed(r.text[:2_000_000])
            LOG.info("Creator %s: HTTP=%d page_bytes=%d candidate_post_links=%d",
                     handle, r.status_code, len(r.content), len(parser.links))
            for item in parser.links:
                if urlparse(item["url"]).hostname != "www.binance.com":
                    continue
                title = re.sub(r"\s+", " ", item["text"]).strip()[:450]
                if not title or re.search(r"(?i)premium group|free trial|scan qr|subscribe now", title):
                    continue
                existing = next((x for x in result if x["url"] == item["url"]), None)
                if existing:
                    if len(title) > len(existing["topic"]):
                        existing["topic"] = title
                else:
                    result.append({"creator": handle, "url": item["url"], "topic": title})
                    if len(result) >= limit:
                        _CACHE.update(at=time.monotonic(), topics=result)
                        return result
        except (requests.RequestException, ValueError) as exc:
            LOG.warning("Creator feed unavailable for %s: %s", handle, type(exc).__name__)
    _CACHE.update(at=time.monotonic(), topics=result)
    LOG.info("Creator inspiration topics_available=%d", len(result))
    return result
