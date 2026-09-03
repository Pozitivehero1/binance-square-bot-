"""v11.7 reach-recovery policy.

This layer leaves the market/trade engine intact and changes only bounded
editorial/reach ranking while the account is in a depressed-distribution state.

Activation happens after ``main`` is imported so the policy can replace the
function references that main/event_writer imported directly.
"""
from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
import logging
import os
from statistics import median
from typing import Optional

logger = logging.getLogger(__name__)

# Empirical bootstrap priors from this account's mature history. They are used
# only during recovery and only as small bounded nudges; live learned affinity
# remains the main signal.
_RECOVERY_FORMAT_PRIOR = {
    "event_market_story": 2.8,
    "micro_note": 2.4,
    "event_one_price": 2.3,
    "one_level": 2.0,
    "two_paths": 1.6,
    "event_price_volume": 0.6,
    "market_story": 0.6,
    "event_pulse": 0.3,
    "no_chase": 0.0,
    "event_trade_bridge": -1.8,
    "hot_take": -2.2,
    "volume_read": -2.8,
    "event_no_trade": -3.2,
    "trade_map": -3.2,
    "risk_first": -3.5,
}

_STRONG_HOUR_AFFINITY = 58.0
_WEAK_HOUR_AFFINITY = 43.0
_MIN_HOUR_SAMPLES = 10
_MIN_FORMAT_SAMPLES = 10
_MIN_TICKER_SAMPLES = 5

_ORIGINAL_SCORE_ADAPTIVE = None
_ORIGINAL_SCORE_CONTENT = None
_ORIGINAL_RECOVERY_GATE = None


def configure_environment() -> None:
    """Install v11.7 defaults before adaptive/main modules are imported."""
    os.environ["BOT_VERSION"] = "v11.7"
    # Keep the external ~20 minute trigger untouched. We only increase the
    # influence of proven reach evidence on candidate/draft ranking.
    os.environ["ADAPTIVE_MAX_TOTAL"] = "20"
    os.environ["ADAPTIVE_TICKER_MAX"] = "13"
    os.environ["ADAPTIVE_HOUR_MAX"] = "9"
    os.environ["ADAPTIVE_CONTENT_MAX_TOTAL"] = "13"
    os.environ["ADAPTIVE_FORMAT_MAX"] = "7"
    os.environ["ADAPTIVE_WRITER_MAX"] = "3.5"
    os.environ["ADAPTIVE_EVENT_CLASS_MAX"] = "2.5"
    os.environ["ADAPTIVE_DIRECTION_MAX"] = "1.5"
    os.environ["OUTCOME_POST_STOPS"] = "0"
    os.environ["OUTCOME_POST_PARTIAL_TARGETS"] = "0"


def _parse_dt(value: object) -> Optional[datetime]:
    try:
        dt = datetime.fromisoformat(str(value or ""))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except (TypeError, ValueError):
        return None


def _distribution_health(now: Optional[datetime] = None) -> tuple[float, float, float, int]:
    """Return recent30m median, historical30m median, ratio, recent sample count.

    The recent bucket is intentionally small so the bot reacts within hours when
    Binance stops expanding the first distribution test. The baseline excludes
    the most recent 12 hours to avoid teaching the current slump to itself.
    """
    from performance_store import load_store

    now = now or datetime.now(timezone.utc)
    recent_cutoff = now - timedelta(hours=12)
    baseline_cutoff = now - timedelta(days=7)

    recent: list[float] = []
    baseline: list[float] = []
    for item in load_store().get("posts", {}).values():
        if not isinstance(item, dict) or not item.get("learning_eligible", True):
            continue
        published = _parse_dt(item.get("published_at"))
        if not published or published < baseline_cutoff or published > now:
            continue
        milestones = item.get("milestones") if isinstance(item.get("milestones"), dict) else {}
        row = milestones.get("30m")
        if not isinstance(row, dict):
            continue
        try:
            views = float(row.get("views", 0) or 0)
        except (TypeError, ValueError):
            continue
        if views <= 0:
            continue
        if published >= recent_cutoff:
            recent.append(views)
        else:
            baseline.append(views)

    recent_med = float(median(recent)) if recent else 0.0
    baseline_med = float(median(baseline)) if baseline else 0.0
    ratio = recent_med / baseline_med if recent_med > 0 and baseline_med > 0 else 1.0
    return recent_med, baseline_med, ratio, len(recent)


def _recovery_state(now: Optional[datetime] = None) -> tuple[bool, float, float, float]:
    from performance_store import reach_recovery_state

    recovery, rolling, baseline = reach_recovery_state(now=now)
    ratio = rolling / baseline if baseline > 0 else 1.0
    return recovery, rolling, baseline, ratio


def _amplify_component(
    value: float,
    *,
    samples: int,
    max_abs: float,
    positive_mult: float,
    negative_mult: float,
) -> float:
    if samples <= 0:
        return float(value)
    mult = positive_mult if value >= 0 else negative_mult
    result = float(value) * mult
    return max(-max_abs, min(max_abs, result))


def score_adaptive_v117(*args, **kwargs):
    """Recovery-aware wrapper around adaptive.score_adaptive."""
    base = _ORIGINAL_SCORE_ADAPTIVE(*args, **kwargs)
    if not getattr(base, "enabled", False):
        return base

    recovery, rolling, baseline, reach_ratio = _recovery_state(kwargs.get("now"))
    if not recovery:
        return base

    ticker_comp = float(base.ticker_component)
    hour_comp = float(base.hour_component)
    lane_comp = float(base.lane_component)
    breakout_comp = float(base.breakout_component)
    exploration_comp = float(base.exploration_component)
    saturation_comp = float(base.saturation_component)

    if int(base.ticker_samples) >= _MIN_TICKER_SAMPLES:
        ticker_comp = _amplify_component(
            ticker_comp,
            samples=int(base.ticker_samples),
            max_abs=13.0,
            positive_mult=1.35,
            negative_mult=1.55,
        )
        if float(base.ticker_affinity) >= 60.0:
            ticker_comp = min(13.0, ticker_comp + 1.0)
        elif float(base.ticker_affinity) <= 35.0:
            ticker_comp = max(-13.0, ticker_comp - 1.5)

    if int(base.hour_samples) >= _MIN_HOUR_SAMPLES:
        hour_aff = float(base.hour_affinity)
        if hour_aff >= _STRONG_HOUR_AFFINITY:
            hour_comp = min(9.0, hour_comp * 1.8 + 1.4)
        elif hour_aff <= _WEAK_HOUR_AFFINITY:
            hour_comp = max(-9.0, hour_comp * 2.0 - 1.8)
        else:
            hour_comp = max(-9.0, min(9.0, hour_comp * 1.25))

    breakout_comp = max(-4.0, min(4.0, breakout_comp * 1.2))
    # Recovery is not the time to spend many slots exploring an unknown ticker.
    exploration_comp = min(exploration_comp, 0.8)

    recent30, baseline30, early_ratio, early_n = _distribution_health(kwargs.get("now"))
    severe = early_n >= 4 and early_ratio < 0.72
    if severe:
        if int(base.hour_samples) >= _MIN_HOUR_SAMPLES:
            if float(base.hour_affinity) >= 60.0:
                hour_comp = min(9.0, hour_comp + 1.5)
            elif float(base.hour_affinity) < 50.0:
                hour_comp = max(-9.0, hour_comp - 1.5)
        if int(base.ticker_samples) >= _MIN_TICKER_SAMPLES:
            if float(base.ticker_affinity) >= 58.0:
                ticker_comp = min(13.0, ticker_comp + 1.0)
            elif float(base.ticker_affinity) < 42.0:
                ticker_comp = max(-13.0, ticker_comp - 1.0)

    # outcome component is not exposed as a dataclass field in the original
    # object, so preserve it by deriving the residual before rebuilding total.
    known_base = (
        float(base.ticker_component)
        + float(base.hour_component)
        + float(base.lane_component)
        + float(base.breakout_component)
        + float(base.exploration_component)
        + float(base.saturation_component)
    )
    residual = float(base.total) - known_base
    total = (
        ticker_comp + hour_comp + lane_comp + breakout_comp
        + exploration_comp + saturation_comp + residual
    )
    total = max(-20.0, min(20.0, total))

    reason = (
        f"{base.reason}; v11.7 recovery={rolling:.0f}/{baseline:.0f} ({reach_ratio:.2f}), "
        f"30m={recent30:.0f}/{baseline30:.0f} ({early_ratio:.2f}, n={early_n}), "
        f"ticker={ticker_comp:+.1f}, hour={hour_comp:+.1f}, explore={exploration_comp:+.1f}"
    )
    return replace(
        base,
        total=round(total, 2),
        ticker_component=round(ticker_comp, 2),
        hour_component=round(hour_comp, 2),
        breakout_component=round(breakout_comp, 2),
        exploration_component=round(exploration_comp, 2),
        reason=reason,
    )


def score_content_performance_v117(*args, **kwargs):
    """Make proven formats materially matter while reach is depressed."""
    base = _ORIGINAL_SCORE_CONTENT(*args, **kwargs)
    if not getattr(base, "enabled", False):
        return base

    recovery, rolling, baseline, reach_ratio = _recovery_state(kwargs.get("now"))
    if not recovery:
        return base

    fmt = str(kwargs.get("content_format") or "")
    writer = str(kwargs.get("writer_source") or "").lower()
    format_comp = float(base.format_component)
    writer_comp = float(base.writer_component)
    event_comp = float(base.event_component)
    direction_comp = float(base.direction_component)

    if int(base.format_samples) >= _MIN_FORMAT_SAMPLES:
        if format_comp >= 0.8:
            format_comp = min(9.0, format_comp * 1.45 + 1.4)
        elif format_comp <= -0.8:
            format_comp = max(-9.0, format_comp * 1.65 - 1.8)
        else:
            format_comp *= 1.2

    # Small bootstrap prior is deliberately weaker than the learned component.
    format_comp += _RECOVERY_FORMAT_PRIOR.get(fmt, 0.0)

    if writer.startswith("deterministic"):
        writer_comp -= 3.5
    elif writer.startswith(("mistral", "deepseek")) and writer_comp > 0:
        writer_comp *= 1.15

    recent30, baseline30, early_ratio, early_n = _distribution_health(kwargs.get("now"))
    if early_n >= 4 and early_ratio < 0.72:
        # Severe first-distribution failure: concentrate even more on formats
        # with proven positive evidence, and punish weak format families.
        if format_comp > 0:
            format_comp += 1.0
        elif format_comp < 0:
            format_comp -= 1.2
        if writer.startswith("deterministic"):
            writer_comp -= 1.0

    format_comp = max(-9.0, min(9.0, format_comp))
    writer_comp = max(-5.0, min(5.0, writer_comp))
    total = format_comp + writer_comp + event_comp + direction_comp
    total = max(-13.0, min(13.0, total))
    reason = (
        f"{base.reason}; v11.7 recovery={rolling:.0f}/{baseline:.0f} ({reach_ratio:.2f}), "
        f"30m={recent30:.0f}/{baseline30:.0f} ({early_ratio:.2f}, n={early_n}), "
        f"format_policy={_RECOVERY_FORMAT_PRIOR.get(fmt, 0.0):+.1f}, total={total:+.1f}"
    )
    return replace(
        base,
        total=round(total, 2),
        format_component=round(format_comp, 2),
        writer_component=round(writer_comp, 2),
        reason=reason,
    )


def evaluate_recovery_candidate_v117(*args, **kwargs):
    """Add a distribution-health/hour guard on top of the v11.6 hard gate."""
    base = _ORIGINAL_RECOVERY_GATE(*args, **kwargs)
    recovery_mode = bool(kwargs.get("recovery_mode", False))
    if not recovery_mode:
        return base

    event = str(kwargs.get("event_class") or "ordinary").lower()
    source = str(kwargs.get("writer_source") or "").lower()
    strong_event = event in {"fresh_event", "audience_breakout"}
    hour_aff = float(kwargs.get("hour_affinity", 50.0) or 50.0)
    hour_n = int(kwargs.get("hour_samples", 0) or 0)
    reach = float(kwargs.get("reach_score", 0.0) or 0.0)
    selection = float(kwargs.get("selection_score", 0.0) or 0.0)
    opportunity = float(kwargs.get("opportunity_score", 0.0) or 0.0)
    demand = float(kwargs.get("audience_demand", 0.0) or 0.0)

    recent30, baseline30, early_ratio, early_n = _distribution_health()
    severe = early_n >= 4 and early_ratio < 0.72

    # Preserve every block from the base gate. v11.7 only adds evidence.
    if not base.allowed:
        return replace(
            base,
            reason=(
                f"{base.reason}; v11.7 30m={recent30:.0f}/{baseline30:.0f} "
                f"({early_ratio:.2f}, n={early_n})"
            ),
        )

    exceptional = (
        not source.startswith("deterministic")
        and reach >= 80.0
        and selection >= 75.0
        and opportunity >= 68.0
        and demand >= 76.0
    )

    if hour_n >= _MIN_HOUR_SAMPLES and hour_aff <= _WEAK_HOUR_AFFINITY and not strong_event and not exceptional:
        return replace(
            base,
            allowed=False,
            threshold=max(float(base.threshold), 78.0),
            reason=(
                f"v11.7 weak-hour block: affinity={hour_aff:.1f}/n{hour_n}; "
                f"30m={recent30:.0f}/{baseline30:.0f} ({early_ratio:.2f})"
            ),
        )

    if severe and hour_n >= _MIN_HOUR_SAMPLES and hour_aff < 50.0 and not strong_event and not exceptional:
        return replace(
            base,
            allowed=False,
            threshold=max(float(base.threshold), 79.0),
            reason=(
                f"v11.7 severe distribution block: hour={hour_aff:.1f}/n{hour_n}, "
                f"30m ratio={early_ratio:.2f}"
            ),
        )

    if severe and source.startswith("deterministic") and not exceptional:
        return replace(
            base,
            allowed=False,
            threshold=max(float(base.threshold), 80.0),
            reason=f"v11.7 deterministic blocked during severe 30m recovery ({early_ratio:.2f})",
        )

    suffix = (
        f"; v11.7 30m={recent30:.0f}/{baseline30:.0f} ({early_ratio:.2f}, n={early_n}), "
        f"hour={hour_aff:.1f}/n{hour_n}"
    )
    return replace(base, reason=base.reason + suffix)


def prepare_originals() -> None:
    global _ORIGINAL_SCORE_ADAPTIVE, _ORIGINAL_SCORE_CONTENT, _ORIGINAL_RECOVERY_GATE
    if _ORIGINAL_SCORE_ADAPTIVE is not None:
        return
    import adaptive
    import recovery_guard

    _ORIGINAL_SCORE_ADAPTIVE = adaptive.score_adaptive
    _ORIGINAL_SCORE_CONTENT = adaptive.score_content_performance
    _ORIGINAL_RECOVERY_GATE = recovery_guard.evaluate_recovery_candidate


def activate_reach_recovery() -> None:
    """Patch the references imported by main/event_writer after import."""
    prepare_originals()

    import adaptive
    import event_writer
    import main
    import recovery_guard

    adaptive.score_adaptive = score_adaptive_v117
    adaptive.score_content_performance = score_content_performance_v117
    main.score_adaptive = score_adaptive_v117
    main.score_content_performance = score_content_performance_v117
    event_writer.score_content_performance = score_content_performance_v117
    recovery_guard.evaluate_recovery_candidate = evaluate_recovery_candidate_v117

    logger.info(
        "v11.7 reach recovery policy active: adaptive hour/ticker concentration, "
        "format evidence weighting, 30m distribution health guard"
    )
