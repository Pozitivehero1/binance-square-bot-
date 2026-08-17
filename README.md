# Binance Square Bot — v11.1 Outcome Integrity + Full Plan

Production-oriented bot for `PozitiveHero`: adaptive market selection, fact-locked AI copy, automatic public-performance learning, a **hard full-plan publication contract**, and an exact post-bound Trade Outcome Engine.

> No bot can guarantee views or a fixed W2E payout. v11.1 optimizes the measurable funnel and refuses to fabricate market facts, targets, profits, leverage or outcomes.

## v11.1: what is new

### 1. Full public plan is mandatory

Every `plan_valid=true` TRADE or EVENT post must expose **LONG/SHORT + entry/entry zone + stop + TP1 + TP2 + TP3 in the text itself**. AI cannot silently drop TP2/TP3. Python appends a compact exact plan block if needed, validates it again, and the orchestrator performs a final independent hard check before publication.

Observation-only EVENT posts remain valid but cannot invent a trade.

### 2. Outcome Engine is bound to the exact source post

New setups are stored in `state/trade_journal.json` only after the full public text contract passes and Binance returns the source post ID. Each setup stores `source_post_id`, a deterministic `setup_id` fingerprint, and a hash of the exact published text.

**Historical/backfilled v11 setups are not trusted anymore.** On first v11.1 load, old journal rows are automatically quarantined as `legacy_disabled`; they cannot generate follow-ups.

Every normal cron run checks only v11.1-tracked setups before scanning for a new post. Closed Binance 1-minute candles are used for verification. Breakout/retest entries must trigger first. If target and stop touch in the same 1m candle, ordering is ambiguous and the bot publishes nothing automatically.

Default follow-up policy remains anti-spam: first meaningful partial result, then final target or stop.

### 3. Outcome text/card consistency

Outcome copy and image are generated from one fact object. A partial TP1 result cannot produce an `ALL TARGETS HIT` card. `target_complete` is valid only after TP1+TP2+TP3 are all hit and the final card shows `TP3 · ALL TARGETS HIT`.

The bundled avatar remains `assets/pozitivehero_avatar.png`; cards show exact market-plan facts but never invent position size, leverage or USDT PnL.

### 4. DeepSeek retry before Mistral fallback

Primary author remains `deepseek/deepseek-v4-pro-free` through `https://api.orcarouter.ai/v1`. Transient 429/5xx/timeout responses get bounded retries with `Retry-After`/backoff; Mistral is called only after primary attempts are exhausted.

### 5. Adaptive W2E proxy

Live opportunity remains dominant. Ticker/hour/lane affinity, recency, exploration and saturation still provide bounded corrections. v11.1 adds a modest preference for a valid actionable plan over an otherwise similar observation-only event. Outcome posts remain excluded from adaptive market learning.

### 6. Dashboard

GitHub Pages still auto-refreshes hourly at minute 17 and can be run manually. The `Результаты` tab now represents only v11.1 integrity-verified setups and reports any quarantined legacy rows separately.

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
OUTCOME_MAX_JOURNAL_TRADES=600
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

Required GitHub Secrets remain `SQUARE_API`, `ORCAROUTER_API_KEY`, `MISTRAL_API`.

## W2E-oriented selection knobs

```env
VALID_PLAN_EVENT_BONUS=4.0
OBSERVATION_ONLY_EVENT_PENALTY=1.5
W2E_PROXY_MAX_BONUS=5
W2E_PROXY_MAX_PENALTY=3
```

These are bounded selection nudges, not a revenue model.

## Workflows

Publishing: `.github/workflows/run.yml`

Automatic dashboard: `.github/workflows/dashboard.yml` (`17 * * * *`).

## Safety / anti-fabrication

The author and outcome modules reject or avoid invented prices/TP/SL, fabricated reasons/news/whales, invented USDT PnL/leverage, guaranteed-profit language, donation/tip begging, like/comment/follow solicitation, incomplete plan-valid posts, historical outcome reconstruction, fingerprint mismatches, and ambiguous target+stop 1m candles.

## Local validation

```bash
python -m pip install -r requirements.txt
python config_check.py
python run_tests.py
```

Long stress tests:

```bash
python repetition_test.py
python event_repetition_test.py
```

See `CHANGES_V11_1.md` and `V11_1_SETUP.md`.
