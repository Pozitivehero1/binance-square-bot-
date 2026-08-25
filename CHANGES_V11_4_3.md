# v11.4.3 Language + Reach Guard

## Goal

Protect reach gains from malformed mixed-language AI copy and make new versions measurable without mixing them with older bot history.

## Changes

- Added a conservative Russian-language integrity guard.
  - Blocks prompt/translation leaks such as `in тогда`, `or рынок`, `and потом`, `a второй`.
  - Allows normal market vocabulary such as LONG, SHORT, VWAP, Entry, Stop and TP1/TP2/TP3.
  - Final publisher gate checks language integrity again before Square publication.
- Raised the healthy AI pool target to four valid drafts.
  - Invalid AI variants are rejected and the second AI attempt is used before fallback.
  - If fewer than four valid AI drafts remain after retries, deterministic generation expands as an outage/degraded-AI safety net.
  - When AI is healthy, deterministic remains only a small comparison fallback.
- New publications and trade setups are stamped with `engine_version=v11.4.3` through the existing runtime version field introduced in v11.4.2.
- Added `dashboard_version_enrich.py`.
  - Dashboard JSON gains version-isolated reach metrics.
  - Dashboard JSON gains version-isolated outcome metrics.
  - Older unversioned history is intentionally excluded from version comparisons.
- Added `language_quality_test.py` to the standard offline regression suite.

## Unchanged

- Posting cadence policy.
- Entry/SL/TP1/TP2/TP3 geometry.
- Confirmed-entry tracking.
- Outcome Engine rules.
- Public outcome policy: TP1/TP2/STOP remain internal; verified TP3 completion is the public result.
- Existing charts/cards and media layout.
