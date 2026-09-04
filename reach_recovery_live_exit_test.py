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


def _dash_outage_kwargs():
    return dict(
        lane="trade",
        writer_source="deterministic",
        event_class="audience_breakout",
        micro_phase="fresh",
        opportunity_score=81.7,
        audience_demand=86.7,
        attention_score=71.8,
        micro_score=79.7,
        monetization_score=71.8,
        selection_score=96.7,
        reach_score=81.9,
        plan_valid=True,
        recovery_mode=True,
        hour_affinity=50.0,
        hour_samples=8,
    )


def main() -> int:
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

    # Ordinary/mediocre deterministic copy remains blocked.
    deterministic_weak = live_exit._evaluate_with_live_exit(
        policy.evaluate_recovery_candidate_v118,
        **_prom_kwargs(source="deterministic"),
    )
    assert not deterministic_weak.allowed

    # If every provider is down, a genuinely exceptional strong-market outage
    # fallback can keep the account alive once fresh distribution has recovered.
    deterministic_strong = live_exit._evaluate_with_live_exit(
        policy.evaluate_recovery_candidate_v118,
        **_dash_outage_kwargs(),
    )
    assert deterministic_strong.allowed
    assert "exceptional outage fallback" in deterministic_strong.reason

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

    print("LIVE RECOVERY EXIT: OK | AI resumes | exceptional outage continuity guarded")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
