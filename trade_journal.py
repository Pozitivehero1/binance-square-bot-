"""Strict persistent journal for v11.1 published trade plans.

Safety contract:
- only a plan that was actually published with direction + entry + SL + TP1/2/3 is tracked;
- every tracked setup is bound to the exact Binance Square source_post_id;
- pre-v11.1 journal rows are quarantined and can never generate automatic outcomes.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import logging
import math
import os
from pathlib import Path
import re
from typing import Any, Dict, List, Optional, Tuple

from runtime import atomic_write_json, resolve_state_file

logger = logging.getLogger(__name__)
JOURNAL_FILE = resolve_state_file("TRADE_JOURNAL_FILE", "trade_journal.json")
SCHEMA_VERSION = 2
TRACKING_VERSION = 2
MAX_TRADES = max(100, int(os.getenv("OUTCOME_MAX_JOURNAL_TRADES", "600")))


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _fmt_price(value: float) -> str:
    price = float(value)
    absolute = abs(price)
    if absolute >= 1000:
        decimals = 1
    elif absolute >= 100:
        decimals = 1
    elif absolute >= 10:
        decimals = 2
    elif absolute >= 1:
        decimals = 3
    elif absolute >= 0.1:
        decimals = 4
    elif absolute >= 0.01:
        decimals = 5
    elif absolute >= 0.001:
        decimals = 6
    else:
        decimals = 8
    return f"{price:.{decimals}f}".rstrip("0").rstrip(".")


def _price_variants(value: float) -> set[str]:
    formatted = _fmt_price(value)
    variants = {formatted, formatted.replace(".", ",")}
    for extra in (1, 2):
        if "." in formatted:
            decimals = len(formatted.split(".", 1)[1]) + extra
            raw = f"{float(value):.{min(decimals, 10)}f}".rstrip("0").rstrip(".")
            variants.add(raw)
            variants.add(raw.replace(".", ","))
    return {v for v in variants if v}


def _contains_price(text: str, value: float) -> bool:
    raw = str(text or "")
    return any(re.search(rf"(?<![\d]){re.escape(v)}(?![\d])", raw) for v in _price_variants(value))


def explicit_public_targets(text: str, levels: Dict[str, Any]) -> List[str]:
    """Return TP names whose prices are explicitly presented as targets in text."""
    raw = str(text or "")
    if not raw.strip():
        return []
    lines = [line.strip() for line in raw.splitlines() if line.strip()]
    cue = re.compile(r"\b(?:tp\s*[123]?|цель|цели|таргет|target|тейк|фиксац)\w*", re.IGNORECASE)
    exposed: List[str] = []
    for name in ("tp1", "tp2", "tp3"):
        value = levels.get(name)
        try:
            value = float(value)
        except (TypeError, ValueError):
            continue
        if not math.isfinite(value):
            continue
        variants = _price_variants(value)
        for index, line in enumerate(lines):
            if not any(re.search(rf"(?<![\d]){re.escape(v)}(?![\d])", line) for v in variants):
                continue
            context = line
            if index > 0:
                context = lines[index - 1] + " " + context
            if cue.search(context):
                exposed.append(name)
                break
    return exposed


def validate_public_plan_text(text: str, levels: Dict[str, Any], direction: str) -> Tuple[bool, Tuple[str, ...]]:
    """Verify the exact published text exposes the complete Python-owned plan."""
    reasons: List[str] = []
    raw = str(text or "").strip()
    lowered = raw.lower().replace("ё", "е")
    direction = str(direction or "").lower()
    if direction not in {"long", "short"}:
        reasons.append("invalid direction")
        return False, tuple(reasons)

    expected = ("long", "лонг") if direction == "long" else ("short", "шорт")
    opposite = ("short", "шорт") if direction == "long" else ("long", "лонг")
    if not any(re.search(rf"\b{term}\b", lowered) for term in expected):
        reasons.append("direction not public")
    if any(re.search(rf"\b{term}\b", lowered) for term in opposite):
        reasons.append("opposite direction present")

    try:
        entry = float(levels.get("plan_entry", levels.get("entry")))
        zone_low = float(levels.get("entry_zone_low", entry))
        zone_high = float(levels.get("entry_zone_high", entry))
        stop = float(levels["stop"])
        target_values = {name: float(levels[name]) for name in ("tp1", "tp2", "tp3")}
    except (TypeError, ValueError, KeyError):
        return False, tuple([*reasons, "missing numeric plan fields"])

    if not all(math.isfinite(v) for v in (entry, zone_low, zone_high, stop, *target_values.values())):
        reasons.append("non-finite plan field")
    entry_public = _contains_price(raw, entry) or (_contains_price(raw, zone_low) and _contains_price(raw, zone_high))
    if not entry_public:
        reasons.append("entry not public")
    if not _contains_price(raw, stop):
        reasons.append("stop not public")
    if not re.search(r"(?:\bстоп\b|\bstop(?:-loss)?\b|\bsl\b|отмен\w*|закрываю|закрыт)", lowered, re.IGNORECASE):
        reasons.append("stop rule not public")
    targets = explicit_public_targets(raw, target_values)
    if targets != ["tp1", "tp2", "tp3"]:
        reasons.append("full TP ladder not public")
    return not reasons, tuple(reasons)


def _num(levels: Dict[str, Any], name: str, fallback: Optional[float] = None) -> Optional[float]:
    value = levels.get(name, fallback)
    try:
        value = float(value)
        return value if math.isfinite(value) else fallback
    except (TypeError, ValueError):
        return fallback


def _setup_material(*, source_post_id: str, market_symbol: str, direction: str, levels: Dict[str, Any]) -> str:
    values = [
        str(source_post_id), str(market_symbol).upper(), str(direction).lower(),
        repr(_num(levels, "plan_entry", _num(levels, "entry"))),
        repr(_num(levels, "entry_zone_low", _num(levels, "plan_entry", _num(levels, "entry")))),
        repr(_num(levels, "entry_zone_high", _num(levels, "plan_entry", _num(levels, "entry")))),
        repr(_num(levels, "stop")), repr(_num(levels, "tp1")), repr(_num(levels, "tp2")), repr(_num(levels, "tp3")),
    ]
    return "|".join(values)


def build_setup_id(*, source_post_id: str, market_symbol: str, direction: str, levels: Dict[str, Any]) -> str:
    material = _setup_material(
        source_post_id=source_post_id, market_symbol=market_symbol, direction=direction, levels=levels,
    )
    return "setup_" + hashlib.sha256(material.encode("utf-8")).hexdigest()[:20]


def _trade_as_levels(trade: dict) -> Dict[str, Any]:
    return {
        "plan_entry": trade.get("entry"),
        "entry": trade.get("entry"),
        "entry_zone_low": trade.get("entry_zone_low"),
        "entry_zone_high": trade.get("entry_zone_high"),
        "stop": trade.get("stop"),
        "tp1": trade.get("tp1"),
        "tp2": trade.get("tp2"),
        "tp3": trade.get("tp3"),
    }


def verify_trade_integrity(trade: dict) -> Tuple[bool, str]:
    """Cryptographically bind outcome tracking to a source post and exact plan snapshot."""
    if int(trade.get("tracking_version") or 0) != TRACKING_VERSION:
        return False, "legacy tracking version"
    source_post_id = str(trade.get("source_post_id") or trade.get("post_id") or "").strip()
    if not source_post_id:
        return False, "missing source_post_id"
    if trade.get("exposed_targets") != ["tp1", "tp2", "tp3"]:
        return False, "incomplete public target ladder"
    expected = build_setup_id(
        source_post_id=source_post_id,
        market_symbol=str(trade.get("market_symbol") or ""),
        direction=str(trade.get("direction") or ""),
        levels=_trade_as_levels(trade),
    )
    if str(trade.get("setup_id") or trade.get("trade_id") or "") != expected:
        return False, "setup fingerprint mismatch"
    if not bool(trade.get("public_plan_complete")):
        return False, "public plan completeness flag missing"
    return True, "ok"


def _quarantine_legacy(payload: dict, path: Path) -> dict:
    version = int(payload.get("schema_version") or 1)
    if version >= SCHEMA_VERSION:
        return payload
    trades = payload.get("trades") if isinstance(payload.get("trades"), dict) else {}
    count = 0
    for trade in trades.values():
        if not isinstance(trade, dict):
            continue
        trade["tracking_version"] = int(trade.get("tracking_version") or 1)
        trade["status"] = "legacy_disabled"
        trade["pending_followup"] = None
        trade["close_reason"] = "v11_1_legacy_quarantine"
        trade["closed_at"] = trade.get("closed_at") or _now_iso()
        count += 1
    payload["schema_version"] = SCHEMA_VERSION
    payload["updated_at"] = _now_iso()
    try:
        atomic_write_json(path, payload)
    except Exception as exc:
        logger.warning("Could not persist legacy outcome quarantine: %s", exc)
    if count:
        logger.warning(
            "Outcome journal migration: quarantined %s pre-v11.1 setup(s); only newly published full-plan posts can be tracked",
            count,
        )
    return payload


def load_journal(path: Optional[Path] = None) -> dict:
    path = Path(path or JOURNAL_FILE)
    if not path.exists():
        return {"schema_version": SCHEMA_VERSION, "updated_at": _now_iso(), "trades": {}}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("journal root is not an object")
        if not isinstance(payload.get("trades"), dict):
            payload["trades"] = {}
        return _quarantine_legacy(payload, path)
    except Exception as exc:
        logger.warning("Trade journal load failed: %s", exc)
        return {"schema_version": SCHEMA_VERSION, "updated_at": _now_iso(), "trades": {}}


def save_journal(journal: dict, path: Optional[Path] = None) -> None:
    path = Path(path or JOURNAL_FILE)
    trades = journal.get("trades") if isinstance(journal.get("trades"), dict) else {}
    if len(trades) > MAX_TRADES:
        ranked = sorted(
            trades.items(), key=lambda kv: str(kv[1].get("published_at") or ""), reverse=True,
        )[:MAX_TRADES]
        journal["trades"] = dict(ranked)
    journal["schema_version"] = SCHEMA_VERSION
    journal["updated_at"] = _now_iso()
    atomic_write_json(path, journal)


def record_trade_setup(
    *,
    post_id: str,
    symbol: str,
    market_symbol: str,
    direction: str,
    lane: str,
    text: str,
    levels: Dict[str, Any],
    published_at: Optional[str] = None,
    writer_source: str = "",
    additional_public_targets: Optional[Iterable[str]] = None,  # ignored, kept for API compatibility
) -> Optional[dict]:
    """Persist one exact published setup. Media can never substitute for missing text levels."""
    del additional_public_targets
    source_post_id = str(post_id or "").strip()
    if not source_post_id:
        logger.warning("Outcome journal refused %s: missing published post_id", market_symbol)
        return None
    if not bool(levels.get("plan_valid", False)):
        return None
    direction = str(direction or "").lower()
    if direction not in {"long", "short"}:
        return None
    complete, reasons = validate_public_plan_text(text, levels, direction)
    if not complete:
        logger.warning(
            "Outcome journal refused %s post=%s: published plan incomplete (%s)",
            market_symbol, source_post_id, "; ".join(reasons),
        )
        return None

    journal = load_journal()
    trades = journal.setdefault("trades", {})
    for existing in trades.values():
        if isinstance(existing, dict) and str(existing.get("source_post_id") or existing.get("post_id") or "") == source_post_id:
            ok, _ = verify_trade_integrity(existing)
            if ok:
                return existing

    timestamp = str(published_at or _now_iso())
    setup_id = build_setup_id(
        source_post_id=source_post_id, market_symbol=market_symbol, direction=direction, levels=levels,
    )
    public_decision_mode = str(levels.get("decision_mode") or "at_level")
    require_near_confirmation = os.getenv("REQUIRE_NEAR_LEVEL_CONFIRMATION", "1").strip().lower() in {
        "1", "true", "yes", "on"
    }
    # Keep the published semantics unchanged (the writer may correctly say price
    # is already at the zone), but track a real entry only after a closed candle
    # confirms through the outer edge of that zone. Outcome Engine already knows
    # breakout_confirm / breakdown_confirm, so this is conservative and backward-compatible.
    tracking_decision_mode = public_decision_mode
    if require_near_confirmation and public_decision_mode == "at_level":
        tracking_decision_mode = "breakout_confirm" if direction == "long" else "breakdown_confirm"
    immediate = public_decision_mode == "at_level" and not require_near_confirmation
    entry = _num(levels, "plan_entry", _num(levels, "entry"))

    trade = {
        "tracking_version": TRACKING_VERSION,
        "setup_id": setup_id,
        "trade_id": setup_id,
        "source_post_id": source_post_id,
        "post_id": source_post_id,  # dashboard/backward-compatible alias
        "source_text_hash": hashlib.sha256(str(text).strip().encode("utf-8")).hexdigest(),
        "public_plan_complete": True,
        "symbol": str(symbol or "").upper(),
        "market_symbol": str(market_symbol or "").upper(),
        "direction": direction,
        "lane": str(lane or "").upper(),
        "published_at": timestamp,
        "writer_source": str(writer_source or ""),
        "status": "active" if immediate else "pending_entry",
        "decision_mode": tracking_decision_mode,
        "public_decision_mode": public_decision_mode,
        "trade_state": str(levels.get("trade_state") or ""),
        "entry": entry,
        "entry_zone_low": _num(levels, "entry_zone_low", entry),
        "entry_zone_high": _num(levels, "entry_zone_high", entry),
        "stop": _num(levels, "stop"),
        "tp1": _num(levels, "tp1"),
        "tp2": _num(levels, "tp2"),
        "tp3": _num(levels, "tp3"),
        "rr_tp1": _num(levels, "rr_tp1", 0.0),
        "rr_tp2": _num(levels, "rr_tp2", 0.0),
        "rr_tp3": _num(levels, "rr_tp3", _num(levels, "public_rr", 0.0)),
        "public_risk_pct": _num(levels, "public_risk_pct", 0.0),
        "exposed_targets": ["tp1", "tp2", "tp3"],
        "entry_confirmed": bool(immediate),
        "entry_confirmed_at": timestamp if immediate else "",
        "last_checked_at": timestamp,
        "hits": {"tp1": False, "tp2": False, "tp3": False, "stop": False},
        "hit_at": {},
        "pending_followup": None,
        "followups": [],
        "close_reason": "",
        "closed_at": "",
    }
    integrity, reason = verify_trade_integrity(trade)
    if not integrity:
        logger.error("Outcome journal internal integrity failure for %s: %s", market_symbol, reason)
        return None
    trades[setup_id] = trade
    save_journal(journal)
    logger.info(
        "Outcome journal: tracking setup=%s source_post_id=%s %s %s | full public plan TP1/TP2/TP3 | state=%s",
        setup_id, source_post_id, market_symbol, direction.upper(), trade["status"],
    )
    return trade


def summarize_journal(journal: Optional[dict] = None) -> dict:
    journal = journal or load_journal()
    trades = [row for row in journal.get("trades", {}).values() if isinstance(row, dict)]
    eligible = [row for row in trades if int(row.get("tracking_version") or 0) == TRACKING_VERSION]
    entered = [row for row in eligible if row.get("entry_confirmed")]
    active = [row for row in eligible if row.get("status") in {"active", "pending_entry"}]
    closed = [row for row in eligible if row.get("status") in {"closed", "expired", "manual_review"}]
    tp1 = sum(1 for row in entered if (row.get("hits") or {}).get("tp1"))
    tp3 = sum(1 for row in entered if (row.get("hits") or {}).get("tp3"))
    stops = sum(1 for row in entered if (row.get("hits") or {}).get("stop"))
    completed = sum(1 for row in eligible if row.get("close_reason") == "public_targets_complete")
    followups = sum(len(row.get("followups") or []) for row in eligible)
    recent = sorted(eligible, key=lambda row: str(row.get("published_at") or ""), reverse=True)[:80]
    return {
        "total": len(eligible),
        "quarantined": max(0, len(trades) - len(eligible)),
        "entered": len(entered),
        "active": len(active),
        "closed": len(closed),
        "tp1_hits": tp1,
        "tp3_hits": tp3,
        "stops": stops,
        "target_complete": completed,
        "tp1_rate": round(tp1 / len(entered) * 100.0, 1) if entered else 0.0,
        "tp3_rate": round(tp3 / len(entered) * 100.0, 1) if entered else 0.0,
        "followups": followups,
        "recent": recent,
    }
