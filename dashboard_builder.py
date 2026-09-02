"""Build dashboard/data.json and a compact dashboard/summary.json."""
from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
from statistics import median
from typing import Optional

from performance_store import build_learning_summary, load_store
from trade_journal import summarize_journal
from runtime import PROJECT_DIR, atomic_write_json

DASHBOARD_DIR = PROJECT_DIR / "dashboard"
SUMMARY_POST_LIMIT = 20
SUMMARY_TICKER_TOP = 25
SUMMARY_TICKER_BOTTOM = 15
SUMMARY_OUTCOME_LIMIT = 20


def _parse(value: str) -> Optional[datetime]:
    try:
        dt = datetime.fromisoformat(str(value))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except (TypeError, ValueError):
        return None


def _safe_int(value) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _compact_milestones(value) -> dict:
    milestones = value if isinstance(value, dict) else {}
    compact = {}
    for key in ("30m", "2h", "6h", "24h"):
        row = milestones.get(key)
        if not isinstance(row, dict):
            continue
        compact[key] = {
            "views": _safe_int(row.get("views")),
            "likes": _safe_int(row.get("likes")),
            "comments": _safe_int(row.get("comments")),
            "quotes": _safe_int(row.get("quotes")),
            "shares": _safe_int(row.get("shares")),
        }
    return compact


def _compact_post(post: Optional[dict]) -> Optional[dict]:
    if not isinstance(post, dict):
        return None
    text = str(post.get("text") or "")
    return {
        "post_id": str(post.get("post_id") or ""),
        "symbol": str(post.get("symbol") or ""),
        "lane": str(post.get("lane") or "UNKNOWN"),
        "direction": str(post.get("direction") or ""),
        "published_at": str(post.get("published_at") or ""),
        "age_hours": post.get("age_hours"),
        "text": text[:800],
        "views": _safe_int(post.get("views")),
        "likes": _safe_int(post.get("likes")),
        "comments": _safe_int(post.get("comments")),
        "quotes": _safe_int(post.get("quotes")),
        "shares": _safe_int(post.get("shares")),
        "milestones": _compact_milestones(post.get("milestones")),
        "writer_source": str(post.get("writer_source") or ""),
        "content_format": str(post.get("content_format") or ""),
        "event_class": str(post.get("event_class") or ""),
        "tracked_from_publish": bool(post.get("tracked_from_publish")),
        "learning_eligible": bool(post.get("learning_eligible", True)),
    }


def _compact_outcome(row: dict) -> dict:
    if not isinstance(row, dict):
        return {}
    return {
        "setup_id": str(row.get("setup_id") or ""),
        "source_post_id": str(row.get("source_post_id") or ""),
        "symbol": str(row.get("symbol") or ""),
        "direction": str(row.get("direction") or ""),
        "lane": str(row.get("lane") or ""),
        "published_at": str(row.get("published_at") or ""),
        "writer_source": str(row.get("writer_source") or ""),
        "status": str(row.get("status") or ""),
        "decision_mode": str(row.get("decision_mode") or ""),
        "public_decision_mode": str(row.get("public_decision_mode") or ""),
        "trade_state": str(row.get("trade_state") or ""),
        "entry": row.get("entry"),
        "entry_zone_low": row.get("entry_zone_low"),
        "entry_zone_high": row.get("entry_zone_high"),
        "stop": row.get("stop"),
        "tp1": row.get("tp1"),
        "tp2": row.get("tp2"),
        "tp3": row.get("tp3"),
        "rr_tp1": row.get("rr_tp1"),
        "rr_tp2": row.get("rr_tp2"),
        "rr_tp3": row.get("rr_tp3"),
        "public_risk_pct": row.get("public_risk_pct"),
        "exposed_targets": list(row.get("exposed_targets") or []),
        "entry_confirmed": bool(row.get("entry_confirmed")),
        "hits": row.get("hits") if isinstance(row.get("hits"), dict) else {},
        "hit_at": row.get("hit_at") if isinstance(row.get("hit_at"), dict) else {},
        "followups": list(row.get("followups") or [])[-5:],
        "close_reason": str(row.get("close_reason") or ""),
        "closed_at": str(row.get("closed_at") or ""),
    }


def build_dashboard_payload() -> dict:
    store = load_store()
    now = datetime.now(timezone.utc)
    items = [item for item in store.get("posts", {}).values() if isinstance(item, dict)]
    items.sort(key=lambda item: str(item.get("published_at") or ""), reverse=True)

    posts = []
    last_24h = []
    mature_views = []
    for item in items:
        dt = _parse(item.get("published_at", ""))
        stats = item.get("stats") if isinstance(item.get("stats"), dict) else {}
        age_h = (now - dt).total_seconds() / 3600.0 if dt else None
        if age_h is not None and age_h <= 24:
            last_24h.append(item)
        if age_h is not None and age_h >= 6:
            mature_views.append(_safe_int(stats.get("views")))
        posts.append(
            {
                "post_id": str(item.get("post_id") or ""),
                "symbol": str(item.get("symbol") or ""),
                "lane": str(item.get("lane") or "UNKNOWN"),
                "direction": str(item.get("direction") or ""),
                "published_at": str(item.get("published_at") or ""),
                "age_hours": round(age_h, 2) if age_h is not None else None,
                "text": str(item.get("text") or ""),
                "image_url": str(item.get("image_url") or ""),
                "views": _safe_int(stats.get("views")),
                "likes": _safe_int(stats.get("likes")),
                "comments": _safe_int(stats.get("comments")),
                "quotes": _safe_int(stats.get("quotes")),
                "shares": _safe_int(stats.get("shares")),
                "milestones": item.get("milestones") or {},
                "scores": item.get("scores") or {},
                "market": item.get("market") or {},
                "adaptive": item.get("adaptive") or {},
                "writer_source": str(item.get("writer_source") or ""),
                "content_format": str(item.get("content_format") or ""),
                "event_class": str(item.get("event_class") or ""),
                "tracked_from_publish": bool(item.get("tracked_from_publish")),
                "learning_eligible": bool(item.get("learning_eligible", True)),
            }
        )

    learning = build_learning_summary(store)
    outcomes = summarize_journal()
    mature_med = float(median(mature_views)) if mature_views else 0.0
    best = max(posts, key=lambda post: post["views"], default=None)
    overview = {
        "posts_24h": len(last_24h),
        "views_on_24h_posts": sum(_safe_int((item.get("stats") or {}).get("views")) for item in last_24h),
        "median_views_6h_plus": round(mature_med, 1),
        "tracked_posts": len(posts),
        "posts_300_plus": sum(1 for post in posts if post["views"] >= 300),
        "posts_500_plus": sum(1 for post in posts if post["views"] >= 500),
        "posts_1000_plus": sum(1 for post in posts if post["views"] >= 1000),
        "best_post": best,
    }
    return {
        "meta": {
            "generated_at": now.isoformat(),
            "profile_uid": store.get("profile_uid", ""),
            "learning_only": learning.get("learning_only", True),
            "timezone": "UTC+3",
        },
        "overview": overview,
        "learning": learning,
        "outcomes": outcomes,
        "posts": posts[:500],
    }


def build_summary_payload(payload: dict) -> dict:
    """Return a small, read-only analytics snapshot for external readers/tools."""
    learning = payload.get("learning") if isinstance(payload.get("learning"), dict) else {}
    tickers = list(learning.get("tickers") or [])
    top = tickers[:SUMMARY_TICKER_TOP]
    bottom = list(reversed(tickers[-SUMMARY_TICKER_BOTTOM:])) if tickers else []

    overview = dict(payload.get("overview") or {})
    overview["best_post"] = _compact_post(overview.get("best_post"))

    outcomes = payload.get("outcomes") if isinstance(payload.get("outcomes"), dict) else {}
    compact_outcomes = {
        key: outcomes.get(key, 0)
        for key in (
            "total",
            "quarantined",
            "entered",
            "active",
            "closed",
            "tp1_hits",
            "tp3_hits",
            "stops",
            "target_complete",
            "tp1_rate",
            "tp3_rate",
            "followups",
        )
    }
    compact_outcomes["recent"] = [
        _compact_outcome(row)
        for row in list(outcomes.get("recent") or [])[:SUMMARY_OUTCOME_LIMIT]
        if isinstance(row, dict)
    ]

    return {
        "meta": {
            **dict(payload.get("meta") or {}),
            "summary_version": 1,
            "source": "dashboard/data.json",
            "note": "Compact analytics snapshot for external readers; the web dashboard still uses data.json.",
        },
        "overview": overview,
        "recent_posts": [
            compact
            for post in list(payload.get("posts") or [])[:SUMMARY_POST_LIMIT]
            if (compact := _compact_post(post)) is not None
        ],
        "learning": {
            "learning_only": learning.get("learning_only", True),
            "account_median_24h": learning.get("account_median_24h", 0),
            "mature_samples": learning.get("mature_samples", 0),
            "tickers_top": top,
            "tickers_bottom": bottom,
            "lanes": list(learning.get("lanes") or []),
            "hours": list(learning.get("hours") or []),
            "authors": list(learning.get("authors") or []),
            "formats": list(learning.get("formats") or []),
            "event_classes": list(learning.get("event_classes") or []),
            "directions": list(learning.get("directions") or []),
        },
        "outcomes": compact_outcomes,
    }


def build_dashboard_data(path: Optional[Path] = None) -> Path:
    DASHBOARD_DIR.mkdir(parents=True, exist_ok=True)
    output = path or (DASHBOARD_DIR / "data.json")
    payload = build_dashboard_payload()
    atomic_write_json(output, payload)
    atomic_write_json(DASHBOARD_DIR / "summary.json", build_summary_payload(payload))
    return output


if __name__ == "__main__":
    print(build_dashboard_data())
