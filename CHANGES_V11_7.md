# v11.7 — Account-Specific Reach Recovery

- Added a recovery-only policy driven by this account's own mature Binance Square analytics.
- Kept the external ~20-minute trigger unchanged; v11.7 changes selection quality, not cron cadence.
- Amplified proven ticker and local-hour affinity during reach recovery while reducing exploration of unknown tickers.
- Added a 30-minute distribution-health signal: recent first-test median is compared with the preceding 7-day baseline.
- During severe first-distribution weakness, ordinary candidates in historically weak hours are blocked unless they are exceptional live events.
- Strengthened content-format learning during recovery. Proven formats receive a bounded boost; historically weak families receive a bounded penalty.
- Added recovery priors from current account evidence: `event_market_story`, `micro_note`, `event_one_price`, `one_level`, and `two_paths` are favored; `risk_first`, `trade_map`, `event_no_trade`, `volume_read`, and `hot_take` are de-emphasized.
- Deterministic writers are demoted further during recovery and blocked during severe 30-minute distribution weakness.
- Outcome posts remain disabled while reach recovery mode is active.
- Trade-plan math, public Entry/SL/TP contracts, Binance publishing, analytics storage, and the external cron are unchanged.
- Added offline regression coverage for strong/weak hour concentration, format recovery ranking, deterministic penalties, and weak-hour blocking.
