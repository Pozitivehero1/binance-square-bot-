"""Network-free contract test for the dedicated qwen3:4b desktop build."""
from __future__ import annotations

import os

import ai_provider
import local_ai_primary
import local_ai_runtime
import ollama_native_patch
from desktop_runtime_qwen4b import Qwen4BLocalAIServer


class _Response:
    ok = True
    status_code = 200
    text = ""

    def json(self):
        return {
            "model": "qwen3:4b",
            "message": {
                "role": "assistant",
                "content": '{"candidates":[{"format_id":"hot_take","text":"$BTC: тест."}]}'
            },
        }


def run() -> None:
    old_probe = local_ai_runtime._probe_ollama
    old_post = ollama_native_patch.requests.post
    old_budget = ai_provider._budget_timeout
    saved_env = {key: os.environ.get(key) for key in (
        "LOCAL_AI_RUNTIME_BACKEND",
        "LOCAL_AI_RUNTIME_ENDPOINT",
        "LOCAL_AI_RUNTIME_API_MODEL",
        "LOCAL_AI_RUNTIME_MODEL_NAME",
        "LOCAL_AI_BACKEND",
    )}
    captured = {}
    try:
        local_ai_runtime._probe_ollama = lambda timeout=1.2: "qwen3:4b"
        server = Qwen4BLocalAIServer()
        logs = []
        server.start(progress=logs.append)
        assert server.backend == "ollama"
        assert server.api_model == "qwen3:4b"
        assert "11434" in server.endpoint
        assert any("Ничего скачивать не нужно" in row for row in logs)

        os.environ["LOCAL_AI_RUNTIME_BACKEND"] = "ollama"
        os.environ["LOCAL_AI_RUNTIME_ENDPOINT"] = server.endpoint
        os.environ["LOCAL_AI_RUNTIME_API_MODEL"] = "qwen3:4b"
        os.environ["LOCAL_AI_RUNTIME_MODEL_NAME"] = "qwen3:4b"
        ai_provider._budget_timeout = lambda value: float(value)

        def fake_post(url, json=None, timeout=None, **kwargs):
            captured["url"] = url
            captured["json"] = json
            captured["timeout"] = timeout
            return _Response()

        ollama_native_patch.requests.post = fake_post
        ollama_native_patch.install_native_ollama_patch()
        result = local_ai_primary._post_local({
            "model": "qwen3:4b",
            "messages": [{"role": "system", "content": "/no_think"}],
            "temperature": 0.5,
            "top_p": 0.8,
            "max_tokens": 600,
            "stream": False,
        }, 30)
        assert captured["url"] == "http://127.0.0.1:11434/api/chat"
        assert captured["json"]["model"] == "qwen3:4b"
        assert captured["json"]["think"] is False
        assert captured["json"]["format"] == "json"
        assert result["choices"][0]["message"]["content"].startswith("{\"candidates\"")
    finally:
        local_ai_runtime._probe_ollama = old_probe
        ollama_native_patch.requests.post = old_post
        ai_provider._budget_timeout = old_budget
        for key, value in saved_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


if __name__ == "__main__":
    run()
    print("qwen3:4b fixed desktop smoke test: OK")
