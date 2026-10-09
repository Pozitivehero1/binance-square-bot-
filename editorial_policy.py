"""Reader-first quality policy driven only by measured market data.

This layer is independent of market/execution correctness. It is intentionally
opt-in so isolated old tests retain their original selection contracts.
Production enables it via GitHub Actions environment settings.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
import os
import re


@dataclass(frozen=True)
class EditorialDecision:
    allowed: bool
    score: float
    reason: str


def enabled(name: str) -> bool:
    return os.getenv(name, "0").strip().lower() in {"1", "true", "yes", "on"}


def _num(value: object, default: float = 0.0) -> float:
    try:
        value = float(value)
        return value if math.isfinite(value) else default
    except (TypeError, ValueError):
        return default


def evaluate_story(attention, micro, opportunity, *, lane: str) -> EditorialDecision:
    """Require an actual timely observation, not just high abstract model scores.

    Thresholds are deliberately moderate: rare exceptional moves, fresh
    price+volume changes, and high-demand confirmed setups can qualify.
    No arbitrary daily post quota is applied.
    """
    d15 = abs(_num(getattr(attention, "change_15m", 0)))
    d45 = abs(_num(getattr(attention, "change_45m", 0)))
    v15 = _num(getattr(attention, "volume_spike", 1), 1)
    d5 = abs(_num(getattr(micro, "change_5m", 0)))
    v5 = _num(getattr(micro, "volume_spike_5m", 1), 1)
    demand = _num(getattr(opportunity, "audience_demand", 0))
    freshness = str(getattr(micro, "phase", "unknown")).lower()
    story_class = str(getattr(opportunity, "event_class", ""))
    score = round(min(100.0, 10*d15 + 4*d45 + 6*max(0,v15-1)
                      + 4*max(0,v5-1) + min(15,demand/7)), 1)

    # A giant move can be newsworthy even if relative volume normalizes
    # after the initial event. Low-demand tickers need stronger evidence.
    exceptional = (d15 >= 3.5 and v15 >= 0.8) or (d45 >= 7 and v15 >= 0.9)
    notable = [
        d15 >= 1.0 and v15 >= 1.45,
        d45 >= 2.8 and v15 >= 1.15,
        d5 >= 0.85 and v5 >= 1.9 and freshness in {"fresh", "developing"},
        v15 >= 3.0 and d15 >= 0.45,
        v15 >= 6.0 and d5 >= 0.25,
    ]
    # Strong setups with an engaged audience can still be informative, but
    # do not exempt a quiet 0.09% move without meaningful volume.
    solid_trade = (
        lane.upper() == "TRADE" and demand >= 67
        and _num(getattr(opportunity, "score", 0)) >= 78
        and d15 >= 0.65 and v15 >= 1.2
    )
    if freshness == "stale" and not exceptional:
        return EditorialDecision(False, score, "stale market, no new catalyst")
    if demand < 25 and not (exceptional and v15 >= 1.6):
        return EditorialDecision(False, score, "audience too small for an ordinary move")
    if not (exceptional or any(notable) or solid_trade):
        return EditorialDecision(False, score, "no significant verified price/volume event")
    if story_class == "ordinary" and score < 27 and not exceptional:
        return EditorialDecision(False, score, "ordinary movement without compelling evidence")
    return EditorialDecision(
        True, score,
        f"measured move 5m={d5:.2f}% 15m={d15:.2f}% 45m={d45:.2f}%"
        f" volume15=x{v15:.1f} volume5=x{v5:.1f} demand={demand:.0f}"
    )


def event_publication_levels(lane: str, levels: dict) -> dict:
    """EVENT is useful as analysis without an unsolicited trade plan.

    Trade-lane plans are untouched; never publish AI-authored targets.
    """
    if lane.lower() == "event" and enabled("EVENT_OBSERVATION_PREFERRED"):
        return {"plan_valid": False}
    return levels


_SOFT_GENERIC = (
    r"(?iu)наблюдаем\s+за\s+реакцией",
    r"(?iu)ключев(?:ой|ая)\s+момент",
    r"(?iu)рынок\s+жд[её]т",
    r"(?iu)жд[её]м\s+(?:чистую|ясную)\s+реакцию",
    r"(?iu)пока\s+(?:нет|не\s+видно)\s+однозначн",
)
_MEANINGFUL_HEADLINE = re.compile(
    r"(?iu)(?:[+-]?\d+(?:[.,]\d+)?%|\b(?:вырос|раст[её]т|рост|упал|"
    r"падени|снижа|просел|отскоч|пробил|пробой|скачок|обвал|"
    r"рекорд|аномал|всплеск|разворот|перегрев|ускор|объ[её]м|"
    r"конфликт|расхожд|резк|риск|сильн|слаб|противореч)\w*)"
)


def review_copy(text: str) -> EditorialDecision:
    """Reject fake hooks and broken first paragraphs, penalize formulaic jargon.

    Does not validate truth of model-authored numbers: the existing strict
    semantic and final publication guards remain authoritative.
    """
    source = str(text or "").strip()
    lines = [line.strip() for line in source.splitlines() if line.strip()]
    if not lines:
        return EditorialDecision(False, -20, "empty copy")
    first = lines[0]
    editorial = source.split("TP1")[0]
    # Exclude mandatory Entry/SL/TP rows from the style assessment.
    editorial = re.split(r"(?im)^(?:план\s+(?:LONG|SHORT)|вход\s+(?:LONG|SHORT)|LONG\b|SHORT\b)", editorial)[0]
    if len(first) > 125:
        return EditorialDecision(False, -20, "first line is not a headline")
    if not _MEANINGFUL_HEADLINE.search(first):
        return EditorialDecision(False, -20, "headline has no event or reader insight")
    if re.search(r"(?iu)(?:за\s+последние|объ[её]м\s+(?:на|за)|"
                 r"цена\s+(?:на|в)|вырос\s+на|упал\s+на|ниже\s+уровня)\s*$", first):
        return EditorialDecision(False, -20, "first paragraph ends mid-sentence")
    counts = sum(bool(re.search(pattern, editorial)) for pattern in _SOFT_GENERIC)
    jargon = sum(bool(re.search(rf"(?i)\b{name}\b", editorial)) for name in ("RSI","ADX","VWAP","ATR","EMA","MACD"))
    penalty = -min(15, counts*4 + max(0,jargon-2)*4)
    if counts >= 3:
        return EditorialDecision(False, -20, "generic phrases dominate the explanation")
    return EditorialDecision(True, float(penalty), f"generic={counts} indicators={jargon} adjustment={penalty}")


def recommend_copy(draft, *, reviewer=review_copy):
    """Return safe reader-value assessment without touching original text."""
    return reviewer(getattr(draft, "text", ""))
