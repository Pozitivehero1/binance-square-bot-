"""Route the desktop local author through Ollama's native API.

This patch is intentionally small and is installed by the Qwen3 4B desktop
entrypoint before the production worker imports the writer stack.  Ollama's
native /api/chat endpoint exposes an explicit `think` switch, so the desktop
bot can guarantee that Qwen3 does not spend time producing reasoning tokens.
"""
from __future__ import annotations

import os
from urllib.parse import urlsplit

import requests


def _backend() -> str:
    return (
        os.getenv("LOCAL_AI_RUNTIME_BACKEND")
        or os.getenv("LOCAL_AI_BACKEND")
        or ""
    ).strip().lower()


def _native_ollama_url(endpoint: str) -> str:
    parsed = urlsplit(endpoint)
    if not parsed.scheme or not parsed.netloc:
        return "http://127.0.0.1:11434/api/chat"
    return f"{parsed.scheme}://{parsed.netloc}/api/chat"


def install_native_ollama_patch() -> None:
    import local_ai_primary

    current = local_ai_primary._post_local
    if getattr(current, "_ollama_native_no_think", False):
        return

    def post_local(body: dict, timeout: int) -> dict:
        if _backend() != "ollama":
            return current(body, timeout)

        endpoint = local_ai_primary._endpoint()
        model = local_ai_primary._api_model_name()
        max_tokens = max(32, int(body.get("max_tokens") or 1500))
        payload = {
            "model": model,
            "messages": list(body.get("messages") or []),
            "stream": False,
            "think": False,
            "format": "json",
            "keep_alive": "15m",
            "options": {
                "temperature": float(body.get("temperature") or 0.55),
                "top_p": float(body.get("top_p") or 0.8),
                "num_predict": max_tokens,
            },
        }
        response = requests.post(
            _native_ollama_url(endpoint),
            json=payload,
            timeout=local_ai_primary._request_timeout(timeout),
        )
        if not response.ok:
            raise RuntimeError(f"Ollama HTTP {response.status_code}: {response.text[:700]}")
        data = response.json()
        if not isinstance(data, dict):
            raise ValueError("Ollama returned a non-object response")
        message = data.get("message")
        if not isinstance(message, dict):
            raise ValueError("Ollama response has no message")
        content = str(message.get("content") or "").strip()
        if not content:
            raise ValueError("Ollama returned empty content")
        return {
            "model": str(data.get("model") or model),
            "choices": [{"message": {"role": "assistant", "content": content}}],
        }

    post_local._ollama_native_no_think = True  # type: ignore[attr-defined]
    local_ai_primary._post_local = post_local
