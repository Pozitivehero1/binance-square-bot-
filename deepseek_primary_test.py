"""Offline primary/fallback, rate-limit, budget and attribution checks."""
import json
import os
import time
from types import SimpleNamespace
from unittest.mock import Mock, patch

import ai_provider
import deepseek_primary as deepseek
import groq_primary as chain
import requests


def response(status=200, content=None):
    value = Mock()
    value.status_code = status
    value.headers = {"Retry-After": "900"} if status == 429 else {}
    value.text = "Never log Bearer deepseek-test-key"
    value.json.return_value = {"choices": [{"message": {"content": content or json.dumps({
        "candidates": [{"format_id": "hot_take", "text": "Русский тестовый текст"}]
    })}}]}
    if status >= 400:
        error = requests.HTTPError(str(status))
        error.response = value
        value.raise_for_status.side_effect = error
    return value


def main():
    env = {"DEEPSEEK_API_KEY": "deepseek-test-key", "DEEPSEEK_BASE_URL": "https://api.example/v1",
           "DEEPSEEK_MODEL": "deepseek-chat", "DEEPSEEK_MODEL_TIMEOUT": "25",
           "GROQ_API_KEY": "groq-test-key", "GEMINI_API_KEY": "", "MISTRAL_API": "",
           "MISTRAL_API_KEY": "", "ORCAROUTER_API_KEY": "", "ORCA_API_KEY": "",
           "OPENROUTER_API_KEY": "", "GROQ_MODELS": "qwen/qwen3.8-27b", "DRY_RUN": "1"}
    kwargs = dict(system_prompt="Верни candidates", user_payload={"task": "test"},
                  temperature=0.4, max_tokens=1000, timeout=60)
    chain.install_groq_primary()
    with patch.dict(os.environ, env):
        deepseek._COOLDOWN_UNTIL = 0
        with patch("deepseek_primary.requests.post", return_value=response()) as post:
            result = ai_provider.request_candidates(**kwargs)
            assert result.provider == "deepseek_local"
            assert result.candidates[0]["_provider"] == "deepseek_local"
            assert ai_provider.preferred_provider_name() == "deepseek_local"
            assert post.call_count == 1
            assert post.call_args.args[0] == "https://api.example/v1/chat/completions"
            assert post.call_args.kwargs["json"]["stream"] is False
            assert post.call_args.kwargs["json"]["model"] == "deepseek-chat"
            assert post.call_args.kwargs["timeout"] == (5.0, 25.0)
            assert post.call_args.kwargs["allow_redirects"] is False
            first_user = post.call_args.kwargs['json']['user']
            ai_provider.request_candidates(**kwargs)
            assert post.call_args.kwargs['json']['user'] != first_user

        # Every unusable primary must hand off to Groq without an immediate retry.
        for bad in [response(401), response(403), response(429), response(503),
                    response(content="not JSON"), response(content='{"candidates":[{"text":""}]}'),
                    requests.Timeout("timeout"), requests.ConnectionError("offline")]:
            deepseek._COOLDOWN_UNTIL = 0
            with patch("deepseek_primary.requests.post", side_effect=[bad, response()]) as post:
                result = ai_provider.request_candidates(**kwargs)
                assert result.provider == "groq"
                assert post.call_count == 2
                assert "groq.com" in post.call_args.args[0]
                assert deepseek._COOLDOWN_UNTIL > time.monotonic()

        deepseek._COOLDOWN_UNTIL = 0
        with patch("deepseek_primary.requests.post", side_effect=[response(429), response(), response()]) as post:
            start = time.monotonic()
            assert ai_provider.request_candidates(**kwargs).provider == "groq"
            assert deepseek._COOLDOWN_UNTIL >= start + 900
            assert ai_provider.request_candidates(**kwargs).provider == "groq"
            assert post.call_count == 3  # Second batch skips the limited primary.

        # Existing Gemini remains first in the preserved fallback chain.
        deepseek._COOLDOWN_UNTIL = 0
        with patch.dict(os.environ, {"GEMINI_API_KEY": "gemini-test"}), patch(
                "deepseek_primary.requests.post", side_effect=[response(503), response()]) as post:
            assert ai_provider.request_candidates(**kwargs).provider == "gemini"
            assert "googleapis.com" in post.call_args.args[0]

        with patch.dict(os.environ, {"GROQ_API_KEY": ""}):
            assert ai_provider.has_ai_provider()
            chain.verify_groq_primary(require_key=True)

        deepseek._COOLDOWN_UNTIL = 0
        ai_provider.start_scan_budget(time.monotonic() + 60, 0)
        with patch("deepseek_primary.requests.post") as post:
            try:
                ai_provider.request_candidates(**kwargs)
            except RuntimeError:
                pass
            else:
                raise AssertionError("Exhausted scan budget must not make a request")
            assert post.call_count == 0
        ai_provider.start_scan_budget(None, None)

        chain.install_provider_source_tracking()
        import reach_recovery_v11_8 as tracking
        import author_pool_policy
        tracking._LAST_AI_PROVIDER = "deepseek_local"
        assert tracking._source_name_v118("mistral") == "deepseek_local"
        for prefix, expected in [("deepseek_local_event_", "deepseek_local_event"),
                                 ("deepseek_local_repaired_event_", "deepseek_local_event_repaired")]:
            draft = SimpleNamespace(style_id=prefix + "hot_take_0", source="mistral_event")
            assert author_pool_policy._truthful_event_source(draft).source == expected

        for url in ["http://public.example/v1", "https://user:password@api.example/v1", "https://api.example/v1?key=bad"]:
            with patch.dict(os.environ, {"DEEPSEEK_BASE_URL": url}):
                try:
                    deepseek.endpoint()
                except ValueError:
                    pass
                else:
                    raise AssertionError("Unsafe URL accepted")
        with patch.dict(os.environ, {"DEEPSEEK_API_KEY": ""}):
            assert ai_provider.preferred_provider_name() == "groq"
    print("DEEPSEEK PRIMARY: OK | fallback, cooldown, budget and source attribution")


if __name__ == "__main__":
    main()
