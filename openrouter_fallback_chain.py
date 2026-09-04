"""Explicit OpenRouter free-model failover for v11.8.

Do not rely on one routed `models` array to rescue an upstream 429/503. The
wrapper tries concrete free models itself, validates that the HTTP response
contains parseable candidate JSON, and only then returns it to ai_provider.
Two outer OpenRouter attempts rotate through the five-model pool.
"""
from __future__ import annotations

from functools import wraps
import logging
import os
from typing import List

import requests

import ai_provider

logger = logging.getLogger(__name__)

DEFAULT_OPENROUTER_MODELS = (
    "openai/gpt-oss-20b:free",
    "z-ai/glm-5.2:free",
    "google/gemma-4-26b-a4b-it:free",
    "nex-agi/nex-n2-pro:free",
    "liquid/lfm-2.5-2.6b:free",
)

OPENROUTER_MODELS_PER_REQUEST = 3


def configured_openrouter_models() -> List[str]:
    """Return a unique priority-ordered OpenRouter model chain."""
    explicit = [
        item.strip()
        for item in os.getenv("OPENROUTER_MODELS", "").split(",")
        if item.strip()
    ]
    primary = os.getenv("OPENROUTER_MODEL", "").strip()

    candidates: List[str] = []
    if explicit:
        candidates.extend(explicit)
    else:
        if primary:
            candidates.append(primary)
        candidates.extend(DEFAULT_OPENROUTER_MODELS)

    unique: List[str] = []
    seen = set()
    for model in candidates:
        if model and model not in seen:
            seen.add(model)
            unique.append(model)
    return unique or list(DEFAULT_OPENROUTER_MODELS)


def _rotated(models: List[str], offset: int) -> List[str]:
    if not models:
        return []
    pos = offset % len(models)
    return models[pos:] + models[:pos]


def _request_batch(models: List[str], call_index: int) -> List[str]:
    """Return at most three concrete models, rotating across outer retries."""
    if not models:
        return []
    offset = (call_index * OPENROUTER_MODELS_PER_REQUEST) % len(models)
    return _rotated(models, offset)[:OPENROUTER_MODELS_PER_REQUEST]


def _model_error_is_fallbackable(exc: Exception) -> bool:
    if isinstance(exc, requests.HTTPError):
        response = exc.response
        status = int(response.status_code) if response is not None else 0
        # Auth/account failures are global; model/rate/capacity/format failures
        # are worth trying on the next free model.
        return status in {400, 404, 408, 409, 422, 425, 429, 500, 502, 503, 504}
    return isinstance(
        exc,
        (requests.Timeout, requests.ConnectionError, ValueError, KeyError, TypeError),
    )


def install_openrouter_fallback_chain() -> None:
    """Patch ai_provider._request with explicit model-by-model OpenRouter failover."""
    current = ai_provider._request
    if getattr(current, "_openrouter_multi_model_fallback", False):
        return

    call_index = 0

    @wraps(current)
    def wrapped_request(
        *,
        url: str,
        key: str,
        body: dict,
        timeout: int,
        provider: str,
        retry_without_response_format: bool = False,
    ) -> dict:
        nonlocal call_index
        is_openrouter = "openrouter.ai" in str(url).lower() or str(provider).lower().startswith("openrouter")
        if not is_openrouter:
            return current(
                url=url,
                key=key,
                body=body,
                timeout=timeout,
                provider=provider,
                retry_without_response_format=retry_without_response_format,
            )

        models = configured_openrouter_models()
        batch = _request_batch(models, call_index)
        call_index += 1
        if not batch:
            raise RuntimeError("OpenRouter fallback model pool is empty")

        per_model_timeout = max(8, min(int(os.getenv("OPENROUTER_MODEL_TIMEOUT", "24")), int(timeout)))
        logger.info(
            "OpenRouter explicit fallback batch=%s configured=%s per_model_timeout=%ss",
            " -> ".join(batch), len(models), per_model_timeout,
        )

        last_exc: Exception | None = None
        for position, model in enumerate(batch, start=1):
            routed_body = dict(body)
            routed_body.pop("models", None)
            routed_body["model"] = model
            try:
                payload = current(
                    url=url,
                    key=key,
                    body=routed_body,
                    timeout=per_model_timeout,
                    provider=f"OpenRouter/{model}",
                    retry_without_response_format=retry_without_response_format,
                )
                # Validate candidate structure here so malformed/free-model output
                # can fall through to the next model in the same outer attempt.
                rows = ai_provider._parse_candidates(payload)
                if not rows:
                    raise ValueError("OpenRouter model returned zero candidate rows")
                payload = dict(payload)
                payload["model"] = str(payload.get("model") or model)
                logger.info(
                    "OpenRouter model success model=%s slot=%s/%s candidates=%s",
                    payload["model"], position, len(batch), len(rows),
                )
                return payload
            except Exception as exc:  # provider-specific errors are handled here
                last_exc = exc
                if not _model_error_is_fallbackable(exc):
                    raise
                diagnostic = str(exc).replace("\n", " ")[:260]
                logger.warning(
                    "OpenRouter model failed model=%s slot=%s/%s: %s; trying next model",
                    model, position, len(batch), diagnostic,
                )

        if last_exc is not None:
            raise last_exc
        raise RuntimeError("OpenRouter fallback batch exhausted without an exception")

    wrapped_request._openrouter_multi_model_fallback = True  # type: ignore[attr-defined]
    ai_provider._request = wrapped_request


def verify_openrouter_fallback_chain() -> None:
    if not getattr(ai_provider._request, "_openrouter_multi_model_fallback", False):
        raise RuntimeError("OpenRouter explicit fallback chain was not installed")
    models = configured_openrouter_models()
    if len(models) < 3:
        raise RuntimeError("OpenRouter fallback chain must contain at least three models")
