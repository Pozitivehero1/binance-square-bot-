"""Persistent adaptive-learning store for real Binance Square post performance."""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone
import logging
import math
import os
from statistics import median
from typing import Any, Dict, Iterable, Optional

from runtime import atomic_write_json, resolve_state_file
from square_public_stats import PublicPostStats

logger = logging.getLogger(__name__)
ANALYTICS_FILE = resolve_state_file("ANALYTICS_FILE", "performance_history.json")
SCHEMA_VERSION = 2
MAX_POSTS = max(100, int(os.getenv("ANALYTICS_MAX_POSTS", "1200")))
LOCAL_TZ_OFFSET_HOURS = int(os.getenv("ANALYTICS_TZ_OFFSET", "3"))

MILESTONES = {
    "30m": (20, 70),
    "2h": (90, 210),
    "6h": (300, 540),
    "24h": (1200, 1860),
}


def reach_recovery_state(now: Optional[datetime] = None) -> tuple[bool, float, float]:
    """Return (enabled, rolling_24h_views, seven-day daily baseline).

    The state is data-driven and fail-open until enough history exists. The
    current day enters recovery below 82% of the preceding six complete daily
    buckets, with a small hysteresis margin supplied by the stricter threshold.
    """
    now = now or _now()
    rows: list[tuple[datetime, dict]] = []
    for item in load_store().get("posts", {}).values():
        if not isinstance(item, dict):
            continue
        published = _parse_dt(item.get("published_at", ""))
        if published and now - timedelta(days=7) <= published <= now:
            rows.append((published, item))

    def projected(item: dict) -> float:
        milestones = item.get("milestones") if isinstance(item.get("milestones"), dict) else {}
        for label, factor in (("24h", 1.0), ("6h", 1.04), ("2h", 1.12), ("30m", 1.25)):
            row = milestones.get(label)
            if isinstance(row, dict):
                try:
                    return float(row.get("views", 0) or 0) * factor
                except (TypeError, ValueError):
                    pass
        stats = item.get("stats") if isinstance(item.get("stats"), dict) else {}
        try:
            return float(stats.get("views", 0) or 0) * 1.25
        except (TypeError, ValueError):
            return 0.0

    current = sum(projected(item) for published, item in rows if published >= now - timedelta(hours=24))
    buckets = []
    for day in range(1, 7):
        high = now - timedelta(days=day)
        low = high - timedelta(days=1)
        total = 0.0
        for published, item in rows:
            if not low <= published < high:
                continue
            milestone = item.get("milestones") if isinstance(item.get("milestones"), dict) else {}
            row = milestone.get("24h")
            if isinstance(row, dict):
                try:
                    total += float(row.get("views", 0) or 0)
                except (TypeError, ValueError):
                    pass
        if total > 0:
            buckets.append(total)
    if len(buckets) < 3:
        return False, round(current, 1), 0.0
    baseline = float(median(buckets))
    return current < baseline * 0.82, round(current, 1), round(baseline, 1)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso_from_ms(value: int) -> str:
    if not value:
        return ""
    return datetime.fromtimestamp(value / 1000.0, tz=timezone.utc).isoformat()


def _parse_dt(value: str) -> Optional[datetime]:
    try:
        parsed = datetime.fromisoformat(str(value))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except (TypeError, ValueError):
        return None


def _blank_store(profile_uid: str = "") -> dict:
    return {
        "schema_version": SCHEMA_VERSION,
        "profile_uid": profile_uid,
        "updated_at": _now().isoformat(),
        "posts": {},
    }


def load_store() -> dict:
    if not ANALYTICS_FILE.exists():
        return _blank_store()
    try:
        import json
        payload = json.loads(ANALYTICS_FILE.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            return _blank_store()
        if not isinstance(payload.get("posts"), dict):
            payload["posts"] = {}
        payload.setdefault("schema_version", SCHEMA_VERSION)
        payload.setdefault("profile_uid", "")
        return payload
    except Exception as exc:
        logger.warning("Analytics store load failed: %s", exc)
        return _blank_store()


def save_store(store: dict) -> None:
    posts = store.get("posts") if isinstance(store.get("posts"), dict) else {}
    if len(posts) > MAX_POSTS:
        ranked = sorted(
            posts.items(),
            key=lambda kv: str(kv[1].get("published_at") or ""),
            reverse=True,
        )[:MAX_POSTS]
        store["posts"] = dict(ranked)
    store["schema_version"] = SCHEMA_VERSION
    store["updated_at"] = _now().isoformat()
    atomic_write_json(ANALYTICS_FILE, store)


def _normalize_symbol(symbol: str) -> str:
    value = str(symbol or "").upper().strip()
    if value.endswith("USDT") and len(value) > 4:
        value = value[:-4]
    return value


def record_publication(
    *,
    post_id: str,
    symbol: str,
    market_symbol: str,
    text: str,
    lane: str,
    direction: str,
    content_format: str,
    visual_style: str,
    event_class: str,
    writer_source: str,
    signal_type: str = "",
    opportunity_score: float = 0.0,
    audience_demand: float = 0.0,
    attention_score: float = 0.0,
    micro_freshness: float = 0.0,
    w2e_market_score: float = 0.0,
    change_5m: float = 0.0,
    change_15m: float = 0.0,
    volume_5m: float = 0.0,
    volume_15m: float = 0.0,
    public_rr: Optional[float] = None,
    decision_mode: str = "",
    adaptive_total: float = 0.0,
    ticker_affinity: float = 50.0,
    hour_affinity: float = 50.0,
    lane_affinity: float = 50.0,
    adaptive_reason: str = "",
    w2e_proxy_score: float = 0.0,
    learning_eligible: bool = True,
) -> None:
    store = load_store()
    posts = store.setdefault("posts", {})
    now = _now()
    key = str(post_id or f"local-{int(now.timestamp() * 1000)}")
    previous = posts.get(key) if isinstance(posts.get(key), dict) else {}
    previous.update(
        {
            "post_id": str(post_id or ""),
            "local_key": key,
            "symbol": _normalize_symbol(symbol),
            "market_symbol": str(market_symbol or "").upper(),
            "text": str(text or ""),
            "published_at": previous.get("published_at") or now.isoformat(),
            "tracked_from_publish": True,
            "source": "bot",
            "lane": str(lane or "").upper(),
            "direction": str(direction or "").upper(),
            "content_format": str(content_format or ""),
            "visual_style": str(visual_style or ""),
            "event_class": str(event_class or ""),
            "writer_source": str(writer_source or ""),
            "signal_type": str(signal_type or ""),
            "learning_eligible": bool(learning_eligible),
            "scores": {
                "opportunity": round(float(opportunity_score or 0.0), 2),
                "audience_demand": round(float(audience_demand or 0.0), 2),
                "attention": round(float(attention_score or 0.0), 2),
                "micro_freshness": round(float(micro_freshness or 0.0), 2),
                "w2e_market": round(float(w2e_market_score or 0.0), 2),
            },
            "market": {
                "change_5m": round(float(change_5m or 0.0), 4),
                "change_15m": round(float(change_15m or 0.0), 4),
                "volume_5m": round(float(volume_5m or 0.0), 4),
                "volume_15m": round(float(volume_15m or 0.0), 4),
                "public_rr": round(float(public_rr), 3) if public_rr is not None else None,
                "decision_mode": str(decision_mode or ""),
            },
            "adaptive": {
                "total": round(float(adaptive_total or 0.0), 2),
                "ticker_affinity": round(float(ticker_affinity or 50.0), 2),
                "hour_affinity": round(float(hour_affinity or 50.0), 2),
                "lane_affinity": round(float(lane_affinity or 50.0), 2),
                "reason": str(adaptive_reason or ""),
                "w2e_proxy": round(float(w2e_proxy_score or 0.0), 2),
            },
            "stats": previous.get("stats") or {},
            "milestones": previous.get("milestones") or {},
        }
    )
    posts[key] = previous
    save_store(store)


def _find_local_match(posts: dict, row: PublicPostStats) -> Optional[str]:
    if row.post_id in posts:
        return row.post_id
    if not row.published_ms:
        return None
    published = datetime.fromtimestamp(row.published_ms / 1000.0, tz=timezone.utc)
    for key, item in posts.items():
        if not isinstance(item, dict) or item.get("post_id"):
            continue
        if _normalize_symbol(item.get("symbol", "")) != _normalize_symbol(row.symbol):
            continue
        local_dt = _parse_dt(item.get("published_at", ""))
        if local_dt and abs((local_dt - published).total_seconds()) <= 300:
            return key
    return None


def _capture_milestones(item: dict, now: datetime, stats: dict) -> None:
    if not item.get("tracked_from_publish"):
        return
    published = _parse_dt(item.get("published_at", ""))
    if not published:
        return
    age_min = max(0.0, (now - published).total_seconds() / 60.0)
    milestones = item.setdefault("milestones", {})
    for label, (low, high) in MILESTONES.items():
        if label in milestones:
            continue
        if low <= age_min <= high:
            milestones[label] = {
                "captured_at": now.isoformat(),
                "age_minutes": round(age_min, 1),
                **stats,
            }


def merge_public_stats(rows: Iterable[PublicPostStats], profile_uid: str = "") -> dict:
    store = load_store()
    if profile_uid:
        store["profile_uid"] = str(profile_uid)
    posts = store.setdefault("posts", {})
    now = _now()
    merged = 0
    for row in rows:
        match_key = _find_local_match(posts, row)
        if match_key and match_key != row.post_id:
            local = posts.pop(match_key)
            local["post_id"] = row.post_id
            local["local_key"] = row.post_id
            posts[row.post_id] = local
        item = posts.get(row.post_id)
        if not isinstance(item, dict):
            item = {
                "post_id": row.post_id,
                "local_key": row.post_id,
                "symbol": _normalize_symbol(row.symbol),
                "market_symbol": "",
                "text": row.text,
                "published_at": _iso_from_ms(row.published_ms),
                "tracked_from_publish": False,
                "source": "public_import",
                "lane": "UNKNOWN",
                "direction": "",
                "content_format": "",
                "visual_style": "",
                "event_class": "",
                "writer_source": "",
                "signal_type": "",
                "learning_eligible": True,
                "scores": {},
                "market": {},
                "adaptive": {},
                "milestones": {},
            }
            posts[row.post_id] = item
        if not item.get("symbol"):
            item["symbol"] = _normalize_symbol(row.symbol)
        if not item.get("text"):
            item["text"] = row.text
        if not item.get("published_at") and row.published_ms:
            item["published_at"] = _iso_from_ms(row.published_ms)
        item["image_url"] = row.image_url
        item["language"] = row.language
        stats = {
            "views": int(row.views),
            "likes": int(row.likes),
            "comments": int(row.comments),
            "quotes": int(row.quotes),
            "shares": int(row.shares),
        }
        item["stats"] = stats
        item["last_stats_at"] = now.isoformat()
        _capture_milestones(item, now, stats)
        merged += 1
    save_store(store)
    return {"merged": merged, "posts": len(posts), "updated_at": store.get("updated_at", "")}


def _metric_views(item: dict) -> Optional[int]:
    milestones = item.get("milestones") if isinstance(item.get("milestones"), dict) else {}
    if isinstance(milestones.get("24h"), dict):
        return int(milestones["24h"].get("views", 0))
    published = _parse_dt(item.get("published_at", ""))
    if published and (_now() - published).total_seconds() >= 24 * 3600:
        stats = item.get("stats") if isinstance(item.get("stats"), dict) else {}
        return int(stats.get("views", 0))
    return None


def _affinity(rows: list[dict], account_median: float) -> dict:
    values = [v for item in rows if (v := _metric_views(item)) is not None]
    if not values:
        return {"posts": 0, "median_views": 0, "avg_views": 0, "breakout_rate": 0, "absolute_300_rate": 0, "affinity": 50}
    med = float(median(values))
    avg = sum(values) / len(values)
    baseline = max(1.0, account_median)
    ratio = med / baseline
    raw = max(10.0, min(95.0, 50.0 + math.log(max(0.15, ratio), 2) * 22.0))
    confidence = min(1.0, len(values) / 8.0)
    score = 50.0 + (raw - 50.0) * confidence
    breakout = sum(1 for v in values if v >= baseline * 2.0) / len(values) * 100.0
    absolute_300 = sum(1 for v in values if v >= 300.0) / len(values) * 100.0
    return {
        "posts": len(values),
        "median_views": round(med, 1),
        "avg_views": round(avg, 1),
        "breakout_rate": round(breakout, 1),
        "absolute_300_rate": round(absolute_300, 1),
        "affinity": round(score, 1),
    }


def build_learning_summary(store: Optional[dict] = None) -> dict:
    store = store or load_store()
    all_posts = [item for item in store.get("posts", {}).values() if isinstance(item, dict)]
    # Outcome follow-ups are tracked for reach in the dashboard, but they must not
    # contaminate ticker/hour/lane priors used to choose fresh market setups.
    posts = [item for item in all_posts if item.get("learning_eligible", True)]
    mature = [v for item in posts if (v := _metric_views(item)) is not None]
    account_median = float(median(mature)) if mature else 0.0

    by_symbol: dict[str, list[dict]] = defaultdict(list)
    by_lane: dict[str, list[dict]] = defaultdict(list)
    by_hour: dict[int, list[dict]] = defaultdict(list)
    by_author: dict[str, list[dict]] = defaultdict(list)
    by_format: dict[str, list[dict]] = defaultdict(list)
    by_event_class: dict[str, list[dict]] = defaultdict(list)
    by_direction: dict[str, list[dict]] = defaultdict(list)
    for item in posts:
        symbol = _normalize_symbol(item.get("symbol", "")) or "UNKNOWN"
        by_symbol[symbol].append(item)
        by_lane[str(item.get("lane") or "UNKNOWN").upper()].append(item)
        by_author[str(item.get("writer_source") or "UNKNOWN")].append(item)
        by_format[str(item.get("content_format") or "UNKNOWN")].append(item)
        by_event_class[str(item.get("event_class") or "UNKNOWN")].append(item)
        by_direction[str(item.get("direction") or "UNKNOWN").upper()].append(item)
        published = _parse_dt(item.get("published_at", ""))
        if published:
            local_hour = (published.hour + LOCAL_TZ_OFFSET_HOURS) % 24
            by_hour[local_hour].append(item)

    tickers = [
        {"symbol": symbol, **_affinity(rows, account_median)}
        for symbol, rows in by_symbol.items()
        if symbol != "UNKNOWN"
    ]
    tickers.sort(key=lambda row: (row["affinity"], row["posts"]), reverse=True)
    lanes = [{"lane": lane, **_affinity(rows, account_median)} for lane, rows in by_lane.items()]
    lanes.sort(key=lambda row: row["affinity"], reverse=True)
    hours = [{"hour": hour, **_affinity(rows, account_median)} for hour, rows in sorted(by_hour.items())]
    authors = [{"author": author, **_affinity(rows, account_median)} for author, rows in by_author.items()]
    authors.sort(key=lambda row: (row["posts"], row["affinity"]), reverse=True)
    formats = [{"format": name, **_affinity(rows, account_median)} for name, rows in by_format.items()]
    formats.sort(key=lambda row: (row["affinity"], row["posts"]), reverse=True)
    event_classes = [{"event_class": name, **_affinity(rows, account_median)} for name, rows in by_event_class.items()]
    event_classes.sort(key=lambda row: (row["affinity"], row["posts"]), reverse=True)
    directions = [{"direction": name, **_affinity(rows, account_median)} for name, rows in by_direction.items()]
    directions.sort(key=lambda row: (row["affinity"], row["posts"]), reverse=True)
    return {
        "learning_only": str(os.getenv("LEARNING_ONLY", "0")).lower() in {"1", "true", "yes"},
        "account_median_24h": round(account_median, 1),
        "mature_samples": len(mature),
        "tickers": tickers,
        "lanes": lanes,
        "hours": hours,
        "authors": authors,
        "formats": formats,
        "event_classes": event_classes,
        "directions": directions,
    }
