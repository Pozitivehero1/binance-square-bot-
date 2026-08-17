"""Adaptive performance layer for Binance Square candidate ranking.

The market engine remains the source of truth. Historical performance can only
nudge the ranking, never create a trade or bypass market-quality gates.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import math
import os
from statistics import median
from typing import Iterable, Optional

from performance_store import load_store


def _bool(name: str, default: str = "1") -> bool:
    return os.getenv(name, default).strip().lower() in {"1", "true", "yes", "on"}


LOCAL_TZ_OFFSET = int(os.getenv("ANALYTICS_TZ_OFFSET", "3"))
LOOKBACK_DAYS = max(3, min(int(os.getenv("ADAPTIVE_LOOKBACK_DAYS", "14")), 60))
HALF_LIFE_DAYS = max(2.0, min(float(os.getenv("ADAPTIVE_HALF_LIFE_DAYS", "7")), 30.0))
MAX_TOTAL = max(4.0, min(float(os.getenv("ADAPTIVE_MAX_TOTAL", "14")), 25.0))
MAX_TICKER = max(2.0, min(float(os.getenv("ADAPTIVE_TICKER_MAX", "10")), 15.0))
MAX_HOUR = max(1.0, min(float(os.getenv("ADAPTIVE_HOUR_MAX", "5")), 10.0))
MAX_LANE = max(0.5, min(float(os.getenv("ADAPTIVE_LANE_MAX", "2.5")), 6.0))
MAX_BREAKOUT = max(0.0, min(float(os.getenv("ADAPTIVE_BREAKOUT_MAX", "3")), 6.0))
MAX_EXPLORATION = max(0.0, min(float(os.getenv("ADAPTIVE_EXPLORATION_MAX", "2.5")), 5.0))
MAX_SATURATION = max(0.0, min(float(os.getenv("ADAPTIVE_SATURATION_MAX", "5")), 10.0))


@dataclass(frozen=True)
class AdaptiveAdjustment:
    enabled: bool
    total: float
    ticker_component: float
    hour_component: float
    lane_component: float
    breakout_component: float
    exploration_component: float
    saturation_component: float
    ticker_affinity: float
    hour_affinity: float
    lane_affinity: float
    ticker_samples: int
    hour_samples: int
    lane_samples: int
    recent_symbol_posts: int
    baseline_views: float
    reason: str


def _parse_dt(value: str) -> Optional[datetime]:
    try:
        dt = datetime.fromisoformat(str(value or ""))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except (TypeError, ValueError):
        return None


def _metric(item: dict, now: datetime) -> Optional[float]:
    milestones = item.get("milestones") if isinstance(item.get("milestones"), dict) else {}
    if isinstance(milestones.get("24h"), dict):
        try:
            return float(milestones["24h"].get("views", 0) or 0)
        except (TypeError, ValueError):
            return None
    published = _parse_dt(item.get("published_at", ""))
    if not published or (now - published).total_seconds() < 24 * 3600:
        return None
    stats = item.get("stats") if isinstance(item.get("stats"), dict) else {}
    try:
        return float(stats.get("views", 0) or 0)
    except (TypeError, ValueError):
        return None


def _weighted_median(values: Iterable[tuple[float, float]]) -> float:
    rows = sorted((float(v), max(0.0, float(w))) for v, w in values if w > 0)
    if not rows:
        return 0.0
    total = sum(w for _, w in rows)
    midpoint = total / 2.0
    acc = 0.0
    for value, weight in rows:
        acc += weight
        if acc >= midpoint:
            return value
    return rows[-1][0]


def _decay_weight(published: datetime, now: datetime) -> float:
    age_days = max(0.0, (now - published).total_seconds() / 86400.0)
    return 0.5 ** (age_days / HALF_LIFE_DAYS)


def _rows(store: dict, now: datetime) -> list[dict]:
    cutoff = now - timedelta(days=LOOKBACK_DAYS)
    result = []
    for item in store.get("posts", {}).values():
        if not isinstance(item, dict):
            continue
        published = _parse_dt(item.get("published_at", ""))
        if not published or published < cutoff:
            continue
        views = _metric(item, now)
        if views is None:
            continue
        result.append({"item": item, "published": published, "views": views, "weight": _decay_weight(published, now)})
    return result


def _affinity(group: list[dict], baseline: float, *, prior: float, max_component: float) -> tuple[float, float, int]:
    if not group or baseline <= 0:
        return 50.0, 0.0, 0
    med = _weighted_median((row["views"], row["weight"]) for row in group)
    ratio = max(0.15, med / max(1.0, baseline))
    raw_affinity = max(10.0, min(95.0, 50.0 + math.log(ratio, 2) * 22.0))
    n = len(group)
    confidence = n / (n + max(1.0, prior))
    affinity = 50.0 + (raw_affinity - 50.0) * confidence
    component = max(-max_component, min(max_component, (affinity - 50.0) / 45.0 * max_component))
    return round(affinity, 2), round(component, 2), n


def _relative_breakout_rate(group: list[dict], baseline: float) -> float:
    if not group or baseline <= 0:
        return 0.0
    threshold = max(160.0, baseline * 2.0)
    total_weight = sum(row["weight"] for row in group)
    if total_weight <= 0:
        return 0.0
    return sum(row["weight"] for row in group if row["views"] >= threshold) / total_weight


def _symbol(item: dict) -> str:
    value = str(item.get("symbol") or "").upper().strip()
    return value[:-4] if value.endswith("USDT") and len(value) > 4 else value


def score_adaptive(
    *,
    symbol: str,
    lane: str,
    live_score: float,
    event_class: str = "",
    micro_score: float = 50.0,
    now: Optional[datetime] = None,
) -> AdaptiveAdjustment:
    now = now or datetime.now(timezone.utc)
    enabled = _bool("ENABLE_ADAPTIVE_RANKING", "1") and not _bool("LEARNING_ONLY", "0")
    if not enabled:
        return AdaptiveAdjustment(False, 0, 0, 0, 0, 0, 0, 0, 50, 50, 50, 0, 0, 0, 0, 0, "adaptive disabled")

    store = load_store()
    rows = _rows(store, now)
    if len(rows) < max(40, int(os.getenv("ADAPTIVE_MIN_MATURE_SAMPLES", "80"))):
        return AdaptiveAdjustment(False, 0, 0, 0, 0, 0, 0, 0, 50, 50, 50, 0, 0, 0, 0, 0, f"insufficient mature samples={len(rows)}")

    baseline = _weighted_median((row["views"], row["weight"]) for row in rows)
    target = str(symbol or "").upper().replace("USDT", "")
    lane_name = str(lane or "").upper()
    local_hour = (now.hour + LOCAL_TZ_OFFSET) % 24

    ticker_rows = [row for row in rows if _symbol(row["item"]) == target]
    hour_rows = [row for row in rows if (row["published"].hour + LOCAL_TZ_OFFSET) % 24 == local_hour]
    lane_rows = [row for row in rows if str(row["item"].get("lane") or "UNKNOWN").upper() == lane_name]

    ticker_aff, ticker_comp, ticker_n = _affinity(ticker_rows, baseline, prior=5.0, max_component=MAX_TICKER)
    hour_aff, hour_comp, hour_n = _affinity(hour_rows, baseline, prior=12.0, max_component=MAX_HOUR)
    lane_aff, lane_comp, lane_n = _affinity(lane_rows, baseline, prior=35.0, max_component=MAX_LANE)

    global_breakout = _relative_breakout_rate(rows, baseline)
    ticker_breakout = _relative_breakout_rate(ticker_rows, baseline)
    breakout_conf = min(1.0, ticker_n / 8.0)
    breakout_comp = (ticker_breakout - global_breakout) * 14.0 * breakout_conf
    breakout_comp = max(-MAX_BREAKOUT, min(MAX_BREAKOUT, breakout_comp))

    # Exploration is earned only by a live opportunity, never by historical ignorance alone.
    exploration = 0.0
    if ticker_n < 3 and (live_score >= 68.0 or micro_score >= 74.0 or event_class in {"fresh_event", "audience_breakout"}):
        live_strength = max(float(live_score), float(micro_score))
        exploration = min(MAX_EXPLORATION, max(0.0, (live_strength - 68.0) / 12.0 * MAX_EXPLORATION))

    # Avoid learning "post the same winner forever". More than two posts of the
    # same symbol in 48h receives a gradually stronger penalty.
    recent_cutoff = now - timedelta(hours=48)
    recent_symbol_posts = 0
    for item in store.get("posts", {}).values():
        if not isinstance(item, dict) or _symbol(item) != target:
            continue
        published = _parse_dt(item.get("published_at", ""))
        if published and published >= recent_cutoff:
            recent_symbol_posts += 1
    saturation = -min(MAX_SATURATION, max(0, recent_symbol_posts - 2) * 1.15)

    total = ticker_comp + hour_comp + lane_comp + breakout_comp + exploration + saturation
    total = max(-MAX_TOTAL, min(MAX_TOTAL, total))
    reason = (
        f"ticker={ticker_aff:.1f}/n{ticker_n} ({ticker_comp:+.1f}), "
        f"hour{local_hour}={hour_aff:.1f}/n{hour_n} ({hour_comp:+.1f}), "
        f"lane={lane_aff:.1f}/n{lane_n} ({lane_comp:+.1f}), breakout={breakout_comp:+.1f}, "
        f"explore={exploration:+.1f}, saturation={saturation:+.1f}, baseline={baseline:.1f}"
    )
    return AdaptiveAdjustment(
        True,
        round(total, 2), round(ticker_comp, 2), round(hour_comp, 2), round(lane_comp, 2),
        round(breakout_comp, 2), round(exploration, 2), round(saturation, 2),
        ticker_aff, hour_aff, lane_aff, ticker_n, hour_n, lane_n, recent_symbol_posts,
        round(baseline, 2), reason,
    )
