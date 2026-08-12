"""Public Binance Square profile statistics client.

The endpoints used here are public web endpoints observed in the Binance Square web
client. No account cookie, SQUARE_API key, or browser token is sent. Failures are
non-fatal by design: analytics must never prevent publishing.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
import logging
import os
import re
from typing import Iterable, List, Optional

import requests

logger = logging.getLogger(__name__)

PROFILE_ENDPOINT = (
    "https://www.binance.com/bapi/composite/v2/friendly/pgc/content/"
    "queryUserProfilePageContentsWithFilter"
)
DETAIL_ENDPOINT = (
    "https://www.binance.com/bapi/composite/v3/friendly/pgc/special/content/detail/{post_id}"
)


@dataclass(frozen=True)
class PublicPostStats:
    post_id: str
    text: str
    symbol: str
    published_ms: int
    views: int
    likes: int
    comments: int
    quotes: int
    shares: int
    image_url: str = ""
    language: str = ""

    def as_dict(self) -> dict:
        return asdict(self)


def _int(value: object, default: int = 0) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return default


def extract_symbol(text: str) -> str:
    match = re.search(r"\$([A-Za-z0-9]{2,24})", str(text or ""))
    if not match:
        return ""
    return match.group(1).upper()


def _parse_content(item: dict) -> Optional[PublicPostStats]:
    if not isinstance(item, dict):
        return None
    post_id = str(item.get("id") or item.get("contentId") or "").strip()
    if not post_id:
        return None
    text = str(item.get("bodyTextOnly") or item.get("title") or "").strip()
    images = item.get("imageList") if isinstance(item.get("imageList"), list) else []
    return PublicPostStats(
        post_id=post_id,
        text=text,
        symbol=extract_symbol(text),
        published_ms=_int(item.get("firstReleaseTime") or item.get("createTime")),
        views=_int(item.get("viewCount")),
        likes=_int(item.get("likeCount")),
        comments=_int(item.get("commentCount")),
        quotes=_int(item.get("quoteCount")),
        shares=_int(item.get("shareCount")),
        image_url=str(images[0]) if images else "",
        language=str(item.get("lan") or ""),
    )


def parse_profile_payload(payload: dict) -> tuple[List[PublicPostStats], Optional[int]]:
    if not isinstance(payload, dict) or str(payload.get("code", "")) not in {"000000", "0", ""}:
        return [], None
    data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    rows = []
    for item in data.get("contents") or []:
        parsed = _parse_content(item)
        if parsed:
            rows.append(parsed)
    offset = data.get("timeOffset")
    try:
        next_offset = int(offset) if offset not in (None, "") else None
    except (TypeError, ValueError):
        next_offset = None
    return rows, next_offset


class BinanceSquarePublicClient:
    def __init__(self, timeout: Optional[int] = None):
        self.timeout = max(5, timeout or int(os.getenv("STATS_HTTP_TIMEOUT", "20")))
        self.session = requests.Session()
        self.session.headers.update(
            {
                "Accept": "application/json, text/plain, */*",
                "User-Agent": os.getenv(
                    "STATS_USER_AGENT",
                    "Mozilla/5.0 (compatible; SquareAnalytics/1.0; +https://www.binance.com/square)",
                ),
                "Referer": "https://www.binance.com/en/square/profile",
            }
        )

    def profile_page(self, profile_uid: str, time_offset: int = -1) -> tuple[List[PublicPostStats], Optional[int]]:
        response = self.session.get(
            PROFILE_ENDPOINT,
            params={
                "targetSquareUid": profile_uid,
                "timeOffset": int(time_offset),
                "filterType": "ALL",
            },
            timeout=self.timeout,
        )
        response.raise_for_status()
        return parse_profile_payload(response.json())

    def recent_posts(self, profile_uid: str, pages: int = 4) -> List[PublicPostStats]:
        profile_uid = str(profile_uid or "").strip()
        if not profile_uid:
            return []
        pages = max(1, min(int(pages), 20))
        offset = -1
        seen_offsets: set[int] = set()
        seen_ids: set[str] = set()
        result: List[PublicPostStats] = []
        for _ in range(pages):
            rows, next_offset = self.profile_page(profile_uid, offset)
            if not rows:
                break
            for row in rows:
                if row.post_id not in seen_ids:
                    result.append(row)
                    seen_ids.add(row.post_id)
            if next_offset is None or next_offset in seen_offsets or next_offset == offset:
                break
            seen_offsets.add(offset)
            offset = next_offset
        return result

    def post_detail(self, post_id: str) -> Optional[PublicPostStats]:
        response = self.session.get(
            DETAIL_ENDPOINT.format(post_id=str(post_id).strip()),
            timeout=self.timeout,
        )
        response.raise_for_status()
        payload = response.json()
        data = payload.get("data") if isinstance(payload, dict) else None
        return _parse_content(data) if isinstance(data, dict) else None
