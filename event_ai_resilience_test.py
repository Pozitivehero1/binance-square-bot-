"""Offline checks for EVENT AI outage resilience."""
from __future__ import annotations

from dataclasses import dataclass

import event_ai_resilience as policy
import event_writer


@dataclass(frozen=True)
class _Draft:
    style_id: str
    source: str


def main() -> int:
    normalized = policy._normalize_sources([
        _Draft("openrouter_free_event_event_pulse_0", "mistral_event"),
        _Draft("deepseek_v4_pro_event_event_pulse_1", "deepseek_event"),
        _Draft("det_event_event_pulse_0", "deterministic_event"),
    ])
    assert normalized[0].source == "openrouter_event"
    assert normalized[1].source == "deepseek_event"
    assert normalized[2].source == "deterministic_event"

    # Reproduce the production problem: the old EVENT policy required two valid
    # AI drafts and had only one outer generation attempt after v11.8 startup.
    event_writer.EVENT_MIN_VALID_AI_DRAFTS = 2
    event_writer.EVENT_AI_RETRIES = 1
    policy._ORIGINAL_GENERATE = None
    policy.install_event_ai_resilience()

    assert event_writer.EVENT_MIN_VALID_AI_DRAFTS == 1
    assert event_writer.EVENT_AI_RETRIES >= 2
    assert event_writer.generate_event_candidates is policy._generate_event_candidates_resilient

    print("EVENT AI resilience tests passed | one valid AI draft accepted | OpenRouter source truthful")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
