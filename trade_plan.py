"""Deterministic public trade plan for Binance Square v9.

Python owns every tradable number.  The language model receives this package but
is never allowed to invent or alter entry, stop or targets.

v9 exposes a complete plan to the author:
* decision / entry centre;
* entry zone;
* stop loss;
* TP1 / TP2 / TP3;
* reward/risk for every target;
* trade state (decision now / wait for break / wait for retest).

The public ladder is rebuilt around the *public* entry and stop so a structural
entry cannot accidentally produce inverted or absurd target geometry.
"""
from __future__ import annotations

import math
import os
from typing import Any, Dict, Tuple

from indicators import build_trade_levels

MIN_PUBLIC_TP3_RR = float(os.getenv("MIN_PUBLIC_TP3_RR", "1.55"))
MAX_PUBLIC_RISK_PCT = float(os.getenv("MAX_PUBLIC_RISK_PCT", "8.0"))
DECISION_NEAR_ATR = float(os.getenv("DECISION_NEAR_ATR", "0.30"))
DECISION_NEAR_PCT = float(os.getenv("DECISION_NEAR_PCT", "0.25"))  # percent
MAX_STRUCTURAL_DISTANCE_ATR = float(os.getenv("MAX_STRUCTURAL_DISTANCE_ATR", "2.40"))
MAX_STRUCTURAL_DISTANCE_PCT = float(os.getenv("MAX_STRUCTURAL_DISTANCE_PCT", "4.0"))
PUBLIC_STOP_BUFFER_ATR = float(os.getenv("PUBLIC_STOP_BUFFER_ATR", "0.75"))
ENTRY_ZONE_ATR = float(os.getenv("ENTRY_ZONE_ATR", "0.16"))
ENTRY_ZONE_MAX_PCT = float(os.getenv("ENTRY_ZONE_MAX_PCT", "0.35"))  # percent

# Backward compatibility with v8 configuration.  It is no longer the only public
# target threshold, but older env files can still influence the floor.
LEGACY_MIN_RR = float(os.getenv("MIN_PUBLIC_PLAN_RR", "1.30"))


def _finite(value: Any) -> bool:
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


def _risk_reward(entry: float, target: float, stop: float, direction: str) -> float:
    if direction == "long":
        if not (stop < entry < target):
            return 0.0
    else:
        if not (target < entry < stop):
            return 0.0
    risk = abs(entry - stop)
    return abs(target - entry) / risk if risk > 0 else 0.0


def _risk_pct(entry: float, stop: float) -> float:
    return abs(entry - stop) / max(abs(entry), 1e-12) * 100.0


def _decision_mode(current: float, decision: float, atr: float, direction: str) -> Tuple[str, float, float]:
    tolerance = max(abs(atr) * DECISION_NEAR_ATR, abs(current) * (DECISION_NEAR_PCT / 100.0))
    distance = current - decision
    distance_pct = abs(distance) / max(abs(current), 1e-12) * 100.0
    distance_atr = abs(distance) / max(abs(atr), 1e-12)

    if abs(distance) <= tolerance:
        return "at_level", distance_pct, distance_atr
    if direction == "long":
        return ("retest_hold" if current > decision else "breakout_confirm"), distance_pct, distance_atr
    return ("retest_reject" if current < decision else "breakdown_confirm"), distance_pct, distance_atr


def _structural_candidate(ind, direction: str, base: Dict[str, float]) -> float | None:
    current = float(ind.price)
    atr = max(abs(float(ind.atr)), abs(current) * 1e-8)
    structural = float(ind.resistance if direction == "long" else ind.support)
    technical_stop = float(base["stop"])
    technical_far = float(base["tp3"])
    if not _finite(structural):
        return None

    if direction == "long" and not (technical_stop < structural < technical_far):
        return None
    if direction == "short" and not (technical_far < structural < technical_stop):
        return None

    distance = abs(structural - current)
    max_distance = max(atr * MAX_STRUCTURAL_DISTANCE_ATR, abs(current) * (MAX_STRUCTURAL_DISTANCE_PCT / 100.0))
    return structural if distance <= max_distance else None


def _entry_zone(entry: float, atr: float, stop: float, direction: str) -> Tuple[float, float]:
    half = min(abs(atr) * ENTRY_ZONE_ATR, abs(entry) * (ENTRY_ZONE_MAX_PCT / 100.0))
    half = max(half, abs(entry) * 0.00005)
    if direction == "long":
        low = max(stop + abs(entry - stop) * 0.06, entry - half)
        high = entry + half
    else:
        low = entry - half
        high = min(stop - abs(stop - entry) * 0.06, entry + half)
    return min(low, high), max(low, high)


def _target_ladder(
    *,
    entry: float,
    stop: float,
    technical_far: float,
    direction: str,
) -> Tuple[float, float, float, float, float, float]:
    risk = abs(entry - stop)
    far_rr = _risk_reward(entry, technical_far, stop, direction)
    if risk <= 0 or far_rr <= 0:
        return technical_far, technical_far, technical_far, 0.0, 0.0, 0.0

    # Preserve the technical far target.  TP1/TP2 are partial-exit levels inside
    # that corridor.  They are not new support/resistance claims; they are a
    # deterministic risk ladder for position management.
    tp1_rr = min(max(1.00, far_rr * 0.46), far_rr)
    tp2_rr = min(max(tp1_rr + 0.20, far_rr * 0.72), far_rr)
    if far_rr - tp2_rr < 0.12 and far_rr > 1.25:
        tp2_rr = max(tp1_rr + 0.10, far_rr - 0.12)
    tp3_rr = far_rr

    sign = 1.0 if direction == "long" else -1.0
    tp1 = entry + sign * risk * tp1_rr
    tp2 = entry + sign * risk * tp2_rr
    tp3 = entry + sign * risk * tp3_rr
    return tp1, tp2, tp3, tp1_rr, tp2_rr, tp3_rr


def _trade_state(mode: str) -> str:
    return {
        "at_level": "decision_now",
        "retest_hold": "waiting_retest",
        "retest_reject": "waiting_retest",
        "breakout_confirm": "waiting_breakout",
        "breakdown_confirm": "waiting_breakdown",
    }.get(mode, "waiting_confirmation")


def _build_for_decision(ind, direction: str, base: Dict[str, float], decision: float, source: str) -> Dict[str, Any]:
    current = float(ind.price)
    technical_stop = float(base["stop"])
    technical_far = float(base["tp3"])
    atr = max(abs(float(ind.atr)), abs(current) * 1e-8)
    mode, distance_pct, distance_atr = _decision_mode(current, decision, atr, direction)

    # Keep at least an ATR buffer around a structural public entry.  This avoids
    # fake 10R/30R setups caused by a stop sitting a few ticks from that level.
    min_buffer = atr * PUBLIC_STOP_BUFFER_ATR
    if direction == "long":
        stop = min(technical_stop, float(decision) - min_buffer)
    else:
        stop = max(technical_stop, float(decision) + min_buffer)

    # The original technical TP3 can become invalid when the public decision
    # level moves.  In that case use the original reward distance from the current
    # price, projected from the public entry, while retaining the same cap.
    technical_reward = abs(float(base["tp3"]) - float(base["entry"]))
    if direction == "long":
        far_target = technical_far if technical_far > decision else decision + technical_reward
    else:
        far_target = technical_far if technical_far < decision else decision - technical_reward

    tp1, tp2, tp3, rr1, rr2, rr3 = _target_ladder(
        entry=decision, stop=stop, technical_far=far_target, direction=direction
    )
    zone_low, zone_high = _entry_zone(decision, atr, stop, direction)
    risk_pct = _risk_pct(decision, stop)

    if direction == "long":
        geometry_ok = stop < zone_low <= decision <= zone_high < tp1 <= tp2 <= tp3
    else:
        geometry_ok = tp3 <= tp2 <= tp1 < zone_low <= decision <= zone_high < stop

    rr_floor = max(1.20, min(LEGACY_MIN_RR, MIN_PUBLIC_TP3_RR))
    rr_ok = rr3 >= max(MIN_PUBLIC_TP3_RR, rr_floor)
    risk_ok = risk_pct <= MAX_PUBLIC_RISK_PCT

    reasons = []
    if not geometry_ok:
        reasons.append("invalid level geometry")
    if not rr_ok:
        reasons.append(f"TP3 R/R {rr3:.2f} < {max(MIN_PUBLIC_TP3_RR, rr_floor):.2f}")
    if not risk_ok:
        reasons.append(f"public risk {risk_pct:.2f}% > {MAX_PUBLIC_RISK_PCT:.2f}%")

    result: Dict[str, Any] = dict(base)
    result.update(
        {
            "technical_stop": technical_stop,
            "stop": float(stop),
            "decision": float(decision),
            "decision_source": source,
            "decision_mode": mode,
            "trade_state": _trade_state(mode),
            "decision_distance_pct": float(distance_pct),
            "decision_distance_atr": float(distance_atr),
            "plan_entry": float(decision),
            "entry_zone_low": float(zone_low),
            "entry_zone_high": float(zone_high),
            "tp1": float(tp1),
            "tp2": float(tp2),
            "tp3": float(tp3),
            "rr_tp1": float(rr1),
            "rr_tp2": float(rr2),
            "rr_tp3": float(rr3),
            # Compatibility: the first target is what compact posts must contain.
            "public_target": float(tp1),
            "public_target_name": "tp1",
            "public_rr": float(rr3),
            "public_risk_pct": float(risk_pct),
            "plan_valid": bool(geometry_ok and rr_ok and risk_ok),
            "plan_reasons": tuple(reasons),
        }
    )
    return result


def build_public_trade_plan(ind, direction: str) -> Dict[str, Any]:
    if direction not in {"long", "short"}:
        raise ValueError("direction must be 'long' or 'short'")

    base = dict(build_trade_levels(ind, direction))
    current = float(ind.price)

    structural = _structural_candidate(ind, direction, base)
    if structural is not None:
        plan = _build_for_decision(ind, direction, base, structural, "structure")
        if plan["plan_valid"]:
            return plan

    # Current price is a decision zone, not a promise of a future retest.
    return _build_for_decision(ind, direction, base, current, "current")


def plan_summary(levels: Dict[str, Any]) -> str:
    reasons = "; ".join(str(item) for item in levels.get("plan_reasons", ())) or "ok"
    return (
        f"state={levels.get('trade_state', 'n/a')} mode={levels.get('decision_mode', 'n/a')} "
        f"source={levels.get('decision_source', 'n/a')} "
        f"R1={float(levels.get('rr_tp1', 0.0)):.2f} "
        f"R2={float(levels.get('rr_tp2', 0.0)):.2f} "
        f"R3={float(levels.get('rr_tp3', levels.get('public_rr', 0.0))):.2f} "
        f"risk={float(levels.get('public_risk_pct', 0.0)):.2f}% "
        f"valid={bool(levels.get('plan_valid', False))} ({reasons})"
    )
