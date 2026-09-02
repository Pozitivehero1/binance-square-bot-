"""Context-aware fact consistency checks for generated Binance Square copy.

Unlike the generic semantic guard, these checks can inspect the exact Python
semantic package that was supplied to the writer. They reject prose that turns
raw indicators into the wrong meaning or speaks as if a newly published plan is
already an open/winning position.
"""
from __future__ import annotations

import re
from typing import Any, Dict, Tuple


def _number(value: Any) -> float | None:
    if value is None:
        return None
    match = re.search(r"[-+]?\d+(?:[.,]\d+)?", str(value))
    if not match:
        return None
    try:
        return float(match.group(0).replace(",", "."))
    except ValueError:
        return None


def _market(package: Dict[str, Any]) -> Dict[str, Any]:
    value = package.get("market") or package.get("market_event") or {}
    return value if isinstance(value, dict) else {}


def _has_public_plan(package: Dict[str, Any]) -> bool:
    if isinstance(package.get("trade_plan"), dict):
        return True
    plan = package.get("optional_trade_plan")
    return bool(isinstance(plan, dict) and plan.get("available"))


def fact_consistency_reasons(text: str, package: Dict[str, Any]) -> Tuple[str, ...]:
    value = str(text or "")
    lowered = value.lower().replace("ё", "е")
    reasons: list[str] = []
    market = _market(package or {})

    # A public setup is published before the outcome engine can confirm an entry.
    # It must therefore read as a plan/condition, never as an already open or
    # profitable position.
    if _has_public_plan(package or {}):
        open_claims = (
            r"\bсделк\w*\s+(?:уже\s+)?(?:работает|активн\w*|открыт\w*)\b",
            r"\bпозици\w*\s+(?:уже\s+)?(?:открыт\w*|активн\w*|работает)\b",
            r"\b(?:мы|я)\s+уже\s+(?:в\s+)?(?:сделк\w*|позици\w*|рынк\w*)\b",
            r"\bвход\s+(?:уже\s+)?(?:сработал|исполнен|активирован)\b",
            r"\bсделк\w*.{0,35}\bв\s+(?:мою|нашу)\s+пользу\b",
        )
        if any(re.search(pattern, lowered, flags=re.IGNORECASE) for pattern in open_claims):
            reasons.append("unconfirmed-position-claim")

    # The package contains a current snapshot, not a historical backtest. Do not
    # let the model manufacture statistical frequency from a single observation.
    if re.search(
        r"(?iu)\b(?:часто\s+предшеству\w*|обычно\s+привод\w*|как\s+правило\s+привод\w*|"
        r"исторически\s+(?:часто|обычно)|в\s+большинстве\s+случаев)\b",
        value,
    ):
        reasons.append("unsupported-historical-generalization")

    # ADX measures trend strength, not direction. Catch both a wrong threshold
    # interpretation and common directional misuse.
    adx = _number(market.get("adx_15m"))
    if re.search(r"(?iu)\b(?:давлени\w*\s+ADX|ADX\s+давит|ADX\s+подтвержда\w*\s+(?:рост|падени)|ADX\s+показыва\w*\s+направлен)\b", value):
        reasons.append("adx-direction-misuse")
    if adx is not None:
        if adx >= 25.0 and re.search(r"(?iu)\bADX\b.{0,45}(?:слаб\w*\s+тренд\w*|тренд\w*\s+слаб\w*)", value):
            reasons.append("adx-strength-contradiction")
        if adx < 20.0 and re.search(r"(?iu)\bADX\b.{0,45}\b(?:сильн\w*|выраженн\w*)\s+тренд", value):
            reasons.append("adx-strength-contradiction")

    rsi = _number(market.get("rsi_15m"))
    if rsi is not None:
        if rsi >= 70.0 and re.search(r"(?iu)\bRSI\b.{0,45}\bперепродан\w*\b", value):
            reasons.append("rsi-state-contradiction")
        if rsi <= 30.0 and re.search(r"(?iu)\bRSI\b.{0,45}\bперекуплен\w*\b", value):
            reasons.append("rsi-state-contradiction")
        if (rsi < 40.0 or rsi > 60.0) and re.search(r"(?iu)\bRSI\b.{0,45}нейтральн\w*\s+зон", value):
            reasons.append("rsi-neutral-contradiction")

    # Prevent category/unit mixing such as "price rose by a third of turnover".
    if re.search(
        r"(?iu)\b(?:вырос\w*|упал\w*|снизил\w*|поднял\w*)\b.{0,35}"
        r"\b(?:треть|половин|четверт|\d+(?:[.,]\d+)?\s*%)\b.{0,20}\bоборот\w*\b",
        value,
    ):
        reasons.append("price-turnover-unit-mix")

    return tuple(dict.fromkeys(reasons))
