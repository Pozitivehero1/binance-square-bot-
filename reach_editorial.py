"""Bounded editorial reach heuristics shared by TRADE and EVENT copy ranking."""
from __future__ import annotations

from dataclasses import dataclass
import re


@dataclass(frozen=True)
class EditorialReachAdjustment:
    score: float
    specificity_hits: int
    generic_hits: int
    reason: str


_PLAN_START = re.compile(
    r"(?iu)^(?:вход\s+(?:long|short)|(?:long|short)[-\s]?план|план\s+(?:long|short)|entry\b)"
)
_SPECIFIC = (
    r"(?iu)\b(?:объ[её]м|vwap|rsi|adx|5\s*минут|15\s*минут|45\s*минут)\b",
    r"(?iu)(?:x|х|×)\s*\d+(?:[.,]\d+)?",
    r"(?u)[+-]?\d+(?:[.,]\d+)?\s*%",
    r"(?iu)\b(?:выше|ниже|около|возле|у\s+уровня)\s+\d+(?:[.,]\d+)?",
)
_GENERIC = (
    r"(?iu)\b(?:активн\w+\s+интерес\w+\s+рынк\w*|ч[её]тк\w+\s+план\w*)\b",
    r"(?iu)\b(?:перв\w+\s+сценар\w+|втор\w+\s+сценар\w+|либо\s+продолжит\w+.*либо)\b",
    r"(?iu)\b(?:пока\s+рано\s+говорить|достаточно\s+подождать|нов\w+\s+структур\w+\s+рынк\w*)\b",
    r"(?iu)\b(?:зон\w+\s+контрол\w+\s+(?:покупател|продавц)\w*|рынок\s+продолжит\s+гнать)\b",
)


def _editorial_text(text: str) -> str:
    lines = []
    for line in str(text or "").splitlines():
        clean = line.strip()
        if _PLAN_START.search(clean):
            break
        if re.search(r"(?iu)\bTP1\b.*\bTP2\b.*\bTP3\b", clean):
            break
        lines.append(line)
    return "\n".join(lines).strip()


def editorial_reach_adjustment(text: str) -> EditorialReachAdjustment:
    value = str(text or "").strip()
    editorial = _editorial_text(value)
    first = next((line.strip() for line in editorial.splitlines() if line.strip()), "")
    specificity = sum(bool(re.search(pattern, editorial)) for pattern in _SPECIFIC)
    generic = sum(bool(re.search(pattern, editorial)) for pattern in _GENERIC)

    score = min(4.0, specificity * 1.6)
    if specificity == 0:
        score -= 4.0
    score -= generic * (1.8 if specificity == 0 else 0.8)
    length = len(value)
    if 250 <= length <= 380:
        score += 2.0
    elif 220 <= length <= 430:
        score += 1.0
    elif length > 450:
        score -= min(5.0, (length - 450) / 22.0 + 1.0)
    elif length < 190:
        score -= 2.0
    if 25 <= len(first) <= 110:
        score += 1.0
    elif len(first) > 135:
        score -= 2.0
    score = max(-8.0, min(7.0, score))
    return EditorialReachAdjustment(
        round(score, 2), specificity, generic,
        f"editorial={score:+.1f} specificity={specificity} generic={generic} chars={length} hook={len(first)}",
    )
