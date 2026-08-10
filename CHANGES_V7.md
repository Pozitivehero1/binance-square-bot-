# Market Attention v7

This release changes the bot from **setup-first** to **attention-first** selection.
The technical engine still validates the trade idea, but a technically clean chart
is no longer enough to become a Square post.

## What changed

- Added `opportunity.py` with a separate Market Opportunity score.
- Candidate ranking now combines relative audience demand, fresh 15-minute
  attention, technical quality, volume anomaly, move quality and actionability.
- Large already-completed pumps are softly penalized instead of automatically
  winning because of a huge percentage move.
- Strict and balanced technical candidates enter the same attention race; strict
  setups keep a small preference, while an exceptional live event can beat a
  merely neat strict setup.
- The cheap 15m/1h shortlist is attention-aware, so a hot market is less likely to
  disappear before 4h/1d confirmation is fetched.
- BTC disagreement is context by default (`STRICT_BTC_FILTER=0`) rather than an
  automatic rejection of a strong alt event.
- Market Opportunity and W2E gates can skip a cron cycle instead of forcing a
  low-interest publication.
- Follow-up posts are disabled by default because the bot cannot reliably know
  whether the previous Square post received enough distribution to justify a
  discovery follow-up.

## Human feed changes

- Normal posts target roughly 150–540 characters.
- Prices are rounded to feed-friendly precision instead of looking like raw API
  output.
- Decision levels are checked against stop/TP1 so the copy cannot say “wait for a
  level” that is already beyond the invalidation/target corridor.
- Questions appear occasionally (`QUESTION_EVERY=7`), not at the end of every
  post.
- Generic hashtags are off by default; the cashtag stays the primary instrument
  reference.
- A maximum of one contextual emoji may appear on a minority of posts
  (`EMOJI_RATE=0.24`). It is decoration, not a ranking assumption.
- Charts are the default media format.
- Duplicate/near-duplicate copy remains hard-gated with a 0.50 similarity limit.

## Default GitHub Actions profile

The included `.github/workflows/run.yml` is ready for an external cron that calls
`workflow_dispatch` every ~20 minutes. The cron is a market scanner; publication
is conditional on the opportunity/reach gates.

Required repository secrets:

- `SQUARE_API`
- `MISTRAL_API` (recommended; deterministic fallback exists)

`OPENAI_API_KEY` is kept as an optional compatibility secret and is not required
by the default v7 writer.

## Validation

Offline tests cover compilation, long/short generation, technical gates,
attention scoring, W2E scoring, Market Opportunity ranking, coherent decision
levels, Mistral fact-lock behavior, duplicate stress, copy direction alignment,
cron locking and publisher command construction.

No live Binance publication is performed by the test suite.
