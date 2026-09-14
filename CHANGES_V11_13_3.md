# v11.13.3 — Mistral Free-Tier Request Budget

- Production verification showed that `mistral-large-2512` is listed on the limits page but still returns `403 tier_not_allowed` for this API key.
- The primary author now uses the exact free-tier model ID `mistral-small-2603`.
- Each request asks for three variants instead of six and caps output at 1,400 tokens, which is sufficient for three 220–430 character posts and fits the model's 20,000 TPM limit comfortably.
- A rate-limited request now waits for the minute window to reset instead of retrying after only 2–4 seconds.
- Author-level retries were reduced from three to two to avoid consuming the shared scan request budget with duplicate calls.
- Deterministic copy remains disabled whenever AI is configured.
