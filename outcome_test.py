"""Offline tests for public-target exposure and conservative outcome state machine."""
from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import tempfile

from outcome_engine import process_trade_candles
from trade_journal import build_setup_id, explicit_public_targets, load_journal, validate_public_plan_text, verify_trade_integrity


def candle(open_ms, o, h, l, c):
    return {"open_ms": open_ms, "close_ms": open_ms + 59_999, "open": o, "high": h, "low": l, "close": c}


def base_trade(direction="long"):
    if direction == "long":
        trade = {
            "tracking_version": 2, "source_post_id": "123", "post_id": "123", "public_plan_complete": True,
            "market_symbol": "TESTUSDT", "direction": "long", "status": "active", "decision_mode": "at_level",
            "entry": 100.0, "entry_zone_low": 99.8, "entry_zone_high": 100.2, "stop": 98.0,
            "tp1": 102.0, "tp2": 104.0, "tp3": 106.0, "rr_tp1": 1.0, "rr_tp2": 2.0, "rr_tp3": 3.0,
            "exposed_targets": ["tp1", "tp2", "tp3"], "entry_confirmed": True,
            "hits": {"tp1": False, "tp2": False, "tp3": False, "stop": False}, "hit_at": {}, "followups": [],
        }
    else:
        trade = {
            "tracking_version": 2, "source_post_id": "456", "post_id": "456", "public_plan_complete": True,
            "market_symbol": "TESTUSDT", "direction": "short", "status": "active", "decision_mode": "at_level",
            "entry": 100.0, "entry_zone_low": 99.8, "entry_zone_high": 100.2, "stop": 102.0,
            "tp1": 98.0, "tp2": 96.0, "tp3": 94.0, "rr_tp1": 1.0, "rr_tp2": 2.0, "rr_tp3": 3.0,
            "exposed_targets": ["tp1", "tp2", "tp3"], "entry_confirmed": True,
            "hits": {"tp1": False, "tp2": False, "tp3": False, "stop": False}, "hit_at": {}, "followups": [],
        }
    levels = {
        "plan_entry": trade["entry"], "entry_zone_low": trade["entry_zone_low"], "entry_zone_high": trade["entry_zone_high"],
        "stop": trade["stop"], "tp1": trade["tp1"], "tp2": trade["tp2"], "tp3": trade["tp3"],
    }
    trade["setup_id"] = build_setup_id(
        source_post_id=trade["source_post_id"], market_symbol=trade["market_symbol"], direction=trade["direction"], levels=levels,
    )
    trade["trade_id"] = trade["setup_id"]
    return trade



def main() -> None:
    levels = {"tp1": 0.1723, "tp2": 0.1788, "tp3": 0.1855}
    text = "$ACE: вход только после подтверждения. Первая цель 0.1723, затем TP2 0.1788. Стоп ниже структуры."
    assert explicit_public_targets(text, levels) == ["tp1", "tp2"]
    assert explicit_public_targets("$ACE: цена сейчас 0.1723, наблюдаю движение.", levels) == []

    full_levels = {
        "plan_entry": 0.1700, "entry_zone_low": 0.1695, "entry_zone_high": 0.1705, "stop": 0.1670,
        "tp1": 0.1723, "tp2": 0.1788, "tp3": 0.1855,
    }
    full_text = "$ACE LONG: вход 0.1695–0.1705, стоп 0.167\nTP1 0.1723 | TP2 0.1788 | TP3 0.1855"
    ok, reasons = validate_public_plan_text(full_text, full_levels, "long")
    assert ok, reasons
    bad, bad_reasons = validate_public_plan_text(full_text.replace(" | TP3 0.1855", ""), full_levels, "long")
    assert not bad and "full TP ladder not public" in bad_reasons

    integrity = base_trade("long")
    assert verify_trade_integrity(integrity)[0]
    tampered = deepcopy(integrity)
    tampered["tp3"] = 107.0
    assert not verify_trade_integrity(tampered)[0]

    # Existing v11 journal rows must be persisted as disabled on first v11.1 load,
    # so cached/backfilled setups can never publish another false outcome.
    with tempfile.TemporaryDirectory() as td:
        legacy_path = Path(td) / "trade_journal.json"
        legacy_path.write_text(json.dumps({
            "schema_version": 1,
            "trades": {"old": {"post_id": "old-post", "status": "active", "pending_followup": {"kind": "target"}}},
        }), encoding="utf-8")
        migrated = load_journal(legacy_path)
        old = migrated["trades"]["old"]
        assert migrated["schema_version"] == 2
        assert old["status"] == "legacy_disabled" and old["pending_followup"] is None
        persisted = json.loads(legacy_path.read_text(encoding="utf-8"))
        assert persisted["trades"]["old"]["status"] == "legacy_disabled"

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

    print("OUTCOME ENGINE: OK | full-plan exposure | source/setup integrity | long/short | partial/final | ambiguity guard")


if __name__ == "__main__":
    main()
