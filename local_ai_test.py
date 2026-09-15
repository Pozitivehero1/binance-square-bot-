"""Network-free contract test for the desktop local provider."""
from __future__ import annotations

import os

import ai_provider
import local_ai_primary


class _Response:
    status_code = 200
    ok = True
    text = ""

    def json(self):
        return {
            "model": "binance-square-local",
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
    old_batches = os.environ.get("LOCAL_AI_BATCHES")
    old_model = os.environ.get("LOCAL_AI_MODEL_NAME")
    old_api_model = os.environ.get("LOCAL_AI_API_MODEL")
    try:
        local_ai_primary.requests.post = lambda *args, **kwargs: _Response()
        ai_provider._budget_timeout = lambda timeout: float(timeout)
        os.environ["LOCAL_AI_BATCHES"] = "2"
        os.environ["LOCAL_AI_MODEL_NAME"] = "Qwen3.5-9B-Q4_K_M"
        os.environ["LOCAL_AI_API_MODEL"] = "binance-square-local"

        body = local_ai_primary._body(
            system_prompt="Верни JSON.",
            user_payload={"test": True},
            temperature=0.5,
            max_tokens=600,
            batch_index=0,
        )
        assert body["model"] == "binance-square-local"

        result = local_ai_primary._request_local_candidates(
            system_prompt="Верни JSON.",
            user_payload={"test": True},
            temperature=0.5,
            max_tokens=600,
            timeout=30,
        )
        assert result.provider == "local_qwen"
        assert result.model == "Qwen3.5-9B-Q4_K_M"
        assert len(result.candidates) == 1, "duplicate batches must be deduplicated"
        row = result.candidates[0]
        assert row["_provider"] == "local_qwen"
        assert row["_model"] == "Qwen3.5-9B-Q4_K_M"
        assert row["format_id"] == "hot_take"
    finally:
        local_ai_primary.requests.post = old_post
        ai_provider._budget_timeout = old_budget
        for key, value in (
            ("LOCAL_AI_BATCHES", old_batches),
            ("LOCAL_AI_MODEL_NAME", old_model),
            ("LOCAL_AI_API_MODEL", old_api_model),
        ):
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


if __name__ == "__main__":
    run()
    print("local provider smoke test: OK")
