"""Build dashboard/data.json from the shadow-learning performance store."""
from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
from statistics import median
from typing import Optional

from performance_store import build_learning_summary, load_store
from runtime import PROJECT_DIR, atomic_write_json

DASHBOARD_DIR = PROJECT_DIR / "dashboard"


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
                "content_format": str(item.get("content_format") or ""),
                "event_class": str(item.get("event_class") or ""),
                "tracked_from_publish": bool(item.get("tracked_from_publish")),
            }
        )

    learning = build_learning_summary(store)
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
        "posts": posts[:500],
    }


def build_dashboard_data(path: Optional[Path] = None) -> Path:
    DASHBOARD_DIR.mkdir(parents=True, exist_ok=True)
    output = path or (DASHBOARD_DIR / "data.json")
    atomic_write_json(output, build_dashboard_payload())
    return output


if __name__ == "__main__":
    print(build_dashboard_data())
