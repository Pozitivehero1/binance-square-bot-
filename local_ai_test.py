"""Network-free contract tests for the desktop local provider/runtime."""
from __future__ import annotations

import os

import ai_provider
import local_ai_primary
import local_ai_runtime


class _Response:
    status_code = 200
    ok = True
    text = ""

    def json(self):
        return {
            "model": "qwen3:4b",
            "choices": [
                {
                    "message": {
                        "content": '{"candidates":[{"format_id":"hot_take","text":"$BTC: тестовый локальный текст без выдуманных чисел."}]}'
                    }
                }
            ],
        }


def run() -> None:
    old_post = local_ai_primary.requests.post
    old_budget = ai_provider._budget_timeout
    keys = (
        "LOCAL_AI_BATCHES",
        "LOCAL_AI_MODEL_NAME",
        "LOCAL_AI_API_MODEL",
        "LOCAL_AI_ENDPOINT",
        "LOCAL_AI_RUNTIME_MODEL_NAME",
        "LOCAL_AI_RUNTIME_API_MODEL",
        "LOCAL_AI_RUNTIME_ENDPOINT",
    )
    previous = {key: os.environ.get(key) for key in keys}
    try:
        local_ai_primary.requests.post = lambda *args, **kwargs: _Response()
        ai_provider._budget_timeout = lambda timeout: float(timeout)

        # Simulate desktop.env containing generic llama.cpp values while the GUI
        # discovered the user's already installed Ollama qwen3:4b at runtime.
        os.environ["LOCAL_AI_BATCHES"] = "2"
        os.environ["LOCAL_AI_MODEL_NAME"] = "Qwen3-4B-Q4_K_M"
        os.environ["LOCAL_AI_API_MODEL"] = "binance-square-local"
        os.environ["LOCAL_AI_ENDPOINT"] = "http://127.0.0.1:8089/v1/chat/completions"
        os.environ["LOCAL_AI_RUNTIME_MODEL_NAME"] = "qwen3:4b"
        os.environ["LOCAL_AI_RUNTIME_API_MODEL"] = "qwen3:4b"
        os.environ["LOCAL_AI_RUNTIME_ENDPOINT"] = "http://127.0.0.1:11434/v1/chat/completions"

        assert local_ai_primary._endpoint().endswith(":11434/v1/chat/completions")
        assert local_ai_primary._model_name() == "qwen3:4b"
        assert local_ai_primary._api_model_name() == "qwen3:4b"

        body = local_ai_primary._body(
            system_prompt="Верни JSON.",
            user_payload={"test": True},
            temperature=0.5,
            max_tokens=600,
            batch_index=0,
        )
        assert body["model"] == "qwen3:4b"
        assert "/no_think" in body["messages"][0]["content"]

        result = local_ai_primary._request_local_candidates(
            system_prompt="Верни JSON.",
            user_payload={"test": True},
            temperature=0.5,
            max_tokens=600,
            timeout=30,
        )
        assert result.provider == "local_qwen"
        assert result.model == "qwen3:4b"
        assert len(result.candidates) == 1, "duplicate batches must be deduplicated"
        row = result.candidates[0]
        assert row["_provider"] == "local_qwen"
        assert row["_model"] == "qwen3:4b"
        assert row["format_id"] == "hot_take"

        tags = {
            "models": [
                {"name": "gemma3:4b"},
                {"name": "qwen3:8b"},
                {"name": "qwen3:4b"},
            ]
        }
        assert local_ai_runtime._ollama_model_from_tags(tags) == "qwen3:4b"
    finally:
        local_ai_primary.requests.post = old_post
        ai_provider._budget_timeout = old_budget
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


if __name__ == "__main__":
    run()
    print("local provider/runtime smoke test: OK")
