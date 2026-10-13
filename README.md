# Binance Square Bot — v12.0 Quality & Reliability Engine

Production bot for `PozitiveHero`: live TRADE/EVENT selection, fact-locked AI
copy, public-performance learning, a hard full-plan contract and exact
post-bound trade outcomes. v11.17 keeps the 20-minute market scan and adds an
account-specific pre-publication model trained on mature posts that reached 100+ views.

No bot can guarantee views or a fixed W2E payout. v11.17 improves the parts the
bot controls—candidate quality, copy selection, repetition, timing and feedback—
and keeps the 20-minute trigger while preserving factual and publication-safety
checks.

## Reach policy

- Live market facts remain the primary signal. Historical performance supplies
  bounded corrections; it cannot manufacture a setup or bypass safety gates.
- Recent performance uses a 7-day lookback and 3-day half-life.
- Draft ranking learns from lane, format, writer, event class and direction.
- Early 30m/2h/6h views are projected with account-calibrated factors
  `1.25/1.12/1.04`; mature 24h views take precedence.
- Recovery mode compares projected rolling reach with mature daily baselines,
  tightens weak candidates and weak historical hours, and never forces cadence.
- Target copy length is 220–430 characters. The AI writes the narrative; Python appends one canonical plan. Specific live facts beat generic
  prose; repetition and structural similarity remain hard constraints.
- Groq Qwen is the primary author; GPT-OSS, Mistral, OrcaRouter and OpenRouter
  form the guarded fallback chain. Production does not silently replace a
  configured AI author with deterministic copy.
- Lane and format learning uses confidence-shrunk observed reach lift. Recent
  format use remains a diversity penalty, but weak formats are no longer forced
  into the three-slot AI request merely because they were used less often.
- W2E-oriented trade ranking learns from verified outcomes by public decision
  mode (`at_level`, retest, breakout) and ticker. A bounded feed-mix rule keeps
  actionable plans present without discarding a materially stronger live event.
- TP3 completions and verified stops are refreshed every run but publish
  only as a fallback when no fresh candidate wins and reach recovery is inactive.

## Integrity contract

Every `plan_valid=true` TRADE or EVENT post must expose LONG/SHORT, entry or
entry zone, stop, TP1, TP2 and TP3 in its public text. Observation-only EVENT
posts may omit a plan but cannot invent one.

Trade outcomes are tied to the exact source post ID and text fingerprint.
Closed Binance 1-minute candles verify entry and target order. Ambiguous
target-and-stop candles never produce an automatic claim. Public follow-ups
report only verified complete targets or stops, never interim TP1/TP2.

## v12.2 — accountable analysis and honest experiments

- Corrected the A/B author assignment for TRADE: the real `market.ticker`
  is used in both generation and dashboard attribution. Separate v2 cohorts
  exclude the previously misclassified observations.
- Only genuine TP3-complete and **stopped** outcomes may produce public
  follow-ups, sourced from the original post and closed 1-minute candles.
  Same-candle target/stop ambiguity is still quarantined. Both positive and
  negative outcomes are reported transparently without invented PnL.
- At most one outcome follow-up per six hours, and only as a fallback when
  there is no suitable live trade/event. Interim TP1/TP2 remain internal.
- Verified outcomes use deterministic factual wording to avoid AI inventing
  performance; ordinary market posts still use the existing AI author chain.
- Reduced the arbitrary TRADE-lane rotation bonus, so the real market story
  has greater precedence over writing another speculative plan.

## Semantic accuracy control (12 October)

- Final publication guard rejects explicit RSI interpretation inversions,
  e.g. calling RSI 63.2 "oversold" or RSI 27 "overbought".
- Writer instructions reinforce technical accuracy; the existing market-data
  fact lock and Entry/SL/TP validation remain unchanged.
- This is a conservative semantic safeguard, not a guarantee of engagement.
  Observe post-quality and 24h reach before modifying editorial experiments.

## Reader-value experiment: October 2026

- **Novelty before AI:** a ticker normally needs a 12-hour gap before another
  story. A genuinely exceptional **new** 5m/15m movement may qualify after
  four hours; repetitive minor observations do not.
- **Measured two-arm experiment:** deterministic day/ticker assignment chooses
  **what_changed** (explain the verified move) or **risk_map** (explain an
  observed contradiction). Both obey the same price/number integrity checks.
  Group assignment is logged and persisted with each AI post.
- **Fair comparison:** `dashboard/summary.json` now includes
  `reader_experiment` with separate 24h medians and 100+ hit rates for each
  arm. Only actual 24-hour milestones enter the comparison; wait for at least
  20 matured posts per arm before making a decision. Different market events
  still mean this is directional evidence, not a guarantee of causation.
- **Safety:** publisher does not retry an ambiguous send, preserving protection
  against duplicate posts. Market scans still run every 20 minutes; no
  artificial daily publication quota or paid AI dependency.

## Reader-first editorial controls

Production runs with `ENABLE_EDITORIAL_STORY_GATE=1` and
`ENABLE_EDITORIAL_COPY_FILTER=1`. A publication needs an actual measured
price/volume anomaly or high-interest confirmed setup rather than a high score
on generic indicators alone. Both EVENT and TRADE lanes scan continuously;
quiet cycles are reported as deliberate skips, not fake successful posts.

With `EVENT_OBSERVATION_PREFERRED=1`, EVENT posts provide readable,
observation-only market context **without unsolicited Entry/SL/TP blocks**.
TRADE posts still use the complete, Python-owned and verified public trade
plan. The original hard facts, profile de-duplication, and API safety checks
remain mandatory. These controls can be temporarily turned off by setting
the corresponding env variable to `0`. Changes in organic reach are not
guaranteed; measure comparable cohorts at 2h, 6h, and 24h.

## v12.0 improvements

- **Honest run results**: `operations.py` writes `state/run_telemetry.json`,
  a concise Actions run summary, and warnings after 6 hours without a
  confirmed post. A successful market scan is *not* a confirmed publication.
- **Stronger headlines**: `editorial_repair.py` reflows oversized AI headlines
  into the body without removing original words or numbers; downstream
  fact-consistency and trade-plan validators remain mandatory.
- **Adaptive lane mix**: `content_strategy.py` gives EVENT a bounded
  +/-4 point preference only when sufficient, mature, recent EVENT and TRADE
  results exist. Live market gates always override historic popularity.
- **Safe pre-send failure recovery**: if the Node.js process cannot be started,
  its pending publication intent is cleared; ambiguous network sends remain
  quarantined to prevent duplicates.
- **Visibility**: one verified Square post ID, a known no-post status, or
  a failed run. Hard 100-view thresholds remain diagnostics, not guarantees.
- **Compatibility**: existing charts, attribution, trade math, publication
  deduplication, and offline test suite remain in place.

## Gemini API (no credentials committed)

Create a new API key in Google AI Studio and add it in GitHub repository
**Settings → Secrets and variables → Actions → New repository secret**
with the exact name `GEMINI_API_KEY`. Never paste API keys into repository
files, workflow YAML, issue comments, or chat messages. Rotate a key if exposed.
The bot uses `gemini-2.5-flash-lite` first and retains Groq/Mistral/Orca/OpenRouter
as fallback providers. Gemini usage remains subject to Google's region/quota limits.

GitHub workflow opts into `ENABLE_PROVIDER_OUTAGE_COPY=1` to allow the existing
fact-validated, market-data-derived templates only when no valid AI draft
survives. No invented market data or bypass of the public trade-plan contract.
`VIEW_TARGET_HARD_GATE=0` keeps the 100-view estimate for analysis without
blocking every post in a low-reach period; no view target can be guaranteed.
Every run writes its reason to the Actions job summary.

## Production settings

See [CHANGES_V11_15.md](CHANGES_V11_15.md) for the latest evidence and changes.

The active configuration is in `.github/workflows/run.yml`; `env.example`
contains safe local defaults (`DRY_RUN=1`). Required GitHub secrets are:

- `SQUARE_API`
- `GROQ_API_KEY`
- `ORCAROUTER_API_KEY`
- `MISTRAL_API`
- `OPENROUTER_API_KEY` (optional independent fallback)

The publishing workflow is externally dispatched approximately every 20
minutes. The analytics dashboard refreshes hourly through
`.github/workflows/dashboard.yml`.

Startup is cumulative: `run_bot.py` calls one read-only verifier,
`runtime_release.py`. It does not apply a chain of source-rewriting hotfixes.

## Local validation

```bash
python -m pip install -r requirements.txt
python config_check.py
python run_tests.py
RUN_STRESS_TESTS=1 python run_tests.py
```

All offline tests avoid market, AI-author and publishing network calls unless a
test explicitly mocks them. See `CHANGES_V11_10.md` for this release.
