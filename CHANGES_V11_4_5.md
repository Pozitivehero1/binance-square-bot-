# v11.4.5 Production Guard

This release fixes two production regressions observed after v11.4.4 without changing the trading geometry or the v11.3 outcome policy.

## 1. Canonical single trade plan

AI prose is no longer trusted to own the visible Entry/SL/TP ladder. Before validation, Python removes AI-written plan rows and appends exactly one canonical block from the Python-owned levels.

This prevents malformed posts such as a truncated `TP3 100,` followed by a second complete plan block.

The final publisher also rejects duplicate TP blocks, duplicate plan blocks, truncated TP numbers and dangling plan-number fragments.

## 2. Stronger semantic rejection

The final semantic gate now rejects unsupported narrative inventions observed in live posts, including invented buyer/seller intent, unsupported time-of-day context, fabricated "second/third order" support/resistance language and over-aggressive risk wording.

## 3. Recovery gate rebalanced

The v11.4.4 recovery gate could suppress a strong live candidate because one historical reach threshold was missed by a few points. v11.4.5 adds a bounded live-interest recovery path for AI-authored candidates that simultaneously have strong demand, opportunity, monetization, activity and selection quality.

Weak ordinary cycles, stale markets and deterministic fallback copy remain under stricter thresholds.

## Preserved behavior

- Entry/zone, stop and TP1/TP2/TP3 calculations are unchanged.
- Confirmed-entry behavior is unchanged.
- TP1 and TP2 remain internal-only outcomes.
- STOP remains internal-only.
- Only verified TP3/target-complete outcomes are public by default.
- Clickable cashtag punctuation normalization remains enabled.
- External cron cadence remains unchanged.
