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
from trade_journal import load_journal


def _bool(name: str, default: str = "1") -> bool:
    return os.getenv(name, default).strip().lower() in {"1", "true", "yes", "on"}


LOCAL_TZ_OFFSET = int(os.getenv("ANALYTICS_TZ_OFFSET", "3"))
LOOKBACK_DAYS = max(3, min(int(os.getenv("ADAPTIVE_LOOKBACK_DAYS", "7")), 60))
HALF_LIFE_DAYS = max(2.0, min(float(os.getenv("ADAPTIVE_HALF_LIFE_DAYS", "3")), 30.0))
MAX_TOTAL = max(4.0, min(float(os.getenv("ADAPTIVE_MAX_TOTAL", "14")), 25.0))
MAX_TICKER = max(2.0, min(float(os.getenv("ADAPTIVE_TICKER_MAX", "10")), 15.0))
MAX_HOUR = max(1.0, min(float(os.getenv("ADAPTIVE_HOUR_MAX", "5")), 10.0))
MAX_LANE = max(0.5, min(float(os.getenv("ADAPTIVE_LANE_MAX", "2.5")), 6.0))
MAX_BREAKOUT = max(0.0, min(float(os.getenv("ADAPTIVE_BREAKOUT_MAX", "3")), 6.0))
MAX_EXPLORATION = max(0.0, min(float(os.getenv("ADAPTIVE_EXPLORATION_MAX", "2.5")), 5.0))
MAX_SATURATION = max(0.0, min(float(os.getenv("ADAPTIVE_SATURATION_MAX", "5")), 10.0))
MAX_OUTCOME = max(0.0, min(float(os.getenv("ADAPTIVE_OUTCOME_MAX", "5")), 8.0))
OUTCOME_PRIOR = max(2.0, min(float(os.getenv("ADAPTIVE_OUTCOME_PRIOR", "6")), 20.0))
OUTCOME_MIN_CLOSED = max(1, min(int(os.getenv("ADAPTIVE_OUTCOME_MIN_CLOSED", "3")), 20))
MAX_CONTENT_TOTAL = max(2.0, min(float(os.getenv("ADAPTIVE_CONTENT_MAX_TOTAL", "9")), 14.0))
MAX_FORMAT = max(1.0, min(float(os.getenv("ADAPTIVE_FORMAT_MAX", "5")), 8.0))
MAX_WRITER = max(0.5, min(float(os.getenv("ADAPTIVE_WRITER_MAX", "2.5")), 5.0))
MAX_EVENT_CLASS = max(0.5, min(float(os.getenv("ADAPTIVE_EVENT_CLASS_MAX", "2")), 4.0))
MAX_DIRECTION = max(0.0, min(float(os.getenv("ADAPTIVE_DIRECTION_MAX", "1.5")), 3.0))


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


@dataclass(frozen=True)
class ContentPerformanceAdjustment:
    enabled: bool
    total: float
    format_component: float
    writer_component: float
    event_component: float
    direction_component: float
    format_samples: int
    writer_samples: int
    event_samples: int
    direction_samples: int
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
    # Early feedback is converted to a conservative 24h-equivalent. It reacts
    # to failing formats within hours while giving mature 24h data precedence.
    # Calibrated on the account's tracked history: most Square distribution is
    # delivered early. Large generic multipliers (for example 30m x5) grossly
    # overstate weak fresh posts and poison the feedback loop.
    for label, factor in (("6h", 1.04), ("2h", 1.12), ("30m", 1.25)):
        if isinstance(milestones.get(label), dict):
            try:
                return float(milestones[label].get("views", 0) or 0) * factor
            except (TypeError, ValueError):
                pass
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
        if not item.get("learning_eligible", True):
            continue
        published = _parse_dt(item.get("published_at", ""))
        if not published or published < cutoff:
            continue
        views = _metric(item, now)
        if views is None:
            continue
        result.append({"item": item, "published": published, "views": views, "weight": _decay_weight(published, now)})
    return result


def score_content_performance(
    *,
    lane: str,
    content_format: str,
    writer_source: str,
    event_class: str,
    direction: str,
    now: Optional[datetime] = None,
) -> ContentPerformanceAdjustment:
    """Score the actual editorial attributes of a generated draft.

    Candidate-market ranking cannot know the eventual format or writer. This
    second bounded layer runs after copy generation, so stored format/writer
    analytics finally influence which valid draft consumes the slot.
    """
    now = now or datetime.now(timezone.utc)
    enabled = _bool("ENABLE_ADAPTIVE_RANKING", "1") and not _bool("LEARNING_ONLY", "0")
    if not enabled:
        return ContentPerformanceAdjustment(False, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, "content adaptive disabled")
    rows = _rows(load_store(), now)
    minimum = max(30, int(os.getenv("ADAPTIVE_CONTENT_MIN_SAMPLES", "60")))
    if len(rows) < minimum:
        return ContentPerformanceAdjustment(False, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, f"insufficient content samples={len(rows)}")

    baseline = _weighted_median((row["views"], row["weight"]) for row in rows)
    lane_name = str(lane or "").upper()
    fmt = str(content_format or "")
    writer = str(writer_source or "")
    event = str(event_class or "")
    side = str(direction or "").upper()
    lane_rows = [row for row in rows if str(row["item"].get("lane") or "").upper() == lane_name]

    format_rows = [row for row in lane_rows if str(row["item"].get("content_format") or "") == fmt]
    writer_rows = [row for row in lane_rows if str(row["item"].get("writer_source") or "") == writer]
    event_rows = [row for row in lane_rows if str(row["item"].get("event_class") or "") == event]
    direction_rows = [row for row in lane_rows if str(row["item"].get("direction") or "").upper() == side]

    _, format_comp, format_n = _affinity(format_rows, baseline, prior=8.0, max_component=MAX_FORMAT)
    _, writer_comp, writer_n = _affinity(writer_rows, baseline, prior=14.0, max_component=MAX_WRITER)
    _, event_comp, event_n = _affinity(event_rows, baseline, prior=18.0, max_component=MAX_EVENT_CLASS)
    _, direction_comp, direction_n = _affinity(direction_rows, baseline, prior=24.0, max_component=MAX_DIRECTION)
    total = max(-MAX_CONTENT_TOTAL, min(MAX_CONTENT_TOTAL, format_comp + writer_comp + event_comp + direction_comp))
    reason = (
        f"format={fmt}/n{format_n} ({format_comp:+.1f}), writer={writer}/n{writer_n} ({writer_comp:+.1f}), "
        f"event={event}/n{event_n} ({event_comp:+.1f}), direction={side}/n{direction_n} ({direction_comp:+.1f}), "
        f"baseline={baseline:.1f}"
    )
    return ContentPerformanceAdjustment(
        True, round(total, 2), round(format_comp, 2), round(writer_comp, 2),
        round(event_comp, 2), round(direction_comp, 2), format_n, writer_n,
        event_n, direction_n, round(baseline, 2), reason,
    )


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


def _outcome_value(trade: dict) -> Optional[float]:
    """Map a verified closed public setup to a bounded quality value.

    Full TP3 completion is strongest; reaching TP1/TP2 before a later stop still
    earns partial credit. Pure stops earn zero. Expired/manual-review rows are not
    treated as wins or losses because they do not prove a tradable outcome.
    """
    if not isinstance(trade, dict) or int(trade.get("tracking_version") or 0) < 2:
        return None
    if not bool(trade.get("public_plan_complete")):
        return None
    status = str(trade.get("status") or "")
    close_reason = str(trade.get("close_reason") or "")
    if status != "closed" or close_reason not in {"stop", "public_targets_complete"}:
        return None
    hits = trade.get("hits") if isinstance(trade.get("hits"), dict) else {}
    if hits.get("tp3"):
        return 1.0
    if hits.get("tp2"):
        return 0.70
    if hits.get("tp1"):
        return 0.40
    if hits.get("stop"):
        return 0.0
    return None


def _outcome_quality(target: str, *, plan_valid: bool, now: datetime) -> tuple[float, float, int, int]:
    """Return (quality affinity, component, symbol_n, global_n).

    Reach and trade quality stay separate. This component is applied only when
    the candidate actually exposes a tradable plan; observation-only EVENT posts
    keep their reach score untouched. A Bayesian-style prior prevents a few early
    outcomes from blacklisting a ticker.
    """
    if not plan_valid or MAX_OUTCOME <= 0:
        return 50.0, 0.0, 0, 0
    try:
        journal = load_journal()
    except Exception:
        return 50.0, 0.0, 0, 0
    rows = []
    cutoff = now - timedelta(days=LOOKBACK_DAYS)
    for trade in (journal.get("trades") or {}).values():
        value = _outcome_value(trade)
        if value is None:
            continue
        published = _parse_dt(trade.get("published_at", ""))
        if not published or published < cutoff:
            continue
        sym = _symbol(trade)
        rows.append((sym, value, _decay_weight(published, now)))
    if len(rows) < OUTCOME_MIN_CLOSED:
        return 50.0, 0.0, 0, len(rows)

    def weighted_mean(items: list[tuple[str, float, float]]) -> float:
        denom = sum(weight for _, _, weight in items)
        return sum(value * weight for _, value, weight in items) / max(denom, 1e-9)

    global_mean = weighted_mean(rows)
    symbol_rows = [row for row in rows if row[0] == target]
    symbol_n = len(symbol_rows)
    if symbol_rows:
        symbol_mean = weighted_mean(symbol_rows)
        confidence = symbol_n / (symbol_n + OUTCOME_PRIOR)
        mean = global_mean + (symbol_mean - global_mean) * confidence
    else:
        mean = global_mean

    # 0.45 is deliberately not a required win rate. Partial TP progress has value,
    # and the component is a soft nudge rather than a hard profitability claim.
    raw_affinity = 50.0 + (mean - 0.45) * 90.0
    global_confidence = len(rows) / (len(rows) + 12.0)
    affinity = 50.0 + (max(10.0, min(90.0, raw_affinity)) - 50.0) * global_confidence
    component = max(-MAX_OUTCOME, min(MAX_OUTCOME, (affinity - 50.0) / 40.0 * MAX_OUTCOME))
    return round(affinity, 2), round(component, 2), symbol_n, len(rows)


def score_adaptive(
    *,
    symbol: str,
    lane: str,
    live_score: float,
    event_class: str = "",
    micro_score: float = 50.0,
    plan_valid: Optional[bool] = None,
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

    # Existing callers do not all pass plan_valid yet. TRADE lane is always a
    # validated public plan by construction; EVENT defaults to reach-only unless
    # a caller explicitly marks its plan valid. This preserves EVENT reach.
    effective_plan_valid = (lane_name == "TRADE") if plan_valid is None else bool(plan_valid)
    outcome_aff, outcome_comp, outcome_n, outcome_global_n = _outcome_quality(
        target, plan_valid=effective_plan_valid, now=now
    )

    total = ticker_comp + hour_comp + lane_comp + breakout_comp + exploration + saturation + outcome_comp
    total = max(-MAX_TOTAL, min(MAX_TOTAL, total))
    reason = (
        f"ticker={ticker_aff:.1f}/n{ticker_n} ({ticker_comp:+.1f}), "
        f"hour{local_hour}={hour_aff:.1f}/n{hour_n} ({hour_comp:+.1f}), "
        f"lane={lane_aff:.1f}/n{lane_n} ({lane_comp:+.1f}), breakout={breakout_comp:+.1f}, "
        f"explore={exploration:+.1f}, saturation={saturation:+.1f}, "
        f"outcome={outcome_aff:.1f}/n{outcome_n}/g{outcome_global_n} ({outcome_comp:+.1f}), baseline={baseline:.1f}"
    )
    return AdaptiveAdjustment(
        True,
        round(total, 2), round(ticker_comp, 2), round(hour_comp, 2), round(lane_comp, 2),
        round(breakout_comp, 2), round(exploration, 2), round(saturation, 2),
        ticker_aff, hour_aff, lane_aff, ticker_n, hour_n, lane_n, recent_symbol_posts,
        round(baseline, 2), reason,
    )
