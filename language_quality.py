"""Language-integrity checks for Russian Binance Square copy.

The bot intentionally allows market terms such as LONG/SHORT, VWAP and TP1/TP2/TP3.
This module blocks prompt/translation leakage plus high-confidence malformed AI prose
that should never reach publication.
"""
from __future__ import annotations

import re
from typing import Tuple


_ALLOWED_LATIN = {
    "long", "short", "vwap", "usdt", "tp", "tp1", "tp2", "tp3", "sl",
    "entry", "stop", "loss", "take", "profit", "binance", "futures", "spot",
    "breakout", "retest", "setup", "risk", "rr", "ema", "rsi", "adx",
    "btc", "eth", "sol", "bnb", "xrp", "ai",
}
_STRUCTURE_WORDS = {"in", "or", "and", "then", "else", "the", "a", "an", "if"}

# Production failures seen in free-model/repaired copy. Keep this list narrow:
# these are not style preferences, they are publication-corruption markers.
_CORRUPT_FRAGMENTS = (
    "оверсаттеринг", "окоражилась", "классическое срезы", "реализовать эту",
    "цeлая структура правила", "целая структура правила", "cashtag @",
    "xa/rvab", "предварительно заданную схему",
)
_PLACEHOLDER_PATTERNS = (
    r"(?iu)(?<![A-Za-zА-Яа-я0-9])v\d{3,}(?![A-Za-zА-Яа-я0-9])",
    r"(?iu)\[\s*v\d{3,}\s*[;,]\s*v\d{3,}\s*\]",
    r"(?iu)\$[A-Z0-9]{2,20}\s*[≈~=]\s*v\d+",
)


def language_quality_reasons(text: str) -> Tuple[str, ...]:
    """Return high-confidence mixed-language and malformed-prose markers."""
    value = str(text or "")
    reasons: list[str] = []
    lowered_value = value.lower().replace("ё", "е")

    if re.search(
        r"(?iu)\b(?:in|or|and|then|else|the|a|an)\b\s+(?=[А-Яа-яЁё])",
        value,
    ):
        reasons.append("mixed-language-logic-token")

    latin_tokens = re.findall(r"(?u)(?<!\$)\b[A-Za-z][A-Za-z-]{0,30}\b", value)
    lowered = [token.lower() for token in latin_tokens]
    structural = [token for token in lowered if token in _STRUCTURE_WORDS]
    if len(structural) >= 2:
        reasons.append("english-structure-leak")

    unexpected = [
        token
        for token in lowered
        if token not in _ALLOWED_LATIN
        and token not in _STRUCTURE_WORDS
        and not re.fullmatch(r"[a-z]{1,2}\d+", token)
    ]
    if len(latin_tokens) >= 5 and len(unexpected) >= 3 and len(unexpected) / len(latin_tokens) >= 0.45:
        reasons.append("unexpected-english-density")

    if any(fragment in lowered_value for fragment in _CORRUPT_FRAGMENTS):
        reasons.append("known-gibberish-fragment")

    if any(re.search(pattern, value) for pattern in _PLACEHOLDER_PATTERNS):
        reasons.append("model-placeholder-token")

    # Hallucinated social handles are not part of the semantic package and have
    # repeatedly appeared in broken repaired drafts. Email-like tokens are not
    # expected in Square posts either, so any @handle is a safe hard reject.
    if re.search(r"(?u)(?<![\w.])@[A-Za-z][A-Za-z0-9_]{2,30}\b", value):
        reasons.append("hallucinated-social-handle")

    # Catch visibly unfinished Russian prose such as "позволяет реализовать эту."
    if re.search(r"(?iu)\b(?:этот|эта|это|эту|эти|такой|такую)\s*[.!?]\s*$", value.strip()):
        reasons.append("unfinished-russian-clause")

    return tuple(dict.fromkeys(reasons))
