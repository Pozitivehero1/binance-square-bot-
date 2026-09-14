"""Regression checks for fresh-distribution recovery annotations and outage safety."""
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


def _pump_kwargs(source="openrouter_event_repaired"):
    return dict(
        lane="event",
        writer_source=source,
        event_class="ordinary",
        micro_phase="fresh",
        opportunity_score=68.8,
        audience_demand=68.8,
        attention_score=61.4,
        micro_score=70.4,
        monetization_score=57.1,
        selection_score=73.1,
        reach_score=81.5,
        plan_valid=True,
        recovery_mode=True,
        hour_affinity=47.4,
        hour_samples=6,
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

    # v11.12: rolling recovery is no longer a second hard gate for valid AI copy.
    direct_ai = policy.evaluate_recovery_candidate_v118(**_prom_kwargs())
    assert direct_ai.allowed, direct_ai.reason

    # The legacy live-exit layer may still add a useful diagnostic annotation when
    # fresh distribution has clearly recovered, but it is no longer required to
    # unlock an otherwise valid AI post.
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

    # One very strong fresh sample still gets the restart annotation.
    policy.distribution_health = lambda now=None: _health(
        early=115.0 / 70.0,
        early_n=1,
        expansion=1.13 / 1.11,
        expansion_n=7,
    )
    restart = live_exit._evaluate_with_live_exit(
        policy.evaluate_recovery_candidate_v118,
        **_pump_kwargs(),
    )
    assert restart.allowed, restart.reason
    assert "restart" in restart.reason

    # These weaker distribution states previously caused a self-sustaining
    # no-post loop. They must no longer veto an AI candidate that passed the
    # normal market/content guard.
    policy.distribution_health = lambda now=None: _health(early=1.02, early_n=1, expansion=1.05, expansion_n=7)
    insufficient = live_exit._evaluate_with_live_exit(
        policy.evaluate_recovery_candidate_v118,
        **_prom_kwargs(),
    )
    assert insufficient.allowed, insufficient.reason

    policy.distribution_health = lambda now=None: _health(early=1.30, early_n=1, expansion=0.75, expansion_n=7)
    weak_expansion = live_exit._evaluate_with_live_exit(
        policy.evaluate_recovery_candidate_v118,
        **_pump_kwargs(),
    )
    assert weak_expansion.allowed, weak_expansion.reason
    assert "advisory only" in weak_expansion.reason

    policy.distribution_health = lambda now=None: _health(early=0.82, early_n=2, expansion=0.75, expansion_n=7)
    depressed = live_exit._evaluate_with_live_exit(
        policy.evaluate_recovery_candidate_v118,
        **_prom_kwargs(),
    )
    assert depressed.allowed, depressed.reason
    assert "advisory only" in depressed.reason

    print("LIVE RECOVERY EXIT: OK | AI cadence non-blocking | deterministic outage continuity guarded")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
