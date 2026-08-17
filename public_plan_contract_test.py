"""v11.1 regression: every plan-valid post must expose Direction/Entry/SL/TP1-3."""
from __future__ import annotations

import logging
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

from attention import AttentionSnapshot, MicroAttentionSnapshot
from event_writer import generate_event_candidates
from filters import SignalFilter
from indicators import calculate_multi_timeframe
from memory import PostMemory
from monetization import score_market_monetization
from opportunity import score_audience_event, score_market_opportunity
from self_test import _build_setup
from trade_journal import validate_public_plan_text
from trend import TrendingMarket
from writer import generate_post_candidates, _levels


def main() -> None:
    logging.getLogger().setLevel(logging.ERROR)
    mtf = calculate_multi_timeframe("BICOUSDT", _build_setup("long"))
    score = SignalFilter(min_score=0).evaluate(mtf)
    assert score is not None
    levels = _levels(mtf.tf_15m, score.direction)
    assert levels["plan_valid"]
    attention = AttentionSnapshot(
        score=88.0, change_15m=2.1, change_45m=3.6, volume_spike=4.5,
        range_expansion=2.0, turnover_1h=8_000_000.0, distance_atr=1.1,
        label="event", overextended=False,
    )
    micro = MicroAttentionSnapshot(
        score=82.0, change_5m=0.9, change_15m=2.1, volume_spike_5m=3.7,
        return_impulse=3.0, volume_impulse=76.0, acceleration=1.5,
        event_age_bars=0, phase="fresh", stale_penalty=0.0,
    )
    universe = [
        TrendingMarket("BTCUSDT", 90, 20_000_000_000, 4_000_000, 1, 100000, 1),
        TrendingMarket("BICOUSDT", 74, 700_000_000, 700_000, 3, mtf.tf_15m.price, 8),
        TrendingMarket("ALTUSDT", 40, 30_000_000, 50_000, 1, 1, 30),
    ]
    meta = universe[1]
    opp_event = score_audience_event(meta=meta, universe=universe, attention=attention, technical_score=score.total, micro=micro)
    opp_trade = score_market_opportunity(
        meta=meta, universe=universe, attention=attention, technical_score=score.total,
        risk_reward=float(levels["public_rr"]), strict_setup=True, micro=micro,
    )
    mon = score_market_monetization(
        quote_volume_24h=meta.quote_volume, trade_count_24h=meta.trade_count,
        abs_change_24h=abs(meta.change_pct), trend_rank=meta.rank, trend_universe_size=len(universe),
        attention_score=attention.score, change_15m=attention.change_15m, volume_spike=attention.volume_spike,
        risk_reward=float(levels["public_rr"]), overextended=False, micro_freshness=micro.score,
    )
    with tempfile.TemporaryDirectory() as tempdir:
        memory = PostMemory(Path(tempdir) / "memory.json")
        with patch.dict(os.environ, {"CONTENT_MODE": "deterministic"}, clear=False):
            trade_posts = generate_post_candidates(
                symbol="BICOUSDT", basic="BICO", mtf=mtf, score=score, memory=memory, levels=levels,
                btc=None, attention=attention, micro=micro, opportunity=opp_trade, monetization=mon, variant_count=12,
            )
            event_posts = generate_event_candidates(
                basic="BICO", mtf=mtf, direction=score.direction, levels=levels, memory=memory,
                btc=None, attention=attention, micro=micro, opportunity=opp_event, monetization=mon, variant_count=12,
            )
    assert trade_posts, "no trade candidates"
    assert event_posts, "no plan-valid event candidates"
    for draft in [*trade_posts, *event_posts]:
        ok, reasons = validate_public_plan_text(draft.text, levels, score.direction)
        assert ok, (draft.source, draft.content_format, reasons, draft.text)
    print(f"PUBLIC PLAN CONTRACT: OK | trade={len(trade_posts)} event={len(event_posts)} | every valid plan exposes Entry/SL/TP1-3")


if __name__ == "__main__":
    main()
