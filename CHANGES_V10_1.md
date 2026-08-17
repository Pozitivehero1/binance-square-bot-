# v10.1 — Adaptive W2E Proxy

## Ranking

- Enabled bounded `ACCOUNT_TICKER_AFFINITY` from real 24h Square performance.
- Added `HOUR_AFFINITY` (UTC+3), lane affinity and relative breakout adjustment.
- Added 14-day lookback with 7-day half-life so old results decay.
- Added exploration bonus for strong low-sample/new tickers.
- Added 48h symbol saturation penalty so past winners cannot monopolize the feed.
- Hard cap: adaptive history cannot override live market/risk/quality gates.
- Added small W2E-proxy nudge using liquidity, activity, freshness and actionability.

## Author

- Added OrcaRouter/OpenAI-compatible provider layer.
- Primary model: `deepseek/deepseek-v4-pro-free`.
- Mistral is contacted only when the primary API is unavailable/unusable.
- Python fact lock remains authoritative for all market/trade numbers.
- Direct requests for likes/comments/follows/donations/tips are rejected.

## Analytics / dashboard

- Dashboard now reports `Adaptive ON`.
- Split relative breakout and absolute `300+` rate.
- Added author-provider performance summary.
- Publication records include adaptive components and W2E-proxy metadata.
- Automatic GitHub Pages dashboard refresh restored: once per hour at minute 17 UTC; manual `workflow_dispatch` remains available.

## Compatibility

- Same state/cache paths as v10, so existing `performance_history.json` can continue to be used.
- Same external-cron workflow entrypoint (`workflow_dispatch`).
- New required secret for the preferred author: `ORCAROUTER_API_KEY`.
