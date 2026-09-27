"""Dedicated Windows entrypoint for the user's installed qwen3:4b model."""
from __future__ import annotations

import os
import sys

import desktop_app as base
from desktop_runtime_qwen4b import Qwen4BLocalAIServer
from ollama_native_patch import install_native_ollama_patch

BUILD_ID = "QWEN3-4B-FIX-R2-20260916"
APP_TITLE = f"Binance Square Bot — {BUILD_ID}"
MODEL_AUTO = "qwen3:4b — установленная модель Ollama (без загрузки)"
MODEL_4B = "Qwen3 4B Q4_K_M — ручной резерв"
MODEL_8B = "Qwen3 8B Q4_K_M — ручной резерв"
MODEL_MAP = {
    MODEL_AUTO: ("Qwen/Qwen3-4B-GGUF:Q4_K_M", "qwen3:4b", "30", "1"),
    MODEL_4B: ("Qwen/Qwen3-4B-GGUF:Q4_K_M", "Qwen3-4B-Q4_K_M", "30", "0"),
    MODEL_8B: ("Qwen/Qwen3-8B-GGUF:Q4_K_M", "Qwen3-8B-Q4_K_M", "18", "0"),
}

# Patch the existing mature desktop shell rather than duplicating the bot UI.
base.APP_TITLE = APP_TITLE
base.MODEL_AUTO = MODEL_AUTO
base.MODEL_4B = MODEL_4B
base.MODEL_8B = MODEL_8B
base.MODEL_MAP = MODEL_MAP
base.LocalAIServer = Qwen4BLocalAIServer

_original_default_config = base._default_config


def _default_config():
    values = _original_default_config()
    values.update({
        "LOCAL_AI_PREFER_INSTALLED": "1",
        "LOCAL_AI_HF_MODEL": "Qwen/Qwen3-4B-GGUF:Q4_K_M",
        "LOCAL_AI_MODEL_NAME": "qwen3:4b",
        "LOCAL_AI_API_MODEL": "qwen3:4b",
        "LOCAL_AI_BACKEND": "ollama",
        "LOCAL_AI_AUTO_REQUIRE_INSTALLED": "1",
        "LOCAL_AI_BATCHES": "2",
        "LOCAL_AI_CTX": "4096",
        "MIN_GLOBAL_INTERVAL_MIN": "20",
    })
    return values


base._default_config = _default_config


class DesktopApp(base.DesktopApp):
    def __init__(self) -> None:
        super().__init__()
        self.title(APP_TITLE)
        self._append_log(f"СБОРКА: {BUILD_ID}")
        self._append_log("Режим: только установленный qwen3:4b через Ollama; автозагрузка моделей запрещена.")

    def _collect_settings(self):
        values = super()._collect_settings()
        if self.model_var.get() == MODEL_AUTO:
            values.update({
                "LOCAL_AI_PREFER_INSTALLED": "1",
                "LOCAL_AI_MODEL_NAME": "qwen3:4b",
                "LOCAL_AI_API_MODEL": "qwen3:4b",
                "LOCAL_AI_BACKEND": "ollama",
                "LOCAL_AI_AUTO_REQUIRE_INSTALLED": "1",
            })
        return values


def main() -> int:
    os.environ["BINANCE_DESKTOP_BUILD"] = BUILD_ID
    install_native_ollama_patch()
    if "--worker" in sys.argv:
        try:
            return base._run_bot_worker()
        except Exception as exc:
            print(f"DESKTOP WORKER FATAL [{BUILD_ID}]: {type(exc).__name__}: {exc}", flush=True)
            return 1
    app = DesktopApp()
    app.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
