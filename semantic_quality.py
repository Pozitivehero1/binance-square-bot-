"""High-confidence semantic quality checks for Binance Square copy.

These checks are deliberately conservative. They only block wording that is
clearly corrupted, leaked from prompts, unsupported by the fact package, or
too pushy/absolute for a trading post. Normal stylistic variation remains free.
"""
from __future__ import annotations

import re
from typing import Tuple


_HIGH_CONFIDENCE_RULES = (
    ("known-typo", r"(?iu)\b(?:ыход|ыхода|ыходу|ыходом|ыходе)\b"),
    ("unsupported-certainty", r"(?iu)\b(?:дело\s+времени|без\s+потерь|гарантированн\w*)\b"),
    (
        "unsupported-timing",
        r"(?iu)\b(?:уже\s+)?через\s+(?:(?:\d+|пару|несколько)\s+)?"
        r"(?:минут\w*|час\w*)\b",
    ),
    (
        "unsupported-target-timing",
        r"(?iu)(?:"
        r"\b(?:сорв[её]тся|дойд[её]т|пойд[её]т|улетит)\b.{0,70}"
        r"\b(?:к|до)\s+(?:перв\w+\s+)?(?:цел\w+|tp\d)\b.{0,45}"
        r"\b(?:(?:менее\s+чем\s+)?за|через|в\s+первые)\b"
        r"|"
        r"\b(?:цел\w+|tp\d)\b.{0,45}\b(?:даст|принес[её]т)\b.{0,70}"
        r"\b(?:уже\s+)?(?:в\s+первые\s+час\w*|через\s+\w+\s+(?:минут\w*|час\w*))\b"
        r")",
    ),
    (
        "pushy-trading",
        r"(?iu)\b(?:покупай|продавай|заходи|залетай)\b|"
        r"\bвпер[её]д\s+к\b|"
        r"\b(?:нужно|надо)\s+действовать\s+быстро\b|"
        r"\bдействовать\s+быстро\s+или\s+пропустить\b",
    ),
    (
        "prompt-leak",
        r"(?iu)\b(?:semantic_package|optional_trade_plan|directional_bias|"
        r"trade_state|json_shape|plain\s+text)\b",
    ),
    (
        "future-certainty",
        r"(?iu)\b(?:цена|рынок|актив|монета|токен)\s+"
        r"(?:точно\s+)?(?:долж(?:ен|на|но)\s+)?"
        r"(?:пойд[её]т|вырастет|упад[её]т)\b",
    ),
    (
        "invented-actor-intent",
        r"(?iu)\b(?:покупатели|продавцы)\b.{0,45}\b(?:"
        r"решил\w*|не\s+успел\w*|заяв\w+\s+о\s+себе|"
        r"повед\w*|потян\w*|рван\w*)\b",
    ),
    (
        "unsupported-time-context",
        r"(?iu)\b(?:после\s+обеда|до\s+обеда|с\s+утра|под\s+вечер|"
        r"по\s+местному\s+рынку|по\s+местному\s+времени)\b",
    ),
    (
        "invented-level-order",
        r"(?iu)\b(?:поддержк\w*|сопротивлен\w*)\s+"
        r"(?:второго|третьего|четв[её]ртого)\s+порядка\b",
    ),
    (
        "overaggressive-risk-wording",
        r"(?iu)\b(?:при\s+малейш\w+\s+слабост\w*|"
        r"свалит\w*\s+без\s+раздумий)\b",
    ),
    (
        "misleading-target-zone",
        r"(?iu)\bцелев\w+\s+зон\w+\s+для\s+(?:long|short|лонг\w*|шорт\w*)\b",
    ),
)


def semantic_quality_reasons(text: str) -> Tuple[str, ...]:
    """Return only high-confidence semantic problems that should block a post."""
    value = str(text or "")
    reasons: list[str] = []
    for label, pattern in _HIGH_CONFIDENCE_RULES:
        if re.search(pattern, value):
            reasons.append(label)
    return tuple(dict.fromkeys(reasons))
