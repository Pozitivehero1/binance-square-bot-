"""Offline regression tests for the public trade-plan state machine."""
from __future__ import annotations

from types import SimpleNamespace

from trade_plan import build_public_trade_plan
from writer import _fmt_price, _state_instruction


def _indicator(*, price=0.1362, atr=0.0050):
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
    assert plan["rr_tp1"] >= 1.0, plan
    assert plan["rr_tp1"] < plan["rr_tp2"] < plan["rr_tp3"], plan
    assert plan["public_rr"] >= 1.55, plan
    assert plan["public_risk_pct"] <= 8.0, plan
    assert plan["entry_zone_low"] <= plan["plan_entry"] <= plan["entry_zone_high"], plan

    key = _fmt_price(plan["decision"])
    instruction = _state_instruction(plan, "long").lower().replace("ё", "е")
    assert "цена уже у рабочей зоны" in instruction
    assert "будущий ретест" in instruction
    assert key == "0.1362"
    assert plan["trade_state"] == "decision_now"

    # A wide stop should not be dressed up as a clean public setup.
    wide = build_public_trade_plan(_indicator(atr=0.0100), "long")
    assert not wide["plan_valid"], wide
    assert any("public risk" in reason for reason in wide["plan_reasons"]), wide

    print("TRADE PLAN: OK | at-level state | public RR guard | risk guard")


if __name__ == "__main__":
    main()
