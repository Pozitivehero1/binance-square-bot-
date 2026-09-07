# v11.9 — Writer Hardening

v11.9 keeps the v11.8 distribution-recovery logic unchanged and targets the main live-content failure found in production: formally valid AI/repaired drafts could still contain visibly broken Russian, placeholder leakage or repeated repair filler.

## Changes

- Final publication guard now includes language-integrity and text-artifact checks, so upstream quality scores cannot override malformed final copy.
- Blocks high-confidence production corruption such as `v00397`/`[v00389;v00405]` placeholders, hallucinated `@handles`, known gibberish fragments and visibly unfinished Russian clauses.
- Adds regressions based on the malformed ORCA/HEMI production examples.
- Repaired EVENT prose is now strict: no static neutral filler paragraphs are appended to make a weak repaired candidate long enough.
- If insufficient genuine AI prose survives repair, that candidate is rejected instead of being converted into repetitive pseudo-human copy.
- v11.9 is stamped as a separate engine version so dashboard learning can compare it against v11.8 without mixing cohorts.

## Intentionally unchanged

- v11.8 30m and 30m→2h distribution-health logic.
- Market scanner and trading mathematics.
- Entry/SL/TP ownership and public-plan contract.
- External ~20 minute trigger cadence.
- Deterministic fallback remains available as an outage safety net and remains separately identifiable through `writer_source`.

## Success criteria

Judge v11.9 separately by writer source. The first requirement is zero malformed published copy. Reach should then be compared on clean AI-authored cohorts using 30m median, 30m→2h expansion and mature per-post median, without mixing deterministic fallback with AI-authored posts.
