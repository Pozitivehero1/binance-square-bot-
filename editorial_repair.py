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
    """Move excess first-line prose into body at a word boundary, never truncate.

    Only acts on overlong headlines. The downstream writer validates every
    number and the full trade-plan block again before publication.
    """
    value = fix_russian_time(re.sub(r"\r\n?", "\n", str(text or "")).strip())
    if not value:
        return value
    first, sep, rest = value.partition("\n")
    if len(first) <= max_headline:
        return value
    cut = first.rfind(" ", 26, max_headline + 1)
    if cut < 26:
        return value  # do not damage a malformed/unbreakable headline
    head = first[:cut].rstrip(" ,;:-—")
    tail = first[cut:].lstrip(" ,;:-—")
    if not head or not tail:
        return value
    return head + "\n\n" + tail + ("\n" + rest.lstrip("\n") if sep and rest.strip() else "")
