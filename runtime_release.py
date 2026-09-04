"""Single cumulative startup activation and read-only release verification."""
from __future__ import annotations

import os


def activate_release() -> None:
    from reach_recovery_v11_8 import configure_environment

    configure_environment()

    from production_guard import final_text_reasons
    from semantic_quality import semantic_quality_reasons

    if not semantic_quality_reasons("Активность х2 в разы подтверждает рост."):
        raise RuntimeError("v11.8 semantic quality contract is incomplete")
    if not final_text_reasons("TP3 100,"):
        raise RuntimeError("v11.8 final text contract is incomplete")
    if os.environ.get("BOT_VERSION") != "v11.8":
        raise RuntimeError("v11.8 version defaults were not activated")
    if os.environ.get("ADAPTIVE_HOUR_MAX") != "5":
        raise RuntimeError("v11.8 conservative ranking bounds were not activated")
    if os.environ.get("EVENT_AI_RETRIES") != "1":
        raise RuntimeError("v11.8 provider retry guard was not activated")
    print("[v11.8] cumulative release verified: distribution recovery active")


if __name__ == "__main__":
    activate_release()
