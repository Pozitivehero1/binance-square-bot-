"""Remember explicit account/model limits across cron runs; never store keys."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import json
import time
from urllib.parse import urlsplit

import requests

from runtime import atomic_write_json, resolve_state_file


class ProviderCooldown(requests.RequestException):
    def __init__(self, scope: str):
        self.scope = scope
        super().__init__(f"provider cooldown ({scope}); waiting for retry window")


def account_limit(response) -> bool:
    if response is None or response.status_code not in (402, 429):
        return False
    body = str(response.text or "").lower()
    return response.status_code == 402 or any(marker in body for marker in (
        "free-models-per-day", "openrouter_free_tier_daily", "daily limit",
        "daily quota", "insufficient credits",
    ))


def _read() -> dict:
    try:
        value = json.loads(resolve_state_file("PROVIDER_HEALTH_FILE", "provider_health.json").read_text())
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def _identity(url: str, key: str) -> str:
    # Key rotation immediately releases an old account cooldown.
    digest = hashlib.sha256(key.encode()).hexdigest()[:16]
    return f"{urlsplit(url).netloc}:{digest}"


def check_cooldown(url: str, key: str, model: str) -> None:
    data = _read()
    identity = _identity(url, key)
    for scope, name in (("account", identity), ("model", f"{identity}:{model}")):
        try:
            if float(data.get(name, 0)) > time.time():
                raise ProviderCooldown(scope)
        except (TypeError, ValueError):
            continue


def remember_failure(url: str, key: str, model: str, response) -> None:
    """Only hard account limits and unavailable models survive the process."""
    if response is None:
        return
    now = time.time()
    identity = _identity(url, key)
    if account_limit(response):
        reset = (datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
                 + timedelta(days=1)).timestamp()
        headers = dict(response.headers)
        try:
            headers.update(response.json().get("error", {}).get("metadata", {}).get("headers", {}))
        except (ValueError, AttributeError, TypeError):
            pass
        raw = next((v for k, v in headers.items() if k.lower() == "x-ratelimit-reset"), None)
        try:
            candidate = float(raw)
            if candidate > 10**11:
                candidate /= 1000
            if now < candidate <= now + 86400:
                reset = candidate
        except (TypeError, ValueError):
            pass
        name, until = identity, reset
    elif response.status_code in (404, 410):
        name, until = f"{identity}:{model}", now + 6 * 3600
    else:
        return
    data = _read()
    data = {k: v for k, v in data.items() if isinstance(v, (int, float)) and v > now}
    data[name] = until
    atomic_write_json(resolve_state_file("PROVIDER_HEALTH_FILE", "provider_health.json"), data)
