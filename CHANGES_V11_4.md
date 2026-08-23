# v11.4 — Reach Writer

Editorial-only upgrade based on the live dashboard after several days of v11.3.

- Keeps market selection, trade-plan geometry, confirmed-entry, stop policy and Outcome Engine unchanged.
- Preserves deterministic copy as an outage safety net, but when AI returns valid drafts it contributes only a small comparison set instead of filling most candidate slots.
- Gives valid Mistral/DeepSeek drafts a bounded ranking bonus; factual, quality, similarity and conversion gates remain mandatory.
- If the full AI provider chain fails once, the writer now uses the configured outer retry before falling back.
- Strengthens the first-line brief: lead with the strongest factual movement/activity/level/conflict instead of a generic intro.
- Applies the same policy to TRADE and EVENT copy.

Baseline used for the decision: AI-authored mature posts have materially higher median views than deterministic copy in the current dashboard, while v11.3 trade/outcome metrics improved and are intentionally left alone.
