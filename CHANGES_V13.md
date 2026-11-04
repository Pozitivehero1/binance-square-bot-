# v13.0 — editorial engine rewrite, 4 November 2026

## Observed starting point

The committed snapshot from 2026-11-04 06:13 UTC reports 318 age-matched 24h
samples over seven days. Market observations: median 11 views (258 measured
posts); trade plans: 11 (41 posts); news: 6 (19 posts). None reached 100 views
in these age-matched groups. These are account observations, not proof of a
particular Binance recommendation algorithm or a shadow ban.

The 14:00 UTC production run (41843377337) ended with no publication. Logs show
DeepSeek cooldown, a Gemini error, Groq limits, Mistral HTTP 429, Orca capacity
HTTP 503 and repeated attempts after the scan budget had already expired.
Recent public texts repeatedly described minor moves and volume ratios; several
inferred accumulation/distribution or participant demand from insufficient data.

## New production path

`run_bot.py` now calls `squarebot.pipeline.run` directly. Discovery, topic
selection, provider failover, factual substitution, repeat memory, charts and
rollout metrics are separate ordinary modules. The old runtime monkey-patch
stack is not installed. Existing publisher receipt/intents and analytics are reused.

No frequency caps, predicted-view rejection, template outage copy or forced
trade plan. One source pool for news and market stories, one shared AI budget,
one send transaction, clear failure/skip/published statuses.

News no longer requires a cover to enter discovery. Full RSS content is used
when supplied. Short input produces a short report; available source covers can
support articles. Market topics compare equal windows from contiguous closed
candles; generated graphs carry UTC ranges and no fabricated trading levels.

The legacy source files remain available for analytics and regression coverage.
They are not a second publication engine. Rollback is a normal revert of this
release commit; state and old trade journals have not been erased.

## Verification

`editorial_engine_test.py` checks source windows, stale/gapped candles,
news evidence, template repeats, budgets and cooldowns, confirmed/ambiguous
sends, crash recovery, dry runs and age-matched metrics. The existing full
regression suite is retained; its runtime-entry test now checks the new path.
Live provider availability and actual reach must be assessed from subsequent
Actions runs and measured posts, not inferred from offline tests.
