"""Single cumulative startup activation and read-only release verification."""
from __future__ import annotations

import os


def activate_release() -> None:
    from reach_recovery_v11_8 import configure_environment

    # v11.10 is intentionally layered on top of the proven v11.8 distribution
    # recovery policy. Keep those recovery defaults, then stamp the new engine
    # version so dashboard cohorts do not mix the writer-hardening release with
    # the previous one.
    configure_environment()
    os.environ["BOT_VERSION"] = "v11.10"

    from production_guard import final_text_reasons
    from semantic_quality import semantic_quality_reasons

    if not semantic_quality_reasons("Активность х2 в разы подтверждает рост."):
        raise RuntimeError("semantic quality contract is incomplete")
    if not final_text_reasons("TP3 100,"):
        raise RuntimeError("final text contract is incomplete")
    if not final_text_reasons("$ORCA: Оверсаттеринг момента. Cashtag @oracetrade"):
        raise RuntimeError("v11.10 malformed-language guard is incomplete")
    if os.environ.get("BOT_VERSION") != "v11.10":
        raise RuntimeError("v11.10 version defaults were not activated")
    if os.environ.get("ADAPTIVE_HOUR_MAX") != "5":
        raise RuntimeError("v11.8 conservative ranking bounds were not preserved")
    if os.environ.get("AI_RETRIES") != "2" or os.environ.get("EVENT_AI_RETRIES") != "2":
        raise RuntimeError("author retry policy was not activated")
    if os.environ.get("ORCAROUTER_RETRIES") != "1":
        raise RuntimeError("Orca capacity retry guard was not activated")
    print("[v11.10] cumulative release verified: distribution recovery + writer hardening active")


if __name__ == "__main__":
    activate_release()
