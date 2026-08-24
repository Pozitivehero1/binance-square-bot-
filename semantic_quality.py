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
        r"(?iu)\b(?:уже\s+)?через\s+(?:\d+|пару|несколько)\s+"
        r"(?:минут\w*|час\w*)\b",
    ),
    (
        "pushy-trading",
        r"(?iu)\b(?:покупай|продавай|заходи|залетай)\b|"
        r"\bвпер[её]д\s+к\b",
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
)


def semantic_quality_reasons(text: str) -> Tuple[str, ...]:
    """Return only high-confidence semantic problems that should block a post."""
    value = str(text or "")
    reasons: list[str] = []
    for label, pattern in _HIGH_CONFIDENCE_RULES:
        if re.search(pattern, value):
            reasons.append(label)
    return tuple(dict.fromkeys(reasons))
