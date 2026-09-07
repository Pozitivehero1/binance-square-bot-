"""v11.9 writer hardening layered on top of the v11.8 recovery release.

Goals:
- repaired EVENT copy must remain meaningfully AI-authored;
- never pad weak AI residue with repeated deterministic filler paragraphs;
- reject malformed language/placeholder leakage before repaired rows re-enter scoring.
"""
from __future__ import annotations

import re
from typing import Optional


def _strict_repair_event_narrative(raw_text: str, *, ticker: str, plan_available: bool) -> Optional[str]:
    import author_pool_policy as policy
    from language_quality import language_quality_reasons

    source = re.sub(r"```(?:json)?|```", "", str(raw_text or ""), flags=re.IGNORECASE)
    source = policy._HASHTAG_RE.sub("", source)
    source = policy._EMOJI_RE.sub("", source)
    source = re.sub(r"\r\n?", "\n", source)

    kept: list[str] = []
    for raw_line in source.splitlines():
        line = re.sub(r"[ \t]+", " ", raw_line).strip()
        if not line:
            continue
        lowered = line.lower().replace("ё", "е")
        if any(fragment in lowered for fragment in policy._ROBOTIC_FRAGMENTS):
            continue
        if any(fragment in lowered for fragment in policy._UNSAFE_FRAGMENTS):
            continue
        if policy._PLAN_LINE_RE.search(line):
            continue
        if not plan_available and policy._TRADE_ACTION_RE.search(line):
            continue
        # During repair, numeric market claims are discarded because Python owns
        # the factual package. Clean candidates still keep package-owned numbers.
        if policy._NUMBER_RE.search(line):
            continue
        kept.append(line)

    narrative = "\n\n".join(kept).strip()
    narrative = policy._normalize_event_headline(narrative, ticker)
    if not narrative or not policy._text_has_meaningful_ai_residue(narrative, ticker):
        return None

    # v11.9 deliberately does NOT append generic filler. If too little genuine
    # model prose survives repair, the candidate dies and another author/fallback
    # path gets a chance instead of publishing repeated canned language.
    letters = re.sub(r"[^A-Za-zА-Яа-яЁё]", "", narrative)
    words = re.findall(r"[A-Za-zА-Яа-яЁё]{3,}", narrative)
    if len(letters) < 115 or len(words) < 18:
        return None
    if language_quality_reasons(narrative):
        return None

    if len(narrative) > 390:
        paragraphs = [p.strip() for p in narrative.split("\n\n") if p.strip()]
        out: list[str] = []
        for paragraph in paragraphs:
            candidate = "\n\n".join([*out, paragraph]) if out else paragraph
            if len(candidate) > 390:
                break
            out.append(paragraph)
        narrative = "\n\n".join(out).strip()

    if len(narrative) < 150:
        return None
    return narrative


def install_v119_writer_policy() -> None:
    import author_pool_policy as policy

    policy._repair_event_narrative = _strict_repair_event_narrative


def verify_v119_writer_policy() -> None:
    import author_pool_policy as policy

    if policy._repair_event_narrative is not _strict_repair_event_narrative:
        raise RuntimeError("v11.9 strict EVENT repair policy was not installed")

    # Repaired residue that would previously be padded by static fillers must die.
    weak = "$ZEC — движение интересно, но пока без сделки."
    if policy._repair_event_narrative(weak, ticker="$ZEC", plan_available=False) is not None:
        raise RuntimeError("v11.9 weak repaired EVENT residue unexpectedly survived")
