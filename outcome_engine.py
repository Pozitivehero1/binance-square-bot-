"""Outcome Engine: verify public trade targets and publish factual follow-ups.

The engine uses closed 1-minute Binance candles and is deliberately conservative:
if a single candle touches both an unhit target and the stop, ordering is ambiguous
and no success/failure claim is published automatically.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import logging
import math
import os
from pathlib import Path
import time
from typing import Dict, Iterable, List, Optional

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from memory import PostMemory
from outcome_card import generate_outcome_card
from outcome_writer import build_outcome_post
from performance_store import record_publication
from publication_guard import PublicationGuard
from publisher import publish
from trade_journal import load_journal, save_journal

logger = logging.getLogger(__name__)
ENABLED = os.getenv("ENABLE_OUTCOME_ENGINE", "1").strip().lower() in {"1", "true", "yes", "on"}
POST_STOPS = os.getenv("OUTCOME_POST_STOPS", "1").strip().lower() in {"1", "true", "yes", "on"}
PENDING_HOURS = max(2.0, float(os.getenv("OUTCOME_PENDING_ENTRY_HOURS", "36")))
MAX_AGE_HOURS = max(PENDING_HOURS, float(os.getenv("OUTCOME_MAX_AGE_HOURS", "96")))
MIN_FOLLOWUP_GAP_MIN = max(20.0, float(os.getenv("OUTCOME_MIN_FOLLOWUP_GAP_MIN", "45")))
MAX_FOLLOWUPS = max(1, min(3, int(os.getenv("OUTCOME_MAX_FOLLOWUPS_PER_TRADE", "2"))))
MAX_FETCH_PAGES = max(1, min(10, int(os.getenv("OUTCOME_MAX_KLINE_PAGES", "7"))))


def _session() -> requests.Session:
    retry = Retry(
        total=3, connect=3, read=3, status=3, backoff_factor=0.5,
        status_forcelist=(429, 500, 502, 503, 504), allowed_methods=frozenset({"GET"}),
        respect_retry_after_header=True, raise_on_status=False,
    )
    s = requests.Session()
    s.headers.update({"User-Agent": "BinanceSquareOutcomeEngine/1.0"})
    s.mount("https://", HTTPAdapter(max_retries=retry, pool_connections=6, pool_maxsize=6))
    return s


_SESSION = _session()
_BASES = ("https://data-api.binance.vision", "https://api.binance.com")


def _parse_dt(value: str) -> Optional[datetime]:
    try:
        dt = datetime.fromisoformat(str(value))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except (TypeError, ValueError):
        return None


def _iso_ms(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000.0, tz=timezone.utc).isoformat()


def _fetch_1m(symbol: str, start: datetime, end: Optional[datetime] = None) -> List[dict]:
    """Fetch all closed 1m candles in the requested window, paginated."""
    end = end or datetime.now(timezone.utc)
    start_ms = int(start.timestamp() * 1000)
    end_ms = int(end.timestamp() * 1000)
    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    rows: List[dict] = []
    pages = 0
    cursor = start_ms
    while cursor < end_ms and pages < MAX_FETCH_PAGES:
        response = None
        last_error: Optional[Exception] = None
        for base in _BASES:
            try:
                candidate = _SESSION.get(
                    f"{base}/api/v3/klines",
                    params={"symbol": symbol.upper(), "interval": "1m", "startTime": cursor, "endTime": end_ms, "limit": 1000},
                    timeout=(5, 18),
                )
                candidate.raise_for_status()
                response = candidate
                break
            except requests.RequestException as exc:
                last_error = exc
        if response is None:
            raise RuntimeError(f"Outcome kline endpoints failed for {symbol}: {last_error}")
        payload = response.json()
        if not isinstance(payload, list) or not payload:
            break
        for row in payload:
            try:
                close_ms = int(row[6])
                if close_ms >= now_ms:
                    continue
                rows.append({
                    "open_ms": int(row[0]), "close_ms": close_ms,
                    "open": float(row[1]), "high": float(row[2]), "low": float(row[3]), "close": float(row[4]),
                })
            except (IndexError, TypeError, ValueError):
                continue
        last_close = int(payload[-1][6])
        next_cursor = last_close + 1
        if next_cursor <= cursor:
            break
        cursor = next_cursor
        pages += 1
        if len(payload) < 1000:
            break
    rows.sort(key=lambda row: row["open_ms"])
    return rows


def _entry_triggered(trade: dict, candle: dict) -> bool:
    direction = trade["direction"]
    mode = str(trade.get("decision_mode") or "at_level")
    entry = float(trade["entry"])
    low = float(trade.get("entry_zone_low") or entry)
    high = float(trade.get("entry_zone_high") or entry)
    if mode == "at_level":
        return True
    if mode == "breakout_confirm":
        return direction == "long" and candle["close"] >= high
    if mode == "breakdown_confirm":
        return direction == "short" and candle["close"] <= low
    if mode == "retest_hold":
        touched = candle["low"] <= high and candle["high"] >= low
        return direction == "long" and touched and candle["close"] >= entry
    if mode == "retest_reject":
        touched = candle["low"] <= high and candle["high"] >= low
        return direction == "short" and touched and candle["close"] <= entry
    touched = candle["low"] <= high and candle["high"] >= low
    return touched


def _target_hit(trade: dict, name: str, candle: dict) -> bool:
    value = float(trade[name])
    return candle["high"] >= value if trade["direction"] == "long" else candle["low"] <= value


def _stop_hit(trade: dict, candle: dict) -> bool:
    stop = float(trade["stop"])
    return candle["low"] <= stop if trade["direction"] == "long" else candle["high"] >= stop


def _move_pct(trade: dict, reached: float) -> float:
    entry = max(abs(float(trade["entry"])), 1e-12)
    if trade["direction"] == "long":
        return (float(reached) - float(trade["entry"])) / entry * 100.0
    return (float(trade["entry"]) - float(reached)) / entry * 100.0


def _target_index(name: str) -> int:
    return {"tp1": 1, "tp2": 2, "tp3": 3}.get(name, 0)


def _event_for_target(trade: dict, name: str, when: str) -> dict:
    exposed = list(trade.get("exposed_targets") or [])
    complete = all(bool((trade.get("hits") or {}).get(item)) for item in exposed)
    next_target = None
    for item in exposed:
        if _target_index(item) > _target_index(name) and not (trade.get("hits") or {}).get(item):
            next_target = trade.get(item)
            break
    return {
        "kind": "target_complete" if complete else "target",
        "target_name": name,
        "event_at": when,
        "reached_price": float(trade[name]),
        "rr": float(trade.get(f"rr_{name}") or 0.0),
        "move_pct": _move_pct(trade, float(trade[name])),
        "next_target": float(next_target) if next_target is not None else None,
    }


def _event_for_stop(trade: dict, when: str) -> dict:
    prior = [name.upper() for name in ("tp1", "tp2", "tp3") if (trade.get("hits") or {}).get(name)]
    return {
        "kind": "stop_after_target" if prior else "stop",
        "target_name": "",
        "event_at": when,
        "reached_price": float(trade["stop"]),
        "rr": -1.0,
        "move_pct": _move_pct(trade, float(trade["stop"])),
        "next_target": None,
        "prior_targets": ", ".join(prior),
    }


def _queue_event(trade: dict, event: dict) -> None:
    """Keep the most important unsent event; final target outranks partial."""
    existing = trade.get("pending_followup") if isinstance(trade.get("pending_followup"), dict) else None
    rank = {"target": 1, "stop": 2, "stop_after_target": 3, "target_complete": 4}
    if existing is None or rank.get(event["kind"], 0) >= rank.get(existing.get("kind"), 0):
        trade["pending_followup"] = event


def process_trade_candles(trade: dict, candles: Iterable[dict]) -> None:
    """Pure state transition over candle dictionaries; used by tests and live engine."""
    exposed = [name for name in trade.get("exposed_targets", []) if name in {"tp1", "tp2", "tp3"}]
    if not exposed:
        trade["status"] = "closed"
        trade["close_reason"] = "no_public_targets"
        return
    hits = trade.setdefault("hits", {"tp1": False, "tp2": False, "tp3": False, "stop": False})
    hit_at = trade.setdefault("hit_at", {})

    for candle in candles:
        if trade.get("status") not in {"pending_entry", "active"}:
            break
        when = _iso_ms(int(candle["close_ms"]))
        if trade.get("status") == "pending_entry":
            if not _entry_triggered(trade, candle):
                trade["last_checked_at"] = when
                continue
            trade["entry_confirmed"] = True
            trade["entry_confirmed_at"] = when
            trade["status"] = "active"
            trade["last_checked_at"] = when
            logger.info("Outcome entry confirmed %s %s at %s", trade.get("market_symbol"), trade.get("direction"), when)
            # Avoid guessing intraminute path on the trigger candle.
            continue

        newly = [name for name in exposed if not hits.get(name) and _target_hit(trade, name, candle)]
        stop_now = not hits.get("stop") and _stop_hit(trade, candle)
        if newly and stop_now:
            trade["status"] = "manual_review"
            trade["close_reason"] = "target_and_stop_same_1m_candle"
            trade["closed_at"] = when
            trade["pending_followup"] = None
            trade["last_checked_at"] = when
            logger.warning("Outcome ambiguous %s: target and stop touched in the same 1m candle; no automatic claim", trade.get("market_symbol"))
            break

        if newly:
            for name in newly:
                hits[name] = True
                hit_at[name] = when
            highest = max(newly, key=_target_index)
            event = _event_for_target(trade, highest, when)
            # If a partial target follow-up has already been sent, suppress further
            # partial updates and reserve the second slot for final/stop outcome.
            sent_target = any((f.get("kind") == "target") for f in (trade.get("followups") or []))
            if event["kind"] == "target_complete" or not sent_target:
                _queue_event(trade, event)
            if event["kind"] == "target_complete":
                trade["status"] = "closed"
                trade["close_reason"] = "public_targets_complete"
                trade["closed_at"] = when
            trade["last_checked_at"] = when
            if trade["status"] == "closed":
                break

        if stop_now and trade.get("status") == "active":
            hits["stop"] = True
            hit_at["stop"] = when
            trade["status"] = "closed"
            trade["close_reason"] = "stop"
            trade["closed_at"] = when
            if POST_STOPS:
                _queue_event(trade, _event_for_stop(trade, when))
            trade["last_checked_at"] = when
            break

        trade["last_checked_at"] = when


def _refresh_trade(trade: dict, now: datetime) -> None:
    published = _parse_dt(trade.get("published_at", ""))
    if not published:
        trade["status"] = "manual_review"
        trade["close_reason"] = "invalid_published_at"
        return
    age_h = (now - published).total_seconds() / 3600.0
    if trade.get("status") == "pending_entry" and age_h > PENDING_HOURS:
        trade["status"] = "expired"
        trade["close_reason"] = "entry_not_triggered"
        trade["closed_at"] = now.isoformat()
        trade["pending_followup"] = None
        return
    if trade.get("status") == "active" and age_h > MAX_AGE_HOURS:
        trade["status"] = "expired"
        trade["close_reason"] = "max_tracking_age"
        trade["closed_at"] = now.isoformat()
        trade["pending_followup"] = None
        return
    if trade.get("status") not in {"pending_entry", "active"}:
        return
    last = _parse_dt(trade.get("last_checked_at", "")) or published
    # One-minute overlap prevents a boundary miss; hit flags make reprocessing idempotent.
    start = max(published, last - timedelta(seconds=65))
    candles = _fetch_1m(str(trade["market_symbol"]), start, now)
    if candles:
        process_trade_candles(trade, candles)


def _last_followup_dt(trades: Iterable[dict]) -> Optional[datetime]:
    latest = None
    for trade in trades:
        for row in trade.get("followups") or []:
            dt = _parse_dt(row.get("published_at", ""))
            if dt and (latest is None or dt > latest):
                latest = dt
    return latest


def _pending_candidates(trades: Iterable[dict]) -> List[tuple[dict, dict]]:
    result = []
    priority = {"target_complete": 4, "stop_after_target": 3, "stop": 2, "target": 1}
    for trade in trades:
        event = trade.get("pending_followup")
        if not isinstance(event, dict):
            continue
        if len(trade.get("followups") or []) >= MAX_FOLLOWUPS:
            trade["pending_followup"] = None
            continue
        result.append((trade, event))
    result.sort(key=lambda pair: (-priority.get(pair[1].get("kind"), 0), str(pair[1].get("event_at") or "")))
    return result


def _facts(trade: dict, event: dict) -> dict:
    return {
        "symbol": str(trade.get("symbol") or str(trade.get("market_symbol", "")).removesuffix("USDT")),
        "market_symbol": str(trade.get("market_symbol") or ""),
        "direction": str(trade.get("direction") or "").upper(),
        "event_kind": str(event.get("kind") or ""),
        "target_name": str(event.get("target_name") or ""),
        "entry": float(trade["entry"]),
        "reached_price": float(event["reached_price"]),
        "stop": float(trade["stop"]),
        "rr": float(event.get("rr") or 0.0),
        "move_pct": float(event.get("move_pct") or 0.0),
        "next_target": event.get("next_target"),
        "prior_targets": str(event.get("prior_targets") or ""),
        "original_post_id": str(trade.get("post_id") or ""),
        "event_at": str(event.get("event_at") or ""),
    }


def process_outcomes(*, memory: PostMemory, guard: PublicationGuard, dry_run: bool = False) -> bool:
    """Refresh journal and publish at most one outcome. Return True if published."""
    if not ENABLED:
        return False
    journal = load_journal()
    trades_map = journal.get("trades") if isinstance(journal.get("trades"), dict) else {}
    trades = [row for row in trades_map.values() if isinstance(row, dict)]
    if not trades:
        return False
    now = datetime.now(timezone.utc)
    changed = False
    for trade in trades:
        before = repr(trade)
        try:
            _refresh_trade(trade, now)
        except Exception as exc:
            logger.warning("Outcome refresh failed for %s: %s", trade.get("market_symbol"), exc)
        if repr(trade) != before:
            changed = True
    if changed:
        save_journal(journal)

    pending = _pending_candidates(trades)
    if not pending:
        return False
    last_followup = _last_followup_dt(trades)
    if last_followup and (now - last_followup).total_seconds() < MIN_FOLLOWUP_GAP_MIN * 60:
        logger.info("Outcome follow-up queued; global outcome gap %.0f min not elapsed", MIN_FOLLOWUP_GAP_MIN)
        save_journal(journal)
        return False

    trade, event = pending[0]
    facts = _facts(trade, event)
    if dry_run:
        logger.info("DRY_RUN outcome ready %s %s", trade.get("market_symbol"), event.get("kind"))
        return False

    card_path: Optional[str] = None
    try:
        text, source = build_outcome_post(facts, memory=memory)
        try:
            card_path = generate_outcome_card(
                symbol=facts["symbol"], direction=facts["direction"], event_kind=facts["event_kind"],
                target_name=facts["target_name"], entry=facts["entry"], reached_price=facts["reached_price"],
                rr=facts["rr"], move_pct=facts["move_pct"], stop=facts["stop"],
                original_post_id=facts["original_post_id"], event_time=facts["event_at"],
            )
        except Exception as exc:
            logger.warning("Outcome card generation failed; text-only follow-up: %s", exc)
        published = publish(text, image_path=card_path if card_path and Path(card_path).is_file() else None)
        if not published:
            logger.error("Outcome follow-up publication failed; event remains queued")
            return False

        followup = {
            "kind": event.get("kind"), "target_name": event.get("target_name", ""),
            "post_id": published.post_id, "published_at": datetime.now(timezone.utc).isoformat(),
            "event_at": event.get("event_at", ""), "writer_source": source,
        }
        trade.setdefault("followups", []).append(followup)
        trade["pending_followup"] = None
        save_journal(journal)
        memory.add_post(
            str(trade.get("market_symbol") or facts["symbol"]), text,
            post_style="outcome", signal_type=f"outcome_{event.get('kind')}",
            content_format=f"outcome_{event.get('kind')}", visual_style="avatar_outcome_card",
            direction=str(trade.get("direction") or ""), levels={}, market_price=facts["reached_price"],
        )
        guard.record_success(
            symbol=str(trade.get("market_symbol") or facts["symbol"]), direction=str(trade.get("direction") or ""),
            content_format=f"outcome_{event.get('kind')}", visual_style="avatar_outcome_card",
            market_score=0.0, quality_score=92.0, reach_score=0.0, post_id=published.post_id,
        )
        try:
            record_publication(
                post_id=published.post_id, symbol=facts["symbol"], market_symbol=str(trade.get("market_symbol") or ""),
                text=text, lane="OUTCOME", direction=str(trade.get("direction") or ""),
                content_format=f"outcome_{event.get('kind')}", visual_style="avatar_outcome_card",
                event_class="trade_outcome", writer_source=source, signal_type=f"outcome_{event.get('kind')}",
                public_rr=facts["rr"], decision_mode="outcome", learning_eligible=False,
            )
        except Exception as exc:
            logger.warning("Could not record outcome analytics: %s", exc)
        logger.info(
            "OUTCOME PUBLISHED %s kind=%s target=%s followup_post_id=%s original_post_id=%s",
            trade.get("market_symbol"), event.get("kind"), event.get("target_name"), published.post_id or "n/a", trade.get("post_id"),
        )
        return True
    finally:
        if card_path:
            try:
                Path(card_path).unlink(missing_ok=True)
            except OSError:
                pass
