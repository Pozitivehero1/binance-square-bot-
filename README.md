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
- The configured DeepSeek proxy is the primary author. The existing
  Gemini/Groq, GPT-OSS, Mistral, OrcaRouter and OpenRouter providers retain
  their fallback ordering. Production does not silently replace a
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

## 15 October audit — avoid template fallback and unverified claims

- **Observed:** v12.5 first 13 posts reached median 15 views (10 mature
  at six hours); 7 of 13 drafts came from deterministic fallback/outcome
  writers, despite DeepSeek being connected. Both figures are early,
  not evidence that DeepSeek lowers reach.
- **Change:** disable `ENABLE_PROVIDER_OUTAGE_COPY` in production. The
  multi-provider AI chain is still intact; when all AI drafts fail fact
  validation, skip a weak post instead of filling the feed with mechanical
  templates. Deterministic *verified trade outcomes* remain available:
  these are retrospective fact-based reports, not generic market filler.
- Block unsupported inferences about traders' actual cost basis and unverified
  historical superlatives (e.g. "first time in recent history"). Values from
  hourly averages do not reveal individual trade entry prices.
- Keep honesty above cadence: a green Actions run can mean a valid skip.
  Success is tracked using real mature views and engagement, not post volume.

## v12.5 — clear language without amateur market conclusions

- **Audience:** understandable to a curious first-time investor, defensible to
  an experienced trader. Explains *what happened and why it matters*, without
  talking down or promising a profitable outcome.
- DeepSeek remains primary and keeps editorial freedom. System prompts request
  plain Russian prose and normally no RSI/ADX/VWAP/ATR/EMA/MACD in the authored
  narrative. One genuinely necessary indicator may be explained briefly and
  carefully; there is no mandatory glossary or formulaic tutorial.
- Reader-voice preference lowers the rank of unexplained abbreviation clusters
  and unsupported metaphors. It excludes the canonical, Python-owned
  LONG/SHORT/TP1–TP3 block from evaluation. No new editorial hard blocker.
- Original numeric fact lock, trade geometry, no fake-news rules and
  publication safety remain authoritative. An indicator alone never proves
  trader intention or an inevitable market reversal.
- New A/B cohort `v4` prevents misleading comparisons between the previous
  more technical prompts and the reader-friendly copy.
- These changes target clarity and trust, not guaranteed reach.

## DeepSeek 15:20 incident: reject the right things

- A verified `$PUMP` 5m -0.84% / x4.49 volume, with reach score 78.6
  and an already validated DeepSeek draft, was rejected solely by the
  *second* legacy editorial selection score gate (60.6 < 71.5).
- The recovery gate now accepts a **measured fresh shock** only when price,
  relative 5m volume, audience demand, novelty and the existing independent
  reach/fact-quality checks all pass. It is not a forced cadence exemption;
  ordinary and stale markets remain blocked.
- Genuine level-centric headlines count as reader insight. The statement
  `не вход` is allowed for observation-only drafts; an actual proposed
  entry is still forbidden without a valid Python-owned plan.
- Fixed number validation for outcome reports on tickers starting with digits
  and log a safe, precise warning when deterministic outcome copy cannot pass.
  No invalid outcome is published.
- DeepSeek's JSON `candidates` response is expected; one rejected AI draft
  does not mean the API failed. New authored posts remain subject to all hard
  market and publication preflight checks.

## v12.4 — DeepSeek editorial freedom

- DeepSeek is still primary. It now chooses story angle, length, paragraph
  count, opening and conclusion; requested format IDs are metadata with
  optional inspiration rather than rigid prose templates.
- Actual trade entry/stop/TP1–TP3 figures, fact locking, ticker,
  semantic review, duplicate protection and no invented catalysts remain strict.
- Live body limits are broadened to 185–520 characters (including any public
  trade plan). Reader-value scoring no longer rewards RSI/VWAP/ADX keyword
  density and penalizes multi-indicator dumps.
- Increase API temperature moderately for variation, with conservative output
  validation and Groq fallback unchanged. A/B author-cohort version increments
  to v3 to prevent apples-to-oranges reach comparisons after the prompt change.
- This is an editorial experiment, not evidence or a guarantee of more views.

## v12.3 — Verified outcomes during distribution recovery

- Production startup now preserves the workflow's `OUTCOME_POST_STOPS=1`.
  Previously, an older release configurator silently overwrote it with `0`,
  which disabled honest stop-loss reviews.
- `OUTCOME_IN_RECOVERY=1` allows *verified* outcomes when the rolling
  distribution-recovery flag is active. They are still a fallback after live
  scanning and limited to one public post every six hours (globally).
  Original published levels, candle order, ambiguous-case quarantine and
  idempotent publisher receipts are unchanged.
- Low-demand obscure tickers now need a truly exceptional measured market
  event instead of a routine volume spike to enter the author pipeline.
  Scanning is still every 20 minutes; no forced quota.
- DeepSeek remains the first prose author. Prompt rules reject internal
  ranking scores, urge plain-language value, and do not invent catalysts.
  Final text validation blocks visible internal 0–100 scoring leaks.
- Reach must be measured using comparable, matured posting cohorts; no
  claim that these changes guarantee 100+ views is implied.

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
- Expanded final semantic integrity checks for unsupported buyer counts, fake
  order-book absorption, invalidation in the wrong trade direction, and
  contradictory VWAP explanations.

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

DeepSeek uses repository secret `DEEPSEEK_API_KEY` and variables
`DEEPSEEK_BASE_URL`/`DEEPSEEK_MODEL`. One bounded request is tried before the
existing chain; outages, 401/403/429 and unusable JSON fall back without
immediate repeated DeepSeek requests. The Windows API host must be awake and
online. See [DEEPSEEK_ACTIONS.md](DEEPSEEK_ACTIONS.md).

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
