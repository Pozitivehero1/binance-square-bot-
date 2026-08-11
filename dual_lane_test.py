"""Offline regression for v9.1 TRADE + EVENT dual lane."""
from __future__ import annotations

from dataclasses import replace
import logging
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

from attention import AttentionSnapshot, MicroAttentionSnapshot
from event_writer import generate_event_candidates, rank_event_candidates
from filters import SignalFilter
from indicators import calculate_multi_timeframe
from main import _choose_event_candidate, _event_candidate_gate
from memory import PostMemory
from monetization import score_market_monetization
from opportunity import score_audience_event
from self_test import _build_setup
from trend import TrendingMarket


def main() -> None:
    logging.getLogger().setLevel(logging.ERROR)
    mtf = calculate_multi_timeframe("TSTUSDT", _build_setup("long"))
    score = SignalFilter(min_score=0, profile="balanced").evaluate(mtf)
    assert score is not None
    # Simulate exactly the architecture problem seen in the live log: a coin may
    # fail a technical gate and must still reach audience-event evaluation.
    score = replace(score, passed_gates=False, gate_reasons=("ADX below trade gate",))

    attention = AttentionSnapshot(
        score=82.0, change_15m=-1.30, change_45m=-2.10, volume_spike=3.8,
        range_expansion=2.4, turnover_1h=18_000_000.0, distance_atr=1.4,
        label="fresh event", overextended=False,
    )
    micro = MicroAttentionSnapshot(
        score=86.0, change_5m=-0.72, change_15m=-1.30, volume_spike_5m=4.6,
        return_impulse=4.0, volume_impulse=82.0, acceleration=2.0,
        event_age_bars=0, phase="fresh", stale_penalty=0.0,
    )
    universe = [
        TrendingMarket("BTCUSDT", 90, 20_000_000_000, 4_000_000, 1.0, 100000, 1),
        TrendingMarket("ETHUSDT", 86, 10_000_000_000, 3_000_000, 1.5, 4000, 2),
        TrendingMarket("TSTUSDT", 75, 850_000_000, 900_000, -3.0, mtf.tf_15m.price, 7),
        TrendingMarket("LOWUSDT", 40, 25_000_000, 45_000, 1.0, 1, 35),
    ]
    meta = universe[2]
    opportunity = score_audience_event(
        meta=meta, universe=universe, attention=attention,
        technical_score=score.total, micro=micro,
    )
    monetization = score_market_monetization(
        quote_volume_24h=meta.quote_volume, trade_count_24h=meta.trade_count,
        abs_change_24h=abs(meta.change_pct), trend_rank=meta.rank,
        trend_universe_size=len(universe), attention_score=attention.score,
        change_15m=attention.change_15m, volume_spike=attention.volume_spike,
        risk_reward=0.0, overextended=False, micro_freshness=micro.score,
        observation_only=True,
    )
    allowed, mode = _event_candidate_gate(score, attention, micro, monetization, opportunity)
    assert allowed, (mode, opportunity, monetization)
    assert not score.passed_gates

    # The actual selector must also keep the candidate even though its technical
    # gates are marked failed. Patch only the market snapshots so this stays a
    # deterministic offline test of orchestration rather than candle math.
    frames = _build_setup("long")
    with tempfile.TemporaryDirectory() as selector_temp:
        selector_memory = PostMemory(Path(selector_temp) / "selector_memory.json")
        with patch("main.compute_event_attention", return_value=attention), \
             patch("main.compute_micro_attention", return_value=micro), \
             patch("main._levels", return_value={"plan_valid": False}):
            selected_event = _choose_event_candidate(
                [mtf], {"TSTUSDT": score}, None, selector_memory,
                {"TSTUSDT": {"5m": frames["5m"], "15m": frames["15m"]}},
                {item.symbol: item for item in universe}, universe,
            )
    assert selected_event is not None, "main event selector dropped a technically rejected fresh event"
    assert selected_event[0].symbol == "TSTUSDT"
    assert selected_event[6].get("plan_valid") is False

    # No clean public plan: event copy must stay observation-only and must not
    # invent LONG/SHORT, entry, SL or TP levels.
    levels = {"plan_valid": False}
    with tempfile.TemporaryDirectory() as temp_directory:
        memory = PostMemory(Path(temp_directory) / "post_memory.json")
        with patch.dict(os.environ, {"CONTENT_MODE": "deterministic"}, clear=False):
            drafts = generate_event_candidates(
                basic="TST", mtf=mtf, direction=score.direction, levels=levels,
                memory=memory, btc=None, attention=attention, micro=micro,
                opportunity=opportunity, monetization=monetization, variant_count=12,
            )
        assert drafts, "event lane produced no observation-only drafts"
        selected = rank_event_candidates(
            drafts=drafts, basic="TST", memory=memory,
            min_feed_appeal=74, min_conversion=72, min_quality=80,
            max_similarity=0.46, plan_available=False,
        )

    assert selected is not None
    draft, report = selected
    lowered = draft.text.lower().replace("ё", "е")
    assert report.valid
    assert "$TST" in draft.text
    assert not any(token in lowered for token in (" long", "лонг", " short", "шорт", "tp1", "tp2", "tp3", "стоп")), draft.text
    assert draft.content_format.startswith("event_")

    # High-demand but stale/quiet ticker should still be rejected.
    stale_attention = replace(attention, score=34.0, change_15m=0.12, change_45m=0.30, volume_spike=0.6)
    stale_micro = replace(micro, score=24.0, change_5m=0.02, volume_spike_5m=0.5, phase="stale", stale_penalty=20.0)
    stale_opp = score_audience_event(
        meta=universe[0], universe=universe, attention=stale_attention,
        technical_score=70, micro=stale_micro,
    )
    stale_mon = score_market_monetization(
        quote_volume_24h=universe[0].quote_volume, trade_count_24h=universe[0].trade_count,
        abs_change_24h=1.0, trend_rank=1, trend_universe_size=len(universe),
        attention_score=stale_attention.score, change_15m=stale_attention.change_15m,
        volume_spike=stale_attention.volume_spike, risk_reward=0.0,
        overextended=False, micro_freshness=stale_micro.score, observation_only=True,
    )
    stale_allowed, _ = _event_candidate_gate(score, stale_attention, stale_micro, stale_mon, stale_opp)
    assert not stale_allowed, stale_opp

    print(
        "DUAL LANE: OK | technical gate bypassed for fresh event | "
        f"event={opportunity.score:.1f} w2e={monetization.score:.1f} | "
        f"copy={draft.content_format}/{draft.source}"
    )
    print("--- event sample ---")
    print(draft.text)


if __name__ == "__main__":
    main()
