"""Stress the observation-only event fallback against the memory gate."""
from __future__ import annotations

import logging
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

from attention import AttentionSnapshot, MicroAttentionSnapshot
from event_writer import generate_event_candidates, rank_event_candidates
from filters import SignalFilter
from indicators import calculate_multi_timeframe
from memory import PostMemory
from monetization import score_market_monetization
from opportunity import score_audience_event
from self_test import _build_setup
from trend import TrendingMarket


def main() -> None:
    logging.getLogger().setLevel(logging.ERROR)
    frames = _build_setup("long")
    mtf = calculate_multi_timeframe("EVENTUSDT", frames)
    score = SignalFilter(min_score=0, profile="balanced").evaluate(mtf)
    assert score is not None
    attention = AttentionSnapshot(
        score=80, change_15m=1.1, change_45m=2.4, volume_spike=4.2,
        range_expansion=2.0, turnover_1h=12_000_000, distance_atr=1.2,
        label="event", overextended=False,
    )
    micro = MicroAttentionSnapshot(
        score=84, change_5m=0.55, change_15m=1.1, volume_spike_5m=3.9,
        return_impulse=4, volume_impulse=80, acceleration=1.8,
        event_age_bars=0, phase="fresh", stale_penalty=0,
    )
    universe = [
        TrendingMarket("BTCUSDT", 90, 20e9, 4e6, 1, 100000, 1),
        TrendingMarket("EVENTUSDT", 72, 600e6, 650000, 2, mtf.tf_15m.price, 8),
        TrendingMarket("ALTUSDT", 40, 30e6, 50000, 1, 1, 30),
    ]
    meta = universe[1]
    opp = score_audience_event(meta=meta, universe=universe, attention=attention, technical_score=score.total, micro=micro)
    mon = score_market_monetization(
        quote_volume_24h=meta.quote_volume, trade_count_24h=meta.trade_count,
        abs_change_24h=2, trend_rank=8, trend_universe_size=len(universe),
        attention_score=attention.score, change_15m=attention.change_15m,
        volume_spike=attention.volume_spike, risk_reward=0, overextended=False,
        micro_freshness=micro.score, observation_only=True,
    )

    accepted = []
    with tempfile.TemporaryDirectory() as td:
        memory = PostMemory(Path(td) / "memory.json")
        with patch.dict(os.environ, {"CONTENT_MODE": "deterministic"}, clear=False):
            for cycle in range(40):
                basic = f"EV{cycle % 13}"
                drafts = generate_event_candidates(
                    basic=basic, mtf=mtf, direction=score.direction, levels={"plan_valid": False},
                    memory=memory, btc=None, attention=attention, micro=micro,
                    opportunity=opp, monetization=mon, variant_count=16,
                )
                selected = rank_event_candidates(
                    drafts=drafts, basic=basic, memory=memory,
                    min_feed_appeal=74, min_conversion=72, min_quality=80,
                    max_similarity=0.46, plan_available=False,
                )
                if selected is None:
                    continue
                draft, _ = selected
                similarity = memory.similarity_score(draft.text)
                assert similarity < 0.46
                accepted.append((draft.text, similarity))
                memory.add_post(
                    basic + "USDT", draft.text, post_style=draft.style_id,
                    signal_type=draft.signal_type, content_format=draft.content_format,
                    visual_style=draft.visual_style,
                )

    assert accepted, "event fallback never produced publishable text"
    max_sim = max(value for _, value in accepted)
    print(f"EVENT REPETITION: OK | cycles=40 accepted={len(accepted)} max_similarity={max_sim:.3f}")


if __name__ == "__main__":
    main()
