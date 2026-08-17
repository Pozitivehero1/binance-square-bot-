# v11.1 — Outcome Integrity + Full Public Plan

This release fixes two production issues found immediately after v11 deployment.

## 1. Full trade plan is now a hard publication contract

For every `plan_valid=true` post — TRADE **and** EVENT — the published text must explicitly contain:

- LONG / SHORT;
- entry price or entry zone;
- stop / invalidation price;
- TP1;
- TP2;
- TP3.

DeepSeek/Mistral are instructed to include the full plan. If an AI draft omits part of it, Python appends a compact fact-locked plan block. The writer validator and a second independent pre-publication guard then verify the final text. A plan-valid post cannot be published if the complete plan is not public.

Observation-only EVENT posts remain allowed, but they are explicitly forbidden from inventing direction, entry, stop or targets.

## 2. W2E-proxy selection now modestly prefers actionable valid plans

A valid full plan gets a bounded selection bonus; observation-only EVENT candidates receive a small penalty. Live market opportunity, freshness, demand, risk, factual safety and adaptive account history remain dominant.

## 3. Unsafe v11 outcome backfill is removed

There is **no historical setup reconstruction** in v11.1. Outcome tracking starts only from new posts published by v11.1 whose complete plan is explicit in the text.

On first load, any schema-v1/v11 `trade_journal.json` rows are automatically quarantined as `legacy_disabled`. This prevents cached/backfilled setups from producing another incorrect follow-up.

## 4. Exact source-post binding

Every new tracked setup gets:

- `source_post_id` — exact Binance Square post ID;
- `setup_id` — SHA-256-derived fingerprint of source post ID + symbol + direction + entry zone + stop + TP1/2/3;
- `source_text_hash` — hash of the exact published text;
- `tracking_version=2`;
- `public_plan_complete=true`.

Before each outcome check, the fingerprint is verified. Any tampered/inconsistent row is moved to `manual_review` and can never auto-publish a result.

## 5. Outcome text and card share one fact object

- partial target event => `TP1/TP2/TP3 HIT` consistently in text/card;
- final event is possible only when TP1 + TP2 + TP3 are all hit;
- final card shows `TP3 · ALL TARGETS HIT`;
- a `target_complete` card with anything except TP3 is rejected;
- stop outcomes cannot be rendered as target outcomes.

The conservative same-1m-candle ambiguity guard remains: if an unhit target and stop are both touched in the same closed 1m candle, no automatic claim is made.

## 6. DeepSeek / dashboard / adaptive learning preserved

- `deepseek/deepseek-v4-pro-free` through OrcaRouter remains primary;
- transient 429/5xx gets up to 4 DeepSeek attempts with Retry-After/backoff before Mistral fallback;
- dashboard still auto-deploys hourly at minute 17;
- Outcome posts remain `learning_eligible=false` so result posts cannot distort fresh-market ticker/hour/lane affinity.

## Regression coverage

Standard suite now includes `public_plan_contract_test.py` plus journal integrity/migration tests. Long repetition suites are still available separately.
