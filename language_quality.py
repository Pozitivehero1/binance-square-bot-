"""Language-integrity checks for Russian Binance Square copy.

The bot intentionally allows market terms such as LONG/SHORT, VWAP and TP1/TP2/TP3.
This module only blocks clear prompt/translation leakage where English structure
words get mixed into an otherwise Russian post.
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


def language_quality_reasons(text: str) -> Tuple[str, ...]:
    """Return high-confidence mixed-language corruption markers."""
    value = str(text or "")
    if not re.search(r"[А-Яа-яЁё]", value):
        return tuple()

    reasons: list[str] = []

    # The real production failure looked like: "in тогда ... / a второй ... / or рынок ...".
    if re.search(
        r"(?iu)\b(?:in|or|and|then|else|the|a|an)\b\s+(?=[А-Яа-яЁё])",
        value,
    ):
        reasons.append("mixed-language-logic-token")

    # Ignore cashtags and normal market vocabulary, but reject a cluster of English
    # connective words that strongly suggests leaked prompt/translation structure.
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
    # Density is only used with a meaningful sample to avoid rejecting one harmless
    # English market term in an otherwise normal Russian post.
    if len(latin_tokens) >= 5 and len(unexpected) >= 3 and len(unexpected) / len(latin_tokens) >= 0.45:
        reasons.append("unexpected-english-density")

    return tuple(dict.fromkeys(reasons))
