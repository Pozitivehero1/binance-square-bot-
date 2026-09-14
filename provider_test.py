"""Offline regression tests for Mistral-primary AI routing."""
from __future__ import annotations

import json
import os
from unittest.mock import Mock, patch

import requests

from ai_provider import preferred_provider_name, request_candidates


def _ok(provider_text: str, model: str | None = None) -> Mock:
    content = json.dumps({"candidates": [{"format_id": "hot_take", "text": provider_text}]})
    response = Mock()
    response.status_code = 200
    response.headers = {}
    response.text = content
    response.raise_for_status.return_value = None
    payload = {"choices": [{"message": {"content": content}}]}
    if model:
        payload["model"] = model
    response.json.return_value = payload
    return response


def _http_error(status: int, body: str = "temporarily unavailable") -> Mock:
    response = Mock()
    response.status_code = status
    response.headers = {}
    response.text = body
    error = requests.HTTPError(str(status))
    error.response = response
    response.raise_for_status.side_effect = error
    return response


def main() -> None:
    env = {
        "MISTRAL_API": "mistral-test",
        "MISTRAL_MODEL": "mistral-small-2603",
        "MISTRAL_RETRIES": "3",
        "MISTRAL_RETRY_BASE_SECONDS": "0.01",
        "MISTRAL_RETRY_CAP_SECONDS": "0.01",
        "ORCAROUTER_API_KEY": "orca-test",
        "ORCAROUTER_BASE_URL": "https://api.orcarouter.ai/v1",
        "ORCAROUTER_MODEL": "deepseek/deepseek-v4-pro-free",
        "ORCAROUTER_RETRIES": "1",
        "OPENROUTER_API_KEY": "openrouter-test",
        "OPENROUTER_BASE_URL": "https://openrouter.ai/api/v1",
        "OPENROUTER_MODEL": "openrouter/free",
        "OPENROUTER_RETRIES": "1",
    }
    kwargs = dict(
        system_prompt="system",
        user_payload={"task": "test", "semantic_package": {}},
        temperature=0.5,
        max_tokens=200,
        timeout=5,
    )

    with patch.dict(os.environ, env, clear=False), patch(
        "ai_provider.requests.post", return_value=_ok("mistral")
    ) as post:
        assert preferred_provider_name() == "mistral"
        result = request_candidates(**kwargs)
        assert result.provider == "mistral"
        assert result.model == "mistral-small-2603"
        assert result.candidates[0]["_provider"] == "mistral"
        assert post.call_count == 1
        assert "mistral.ai" in post.call_args.args[0]
        body = post.call_args.kwargs["json"]
        assert body["model"] == "mistral-small-2603"
        assert "КРИТИЧЕСКИЙ КОНТРАКТ ОТВЕТА" in body["messages"][0]["content"]

    with patch.dict(os.environ, env, clear=False), patch(
        "ai_provider.requests.post",
        side_effect=[_http_error(503), _http_error(429), _ok("mistral-after-retry")],
    ) as post, patch("ai_provider.time.sleep") as sleeper:
        result = request_candidates(**kwargs)
        assert result.provider == "mistral"
        assert result.candidates[0]["text"] == "mistral-after-retry"
        assert post.call_count == 3
        assert sleeper.call_count == 2
        retry_messages = post.call_args.kwargs["json"]["messages"]
        assert any("Предыдущий ответ не прошёл" in item["content"] for item in retry_messages)

    with patch.dict(os.environ, env, clear=False), patch(
        "ai_provider.requests.post",
        side_effect=[_http_error(503), _http_error(503), _http_error(503), _ok("deepseek-fallback")],
    ) as post, patch("ai_provider.time.sleep"):
        result = request_candidates(**kwargs)
        assert result.provider == "deepseek_v4_pro"
        assert result.candidates[0]["text"] == "deepseek-fallback"
        assert post.call_count == 4
        assert "orcarouter.ai" in post.call_args.args[0]

    no_mistral = dict(env)
    no_mistral["MISTRAL_API"] = ""
    with patch.dict(os.environ, no_mistral, clear=False), patch(
        "ai_provider.requests.post", return_value=_ok("deepseek-direct")
    ) as post:
        assert preferred_provider_name() == "deepseek_v4_pro"
        result = request_candidates(**kwargs)
        assert result.provider == "deepseek_v4_pro"
        assert post.call_count == 1

    print("AI PROVIDER: OK | Mistral Small 2603 primary | 3 retries | AI fallbacks preserved")


if __name__ == "__main__":
    main()
