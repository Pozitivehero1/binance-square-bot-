"""Bounded, confidence-aware EVENT/TRADE preference from recent Square data."""
from __future__ import annotations
from datetime import datetime, timedelta, timezone
from statistics import median
import os


def _date(value: object):
    try:
        dt = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
        return (dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)).astimezone(timezone.utc)
    except (TypeError, ValueError):
        return None


def lane_bonus(store: dict, *, now=None, lookback_days: int = 7) -> tuple[float, str]:
    """Return bounded EVENT score adjustment, not a mandatory publication target.

    Requires mature 24h samples in both lanes; skips sparse history. The live
    opportunity and hard factual checks stay authoritative.
    """
    if os.getenv("ENABLE_EVENT_REACH_LEARNING", "1").strip().lower() not in {"1", "yes", "true", "on"}:
        return 0.0, "event learning disabled"
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(days=lookback_days)
    groups = {"EVENT": [], "TRADE": []}
    for row in (store.get("posts") or {}).values():
        if not isinstance(row, dict) or row.get("learning_eligible") is False:
            continue
        lane = str(row.get("lane") or "").upper()
        if lane not in groups:
            continue
        timestamp = _date(row.get("published_at"))
        if not timestamp or timestamp > now - timedelta(hours=24) or timestamp < cutoff:
            continue
        milestones = row.get("milestones") or {}
        mature = milestones.get("24h") if isinstance(milestones, dict) else None
        try:
            value = float(mature["views"]) if isinstance(mature, dict) else None
        except (ValueError, TypeError):
            value = None
        if value is not None and value >= 0:
            groups[lane].append(value)
    ne, nt = len(groups["EVENT"]), len(groups["TRADE"])
    if min(ne, nt) < 15:
        return 0.0, f"not enough mature event/trade samples ({ne}/{nt})"
    me, mt = median(groups["EVENT"]), median(groups["TRADE"])
    confidence = min(1.0, min(ne, nt) / 60.0)
    # Do not let historical popularity override a substantially stronger
    # live signal. Also allow TRADE to win if its observed reach is better.
    bonus = max(-4.0, min(4.0, (me / max(20.0, mt) - 1.0) * 8.0)) * confidence
    return round(bonus, 2), f"7d 24h event={me:.0f}/n{ne} trade={mt:.0f}/n{nt} bonus={bonus:+.1f}"


def live_lane_bonus() -> tuple[float, str]:
    try:
        from performance_store import load_store
        return lane_bonus(load_store())
    except Exception as exc:
        return 0.0, f"learning unavailable: {type(exc).__name__}"
