"""Fact-lock tests for the v9.1 event author semantic package."""
from __future__ import annotations

import logging

from attention import AttentionSnapshot, MicroAttentionSnapshot
from event_writer import _semantic_package, _validate_event_post
from filters import SignalFilter
from indicators import calculate_multi_timeframe
from monetization import score_market_monetization
from opportunity import score_audience_event
from self_test import _build_setup
from trend import TrendingMarket
from writer import _fmt_price, _levels


def main() -> None:
    logging.getLogger().setLevel(logging.ERROR)
    mtf = calculate_multi_timeframe("BICOUSDT", _build_setup("long"))
    score = SignalFilter(min_score=0).evaluate(mtf)
    assert score is not None
    levels = _levels(mtf.tf_15m, score.direction)
    assert levels["plan_valid"]

    attention = AttentionSnapshot(
        score=84.0, change_15m=1.8, change_45m=3.2, volume_spike=5.4,
        range_expansion=2.2, turnover_1h=9_000_000.0, distance_atr=1.2,
        label="event", overextended=False,
    )
    micro = MicroAttentionSnapshot(
        score=82.0, change_5m=0.8, change_15m=1.8, volume_spike_5m=4.2,
        return_impulse=3.0, volume_impulse=78.0, acceleration=1.8,
        event_age_bars=0, phase="fresh", stale_penalty=0.0,
    )
    universe = [
        TrendingMarket("BTCUSDT", 90, 20_000_000_000, 4_000_000, 1, 100000, 1),
        TrendingMarket("BICOUSDT", 74, 700_000_000, 700_000, 3, mtf.tf_15m.price, 8),
        TrendingMarket("ALTUSDT", 40, 30_000_000, 50_000, 1, 1, 30),
    ]
    meta = universe[1]
    opp = score_audience_event(
        meta=meta, universe=universe, attention=attention,
        technical_score=score.total, micro=micro,
    )
    mon = score_market_monetization(
        quote_volume_24h=meta.quote_volume, trade_count_24h=meta.trade_count,
        abs_change_24h=abs(meta.change_pct), trend_rank=meta.rank,
        trend_universe_size=len(universe), attention_score=attention.score,
        change_15m=attention.change_15m, volume_spike=attention.volume_spike,
        risk_reward=float(levels["public_rr"]), overextended=False,
        micro_freshness=micro.score,
    )
    package = _semantic_package(
        basic="BICO", mtf=mtf, direction=score.direction, levels=levels,
        btc=None, attention=attention, micro=micro, opportunity=opp, monetization=mon,
    )
    plan = package["optional_trade_plan"]
    assert plan["available"] is True
    for key in ("entry", "entry_zone", "stop_loss", "tp1", "tp2", "tp3", "rr_tp1", "rr_tp2", "rr_tp3"):
        assert key in plan, key

    # A human event post is allowed to use the full Python-owned plan.
    entry = _fmt_price(levels["plan_entry"])
    tp1 = _fmt_price(levels["tp1"])
    tp2 = _fmt_price(levels["tp2"])
    tp3 = _fmt_price(levels["tp3"])
    stop = _fmt_price(levels["stop"])
    text = (
        f"$BICO стал заметно активнее — но сама свеча для меня ещё не причина входить\n\n"
        f"Если рынок даст нормальное исполнение, мой LONG-план уже готов: вход около {entry}, стоп {stop}.\n"
        f"TP1 {tp1} | TP2 {tp2} | TP3 {tp3}.\n\n"
        "До этого момента я просто смотрю, сохраняется ли свежая активность, а не догоняю движение."
    )
    valid, reasons = _validate_event_post(
        text, basic="BICO", direction=score.direction, package=package,
    )
    assert valid, reasons

    partial = text.replace(f" | TP2 {tp2} | TP3 {tp3}", "")
    partial_ok, partial_reasons = _validate_event_post(
        partial, basic="BICO", direction=score.direction, package=package,
    )
    assert not partial_ok and "missing TP2" in partial_reasons and "missing TP3" in partial_reasons

    fabricated = text.replace("свежая активность", "свежая активность x99")
    valid_bad, reasons_bad = _validate_event_post(
        fabricated, basic="BICO", direction=score.direction, package=package,
    )
    assert not valid_bad and any("unexpected numbers" in reason for reason in reasons_bad), reasons_bad

    # Observation-only mode must not manufacture the same trade call.
    no_plan_package = _semantic_package(
        basic="BICO", mtf=mtf, direction=score.direction, levels={"plan_valid": False},
        btc=None, attention=attention, micro=micro, opportunity=opp, monetization=mon,
    )
    invalid_trade, invalid_reasons = _validate_event_post(
        text, basic="BICO", direction=score.direction, package=no_plan_package,
    )
    assert not invalid_trade
    assert any("direction forbidden" in reason or "trade targets forbidden" in reason for reason in invalid_reasons)

    print("EVENT AUTHOR: OK | full plan mandatory | partial plan blocked | observation-only trade invention blocked | fabricated x99 blocked")


if __name__ == "__main__":
    main()
