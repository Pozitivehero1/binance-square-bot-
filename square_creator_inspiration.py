"""Read public Binance Square creator posts via the public profile/content API.

The profile HTML can return HTTP 202 with an empty body on GitHub Actions,
so HTML scraping cannot be the primary data source. No credentials are used.
External posts are inspiration, NEVER evidence for live price/trade claims.
"""
from __future__ import annotations

import logging
import re
import time
from urllib.parse import urlparse

import requests

LOG = logging.getLogger(__name__)
CREATORS = ("cryptonexus_btc",)
BASE = "https://www.binance.com"
PROFILE_API = "/bapi/composite/v3/friendly/pgc/user/client"
POSTS_API = "/bapi/composite/v2/friendly/pgc/content/queryUserProfilePageContentsWithFilter"
MAX_POST_AGE_HOURS = 48
_CACHE = {"at": 0.0, "topics": []}

_PROMO = re.compile(
    r"(?i)\b(?:premium group|paid group|free trial|join my group|join our group|"
    r"subscribe now|invite link|referral link|whatsapp|telegram group|group chat)\b"
)
_CASHTAGS = re.compile(r"(?<![A-Za-z0-9])\$([A-Za-z][A-Za-z0-9]{1,14})\b")


def _editorial_angle(body: str) -> str:
    """An abstract, non-factual angle: never pass another trader's prices."""
    value = body.lower()
    if re.search(r"(?i)\b(?:closed|closing|took profit|stop hit|liquidated|well played)\b", value):
        return "объяснить исход предыдущей идеи, только если собственные результаты проверены"
    if re.search(r"(?i)\b(?:recovery|recover|bounce|rebounds?|reclaim)\b", value):
        return "условия возможного восстановления после снижения"
    if re.search(r"(?i)\b(?:short|bearish|downside|selloff|dump)\b", value):
        return "условия и риски возможного снижения"
    if re.search(r"(?i)\b(?:long|bullish|breakout|rally|surge)\b", value):
        return "условия и риски возможного роста"
    if re.search(r"(?i)\b(?:support|resistance|level|range)\b", value):
        return "важная рыночная граница и что она позволяет проверить"
    if re.search(r"(?i)\b(?:news|etf|announcement|regulation|listing)\b", value):
        return "повод новости, который необходимо подтвердить независимым источником"
    return "одно конкретное наблюдение и его ограничения"


def _editorial_style(body: str) -> str:
    """Transfer narrative structure only, not an unverified trading signal."""
    if "?" in body:
        return "Заверши полезным вопросом читателю, только если данные дают выбор."
    if re.search(r"(?i)\b(?:entry|tp1|tp2|stop.loss|trade signal)\b", body):
        return "Чётко разделяй проверенные факты, условия сценария и риск; чужие уровни не используй."
    if len(body) < 180:
        return "Одна сильная мысль и короткий вывод без повторяющихся оговорок."
    return "Начни с конкретного события, затем объясни значение для читателя."


def _topic_from_post(post: dict, now_ms: int):
    """Normalize a verified recent creator post into safe, original inspiration."""
    if not isinstance(post, dict):
        return None
    post_id = str(post.get("id") or "").strip()
    if not post_id.isdigit():
        return None
    raw = str(post.get("bodyTextOnly") or post.get("title") or "").strip()
    if not 50 <= len(raw) <= 12000 or _PROMO.search(raw):
        return None
    try:
        posted = int(post.get("firstReleaseTime") or post.get("createTime") or 0)
    except (TypeError, ValueError):
        return None
    if posted < 10_000_000_000:
        posted *= 1000
    age_ms = now_ms - posted
    if age_ms < -10 * 60_000 or age_ms > MAX_POST_AGE_HOURS * 3_600_000:
        return None
    tickers = list(dict.fromkeys(t.upper() for t in _CASHTAGS.findall(raw)))[:8]
    angle = _editorial_angle(raw)
    ticker_label = ", ".join("$" + token for token in tickers[:2]) if tickers else "крипторынке"
    return {
        "creator": "cryptonexus_btc",
        "url": f"{BASE}/en/square/post/{post_id}",
        "topic": f"Автор обсуждает {ticker_label}: {angle}. Не переносить его прогноз или числа.",
        "style": _editorial_style(raw),
        "tickers": tickers,
        "published_at_ms": posted,
    }


def _request_data(response: requests.Response, label: str) -> dict:
    response.raise_for_status()
    payload = response.json()
    if (not isinstance(payload, dict) or str(payload.get("code")) != "000000"
            or payload.get("success") is False or not isinstance(payload.get("data"), dict)):
        raise ValueError(f"Unexpected public Square {label} response")
    return payload["data"]


def _fetch_creator(handle: str, now_ms: int) -> list[dict]:
    if not re.fullmatch(r"[A-Za-z0-9_]{3,64}", handle):
        return []
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36"
        ),
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": f"{BASE}/en/square/profile/{handle}",
        "clienttype": "web",
        "Content-Type": "application/json",
    }
    with requests.Session() as session:
        session.headers.update(headers)
        # Warm up public cookie/session headers. The body often returns 202/empty.
        try:
            session.get(f"{BASE}/en/square/profile/{handle}", timeout=5)
        except requests.RequestException:
            LOG.info("Creator %s: HTML warmup unavailable; trying public API", handle)
        profile = _request_data(session.post(
            BASE + PROFILE_API,
            json={"username": handle, "getFollowCount": False,
                  "queryFollowersInfo": False, "queryRelationTokens": False},
            timeout=8,
        ), "profile")
        uid = str(profile.get("squareUid") or "").strip()
        if not re.fullmatch(r"[A-Za-z0-9_-]{5,150}", uid):
            raise ValueError("Creator API supplied no valid squareUid")
        page = _request_data(session.get(
            BASE + POSTS_API,
            params={"targetSquareUid": uid, "timeOffset": now_ms, "filterType": "ALL"},
            timeout=10,
        ), "posts")
    entries = page.get("contents") or []
    if not isinstance(entries, list):
        raise ValueError("Creator API supplied malformed posts")
    posts = [_topic_from_post(post, now_ms) for post in entries[:40]]
    posts = [post for post in posts if post]
    posts.sort(key=lambda item: item["published_at_ms"], reverse=True)
    LOG.info("Creator %s: API contents=%d useful_recent_topics=%d",
             handle, len(entries), len(posts))
    return posts


def recent_creator_topics(limit=8):
    """Retrieve latest public topics; safe empty fallback when the API is blocked."""
    limit = max(1, min(int(limit), 12))
    if time.monotonic() - _CACHE["at"] < 900:
        return _CACHE["topics"][:limit]
    result = []
    now_ms = int(time.time() * 1000)
    for handle in CREATORS:
        try:
            for item in _fetch_creator(handle, now_ms):
                if not any(existing["url"] == item["url"] for existing in result):
                    result.append(item)
        except (requests.RequestException, ValueError, TypeError) as exc:
            LOG.warning("Creator API unavailable for %s: %s", handle, type(exc).__name__)
    result.sort(key=lambda item: item["published_at_ms"], reverse=True)
    _CACHE.update(at=time.monotonic(), topics=result)
    LOG.info("Creator inspiration topics_available=%d", len(result))
    return result[:limit]
