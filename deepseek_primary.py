"""One bounded DeepSeek proxy request before the existing author chain."""
from __future__ import annotations

import json
import logging
import os
import time
from email.utils import parsedate_to_datetime
from urllib.parse import urlsplit

import requests
import ai_provider

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


def _cooldown(response=None, *, seconds=60.0) -> None:
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


def request_candidates(*, system_prompt, user_payload, temperature, max_tokens, timeout,
                       presence_penalty=None, frequency_penalty=None):
    if time.monotonic() < _COOLDOWN_UNTIL:
        raise RuntimeError("DeepSeek cooldown active; use existing fallback chain")
    url = endpoint()
    model = os.getenv("DEEPSEEK_MODEL", "deepseek-chat").strip() or "deepseek-chat"
    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt.strip() +
             "\nВерни ровно один валидный JSON-объект с массивом candidates по запрошенной схеме. "
             "Без Markdown, рассуждений и новых фактов или чисел."},
            {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False)},
        ],
        "stream": False,
        "user": "binance-square-" + os.getenv("GITHUB_RUN_ID", "local"),
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
            headers={"Authorization": "Bearer " + os.getenv("DEEPSEEK_API_KEY", "").strip(),
                     "Content-Type": "application/json"},
            json=body, timeout=(min(5.0, budget), budget), allow_redirects=False,
        )
        if response.status_code != 200:
            _cooldown(response, seconds=600.0 if response.status_code in {401, 403, 429} else 60.0)
            raise RuntimeError(f"DeepSeek HTTP {response.status_code}; use existing fallback chain")
        rows = ai_provider._parse_candidates(response.json())
        if not rows or any(not isinstance(row.get("text"), str) or not row["text"].strip() for row in rows):
            raise ValueError("DeepSeek response has no usable candidate prose")
    except (requests.RequestException, ValueError, KeyError, TypeError):
        _cooldown()
        raise
    ai_provider._annotate(rows, "deepseek_local", model)
    logger.info("AI author provider=deepseek_local primary=true model=%s candidates=%s", model, len(rows))
    return ai_provider.ProviderResult(rows, "deepseek_local", model)
