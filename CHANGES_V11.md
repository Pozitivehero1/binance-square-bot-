# v11 changes

- Added 24h one-time bootstrap for recent pre-v11 setups when memory + analytics prove the original post.
- Added persistent Trade Outcome Engine (`state/trade_journal.json`).
- Tracks only target prices explicitly present in the original published text.
- Verifies entry/TP/stop using closed Binance 1m candles.
- Conservative ambiguity guard: target + stop in same 1m candle => manual review, no automatic claim.
- Publishes at most one outcome per cron run; no fresh setup in the same run after an outcome post.
- Added avatar-backed 1080x1350 result cards using `assets/pozitivehero_avatar.png`.
- Cards report R and market move, never invented USDT PnL/leverage.
- Added fact-locked AI outcome writer with deterministic fallback.
- Added anti-spam partial/final follow-up policy and global outcome gap.
- Outcome posts are collected in Square analytics but excluded from adaptive market learning.
- Added dashboard `Результаты` tab.
- DeepSeek OrcaRouter now retries transient 429/5xx with Retry-After/backoff before Mistral fallback.
- PUBLIC PLAN R/R log precision increased to 3 decimals.
- Automatic dashboard schedule remains hourly at minute 17.

> Superseded by v11.1. The v11 historical bootstrap described above is disabled in v11.1 because it could associate an old same-ticker plan with a newer post. See `CHANGES_V11_1.md`.
