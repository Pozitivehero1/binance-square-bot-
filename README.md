# Binance Square Bot — v11.15 Reach-to-W2E Learning

Production bot for `PozitiveHero`: live TRADE/EVENT selection, fact-locked AI
copy, public-performance learning, a hard full-plan contract and exact
post-bound trade outcomes. v11.15 spends the limited AI draft budget on formats
that have actually earned reach for the account and learns trade-plan quality by
decision mode as well as ticker.

No bot can guarantee views or a fixed W2E payout. v11.15 improves the parts the
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
- TP3 outcomes are refreshed every run but publish only as a fallback when no
  fresh candidate wins and reach recovery is inactive.

## Integrity contract

Every `plan_valid=true` TRADE or EVENT post must expose LONG/SHORT, entry or
entry zone, stop, TP1, TP2 and TP3 in its public text. Observation-only EVENT
posts may omit a plan but cannot invent one.

Trade outcomes are tied to the exact source post ID and text fingerprint.
Closed Binance 1-minute candles verify entry and target order. Ambiguous
target-and-stop candles never produce an automatic claim. Public outcome posts
are final-only by default (`TP3`); partial targets and stops remain internal.

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
