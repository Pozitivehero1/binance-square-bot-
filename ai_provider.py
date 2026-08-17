"""Resilient AI author provider chain.

Primary: DeepSeek V4 Pro through OrcaRouter (OpenAI-compatible API).
Fallback: Mistral, but only when the primary provider is unavailable or returns
an unusable API response. Content/fact validation remains in writer modules.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
import logging
import os
import re
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

    Mistral is contacted only if OrcaRouter is absent/unavailable/unparseable.
    If DeepSeek responds successfully but downstream content validation rejects
    its prose, writer.py retries DeepSeek rather than silently switching models.
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
            logger.info("AI author provider=deepseek_v4_pro model=%s candidates=%s", model, len(candidates))
            return ProviderResult(candidates, "deepseek_v4_pro", model)
        except (requests.RequestException, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
            failures.append(f"deepseek:{type(exc).__name__}:{exc}")
            logger.warning("DeepSeek primary unavailable/unusable: %s; trying Mistral fallback", exc)

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

    reason = " | ".join(failures) if failures else "no AI provider key configured"
    raise RuntimeError(reason)
