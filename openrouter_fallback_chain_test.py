"""Offline tests for explicit OpenRouter free-model failover."""
from __future__ import annotations

import os
from unittest.mock import patch

import requests

import ai_provider
import openrouter_fallback_chain as chain


def _http_error(status: int, text: str = "error") -> requests.HTTPError:
    response = requests.Response()
    response.status_code = status
    response._content = text.encode("utf-8")
    response.url = "https://openrouter.ai/api/v1/chat/completions"
    return requests.HTTPError(f"HTTP {status}", response=response)


def main() -> None:
    original = ai_provider._request
    captured: list[tuple[str, dict, str, bool, int]] = []
    calls_by_model: dict[str, int] = {}

    def fake_request(*, url, key, body, timeout, provider, retry_without_response_format=False):
        del key
        model = str(body.get("model") or "")
        calls_by_model[model] = calls_by_model.get(model, 0) + 1
        captured.append((url, dict(body), provider, retry_without_response_format, timeout))

        # First outer batch: transport failure -> malformed JSON -> success.
        if model == "openai/gpt-oss-20b:free" and calls_by_model[model] == 1:
            raise _http_error(429, "rate limited")
        if model == "z-ai/glm-5.2:free":
            return {"choices": [{"message": {"content": "not-json"}}], "model": model}
        if model == "google/gemma-4-26b-a4b-it:free":
            return {
                "choices": [{"message": {"content": '{"candidates":[{"format_id":"hot_take","text":"gemma-ok"}]}'}}],
                "model": model,
            }

        # Second outer batch: one capacity failure, then success.
        if model == "nex-agi/nex-n2-pro:free":
            raise _http_error(503, "no capacity")
        if model == "liquid/lfm-2.5-2.6b:free":
            return {
                "choices": [{"message": {"content": '{"candidates":[{"format_id":"hot_take","text":"lfm-ok"}]}'}}],
                "model": model,
            }
        return {
            "choices": [{"message": {"content": '{"candidates":[{"format_id":"hot_take","text":"fallback-ok"}]}'}}],
            "model": model,
        }

    try:
        ai_provider._request = fake_request
        with patch.dict(
            os.environ,
            {
                "OPENROUTER_MODEL": "openai/gpt-oss-20b:free",
                "OPENROUTER_MODELS": "",
                "OPENROUTER_MODEL_TIMEOUT": "17",
            },
            clear=False,
        ):
            models = chain.configured_openrouter_models()
            assert models[:5] == [
                "openai/gpt-oss-20b:free",
                "z-ai/glm-5.2:free",
                "google/gemma-4-26b-a4b-it:free",
                "nex-agi/nex-n2-pro:free",
                "liquid/lfm-2.5-2.6b:free",
            ]
            assert chain._request_batch(models, 0) == models[:3]
            assert chain._request_batch(models, 1) == [models[3], models[4], models[0]]

            chain.install_openrouter_fallback_chain()
            patched = ai_provider._request
            chain.verify_openrouter_fallback_chain()
            assert getattr(patched, "_openrouter_multi_model_fallback", False)

            base_body = {
                "model": models[0],
                "messages": [{"role": "user", "content": "test"}],
                "response_format": {"type": "json_object"},
            }
            payload1 = patched(
                url="https://openrouter.ai/api/v1/chat/completions",
                key="test",
                body=base_body,
                timeout=55,
                provider="OpenRouter/free",
                retry_without_response_format=True,
            )
            assert payload1["model"] == models[2]
            first_models = [row[1]["model"] for row in captured[:3]]
            assert first_models == models[:3]
            assert all("models" not in row[1] for row in captured[:3])
            assert all(row[4] == 17 for row in captured[:3])

            start = len(captured)
            payload2 = patched(
                url="https://openrouter.ai/api/v1/chat/completions",
                key="test",
                body=base_body,
                timeout=55,
                provider="OpenRouter/free",
                retry_without_response_format=True,
            )
            assert payload2["model"] == models[4]
            second_models = [row[1]["model"] for row in captured[start:]]
            assert second_models == [models[3], models[4]]

            start = len(captured)
            patched(
                url="https://api.mistral.ai/v1/chat/completions",
                key="test",
                body={"model": "mistral-small-latest"},
                timeout=5,
                provider="Mistral",
            )
            non_openrouter = captured[start][1]
            assert non_openrouter == {"model": "mistral-small-latest"}

        with patch.dict(
            os.environ,
            {"OPENROUTER_MODELS": "z-ai/glm-5.2:free, openai/gpt-oss-20b:free, z-ai/glm-5.2:free"},
            clear=False,
        ):
            assert chain.configured_openrouter_models() == [
                "z-ai/glm-5.2:free",
                "openai/gpt-oss-20b:free",
            ]
    finally:
        ai_provider._request = original

    print("OPENROUTER FALLBACK CHAIN: OK | explicit model rotation | 429/503/bad-JSON failover")


if __name__ == "__main__":
    main()
