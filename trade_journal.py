"""Persistent journal for published, public trade plans.

Only targets that were explicitly visible in the original Square post text or
published plan media are eligible for automatic "target reached" follow-ups.
This prevents the bot from claiming a level after the fact when readers never saw it.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import logging
import math
import os
from pathlib import Path
import re
from typing import Any, Dict, Iterable, List, Optional

from runtime import atomic_write_json, resolve_state_file

logger = logging.getLogger(__name__)
JOURNAL_FILE = resolve_state_file("TRADE_JOURNAL_FILE", "trade_journal.json")
SCHEMA_VERSION = 1
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
    # Writer sometimes keeps one extra digit around low-priced assets.
    for extra in (1, 2):
        if "." in formatted:
            decimals = len(formatted.split(".", 1)[1]) + extra
            raw = f"{float(value):.{min(decimals, 10)}f}".rstrip("0").rstrip(".")
            variants.add(raw)
            variants.add(raw.replace(".", ","))
    return {v for v in variants if v}


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
        payload.setdefault("schema_version", SCHEMA_VERSION)
        return payload
    except Exception as exc:
        logger.warning("Trade journal load failed: %s", exc)
        return {"schema_version": SCHEMA_VERSION, "updated_at": _now_iso(), "trades": {}}


def save_journal(journal: dict, path: Optional[Path] = None) -> None:
    path = Path(path or JOURNAL_FILE)
    trades = journal.get("trades") if isinstance(journal.get("trades"), dict) else {}
    if len(trades) > MAX_TRADES:
        ranked = sorted(
            trades.items(),
            key=lambda kv: str(kv[1].get("published_at") or ""),
            reverse=True,
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
    additional_public_targets: Optional[Iterable[str]] = None,
) -> Optional[dict]:
    """Persist a published setup if at least one target was explicitly public in text/media."""
    if not bool(levels.get("plan_valid", False)):
        return None
    exposed = explicit_public_targets(text, levels)
    for name in (additional_public_targets or []):
        clean = str(name).lower()
        if clean in {"tp1", "tp2", "tp3"} and clean not in exposed and levels.get(clean) is not None:
            exposed.append(clean)
    exposed.sort(key=lambda name: {"tp1": 1, "tp2": 2, "tp3": 3}.get(name, 9))
    if not exposed:
        logger.info("Outcome journal: %s not tracked because no target price was explicit in the published text/media", market_symbol)
        return None
    direction = str(direction or "").lower()
    if direction not in {"long", "short"}:
        return None

    journal = load_journal()
    trades = journal.setdefault("trades", {})
    timestamp = str(published_at or _now_iso())
    key = str(post_id or f"local-{market_symbol}-{int(datetime.now(timezone.utc).timestamp())}")
    decision_mode = str(levels.get("decision_mode") or "at_level")
    immediate = decision_mode == "at_level" or str(levels.get("trade_state")) == "decision_now"

    def num(name: str, fallback: Optional[float] = None) -> Optional[float]:
        value = levels.get(name, fallback)
        try:
            value = float(value)
            return value if math.isfinite(value) else fallback
        except (TypeError, ValueError):
            return fallback

    trade = {
        "trade_id": key,
        "post_id": str(post_id or ""),
        "symbol": str(symbol or "").upper(),
        "market_symbol": str(market_symbol or "").upper(),
        "direction": direction,
        "lane": str(lane or "").upper(),
        "published_at": timestamp,
        "writer_source": str(writer_source or ""),
        "status": "active" if immediate else "pending_entry",
        "decision_mode": decision_mode,
        "trade_state": str(levels.get("trade_state") or ""),
        "entry": num("plan_entry", num("entry")),
        "entry_zone_low": num("entry_zone_low", num("plan_entry", num("entry"))),
        "entry_zone_high": num("entry_zone_high", num("plan_entry", num("entry"))),
        "stop": num("stop"),
        "tp1": num("tp1"),
        "tp2": num("tp2"),
        "tp3": num("tp3"),
        "rr_tp1": num("rr_tp1", 0.0),
        "rr_tp2": num("rr_tp2", 0.0),
        "rr_tp3": num("rr_tp3", num("public_rr", 0.0)),
        "public_risk_pct": num("public_risk_pct", 0.0),
        "exposed_targets": exposed,
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
    trades[key] = trade
    save_journal(journal)
    logger.info(
        "Outcome journal: tracking %s %s from post %s | public targets=%s | state=%s",
        market_symbol, direction.upper(), post_id or key, ",".join(exposed), trade["status"],
    )
    return trade


def summarize_journal(journal: Optional[dict] = None) -> dict:
    journal = journal or load_journal()
    trades = [row for row in journal.get("trades", {}).values() if isinstance(row, dict)]
    entered = [row for row in trades if row.get("entry_confirmed")]
    active = [row for row in trades if row.get("status") in {"active", "pending_entry"}]
    closed = [row for row in trades if row.get("status") in {"closed", "expired", "manual_review"}]
    tp1 = sum(1 for row in entered if (row.get("hits") or {}).get("tp1"))
    tp3 = sum(1 for row in entered if (row.get("hits") or {}).get("tp3"))
    stops = sum(1 for row in entered if (row.get("hits") or {}).get("stop"))
    completed = sum(1 for row in trades if row.get("close_reason") == "public_targets_complete")
    followups = sum(len(row.get("followups") or []) for row in trades)
    recent = sorted(trades, key=lambda row: str(row.get("published_at") or ""), reverse=True)[:80]
    return {
        "total": len(trades),
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


def _parse_dt(value: str) -> Optional[datetime]:
    try:
        dt = datetime.fromisoformat(str(value))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except (TypeError, ValueError):
        return None


def bootstrap_recent_setups(memory_items: Iterable[dict], lookback_hours: Optional[float] = None) -> int:
    """One-time/idempotent migration of recent v10.x public setups into v11 journal.

    This lets a freshly upgraded bot continue following a very recent setup instead
    of waiting for the next new trade post. A matching bot analytics row is required
    so the original post id/time/media metadata are grounded rather than guessed.
    """
    try:
        from performance_store import load_store
    except Exception:
        return 0
    hours = max(1.0, float(lookback_hours if lookback_hours is not None else os.getenv("OUTCOME_BOOTSTRAP_HOURS", "24")))
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    store = load_store()
    analytics = [row for row in store.get("posts", {}).values() if isinstance(row, dict) and row.get("post_id")]
    journal = load_journal()
    existing = {str(row.get("post_id") or "") for row in journal.get("trades", {}).values() if isinstance(row, dict)}
    added = 0

    def norm_symbol(value: str) -> str:
        v = str(value or "").upper().strip()
        return v[:-4] if v.endswith("USDT") else v

    for item in memory_items:
        if not isinstance(item, dict):
            continue
        ts = _parse_dt(item.get("ts", ""))
        if not ts or ts < cutoff:
            continue
        direction = str(item.get("direction") or "").lower()
        levels = item.get("levels") if isinstance(item.get("levels"), dict) else {}
        if direction not in {"long", "short"} or not all(key in levels for key in ("plan_entry", "stop", "tp1", "tp2", "tp3")):
            continue
        base = norm_symbol(item.get("symbol", ""))
        matches = []
        for row in analytics:
            if str(row.get("post_id") or "") in existing:
                continue
            if norm_symbol(row.get("symbol", "")) != base:
                continue
            pub = _parse_dt(row.get("published_at", ""))
            if not pub or abs((pub - ts).total_seconds()) > 600:
                continue
            if str(row.get("direction") or "").lower() not in {direction, direction.upper().lower()}:
                continue
            matches.append((abs((pub - ts).total_seconds()), row, pub))
        if not matches:
            continue
        _, row, pub = min(matches, key=lambda x: x[0])
        reconstructed = dict(levels)
        reconstructed["plan_valid"] = True
        mode = str((row.get("market") or {}).get("decision_mode") or "at_level")
        reconstructed["decision_mode"] = mode
        reconstructed["trade_state"] = {
            "at_level": "decision_now", "retest_hold": "waiting_retest", "retest_reject": "waiting_retest",
            "breakout_confirm": "waiting_breakout", "breakdown_confirm": "waiting_breakdown",
        }.get(mode, "waiting_confirmation")
        media_targets = []
        if row.get("image_url"):
            media_targets = ["tp1", "tp2", "tp3"] if str(row.get("visual_style")) == "trade_map" else ["tp1"]
        tracked = record_trade_setup(
            post_id=str(row.get("post_id") or ""), symbol=base,
            market_symbol=str(row.get("market_symbol") or item.get("symbol") or f"{base}USDT"),
            direction=direction, lane=str(row.get("lane") or "TRADE"), text=str(row.get("text") or item.get("text") or ""),
            levels=reconstructed, published_at=pub.isoformat(), writer_source=str(row.get("writer_source") or ""),
            additional_public_targets=media_targets,
        )
        if tracked:
            existing.add(str(row.get("post_id") or ""))
            added += 1
    if added:
        logger.info("Outcome journal bootstrap: imported %s recent pre-v11 setup(s)", added)
    return added
