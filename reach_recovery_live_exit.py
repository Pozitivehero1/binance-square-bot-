"""Live exit from stale rolling-24h recovery mode.

The rolling 24h total is intentionally slow to recover after a publishing outage.
Once both observable fresh distribution stages are back near baseline, AI-authored
posts use the normal quality gate again. If every AI provider is unavailable,
a deterministic outage draft may also pass only for a genuinely strong live
market under explicit continuity floors; it never becomes a co-equal author.
"""
from __future__ import annotations

from dataclasses import replace
import logging

import reach_recovery_v11_8 as policy

logger = logging.getLogger(__name__)


def fresh_distribution_recovered(health: dict) -> bool:
    """Return True only with enough fresh evidence that distribution recovered."""
    early_n = int(health.get("early_n", 0) or 0)
    expansion_n = int(health.get("expansion_n", 0) or 0)
    early_ratio = float(health.get("early_ratio", 0.0) or 0.0)
    expansion_ratio = float(health.get("expansion_ratio", 0.0) or 0.0)
    return (
        early_n >= 2
        and early_ratio >= 0.90
        and expansion_n >= 4
        and expansion_ratio >= 0.90
    )


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

    # Fresh 30m and 30m->2h distribution have recovered. Re-evaluate without the
    # stale rolling-24h uplift. Normal factual/quality/reach gates remain active.
    # Deterministic copy still carries the base guard's own stricter penalty and,
    # above, must satisfy additional strong-market continuity floors.
    relaxed = dict(kwargs)
    relaxed["recovery_mode"] = False
    decision = base_gate(*args, **relaxed)
    if decision.allowed:
        mode = "exceptional outage fallback" if deterministic else "AI"
        reason = (
            f"v11.8 live-distribution recovery exit ({mode}): "
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
        "v11.8 live recovery exit active: fresh distribution releases AI; exceptional strong-market deterministic fallback is continuity-only"
    )
