"""Bounded editorial reach heuristics shared by TRADE and EVENT copy ranking."""
from __future__ import annotations

from dataclasses import dataclass
import re

from reader_voice import assess_voice


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
    r"(?iu)\b(?:объ[её]м|движени\w*|рост|падени\w*|снижен\w*|изменени\w*|"
    r"пробой|риск|импульс|отскок|уров[няем]+|5\s*минут|15\s*минут|45\s*минут)\b",
    r"(?iu)(?:x|х|×)\s*\d+(?:[.,]\d+)?",
    r"(?u)[+-]?\d+(?:[.,]\d+)?\s*%",
    r"(?iu)\b(?:выше|ниже|около|возле|у\s+уровня)\s+\d+(?:[.,]\d+)?",
)
_GENERIC = (
    r"(?iu)\b(?:активн\w+\s+интерес\w+\s+рынк\w*|ч[её]тк\w+\s+план\w*)\b",
    r"(?iu)\b(?:перв\w+\s+сценар\w+|втор\w+\s+сценар\w+|либо\s+продолжит\w+.*либо)\b",
    r"(?iu)\b(?:пока\s+рано\s+говорить|достаточно\s+подождать|нов\w+\s+структур\w+\s+рынк\w*)\b",
    r"(?iu)\b(?:зон\w+\s+контрол\w+\s+(?:покупател|продавц)\w*|рынок\s+продолжит\s+гнать)\b",
    r"(?iu)\bключев(?:ой|ая|ое)\s+(?:момент|условие|уровень)\b",
    r"(?iu)\b(?:структур\w+\s+оста[её]тся\s+под\s+вопросом|движение\s+не\s+пустое)\b",
    r"(?iu)\b(?:наблюдаем\s+за\s+(?:реакц|динамик)\w*|жд[её]м\s+(?:реакц|стабилизац)\w*)\b",
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

    score = min(3.0, specificity * 1.0)
    if specificity == 0:
        score -= 1.5  # Insightful plain-language copy needn't mention a technical indicator.
    score -= generic * (2.0 if specificity == 0 else 1.2)
    # Listing indicators is not evidence of a compelling story.
    indicator_count = sum(bool(re.search(rf"(?i)\b{indicator}\b", editorial))
                          for indicator in ("RSI", "ADX", "VWAP", "ATR", "EMA", "MACD"))
    score -= max(0, indicator_count - 1) * 2.0
    # Prefer readable insight over abbreviation-stuffed copy. The canonical
    # Python-owned trade plan is excluded by assess_voice().
    voice = assess_voice(value)
    score += voice.score * 0.6
    length = len(value)
    if 195 <= length <= 420:
        score += 1.5
    elif 170 <= length <= 520:
        score += 0.5
    elif length > 520:
        score -= min(5.0, (length - 520) / 20.0 + 1.0)
    elif length < 165:
        score -= 2.0
    if 25 <= len(first) <= 110:
        score += 1.0
    elif len(first) > 135:
        score -= 2.0
    score = max(-8.0, min(7.0, score))
    return EditorialReachAdjustment(
        round(score, 2), specificity, generic,
        f"editorial={score:+.1f} specificity={specificity} generic={generic} "
        f"voice={voice.score:+.1f}/terms{voice.tech_terms} chars={length} hook={len(first)}",
    )
