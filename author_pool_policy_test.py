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

    outage = [Draft("deterministic", "det_0"), Draft("deterministic", "det_1")]
    assert policy._ai_authoritative(outage, "TRADE") == outage

    # EVENT metadata must preserve provider and repaired-vs-clean attribution.
    event = policy._ai_authoritative(
        [Draft("mistral_event", "openrouter_free_event_event_pulse_0"), Draft("deterministic_event", "det")],
        "EVENT",
    )
    assert len(event) == 1 and event[0].source == "openrouter_event"
    repaired_meta = policy._truthful_event_source(
        Draft("mistral_event", "openrouter_free_repaired_event_event_pulse_0")
    )
    assert repaired_meta.source == "openrouter_event_repaired"

    # Reproduce the EVENT outage pattern from production: free model returns
    # meaningful prose plus an invented LONG/Entry/TP block. The unsafe block is
    # removed, the useful narrative survives, and the strict event validator is
    # still the final authority.
    package = {
        "market_event": {"ticker": "$ZEN"},
        "optional_trade_plan": {"available": False, "directional_bias": "long"},
    }
    raw = {
        "format_id": "event_pulse",
        "_provider": "openrouter_free",
        "text": (
            "$ZEN рынок снова стал заметнее\n\n"
            "LONG вход 123.45, стоп 120, TP1 130, TP2 140, TP3 150.\n\n"
            "Мне интересна сама реакция участников рынка, но один всплеск активности я не хочу превращать в готовый торговый сигнал."
        ),
    }
    repaired_rows = policy._repair_event_rows([raw], package, ["event_pulse"])
    assert len(repaired_rows) == 1
    repaired = repaired_rows[0]
    assert repaired["_provider"] == "openrouter_free_repaired"
    assert "$ZEN" in repaired["text"].splitlines()[0]
    lowered = repaired["text"].lower()
    assert "long" not in lowered and "tp1" not in lowered and "123.45" not in repaired["text"]
    valid, reasons = policy._event_row_is_valid(repaired, package)
    assert valid, reasons

    # If nothing meaningful from the model survives, it must not be counted as AI.
    garbage = {
        "format_id": "event_pulse",
        "_provider": "openrouter_free",
        "text": "$ZEN\nLONG 123\nВход 123\nСтоп 120\nTP1 130\nTP2 140\nTP3 150",
    }
    assert policy._repair_event_rows([garbage], package, ["event_pulse"]) == []

    policy.install_author_pool_policy()
    import writer
    import event_writer

    policy.verify_author_policy()
    assert writer.MIN_VALID_AI_DRAFTS == 1
    assert event_writer.EVENT_MIN_VALID_AI_DRAFTS == 1
    assert writer.AI_RETRIES >= 2
    assert event_writer.EVENT_AI_RETRIES >= 2
    assert writer.DETERMINISTIC_COMPARE_SLOTS == 0
    assert event_writer.EVENT_DETERMINISTIC_COMPARE_SLOTS == 0
    assert getattr(event_writer._request_ai_candidates, "_event_resilience", False)

    print("author_pool_policy_test: OK | EVENT repair | truthful writer_source")


if __name__ == "__main__":
    main()
