"""Single cumulative startup activation and read-only release verification."""
from __future__ import annotations

import os


def activate_release() -> None:
    os.environ["BOT_VERSION"] = "v11.6"
    os.environ["OUTCOME_POST_STOPS"] = "0"
    os.environ["OUTCOME_POST_PARTIAL_TARGETS"] = "0"

    from production_guard import final_text_reasons
    from recovery_guard import evaluate_recovery_candidate
    from semantic_quality import semantic_quality_reasons

    if not semantic_quality_reasons("Активность х2 в разы подтверждает рост."):
        raise RuntimeError("v11.6 semantic quality contract is incomplete")
    if not final_text_reasons("TP3 100,"):
        raise RuntimeError("v11.6 final text contract is incomplete")
    weak = evaluate_recovery_candidate(
        lane="event", writer_source="mistral_event", event_class="ordinary",
        micro_phase="ordinary", opportunity_score=65.2, audience_demand=90.8,
        attention_score=50.8, micro_score=45.8, monetization_score=63.7,
        selection_score=61.6, reach_score=74.4, plan_valid=False,
        recovery_mode=True,
    )
    if weak.allowed:
        raise RuntimeError("v11.6 cadence escape is active")
    print("[v11.6] cumulative release verified: evidence-weighted reach engine active")


if __name__ == "__main__":
    activate_release()
