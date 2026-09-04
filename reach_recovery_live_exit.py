"""Live exit from stale rolling-24h recovery mode.

The rolling 24h total is intentionally slow to recover after a publishing outage.
Once observable fresh distribution is back near baseline, AI-authored posts use
the normal quality gate again. A single very strong 30m sample can be enough
only when the second-stage 30m->2h expansion has a larger healthy sample behind
it. This avoids a stale 24h total creating a self-sustaining publishing outage.
If every AI provider is unavailable, deterministic outage copy may also pass
only for a genuinely strong live market under explicit continuity floors; it
never becomes a co-equal author.
"""
from __future__ import annotations

from dataclasses import replace
import logging

import reach_recovery_v11_8 as policy

logger = logging.getLogger(__name__)


def fresh_distribution_recovered(health: dict) -> bool:
    """Return True when fresh distribution has enough credible recovery evidence.

    Normal path: at least two recent 30m samples are >=90% of baseline and the
    30m->2h stage has >=4 samples at >=90% of baseline.

    Restart path: after a publishing outage there may be only one new 30m sample.
    Allow that single sample to release AI only when it is materially above
    baseline (>=115%) and the slower expansion stage has >=6 healthy samples.
    That is deliberately stricter than the normal path and cannot be triggered
    by a merely average single post.
    """
    early_n = int(health.get("early_n", 0) or 0)
    expansion_n = int(health.get("expansion_n", 0) or 0)
    early_ratio = float(health.get("early_ratio", 0.0) or 0.0)
    expansion_ratio = float(health.get("expansion_ratio", 0.0) or 0.0)

    normal_recovery = (
        early_n >= 2
        and early_ratio >= 0.90
        and expansion_n >= 4
        and expansion_ratio >= 0.90
    )
    confident_restart = (
        early_n >= 1
        and early_ratio >= 1.15
        and expansion_n >= 6
        and expansion_ratio >= 0.95
    )
    return normal_recovery or confident_restart


def _exceptional_outage_fallback(kwargs: dict) -> bool:
    """Continuity escape for provider outages after distribution has recovered."""
    event = str(kwargs.get("event_class") or "ordinary").strip().lower()
    reach = float(kwargs.get("reach_score", 0.0) or 0.0)
    selection = float(kwargs.get("selection_score", 0.0) or 0.0)
    opportunity = float(kwargs.get("opportunity_score", 0.0) or 0.0)
    demand = float(kwargs.get("audience_demand", 0.0) or 0.0)
    activity = max(
        float(kwargs.get("attention_score", 0.0) or 0.0),
        float(kwargs.get("micro_score", 0.0) or 0.0),
    )
    return (
        event in {"fresh_event", "audience_breakout", "high_demand_active"}
        and reach >= 78.0
        and selection >= 72.0
        and opportunity >= 65.0
        and demand >= 55.0
        and activity >= 55.0
    )


def _evaluate_with_live_exit(base_gate, *args, **kwargs):
    source = str(kwargs.get("writer_source") or "").strip().lower()
    recovery_mode = bool(kwargs.get("recovery_mode", False))
    if not recovery_mode:
        return base_gate(*args, **kwargs)

    health = policy.distribution_health()
    if not fresh_distribution_recovered(health):
        return base_gate(*args, **kwargs)

    deterministic = source.startswith("deterministic")
    if deterministic and not _exceptional_outage_fallback(kwargs):
        return base_gate(*args, **kwargs)

    # Fresh distribution has recovered. Re-evaluate without the stale rolling-24h
    # uplift. Normal factual/quality/reach gates remain active. Deterministic copy
    # still carries the base guard's own stricter penalty and, above, must satisfy
    # additional strong-market continuity floors.
    relaxed = dict(kwargs)
    relaxed["recovery_mode"] = False
    decision = base_gate(*args, **relaxed)
    if decision.allowed:
        mode = "exceptional outage fallback" if deterministic else "AI"
        sample_mode = "restart" if int(health.get("early_n", 0) or 0) == 1 else "normal"
        reason = (
            f"v11.8 live-distribution recovery exit ({mode}, {sample_mode}): "
            f"30m={float(health.get('early_ratio', 0.0)):.2f} n={int(health.get('early_n', 0))}, "
            f"2h/30m={float(health.get('expansion_ratio', 0.0)):.2f} n={int(health.get('expansion_n', 0))}; "
            + str(decision.reason)
        )
        return replace(decision, reason=reason)
    return decision


def activate_live_recovery_exit() -> None:
    """Patch the already-activated v11.8 recovery gate with a fresh-data exit."""
    import recovery_guard

    current = recovery_guard.evaluate_recovery_candidate
    if getattr(current, "_v118_live_recovery_exit", False):
        return

    def wrapped(*args, **kwargs):
        return _evaluate_with_live_exit(current, *args, **kwargs)

    wrapped._v118_live_recovery_exit = True  # type: ignore[attr-defined]
    recovery_guard.evaluate_recovery_candidate = wrapped
    logger.info(
        "v11.8 live recovery exit active: fresh distribution releases AI; strong-singleton restart supported; exceptional deterministic fallback is continuity-only"
    )
