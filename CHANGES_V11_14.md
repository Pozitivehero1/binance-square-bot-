# v11.14 — Groq Primary Author

- Added Groq as the authoritative AI author through `GROQ_API_KEY`.
- Primary model: `qwen/qwen3.8-27b`; Groq backup: `openai/gpt-oss-120b`.
- Existing Mistral -> OrcaRouter/DeepSeek -> OpenRouter chain remains available only as AI fallback.
- Long Groq `Retry-After` responses no longer block an entire 20-minute publishing slot; the bot moves to the next Groq model.
- Mistral is reduced to a one-shot fallback so the known free-tier 429 condition cannot add minute-long stalls.
- Deterministic templates remain disabled whenever AI authoring is required. If no valid AI draft survives the existing validators, that publishing slot is skipped.
- TRADE/EVENT provider attribution is patched so Groq-authored text is recorded as Groq instead of Mistral.
- Added offline regression coverage for Groq primary, Groq model failover, JSON request shape, and source attribution.
- GitHub Actions now exposes `GROQ_API_KEY` to the bot and configures the production Groq model chain.

Python remains authoritative for market facts, direction, Entry/SL/TP values and publication safety; the model only writes prose from the supplied semantic package.
