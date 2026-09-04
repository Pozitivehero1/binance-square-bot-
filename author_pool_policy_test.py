from __future__ import annotations

from dataclasses import dataclass

import author_pool_policy as policy


@dataclass(frozen=True)
class Draft:
    source: str
    style_id: str = ""
    text: str = "x"


def main() -> None:
    # Exact production failure mode: one valid AI draft survived local
    # anti-duplicate filtering and deterministic templates filled the rest.
    rows = [Draft("openrouter", "openrouter_trade_map_0")]
    rows.extend(Draft("deterministic", f"det_{i}") for i in range(15))
    chosen = policy._ai_authoritative(rows, "TRADE")
    assert len(chosen) == 1
    assert chosen[0].source == "openrouter"

    # Deterministic remains available only when there is no valid AI draft.
    outage = [Draft("deterministic", "det_0"), Draft("deterministic", "det_1")]
    assert policy._ai_authoritative(outage, "TRADE") == outage

    # OpenRouter EVENT metadata must not be mislabeled as Mistral.
    event = policy._ai_authoritative(
        [Draft("mistral_event", "openrouter_free_event_event_pulse_0"), Draft("deterministic_event", "det")],
        "EVENT",
    )
    assert len(event) == 1
    assert event[0].source == "openrouter_event"

    policy.install_author_pool_policy()
    import writer
    import event_writer

    assert writer.MIN_VALID_AI_DRAFTS == 1
    assert event_writer.EVENT_MIN_VALID_AI_DRAFTS == 1
    assert writer.AI_RETRIES >= 2
    assert event_writer.EVENT_AI_RETRIES >= 2
    assert writer.DETERMINISTIC_COMPARE_SLOTS == 0
    assert event_writer.EVENT_DETERMINISTIC_COMPARE_SLOTS == 0
    assert getattr(writer.generate_post_candidates, "_ai_authoritative_pool", False)
    assert getattr(event_writer.generate_event_candidates, "_ai_authoritative_pool", False)

    print("author_pool_policy_test: OK")


if __name__ == "__main__":
    main()
