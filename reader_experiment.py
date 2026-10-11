"""Two-arm reader-value experiment + event novelty checks (no network access)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from statistics import median
from hashlib import sha256
import os


ARMS = ("what_changed", "risk_map")


def _dt(value):
    try:
        result = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
        return (result if result.tzinfo else result.replace(tzinfo=timezone.utc)).astimezone(timezone.utc)
    except (TypeError, ValueError):
        return None


def _num(value, default=0.0):
    try:
        v = float(value)
        return v if -1e9 < v < 1e9 else default
    except (TypeError, ValueError):
        return default


def assigned_arm(symbol: str, lane: str, *, now=None) -> str:
    """Stable within one UTC day; supports unbiased split across symbol-days."""
    when = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    clean = str(symbol or "").upper().replace("$", "").replace("USDT", "")
    payload = f"reader-exp-v1:{clean}:{str(lane).upper()}:{when.date().isoformat()}"
    return ARMS[int.from_bytes(sha256(payload.encode("utf-8")).digest()[:4], "big") % 2]


def writing_brief(arm: str, lane: str) -> str:
    if arm == "what_changed":
        return (
            "ФОРМАТ A — ЧТО ИЗМЕНИЛОСЬ. Первая строка — необычный подтверждённый факт "
            "о движении с тикером. Затем объясни, как один другой факт подтверждает или "
            "оспаривает первый. Конец — конкретный, проверяемый вывод для читателя. "
            "Без общих фраз 'следим за реакцией' и без клише."
        )
    return (
        "ФОРМАТ B — РИСК/РАЗВИЛКА. Первая строка — конкретное расхождение или риск "
        "в данных с тикером. Затем объясни, почему ситуация неоднозначна, и что уже "
        "известно на данный момент. Конец — ясное условие, при котором оценка поменяется. "
        "Не преувеличивай значимость обычных колебаний и не выдумывай новости."
    )


def repeat_decision(memory_items, symbol, attention, micro, *, now=None,
                    standard_hours=12.0, emergency_hours=4.0):
    """Reject same-ticker fatigue unless a verified *new* outsized event develops.

    An exceptional move still needs a 4h gap. Past events are only compared using
    a publication timestamp; this never guesses a new event from old text.
    """
    now = now or datetime.now(timezone.utc)
    target = str(symbol or "").upper().replace("$", "")
    if not target.endswith("USDT"):
        target += "USDT"
    previous = None
    for item in memory_items or ():
        if not isinstance(item, dict):
            continue
        item_symbol = str(item.get("symbol") or "").upper()
        if item_symbol != target:
            continue
        ts = _dt(item.get("ts"))
        if ts is not None and (previous is None or ts > previous):
            previous = ts
    if previous is None:
        return True, "first recorded story for this ticker"
    age_hours = (now - previous).total_seconds() / 3600
    if age_hours < emergency_hours:
        return False, f"same ticker covered {age_hours:.1f}h ago"
    if age_hours >= standard_hours:
        return True, "different publishing window"
    move15 = abs(_num(getattr(attention, "change_15m", 0)))
    vol15 = _num(getattr(attention, "volume_spike", 1), 1)
    move5 = abs(_num(getattr(micro, "change_5m", 0)))
    vol5 = _num(getattr(micro, "volume_spike_5m", 1), 1)
    exceptional = (move15 >= 4 and vol15 >= 3) or (move5 >= 2.5 and vol5 >= 3)
    if exceptional:
        return True, f"exceptional verified new move (15m {move15:.1f}%, volume x{vol15:.1f})"
    return False, f"same ticker covered {age_hours:.1f}h ago; no exceptional new event"


def summarize_arms(posts: dict, *, now=None, days=14) -> dict:
    """Compare ONLY observed 24h milestones. Never include immature posts."""
    now = now or datetime.now(timezone.utc)
    groups = {arm: [] for arm in ARMS}
    for p in (posts or {}).values():
        if not isinstance(p, dict):
            continue
        arm = str(p.get("editorial_arm") or "")
        if arm not in groups or p.get("learning_eligible") is False:
            continue
        dt = _dt(p.get("published_at"))
        if dt is None or dt < now-timedelta(days=days) or dt > now-timedelta(hours=24):
            continue
        row = (p.get("milestones") or {}).get("24h")
        if not isinstance(row, dict):
            continue
        try:
            v = int(row.get("views"))
        except (TypeError, ValueError):
            continue
        if v >= 0:
            groups[arm].append(v)
    return {
        "window_days": days,
        "measurement": "observed views at 24h; directional only, nonrandom markets",
        "arms": [{
            "arm": arm,
            "samples": len(groups[arm]),
            "median_views_24h": round(median(groups[arm]), 1) if groups[arm] else None,
            "posts_100_plus": sum(v >= 100 for v in groups[arm]),
            "rate_100_plus_pct": round(
                100 * sum(v >= 100 for v in groups[arm])/len(groups[arm]), 1
            ) if groups[arm] else None,
        } for arm in ARMS],
        "decision_ready": min(map(len, groups.values())) >= 20,
    }
