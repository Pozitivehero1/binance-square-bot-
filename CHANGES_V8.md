# Market Attention v8

v8 keeps the v7 event-first market selector and fixes coherence problems found in real published posts.

## Public trade-plan coherence

A new `trade_plan.py` builds the exact plan that is allowed to appear in a post. The public decision level, target and invalidation are evaluated together instead of reusing a technically valid internal TP/stop combination blindly.

Default guards:

```env
MIN_PUBLIC_PLAN_RR=1.30
MAX_PUBLIC_RISK_PCT=9.0
PUBLIC_STOP_BUFFER_ATR=0.75
DECISION_NEAR_ATR=0.30
DECISION_NEAR_PCT=0.25
```

If the public target cannot provide at least 1.30 R/R, or the visible risk is wider than 9%, that market candidate is skipped. A structural retest entry also receives a minimum ATR stop buffer so the bot cannot display absurdly tight stops and artificial 20:1/30:1 R/R.

## Current price vs. level language

The writer now derives one of five states from the actual price/decision-level relationship:

- `at_level` — price is already on the level; copy talks about holding/control;
- `breakout_confirm` — LONG still needs acceptance above resistance;
- `breakdown_confirm` — SHORT still needs acceptance below support;
- `retest_hold` — price is already above a LONG decision level and a pullback can genuinely be called a retest;
- `retest_reject` — the mirrored SHORT state.

`ретест`, `после отката` and similar wording is rejected in states where a future retest is logically impossible or premature. AI output is subject to the same rule.

## More honest event wording

A +1–2% move on ordinary volume is no longer automatically described as a “сильный ход” or “резкий импульс”. Strong adjectives are reserved for genuinely strong movement/volume/attention states.

## Cleaner posts

- default length: 140–500 characters;
- one public target instead of showing a weak first target while calculating R/R to a distant TP3;
- feed-friendly price rounding;
- questions remain occasional (`QUESTION_EVERY=7`);
- generic hashtags remain disabled;
- `📌` is removed;
- only contextual `⚡`, `⚠️`, `👀` are used, with a default 20% rate;
- the emoji rate is now hash-distributed correctly across variants (the previous index-based bucket accidentally decorated too many early variants).

## Media

Charts receive the same decision state as the writer. A chart can therefore label an active level as a check/confirmation instead of drawing a misleading `РЕТЕСТ` marker. Public target and invalidation match the text. Card fallback also renders one public `ЦЕЛЬ` when only one target is intentionally exposed.

## Selection

The v7 Market Attention Engine remains: audience demand + fresh attention + volume anomaly + technical quality + W2E/actionability. v8 adds the public-plan validity gate before a candidate can win.

The external cron can still run every 20 minutes. The bot may skip a run if there is no sufficiently interesting and coherent candidate.
