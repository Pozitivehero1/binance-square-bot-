"""Two-arm reader-value experiment + event novelty checks (no network access)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from statistics import median
from hashlib import sha256
import os


ARMS = ("what_changed", "risk_map")
EXPERIMENT_VERSION = "v4"


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
    payload = f"reader-exp-v4:{clean}:{str(lane).upper()}:{when.date().isoformat()}"
    return ARMS[int.from_bytes(sha256(payload.encode("utf-8")).digest()[:4], "big") % 2]

 
def arm_for_package(package: dict, lane: str, *, now=None) -> str:
    """Keep generated and stored experiment arms tied to the real market."""
    key = "market_event" if str(lane).upper() == "EVENT" else "market"
    market = package.get(key) if isinstance(package, dict) else None
    ticker = str((market or {}).get("ticker") or "").strip()
    if not ticker:
        raise ValueError("missing real market ticker for experiment assignment")
    return assigned_arm(ticker, lane, now=now)


def writing_brief(arm: str, lane: str) -> str:
    if arm == "what_changed":
        return (
            "ФОРМАТ A — ИНТЕРЕСНОЕ НАБЛЮДЕНИЕ. Это только возможный ракурс, "
            "а не требование структуры: выбери сам, какую закономерность, необычный "
            "контраст или практическое понимание события показать. "
            "Свободно меняй композицию и длину. Дай понятный вывод без "
            "биржевого жаргона, не выдумывая фактов."
        )
    return (
        "ФОРМАТ B — ПОЛЕЗНЫЙ РАЗБОР. Это необязательная подсказка: "
        "можно объяснить ограничение рыночного сигнала, ошибку интерпретации, "
        "цену поспешного решения или честно показать, чего пока не знаем. "
        "Никакого обязательного 'если — то' финала. Объясни риск обычными "
        "словами, не выдумывая фактов и не преувеличивая значения одного индикатора."
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
        if (arm not in groups or p.get("learning_eligible") is False
                or p.get("editorial_experiment_version") != EXPERIMENT_VERSION):
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
        "experiment_version": EXPERIMENT_VERSION,
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
