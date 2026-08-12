# v10 — Shadow Learning + Web Dashboard

This release intentionally keeps the v9.1 Dual-Lane publishing decision logic unchanged.

## Added

- Public Binance Square statistics collector (`views`, `likes`, `comments`, `quotes`, `shares`).
- Persistent `state/performance_history.json` with post metadata and 30m/2h/6h/24h milestones.
- Automatic import of older public profile posts for immediate dashboard history.
- Shadow `ACCOUNT_TICKER_AFFINITY`, hour affinity, lane comparison, breakout rate, and confidence shrinkage.
- Static dark analytics dashboard under `dashboard/`.
- Hourly GitHub Pages deployment workflow: `.github/workflows/dashboard.yml`.
- Publication metadata is recorded immediately after a successful post.

## Important

`LEARNING_ONLY=1` is the default. Affinity is calculated and displayed but **does not change what the bot publishes yet**. This preserves the clean v9.1 experiment while real performance data accumulates.

## Dashboard deployment

After pushing the repository, enable **Settings → Pages → Source: GitHub Actions** once. Then run the `Square Analytics Dashboard` workflow manually. It also refreshes automatically every hour.
