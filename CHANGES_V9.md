# Audience Author v9

## Market selection

- Added 5m `MicroAttentionSnapshot` and event age.
- Reweighted market selection toward audience demand + fresh attention.
- Raw x-volume now saturates and cannot dominate ranking by itself.
- Added stale-event penalty and extreme-move saturation.
- Broad scan increased to 120 symbols; 36 reach confirmation stage; up to 20 final technical candidates.
- Strict and balanced candidates compete in one final event ranking.
- BTC conflict is a soft penalty by default rather than an absolute veto.
- A low-baseline-demand coin needs an exceptional fresh event to publish.

## W2E-oriented plan

- Python now owns entry, entry zone, stop, TP1, TP2, TP3 and R/R for every target.
- TP1 floor is 1.0R where geometry allows; TP3 must meet the public R/R floor.
- Public risk has a hard maximum.
- Trade state distinguishes current decision, retest, breakout and breakdown states.
- A post can no longer claim it is waiting for a retest of the price it is already trading at.

## Full-post Mistral author

- Mistral receives a semantic fact package instead of a nearly finished template.
- Last 8-10 posts are included as negative examples to avoid their syntax/composition.
- Mistral may choose what market facts to mention, but may not alter trading facts.
- Numeric fact-lock validates ordinary numbers and x-volume multipliers.
- Full trade ladder is mandatory in `trade_map` and `risk_first` formats.
- Invalid Mistral output is rejected; deterministic fallback remains available.

## Anti-robotic layer

- 9 content formats and 6 chart compositions.
- Phrase-family cooldown penalizes repeated "confirmation / wait / hold the level / don't chase" structures.
- Similarity gate tightened to 0.46.
- Questions are sparse; hashtags disabled; emoji are contextual and rare.
- Deterministic fallback also rotates multiple phrasings and skips rather than publishing a near-duplicate.

## Visuals

- `minimal_chart`: single-decision visual.
- `event_chart`: event/volume emphasis.
- `trade_map`: entry zone + TP1/TP2/TP3 + stop.
- `scenario_chart`: conditional plan view.
- `context_chart`: cleaner market-context view.
- `clean_chart`: compact general chart.

## Safety

- No LLM-generated prices.
- No unsupported market/news claims.
- No guaranteed outcomes or pressure language.
- No live publication is performed by any included test.
