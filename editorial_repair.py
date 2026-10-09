"""Safe light-touch editing of model prose before existing fact-lock checks.

Only rearranges a long headline; all original words and numbers are preserved.
No market facts, targets or claims are created by this module.
"""
from __future__ import annotations
import re


def fix_russian_time(text: str) -> str:
    value = str(text or "")
    return re.sub(
        r"(?iu)(?<!\d)(\d+)\s+минуты\b",
        lambda m: m.group(1) + (" минуты" if int(m.group(1)) % 10 in (2, 3, 4)
                               and int(m.group(1)) % 100 not in (12, 13, 14)
                               else " минут"),
        value,
    )


def normalize_headline(text: str, max_headline: int = 110) -> str:
    """Reflow overlong first lines ONLY between complete sentences.

    Never split a phrase like 'за последние 5 минут' into separate paragraphs.
    If the model did not supply a safe full-sentence boundary, leave the text
    unchanged so ordinary headline/quality validation can reject it.
    """
    value = fix_russian_time(re.sub(r"\r\n?", "\n", str(text or "")).strip())
    if not value:
        return value
    first, sep, rest = value.partition("\n")
    if len(first) <= max_headline:
        return value
    # A complete sentence or semicolon may become the headline. Never break
    # after an arbitrary word merely to satisfy a numeric length threshold.
    boundaries = [
        match.end()
        for match in re.finditer(r"(?<=[.!?;])\s+", first)
        if 27 <= match.start() <= max_headline
    ]
    if not boundaries:
        return value
    cut = boundaries[-1]
    head = first[:cut].strip()
    tail = first[cut:].strip()
    if not head or not tail or len(head) > max_headline:
        return value
    return head + "\n\n" + tail + ("\n" + rest.lstrip("\n") if sep and rest.strip() else "")
