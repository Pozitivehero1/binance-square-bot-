"""Verify the actual run_bot import order installs every production policy."""
from __future__ import annotations

import os


def main() -> int:
    os.environ["DRY_RUN"] = "1"

    # Importing run_bot activates policies but does not execute main().
    import run_bot  # noqa: F401
    import ai_provider
    import event_writer
    import recovery_guard
    import writer

    assert os.environ.get("BOT_VERSION") == "v11.8"
    assert os.environ.get("AI_RETRIES") == "2"
    assert os.environ.get("EVENT_AI_RETRIES") == "2"
    assert os.environ.get("ORCAROUTER_RETRIES") == "1"

    assert getattr(ai_provider._request, "_openrouter_multi_model_fallback", False)
    assert getattr(event_writer._request_ai_candidates, "_event_resilience", False)
    assert getattr(writer.generate_post_candidates, "_ai_authoritative_pool", False)
    assert getattr(event_writer.generate_event_candidates, "_ai_authoritative_pool", False)
    assert getattr(recovery_guard.evaluate_recovery_candidate, "_v118_live_recovery_exit", False)
    assert writer._build_generated.__module__ == "reach_recovery_v11_8"

    assert writer.MIN_VALID_AI_DRAFTS == 1
    assert event_writer.EVENT_MIN_VALID_AI_DRAFTS == 1
    assert writer.DETERMINISTIC_COMPARE_SLOTS == 0
    assert event_writer.EVENT_DETERMINISTIC_COMPARE_SLOTS == 0

    print("RUNTIME POLICY: OK | production startup order and all critical patches active")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
