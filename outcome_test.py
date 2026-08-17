"""Offline tests for public-target exposure and conservative outcome state machine."""
from __future__ import annotations

from copy import deepcopy

from outcome_engine import process_trade_candles
from trade_journal import explicit_public_targets


def candle(open_ms, o, h, l, c):
    return {"open_ms": open_ms, "close_ms": open_ms + 59_999, "open": o, "high": h, "low": l, "close": c}


def base_trade(direction="long"):
    if direction == "long":
        return {
            "market_symbol": "TESTUSDT", "direction": "long", "status": "active", "decision_mode": "at_level",
            "entry": 100.0, "entry_zone_low": 99.8, "entry_zone_high": 100.2, "stop": 98.0,
            "tp1": 102.0, "tp2": 104.0, "tp3": 106.0, "rr_tp1": 1.0, "rr_tp2": 2.0, "rr_tp3": 3.0,
            "exposed_targets": ["tp1", "tp2", "tp3"], "entry_confirmed": True,
            "hits": {"tp1": False, "tp2": False, "tp3": False, "stop": False}, "hit_at": {}, "followups": [],
        }
    return {
        "market_symbol": "TESTUSDT", "direction": "short", "status": "active", "decision_mode": "at_level",
        "entry": 100.0, "entry_zone_low": 99.8, "entry_zone_high": 100.2, "stop": 102.0,
        "tp1": 98.0, "tp2": 96.0, "tp3": 94.0, "rr_tp1": 1.0, "rr_tp2": 2.0, "rr_tp3": 3.0,
        "exposed_targets": ["tp1", "tp2", "tp3"], "entry_confirmed": True,
        "hits": {"tp1": False, "tp2": False, "tp3": False, "stop": False}, "hit_at": {}, "followups": [],
    }


def main() -> None:
    levels = {"tp1": 0.1723, "tp2": 0.1788, "tp3": 0.1855}
    text = "$ACE: вход только после подтверждения. Первая цель 0.1723, затем TP2 0.1788. Стоп ниже структуры."
    assert explicit_public_targets(text, levels) == ["tp1", "tp2"]
    assert explicit_public_targets("$ACE: цена сейчас 0.1723, наблюдаю движение.", levels) == []

    t = base_trade("long")
    process_trade_candles(t, [candle(1_000, 100, 102.3, 99.5, 101.8)])
    assert t["hits"]["tp1"] and not t["hits"]["tp2"]
    assert t["pending_followup"]["kind"] == "target"
    assert t["pending_followup"]["target_name"] == "tp1"

    t["followups"] = [{"kind": "target", "target_name": "tp1"}]
    t["pending_followup"] = None
    process_trade_candles(t, [candle(70_000, 102, 104.3, 101.5, 103.8)])
    assert t["hits"]["tp2"] and t.get("pending_followup") is None, "TP2 partial must be suppressed after TP1 follow-up"
    process_trade_candles(t, [candle(140_000, 104, 106.2, 103.5, 106.0)])
    assert t["hits"]["tp3"] and t["status"] == "closed"
    assert t["pending_followup"]["kind"] == "target_complete"

    s = base_trade("short")
    process_trade_candles(s, [candle(1_000, 100, 100.3, 97.8, 98.2)])
    assert s["hits"]["tp1"]

    ambiguous = base_trade("long")
    process_trade_candles(ambiguous, [candle(1_000, 100, 102.2, 97.8, 100.5)])
    assert ambiguous["status"] == "manual_review"
    assert ambiguous["pending_followup"] is None

    pending = base_trade("long")
    pending.update({"status": "pending_entry", "entry_confirmed": False, "decision_mode": "breakout_confirm"})
    process_trade_candles(pending, [candle(1_000, 99.5, 100.4, 99.2, 100.3)])
    assert pending["status"] == "active" and pending["entry_confirmed"]
    assert not pending["hits"]["tp1"], "trigger candle must not be used to claim a target"

    print("OUTCOME ENGINE: OK | public-only target exposure | long/short | partial/final | ambiguity guard")


if __name__ == "__main__":
    main()
