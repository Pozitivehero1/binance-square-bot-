"""Offline regression test for v9 human-first, fact-locked copy."""
from __future__ import annotations

import logging
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

from attention import AttentionSnapshot, MicroAttentionSnapshot
from filters import SignalFilter
from indicators import calculate_multi_timeframe
from main import _best_post_variant
from memory import PostMemory
from monetization import score_market_monetization
from opportunity import score_market_opportunity
from self_test import _build_setup
from trend import TrendingMarket
from writer import _fmt_price, _levels


BANNED = (
    "направление у идеи",
    "граница ошибки",
    "диапазон контроля",
    "стоп является технической границей",
    "параметры сценария",
    "карта исполнения",
    "правило исполнения",
    "что вижу сейчас",
)


def main() -> None:
    logging.getLogger().setLevel(logging.ERROR)
    frames = _build_setup("long")
    mtf = calculate_multi_timeframe("BICOUSDT", frames)
    score = SignalFilter(min_score=0).evaluate(mtf)
    assert score is not None
    levels = _levels(mtf.tf_15m, "long")
    assert levels["plan_valid"], levels

    attention = AttentionSnapshot(
        score=90.0,
        change_15m=7.47,
        change_45m=11.61,
        volume_spike=18.08,
        range_expansion=4.8,
        turnover_1h=4_500_000.0,
        distance_atr=4.2,
        label="резкий всплеск внимания",
        overextended=True,
    )
    micro = MicroAttentionSnapshot(
        score=91.0,
        change_5m=2.1,
        change_15m=7.47,
        volume_spike_5m=8.2,
        return_impulse=6.0,
        volume_impulse=88.0,
        acceleration=2.2,
        event_age_bars=0,
        phase="fresh",
        stale_penalty=0.0,
    )
    universe = [
        TrendingMarket("BTCUSDT", 90, 20_000_000_000, 4_000_000, 1.0, 100000, 1),
        TrendingMarket("ETHUSDT", 86, 10_000_000_000, 3_000_000, 1.5, 4000, 2),
        TrendingMarket("BICOUSDT", 72, 180_000_000, 420_000, 9.0, mtf.tf_15m.price, 12),
        TrendingMarket("ALTUSDT", 40, 25_000_000, 45_000, 2.0, 1, 28),
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

    with tempfile.TemporaryDirectory() as temp_directory:
        memory = PostMemory(Path(temp_directory) / "post_memory.json")
        with patch.dict(os.environ, {"CONTENT_MODE": "deterministic"}, clear=False):
            selected = _best_post_variant(
                symbol="BICOUSDT", basic="BICO", mtf=mtf, score=score,
                levels=levels, memory=memory, btc=None, attention=attention,
                micro=micro, opportunity=opportunity, monetization=monetization,
            )

    assert selected is not None, "Hot BICO-like event produced no publishable post"
    draft, report = selected
    lowered = draft.text.lower().replace("ё", "е")
    assert report.valid, report.reasons
    assert report.score >= 84.0, report.score
    assert 150 <= len(draft.text) <= 560, len(draft.text)
    assert "$BICO" in draft.text
    assert "LONG" in draft.text.upper()
    assert _fmt_price(levels["tp1"]) in draft.text
    assert _fmt_price(levels["stop"]) in draft.text
    assert not any(item in lowered for item in BANNED), draft.text
    assert draft.text.count("?") <= 1

    # The author is allowed to choose which market facts are worth mentioning;
    # it is not allowed to alter the locked trade facts.
    if draft.content_format in {"trade_map", "risk_first"}:
        assert _fmt_price(levels["tp2"]) in draft.text
        assert _fmt_price(levels["tp3"]) in draft.text

    print(
        f"HUMAN COPY: OK | source={draft.source} | format={draft.content_format} | "
        f"chars={len(draft.text)} | quality={report.score:.1f}"
    )
    print("--- sample ---")
    print(draft.text)


if __name__ == "__main__":
    main()
