# v11.15 — Reach-to-W2E Learning

## Evidence used

The release was tuned from the committed account snapshot, not generic social
media advice:

- 1,200 tracked posts overall; 500 recent posts available for detailed review.
- Last seven days, mature EVENT posts: median 130 views; TRADE: 92.5.
- Best recent EVENT formats: `event_one_price` and `event_market_story`.
- Weak recent TRADE formats by median: `no_chase`, `trade_map`, and
  `market_story`.
- Verified outcome history: TP1 46.8%, TP3 25.1%. Recent `at_level` plans were
  materially healthier than recent retest plans, so decision mode now joins the
  outcome-learning signal.

These observations are correlations from one account. They guide bounded
ranking adjustments and are not promises of future views or W2E revenue.

## Changes

- Added confidence-shrunk reach lift for lane and format selection.
- Moved format learning ahead of the AI call, so the three requested variants
  are selected using performance plus recency rather than recency alone.
- Relaxed the forced 1:1 EVENT/TRADE rotation. Strong EVENT content may win more
  often, while four consecutive EVENT posts give an eligible TRADE a bounded
  W2E-mix preference.
- Extended outcome learning with public decision mode while preserving ticker
  shrinkage and hard caps.
- Made the candidate-attempt and AI-request budgets explicit in `main.py` and
  removed the runtime `range()` monkeypatch from startup.
- Fixed word-boundary corruption in trade-contract similarity filtering.
- Added `engine_version` to every new publication and tracked setup so future
  releases can be compared without mixing data.
- Updated the mobile-length editorial sweet spot to 230–330 characters.

## Production invariants preserved

- GitHub Actions trigger remains every 20 minutes.
- Python still owns price, direction, Entry, SL, TP1, TP2 and TP3.
- Full public plan, fact consistency, language integrity, anti-duplicate,
  live-price and confirmed-publication checks remain hard gates.
- Unconfirmed sends are reconciled instead of blindly retried.
