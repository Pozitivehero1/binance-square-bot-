"""Offline tests for OpenRouter multi-model failover wiring."""
from __future__ import annotations

import os
from unittest.mock import patch

import ai_provider
import openrouter_fallback_chain as chain


def main() -> None:
    original = ai_provider._request
    captured = []

    def fake_request(*, url, key, body, timeout, provider, retry_without_response_format=False):
        captured.append((url, dict(body), provider, retry_without_response_format))
        model = (body.get("models") or [body.get("model")])[0]
        return {"choices": [{"message": {"content": '{"candidates":[{"format_id":"hot_take","text":"ok"}]}'}}], "model": model}

    try:
        ai_provider._request = fake_request
        env = {
            "OPENROUTER_MODEL": "openai/gpt-oss-20b:free",
            "OPENROUTER_MODELS": "",
        }
        with patch.dict(os.environ, env, clear=False):
            models = chain.configured_openrouter_models()
            assert models[:5] == [
                "openai/gpt-oss-20b:free",
                "z-ai/glm-5.2:free",
                "google/gemma-4-26b-a4b-it:free",
                "nex-agi/nex-n2-pro:free",
                "liquid/lfm-2.5-2.6b:free",
            ]

            chain.install_openrouter_fallback_chain()
            patched = ai_provider._request
            assert getattr(patched, "_openrouter_multi_model_fallback", False)

            base_body = {
                "model": "openai/gpt-oss-20b:free",
                "messages": [{"role": "user", "content": "test"}],
                "response_format": {"type": "json_object"},
            }
            patched(
                url="https://openrouter.ai/api/v1/chat/completions",
                key="test",
                body=base_body,
                timeout=5,
                provider="OpenRouter/free",
                retry_without_response_format=True,
            )
            first = captured[-1][1]
            assert "model" not in first
            assert first["models"] == models
            assert first["response_format"] == {"type": "json_object"}

            patched(
                url="https://openrouter.ai/api/v1/chat/completions",
                key="test",
                body=base_body,
                timeout=5,
                provider="OpenRouter/free",
                retry_without_response_format=True,
            )
            second = captured[-1][1]
            assert second["models"][0] == models[1]
            assert second["models"][-1] == models[0]

            patched(
                url="https://api.mistral.ai/v1/chat/completions",
                key="test",
                body={"model": "mistral-small-latest"},
                timeout=5,
                provider="Mistral",
            )
            non_openrouter = captured[-1][1]
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

    print("OPENROUTER FALLBACK CHAIN: OK | 5 models | server failover + retry rotation")


if __name__ == "__main__":
    main()
