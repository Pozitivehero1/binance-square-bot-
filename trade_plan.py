"""Public trade-plan coherence for Binance Square posts.

The technical engine may calculate several targets and a wide ATR-based stop.
That is useful internally, but the public post needs a simpler contract:

* one decision level that matches where price actually is;
* wording mode derived from the current price/level relationship;
* one meaningful target with a reasonable reward/risk ratio;
* one invalidation level;
* no "wait for a retest" when price is already sitting on the level.

This module is intentionally deterministic. It never predicts that a retest or
breakout *will* happen; it only describes the condition that would make the
setup actionable.
"""
from __future__ import annotations

import math
import os
from typing import Any, Dict, Iterable, Tuple

from indicators import build_trade_levels

MIN_PUBLIC_PLAN_RR = float(os.getenv("MIN_PUBLIC_PLAN_RR", "1.30"))
MAX_PUBLIC_RISK_PCT = float(os.getenv("MAX_PUBLIC_RISK_PCT", "9.0"))
DECISION_NEAR_ATR = float(os.getenv("DECISION_NEAR_ATR", "0.30"))
DECISION_NEAR_PCT = float(os.getenv("DECISION_NEAR_PCT", "0.25"))  # percent
MAX_STRUCTURAL_DISTANCE_ATR = float(os.getenv("MAX_STRUCTURAL_DISTANCE_ATR", "2.40"))
MAX_STRUCTURAL_DISTANCE_PCT = float(os.getenv("MAX_STRUCTURAL_DISTANCE_PCT", "4.0"))  # percent
PUBLIC_STOP_BUFFER_ATR = float(os.getenv("PUBLIC_STOP_BUFFER_ATR", "0.75"))


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
    denominator = max(abs(entry), 1e-12)
    return abs(entry - stop) / denominator * 100.0


def _reward_pct(entry: float, target: float) -> float:
    denominator = max(abs(entry), 1e-12)
    return abs(target - entry) / denominator * 100.0


def _target_candidates(base: Dict[str, float], entry: float, direction: str) -> Iterable[Tuple[str, float]]:
    for name in ("tp1", "tp2", "tp3"):
        value = float(base[name])
        if direction == "long" and value > entry:
            yield name, value
        elif direction == "short" and value < entry:
            yield name, value


def _select_public_target(
    base: Dict[str, float],
    entry: float,
    stop: float,
    direction: str,
) -> Tuple[str, float, float]:
    candidates = list(_target_candidates(base, entry, direction))
    if not candidates:
        fallback = float(base["tp3"])
        return "tp3", fallback, _risk_reward(entry, fallback, stop, direction)

    for name, value in candidates:
        rr = _risk_reward(entry, value, stop, direction)
        if rr >= MIN_PUBLIC_PLAN_RR:
            return name, value, rr

    name, value = max(
        candidates,
        key=lambda item: _risk_reward(entry, item[1], stop, direction),
    )
    return name, value, _risk_reward(entry, value, stop, direction)


def _decision_mode(current: float, decision: float, atr: float, direction: str) -> Tuple[str, float, float]:
    tolerance = max(abs(atr) * DECISION_NEAR_ATR, abs(current) * (DECISION_NEAR_PCT / 100.0))
    distance = current - decision
    distance_pct = abs(distance) / max(abs(current), 1e-12) * 100.0
    distance_atr = abs(distance) / max(abs(atr), 1e-12)

    if abs(distance) <= tolerance:
        return "at_level", distance_pct, distance_atr

    if direction == "long":
        # Price already above a decision level: a pullback/hold is the natural condition.
        if current > decision:
            return "retest_hold", distance_pct, distance_atr
        # Price still below resistance: first need acceptance above it.
        return "breakout_confirm", distance_pct, distance_atr

    # SHORT mirrors LONG.
    if current < decision:
        return "retest_reject", distance_pct, distance_atr
    return "breakdown_confirm", distance_pct, distance_atr


def _structural_candidate(ind, direction: str, base: Dict[str, float]) -> float | None:
    current = float(ind.price)
    atr = max(abs(float(ind.atr)), abs(current) * 1e-8)
    structural = float(ind.resistance if direction == "long" else ind.support)
    stop = float(base["stop"])
    far_target = float(base["tp3"])

    if not _finite(structural):
        return None

    # The decision level must live inside the full trade corridor. This is more
    # flexible than the old TP1-only corridor, while still preventing nonsense
    # such as "wait for 0.210, target 0.200".
    if direction == "long" and not (stop < structural < far_target):
        return None
    if direction == "short" and not (far_target < structural < stop):
        return None

    distance = abs(structural - current)
    max_distance = max(atr * MAX_STRUCTURAL_DISTANCE_ATR, abs(current) * (MAX_STRUCTURAL_DISTANCE_PCT / 100.0))
    if distance > max_distance:
        return None
    return structural


def _build_for_decision(ind, direction: str, base: Dict[str, float], decision: float, source: str) -> Dict[str, Any]:
    current = float(ind.price)
    technical_stop = float(base["stop"])
    atr = max(abs(float(ind.atr)), abs(current) * 1e-8)
    mode, distance_pct, distance_atr = _decision_mode(current, decision, atr, direction)

    # If the public entry is a structural retest level rather than the current
    # price, the technical stop calculated from the current candle can end up
    # only a few ticks away from that level (producing absurd public R/R such
    # as 30:1). Give the public invalidation a minimum ATR buffer while never
    # making it tighter than the technical stop.
    min_buffer = atr * PUBLIC_STOP_BUFFER_ATR
    if direction == "long":
        stop = min(technical_stop, float(decision) - min_buffer)
    else:
        stop = max(technical_stop, float(decision) + min_buffer)

    target_name, public_target, public_rr = _select_public_target(base, decision, stop, direction)
    risk_pct = _risk_pct(decision, stop)
    reward_pct = _reward_pct(decision, public_target)

    geometry_ok = (
        stop < decision < public_target
        if direction == "long"
        else public_target < decision < stop
    )
    rr_ok = public_rr >= MIN_PUBLIC_PLAN_RR
    risk_ok = risk_pct <= MAX_PUBLIC_RISK_PCT

    reasons = []
    if not geometry_ok:
        reasons.append("invalid level geometry")
    if not rr_ok:
        reasons.append(f"public R/R {public_rr:.2f} < {MIN_PUBLIC_PLAN_RR:.2f}")
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
            "decision_distance_pct": distance_pct,
            "decision_distance_atr": distance_atr,
            "plan_entry": float(decision),
            "public_target": float(public_target),
            "public_target_name": target_name,
            "public_rr": float(public_rr),
            "public_risk_pct": float(risk_pct),
            "public_reward_pct": float(reward_pct),
            "plan_valid": bool(geometry_ok and rr_ok and risk_ok),
            "plan_reasons": tuple(reasons),
        }
    )
    return result


def build_public_trade_plan(ind, direction: str) -> Dict[str, Any]:
    """Build a feed-safe trade plan from the indicator snapshot.

    A nearby structural level is preferred only when it produces a coherent
    public plan. Otherwise the current price becomes the decision zone. That
    fallback is deliberately labelled ``at_level`` so copy cannot talk about a
    future retest of the price the market is already trading at.
    """
    if direction not in {"long", "short"}:
        raise ValueError("direction must be 'long' or 'short'")

    base = dict(build_trade_levels(ind, direction))
    current = float(ind.price)

    structural = _structural_candidate(ind, direction, base)
    if structural is not None:
        structural_plan = _build_for_decision(ind, direction, base, structural, "structure")
        if structural_plan["plan_valid"]:
            return structural_plan

    # Current-price fallback is not a predicted entry. It is a decision zone:
    # buyers/sellers must demonstrate control from here before the idea is acted on.
    return _build_for_decision(ind, direction, base, current, "current")


def plan_summary(levels: Dict[str, Any]) -> str:
    reasons = "; ".join(str(item) for item in levels.get("plan_reasons", ())) or "ok"
    return (
        f"mode={levels.get('decision_mode', 'n/a')} "
        f"source={levels.get('decision_source', 'n/a')} "
        f"public_rr={float(levels.get('public_rr', 0.0)):.2f} "
        f"risk={float(levels.get('public_risk_pct', 0.0)):.2f}% "
        f"target={levels.get('public_target_name', 'n/a')} "
        f"valid={bool(levels.get('plan_valid', False))} ({reasons})"
    )
