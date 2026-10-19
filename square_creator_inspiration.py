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
    def __init__(self):
        super().__init__()
        self.links = []
        self.active = None
        self.depth = 0
    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if self.active is not None:
            if tag == "a":
                self.depth += 1
        elif tag == "a" and re.search(r"/square/post/\d+", attrs.get("href", "")):
            self.active = {"url": urljoin(BASE, attrs["href"]), "text": ""}
            self.depth = 1
    def handle_data(self, data):
        if self.active is not None:
            self.active["text"] += data
    def handle_endtag(self, tag):
        if self.active is not None and tag == "a":
            self.depth -= 1
            if self.depth <= 0:
                if len(self.active["text"].strip()) >= 45:
                    self.links.append(self.active)
                self.active = None

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
            for item in parser.links:
                if urlparse(item["url"]).hostname != "www.binance.com":
                    continue
                title = re.sub(r"\s+", " ", item["text"]).strip()[:450]
                if title and not any(x["url"] == item["url"] for x in result):
                    result.append({"creator": handle, "url": item["url"], "topic": title})
                    if len(result) >= limit:
                        _CACHE.update(at=time.monotonic(), topics=result)
                        return result
        except (requests.RequestException, ValueError) as exc:
            LOG.info("Creator feed unavailable for %s: %s", handle, type(exc).__name__)
    _CACHE.update(at=time.monotonic(), topics=result)
    return result
