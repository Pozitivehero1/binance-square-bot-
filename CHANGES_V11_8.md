# v11.8 — Distribution Recovery

## Why v11.7 was not enough

v11.7 concentrated more aggressively on historically strong tickers, hours and formats. Live results showed that this was not the main failure mode: the account can still receive a strong first test on individual posts, while many neighboring posts stall almost immediately after 30 minutes.

The live author chain also became unstable: the primary OrcaRouter/DeepSeek route repeatedly returned 503 capacity errors and Mistral sometimes returned 429. Under the previous policy that could fill the candidate pool with deterministic outage templates before the trailing 30-minute health metric had fallen far enough to block them.

## v11.8 changes

- Restores conservative pre-v11.7 adaptive bounds. The bot no longer over-weights historical ticker/hour affinity during the reach slump.
- Keeps the external cron cadence unchanged. A cron tick is a market check, not an obligation to publish.
- Blocks deterministic/outage-fallback copy whenever rolling reach is depressed or either live distribution stage is depressed.
- Adds a second distribution-health signal: median 2h/30m expansion versus the account's own recent historical baseline.
- The initial 30m test and the 30m→2h expansion are evaluated separately. The recent cohort is excluded from its own historical baseline.
- When either distribution stage is weak, only a genuinely strong live event with sufficient reach, selection, opportunity, demand and activity can consume another feed slot.
- When both stages are weak at once, the rescue gate becomes exceptional-only.
- Reduces repeated author retries during provider outages: one author attempt already routes primary → fallback. This avoids multiplying 503/429 traffic and then falling through to template copy.
- Outcome stop/partial posts remain disabled during the recovery release.

## What did not change

- External ~20 minute trigger cadence.
- Market scanner universe and trading mathematics.
- Entry / stop / TP calculations and public-plan integrity contract.
- Binance Square publisher and chart generation.

## Measurement

The release should be judged first by two cohort metrics rather than by raw 24-hour views alone:

1. median views at 30 minutes versus the account baseline;
2. median 2h/30m expansion versus the account baseline.

A recovery is only convincing when both stages improve. A single 100+ view post is not treated as proof that the feed has recovered.
