# Binance Square Bot — v11 Outcome Adaptive Engine

Production-oriented bot for `PozitiveHero`: adaptive market selection, fact-locked AI copy, automatic public-performance learning, and now a **verified Trade Outcome Engine** that follows explicitly published targets after the original setup.

> No bot can guarantee views or a fixed W2E payout. v11 optimizes the measurable funnel and refuses to fabricate market facts, targets, profits, leverage or outcomes.

## v11: what is new

### 1. Trade Outcome Engine

When a published post contains a **real target price in the public text**, v11 stores that setup in:

```text
state/trade_journal.json
```

Every normal cron run checks the active journal before scanning for a new setup.

- closed Binance 1-minute candles are used for verification;
- LONG/SHORT direction, entry, stop and targets come from the original Python trade plan;
- only TP prices that were actually visible in the original post text or published plan image are eligible for a follow-up;
- `decision_now` plans become active immediately;
- breakout/retest plans must first trigger before any target can count;
- if target and stop touch inside the same 1-minute candle, ordering is ambiguous and the bot posts **nothing** automatically;
- at most one outcome post is published per cron run;
- a run that publishes an outcome does not also publish a fresh setup at the same timestamp.

Default follow-up policy is intentionally anti-spam: first meaningful partial result, then final target or stop. Intermediate TP2 updates are suppressed if TP1 already had a follow-up, reserving the second slot for the actual conclusion.

### 2. Avatar-backed result cards

The supplied PozitiveHero avatar is bundled as:

```text
assets/pozitivehero_avatar.png
```

Verified outcomes get a 1080×1350 card with the avatar as a dark background. The card shows:

- ticker and direction;
- `TP1/TP2/TP3 HIT` or `ALL TARGETS HIT`;
- R reached;
- percentage move from the published entry;
- entry / reached level / risk boundary;
- original setup reference and `@PozitiveHero`.

It deliberately **does not invent USDT profit or leverage**, because the bot does not know the real account position size. There is also no referral, donation or engagement CTA on the result card.

A sample is included at `docs/outcome_card_preview.png`.

### 3. DeepSeek retry before Mistral fallback

Primary author remains:

```env
ORCAROUTER_BASE_URL=https://api.orcarouter.ai/v1
ORCAROUTER_MODEL=deepseek/deepseek-v4-pro-free
```

v11 no longer abandons DeepSeek on the first transient `429`/`5xx`. It now:

1. retries DeepSeek up to 4 times;
2. respects `Retry-After` when OrcaRouter sends it;
3. uses bounded exponential backoff;
4. logs a sanitized OrcaRouter error body;
5. only then calls Mistral.

Mistral remains the outage fallback, not a parallel writer.

### 4. Adaptive ranking remains ON

The current live opportunity remains the main signal. Historical Square performance is only a bounded correction:

- ticker affinity;
- hour affinity (UTC+3);
- EVENT/TRADE lane affinity;
- breakout history;
- recency decay;
- exploration;
- saturation protection.

Outcome posts are tracked for their own views in the dashboard but are marked `learning_eligible=false`, so they **cannot distort** ticker/hour/lane priors used to choose fresh setups.

### 5. W2E proxy stays conservative

Without per-post W2E revenue API data, the bot does not pretend it can learn directly from USDC. It still scores observable proxies: liquidity, audience demand, freshness, actionability, valid public plan and entry quality.

### 6. Public trade-plan logs are clearer

R/R values in `PUBLIC PLAN` are logged to 3 decimals, avoiding confusing messages such as rounded `1.55 < 1.55` when the real value was slightly below the threshold.

## Outcome settings

```env
ENABLE_OUTCOME_ENGINE=1
OUTCOME_AVATAR_PATH=assets/pozitivehero_avatar.png
OUTCOME_AI=1
OUTCOME_POST_STOPS=1
OUTCOME_PENDING_ENTRY_HOURS=36
OUTCOME_MAX_AGE_HOURS=96
OUTCOME_MIN_FOLLOWUP_GAP_MIN=45
OUTCOME_MAX_FOLLOWUPS_PER_TRADE=2
OUTCOME_MAX_KLINE_PAGES=7
OUTCOME_BOOTSTRAP_HOURS=24
```

## AI provider settings

```env
ORCAROUTER_API_KEY=...
ORCAROUTER_BASE_URL=https://api.orcarouter.ai/v1
ORCAROUTER_MODEL=deepseek/deepseek-v4-pro-free
ORCAROUTER_RETRIES=4
ORCAROUTER_RETRY_BASE_SECONDS=3
ORCAROUTER_RETRY_CAP_SECONDS=15
ORCAROUTER_MAX_RETRY_AFTER=30

MISTRAL_API=...
MISTRAL_MODEL=mistral-small-latest
```

Required GitHub Secrets remain:

```text
SQUARE_API
ORCAROUTER_API_KEY
MISTRAL_API
```

No new secret is required for v11.

## Dashboard

The GitHub Pages dashboard still auto-refreshes **hourly at minute 17** and can also be run manually.

v11 adds a **Результаты** tab with:

- tracked/active/closed setups;
- TP1 / TP3 hit rates;
- stops;
- generated follow-ups;
- per-setup target status.

Public Square views for `OUTCOME` posts remain visible under Posts, while adaptive learning excludes them.

## Workflows

Publishing:

```text
.github/workflows/run.yml
```

Your external cron can keep triggering it roughly every 20 minutes. That is a scan/check cadence, not a forced publication cadence.

Automatic dashboard:

```text
.github/workflows/dashboard.yml
```

## Safety / anti-fabrication

The author and outcome modules reject or avoid:

- invented prices, TP/SL, reasons, whales/news/liquidations;
- invented USDT PnL or leverage;
- guaranteed profit language;
- donation/tip begging;
- like/comment/follow solicitation;
- target-result claims for levels that were never public;
- automatic claims when 1m candle ordering is ambiguous.

## Local validation

```bash
python -m pip install -r requirements.txt
python config_check.py
python run_tests.py
```

Long repetition stress suite:

```bash
RUN_STRESS_TESTS=1 python run_tests.py
```

## Important v11 files

- `outcome_engine.py` — 1m verification and follow-up orchestration;
- `trade_journal.py` — persistent public-setup journal;
- `outcome_writer.py` — fact-locked result post copy;
- `outcome_card.py` — avatar result-card renderer;
- `assets/pozitivehero_avatar.png` — supplied avatar;
- `ai_provider.py` — DeepSeek retries + Mistral fallback;
- `adaptive.py` — account-specific adaptive ranking;
- `performance_store.py` — Square reach history and learning exclusions;
- `dashboard_builder.py` — dashboard data including outcomes.

See `CHANGES_V11.md` and `V11_SETUP.md`.
