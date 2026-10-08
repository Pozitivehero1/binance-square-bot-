"""No-network Gemini provider regression checks."""
from __future__ import annotations

import json
import os

import groq_primary as provider
import ai_provider


def main() -> None:
    old_key = os.environ.get("GEMINI_API_KEY")
    old_post = provider.requests.post
    old_budget = ai_provider._budget_timeout
    try:
        os.environ["GEMINI_API_KEY"] = "test-key-not-a-real-secret"
        requests_made = []

        class FakeResponse:
            status_code = 200
            def raise_for_status(self):
                pass
            def json(self):
                return {"choices": [{"message": {"content": json.dumps({
                    "candidates": [{"format_id": "event_pulse", "text": "$BTC — test body"}]
                })}}]}

        def fake_post(url, *, headers, json, timeout):
            requests_made.append((url, headers, json, timeout))
            return FakeResponse()

        provider.requests.post = fake_post
        ai_provider._budget_timeout = lambda n: n
        rows = provider._request_gemini_model(
            system_prompt="Return JSON", user_payload={"topic": "BTC"},
            temperature=0.4, max_tokens=800, timeout=12,
        )
        assert rows and rows[0]["_provider"] == "gemini"
        assert rows[0]["format_id"] == "event_pulse"
        assert requests_made[0][0].startswith("https://generativelanguage.googleapis.com/")
        assert requests_made[0][2]["model"] == "gemini-2.5-flash-lite"
        assert "response_format" in requests_made[0][2]
        print("gemini_provider_test: OK")
    finally:
        provider.requests.post = old_post
        ai_provider._budget_timeout = old_budget
        if old_key is None:
            os.environ.pop("GEMINI_API_KEY", None)
        else:
            os.environ["GEMINI_API_KEY"] = old_key


if __name__ == "__main__":
    main()
