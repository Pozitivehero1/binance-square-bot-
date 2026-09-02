# v11.6 — Evidence-Weighted Reach Engine

- Corrected early-view projection using this account's observed 30m/2h/6h to
  24h ratios (`1.25/1.12/1.04`) instead of generic `5/3.2/2` multipliers.
- Fixed the production workflow that still overrode v11.5 with the old 14-day
  lookback and 7-day half-life.
- Added bounded format, writer, event-class and direction performance scoring
  after text generation, so saved analytics now affect the selected draft.
- Removed outcome-first slot stealing. TP3 state is refreshed first, but an
  outcome can publish only as a fallback when no fresh candidate wins and reach
  recovery mode is inactive.
- Deterministic writers are now outage fallbacks. A healthy AI pool respects
  the configured zero deterministic comparison slots.
- Added editorial specificity/generic-copy scoring and moved the target post
  length to 220–430 characters based on the account's mature reach history.
- Added low-performing-hour tightening during recovery without changing the
  external 20-minute cron.
- Aligned Python defaults, `env.example` and the production workflow so local,
  emergency and hosted runs use the same reach, plan, AI and outcome policy.
- Renamed the cumulative startup verifier to stable `runtime_release.py`; future
  releases update this one file rather than rebuilding a patch chain.
- Added regressions for calibrated feedback, editorial/content ranking and the
  rule that a queued outcome cannot publish before fresh-market selection.
