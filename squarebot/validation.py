"""Fact substitution and duplicate checks, without predicted-interest gates."""
from __future__ import annotations

import re

from publisher import _prepare_text_for_square
from .store import similarity

TOKEN = re.compile(r"\[\[([a-zA-Z][a-zA-Z0-9_]*)\]\]")


def validate(draft, story, recent):
    reasons = []
    raw = draft.text.strip()
    title = draft.title.strip()
    used = TOKEN.findall(raw)
    if story.kind != "news":
        if not used:
            reasons.append("missing-measured-fact: use one or more [[fN]] facts")
        if len(used) != len(set(used)):
            reasons.append("repeated-fact")
        if any(key not in story.facts for key in used):
            reasons.append("unknown-fact-token")
        # Python owns the entire measured clause: direction, unit and timeframe
        # cannot drift independently as they did in the old numeric whitelist.
        prose = TOKEN.sub("", raw)
        prose_without_tickers = re.sub(r"\$[A-Za-z0-9]+", "", prose + " " + title)
        if re.search(r"\d|[%‰]", prose_without_tickers):
            reasons.append("raw-market-number: put measured clauses in [[fN]] tokens")
        for sentence in re.split(r"[.!?\n]", prose):
            participant_claim = re.search(r"(?i)\b(?:спрос|покупател\w*|продавц\w*|накоплен\w*|распределени\w*|кит\w*|ликвидац\w*|институционал\w*)\b", sentence)
            cautious = re.search(r"(?i)не (?:доказыва\w*|подтвержда\w*|показыва\w*|означа\w*)|нельзя судить|ничего не говорит", sentence)
            if participant_claim and not cautious:
                reasons.append("unsupported-market-participant-claim")
        if re.search(r"(?i)\b(?:RSI|ADX|VWAP|ATR|EMA|MACD)\b", prose):
            reasons.append("indicator-not-in-evidence")
        text = TOKEN.sub(lambda m: story.facts.get(m[1], m[0]), raw)
    else:
        text = raw
        source = " ".join(story.source_text.split())
        quote = " ".join(draft.evidence_quote.split())
        if len(quote) < 25 or quote.casefold() not in source.casefold():
            reasons.append("missing-verbatim-source-evidence")
        from news_evidence import draft_reasons
        # Retain source event/number checks, with the full RSS content when available.
        reasons.extend(draft_reasons(text + " " + title, quote,
                                     {"title": story.headline, "summary": story.source_text}))
        if TOKEN.search(text):
            reasons.append("unexpected-fact-token-in-news")
    if not 140 <= len(text) <= (1600 if story.kind == "news" else 1100):
        reasons.append("length: aim for 140–1100 characters (news up to 1600)")
    if title and not 5 <= len(title) <= 130:
        reasons.append("title-length")
    if story.kind == "news" and not title:
        reasons.append("news-title-required")
    symbols = set(re.findall(r"\$([A-Za-z][A-Za-z0-9]{0,19})", text))
    if not symbols.intersection(story.symbols):
        reasons.append("missing-relevant-cashtag")
    if symbols - set(story.symbols):
        reasons.append("unsupported-cashtag")
    if re.search(r"(?i)\b(?:LONG|SHORT|TP[123])\b|\bстоп[ -]?лосс|\bвход\s*[:\d]", text):
        reasons.append("unverified-trading-plan")
    if re.search(r"(?i)гарантир\w*|точно (?:вырастет|упадет|вырастут)|иксы|без риска|подпиш\w*|ставь\w* лайк", text):
        reasons.append("unsupported-promise-or-engagement-bait")
    if re.search(r"(?i)\b(?:rss|json|prompt|fact_ids|output_schema)\b|\[\[|\]\]", text):
        reasons.append("internal-artifact")
    if len(re.findall(r"[а-яё]", text, re.I)) < 60:
        reasons.append("expected-russian-prose")
    for previous in recent[:40]:
        if similarity(text, str(previous.get("text", ""))) >= .62:
            reasons.append("repeated-narrative: choose another topic or argument")
            break
    prepared, final_reasons = _prepare_text_for_square(text)
    reasons.extend(final_reasons)
    return prepared, tuple(dict.fromkeys(reasons))
