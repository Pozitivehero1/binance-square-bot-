"""R3 dedicated Windows entrypoint for installed qwen3:4b via Ollama only."""
from __future__ import annotations

import os
import sys

import desktop_app as base
from desktop_runtime_qwen4b import Qwen4BLocalAIServer
from ollama_native_patch_r3 import install_native_ollama_patch_r3

BUILD_ID = "QWEN3-4B-FIX-R3-20260916"
APP_TITLE = f"Binance Square Bot — {BUILD_ID}"
MODEL_AUTO = "qwen3:4b — Ollama, без загрузки"
MODEL_MAP = {
    MODEL_AUTO: ("Qwen/Qwen3-4B-GGUF:Q4_K_M", "qwen3:4b", "30", "1"),
}
_RUNTIME_KEYS = (
    "LOCAL_AI_RUNTIME_ENDPOINT",
    "LOCAL_AI_RUNTIME_API_MODEL",
    "LOCAL_AI_RUNTIME_MODEL_NAME",
    "LOCAL_AI_RUNTIME_BACKEND",
)


def force_ollama_route() -> None:
    """Hard-lock the dedicated build to the user's local Ollama server."""
    values = {
        "LOCAL_AI_ENDPOINT": "http://127.0.0.1:11434/api/chat",
        "LOCAL_AI_API_MODEL": "qwen3:4b",
        "LOCAL_AI_MODEL_NAME": "qwen3:4b",
        "LOCAL_AI_BACKEND": "ollama",
        "LOCAL_AI_PORT": "11434",
        "LOCAL_AI_RUNTIME_ENDPOINT": "http://127.0.0.1:11434/api/chat",
        "LOCAL_AI_RUNTIME_API_MODEL": "qwen3:4b",
        "LOCAL_AI_RUNTIME_MODEL_NAME": "qwen3:4b",
        "LOCAL_AI_RUNTIME_BACKEND": "ollama",
        "LOCAL_AI_PREFER_INSTALLED": "1",
        "LOCAL_AI_AUTO_REQUIRE_INSTALLED": "1",
    }
    os.environ.update(values)


base.APP_TITLE = APP_TITLE
base.MODEL_AUTO = MODEL_AUTO
base.MODEL_4B = MODEL_AUTO
base.MODEL_8B = MODEL_AUTO
base.MODEL_MAP = MODEL_MAP
base.LocalAIServer = Qwen4BLocalAIServer

_original_default_config = base._default_config
_original_load_config = base.load_config
_original_apply_config_to_env = base.apply_config_to_env


def _default_config():
    values = _original_default_config()
    values.update({
        "LOCAL_AI_PREFER_INSTALLED": "1",
        "LOCAL_AI_MODEL_NAME": "qwen3:4b",
        "LOCAL_AI_API_MODEL": "qwen3:4b",
        "LOCAL_AI_BACKEND": "ollama",
        "LOCAL_AI_PORT": "11434",
        "LOCAL_AI_AUTO_REQUIRE_INSTALLED": "1",
        "LOCAL_AI_BATCHES": "2",
        "LOCAL_AI_CTX": "4096",
        "MIN_GLOBAL_INTERVAL_MIN": "20",
    })
    for key in _RUNTIME_KEYS:
        values.pop(key, None)
    return values


def _load_config():
    values = _original_load_config()
    # Never let stale R1/R2 runtime values from desktop.env survive in this build.
    for key in _RUNTIME_KEYS:
        values.pop(key, None)
    values.update({
        "LOCAL_AI_PREFER_INSTALLED": "1",
        "LOCAL_AI_MODEL_NAME": "qwen3:4b",
        "LOCAL_AI_API_MODEL": "qwen3:4b",
        "LOCAL_AI_BACKEND": "ollama",
        "LOCAL_AI_PORT": "11434",
        "LOCAL_AI_AUTO_REQUIRE_INSTALLED": "1",
        "LOCAL_AI_BATCHES": "2",
        "MIN_GLOBAL_INTERVAL_MIN": "20",
    })
    return values


def _apply_config_to_env(values):
    _original_apply_config_to_env(values)
    # base.apply_config_to_env can construct the old 8089 endpoint; overwrite it last.
    force_ollama_route()


base._default_config = _default_config
base.load_config = _load_config
base.apply_config_to_env = _apply_config_to_env


class DesktopApp(base.DesktopApp):
    def __init__(self) -> None:
        force_ollama_route()
        super().__init__()
        self.title(APP_TITLE)
        self._append_log(f"СБОРКА: {BUILD_ID}")
        self._append_log("Маршрут ИИ зафиксирован: Ollama qwen3:4b -> 127.0.0.1:11434/api/chat")
        self._append_log("Автозагрузка моделей отключена.")

    def _collect_settings(self):
        values = super()._collect_settings()
        for key in _RUNTIME_KEYS:
            values.pop(key, None)
        values.update({
            "LOCAL_AI_PREFER_INSTALLED": "1",
            "LOCAL_AI_MODEL_NAME": "qwen3:4b",
            "LOCAL_AI_API_MODEL": "qwen3:4b",
            "LOCAL_AI_BACKEND": "ollama",
            "LOCAL_AI_PORT": "11434",
            "LOCAL_AI_AUTO_REQUIRE_INSTALLED": "1",
        })
        return values


def main() -> int:
    os.environ["BINANCE_DESKTOP_BUILD"] = BUILD_ID
    force_ollama_route()
    install_native_ollama_patch_r3()
    if "--worker" in sys.argv:
        # Force again immediately before the production worker loads config/providers.
        force_ollama_route()
        print(
            "QWEN4B WORKER ROUTE endpoint=http://127.0.0.1:11434/api/chat "
            "model=qwen3:4b backend=ollama",
            flush=True,
        )
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
