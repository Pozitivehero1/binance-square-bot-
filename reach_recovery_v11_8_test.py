"""Offline regression checks for v11.8 distribution recovery."""
from __future__ import annotations

import os

import reach_recovery_v11_8 as policy
from recovery_guard import RecoveryDecision


def _gate(*_args, **_kwargs):
    return RecoveryDecision(True, "base passed", 74.0)


def _health(*, early=0.55, expansion=0.70):
    return {
        "recent30": 40.0,
        "baseline30": 73.0,
        "early_ratio": early,
        "early_n": 8,
        "recent_expansion": 1.05,
        "baseline_expansion": 1.50,
        "expansion_ratio": expansion,
        "expansion_n": 8,
    }


def main() -> int:
    policy.configure_environment()
    assert os.environ["BOT_VERSION"] == "v11.8"
    assert os.environ["ADAPTIVE_MAX_TOTAL"] == "14"
    assert os.environ["ADAPTIVE_TICKER_MAX"] == "10"
    assert os.environ["ADAPTIVE_HOUR_MAX"] == "5"
    assert os.environ["AI_RETRIES"] == "1"
    assert os.environ["EVENT_AI_RETRIES"] == "1"
    assert os.environ["ORCAROUTER_RETRIES"] == "1"

    policy._ORIGINAL_RECOVERY_GATE = _gate
    policy.distribution_health = lambda now=None: _health()

    deterministic = policy.evaluate_recovery_candidate_v118(
        lane="trade", writer_source="deterministic", event_class="audience_breakout",
        micro_phase="fresh", opportunity_score=80.0, audience_demand=90.0,
        attention_score=85.0, micro_score=88.0, monetization_score=70.0,
        selection_score=86.0, reach_score=90.0, plan_valid=True,
        recovery_mode=True, hour_affinity=65.0, hour_samples=30,
    )
    assert not deterministic.allowed
    assert "provider-outage fallback" in deterministic.reason

    ordinary = policy.evaluate_recovery_candidate_v118(
        lane="event", writer_source="mistral_event", event_class="ordinary",
        micro_phase="ordinary", opportunity_score=68.0, audience_demand=78.0,
        attention_score=55.0, micro_score=52.0, monetization_score=65.0,
        selection_score=74.0, reach_score=80.0, plan_valid=False,
        recovery_mode=True, hour_affinity=55.0, hour_samples=30,
    )
    assert not ordinary.allowed
    assert "distribution" in ordinary.reason

    rescue = policy.evaluate_recovery_candidate_v118(
        lane="event", writer_source="mistral_event", event_class="audience_breakout",
        micro_phase="fresh", opportunity_score=72.0, audience_demand=78.0,
        attention_score=72.0, micro_score=75.0, monetization_score=67.0,
        selection_score=78.0, reach_score=85.0, plan_valid=True,
        recovery_mode=True, hour_affinity=55.0, hour_samples=30,
    )
    assert rescue.allowed

    policy.distribution_health = lambda now=None: _health(early=0.92, expansion=0.93)
    healthy = policy.evaluate_recovery_candidate_v118(
        lane="event", writer_source="mistral_event", event_class="active_market",
        micro_phase="developing", opportunity_score=70.0, audience_demand=72.0,
        attention_score=65.0, micro_score=67.0, monetization_score=64.0,
        selection_score=74.0, reach_score=79.0, plan_valid=True,
        recovery_mode=False, hour_affinity=50.0, hour_samples=12,
    )
    assert healthy.allowed

    print("v11.8 distribution recovery tests passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
