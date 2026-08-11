"""Offline 150-post anti-repetition stress test for the deterministic fallback.

Production prefers Mistral authoring. This test makes sure an API outage still
cannot turn the account into a stream of near-duplicate templates.
"""
from __future__ import annotations

import logging
import os
import statistics
import tempfile
from pathlib import Path
from unittest.mock import patch

from attention import compute_attention, compute_micro_attention
from filters import SignalFilter
from indicators import calculate_multi_timeframe
from main import MAX_POST_SIMILARITY, _best_post_variant
from memory import PostMemory
from monetization import score_market_monetization
from opportunity import score_market_opportunity
from self_test import _build_setup
from trend import TrendingMarket
from writer import _levels


def _context(symbol: str, mtf, frames, score, index: int):
    levels = _levels(mtf.tf_15m, score.direction)
    attention = compute_attention(frames["15m"], mtf.tf_15m, score.direction)
    micro = compute_micro_attention(frames["5m"])
    rank = 4 + (index % 28)
    quote = 120_000_000 + (index % 10) * 70_000_000
    trades = 180_000 + (index % 9) * 85_000
    universe = [
        TrendingMarket("BTCUSDT", 95, 20_000_000_000, 4_000_000, 1.0, 100000, 1),
        TrendingMarket("ETHUSDT", 90, 10_000_000_000, 3_000_000, 1.0, 4000, 2),
        TrendingMarket(symbol, 70, quote, trades, 3.0 + index % 5, mtf.tf_15m.price, rank),
        TrendingMarket("ALTUSDT", 35, 25_000_000, 40_000, 1.0, 1, 40),
    ]
    meta = universe[2]
    opportunity = score_market_opportunity(
        meta=meta, universe=universe, attention=attention, micro=micro,
        technical_score=score.total, risk_reward=float(levels["rr_tp3"]), strict_setup=True,
    )
    monetization = score_market_monetization(
        quote_volume_24h=meta.quote_volume, trade_count_24h=meta.trade_count,
        abs_change_24h=abs(meta.change_pct), trend_rank=meta.rank,
        trend_universe_size=len(universe), attention_score=attention.score,
        change_15m=attention.change_15m, volume_spike=attention.volume_spike,
        risk_reward=float(levels["rr_tp3"]), overextended=attention.overextended,
        micro_freshness=micro.score,
    )
    return levels, attention, micro, opportunity, monetization


def main() -> None:
    logging.getLogger().setLevel(logging.ERROR)
    symbols = ("BTC", "ETH", "SOL", "BNB", "XRP", "DOGE", "ADA", "LINK", "AVAX", "SUI", "TAO", "NEAR")
    similarities = []
    accepted = 0
    skipped = 0

    with tempfile.TemporaryDirectory() as temp_directory:
        memory = PostMemory(Path(temp_directory) / "post_memory.json")
        for index in range(150):
            direction = "long" if index % 2 == 0 else "short"
            basic = symbols[index % len(symbols)]
            symbol = f"{basic}USDT"
            frames = _build_setup(direction)
            mtf = calculate_multi_timeframe(symbol, frames)
            score = SignalFilter(min_score=0).evaluate(mtf)
            assert score is not None
            levels, attention, micro, opportunity, monetization = _context(symbol, mtf, frames, score, index)
            assert levels["plan_valid"]

            with patch.dict(os.environ, {"CONTENT_MODE": "deterministic"}, clear=False):
                selected = _best_post_variant(
                    symbol=symbol, basic=basic, mtf=mtf, score=score,
                    levels=levels, memory=memory, btc=None, attention=attention,
                    micro=micro, opportunity=opportunity, monetization=monetization,
                )
            if selected is None:
                # Correct behaviour during a long AI outage: skip rather than
                # publish a post that breaches the similarity/quality gate.
                skipped += 1
                continue

            draft, _ = selected
            similarity = memory.similarity_score(draft.text)
            assert similarity < MAX_POST_SIMILARITY, (
                f"Accepted post at cycle #{index + 1} similarity {similarity:.3f} reached gate {MAX_POST_SIMILARITY:.3f}"
            )
            if accepted:
                similarities.append(similarity)
            accepted += 1
            memory.add_post(
                symbol, draft.text, post_style=draft.style_id, signal_type=draft.signal_type,
                content_format=draft.content_format, visual_style=draft.visual_style,
                direction=direction, levels=levels, market_price=mtf.tf_15m.price,
            )

    assert accepted >= 18, f"Fallback became unusably narrow: accepted={accepted}, skipped={skipped}"
    assert skipped >= 1, "Static repeated markets should eventually be skipped instead of spammed"
    p95 = statistics.quantiles(similarities, n=20)[18] if len(similarities) >= 20 else max(similarities)
    print(
        "REPETITION STRESS: OK | cycles=150 | "
        f"accepted={accepted} skipped={skipped} | max_similarity={max(similarities):.3f} | "
        f"avg_similarity={statistics.mean(similarities):.3f} | p95={p95:.3f} | gate={MAX_POST_SIMILARITY:.2f}"
    )
    print("No market, Mistral or publishing network call was attempted.")


if __name__ == "__main__":
    main()
