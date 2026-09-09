"""Uncached quote check immediately before a public trade setup is sent."""
from __future__ import annotations
import math
import requests
from data import BINANCE_APIS


def check_live_plan(symbol, direction, levels, snapshot_price):
    """Fail closed when quote is unavailable, outside the plan, or too far away.

    This checks the current quote, not the full intraminute price path. A crossed
    and subsequently recovered level cannot be inferred from a ticker response.
    """
    try:
        entry = float(levels.get("plan_entry", levels.get("entry")))
        stop, target = float(levels["stop"]), float(levels["tp1"])
        snapshot = float(snapshot_price)
        if direction.upper() not in {"LONG", "SHORT"}:
            return False, "invalid plan direction"
        if not all(math.isfinite(v) and v > 0 for v in (entry, stop, target, snapshot)):
            return False, "invalid plan prices"
        if not (stop < entry < target if direction.upper() == "LONG" else target < entry < stop):
            return False, "invalid plan geometry"
    except (TypeError, ValueError, KeyError):
        return False, "invalid plan prices"
    price = None
    for host in BINANCE_APIS:
        try:
            response = requests.get(host + "/api/v3/ticker/price", params={"symbol": symbol}, timeout=(3, 5))
            response.raise_for_status()
            candidate = float(response.json()["price"])
            if math.isfinite(candidate) and candidate > 0:
                price = candidate
                break
        except (requests.RequestException, ValueError, KeyError, TypeError):
            continue
    if price is None:
        return False, "fresh quote unavailable"
    if not (stop < price < target if direction.upper() == "LONG" else target < price < stop):
        return False, "current price reached stop or first target"
    # A narrow-risk setup needs a tighter freshness tolerance than a wide one.
    tolerance = min(snapshot * 0.005, abs(entry - stop) * 0.5)
    if abs(price - snapshot) > tolerance:
        return False, "price moved too far from analysis snapshot"
    return True, "fresh quote within plan"
