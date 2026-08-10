"""Offline regression tests for Market Attention v8 public trade plans."""
from __future__ import annotations

from types import SimpleNamespace

from trade_plan import build_public_trade_plan
from writer import _fmt_price, _trade_sentences
from content_strategy import headline_candidates


def _indicator(*, price=0.1362, atr=0.0050):
    # Resistance deliberately far away so current price becomes the public
    # decision zone. This reproduces the class of bug seen in the TUT post:
    # current price ~= published level, yet old copy said "wait for retest".
    return SimpleNamespace(
        price=price,
        atr=atr,
        breakout_up=False,
        breakout_down=False,
        support=0.1000,
        resistance=0.2000,
        swing_high=0.1504,
        swing_low=0.1100,
        bb_high=0.1500,
        bb_low=0.1100,
    )


def main() -> None:
    plan = build_public_trade_plan(_indicator(), "long")
    assert plan["plan_valid"], plan
    assert plan["decision_mode"] == "at_level", plan
    assert abs(plan["decision"] - 0.1362) < 1e-12
    assert plan["public_rr"] >= 1.30, plan
    assert plan["public_risk_pct"] <= 9.0, plan

    key = _fmt_price(plan["decision"])
    entry, invalidation = _trade_sentences(
        "long", key, plan, attention=None, variant_index=0, format_id="hot_reaction"
    )
    combined = f"{entry} {invalidation}".lower().replace("ё", "е")
    assert "ретест" not in combined
    assert "после отката" not in combined
    assert "на откате" not in combined
    assert key in combined

    headlines = headline_candidates(
        ticker="$TUT",
        direction="long",
        format_id="hot_reaction",
        key_level=key,
        risk_pct="6,6%",
        reward_pct="10,4%",
        rsi=52.0,
        adx=23.0,
        price_vs_vwap="выше",
        angle_title="уровень",
        change_15m=1.9,
        volume_spike=1.6,
        decision_mode="at_level",
        event_strength="active",
    )
    normalized = "\n".join(headlines).lower().replace("ё", "е")
    assert "сильный ход" not in normalized
    assert "сильная свеч" not in normalized
    assert "резкий" not in normalized
    assert "ретест" not in normalized

    # A wide stop should not be dressed up as a clean public setup.
    wide = build_public_trade_plan(_indicator(atr=0.0100), "long")
    assert not wide["plan_valid"], wide
    assert any("public risk" in reason for reason in wide["plan_reasons"]), wide

    print(
        "TRADE PLAN: OK | at-level language | public RR guard | "
        "risk guard | no fake retest/strength claims"
    )


if __name__ == "__main__":
    main()
