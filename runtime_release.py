"""Single cumulative startup activation and read-only release verification."""
from __future__ import annotations

import os


def activate_release() -> None:
    from reach_recovery_v11_8 import configure_environment

    # v11.13.3 uses the exact free-tier Mistral Small 2603 model and keeps the proven
    # writer/fact-lock stack. Deterministic templates are disabled whenever an
    # AI token is configured.
    configure_environment()
    os.environ["BOT_VERSION"] = "v11.13"

    from production_guard import final_text_reasons
    from semantic_quality import semantic_quality_reasons

    if not semantic_quality_reasons("Активность х2 в разы подтверждает рост."):
        raise RuntimeError("semantic quality contract is incomplete")
    if not final_text_reasons("TP3 100,"):
        raise RuntimeError("final text contract is incomplete")
    if not final_text_reasons("$ORCA: Оверсаттеринг момента. Cashtag @oracetrade"):
        raise RuntimeError("malformed-language guard is incomplete")
    if not final_text_reasons("$ZEC — цена увеличилась на +++ за пять минут. The市场目前显示出动能."):
        raise RuntimeError("v11.13 multilingual/broken-sign guard is incomplete")
    if os.environ.get("BOT_VERSION") != "v11.13":
        raise RuntimeError("v11.13 version defaults were not activated")
    if os.environ.get("ADAPTIVE_HOUR_MAX") != "5":
        raise RuntimeError("conservative ranking bounds were not preserved")
    if os.environ.get("AI_RETRIES") != "2" or os.environ.get("EVENT_AI_RETRIES") != "2":
        raise RuntimeError("Mistral author retry policy was not activated")
    if os.environ.get("MISTRAL_MODEL") != "mistral-small-2603":
        raise RuntimeError("Mistral Small 2603 primary model was not activated")
    if os.environ.get("AI_AUTHOR_REQUIRED") != "1":
        raise RuntimeError("AI-only author policy was not activated")
    if os.environ.get("ORCAROUTER_RETRIES") != "1":
        raise RuntimeError("Orca capacity retry guard was not activated")
    print("[v11.13] cumulative release verified: Mistral primary + AI-only author policy active")


if __name__ == "__main__":
    activate_release()
