"""Age-matched observations shared by learning, recovery and presentation.

Missing observations stay missing. Lifetime counters and extrapolated early
views must never stand in for measured 24-hour performance.
"""
from __future__ import annotations

import math
from datetime import datetime, timezone

WINDOWS = {"30m": (25, 45), "2h": (110, 150), "6h": (330, 390), "24h": (1380, 1500)}


def parse_time(value):
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return (dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)).astimezone(timezone.utc)
    except (ValueError, TypeError):
        return None


def observation(post: dict, label: str = "24h") -> dict | None:
    low, high = WINDOWS[label]
    published = parse_time(post.get("published_at"))
    candidates = [(post.get(name) or {}).get(label) for name in ("content_milestones", "milestones")]
    # A current counter is admissible only when its actual capture time is in
    # the requested window. Never infer that time from the date of this query.
    if published and post.get("last_stats_at"):
        candidates.append(dict(post.get("stats") or {}, captured_at=post["last_stats_at"]))
    for row in candidates:
        if not isinstance(row, dict):
            continue
        captured = parse_time(row.get("captured_at"))
        try:
            age = ((captured - published).total_seconds()/60 if captured and published
                   else float(row["age_minutes"]))
            views = float(row["views"])
            if not (math.isfinite(age) and math.isfinite(views) and low <= age <= high and views >= 0):
                continue
            result = dict(row, age_minutes=round(age, 2), views=int(views))
            for name in ("likes", "comments", "quotes", "shares"):
                result[name] = max(0, int(row.get(name, 0) or 0))
            return result
        except (KeyError, ValueError, TypeError, OverflowError):
            continue
    return None


def measured_views(post: dict, label: str = "24h") -> float | None:
    row = observation(post, label)
    return float(row["views"]) if row is not None else None
