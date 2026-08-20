# v11.3 — Final-Only Outcomes + Clickable Cashtags

- TP1 and TP2 are still tracked internally but no longer generate public follow-up posts by default.
- Only a verified full TP3 completion is eligible for a public success outcome.
- Stale queued partial-target and stop follow-ups are purged before they can consume a cron slot.
- A final publishing-boundary sanitizer rewrites cashtags attached to a colon, e.g. `$BTC:`, into a whitespace-separated form such as `$BTC —`, so Binance Square can keep the ticker clickable.
- The cashtag fix applies to AI, deterministic, EVENT, TRADE, and OUTCOME posts because it runs immediately before publishing.
- The production entry point applies the patch before importing `main`, so the change takes effect on the next cron run without requiring a full archive replacement.
