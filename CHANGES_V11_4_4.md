# v11.4.4 Recovery Selection

This patch is a recovery release after the first version-isolated v11.4.3 sample showed a reach regression versus v11.4.2.

## What changed

- AI-first fallback was corrected. Two validated AI drafts are now enough to form the final author pool.
- When two or more AI drafts are valid, deterministic copy does not compete with them.
- When only one AI draft survives validation, only one deterministic comparator is added instead of rebuilding a full deterministic pool.
- When AI is fully unavailable, the complete deterministic fallback remains available for reliability.
- DeepSeek/OrcaRouter `503 model_not_found / no available capacity` now falls through to Mistral immediately instead of retrying an unavailable free-model pool. Other transient errors keep bounded retries.
- A new `recovery_guard.py` adds a second publication-quality decision after the existing reach gate. Fresh/audience-breakout events retain a low-friction escape hatch, while ordinary, stale and deterministic-fallback posts need stronger evidence before they consume a publication slot.
- The recovery guard uses live opportunity, audience demand, attention/micro freshness, W2E proxy, selection score, final reach score, lane, plan availability and writer source. It is not a hard ticker blacklist.
- Semantic quality checks now reject unsupported target timing such as “less than half an hour”, “in the first hours”, and pushy urgency such as “act fast or miss it”. Factual windows such as “price changed over 5 minutes” remain allowed.
- AI temperature is reduced slightly from 0.72 to 0.70 to reduce unstable phrasing without making the feed deterministic.

## What did not change

- Cron dispatch cadence is unchanged.
- Entry/zone, SL, TP1/TP2/TP3 geometry is unchanged.
- Confirmed-entry logic is unchanged.
- v11.3 final-only public outcome policy is unchanged: TP1/TP2/STOP stay internal; verified TP3 completion may be public.
- Clickable cashtag normalization remains enabled.
- Existing chart/outcome-card design is unchanged.

## Why

The version-isolated dashboard showed v11.4.2 at a 128-view mature median (39 mature posts) versus v11.4.3 at a 93-view mature median (49 mature posts). v11.4.3 also increased deterministic author share because its “healthy AI pool” threshold was too high. This release fixes that regression and makes weak-market cycles skip publication instead of forcing an ordinary post every cron run.
