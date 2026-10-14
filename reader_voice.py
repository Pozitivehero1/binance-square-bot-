"""Gentle editorial scoring: beginner-accessible, credible to experienced traders.

This is not a factual validator and never silently rewrites market claims.
It assesses only the narrative, excluding Python-owned LONG/SHORT/TP rows.
"""
from __future__ import annotations

from dataclasses import dataclass
import re


_TECH_ABBREVIATIONS = re.compile(r"(?iu)\b(?:RSI|ADX|VWAP|ATR|EMA|MACD)\b")
_OTHER_JARGON = re.compile(
    r"(?iu)\b(?:дивергенци\w*|ретест\w*|сетап\w*|"
    r"сняти\w+\s+ликвидност\w*|дельт\w+\s+объ[её]ма)\b"
)
_EMPTY_CLAIMS = (
    r"(?iu)рынок\s+решает,?\s+что\s+делать\s+дальше",
    r"(?iu)силы\s+есть,?\s+а\s+тренда\s+нет",
    r"(?iu)не\s+победа\s+покупател\w*",
    r"(?iu)вспышка\s+внимания",
)
_PLAN_START = re.compile(
    r"(?iu)^(?:вход\s+(?:long|short)|(?:long|short)[-\s]?план|"
    r"план\s+(?:long|short)|entry\b)"
)


@dataclass(frozen=True)
class VoiceAssessment:
    score: float
    tech_terms: int
    other_jargon: int
    empty_claims: int


def prose_only(text: str) -> str:
    """Exclude canonical execution details from jargon scoring."""
    lines = []
    for line in str(text or "").splitlines():
        clean = line.strip()
        if _PLAN_START.search(clean):
            break
        if re.search(r"(?iu)\bTP1\b.*\bTP2\b.*\bTP3\b", clean):
            break
        lines.append(line)
    return "\n".join(lines).strip()


def assess_voice(text: str) -> VoiceAssessment:
    prose = prose_only(text)
    technical = len(_TECH_ABBREVIATIONS.findall(prose))
    jargon = len(_OTHER_JARGON.findall(prose))
    empty = sum(bool(re.search(p, prose)) for p in _EMPTY_CLAIMS)
    # One genuinely useful technical term is acceptable; two or three raw
    # indicators crammed together should lose clearly to accessible prose.
    tech_penalty = max(0, technical - 1) * 3.0 + (1.0 if technical else 0.0)
    score = -min(14.0, tech_penalty + 1.5*jargon + 2.5*empty)
    return VoiceAssessment(round(score, 1), technical, jargon, empty)
