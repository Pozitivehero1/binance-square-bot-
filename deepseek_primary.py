"""One bounded DeepSeek proxy request before the existing author chain."""
from __future__ import annotations

import json
import logging
import os
import time
from uuid import uuid4
from email.utils import parsedate_to_datetime
from urllib.parse import urlsplit

import requests
import ai_provider
from provider_health import check_cooldown, remember_transient_failure

logger = logging.getLogger(__name__)
_COOLDOWN_UNTIL = 0.0


def configured() -> bool:
    return bool(os.getenv("DEEPSEEK_API_KEY", "").strip() and os.getenv("DEEPSEEK_BASE_URL", "").strip())


def endpoint() -> str:
    base = os.getenv("DEEPSEEK_BASE_URL", "").strip().rstrip("/")
    parsed = urlsplit(base)
    local_http = parsed.scheme == "http" and parsed.hostname in {"127.0.0.1", "localhost", "::1"}
    if (not parsed.hostname or (parsed.scheme != "https" and not local_http)
            or parsed.username or parsed.password or parsed.query or parsed.fragment
            or not parsed.path.rstrip("/").endswith("/v1")):
        raise ValueError("DEEPSEEK_BASE_URL must be HTTPS ending in /v1 (HTTP allowed only on loopback)")
    return base + "/chat/completions"


def _cooldown(response=None, *, seconds=60.0) -> float:
    global _COOLDOWN_UNTIL
    if response is not None:
        raw = response.headers.get("Retry-After", "")
        try:
            delay = float(raw)
        except (ValueError, TypeError):
            try:
                delay = parsedate_to_datetime(raw).timestamp() - time.time()
            except (ValueError, TypeError, OverflowError):
                delay = 0.0
        seconds = max(seconds, delay)
    _COOLDOWN_UNTIL = max(_COOLDOWN_UNTIL, time.monotonic() + seconds)
    return seconds


def _remember_outage(url: str, key: str, model: str, seconds: float) -> None:
    try:
        remember_transient_failure(url, key, model, seconds=seconds)
    except OSError:
        logger.warning("DeepSeek provider cooldown could not be persisted")


def request_candidates(*, system_prompt, user_payload, temperature, max_tokens, timeout,
                       presence_penalty=None, frequency_penalty=None):
    if time.monotonic() < _COOLDOWN_UNTIL:
        raise RuntimeError("DeepSeek cooldown active; use existing fallback chain")
    url = endpoint()
    model = os.getenv("DEEPSEEK_MODEL", "deepseek-chat").strip() or "deepseek-chat"
    key = os.getenv("DEEPSEEK_API_KEY", "").strip()
    check_cooldown(url, key, model)
    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt.strip() +
             "\nВерни ровно один валидный JSON-объект с массивом candidates по запрошенной схеме. "
             "Без Markdown, рассуждений и новых фактов или чисел."},
            {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False)},
        ],
        "stream": False,
        # The web proxy remembers previous turns by user id. Every author call
        # is a complete independent fact package, not a conversational follow-up.
        "user": "binance-square-" + os.getenv("GITHUB_RUN_ID", "local") + "-" + uuid4().hex,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "response_format": {"type": "json_object"},
    }
    for name, value in (("presence_penalty", presence_penalty), ("frequency_penalty", frequency_penalty)):
        if value is not None:
            body[name] = value
    budget = ai_provider._budget_timeout(max(1, min(int(timeout), int(os.getenv("DEEPSEEK_MODEL_TIMEOUT", "25")))))
    try:
        response = requests.post(
            url,
            headers={"Authorization": "Bearer " + key,
                     "Content-Type": "application/json"},
            json=body, timeout=(min(5.0, budget), budget), allow_redirects=False,
        )
        if response.status_code != 200:
            status = response.status_code
            base_delay = (3600.0 if status in {401, 403} else 900.0 if status == 429
                          else 600.0 if status >= 500 else 60.0)
            delay = _cooldown(response, seconds=base_delay)
            if status in {401, 403, 429} or status >= 500:
                _remember_outage(url, key, model, delay)
            raise RuntimeError(f"DeepSeek HTTP {status}; use existing fallback chain")
        rows = ai_provider._parse_candidates(response.json())
        if not rows or any(not isinstance(row.get("text"), str) or not row["text"].strip() for row in rows):
            raise ValueError("DeepSeek response has no usable candidate prose")
    except (requests.RequestException, ValueError, KeyError, TypeError) as exc:
        _cooldown()
        if isinstance(exc, (requests.ConnectionError, requests.Timeout)):
            _remember_outage(url, key, model, 3600.0 if isinstance(exc, requests.ConnectionError) else 1200.0)
        raise
    ai_provider._annotate(rows, "deepseek_local", model)
    logger.info("AI author provider=deepseek_local primary=true model=%s candidates=%s", model, len(rows))
    return ai_provider.ProviderResult(rows, "deepseek_local", model)
