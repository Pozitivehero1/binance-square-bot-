"""RSS reporting with source text and real covers; never fabricate a news image."""
from __future__ import annotations

import hashlib
import html
from html.parser import HTMLParser
import ipaddress
import logging
import re
import socket
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from email.utils import parsedate_to_datetime
from urllib.parse import urljoin, urlsplit, urlunsplit

import requests

from news_evidence import source_has_event
from .models import Story, utcnow

LOG = logging.getLogger(__name__)
FEEDS = ("https://cointelegraph.com/rss", "https://decrypt.co/feed",
         "https://www.coindesk.com/arc/outboundfeeds/rss/")
NAMES = {"bitcoin": "BTC", "btc": "BTC", "ethereum": "ETH", "ether": "ETH", "solana": "SOL",
         "xrp": "XRP", "ripple": "XRP", "bnb": "BNB", "dogecoin": "DOGE", "cardano": "ADA",
         "chainlink": "LINK", "avalanche": "AVAX", "tron": "TRX", "sui": "SUI", "toncoin": "TON"}


def public_url(url):
    parsed = urlsplit(url)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.port not in {None, 443}:
        raise ValueError("Expected a public HTTPS URL")
    addresses = socket.getaddrinfo(parsed.hostname, 443, type=socket.SOCK_STREAM)
    if not addresses or any(not ipaddress.ip_address(a[4][0]).is_global for a in addresses):
        raise ValueError("Non-public address")
    return url


def download(url, max_bytes=2_000_000, image=False):
    """Bound transfers and validate every redirect, including CDN image redirects."""
    for _ in range(4):
        public_url(url)
        with requests.get(url, timeout=(4, 10), stream=True, allow_redirects=False,
                          headers={"User-Agent": "SquareEditorialBot/13.0"}) as response:
            if response.is_redirect:
                url = urljoin(url, response.headers.get("Location", ""))
                continue
            response.raise_for_status()
            if image and not response.headers.get("Content-Type", "").lower().startswith("image/"):
                raise ValueError("Cover is not an image")
            data = bytearray()
            for chunk in response.iter_content(32_768):
                data.extend(chunk)
                if len(data) > max_bytes:
                    raise ValueError("Response exceeds size limit")
            return bytes(data)
    raise ValueError("Too many redirects")


class Text(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts, self.images, self.meta = [], [], {}
        self.skip = 0

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag in {"script", "style"}:
            self.skip += 1
        if tag == "img" and attrs.get("src"):
            self.images.append(attrs["src"])
        if tag == "meta":
            self.meta[attrs.get("property") or attrs.get("name")] = attrs.get("content", "")
        if tag in {"p", "br", "div"}:
            self.parts.append(" ")

    def handle_endtag(self, tag):
        if tag in {"script", "style"}:
            self.skip = max(0, self.skip-1)

    def handle_data(self, data):
        if not self.skip:
            self.parts.append(data)


def plain(value):
    parser = Text()
    parser.feed(html.unescape(value or ""))
    return " ".join(" ".join(parser.parts).split())


def canonical_url(url):
    value = urlsplit(url)
    return urlunsplit((value.scheme, value.netloc.lower(), value.path.rstrip("/"), "", ""))


def parse_feed(data, now=None):
    now = now or utcnow()
    root = ET.fromstring(data)
    stories = []
    for item in root.findall(".//item")[:25]:
        try:
            date = parsedate_to_datetime(item.findtext("pubDate") or "")
            age = (now - date).total_seconds()/3600
            if not 0 <= age <= 18:
                continue
            title = plain(item.findtext("title"))
            link = canonical_url(item.findtext("link") or "")
            if urlsplit(link).scheme != "https":
                continue
            description = plain(item.findtext("description"))
            full = plain(item.findtext("{http://purl.org/rss/1.0/modules/content/}encoded"))
            source = (title + "\n" + (full if len(full) > len(description) else description))[:8000]
            summary = {"title": title, "summary": source[len(title):].strip()}
            if not source_has_event(summary):
                continue
            symbols = list(dict.fromkeys(v for k, v in NAMES.items()
                                        if re.search(r"(?<![a-z])"+re.escape(k)+r"(?![a-z])", source.lower())))[:3]
            if not symbols:
                continue
            image_url = ""
            for tag in ("{http://search.yahoo.com/mrss/}content", "{http://search.yahoo.com/mrss/}thumbnail", "enclosure"):
                child = item.find(tag)
                if child is not None and child.get("url", "").startswith("https://"):
                    image_url = child.get("url")
                    break
            if not image_url:
                parser = Text()
                parser.feed(item.findtext("description") or "")
                image_url = next((u for u in parser.images if u.startswith("https://")), "")
            key = hashlib.sha256(link.encode()).hexdigest()[:16]
            stories.append(Story(key, "news", symbols, title, {}, date.isoformat(),
                                 55+max(0, 12-age), link, source, image_url, "news:"+key))
        except (ValueError, TypeError, OverflowError):
            continue
    return stories


def scan():
    def fetch(feed):
        try:
            return parse_feed(download(feed))
        except (requests.RequestException, ValueError, OSError, ET.ParseError):
            LOG.warning("News feed unavailable host=%s", urlsplit(feed).hostname)
            return []
    with ThreadPoolExecutor(max_workers=3) as pool:
        results = list(pool.map(fetch, FEEDS))
    rows = {s.id: s for batch in results for s in batch}
    LOG.info("News scan stories=%s feeds_available=%s/%s", len(rows), sum(bool(r) for r in results), len(FEEDS))
    return list(rows.values())


def cover(story, directory):
    """Return None if the original cover is unavailable; the story can be a short post."""
    try:
        url = story.image_url
        if not url:
            parser = Text()
            parser.feed(download(story.source_url).decode("utf-8", errors="replace"))
            url = parser.meta.get("og:image", "") or parser.meta.get("twitter:image", "")
        if not url:
            return None
        from io import BytesIO
        from PIL import Image
        raw = download(url, max_bytes=5_000_000, image=True)
        im = Image.open(BytesIO(raw))
        im.verify()
        im = Image.open(BytesIO(raw)).convert("RGB")
        im.thumbnail((1600, 1200))
        path = directory / "news_cover.jpg"
        im.save(path, "JPEG", quality=88)
        return str(path)
    except (requests.RequestException, ValueError, OSError):
        LOG.info("Original news cover unavailable story=%s", story.id)
        return None
