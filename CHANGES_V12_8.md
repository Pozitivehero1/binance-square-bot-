# v12.8 — Measured Market Context

The Oct 21 feed still repeated “volume rose, price barely moved, the snapshot
cannot explain why”. Keyword-based explanations received positive copy scores,
and different 5m/15m windows were incorrectly narrated as successive events.
The preceding release improved factual checks without resolving this weakness.

* Give TRADE/EVENT authors measured one-hour returns, the preceding 15m return,
  the previous hour's high/low excluding the current candle, and volume relative
  to the immediately preceding same-period candle. Require consecutive history;
  missing history and zero-volume denominators never produce invented research.
* Preserve exchange-reported quote turnover through the data loader. Use it
  instead of approximating turnover by closing price times base volume when it
  is available. Executed turnover does not establish order-book liquidity.
* Prefer actual price displacement over volume-only noise; apply stronger soft
  repetition and empty-disclaimer penalties. Existing eligible candidates remain
  available, without another quality threshold or publication quota.
* Bind hourly and preceding-period returns to their own values. Reject treating
  concurrent windows as a sequence and unsupported claims of low liquidity.
* Remove prompt/source limitations from public news. Missing RSS details do not
  prove that a company or regulator withheld information.
* Start reader experiment v6, so the changed research treatment is not pooled
  with v5. Retain the same two arms and observed age windows.

The publishing workflow, cron, daily limits and ticker/news/outcome cooldowns
are unchanged. Account profile metadata is unchanged. Views and account reach
are platform outcomes, not guaranteed consequences of these repairs.

Regression coverage includes the actual Oct 21 wording errors, past/current
window separation, prior ranges without lookahead, missing history, true quote
turnover, research availability to authors and unchanged pacing.
