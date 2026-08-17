"""Offline regression tests for DeepSeek-primary / retry / Mistral-fallback routing."""
from __future__ import annotations

import json
import os
from unittest.mock import Mock, patch

import requests

from ai_provider import request_candidates


def _ok(provider_text: str) -> Mock:
    r = Mock()
    r.status_code = 200
    r.headers = {}
    r.raise_for_status.return_value = None
    r.json.return_value = {
        "choices": [{"message": {"content": json.dumps({"candidates": [{"format_id": "hot_take", "text": provider_text}]})}}]
    }
    return r


def _http_error(status: int, body: str = "rate limited", retry_after: str | None = None) -> Mock:
    r = Mock()
    r.status_code = status
    r.headers = {"Retry-After": retry_after} if retry_after else {}
    r.text = body
    err = requests.HTTPError(f"{status}")
    err.response = r
    r.raise_for_status.side_effect = err
    return r


def main() -> None:
    env = {
        "ORCAROUTER_API_KEY": "orca-test",
        "ORCAROUTER_BASE_URL": "https://api.orcarouter.ai/v1",
        "ORCAROUTER_MODEL": "deepseek/deepseek-v4-pro-free",
        "ORCAROUTER_RETRIES": "3",
        "ORCAROUTER_RETRY_BASE_SECONDS": "0.01",
        "ORCAROUTER_RETRY_CAP_SECONDS": "0.01",
        "MISTRAL_API": "mistral-test",
    }
    kwargs = dict(system_prompt="system", user_payload={"task": "test"}, temperature=0.5, max_tokens=200, timeout=5)

    with patch.dict(os.environ, env, clear=False), patch("ai_provider.requests.post", return_value=_ok("deepseek")) as post:
        result = request_candidates(**kwargs)
        assert result.provider == "deepseek_v4_pro"
        assert result.candidates[0]["_provider"] == "deepseek_v4_pro"
        assert post.call_count == 1, "Mistral must not be contacted when DeepSeek works"
        assert post.call_args.args[0].endswith("/chat/completions")
        assert post.call_args.kwargs["json"]["model"] == "deepseek/deepseek-v4-pro-free"

    with patch.dict(os.environ, env, clear=False), patch(
        "ai_provider.requests.post",
        side_effect=[_http_error(429, '{"error":"free route busy"}'), _ok("deepseek-after-retry")],
    ) as post, patch("ai_provider.time.sleep") as sleeper:
        result = request_candidates(**kwargs)
        assert result.provider == "deepseek_v4_pro"
        assert post.call_count == 2
        assert sleeper.call_count == 1

    with patch.dict(os.environ, env, clear=False), patch(
        "ai_provider.requests.post",
        side_effect=[_http_error(503), _http_error(503), _http_error(503), _ok("mistral")],
    ) as post, patch("ai_provider.time.sleep"):
        result = request_candidates(**kwargs)
        assert result.provider == "mistral"
        assert result.candidates[0]["_provider"] == "mistral"
        assert post.call_count == 4
        assert "mistral.ai" in post.call_args_list[-1].args[0]

    print("AI PROVIDER: OK | DeepSeek primary | 429/5xx retry first | Mistral only after retry exhaustion")


if __name__ == "__main__":
    main()
