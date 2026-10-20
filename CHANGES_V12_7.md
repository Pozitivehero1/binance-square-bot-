# v12.7 — Evidence-led Publishing

Publishing still uses the same 20-minute schedule, existing daily limits, global
interval, ticker cooldown, news cooldown, one-publication-per-scan orchestration
and full public trade-plan safety checks. More selective ranking is not a quota.

* Validate current-price relations (above/below/between), indicator periods,
  volume versus trade count, spelled-out timeframes and signed price changes.
  Validate again at the publication boundary and retain the fact package.
* Give each independent DeepSeek author request its own proxy conversation id.
  The web proxy otherwise retains previous markets/news under the same user id.
* Build an evidence-led story brief, rank stronger price/volume events and
  penalize repeated story kinds and semantically similar copy across tickers.
  Stock headline keywords no longer produce near-perfect hook scores.
* Use measured 23–25h observations in learning. Remove lifetime substitutions
  and fixed early-view extrapolation. Recovery uses per-post medians with sample
  minima, not quantity-dependent totals.
* Split NEWS from observations; expose sample counts, 100+ rate and interactions
  per 1,000 views. Retained historical lifetime fields are labelled separately.
  Fetch bounded post details when pagination misses due measurement windows.
* News needs a specific event, an exact supporting RSS quote and source-backed
  numbers. Reject roundups, repetition and filler; allow concise reports and
  append the source domain. Keep the full source URL in stored evidence.
* Chart titles wrap inside the canvas; show closed-candle timeframe and UTC.
  Chart VWAP uses the same rolling 50 candles as the indicator engine.
* Enable the v5 reader-format experiment without changing cadence. Retain the
  actual generated arm; only measured 24h outcomes count. Assignment is not
  proof of causality across different markets and dates.

`quality`, `appeal`, `conversion`, affinity and the 100-view estimate remain
editorial diagnostics, not measured reach or conversion probabilities. Provider
and version comparisons across different dates must not be read as causal.

Suggested profile description (account metadata, outside bot publishing):

> Короткие разборы рынка: что изменилось, где риск и чем закончились прошлые сценарии. Проверяемые данные, понятные графики и открытые итоги.

Validation covers the published S/ENA errors, correct conditional statements,
unit/sign checks, no lifetime-as-24h fallback, no recovery by posting more,
news grounding, independent proxy sessions, unchanged cadence and the existing
offline/stress suites. Live previews do not call the publisher.
