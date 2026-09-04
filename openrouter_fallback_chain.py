"""OpenRouter multi-model fallback routing for v11.8.

OpenRouter supports model failover through the `models` request field, but the
API accepts at most three model IDs in one request. This module keeps the full
configured pool and exposes it as rotating batches of up to three models.
"""
from __future__ import annotations

from functools import wraps
import logging
import os
from typing import List

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
    """Return a unique priority-ordered OpenRouter model chain.

    OPENROUTER_MODELS may override the defaults with a comma-separated list.
    OPENROUTER_MODEL remains the preferred first model for compatibility with
    the existing workflow configuration.
    """
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
    """Build one OpenRouter-safe batch while covering the whole pool over retries.

    With the default five-model pool the first two calls are:
      1) models 1,2,3
      2) models 4,5,1
    This respects OpenRouter's maximum of three models per request and gives all
    five configured models a chance across OPENROUTER_RETRIES=2.
    """
    if not models:
        return []
    offset = (call_index * OPENROUTER_MODELS_PER_REQUEST) % len(models)
    return _rotated(models, offset)[:OPENROUTER_MODELS_PER_REQUEST]


def install_openrouter_fallback_chain() -> None:
    """Patch ai_provider._request so OpenRouter uses bounded model-level failover.

    Each OpenRouter call sends at most three model IDs. If a request must be made
    again because the provider response is unavailable or unusable, the next
    three-model batch starts after the previous one, so a bad first model cannot
    monopolize every retry.
    """
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

        routed_body = dict(body)
        routed_body.pop("model", None)
        routed_body["models"] = batch

        logger.info(
            "OpenRouter fallback batch start=%s models=%s configured=%s",
            batch[0] if batch else "none",
            " -> ".join(batch),
            len(models),
        )
        return current(
            url=url,
            key=key,
            body=routed_body,
            timeout=timeout,
            provider=provider,
            retry_without_response_format=retry_without_response_format,
        )

    wrapped_request._openrouter_multi_model_fallback = True  # type: ignore[attr-defined]
    ai_provider._request = wrapped_request
