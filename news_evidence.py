"""Ground short RSS reports in an actual event and an auditable source quote."""
from __future__ import annotations
import re

_ROUNDUP = re.compile(r"(?i)latest (?:crypto|bitcoin|market) news|daily (?:crypto|news) roundup|news (?:today|roundup)|price predictions? today|сводк\w* криптоновост|последние новости.*defi")
_EVENT = re.compile(r"(?i)\b(?:approv\w*|reject\w*|rais\w*|launch\w*|acquir\w*|purchas\w*|bought|buys|sold|sells|fil\w*|announc\w*|hack\w*|exploit\w*|report\w*|halt\w*|resum\w*|sign\w*|invest\w*|list\w*|cuts?|increas\w*|decreas\w*|surge\w*|fall\w*|warn\w*|says?|said|plans?|vot\w*|adds?|reach\w*|releas\w*|record\w*|adopt\w*)\b")


def source_has_event(item: dict) -> bool:
    title = str(item.get("title") or "")
    summary = str(item.get("summary") or "")
    return bool(len(title.split()) >= 4 and len(summary)>=45 and not _ROUNDUP.search(title)
                and _EVENT.search(title+" "+summary))


def draft_reasons(body: str, quote: str, item: dict) -> tuple[str, ...]:
    source = " ".join((str(item.get("title", ""))+" "+str(item.get("summary", ""))).split()).lower()
    normalized = " ".join(str(quote).split()).lower()
    reasons=[]
    if not source_has_event(item):
        reasons.append("source-has-no-specific-event")
    if len(normalized)<25 or normalized not in source or not _EVENT.search(normalized):
        reasons.append("missing-exact-event-evidence")
    if re.search(r"(?i)в сегодняшней сводке|материал охватывает|подробности.{0,35}новостях дня|сводка призвана|описание к новости",body):
        reasons.append("generic-news-filler")
    sentences=[s.strip().lower() for s in re.split(r"(?<=[.!?])\s+",body) if len(s.strip())>25]
    if len(sentences)!=len(set(sentences)):
        reasons.append("repeated-news-sentence")
    # Numbers must be present in RSS evidence. Do not invent amounts, dates,
    # percentages or perform unstated unit conversions during a rewrite.
    def nums(text):
        text=re.sub(r"\$[A-Za-z][A-Za-z0-9]*", "",text)
        return {float(x.replace(",",".")) for x in re.findall(r"(?<![A-Za-z0-9])\d+(?:[.,]\d+)?",text)}
    if not nums(body)<=nums(source):
        reasons.append("unsupported-news-number")
    return tuple(reasons)
