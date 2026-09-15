"""Network-free contract test for the desktop local provider."""
from __future__ import annotations

import os

import ai_provider
import local_ai_primary


class _Response:
    status_code = 200

    def raise_for_status(self):
        return None

    def json(self):
        return {
            "model": "Qwen3-4B-Q5_K_M",
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
    try:
        local_ai_primary.requests.post = lambda *args, **kwargs: _Response()
        ai_provider._budget_timeout = lambda timeout: float(timeout)
        os.environ["LOCAL_AI_BATCHES"] = "2"

        result = local_ai_primary._request_local_candidates(
            system_prompt="Верни JSON.",
            user_payload={"test": True},
            temperature=0.5,
            max_tokens=600,
            timeout=30,
        )
        assert result.provider == "local_qwen"
        assert result.model == "Qwen3-4B-Q5_K_M"
        assert len(result.candidates) == 1, "duplicate batches must be deduplicated"
        row = result.candidates[0]
        assert row["_provider"] == "local_qwen"
        assert row["_model"] == "Qwen3-4B-Q5_K_M"
        assert row["format_id"] == "hot_take"
    finally:
        local_ai_primary.requests.post = old_post
        ai_provider._budget_timeout = old_budget
        if old_batches is None:
            os.environ.pop("LOCAL_AI_BATCHES", None)
        else:
            os.environ["LOCAL_AI_BATCHES"] = old_batches


if __name__ == "__main__":
    run()
    print("local provider smoke test: OK")
