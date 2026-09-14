"""Groq-first production author policy for Binance Square bot.

Groq is the primary author because its free-tier limits are predictable enough
for the bot's 20-minute cadence. The existing ai_provider chain remains intact
as fallback: Mistral -> OrcaRouter/DeepSeek -> OpenRouter.

The module is installed before writer/event_writer import their provider
functions, so no trading/fact-lock logic is replaced. Python still owns all
market numbers and public Entry/SL/TP levels; Groq only writes prose.
"""
from __future__ import annotations

from dataclasses import replace
from functools import wraps
import json
import logging
import os
import random
import time
from typing import Any, Dict, List, Optional

import requests

import ai_provider

logger = logging.getLogger(__name__)

DEFAULT_GROQ_MODELS = (
    "qwen/qwen3.8-27b",
    "openai/gpt-oss-120b",
)

_ORIGINAL_REQUEST_CANDIDATES = None
_ORIGINAL_HAS_AI_PROVIDER = None
_ORIGINAL_PREFERRED_PROVIDER = None
_LAST_PROVIDER = ""


def _groq_key() -> str:
    return (os.getenv("GROQ_API_KEY") or "").strip()


def configured_groq_models() -> List[str]:
    """Return a unique priority-ordered Groq model chain."""
    explicit = [item.strip() for item in os.getenv("GROQ_MODELS", "").split(",") if item.strip()]
    primary = os.getenv("GROQ_MODEL", "").strip()
    backup = os.getenv("GROQ_BACKUP_MODEL", "").strip()

    rows: List[str] = []
    if explicit:
        rows.extend(explicit)
    else:
        if primary:
            rows.append(primary)
        if backup:
            rows.append(backup)
        rows.extend(DEFAULT_GROQ_MODELS)

    unique: List[str] = []
    seen = set()
    for model in rows:
        if model and model not in seen:
            seen.add(model)
            unique.append(model)
    return unique or list(DEFAULT_GROQ_MODELS)


def _retry_delay(response: Optional[requests.Response], attempt: int) -> float:
    base = max(0.2, float(os.getenv("GROQ_RETRY_BASE_SECONDS", "1")))
    cap = max(base, float(os.getenv("GROQ_RETRY_CAP_SECONDS", "4")))
    max_retry_after = max(cap, float(os.getenv("GROQ_MAX_RETRY_AFTER", "8")))
    delay = min(cap, base * (2 ** max(0, attempt - 1))) + random.uniform(0.0, 0.25)
    if response is not None:
        raw = response.headers.get("Retry-After")
        if raw:
            try:
                retry_after = float(raw)
                if retry_after <= max_retry_after:
                    delay = max(0.2, retry_after)
                else:
                    return -1.0
            except ValueError:
                pass
    return delay


def _groq_body(
    *,
    model: str,
    system_prompt: str,
    user_payload: Dict[str, Any],
    temperature: float,
    max_tokens: int,
) -> dict:
    # A single user message is deliberate: Groq's reasoning guidance recommends
    # keeping instructions together for reasoning-capable Qwen/GPT-OSS models.
    prompt = (
        system_prompt.strip()
        + "\n\nКРИТИЧЕСКИЙ КОНТРАКТ ОТВЕТА: верни ровно один валидный JSON-объект "
        + "с массивом candidates. Никакого Markdown, текста до/после JSON и никаких "
        + "новых фактов или чисел. Не показывай рассуждения.\n\nINPUT_JSON:\n"
        + json.dumps(user_payload, ensure_ascii=False, separators=(",", ":"))
    )
    requested_max = max(300, int(max_tokens))
    groq_max = max(300, min(int(os.getenv("GROQ_MAX_TOKENS", "1100")), 1600))
    body = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "response_format": {"type": "json_object"},
        "temperature": max(0.15, min(float(temperature), 0.8)),
        "max_completion_tokens": min(requested_max, groq_max),
        "top_p": 0.9,
    }
    lowered = model.lower()
    if lowered.startswith("qwen/"):
        body["reasoning_effort"] = "none"
        body["reasoning_format"] = "hidden"
    elif lowered.startswith("openai/gpt-oss"):
        body["reasoning_effort"] = "low"
        body["reasoning_format"] = "hidden"
    return body


def _request_groq_model(
    *,
    key: str,
    model: str,
    system_prompt: str,
    user_payload: Dict[str, Any],
    temperature: float,
    max_tokens: int,
    timeout: int,
) -> List[dict]:
    base = os.getenv("GROQ_BASE_URL", "https://api.groq.com/openai/v1").strip().rstrip("/")
    url = f"{base}/chat/completions"
    attempts = max(1, min(3, int(os.getenv("GROQ_RETRIES", "2"))))
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    body = _groq_body(
        model=model,
        system_prompt=system_prompt,
        user_payload=user_payload,
        temperature=temperature,
        max_tokens=max_tokens,
    )

    last_exc: Optional[Exception] = None
    for attempt in range(1, attempts + 1):
        response: Optional[requests.Response] = None
        try:
            per_request_timeout = max(8, min(int(os.getenv("GROQ_MODEL_TIMEOUT", "25")), int(timeout)))
            response = requests.post(
                url,
                headers=headers,
                json=body,
                timeout=ai_provider._budget_timeout(per_request_timeout),
            )
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, dict) or not payload.get("choices"):
                raise ValueError("Groq response has no choices")
            candidates = ai_provider._parse_candidates(payload)
            if not candidates:
                raise ValueError("Groq response contained zero candidate rows")
            ai_provider._annotate(candidates, "groq", str(payload.get("model") or model))
            logger.info(
                "AI author provider=groq model=%s candidates=%s attempt=%s/%s",
                str(payload.get("model") or model),
                len(candidates),
                attempt,
                attempts,
            )
            return candidates
        except (requests.RequestException, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
            last_exc = exc
            status = 0
            if isinstance(exc, requests.HTTPError) and exc.response is not None:
                response = exc.response
                status = int(response.status_code)
            diagnostic = ai_provider._safe_error_body(response) if response is not None else str(exc)
            diagnostic = (diagnostic or str(exc)).replace("\n", " ")[:500]

            # 401/403 are key/account problems; another Groq model cannot fix them.
            if status in {401, 403}:
                raise RuntimeError(f"Groq authorization failed HTTP {status}: {diagnostic}") from exc

            retryable = status in {408, 409, 425, 429, 500, 502, 503, 504} or isinstance(
                exc, (requests.Timeout, requests.ConnectionError, ValueError, KeyError, TypeError, json.JSONDecodeError)
            )
            delay = _retry_delay(response, attempt)
            if retryable and attempt < attempts and delay >= 0:
                logger.warning(
                    "Groq model=%s attempt=%s/%s failed: %s; retrying in %.1fs",
                    model,
                    attempt,
                    attempts,
                    diagnostic,
                    delay,
                )
                time.sleep(delay)
                continue
            logger.warning(
                "Groq model=%s unavailable/unusable after %s/%s attempt(s): %s",
                model,
                attempt,
                attempts,
                diagnostic,
            )
            break

    if last_exc is not None:
        raise last_exc
    raise RuntimeError(f"Groq model {model} failed without a diagnostic")


def _request_candidates_groq_first(
    *,
    system_prompt: str,
    user_payload: Dict[str, Any],
    temperature: float,
    max_tokens: int,
    timeout: int,
    presence_penalty: Optional[float] = None,
    frequency_penalty: Optional[float] = None,
):
    """Try Groq models first, then preserve the entire existing AI chain."""
    del presence_penalty, frequency_penalty  # Groq models do not support these reliably.
    global _LAST_PROVIDER
    _LAST_PROVIDER = ""
    failures: List[str] = []
    key = _groq_key()

    if key:
        for model in configured_groq_models():
            try:
                rows = _request_groq_model(
                    key=key,
                    model=model,
                    system_prompt=system_prompt,
                    user_payload=user_payload,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    timeout=timeout,
                )
                _LAST_PROVIDER = "groq"
                actual_model = str(rows[0].get("_model") or model) if rows else model
                return ai_provider.ProviderResult(rows, "groq", actual_model)
            except Exception as exc:
                failures.append(f"groq/{model}:{type(exc).__name__}:{str(exc)[:220]}")
                logger.warning("Groq fallback to next model after %s: %s", model, str(exc)[:260])

    # Keep Mistral/Orca/OpenRouter as emergency AI fallbacks. Never replace them
    # with deterministic copy here; writer policy decides whether to skip.
    try:
        result = _ORIGINAL_REQUEST_CANDIDATES(
            system_prompt=system_prompt,
            user_payload=user_payload,
            temperature=temperature,
            max_tokens=max_tokens,
            timeout=timeout,
        )
        _LAST_PROVIDER = str(result.provider or "").strip().lower()
        return result
    except Exception as exc:
        fallback_error = f"fallback:{type(exc).__name__}:{str(exc)[:500]}"
        reason = " | ".join([*failures[-6:], fallback_error])
        raise RuntimeError(reason) from exc


def _has_ai_provider_groq_first() -> bool:
    return bool(_groq_key()) or bool(_ORIGINAL_HAS_AI_PROVIDER())


def _preferred_provider_groq_first() -> str:
    if _groq_key():
        return "groq"
    return str(_ORIGINAL_PREFERRED_PROVIDER())


def install_groq_primary() -> None:
    """Install Groq before writer/event_writer import provider functions by name."""
    global _ORIGINAL_REQUEST_CANDIDATES, _ORIGINAL_HAS_AI_PROVIDER, _ORIGINAL_PREFERRED_PROVIDER
    current = ai_provider.request_candidates
    if getattr(current, "_groq_primary", False):
        return

    _ORIGINAL_REQUEST_CANDIDATES = current
    _ORIGINAL_HAS_AI_PROVIDER = ai_provider.has_ai_provider
    _ORIGINAL_PREFERRED_PROVIDER = ai_provider.preferred_provider_name

    wrapped = wraps(current)(_request_candidates_groq_first)
    wrapped._groq_primary = True  # type: ignore[attr-defined]
    ai_provider.request_candidates = wrapped
    ai_provider.has_ai_provider = _has_ai_provider_groq_first
    ai_provider.preferred_provider_name = _preferred_provider_groq_first

    # Once Groq is primary, a known-broken free Mistral quota must not stall a
    # publishing slot for two 60-second retries. It remains one-shot fallback.
    os.environ["MISTRAL_RETRIES"] = os.getenv("GROQ_MISTRAL_FALLBACK_RETRIES", "1")
    os.environ["BOT_VERSION"] = "v11.14"
    logger.info("Groq primary installed models=%s", " -> ".join(configured_groq_models()))


def install_provider_source_tracking() -> None:
    """Make TRADE/EVENT analytics report the provider that actually wrote prose."""
    import reach_recovery_v11_8

    current_source = reach_recovery_v11_8._source_name_v118
    if not getattr(current_source, "_groq_source_tracking", False):
        @wraps(current_source)
        def source_name(source: str) -> str:
            raw = str(source or "").strip().lower()
            if reach_recovery_v11_8._LAST_AI_PROVIDER == "groq" and raw == "mistral":
                return "groq"
            return current_source(source)

        source_name._groq_source_tracking = True  # type: ignore[attr-defined]
        reach_recovery_v11_8._source_name_v118 = source_name

    # EVENT style_id already carries raw['_provider']; extend the existing
    # truthful-source normalizer so Groq is not mislabeled as Mistral.
    import author_pool_policy

    current_event_source = author_pool_policy._truthful_event_source
    if not getattr(current_event_source, "_groq_source_tracking", False):
        @wraps(current_event_source)
        def event_source(draft):
            style_id = str(getattr(draft, "style_id", "") or "").lower()
            desired = ""
            if style_id.startswith("groq_repaired_event_"):
                desired = "groq_event_repaired"
            elif style_id.startswith("groq_event_"):
                desired = "groq_event"
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

        event_source._groq_source_tracking = True  # type: ignore[attr-defined]
        author_pool_policy._truthful_event_source = event_source


def verify_groq_primary(*, require_key: Optional[bool] = None) -> None:
    """Fail fast in production if startup ordering or the Groq secret is wrong."""
    if not getattr(ai_provider.request_candidates, "_groq_primary", False):
        raise RuntimeError("Groq primary provider was not installed")
    models = configured_groq_models()
    if not models:
        raise RuntimeError("Groq model chain is empty")
    if models[0] != "qwen/qwen3.8-27b":
        logger.warning("Groq primary model overridden: %s", models[0])

    if require_key is None:
        dry_run = os.getenv("DRY_RUN", "1").strip().lower() in {"1", "true", "yes", "on"}
        require_key = not dry_run and os.getenv("AI_AUTHOR_REQUIRED", "1").strip().lower() in {"1", "true", "yes", "on"}
    if require_key and not _groq_key():
        raise RuntimeError("GROQ_API_KEY is missing in production; add GitHub Secret GROQ_API_KEY")

    print(
        "[v11.14] Groq primary verified: "
        + " -> ".join(models)
        + " -> Mistral -> OrcaRouter -> OpenRouter; deterministic author disabled"
    )


if __name__ == "__main__":
    install_groq_primary()
    verify_groq_primary(require_key=False)
