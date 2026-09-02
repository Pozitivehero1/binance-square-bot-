# Binance Square Bot — v11.6 Evidence-Weighted Reach Engine

Production bot for `PozitiveHero`: live TRADE/EVENT selection, fact-locked AI
copy, public-performance learning, a hard full-plan contract and exact
post-bound trade outcomes.

No bot can guarantee views or a fixed W2E payout. v11.6 improves the parts the
bot controls—candidate quality, copy selection, repetition, timing and feedback—
and keeps the 20-minute external scan while allowing weak slots to be skipped.

## Reach policy

- Live market facts remain the primary signal. Historical performance supplies
  bounded corrections; it cannot manufacture a setup or bypass safety gates.
- Recent performance uses a 7-day lookback and 3-day half-life.
- Draft ranking learns from lane, format, writer, event class and direction.
- Early 30m/2h/6h views are projected with account-calibrated factors
  `1.25/1.12/1.04`; mature 24h views take precedence.
- Recovery mode compares projected rolling reach with mature daily baselines,
  tightens weak candidates and weak historical hours, and never forces cadence.
- Target copy length is 220–430 characters. Specific live facts beat generic
  prose; repetition and structural similarity remain hard constraints.
- DeepSeek is primary and Mistral is fallback. Deterministic templates are used
  only when a healthy AI draft pool is unavailable.
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

The active configuration is in `.github/workflows/run.yml`; `env.example`
contains safe local defaults (`DRY_RUN=1`). Required GitHub secrets are:

- `SQUARE_API`
- `ORCAROUTER_API_KEY`
- `MISTRAL_API`

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
test explicitly mocks them. See `CHANGES_V11_6.md` for this release.
