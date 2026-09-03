"""Offline regression checks for the v11.7 account-specific reach policy."""
from __future__ import annotations

import os

import reach_recovery_v11_7 as policy
from adaptive import AdaptiveAdjustment, ContentPerformanceAdjustment
from recovery_guard import RecoveryDecision


def _adaptive(*_args, **_kwargs):
    return AdaptiveAdjustment(
        enabled=True,
        total=4.0,
        ticker_component=2.0,
        hour_component=2.0,
        lane_component=0.5,
        breakout_component=0.5,
        exploration_component=1.5,
        saturation_component=-1.0,
        ticker_affinity=62.0,
        hour_affinity=64.0,
        lane_affinity=52.0,
        ticker_samples=12,
        hour_samples=30,
        lane_samples=100,
        recent_symbol_posts=1,
        baseline_views=100.0,
        reason="base",
    )


def _content(*_args, **_kwargs):
    return ContentPerformanceAdjustment(
        enabled=True,
        total=0.0,
        format_component=0.0,
        writer_component=0.0,
        event_component=0.0,
        direction_component=0.0,
        format_samples=40,
        writer_samples=100,
        event_samples=100,
        direction_samples=100,
        baseline_views=100.0,
        reason="base",
    )


def _gate(*_args, **_kwargs):
    return RecoveryDecision(True, "base passed", 74.0)


def main() -> int:
    policy.configure_environment()
    assert os.environ["BOT_VERSION"] == "v11.7"
    assert os.environ["ADAPTIVE_HOUR_MAX"] == "9"

    policy._ORIGINAL_SCORE_ADAPTIVE = _adaptive
    policy._ORIGINAL_SCORE_CONTENT = _content
    policy._ORIGINAL_RECOVERY_GATE = _gate
    policy._recovery_state = lambda now=None: (True, 1800.0, 5600.0, 0.321)
    policy._distribution_health = lambda now=None: (55.0, 100.0, 0.55, 8)

    strong = policy.score_adaptive_v117(symbol="ADA", lane="EVENT", live_score=70.0)
    assert strong.hour_component > 2.0
    assert strong.ticker_component > 2.0
    assert strong.exploration_component <= 0.8
    assert strong.total > 4.0

    original = policy._ORIGINAL_SCORE_ADAPTIVE

    def weak_adaptive(*_args, **_kwargs):
        row = original()
        return AdaptiveAdjustment(
            **{
                **row.__dict__,
                "ticker_component": -2.0,
                "hour_component": -2.0,
                "ticker_affinity": 32.0,
                "hour_affinity": 35.0,
                "reason": "weak",
            }
        )

    policy._ORIGINAL_SCORE_ADAPTIVE = weak_adaptive
    weak = policy.score_adaptive_v117(symbol="ARB", lane="TRADE", live_score=70.0)
    assert weak.hour_component < -2.0
    assert weak.ticker_component < -2.0
    assert weak.total < strong.total

    policy._ORIGINAL_SCORE_CONTENT = _content
    good = policy.score_content_performance_v117(
        lane="EVENT", content_format="event_market_story",
        writer_source="mistral_event", event_class="active_market",
        direction="observation",
    )
    bad = policy.score_content_performance_v117(
        lane="TRADE", content_format="risk_first",
        writer_source="deterministic", event_class="ordinary",
        direction="long",
    )
    assert good.total >= 3.0
    assert bad.total <= -7.0
    assert good.total - bad.total >= 9.0

    policy._ORIGINAL_RECOVERY_GATE = _gate
    blocked = policy.evaluate_recovery_candidate_v117(
        lane="trade", writer_source="mistral", event_class="active_market",
        opportunity_score=72.0, audience_demand=70.0, selection_score=76.0,
        reach_score=77.0, recovery_mode=True, hour_affinity=38.0,
        hour_samples=30,
    )
    assert not blocked.allowed
    assert "weak-hour" in blocked.reason or "severe distribution" in blocked.reason

    allowed = policy.evaluate_recovery_candidate_v117(
        lane="event", writer_source="mistral_event", event_class="fresh_event",
        opportunity_score=74.0, audience_demand=80.0, selection_score=80.0,
        reach_score=81.0, recovery_mode=True, hour_affinity=64.0,
        hour_samples=30,
    )
    assert allowed.allowed

    print("v11.7 reach recovery policy tests passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
