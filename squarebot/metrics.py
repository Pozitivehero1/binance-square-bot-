"""Comparable rollout measurements; no forecasts disguised as observed reach."""
from collections import defaultdict
from math import log
from statistics import median

from evidence_metrics import observation, parse_time
from . import PREVIOUS_VERSION, VERSION
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
    current = [p for p in rows if p.get("engine_version") == VERSION]
    previous = [p for p in rows if p.get("engine_version") == PREVIOUS_VERSION]
    kinds = defaultdict(list)
    for row in current:
        kinds[row.get("event_class") or "unknown"].append(row)
    return {
        "version": VERSION, "previous_version": PREVIOUS_VERSION, "window_days": 7,
        "measurement": "Actual 23–25h and 5.5–6.5h observations; missing observations remain missing",
        "current": {label: cohort(current, label) for label in ("6h", "24h")},
        "previous": {label: cohort(previous, label) for label in ("6h", "24h")},
        "by_topic_24h": {kind: cohort(group, "24h") for kind, group in kinds.items()},
        "comparison_ready": cohort(current, "24h")["samples"] >= 20 and cohort(previous, "24h")["samples"] >= 20,
    }


def ranking_lifts(posts, now=None):
    """Use real day-old reads, with small groups pulled back toward the account baseline."""
    now = now or utcnow()
    topics, tickers, samples = defaultdict(list), defaultdict(list), []
    for post in posts:
        date = parse_time(post.get("published_at"))
        if (not str(post.get("engine_version", "")).startswith("v13.")
                or post.get("learning_eligible") is False or date is None
                or not 0 <= (now-date).total_seconds() <= 7*86400):
            continue
        sample = observation(post, "24h")
        if sample is None:
            continue
        views = sample["views"]
        samples.append(views)
        kind = post.get("event_class")
        topics[kind].append(views)
        if kind not in {"news", "market_map", "relative_strength"}:
            tickers[post.get("symbol")].append(views)
    if len(samples) < 20:
        return {}, {}
    baseline = median(samples)

    def adjustments(groups, cap):
        return {key: max(-cap, min(cap, 20*log((median(values)+1)/(baseline+1))))
                * len(values)/(len(values)+10)
                for key, values in groups.items() if key and len(values) >= 5}

    return adjustments(topics, 14), adjustments(tickers, 8)
