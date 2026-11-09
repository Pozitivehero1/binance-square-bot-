"""Fact substitution and duplicate checks, without predicted-interest gates."""
from __future__ import annotations

import re

from publisher import _prepare_text_for_square, russian_news_with_names
from .store import similarity

TOKEN = re.compile(r"\[\[([a-zA-Z][a-zA-Z0-9_]*)\]\]")


def validate(draft, story, recent):
    reasons = []
    raw = draft.text.strip()
    title = draft.title.strip()
    used = TOKEN.findall(raw)
    if story.kind != "news":
        if len(used) != len(set(used)):
            reasons.append("repeated-fact")
        if any(key not in story.facts for key in used):
            reasons.append("unknown-fact-token")
        prose = TOKEN.sub("", raw)
        for sentence in re.split(r"[.!?\n]", prose):
            participant_claim = re.search(r"(?i)\b(?:спрос|покупател\w*|продавц\w*|накоплен\w*|распределени\w*|кит\w*|ликвидац\w*|институционал\w*)\b", sentence)
            cautious = re.search(r"(?i)не (?:доказыва\w*|подтвержда\w*|показыва\w*|означа\w*)|нельзя судить|ничего не говорит", sentence)
            if participant_claim and not cautious:
                reasons.append("unsupported-market-participant-claim")
        if re.search(r"(?i)\b(?:RSI|ADX|VWAP|ATR|EMA|MACD)\b", prose):
            reasons.append("indicator-not-in-evidence")
        text = TOKEN.sub(lambda m: story.facts.get(m[1], m[0]), raw)
        from .grounding import market_reasons
        reasons.extend(market_reasons(text + "\n" + title, story))
    else:
        text = raw
        source = " ".join(story.source_text.split())
        quote = " ".join(draft.evidence_quote.split())
        if len(quote) < 25 or quote.casefold() not in source.casefold():
            reasons.append("missing-verbatim-source-evidence")
        from news_evidence import draft_reasons
        # Retain source event/number checks, with the full RSS content when available.
        checks = draft_reasons(text + " " + title, quote,
                               {"title": story.headline, "summary": story.source_text})
        # Exact source evidence was already checked above. A verb whitelist
        # must not reject an authentic quote just because it says "moves" or
        # "routes" rather than one of the legacy news verbs.
        reasons.extend(r for r in checks if r != "missing-exact-event-evidence")
        if TOKEN.search(text):
            reasons.append("unexpected-fact-token-in-news")
    # A known story ticker is formatting metadata, not an invented market fact.
    # Do not spend another model call merely because the author omitted '$'.
    if not re.search(r"\$[A-Za-z][A-Za-z0-9]{0,19}", text) and story.symbols:
        text = "$"+story.symbols[0]+"\n\n"+text
    if not 90 <= len(text) <= (1600 if story.kind == "news" else 1100):
        reasons.append("length: aim for 90–1100 characters (news up to 1600)")
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
    if story.kind == "news" and russian_news_with_names(prepared):
        final_reasons = tuple(r for r in final_reasons if r != "language:unexpected-english-density")
    reasons.extend(final_reasons)
    return prepared, tuple(dict.fromkeys(reasons))
