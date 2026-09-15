"""Regression tests for the R3 qwen3:4b/Ollama desktop route."""
from __future__ import annotations

import os

import ai_provider
import local_ai_primary
import ollama_native_patch_r3


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
    old_post = ollama_native_patch_r3.requests.post
    old_budget = ai_provider._budget_timeout
    keys = (
        "BINANCE_DESKTOP_BUILD",
        "LOCAL_AI_ENDPOINT",
        "LOCAL_AI_API_MODEL",
        "LOCAL_AI_MODEL_NAME",
        "LOCAL_AI_BACKEND",
        "LOCAL_AI_PORT",
        "LOCAL_AI_RUNTIME_ENDPOINT",
        "LOCAL_AI_RUNTIME_API_MODEL",
        "LOCAL_AI_RUNTIME_MODEL_NAME",
        "LOCAL_AI_RUNTIME_BACKEND",
    )
    saved = {key: os.environ.get(key) for key in keys}
    captured = {}
    try:
        # Reproduce the exact broken state from the user's log.
        os.environ["BINANCE_DESKTOP_BUILD"] = "QWEN3-4B-FIX-R3-TEST"
        os.environ["LOCAL_AI_ENDPOINT"] = "http://127.0.0.1:8089/api/chat"
        os.environ["LOCAL_AI_RUNTIME_ENDPOINT"] = "http://127.0.0.1:8089/api/chat"
        os.environ["LOCAL_AI_API_MODEL"] = "qwen3:4b"
        os.environ["LOCAL_AI_RUNTIME_API_MODEL"] = "qwen3:4b"
        os.environ["LOCAL_AI_BACKEND"] = "ollama"
        os.environ["LOCAL_AI_RUNTIME_BACKEND"] = "ollama"

        ai_provider._budget_timeout = lambda value: float(value)

        def fake_post(url, json=None, timeout=None, **kwargs):
            captured["url"] = url
            captured["json"] = json
            captured["timeout"] = timeout
            return _Response()

        ollama_native_patch_r3.requests.post = fake_post
        ollama_native_patch_r3.install_native_ollama_patch_r3()
        result = local_ai_primary._post_local({
            "model": "qwen3:4b",
            "messages": [{"role": "system", "content": "/no_think"}],
            "temperature": 0.5,
            "top_p": 0.8,
            "max_tokens": 600,
            "stream": False,
        }, 30)

        # R3 must ignore the stale 8089 value completely.
        assert captured["url"] == "http://127.0.0.1:11434/api/chat"
        assert captured["json"]["model"] == "qwen3:4b"
        assert captured["json"]["think"] is False
        assert captured["json"]["format"] == "json"
        assert result["choices"][0]["message"]["content"].startswith("{\"candidates\"")

        import desktop_app_qwen4b_r3
        desktop_app_qwen4b_r3.force_ollama_route()
        assert os.environ["LOCAL_AI_RUNTIME_ENDPOINT"] == "http://127.0.0.1:11434/api/chat"
        assert os.environ["LOCAL_AI_ENDPOINT"] == "http://127.0.0.1:11434/api/chat"
        assert os.environ["LOCAL_AI_PORT"] == "11434"
    finally:
        ollama_native_patch_r3.requests.post = old_post
        ai_provider._budget_timeout = old_budget
        for key, value in saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


if __name__ == "__main__":
    run()
    print("qwen3:4b R3 stale-8089 regression test: OK")
