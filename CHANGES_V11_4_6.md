# v11.4.6 — Cadence Recovery

## Why

v11.4.5 correctly blocked stale and weak filler, but the post-selection Recovery Gate became too strict for some genuinely strong live AI posts. A production XRP cycle had already passed the normal Distribution Gate with reach 74.4 and had audience demand 90.8 / W2E 63.7, yet was skipped because learned selection was 61.6 versus the ordinary-event recovery cutoff.

## Changes

- Added a **high-demand AI cadence recovery** path for non-stale candidates that already passed the normal Distribution Gate.
- Added a narrower **actionable-plan cadence recovery** path for valid Entry/SL/TP plans whose learned selection prior is only modestly below the old cutoff.
- Deterministic fallback copy gets no cadence escape.
- Stale-event protection remains hard except for the existing exceptional-demand escape.
- Weak high-demand candidates still fail if opportunity, monetization or live activity is insufficient.
- Added the exact production XRP regression case to `recovery_guard_test.py`.
- Added runtime verification in `runtime_hotfix_v1146.py` so Actions fail closed if the cadence recovery contract is missing.

## Unchanged

- Cron cadence (~20 minutes) is unchanged.
- Main Distribution Gate is unchanged.
- Trade geometry, Entry/SL/TP1/TP2/TP3 and confirmed-entry logic are unchanged.
- Public outcomes remain final-only: TP1/TP2/STOP stay internal, verified TP3 may publish.
- Text integrity, language guards, fact consistency and canonical public plan checks from v11.4.5 remain enabled.
