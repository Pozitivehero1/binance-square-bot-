# v11.4.2 Reach Quality

This release focuses on reach quality without changing trade-plan geometry or the v11.3 outcome policy.

- Adds a conservative semantic-quality gate for obvious typos, prompt leaks, unsupported timing/certainty and pushy trading language.
- Applies the semantic gate both while ranking AI drafts and again at the final publisher boundary.
- Strengthens proven ticker/hour reach priors after enough mature samples, while preserving a live-event escape hatch for fresh/audience-breakout opportunities.
- Reduces deterministic comparison slots from 2 to 1 when AI is healthy and raises the AI author preference.
- Requests up to 8 AI variants for TRADE and EVENT copy.
- Tags new publication analytics and new trade-journal rows with `engine_version=v11.4.2` so future dashboard slices can compare versions cleanly.
- Keeps Entry/SL/TP geometry, confirmed-entry tracking, TP3-only public outcomes, hidden stop/TP1/TP2 follow-ups, and cashtag normalization unchanged.
