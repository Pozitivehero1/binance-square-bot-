"""Live exit from stale rolling-24h recovery mode.

The rolling 24h total is intentionally slow to recover after a publishing outage.
Once both observable fresh distribution stages are back near baseline, AI-authored
posts should use the normal v11.6/v11.8 quality gate instead of being trapped by
an old 24h deficit. Deterministic outage copy is never relaxed here.
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


def _evaluate_with_live_exit(base_gate, *args, **kwargs):
    source = str(kwargs.get("writer_source") or "").strip().lower()
    recovery_mode = bool(kwargs.get("recovery_mode", False))

    # Never turn outage templates into normal authors merely to fill slots.
    if source.startswith("deterministic") or not recovery_mode:
        return base_gate(*args, **kwargs)

    health = policy.distribution_health()
    if not fresh_distribution_recovered(health):
        return base_gate(*args, **kwargs)

    # Fresh 30m and 30m->2h distribution have recovered. Re-evaluate this AI
    # candidate without the stale rolling-24h uplift; all normal quality, market,
    # plan and v11.8 distribution checks remain active.
    relaxed = dict(kwargs)
    relaxed["recovery_mode"] = False
    decision = base_gate(*args, **relaxed)
    if decision.allowed:
        reason = (
            "v11.8 live-distribution recovery exit: "
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
        "v11.8 live recovery exit active: AI uses normal gate when 30m and 2h expansion recover; deterministic remains protected"
    )
