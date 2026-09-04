"""v11.8 distribution-recovery policy.

v11.7 proved that stronger ticker/hour priors do not solve the current reach
problem.  v11.8 deliberately returns ranking weights to the conservative
pre-v11.7 bounds and focuses on the two distribution stages we can actually
observe from the account:

1. the initial ~30 minute test audience;
2. expansion from 30 minutes to 2 hours.

During a reach/distribution slump deterministic outage copy is not published.
The external cron remains unchanged: every tick may inspect the market, but a
slot is allowed to stay empty when the author providers are unavailable or the
market evidence is not strong enough to justify another post.
"""
from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
import logging
import os
from statistics import median
from typing import Optional

logger = logging.getLogger(__name__)

_ORIGINAL_RECOVERY_GATE = None


def configure_environment() -> None:
    """Install v11.8 defaults before main/adaptive modules are imported."""
    os.environ["BOT_VERSION"] = "v11.8"

    # Roll back the aggressive v11.7 reach priors.  These are the bounded values
    # used before the account-specific over-concentration experiment.
    os.environ["ADAPTIVE_MAX_TOTAL"] = "14"
    os.environ["ADAPTIVE_TICKER_MAX"] = "10"
    os.environ["ADAPTIVE_HOUR_MAX"] = "5"
    os.environ["ADAPTIVE_CONTENT_MAX_TOTAL"] = "9"
    os.environ["ADAPTIVE_FORMAT_MAX"] = "5"
    os.environ["ADAPTIVE_WRITER_MAX"] = "2.5"
    os.environ["ADAPTIVE_EVENT_CLASS_MAX"] = "2"
    os.environ["ADAPTIVE_DIRECTION_MAX"] = "1.5"

    # One author attempt already includes primary -> fallback provider routing.
    # Repeating the whole chain when both providers are failing only multiplies
    # 503/429 traffic and then creates deterministic fallback candidates.
    os.environ["ORCAROUTER_RETRIES"] = "1"
    os.environ["AI_RETRIES"] = "1"
    os.environ["EVENT_AI_RETRIES"] = "1"
    os.environ["DETERMINISTIC_COMPARE_SLOTS"] = "0"
    os.environ["EVENT_DETERMINISTIC_COMPARE_SLOTS"] = "0"

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


def distribution_health(now: Optional[datetime] = None) -> dict[str, float | int]:
    """Measure both initial distribution and second-stage expansion.

    Baselines exclude the recent bucket so a live slump cannot immediately teach
    itself into the historical norm.
    """
    from performance_store import load_store

    now = now or datetime.now(timezone.utc)
    early_cutoff = now - timedelta(hours=12)
    expansion_cutoff = now - timedelta(hours=18)
    baseline_cutoff = now - timedelta(days=7)

    recent30: list[float] = []
    base30: list[float] = []
    recent_expansion: list[float] = []
    base_expansion: list[float] = []

    for item in load_store().get("posts", {}).values():
        if not isinstance(item, dict) or not item.get("learning_eligible", True):
            continue
        published = _parse_dt(item.get("published_at"))
        if not published or published < baseline_cutoff or published > now:
            continue
        milestones = item.get("milestones") if isinstance(item.get("milestones"), dict) else {}
        row30 = milestones.get("30m")
        row2h = milestones.get("2h")

        views30 = 0.0
        if isinstance(row30, dict):
            try:
                views30 = float(row30.get("views", 0) or 0)
            except (TypeError, ValueError):
                views30 = 0.0
        if views30 > 0:
            if published >= early_cutoff:
                recent30.append(views30)
            else:
                base30.append(views30)

        if views30 <= 0 or not isinstance(row2h, dict):
            continue
        try:
            views2h = float(row2h.get("views", 0) or 0)
        except (TypeError, ValueError):
            continue
        if views2h <= 0:
            continue
        # A value below 1 can happen because of noisy snapshots; cap only the
        # extreme tail so one breakout cannot dominate the cohort median.
        expansion = max(0.5, min(4.0, views2h / views30))
        if published >= expansion_cutoff:
            recent_expansion.append(expansion)
        else:
            base_expansion.append(expansion)

    recent30_med = float(median(recent30)) if recent30 else 0.0
    base30_med = float(median(base30)) if base30 else 0.0
    early_ratio = recent30_med / base30_med if recent30_med > 0 and base30_med > 0 else 1.0

    recent_exp_med = float(median(recent_expansion)) if recent_expansion else 0.0
    base_exp_med = float(median(base_expansion)) if base_expansion else 0.0
    expansion_ratio = (
        recent_exp_med / base_exp_med
        if recent_exp_med > 0 and base_exp_med > 0
        else 1.0
    )

    return {
        "recent30": recent30_med,
        "baseline30": base30_med,
        "early_ratio": early_ratio,
        "early_n": len(recent30),
        "recent_expansion": recent_exp_med,
        "baseline_expansion": base_exp_med,
        "expansion_ratio": expansion_ratio,
        "expansion_n": len(recent_expansion),
    }


def evaluate_recovery_candidate_v118(*args, **kwargs):
    """Prevent low-originality outage publishing and react before 24h reach collapses."""
    base = _ORIGINAL_RECOVERY_GATE(*args, **kwargs)

    source = str(kwargs.get("writer_source") or "").strip().lower()
    event = str(kwargs.get("event_class") or "ordinary").strip().lower()
    recovery_mode = bool(kwargs.get("recovery_mode", False))
    reach = float(kwargs.get("reach_score", 0.0) or 0.0)
    selection = float(kwargs.get("selection_score", 0.0) or 0.0)
    opportunity = float(kwargs.get("opportunity_score", 0.0) or 0.0)
    demand = float(kwargs.get("audience_demand", 0.0) or 0.0)
    attention = float(kwargs.get("attention_score", 0.0) or 0.0)
    micro = float(kwargs.get("micro_score", 0.0) or 0.0)

    health = distribution_health()
    early_n = int(health["early_n"])
    expansion_n = int(health["expansion_n"])
    early_ratio = float(health["early_ratio"])
    expansion_ratio = float(health["expansion_ratio"])

    initial_depressed = early_n >= 4 and early_ratio < 0.78
    expansion_depressed = expansion_n >= 4 and expansion_ratio < 0.80
    distribution_depressed = initial_depressed or expansion_depressed
    deterministic = source.startswith("deterministic")

    suffix = (
        f"; v11.8 30m={float(health['recent30']):.0f}/{float(health['baseline30']):.0f} "
        f"({early_ratio:.2f}, n={early_n}), "
        f"2h/30m={float(health['recent_expansion']):.2f}/{float(health['baseline_expansion']):.2f} "
        f"({expansion_ratio:.2f}, n={expansion_n})"
    )

    # Fix the v11.7 lag: when rolling reach is already depressed OR either live
    # distribution stage is depressed, provider-outage templates never publish.
    # They can still be generated for diagnostics, but cannot consume a feed slot.
    if deterministic and (recovery_mode or distribution_depressed):
        return replace(
            base,
            allowed=False,
            threshold=max(float(base.threshold), 82.0),
            reason="v11.8 provider-outage fallback blocked during reach recovery" + suffix,
        )

    # Keep every rejection from the conservative base recovery guard.
    if not base.allowed:
        return replace(base, reason=base.reason + suffix)

    strong_event = event in {"fresh_event", "audience_breakout", "high_demand_active"}
    activity = max(attention, micro)

    # This is the rescue profile for a feed whose initial test and/or second-stage
    # expansion is failing.  It is intentionally about live evidence, not about
    # historical ticker/hour affinity.
    rescue_quality = (
        strong_event
        and reach >= 78.0
        and selection >= 71.0
        and opportunity >= 65.0
        and demand >= 62.0
        and activity >= 58.0
    )
    exceptional = (
        strong_event
        and reach >= 83.0
        and selection >= 76.0
        and opportunity >= 70.0
        and demand >= 72.0
        and activity >= 68.0
    )

    if distribution_depressed and not rescue_quality:
        stage = "initial" if initial_depressed else "expansion"
        return replace(
            base,
            allowed=False,
            threshold=max(float(base.threshold), 78.0),
            reason=f"v11.8 {stage}-distribution rescue block" + suffix,
        )

    # When both stages are depressed simultaneously, only an exceptional live
    # event is worth another test slot.  This prevents a run of merely 'good'
    # posts from repeatedly receiving 10-30 views and teaching the feed the same
    # low-engagement pattern.
    if initial_depressed and expansion_depressed and not exceptional:
        return replace(
            base,
            allowed=False,
            threshold=max(float(base.threshold), 83.0),
            reason="v11.8 dual-stage distribution block" + suffix,
        )

    return replace(base, reason=base.reason + suffix)


def prepare_originals() -> None:
    global _ORIGINAL_RECOVERY_GATE
    if _ORIGINAL_RECOVERY_GATE is not None:
        return
    import recovery_guard
    _ORIGINAL_RECOVERY_GATE = recovery_guard.evaluate_recovery_candidate


def activate_reach_recovery() -> None:
    """Patch only the publication recovery gate; leave trade/ranking math stable."""
    prepare_originals()
    import recovery_guard
    recovery_guard.evaluate_recovery_candidate = evaluate_recovery_candidate_v118
    logger.info(
        "v11.8 distribution recovery active: conservative ranking, no outage-fallback publishing, "
        "30m initial-test + 2h expansion guard"
    )
