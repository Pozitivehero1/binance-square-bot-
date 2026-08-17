# Binance Square Bot — v10.1 Adaptive W2E Proxy

Production-oriented Binance Square bot for `PozitiveHero`. The objective is not raw posting volume: it is to publish **fresh, useful, tradable content** that has a better chance to earn reach and to lead readers into a qualified market interaction.

> Important: the bot cannot guarantee a specific number of views or a fixed W2E payout. It optimizes the measurable funnel and keeps hard factual/risk gates.

## What changed in v10.1

### 1. Adaptive ranking is ON

v10 collected real public Square performance in `state/performance_history.json`. v10.1 now uses that history as a **bounded nudge** on top of the live market engine.

The adaptive layer learns:

- ticker affinity — which symbols historically perform better on this account;
- hour affinity — which UTC+3 publishing hours historically perform better;
- lane affinity — EVENT vs TRADE performance;
- relative breakout rate;
- recency decay — recent performance weighs more than old performance;
- exploration — strong new tickers still get a chance;
- saturation — repeatedly posting the same winner is penalized.

Historical performance cannot invent a setup or bypass technical, factual, liquidity, risk, quality or reach gates. Total adaptive influence is capped.

Default controls:

```env
LEARNING_ONLY=0
ENABLE_ADAPTIVE_RANKING=1
ADAPTIVE_MIN_MATURE_SAMPLES=80
ADAPTIVE_LOOKBACK_DAYS=14
ADAPTIVE_HALF_LIFE_DAYS=7
ADAPTIVE_MAX_TOTAL=14
ADAPTIVE_TICKER_MAX=10
ADAPTIVE_HOUR_MAX=5
ADAPTIVE_LANE_MAX=2.5
ADAPTIVE_BREAKOUT_MAX=3
ADAPTIVE_EXPLORATION_MAX=2.5
ADAPTIVE_SATURATION_MAX=5
```

If the analytics cache disappears or there are fewer than 80 mature samples, adaptive ranking automatically disables itself until enough data returns.

### 2. W2E Proxy ranking

We do not have an automated per-post W2E-revenue feed, so v10.1 **does not pretend it can learn directly from USDC**. Instead it adds a small, capped W2E proxy based on observable market qualities:

- liquidity and trading activity;
- current audience demand;
- event freshness;
- actionability;
- valid public trade plan when one exists;
- non-overextended entry quality.

This proxy is deliberately smaller than the live market opportunity score.

```env
W2E_PROXY_MAX_BONUS=5
W2E_PROXY_MAX_PENALTY=3
```

### 3. DeepSeek V4 Pro primary, Mistral fallback

Python remains the analyst and risk manager. The LLM only writes prose from Python-locked facts.

Primary author:

```env
ORCAROUTER_BASE_URL=https://api.orcarouter.ai/v1
ORCAROUTER_MODEL=deepseek/deepseek-v4-pro-free
ORCAROUTER_API_KEY=...
```

Fallback:

```env
MISTRAL_API=...
MISTRAL_MODEL=mistral-small-latest
```

Routing is strict:

1. DeepSeek through OrcaRouter is tried first.
2. If the primary API is unavailable/unusable (timeout, HTTP error, malformed API response), Mistral is called.
3. If DeepSeek responds normally but its prose fails the factual/content validator, the bot retries the primary author rather than silently using Mistral as a style substitute.
4. Deterministic copy remains the last outage-safe fallback.

### 4. No direct engagement/tip begging

The writer prompt and validator reject direct solicitation such as requests for likes, comments, follows, donations/tips or author rewards. The bot can benefit from Binance creator monetization features naturally, but it does not turn posts into donation or engagement bait.

### 5. TRADE + EVENT dual lane stays

#### TRADE lane

Python owns and validates:

- LONG/SHORT direction;
- entry and entry zone;
- stop loss;
- TP1 / TP2 / TP3;
- R/R;
- risk percentage;
- state of the setup (`decision_now`, retest/breakout/breakdown states).

The author cannot change those values.

#### EVENT lane

A fresh audience event is evaluated independently from strict ADX/R/R gates. If there is no valid public trade plan, the post becomes `OBSERVATION_ONLY`; the writer may not manufacture LONG/SHORT, entry, SL or targets.

This keeps discovery broad without turning every market event into a fake signal.

## AI fact lock

Every AI candidate is checked for:

- correct cashtag in the headline;
- no fabricated numbers;
- correct direction;
- correct entry/stop/TP values;
- no future guarantees;
- no invented news, whales, liquidations or reasons for movement;
- state coherence (for example, no “wait for retest” if price is already at the level);
- no hashtags by default;
- no direct donation/like/comment/follow solicitation;
- similarity to recent posts;
- feed appeal / quality / conversion intent.

## Audience-first market selection

The broad scan uses 5m freshness plus 15m/1h context. The shortlist reserves room for:

- liquid/high-demand tickers;
- fresh events;
- technically strong setups.

Huge volume anomalies saturate instead of dominating the score. A stale `x30` volume spike is not automatically better than a fresh `x4` event.

## Dashboard / analytics

`collect_stats.py` reads public Square post metrics and stores them in:

```text
state/performance_history.json
```

The dashboard shows:

- views and engagement;
- 30m / 2h / 6h / 24h milestones;
- ticker affinity;
- hour affinity;
- EVENT vs TRADE;
- relative breakout rate;
- absolute 300+ rate;
- adaptive mode status;
- AI author performance (DeepSeek / Mistral / deterministic).

The dashboard never receives `SQUARE_API`, `ORCAROUTER_API_KEY` or `MISTRAL_API`.

## GitHub setup

Replace the current repository contents with this archive. Keep the same repository/branch so the existing GitHub Actions cache can restore the accumulated analytics state.

Required GitHub Secrets:

```text
SQUARE_API
ORCAROUTER_API_KEY
MISTRAL_API
```

`MISTRAL_API` remains the fallback key. `OPENAI_API_KEY` is optional and not required for the author chain.

The publishing workflow is already in:

```text
.github/workflows/run.yml
```

Your external cron can keep triggering `workflow_dispatch` at the same cadence as before. The cadence is a **market scan frequency**, not a promise to publish every run.

The dashboard workflow is:

```text
.github/workflows/dashboard.yml
```

It can be run manually whenever you want fresh GitHub Pages data.

## Local validation

```bash
python -m pip install -r requirements.txt
python config_check.py
python run_tests.py
```

Optional longer repetition tests:

```bash
RUN_STRESS_TESTS=1 python run_tests.py
```

Local default stays safe with `DRY_RUN=1`.

## Important files

- `main.py` — dual-lane selection + adaptive/W2E-proxy final ranking;
- `adaptive.py` — ticker/hour/lane affinity, decay, exploration, saturation;
- `ai_provider.py` — DeepSeek primary / Mistral fallback routing;
- `writer.py` — fact-locked TRADE author/validator;
- `event_writer.py` — fact-locked EVENT author/validator;
- `trade_plan.py` — entry/zone/SL/TP1-3;
- `opportunity.py` — live market/audience opportunity;
- `monetization.py` — W2E proxy and conversion-intent scoring;
- `performance_store.py` — analytics history and learning summaries;
- `dashboard_builder.py` — static dashboard export;
- `.github/workflows/run.yml` — production workflow.

See `CHANGES_V10_1.md` and `V10_1_SETUP.md` for the short upgrade guide.
