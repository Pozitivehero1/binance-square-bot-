"""Offline regression tests for DeepSeek -> OpenRouter -> Mistral routing."""
from __future__ import annotations

import json
import os
from unittest.mock import Mock, patch

import requests

from ai_provider import request_candidates


def _ok(provider_text: str, model: str | None = None) -> Mock:
    content = json.dumps({"candidates": [{"format_id": "hot_take", "text": provider_text}]})
    return _ok_raw(content, model=model)


def _ok_raw(content: str, model: str | None = None, reasoning: str | None = None) -> Mock:
    r = Mock()
    r.status_code = 200
    r.headers = {}
    r.raise_for_status.return_value = None
    message = {"content": content}
    if reasoning is not None:
        message["reasoning"] = reasoning
    payload = {"choices": [{"message": message}]}
    if model:
        payload["model"] = model
    r.json.return_value = payload
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
        "OPENROUTER_API_KEY": "openrouter-test",
        "OPENROUTER_BASE_URL": "https://openrouter.ai/api/v1",
        "OPENROUTER_MODEL": "openrouter/free",
        "OPENROUTER_RETRIES": "2",
        "OPENROUTER_RETRY_BASE_SECONDS": "0.01",
        "OPENROUTER_RETRY_CAP_SECONDS": "0.01",
        "MISTRAL_API": "mistral-test",
    }
    kwargs = dict(system_prompt="system", user_payload={"task": "test"}, temperature=0.5, max_tokens=200, timeout=5)

    with patch.dict(os.environ, env, clear=False), patch("ai_provider.requests.post", return_value=_ok("deepseek")) as post:
        result = request_candidates(**kwargs)
        assert result.provider == "deepseek_v4_pro"
        assert result.candidates[0]["_provider"] == "deepseek_v4_pro"
        assert post.call_count == 1, "Fallbacks must not be contacted when DeepSeek works"
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

    # Reproduce the production failure: a routed model returns the wanted JSON
    # plus another JSON object. The old first-{ / last-} parser raised Extra data.
    noisy_openrouter = (
        "Here is the result:\n```json\n"
        + json.dumps({"candidates": [{"format_id": "hot_take", "text": "openrouter-noisy"}]})
        + "\n```\n"
        + json.dumps({"meta": "extra block that must be ignored"})
    )
    with patch.dict(os.environ, env, clear=False), patch(
        "ai_provider.requests.post",
        side_effect=[_http_error(503), _http_error(503), _http_error(503), _ok_raw(noisy_openrouter, "free/model-routed")],
    ) as post, patch("ai_provider.time.sleep"):
        result = request_candidates(**kwargs)
        assert result.provider == "openrouter_free"
        assert result.model == "free/model-routed"
        assert result.candidates[0]["text"] == "openrouter-noisy"
        assert result.candidates[0]["_provider"] == "openrouter_free"
        assert post.call_count == 4
        assert "openrouter.ai" in post.call_args_list[-1].args[0]
        assert post.call_args_list[-1].kwargs["json"]["model"] == "openrouter/free"
        openrouter_system = post.call_args_list[-1].kwargs["json"]["messages"][0]["content"]
        assert "Return exactly one valid JSON object" in openrouter_system

    # Some reasoning routes can return empty content with the final JSON in a
    # reasoning field. This must still be usable instead of falling to Mistral.
    reasoning_json = json.dumps({"candidates": [{"format_id": "micro_note", "text": "reasoning-json"}]})
    with patch.dict(os.environ, env, clear=False), patch(
        "ai_provider.requests.post",
        side_effect=[_http_error(503), _http_error(503), _http_error(503), _ok_raw("", "free/reasoning-model", reasoning=reasoning_json)],
    ) as post, patch("ai_provider.time.sleep"):
        result = request_candidates(**kwargs)
        assert result.provider == "openrouter_free"
        assert result.candidates[0]["text"] == "reasoning-json"
        assert post.call_count == 4

    with patch.dict(os.environ, env, clear=False), patch(
        "ai_provider.requests.post",
        side_effect=[
            _http_error(503), _http_error(503), _http_error(503),
            _http_error(429), _http_error(503),
            _ok("mistral"),
        ],
    ) as post, patch("ai_provider.time.sleep"):
        result = request_candidates(**kwargs)
        assert result.provider == "mistral"
        assert result.candidates[0]["_provider"] == "mistral"
        assert post.call_count == 6
        assert "mistral.ai" in post.call_args_list[-1].args[0]

    print("AI PROVIDER: OK | DeepSeek primary | OpenRouter noisy JSON recovery | Mistral final fallback")


if __name__ == "__main__":
    main()
