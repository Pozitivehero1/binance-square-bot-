# v11 setup

1. Replace repository files with the archive contents.
2. Keep existing GitHub Secrets:
   - `SQUARE_API`
   - `ORCAROUTER_API_KEY`
   - `MISTRAL_API`
3. Do not delete the GitHub Actions state cache; v11 keeps the existing `state/` directory and creates `state/trade_journal.json` automatically.
4. Keep the external workflow trigger cadence unchanged.
5. Dashboard auto-refresh remains enabled (`17 * * * *`).

The avatar is already included; no manual image setup is required.

First useful log markers:

```text
Outcome journal: tracking ACEUSDT LONG ... public targets=tp1,tp2,tp3
DeepSeek attempt 1/4 failed: HTTP 429 ... retrying in ...
AI author provider=deepseek_v4_pro ... attempt=2/4
OUTCOME PUBLISHED ACEUSDT kind=target_complete ...
```

If a published post contains a valid internal plan but no target price in the public text/media, the log intentionally says it is not tracked for outcome follow-ups.
