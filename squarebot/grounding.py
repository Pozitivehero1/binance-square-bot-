"""Bind freely written market measurements to the supplied asset, unit and period."""
from __future__ import annotations

import re

NUMBER = r"[+−–-]?\d+(?:[.,]\d+)?"
MEASURE = re.compile(rf"({NUMBER})\s*(%|процентн\w*\s+пункт\w*)", re.I)
TIME = (
    ("15m", re.compile(r"(?:15|пятнадцат\w*)[\s‑-]*(?:минут\w*)|четверть\s+часа", re.I)),
    ("4h", re.compile(r"(?:4|четыр[её]х?|четырёх)[\s‑-]*(?:час\w*)", re.I)),
    ("24h", re.compile(r"(?:24|двадцат\w*\s+четыр\w*)[\s‑-]*час\w*|сут\w*", re.I)),
    ("1h", re.compile(r"(?:за|последн\w*|предшествующ\w*)\s+(?:(?:один|1)\s+)?час\w*|(?<![а-яё])часов(?:ой|ое|ого|ом|ая)\b", re.I)),
)
DOWN = re.compile(r"пад\w*|снизи\w*|потер\w*|подешев\w*|минус|ниже|уступ\w*", re.I)
UP = re.compile(r"рост\w*|вырос\w*|прибав\w*|подорож\w*|плюс|выше|опереж\w*", re.I)


def value(raw):
    return float(raw.replace(",", ".").replace("−", "-").replace("–", "-"))


def periods(text):
    spans = []
    for name, pattern in TIME:
        for match in pattern.finditer(text):
            # The generic "за час" must not steal "за четыре часа".
            if not any(a <= match.start() < b for _, a, b in spans):
                spans.append((name, match.start(), match.end()))
    return spans


def clauses(text):
    # A decimal comma/point is not a sentence or clause boundary.
    protected = re.sub(r"(?<=\d)[.,](?=\d)", "§", text)
    return [s.replace("§", ".") for s in re.split(r"[.!?;\n]|,(?!\d)", protected) if s.strip()]


def market_reasons(text, story):
    records = []
    source_numbers = set()
    for fact in story.facts.values():
        asset = re.findall(r"\$([A-Z0-9]+)", fact)
        clock = periods(fact)
        for m in MEASURE.finditer(fact):
            records.append((value(m[1]), "%" if m[2] == "%" else "pp", asset,
                            clock[0][0] if clock else None, "предшествующ" in fact))
        source_numbers.update(value(n) for n in re.findall(NUMBER, re.sub(r"\$[A-Za-z0-9]+", "", fact)))
    reasons, matched = [], 0
    for clause in clauses(text):
        matches = list(MEASURE.finditer(clause))
        clock = periods(clause)
        assets = re.findall(r"\$([A-Z0-9]+)", clause)
        for measurement in matches:
            number = value(measurement[1])
            unit = "%" if measurement[2] == "%" else "pp"
            # Each clause must say its measurement window; a number appearing
            # somewhere in the source is not enough to make a claim true.
            nearest = min(clock, key=lambda t: min(abs(t[1]-measurement.end()), abs(measurement.start()-t[2]))) if clock else None
            period = nearest[0] if nearest else None
            candidates = [r for r in records if abs(abs(r[0])-abs(number)) <= .0051 and r[1] == unit
                          and (not assets or set(assets).issubset(set(r[2]))) and r[3] == period
                          and r[4] == ("предшествующ" in clause or "предыдущий час" in clause)]
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
        for _, pattern in TIME:
            rest = pattern.sub("", rest)
        for raw in re.findall(NUMBER, rest):
            if not any(abs(value(raw)-n) <= .00000001 for n in source_numbers):
                reasons.append("unsupported-market-number")
    if not matched:
        reasons.append("missing-grounded-market-measurement")
    if re.search(r"[.][,;.]|[,;][.]", text):
        reasons.append("broken-measurement-punctuation")
    return tuple(dict.fromkeys(reasons))
