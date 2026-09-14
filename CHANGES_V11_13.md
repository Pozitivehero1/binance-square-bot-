# v11.13 — Mistral Primary Author

- Mistral now runs first whenever `MISTRAL_API` is configured.
- Production model changed from `mistral-small-latest` to `mistral-large-latest`.
- Added three bounded Mistral provider retries and three author revision passes.
- Rewrote TRADE and EVENT prompts for natural Russian copy, exact JSON output,
  immutable facts, sign consistency, format diversity and silent self-checking.
- A configured AI author can no longer be silently replaced by deterministic
  templates; if all AI drafts fail validation, the candidate is skipped.
- DeepSeek and OpenRouter remain AI fallbacks for transport/provider outages.
