"""Resilient AI author provider chain.

Primary: DeepSeek V4 Pro through OrcaRouter (OpenAI-compatible API).
Fallback: Mistral, but only after the primary provider is genuinely unavailable
or returns unusable API responses. OrcaRouter 429/5xx/transient failures get a
bounded retry/backoff sequence first; Retry-After is respected when present.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
import logging
import os
import random
import re
import time
from typing import Any, Dict, List, Optional

import requests

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ProviderResult:
    candidates: List[dict]
    provider: str
    model: str


def _orcarouter_key() -> str:
    return (os.getenv("ORCAROUTER_API_KEY") or os.getenv("ORCA_API_KEY") or "").strip()


def _mistral_key() -> str:
    return (os.getenv("MISTRAL_API") or os.getenv("MISTRAL_API_KEY") or "").strip()


def has_ai_provider() -> bool:
    return bool(_orcarouter_key() or _mistral_key())


def preferred_provider_name() -> str:
    if _orcarouter_key():
        return "deepseek_v4_pro"
    if _mistral_key():
        return "mistral"
    return "deterministic"


def _clean_json(text: str) -> str:
    value = re.sub(r"^```(?:json)?\s*", "", str(text or "").strip(), flags=re.IGNORECASE)
    value = re.sub(r"\s*```$", "", value.strip())
    start = value.find("{")
    end = value.rfind("}")
    return value[start:end + 1] if start >= 0 and end > start else value


def _message_text(payload: dict) -> str:
    content = payload["choices"][0]["message"]["content"]
    if isinstance(content, list):
        return "".join(
            str(item.get("text", "")) if isinstance(item, dict) else str(item)
            for item in content
        )
    return str(content or "")


def _parse_candidates(payload: dict) -> List[dict]:
    parsed = json.loads(_clean_json(_message_text(payload)))
    rows = parsed.get("candidates", []) if isinstance(parsed, dict) else []
    return [item for item in rows if isinstance(item, dict)]


def _safe_error_body(response: Optional[requests.Response]) -> str:
    if response is None:
        return ""
    try:
        text = str(response.text or "").strip().replace("\n", " ")
    except Exception:
        return ""
    # Do not risk echoing a token if an upstream error happens to reflect headers.
    text = re.sub(r"(?i)(bearer\s+)[A-Za-z0-9._~-]+", r"\1<redacted>", text)
    text = re.sub(r"(?i)(api[_-]?key[\"'=:\s]+)[A-Za-z0-9._~-]+", r"\1<redacted>", text)
    return text[:600]


def _request(
    *,
    url: str,
    key: str,
    body: dict,
    timeout: int,
    provider: str,
    retry_without_response_format: bool = False,
) -> dict:
    response = requests.post(
        url,
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        json=body,
        timeout=timeout,
    )
    if (
        retry_without_response_format
        and response.status_code == 400
        and "response_format" in body
    ):
        logger.info("%s rejected response_format; retrying with plain JSON prompt", provider)
        retry_body = dict(body)
        retry_body.pop("response_format", None)
        response = requests.post(
            url,
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            json=retry_body,
            timeout=timeout,
        )
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict) or not payload.get("choices"):
        raise ValueError(f"{provider} response has no choices")
    return payload


def _retry_delay(exc: Exception, attempt: int) -> tuple[bool, float, str]:
    """Return (retryable, delay_seconds, diagnostic)."""
    base = max(0.2, float(os.getenv("ORCAROUTER_RETRY_BASE_SECONDS", "2")))
    cap = max(base, float(os.getenv("ORCAROUTER_RETRY_CAP_SECONDS", "6")))
    max_retry_after = max(cap, float(os.getenv("ORCAROUTER_MAX_RETRY_AFTER", "8")))
    delay = min(cap, base * (2 ** max(0, attempt - 1))) + random.uniform(0.0, 0.45)
    diagnostic = str(exc)
    if isinstance(exc, requests.HTTPError):
        response = exc.response
        status = int(response.status_code) if response is not None else 0
        body = _safe_error_body(response)
        diagnostic = f"HTTP {status}" + (f" body={body}" if body else "")
        retryable = status in {408, 409, 425, 429, 500, 502, 503, 504}
        if retryable and response is not None:
            retry_after = response.headers.get("Retry-After")
            if retry_after:
                try:
                    delay = min(max_retry_after, max(0.2, float(retry_after)))
                except ValueError:
                    pass
        return retryable, delay, diagnostic
    if isinstance(exc, (requests.Timeout, requests.ConnectionError)):
        return True, delay, f"{type(exc).__name__}: {exc}"
    if isinstance(exc, (ValueError, KeyError, TypeError, json.JSONDecodeError)):
        # A gateway can occasionally return an empty/truncated body. One or more
        # bounded retries are safer than immediately burning the fallback model.
        return True, delay, f"{type(exc).__name__}: {exc}"
    return False, delay, diagnostic


def request_candidates(
    *,
    system_prompt: str,
    user_payload: Dict[str, Any],
    temperature: float,
    max_tokens: int,
    timeout: int,
    presence_penalty: Optional[float] = None,
    frequency_penalty: Optional[float] = None,
) -> ProviderResult:
    """Return AI candidates using DeepSeek primary and Mistral fallback.

    Mistral is contacted only after OrcaRouter is absent or all configured primary
    API attempts fail. Downstream copy validation still retries the same chosen
    provider rather than silently changing models for stylistic reasons.
    """
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False)},
    ]
    failures: List[str] = []

    orca_key = _orcarouter_key()
    if orca_key:
        base = os.getenv("ORCAROUTER_BASE_URL", "https://api.orcarouter.ai/v1").strip().rstrip("/")
        model = os.getenv("ORCAROUTER_MODEL", "deepseek/deepseek-v4-pro-free").strip()
        body = {
            "model": model,
            "messages": messages,
            "response_format": {"type": "json_object"},
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        attempts = max(1, min(6, int(os.getenv("ORCAROUTER_RETRIES", "2"))))
        last_exc: Optional[Exception] = None
        for attempt in range(1, attempts + 1):
            try:
                payload = _request(
                    url=f"{base}/chat/completions",
                    key=orca_key,
                    body=body,
                    timeout=timeout,
                    provider="OrcaRouter/DeepSeek",
                    retry_without_response_format=True,
                )
                candidates = _parse_candidates(payload)
                if not candidates:
                    raise ValueError("DeepSeek returned no candidate objects")
                for row in candidates:
                    row["_provider"] = "deepseek_v4_pro"
                    row["_model"] = model
                logger.info(
                    "AI author provider=deepseek_v4_pro model=%s candidates=%s attempt=%s/%s",
                    model, len(candidates), attempt, attempts,
                )
                return ProviderResult(candidates, "deepseek_v4_pro", model)
            except (requests.RequestException, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
                last_exc = exc
                retryable, delay, diagnostic = _retry_delay(exc, attempt)
                failures.append(f"deepseek:{diagnostic}")
                if retryable and attempt < attempts:
                    logger.warning(
                        "DeepSeek attempt %s/%s failed: %s; retrying in %.1fs",
                        attempt, attempts, diagnostic, delay,
                    )
                    time.sleep(delay)
                    continue
                logger.warning(
                    "DeepSeek primary unavailable/unusable after %s/%s attempt(s): %s; trying Mistral fallback",
                    attempt, attempts, diagnostic,
                )
                break
        if last_exc is not None:
            logger.debug("DeepSeek final exception type=%s", type(last_exc).__name__)

    mistral_key = _mistral_key()
    if mistral_key:
        model = os.getenv("MISTRAL_MODEL", "mistral-small-latest").strip()
        body = {
            "model": model,
            "messages": messages,
            "response_format": {"type": "json_object"},
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if presence_penalty is not None:
            body["presence_penalty"] = presence_penalty
        if frequency_penalty is not None:
            body["frequency_penalty"] = frequency_penalty
        try:
            payload = _request(
                url="https://api.mistral.ai/v1/chat/completions",
                key=mistral_key,
                body=body,
                timeout=timeout,
                provider="Mistral",
            )
            candidates = _parse_candidates(payload)
            if not candidates:
                raise ValueError("Mistral returned no candidate objects")
            for row in candidates:
                row["_provider"] = "mistral"
                row["_model"] = model
            logger.info("AI author provider=mistral fallback=true model=%s candidates=%s", model, len(candidates))
            return ProviderResult(candidates, "mistral", model)
        except (requests.RequestException, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
            failures.append(f"mistral:{type(exc).__name__}:{exc}")
            logger.warning("Mistral fallback unavailable/unusable: %s", exc)

    reason = " | ".join(failures[-8:]) if failures else "no AI provider key configured"
    raise RuntimeError(reason)
