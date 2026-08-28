"""v11.4.6 Cadence Recovery runtime verification.

Keeps all production/text/trade-plan guards intact while verifying that the
recovery layer no longer creates multi-hour gaps by rejecting strong live AI
candidates that already passed the normal Distribution Gate.
"""
from __future__ import annotations

import os

from runtime import PROJECT_DIR


def _self_check() -> None:
    source = (PROJECT_DIR / "recovery_guard.py").read_text(encoding="utf-8")
    required = (
        "high_demand_ai = (",
        "actionable_cadence = (",
        "cadence recovery pass",
        "actionable cadence pass",
    )
    missing = [token for token in required if token not in source]
    if missing:
        raise RuntimeError("v11.4.6 cadence recovery incomplete: " + ", ".join(missing))

    from recovery_guard import evaluate_recovery_candidate

    xrp = evaluate_recovery_candidate(
        lane="event",
        writer_source="mistral_event",
        event_class="ordinary",
        micro_phase="ordinary",
        opportunity_score=65.2,
        audience_demand=90.8,
        attention_score=50.8,
        micro_score=45.8,
        monetization_score=63.7,
        selection_score=61.6,
        reach_score=74.4,
        plan_valid=False,
    )
    if not xrp.allowed or "cadence recovery pass" not in xrp.reason:
        raise RuntimeError("v11.4.6 production XRP regression check failed")

    weak = evaluate_recovery_candidate(
        lane="event",
        writer_source="mistral_event",
        event_class="ordinary",
        micro_phase="ordinary",
        opportunity_score=58.0,
        audience_demand=91.0,
        attention_score=52.0,
        micro_score=48.0,
        monetization_score=45.0,
        selection_score=62.0,
        reach_score=75.0,
        plan_valid=False,
    )
    if weak.allowed:
        raise RuntimeError("v11.4.6 weak high-demand guard regression check failed")


def apply_v1146_hotfix() -> None:
    os.environ["BOT_VERSION"] = "v11.4.6"
    # Preserve the final-only public outcome contract at the newest boundary.
    os.environ["OUTCOME_POST_STOPS"] = "0"
    os.environ["OUTCOME_POST_PARTIAL_TARGETS"] = "0"
    _self_check()
    print("[v11.4.6 hotfix] Cadence Recovery verified: strong live AI candidates can pass without weakening stale/weak guards")


if __name__ == "__main__":
    apply_v1146_hotfix()
