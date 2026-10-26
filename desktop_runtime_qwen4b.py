"""Strict runtime for the dedicated qwen3:4b desktop build.

Auto mode never downloads a model.  It only reuses the user's installed
qwen3:4b from Ollama.  This prevents the previous confusing fallback where the
GUI silently started downloading an 8B GGUF through llama.cpp.
"""
from __future__ import annotations

import os
import time
from typing import Optional

import requests

import local_ai_runtime as base


class Qwen4BLocalAIServer(base.LocalAIServer):
    def __init__(self) -> None:
        super().__init__()
        self.backend = "ollama"
        self.host = "127.0.0.1"
        self.port = 11434
        self.api_model = "qwen3:4b"
        self.model_label = "qwen3:4b"
        self.managed = False

    @property
    def endpoint(self) -> str:
        # The production provider still receives an OpenAI-style endpoint in
        # environment variables; ollama_native_patch converts calls to /api/chat.
        return "http://127.0.0.1:11434/v1/chat/completions"

    def _installed_qwen(self) -> Optional[str]:
        return base._probe_ollama(timeout=1.5)

    def start(self, progress: base.ProgressCallback = None) -> None:
        with self._start_lock:
            model = self._installed_qwen()
            if model:
                self.api_model = model
                self.model_label = model
                self.backend = "ollama"
                self.host = "127.0.0.1"
                self.port = 11434
                self.managed = False
                self._export_env()
                base._progress(progress, f"Найден установленный Ollama: {model}. Ничего скачивать не нужно.")
                return

            # If Ollama is installed and qwen3:4b exists on disk, start its local service.
            ollama = base.find_ollama()
            if ollama is not None and base._ollama_manifest_exists():
                if self._start_installed_ollama(progress):
                    return

            # Dedicated auto build deliberately has no model-download fallback.
            raise RuntimeError(
                "qwen3:4b не найден через Ollama. Открой приложение Ollama и убедись, "
                "что qwen3:4b отображается как установленная локальная модель. "
                "Эта сборка ничего не скачивает автоматически."
            )

    def wait_until_ready(self, timeout: float = 90.0, progress: base.ProgressCallback = None) -> bool:
        started = time.monotonic()
        next_log = started + 3.0
        deadline = started + timeout
        while time.monotonic() < deadline:
            process = self.process
            if process is not None and process.poll() is not None:
                tail = self._log_tail()
                if tail:
                    base._progress(progress, "Ollama завершился. Последние строки лога:\n" + tail)
                return False

            model = self._installed_qwen()
            if model:
                self.backend = "ollama"
                self.api_model = model
                self.model_label = model
                self._export_env()
                base._progress(progress, f"Ollama готов. Модель: {model}.")
                return True

            now = time.monotonic()
            if now >= next_log:
                base._progress(progress, f"Жду локальный Ollama… {int(now - started)} с.")
                next_log = now + 3.0
            time.sleep(0.5)
        return False

    def smoke_test(self, timeout: float = 90.0) -> str:
        payload = {
            "model": self.api_model or "qwen3:4b",
            "messages": [{"role": "user", "content": "Ответь строго JSON: {\"ok\":true}"}],
            "stream": False,
            "think": False,
            "format": "json",
            "keep_alive": "15m",
            "options": {"temperature": 0.0, "num_predict": 32},
        }
        response = requests.post(
            "http://127.0.0.1:11434/api/chat",
            json=payload,
            timeout=timeout,
        )
        if not response.ok:
            raise RuntimeError(f"Ollama HTTP {response.status_code}: {response.text[:500]}")
        data = response.json()
        message = data.get("message") if isinstance(data, dict) else None
        content = str((message or {}).get("content") or "").strip()
        if not content:
            raise RuntimeError("Ollama вернул пустой ответ")
        return content

    def stop(self) -> None:
        # Do not terminate a user's already-running Ollama application.  Only stop
        # a server process that this bot explicitly launched itself.
        if self.managed:
            super().stop()
