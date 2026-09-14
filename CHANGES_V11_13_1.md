# v11.13.1 — Mistral Free-Tier Author

- Switched the production author from the subscription-gated `mistral-large-latest`
  to `mistral-small-latest`.
- Kept Mistral first in the provider chain, the improved TRADE/EVENT prompts,
  three bounded retries and the AI-only publication policy.
- This fixes the observed `403 tier_not_allowed` response on the free Mistral account.
