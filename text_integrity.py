"""Text-integrity helpers for Binance Square posts.

Safe presentation markup is removed; semantic/template corruption is never guessed
or repaired. Unsafe text is rejected so a malformed AI draft cannot reach Square.
"""
from __future__ import annotations

import re
from typing import Tuple


def sanitize_safe_markup(text: str) -> str:
    """Remove presentation-only markup without changing trading facts."""
    value = str(text or "").replace("\r\n", "\n").replace("\r", "\n")
    value = value.replace("**", "").replace("__", "").replace("~~", "")
    value = value.replace("`", "")
    value = re.sub(r"(?m)^\s*#{1,6}\s+", "", value)
    value = re.sub(r"[ \t]+(?=\n|$)", "", value)
    value = re.sub(r"[ \t]{2,}", " ", value)
    value = re.sub(r"\n{3,}", "\n\n", value)
    return value.strip()


def artifact_reasons(text: str) -> Tuple[str, ...]:
    """Return corruption markers that must block publication."""
    value = str(text or "")
    reasons: list[str] = []

    if "\ufffd" in value:
        reasons.append("replacement-character")
    if re.search(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", value):
        reasons.append("control-character")

    if re.search(r"(?i)\bexactly\b", value):
        reasons.append("prompt-word-exactly")
    if re.search(r"(?i)(?<![A-Za-zА-Яа-я0-9])[+\-−]?\s*[XY]\s*%", value):
        reasons.append("percent-placeholder")
    if re.search(r"(?i)\b(?:TODO|TBD)\b", value):
        reasons.append("template-placeholder")
    if re.search(r"\{\{[^{}\n]{1,80}\}\}", value):
        reasons.append("template-braces")

    if re.search(r"[-_=~]{5,}", value):
        reasons.append("symbol-run")
    if re.search(r"[<>⟨⟩]{2,}", value):
        reasons.append("angle-bracket-run")
    if re.search(r"(?:[<>⟨⟩#_=~-]\s*){6,}", value):
        reasons.append("garbage-symbol-sequence")

    if "```" in value or re.search(r"(?m)^\s*#{1,6}\s*$", value):
        reasons.append("markdown-artifact")

    return tuple(dict.fromkeys(reasons))


def prepare_square_text(text: str) -> tuple[str, Tuple[str, ...]]:
    cleaned = sanitize_safe_markup(text)
    return cleaned, artifact_reasons(cleaned)
