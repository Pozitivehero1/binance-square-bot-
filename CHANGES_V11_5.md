# v11.5 — Quality-First Reach Recovery

- Removed the eight-step runtime hotfix chain. `run_bot.py` now calls one
  read-only cumulative release verifier and never rewrites source at startup.
- Removed v11.4.6 cadence escape paths. A weak tick is skipped.
- Added automatic recovery mode when rolling 24h reach falls below 82% of the
  recent daily median; ordinary posts then face stricter reach, selection and
  opportunity thresholds.
- Added a two-TRADE saturation rule that boosts an already eligible EVENT but
  never invents filler.
- Adaptive defaults now use a 7-day lookback and 3-day half-life, with early
  30m/2h/6h performance contributing conservatively before 24h maturity.
- Added semantic rejection for mixed-script words, repeated English fragments
  and contradictory multiplier wording such as `х2 в разы`.
