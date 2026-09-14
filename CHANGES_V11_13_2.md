# v11.13.2 — Exact Mistral Large 2512

- Switched the primary author to the exact account-enabled `mistral-large-2512` model.
- Avoided the restricted `mistral-large-latest` alias and the 20,000 TPM ceiling of `mistral-small-latest`.
- Preserved six TRADE/EVENT variants and the improved Binance Square prompts.
- Increased Mistral retry spacing to respect the account's 1 request/second limit.
- Kept deterministic templates disabled whenever an AI token is configured.
