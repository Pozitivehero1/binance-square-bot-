"""Final production text guard for Binance Square posts.

The AI is allowed to write the narrative, but Python owns every public trade-plan
number.  This module removes AI-written plan fragments before the canonical
Python plan is appended and catches malformed/duplicated plan text at the final
publication boundary.
"""
from __future__ import annotations

import re
from typing import Tuple


_TP_RE = re.compile(r"(?iu)\bTP[123]\b")
_SIDE_PLAN_RE = re.compile(r"(?iu)\b(?:LONG|SHORT)\s*[- ]?план\b")
_PLAN_START_RE = re.compile(
    r"(?iu)^(?:"
    r"план\s+(?:LONG|SHORT)\b|"
    r"(?:LONG|SHORT)\s*[|:·—-]|"
    r"вход\s+(?:LONG|SHORT)\b|"
    r"фиксация\s*:|"
    r"цели\s*:"
    r")"
)


def _looks_like_embedded_plan_line(line: str) -> bool:
    value = str(line or "").strip()
    if not value:
        return False
    lowered = value.lower().replace("ё", "е")
    if _TP_RE.search(value) or _SIDE_PLAN_RE.search(value) or _PLAN_START_RE.search(value):
        return True
    # AI sometimes writes a complete entry/stop pair in prose and then Python
    # appends the authoritative plan, producing a visibly duplicated block.
    if re.search(r"(?iu)\bвход\w*\b", value) and re.search(r"(?iu)\bстоп\w*\b", value):
        return True
    # Same problem with compact English-side plan rows.
    if re.search(r"(?iu)\b(?:LONG|SHORT)\b", value) and "|" in value and re.search(r"\d", value):
        return True
    # A dangling numeric fragment such as "TP3 100," must never survive.
    if re.search(r"(?u)\b\d+[.,]\s*$", value) and any(token in lowered for token in ("tp", "цель", "вход", "стоп")):
        return True
    return False


def strip_embedded_trade_plan(text: str) -> str:
    """Remove AI-authored plan rows while preserving the surrounding narrative."""
    source = re.sub(r"\r\n?", "\n", str(text or "")).strip()
    if not source:
        return ""
    kept = [line.rstrip() for line in source.split("\n") if not _looks_like_embedded_plan_line(line)]
    cleaned = "\n".join(kept)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()
    return cleaned


def final_text_reasons(text: str) -> Tuple[str, ...]:
    """Return structural defects that are unsafe to publish as-is."""
    value = str(text or "").strip()
    reasons: list[str] = []
    if not value:
        return ("empty-text",)

    counts = {name: len(re.findall(rf"(?iu)\b{name}\b", value)) for name in ("TP1", "TP2", "TP3")}
    if any(count > 1 for count in counts.values()):
        reasons.append("duplicate-target-block")

    plan_markers = len(re.findall(r"(?iu)\b(?:план\s+(?:LONG|SHORT)|(?:LONG|SHORT)\s*[- ]?план)\b", value))
    if plan_markers > 1:
        reasons.append("duplicate-plan-block")

    if re.search(r"(?ium)\bTP[123]\s+[-+]?\d+(?:[.,]\d+)?[.,]\s*$", value):
        reasons.append("truncated-target-number")

    # Catch a broken final numeric token in a plan-like line even if the TP label
    # was lost by an upstream model/truncation artifact.
    for line in value.splitlines():
        lowered = line.lower().replace("ё", "е")
        if any(token in lowered for token in ("tp", "цель", "вход", "стоп")) and re.search(r"\b\d+[.,]\s*$", line.strip()):
            reasons.append("dangling-plan-number")
            break

    return tuple(dict.fromkeys(reasons))
