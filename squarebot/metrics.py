"""Comparable rollout measurements; no forecasts disguised as observed reach."""
from collections import defaultdict
from statistics import median

from evidence_metrics import observation, parse_time
from .models import utcnow


def cohort(rows, label):
    observed = [o for row in rows if (o := observation(row, label)) is not None]
    views = [o["views"] for o in observed]
    return {
        "posts": len(rows), "samples": len(views),
        "median_views": median(views) if views else None,
        "rate_100_plus": sum(v >= 100 for v in views)/len(views) if views else None,
        "interactions": sum(sum(o.get(k, 0) for k in ("likes","comments","quotes","shares")) for o in observed),
    }


def summarize(posts, now=None):
    now = now or utcnow()
    rows = [p for p in posts if isinstance(p, dict) and p.get("learning_eligible") is not False
            and (date := parse_time(p.get("published_at"))) and 0 <= (now-date).total_seconds() <= 7*86400]
    current = [p for p in rows if str(p.get("engine_version", "")).startswith("v13.")]
    previous = [p for p in rows if not str(p.get("engine_version", "")).startswith("v13.")]
    kinds = defaultdict(list)
    for row in current:
        kinds[row.get("event_class") or "unknown"].append(row)
    return {
        "version": "v13.0", "window_days": 7,
        "measurement": "Actual 23–25h and 5.5–6.5h observations; missing observations remain missing",
        "current": {label: cohort(current, label) for label in ("6h", "24h")},
        "previous": {label: cohort(previous, label) for label in ("6h", "24h")},
        "by_topic_24h": {kind: cohort(group, "24h") for kind, group in kinds.items()},
        "comparison_ready": cohort(current, "24h")["samples"] >= 20 and cohort(previous, "24h")["samples"] >= 20,
    }


def ranking_lift(story, posts):
    """Only the new engine learns its topic preferences; old low reach cannot veto it."""
    current = [p for p in posts if str(p.get("engine_version", "")).startswith("v13.")]
    samples = [o["views"] for p in current if (o := observation(p, "24h")) is not None]
    group = [o["views"] for p in current if p.get("event_class") == story.kind
             and (o := observation(p, "24h")) is not None]
    if len(samples) < 20 or len(group) < 5:
        return 0.0
    # Bounded, shrunk adjustment. This ranks; it never rejects a story.
    return max(-5, min(5, (median(group)-median(samples))/max(10, median(samples))*5))*len(group)/(len(group)+10)
