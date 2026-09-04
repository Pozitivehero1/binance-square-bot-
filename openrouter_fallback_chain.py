"""OpenRouter multi-model fallback routing for v11.8.

OpenRouter can fail over across providers for one model and across different
models through the `models` request field.  This module keeps ai_provider.py
backward compatible and upgrades only OpenRouter requests at runtime.
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


def install_openrouter_fallback_chain() -> None:
    """Patch ai_provider._request so OpenRouter uses model-level failover.

    Each OpenRouter call sends the full model list to OpenRouter. If a request
    has to be made again because parsing/validation failed, the starting model
    rotates so a model that returns a technically successful but unusable reply
    does not monopolize every retry.
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
        ordered = _rotated(models, call_index)
        call_index += 1

        routed_body = dict(body)
        routed_body.pop("model", None)
        routed_body["models"] = ordered

        logger.info(
            "OpenRouter fallback chain start=%s models=%s",
            ordered[0] if ordered else "none",
            " -> ".join(ordered),
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
