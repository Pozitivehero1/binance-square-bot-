"""Regression checks for fresh-distribution recovery exit."""
from __future__ import annotations

import reach_recovery_live_exit as live_exit
import reach_recovery_v11_8 as policy
from recovery_guard import evaluate_recovery_candidate as base_recovery_gate


def _health(*, early=1.04, early_n=2, expansion=1.12, expansion_n=10):
    return {
        "recent30": 73.0,
        "baseline30": 70.0,
        "early_ratio": early,
        "early_n": early_n,
        "recent_expansion": 1.24,
        "baseline_expansion": 1.11,
        "expansion_ratio": expansion,
        "expansion_n": expansion_n,
    }


def _prom_kwargs(source="openrouter"):
    return dict(
        lane="trade",
        writer_source=source,
        event_class="ordinary",
        micro_phase="ordinary",
        opportunity_score=66.9,
        audience_demand=78.9,
        attention_score=52.0,
        micro_score=51.3,
        monetization_score=56.9,
        selection_score=66.7,
        reach_score=75.2,
        plan_valid=True,
        recovery_mode=True,
        hour_affinity=47.3,
        hour_samples=8,
    )


def main() -> int:
    # Use the real v11.6 gate underneath v11.8 so this reproduces the production
    # PROM case that was blocked only because rolling24h recovery_mode=True.
    policy._ORIGINAL_RECOVERY_GATE = base_recovery_gate
    policy.distribution_health = lambda now=None: _health()

    blocked = policy.evaluate_recovery_candidate_v118(**_prom_kwargs())
    assert not blocked.allowed

    released = live_exit._evaluate_with_live_exit(
        policy.evaluate_recovery_candidate_v118,
        **_prom_kwargs(),
    )
    assert released.allowed
    assert "live-distribution recovery exit" in released.reason

    # Deterministic outage copy must remain blocked even with healthy fresh data.
    deterministic = live_exit._evaluate_with_live_exit(
        policy.evaluate_recovery_candidate_v118,
        **_prom_kwargs(source="deterministic"),
    )
    assert not deterministic.allowed

    # Insufficient or still-depressed fresh data must not bypass recovery mode.
    policy.distribution_health = lambda now=None: _health(early=0.82, early_n=2)
    still_blocked = live_exit._evaluate_with_live_exit(
        policy.evaluate_recovery_candidate_v118,
        **_prom_kwargs(),
    )
    assert not still_blocked.allowed

    policy.distribution_health = lambda now=None: _health(early=1.02, early_n=1)
    insufficient = live_exit._evaluate_with_live_exit(
        policy.evaluate_recovery_candidate_v118,
        **_prom_kwargs(),
    )
    assert not insufficient.allowed

    print("LIVE RECOVERY EXIT: OK | fresh AI resumes | deterministic remains blocked")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
