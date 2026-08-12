# v10 setup

## 1. Replace the repository

Push the contents of this archive over the current v9.1 repository. Keep the existing GitHub Secrets:

- `SQUARE_API`
- `MISTRAL_API`

`MISTRAL_API` and `SQUARE_API` are never exposed to the dashboard.

## 2. Publishing

Keep using the existing external cron that dispatches **Binance Square Bot**. The v9.1 Dual-Lane publication logic is unchanged. Before every bot run, v10 quietly refreshes public post statistics.

## 3. Enable the web dashboard once

In GitHub:

1. Open **Settings → Pages**.
2. Under **Build and deployment**, select **GitHub Actions** as the source.
3. Open **Actions → Square Analytics Dashboard**.
4. Click **Run workflow** once.
5. When the deployment completes, GitHub shows the Pages URL in the deployment job/environment.

After that the dashboard refreshes automatically every hour (`17 * * * *`). You can also run the workflow manually at any time.

## 4. Shadow mode

`LEARNING_ONLY=1` is intentionally enabled in both workflows. The bot collects and displays:

- real views, likes, comments, quotes, shares;
- 30m / 2h / 6h / 24h checkpoints for newly tracked posts;
- ticker affinity;
- hour affinity (UTC+3);
- TRADE vs EVENT performance;
- breakout counts and rates.

None of these values affects ranking yet. When enough clean data accumulates, `LEARNING_ONLY` can be disabled in a future adaptive release.
