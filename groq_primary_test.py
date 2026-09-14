"""Offline regression tests for the Groq-first production author chain."""
from __future__ import annotations

import json
import os
import time
from types import SimpleNamespace
from unittest.mock import Mock, patch

import requests

import ai_provider
import groq_primary


def _ok(text: str, model: str) -> Mock:
    content = json.dumps({"candidates": [{"format_id": "hot_take", "text": text}]}, ensure_ascii=False)
    response = Mock()
    response.status_code = 200
    response.headers = {}
    response.text = content
    response.raise_for_status.return_value = None
    response.json.return_value = {
        "model": model,
        "choices": [{"message": {"content": content}}],
    }
    return response


def _http_error(status: int, body: str, retry_after: str = "60") -> Mock:
    response = Mock()
    response.status_code = status
    response.headers = {"Retry-After": retry_after}
    response.text = body
    error = requests.HTTPError(str(status))
    error.response = response
    response.raise_for_status.side_effect = error
    return response


def main() -> None:
    env = {
        "GROQ_API_KEY": "groq-test",
        "GROQ_MODEL": "qwen/qwen3.8-27b",
        "GROQ_BACKUP_MODEL": "openai/gpt-oss-120b",
        "GROQ_MODELS": "qwen/qwen3.8-27b,openai/gpt-oss-120b",
        "GROQ_RETRIES": "2",
        "GROQ_MODEL_TIMEOUT": "10",
        "GROQ_MAX_TOKENS": "700",
        "GROQ_QWEN_MAX_TOKENS": "520",
        "GROQ_GPT_OSS_MAX_TOKENS": "700",
        "GROQ_MAX_REQUESTS_PER_MODEL_PER_SCAN": "1",
        "GROQ_RATE_LIMIT_COOLDOWN_CAP_SECONDS": "30",
        "MISTRAL_API": "",
        "ORCAROUTER_API_KEY": "",
        "OPENROUTER_API_KEY": "",
        "DRY_RUN": "1",
    }
    kwargs = dict(
        system_prompt="Верни JSON",
        user_payload={"task": "test", "candidate_count": 1},
        temperature=0.6,
        max_tokens=1200,
        timeout=15,
        presence_penalty=0.4,
        frequency_penalty=0.2,
    )

    groq_primary.install_groq_primary()

    # The Qwen request must stay comfortably below its observed 1000 OTPM cap.
    with patch.dict(os.environ, env, clear=False), patch(
        "groq_primary.requests.post",
        return_value=_ok("groq-primary", "qwen/qwen3.8-27b"),
    ) as post:
        assert ai_provider.has_ai_provider()
        assert ai_provider.preferred_provider_name() == "groq"
        result = ai_provider.request_candidates(**kwargs)
        assert result.provider == "groq"
        assert result.model == "qwen/qwen3.8-27b"
        assert result.candidates[0]["_provider"] == "groq"
        assert result.candidates[0]["_model"] == "qwen/qwen3.8-27b"
        body = post.call_args.kwargs["json"]
        assert body["model"] == "qwen/qwen3.8-27b"
        assert body["response_format"] == {"type": "json_object"}
        assert body["reasoning_effort"] == "none"
        assert body["reasoning_format"] == "hidden"
        assert body["max_completion_tokens"] == 520
        assert "presence_penalty" not in body
        assert "frequency_penalty" not in body

    # Any Groq 429 must switch models immediately. Retrying the same model in
    # the same second only burns its TPM/OTPM window and was the production bug.
    groq_primary._reset_scan_state()
    with patch.dict(os.environ, env, clear=False), patch(
        "groq_primary.requests.post",
        side_effect=[
            _http_error(429, "Please try again in 10.2s", retry_after="10.2"),
            _ok("groq-backup", "openai/gpt-oss-120b"),
        ],
    ) as post, patch("groq_primary.time.sleep") as sleeper:
        result = ai_provider.request_candidates(**kwargs)
        assert result.provider == "groq"
        assert result.model == "openai/gpt-oss-120b"
        assert result.candidates[0]["text"] == "groq-backup"
        assert post.call_count == 2
        assert sleeper.call_count == 0
        second_body = post.call_args.kwargs["json"]
        assert second_body["model"] == "openai/gpt-oss-120b"
        assert second_body["reasoning_effort"] == "low"
        assert second_body["max_completion_tokens"] == 700

    # During a real scan, each model has a small request budget. A second call
    # cannot hammer Qwen again; it moves directly to GPT-OSS.
    with patch.dict(os.environ, env, clear=False), patch(
        "groq_primary.requests.post",
        side_effect=[
            _ok("first-qwen", "qwen/qwen3.8-27b"),
            _ok("second-gpt", "openai/gpt-oss-120b"),
        ],
    ) as post:
        ai_provider.start_scan_budget(time.monotonic() + 60, max_requests=5)
        first = ai_provider.request_candidates(**kwargs)
        second = ai_provider.request_candidates(**kwargs)
        assert first.model == "qwen/qwen3.8-27b"
        assert second.model == "openai/gpt-oss-120b"
        assert post.call_count == 2
        assert post.call_args.kwargs["json"]["model"] == "openai/gpt-oss-120b"
        ai_provider.start_scan_budget(None, None)

    # Source reporting must say Groq, not the legacy hard-coded Mistral label,
    # and the production writers must have the no-waste retry guard installed.
    groq_primary.install_provider_source_tracking()
    import reach_recovery_v11_8
    import author_pool_policy
    import writer
    import event_writer

    reach_recovery_v11_8._LAST_AI_PROVIDER = "groq"
    assert reach_recovery_v11_8._source_name_v118("mistral") == "groq"

    event = SimpleNamespace(style_id="groq_event_hot_take_0", source="mistral_event")
    normalized = author_pool_policy._truthful_event_source(event)
    assert normalized.source == "groq_event"
    assert getattr(writer.generate_post_candidates, "_groq_retry_guard", False)
    assert getattr(event_writer.generate_event_candidates, "_groq_retry_guard", False)

    groq_primary.verify_groq_primary(require_key=False)
    print(
        "GROQ PRIMARY: OK | Qwen 520-token cap -> GPT-OSS 700-token cap -> legacy AI fallbacks | "
        "429 instant failover | per-scan model budgets | no-waste writer retries"
    )


if __name__ == "__main__":
    main()
