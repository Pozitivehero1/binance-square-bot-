"""Bind freely written market measurements to the supplied asset, unit and period."""
from __future__ import annotations

import re

NUMBER = r"[+−–-]?\d+(?:[.,]\d+)?"
MEASURE = re.compile(rf"({NUMBER})\s*(%|процентн\w*\s+пункт\w*|процент(?:а|ов)?)", re.I)
TIME = (
    ("previous_1h", re.compile(r"(?:предшествующ\w*|предыдущ\w*)\s+час\w*|час\s+назад", re.I)),
    ("15m", re.compile(r"(?:15|пятнадцат\w*)[\s‑-]*(?:минут\w*)|четверть\s+часа", re.I)),
    ("4h", re.compile(r"(?:4|четыр[её]х?|четырёх)[\s‑-]*(?:час\w*)", re.I)),
    ("24h", re.compile(r"(?:24|двадцат\w*\s+четыр\w*)[\s‑-]*час\w*|сут\w*", re.I)),
    ("1h", re.compile(r"\bчас(?:а|у|ом|овой|овое|ового|овом|овая)?\b", re.I)),
)
DOWN = re.compile(r"пад\w*|снизи\w*|потер\w*|подешев\w*|минус|ниже|уступ\w*", re.I)
UP = re.compile(r"рост\w*|вырос\w*|прибав\w*|подорож\w*|плюс|выше|опереж\w*", re.I)


def value(raw):
    return float(raw.replace(",", ".").replace("−", "-").replace("–", "-"))


def periods(text):
    matches = []
    for name, pattern in TIME:
        for match in pattern.finditer(text):
            matches.append((name, match.start(), match.end()))
    # Longer explicit windows own their complete span: "четырёх часов"
    # inside "двадцати четырёх часов" is not a separate four-hour claim.
    spans = []
    for name, start, end in sorted(matches, key=lambda t: -(t[2]-t[1])):
        if not any(start < b and end > a for _, a, b in spans):
            spans.append((name,start,end))
    return sorted(spans, key=lambda span: span[1])


def canonical_numbers(text):
    # Russian thin-space thousands and either decimal convention are ordinary
    # typography, not new prices. Do this before splitting decimal punctuation.
    text = re.sub(r"(?<=\d)[\s\u00a0\u202f](?=\d{3}(?:\D|$))", "", text)
    text = re.sub(r"\d{1,3}(?:,\d{3})+\.\d+", lambda m:m[0].replace(",", ""), text)
    text = re.sub(r"\d{1,3}(?:\.\d{3})+,\d+", lambda m:m[0].replace(".", "").replace(",", "."), text)
    return text


def clauses(text):
    # A decimal comma/point is not a sentence or clause boundary.
    protected = re.sub(r"(?<=\d)[.,](?=\d)", "§", text)
    pieces = re.split(r"([.!?;\n]|,(?!\d))", protected)
    return [(pieces[i].replace("§", "."), pieces[i+1] if i+1<len(pieces) else "")
            for i in range(0,len(pieces),2) if pieces[i].strip()]


def market_reasons(text, story):
    text = canonical_numbers(text)
    records = []
    source_numbers = set()
    for fact in map(canonical_numbers, story.facts.values()):
        asset = re.findall(r"\$([A-Z0-9]+)", fact)
        clock = periods(fact)
        for m in MEASURE.finditer(fact):
            records.append((value(m[1]), "pp" if "пункт" in m[2].lower() else "%", asset,
                            clock[0][0] if clock else None, "предшествующ" in fact))
        source_numbers.update(value(n) for n in re.findall(NUMBER, re.sub(r"\$[A-Za-z0-9]+", "", fact)))
    reasons, matched = [], 0
    inherited_clock, inherited_asset = None, None
    for clause, separator in clauses(text):
        matches = list(MEASURE.finditer(clause))
        clock = periods(clause)
        asset_spans = list(re.finditer(r"\$([A-Z0-9]+)", clause))
        for measurement in matches:
            number = value(measurement[1])
            unit = "pp" if "пункт" in measurement[2].lower() else "%"
            # Each clause must say its measurement window; a number appearing
            # somewhere in the source is not enough to make a claim true.
            preceding_clocks = [t for t in clock if t[2] <= measurement.start()]
            nearest = (preceding_clocks[-1] if preceding_clocks else
                       min(clock, key=lambda t: abs(t[1]-measurement.end())) if clock else None)
            period = nearest[0] if nearest else inherited_clock
            preceding_assets = [a for a in asset_spans if a.end() <= measurement.start()]
            asset = (preceding_assets[-1][1] if preceding_assets else
                     asset_spans[0][1] if asset_spans else inherited_asset)
            candidates = [r for r in records if abs(abs(r[0])-abs(number)) <= .0051 and r[1] == unit
                          and (not asset or asset in r[2]) and r[3] == period]
            if not candidates:
                reasons.append("measurement-not-bound-to-asset-unit-and-timeframe")
                continue
            explicit_sign = measurement[1][0] in "+-−–"
            before = clause[:measurement.start()]
            inferred_down = bool(DOWN.search(before)) and not UP.search(before)
            inferred_up = bool(UP.search(before)) and not DOWN.search(before)
            if (explicit_sign and not any((r[0] >= 0) == (number >= 0) for r in candidates)
                    or inferred_down and not any(r[0] <= 0 for r in candidates)
                    or inferred_up and not any(r[0] >= 0 for r in candidates)):
                reasons.append("measurement-direction-contradicts-evidence")
            else:
                matched += 1
        # No invented prices, counts, dates or durations. Percentage values
        # are checked above together with their units and periods.
        rest = MEASURE.sub("", re.sub(r"\$[A-Za-z0-9]+", "", clause))
        for _, start, end in reversed(periods(rest)):
            rest = rest[:start]+" "+rest[end:]
        for raw in re.findall(NUMBER, rest):
            if not any(abs(value(raw)-n) <= .00000001 for n in source_numbers):
                reasons.append("unsupported-market-number")
        if clock:
            inherited_clock = clock[-1][0]
        if asset_spans:
            inherited_asset = asset_spans[-1][1]
        if separator in {".","!","?","\n"}:
            inherited_clock, inherited_asset = None, None
    if not matched:
        reasons.append("missing-grounded-market-measurement")
    if re.search(r"[.][,;.]|[,;][.]", text):
        reasons.append("broken-measurement-punctuation")
    return tuple(dict.fromkeys(reasons))
