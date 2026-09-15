"""Local Qwen author provider for the desktop build.

Installed after the existing remote-provider policy so the local OpenAI-compatible
server is authoritative while all existing fact/number/quality gates stay unchanged.
"""
from __future__ import annotations

from dataclasses import replace
from functools import wraps
import json
import logging
import os
from typing import Any, Dict, List, Optional

import requests

import ai_provider

logger = logging.getLogger(__name__)

_ORIGINAL_REQUEST_CANDIDATES = None
_ORIGINAL_HAS_AI_PROVIDER = None
_ORIGINAL_PREFERRED_PROVIDER = None


def local_ai_enabled() -> bool:
    return os.getenv("LOCAL_AI_ENABLED", "1").strip().lower() in {"1", "true", "yes", "on"}


def _remote_fallback_enabled() -> bool:
    return os.getenv("LOCAL_AI_REMOTE_FALLBACK", "0").strip().lower() in {"1", "true", "yes", "on"}


def _endpoint() -> str:
    return (
        os.getenv("LOCAL_AI_RUNTIME_ENDPOINT")
        or os.getenv("LOCAL_AI_ENDPOINT")
        or "http://127.0.0.1:8089/v1/chat/completions"
    ).strip()


def _model_name() -> str:
    return (
        os.getenv("LOCAL_AI_RUNTIME_MODEL_NAME")
        or os.getenv("LOCAL_AI_MODEL_NAME")
        or "Qwen local"
    ).strip() or "Qwen local"


def _api_model_name() -> str:
    return (
        os.getenv("LOCAL_AI_RUNTIME_API_MODEL")
        or os.getenv("LOCAL_AI_API_MODEL")
        or "binance-square-local"
    ).strip() or "binance-square-local"


def _batch_count() -> int:
    return max(1, min(int(os.getenv("LOCAL_AI_BATCHES", "2")), 3))


def _request_timeout(timeout: int) -> float:
    configured = max(20, min(int(os.getenv("LOCAL_AI_TIMEOUT", "110")), 300))
    return ai_provider._budget_timeout(min(configured, max(20, int(timeout))))


def _body(
    *,
    system_prompt: str,
    user_payload: Dict[str, Any],
    temperature: float,
    max_tokens: int,
    batch_index: int,
) -> dict:
    system = (
        system_prompt.strip()
        + "\n\n/no_think\n"
        + "LOCAL QUALITY CONTRACT: return exactly one valid JSON object with a top-level "
        + "candidates array. Keep every market fact and number immutable. Never add facts. "
        + "Write natural Russian, not indicator-dump prose. Do not expose reasoning."
    )
    if batch_index > 0:
        system += (
            "\nThis is an independent second editorial pass. Use noticeably different wording "
            "and openings from the obvious first solution while preserving the same facts."
        )
    return {
        "model": _api_model_name(),
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False, separators=(",", ":"))},
        ],
        "response_format": {"type": "json_object"},
        "temperature": max(0.35, min(float(temperature), 0.78)),
        "top_p": 0.8,
        "max_tokens": max(500, min(int(max_tokens), int(os.getenv("LOCAL_AI_MAX_TOKENS", "1500")))),
        "stream": False,
    }


def _post_local(body: dict, timeout: int) -> dict:
    endpoint = _endpoint()
    response = requests.post(endpoint, json=body, timeout=_request_timeout(timeout))
    if response.status_code == 400 and "response_format" in body:
        retry = dict(body)
        retry.pop("response_format", None)
        response = requests.post(endpoint, json=retry, timeout=_request_timeout(timeout))
    if not response.ok:
        raise RuntimeError(f"local AI HTTP {response.status_code}: {response.text[:700]}")
    payload = response.json()
    if not isinstance(payload, dict) or not payload.get("choices"):
        raise ValueError("local AI response has no choices")
    return payload


def _request_local_candidates(
    *,
    system_prompt: str,
    user_payload: Dict[str, Any],
    temperature: float,
    max_tokens: int,
    timeout: int,
) -> ai_provider.ProviderResult:
    rows: List[dict] = []
    seen: set[str] = set()
    failures: List[str] = []

    for batch_index in range(_batch_count()):
        try:
            payload = _post_local(
                _body(
                    system_prompt=system_prompt,
                    user_payload=user_payload,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    batch_index=batch_index,
                ),
                timeout,
            )
            candidates = ai_provider._parse_candidates(payload)
            actual_model = _model_name()
            ai_provider._annotate(candidates, "local_qwen", actual_model)
            for row in candidates:
                text = str(row.get("text") or "").strip()
                fmt = str(row.get("format_id") or "").strip()
                key = f"{fmt}\0{text}"
                if text and key not in seen:
                    seen.add(key)
                    rows.append(row)
            logger.info(
                "Local AI batch=%s/%s model=%s candidates=%s unique_total=%s",
                batch_index + 1,
                _batch_count(),
                actual_model,
                len(candidates),
                len(rows),
            )
        except Exception as exc:
            failures.append(f"batch{batch_index + 1}:{type(exc).__name__}:{str(exc)[:240]}")
            logger.warning("Local AI batch %s failed: %s", batch_index + 1, str(exc)[:500])
            if rows:
                break

    if not rows:
        raise RuntimeError("local AI produced no usable candidates: " + " | ".join(failures[-3:]))
    return ai_provider.ProviderResult(rows, "local_qwen", _model_name())


def _request_candidates_local_first(
    *,
    system_prompt: str,
    user_payload: Dict[str, Any],
    temperature: float,
    max_tokens: int,
    timeout: int,
    presence_penalty: Optional[float] = None,
    frequency_penalty: Optional[float] = None,
):
    if local_ai_enabled():
        try:
            return _request_local_candidates(
                system_prompt=system_prompt,
                user_payload=user_payload,
                temperature=temperature,
                max_tokens=max_tokens,
                timeout=timeout,
            )
        except Exception as exc:
            logger.error("Local AI unavailable/unusable: %s", exc)
            if not _remote_fallback_enabled():
                raise
            logger.warning("LOCAL_AI_REMOTE_FALLBACK=1; using the existing remote AI chain")

    return _ORIGINAL_REQUEST_CANDIDATES(
        system_prompt=system_prompt,
        user_payload=user_payload,
        temperature=temperature,
        max_tokens=max_tokens,
        timeout=timeout,
        presence_penalty=presence_penalty,
        frequency_penalty=frequency_penalty,
    )


def _has_ai_provider_local_first() -> bool:
    return bool(local_ai_enabled()) or bool(_ORIGINAL_HAS_AI_PROVIDER())


def _preferred_provider_local_first() -> str:
    if local_ai_enabled():
        return "local_qwen"
    return str(_ORIGINAL_PREFERRED_PROVIDER())


def install_local_ai_primary() -> None:
    global _ORIGINAL_REQUEST_CANDIDATES, _ORIGINAL_HAS_AI_PROVIDER, _ORIGINAL_PREFERRED_PROVIDER
    current = ai_provider.request_candidates
    if getattr(current, "_local_ai_primary", False):
        return

    _ORIGINAL_REQUEST_CANDIDATES = current
    _ORIGINAL_HAS_AI_PROVIDER = ai_provider.has_ai_provider
    _ORIGINAL_PREFERRED_PROVIDER = ai_provider.preferred_provider_name

    wrapped = wraps(current)(_request_candidates_local_first)
    wrapped._local_ai_primary = True  # type: ignore[attr-defined]
    ai_provider.request_candidates = wrapped
    ai_provider.has_ai_provider = _has_ai_provider_local_first
    ai_provider.preferred_provider_name = _preferred_provider_local_first
    os.environ["BOT_VERSION"] = os.getenv("BOT_VERSION", "v11.14.1") + "+desktop-local"
    logger.info(
        "Local AI primary installed endpoint=%s api_model=%s display_model=%s batches=%s remote_fallback=%s",
        _endpoint(), _api_model_name(), _model_name(), _batch_count(), _remote_fallback_enabled(),
    )


def install_local_source_tracking() -> None:
    try:
        import reach_recovery_v11_8
        current_source = reach_recovery_v11_8._source_name_v118
        if not getattr(current_source, "_local_source_tracking", False):
            @wraps(current_source)
            def source_name(source: str) -> str:
                raw = str(source or "").strip().lower()
                if reach_recovery_v11_8._LAST_AI_PROVIDER == "local_qwen" and raw == "mistral":
                    return "local_qwen"
                return current_source(source)
            source_name._local_source_tracking = True  # type: ignore[attr-defined]
            reach_recovery_v11_8._source_name_v118 = source_name
    except Exception:
        logger.exception("Could not install TRADE local source tracking")

    try:
        import author_pool_policy
        current_event_source = author_pool_policy._truthful_event_source
        if not getattr(current_event_source, "_local_source_tracking", False):
            @wraps(current_event_source)
            def event_source(draft):
                style_id = str(getattr(draft, "style_id", "") or "").lower()
                desired = ""
                if style_id.startswith("local_qwen_repaired_event_"):
                    desired = "local_qwen_event_repaired"
                elif style_id.startswith("local_qwen_event_"):
                    desired = "local_qwen_event"
                if desired:
                    try:
                        return replace(draft, source=desired)
                    except TypeError:
                        try:
                            draft.source = desired
                        except Exception:
                            pass
                        return draft
                return current_event_source(draft)
            event_source._local_source_tracking = True  # type: ignore[attr-defined]
            author_pool_policy._truthful_event_source = event_source
    except Exception:
        logger.exception("Could not install EVENT local source tracking")


def verify_local_ai_primary() -> None:
    if local_ai_enabled() and not getattr(ai_provider.request_candidates, "_local_ai_primary", False):
        raise RuntimeError("local AI primary provider was not installed")
    logger.info("Local AI provider verified: %s", _model_name())
