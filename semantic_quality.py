"""High-confidence semantic quality checks for Binance Square copy.

These checks are deliberately conservative. They only block wording that is
clearly corrupted, leaked from prompts, unsupported by the fact package, or
too pushy/absolute for a trading post. Normal stylistic variation remains free.
"""
from __future__ import annotations

import re
from typing import Tuple


_HIGH_CONFIDENCE_RULES = (
    ("mixed-script-word", r"(?u)\b(?:[A-Za-z]+[А-Яа-яЁё]+|[А-Яа-яЁё]+[A-Za-z]+)\b"),
    ("broken-english-fragments", r"(?iu)(?:^|[\s/|,;:])(?:in|a|or)(?:[\s/|,;:]|$).*(?:[\s/|,;:])(?:in|a|or)(?:[\s/|,;:]|$)"),
    ("double-multiplier", r"(?iu)\b(?:x|х|×)\s*\d+(?:[.,]\d+)?\s+в\s+разы\b"),
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
    (
        "unsupported-orderbook-absorption",
        r"(?iu)\b(?:спрос|покупк\w+)\s+(?:полностью\s+)?поглоща\w+\s+продавц\w*\b",
    ),
    (
        "rsi-does-not-count-traders",
        r"(?iu)\bRSI\s*[:=]?\s*\d{1,3}(?:[.,]\d+)?\b.{0,75}"
        r"(?:покупател\w+\s+(?:мало|нет)|продавц\w+\s+(?:мало|нет))\b",
    ),
    (
        "short-invalidated-by-downside-breakout",
        r"(?iu)\b(?:пробой|прорыв)\s+вниз\b.{0,50}\bотмен\w+.{0,28}\b(?:шорт\w*|short)\b",
    ),
    (
        "long-invalidated-by-upside-breakout",
        r"(?iu)\b(?:пробой|прорыв)\s+вверх\b.{0,50}\bотмен\w+.{0,28}\b(?:лонг\w*|long)\b",
    ),
    (
        "vwap-above-does-not-block-upside",
        r"(?iu)\bвыше\s+VWAP\b.{0,60}\bограничива\w+.{0,65}\bрост\w*\b",
    ),
    (
        "internal-ranking-score-leak",
        r"(?iu)\b(?:свежест[ьи](?:\s+(?:события|сигнала))?|"
        r"оценк[а-яё]*(?:\s+(?:интереса|события|качества))?|"
        r"балл(?:ов|а)?)\b[^\n.!?]{0,42}\b\d{1,3}\s*/\s*100\b",
    ),
)


_RSI_RE = re.compile(r"(?iu)\bRSI\s*[:=]?\s*(100(?:[.,]0+)?|\d{1,2}(?:[.,]\d+)?)\b")
_EXTREME_RE = re.compile(r"(?iu)\b(перепродан\w*|перекуплен\w*|перегрев\w*)\b")
_NEGATIVE_RE = re.compile(
    r"(?iu)(?:\bне\s+(?:показыва\w*|указыв\w*|означа\w*|сигнализир\w*|говорит|считается)\b"
    r"|\bбез\s+(?:признаков\s+)?(?:перегрева|перекупленности|перепроданности))"
)
_CLAIM_RE = re.compile(
    r"(?iu)(?:близ\w*\s+к|в\s+зон\w*|указыв\w*\s+на|показыва\w*|"
    r"сигнализир\w*|говорит\s+о|означа\w*|признак\w*|"
    r"находится\s+в|достиг\w*|почти)\b"
)


def rsi_interpretation_reasons(text: str) -> Tuple[str, ...]:
    """Block explicit reversal of RSI extremes while tolerating neutral commentary.

    High-confidence only: RSI at or above 50 is not oversold, and RSI at or
    below 50 is not overbought. Does not claim that an RSI of 70+ proves a
    reversal, or that every RSI reading is an actionable signal.
    """
    value = str(text or "")
    reasons = []
    for match in _RSI_RE.finditer(value):
        rsi = float(match.group(1).replace(",", "."))
        if not 0 <= rsi <= 100:
            continue
        # Only the same clause after RSI belongs to this numeric reading.
        tail = value[match.end():match.end() + 155].split("\n", 1)[0]
        tail = re.split(r"(?<!\d)[.!?](?!\d)|[;]", tail, maxsplit=1)[0]
        claim = _EXTREME_RE.search(tail)
        if not claim:
            continue
        before = tail[:claim.end()]
        if not _CLAIM_RE.search(before) or _NEGATIVE_RE.search(before):
            continue
        word = claim.group(1).lower()
        if "перепродан" in word and rsi >= 50:
            reasons.append("rsi-oversold-meaning-contradiction")
        if ("перекуплен" in word or "перегрев" in word) and rsi <= 50:
            reasons.append("rsi-overbought-meaning-contradiction")
    return tuple(dict.fromkeys(reasons))


def semantic_quality_reasons(text: str) -> Tuple[str, ...]:
    """Return only high-confidence semantic problems that should block a post."""
    value = str(text or "")
    reasons: list[str] = []
    for label, pattern in _HIGH_CONFIDENCE_RULES:
        if re.search(pattern, value):
            reasons.append(label)
    reasons.extend(rsi_interpretation_reasons(value))
    return tuple(dict.fromkeys(reasons))
