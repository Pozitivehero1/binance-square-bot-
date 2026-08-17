"""Offline regression tests for DeepSeek-primary / Mistral-fallback routing."""
from __future__ import annotations

import json
import os
from unittest.mock import Mock, patch

import requests

from ai_provider import request_candidates


def _ok(provider_text: str) -> Mock:
    r = Mock()
    r.status_code = 200
    r.raise_for_status.return_value = None
    r.json.return_value = {
        "choices": [{"message": {"content": json.dumps({"candidates": [{"format_id": "hot_take", "text": provider_text}]})}}]
    }
    return r


def main() -> None:
    env = {
        "ORCAROUTER_API_KEY": "orca-test",
        "ORCAROUTER_BASE_URL": "https://api.orcarouter.ai/v1",
        "ORCAROUTER_MODEL": "deepseek/deepseek-v4-pro-free",
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

    failed = Mock()
    failed.status_code = 503
    failed.raise_for_status.side_effect = requests.HTTPError("503")
    with patch.dict(os.environ, env, clear=False), patch("ai_provider.requests.post", side_effect=[failed, _ok("mistral")]) as post:
        result = request_candidates(**kwargs)
        assert result.provider == "mistral"
        assert result.candidates[0]["_provider"] == "mistral"
        assert post.call_count == 2
        assert "mistral.ai" in post.call_args_list[1].args[0]

    print("AI PROVIDER: OK | DeepSeek primary | Mistral only on primary API failure")


if __name__ == "__main__":
    main()
