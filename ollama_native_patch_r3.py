"""R3 native Ollama transport for the dedicated qwen3:4b desktop build."""
from __future__ import annotations

import requests

OLLAMA_CHAT_URL = "http://127.0.0.1:11434/api/chat"


def install_native_ollama_patch_r3() -> None:
    import local_ai_primary

    current = local_ai_primary._post_local
    if getattr(current, "_ollama_native_r3", False):
        return

    def post_local(body: dict, timeout: int) -> dict:
        # Dedicated R3 intentionally ignores stale LOCAL_AI_ENDPOINT values.
        # The user's qwen3:4b is served by local Ollama on its standard port.
        model = (
            local_ai_primary._api_model_name()
            or "qwen3:4b"
        )
        if model == "binance-square-local":
            model = "qwen3:4b"
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
            OLLAMA_CHAT_URL,
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

    post_local._ollama_native_r3 = True  # type: ignore[attr-defined]
    post_local._ollama_native_no_think = True  # type: ignore[attr-defined]
    post_local._previous_transport = current  # type: ignore[attr-defined]
    local_ai_primary._post_local = post_local
