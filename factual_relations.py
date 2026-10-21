"""Check numeric relations and units, rather than just allowed-number tokens."""
from __future__ import annotations

import re
import math

NUM = r"[-+]?\d+(?:[.,]\d+)?"


def _float(value):
    try:
        number = float(str(value).replace(",", "."))
        return number if math.isfinite(number) else None
    except (ValueError, TypeError):
        return None


def relation_reasons(text: str, market: dict) -> tuple[str, ...]:
    value = str(text).lower().replace("ё", "е")
    reasons = []
    # Concurrent windows do not demonstrate temporal persistence or reversal.
    for clause in re.split(r'[!?;\n]|(?<!\d)\.|\.(?!\d)', value):
        if re.search(r'\b(?:если|может|проверить|покажет|будет)\b', clause):
            continue
        if re.search(r'не переш[её]л.{0,35}(?:длинн|окно)|через (?:15|пятнадцать) минут.{0,30}объем|всплеск.{0,35}(?:быстро спал|оказался коротким)', clause):
            reasons.append('different-windows-are-not-event-sequence')
        if re.search(r'(?:оборот.{0,55}(?:скромн|небольш\w* масштаб|низк\w* ликвид)|(?:низк\w* ликвид|малоликвид))', clause):
            reasons.append('turnover-is-not-orderbook-liquidity')
    # Model prose must retain the supplied numeric literals. Spelling a value
    # out (especially "полтора" for 1.6) must not evade the numeric whitelist.
    written = r"(?:нул\w*|один|одного|одна|дв[аеу]|двух|три|трех|четыр\w*|пят[ьи]|шест[ьи]|сем[ьи]|восем[ьи]|девят[ьи]|десят\w*|полтор\w*|половин\w*)"
    if re.search(rf"\b{written}\s+(?:процент\w*|раз(?:а|\b))", value) or re.search(r"\bполтор\w*\b",value):
        reasons.append("written-market-number-use-source-digits")
    if re.search(r"данн\w*.{0,35}(?:помечен|устарел|устарев)|(?:алгоритм|модель).{0,20}(?:счита|помет|оцен)",value):
        reasons.append("internal-diagnostic-is-not-market-fact")
    price = _float(market.get("current_price"))
    # A snapshot cannot establish a historical crossing. Conditional/future
    # clauses are excluded so an honest scenario does not become a false fact.
    clauses = re.split(r"[!?;\n]|(?<!\d)\.|\.(?!\d)", value)
    for clause in clauses:
        if re.search(r"\b(?:если|когда|после|может|могла|была|будет|вернется|опустится|поднимется)\b", clause):
            continue
        if price is None:
            continue
        # An explicit subject is necessary; e.g. "поддержка ниже 100" does
        # not mean that the current price is below 100.
        if not re.search(r"\bцен\w*\b|\bсейчас\b|\bкотировк\w*\b", clause):
            continue
        for match in re.finditer(rf"\b(выше|ниже)\b[^\d!?;]{{0,55}}({NUM})", clause):
            # "выше на 2%" and "выше, чем 5 минут назад" do not compare
            # current price to a numeric price level of 2 or 5.
            if re.match(r"\s*(?:%|мин|час|дн|раз|[xх×])", clause[match.end():]):
                continue
            before = clause[:match.start()]
            subjects = list(re.finditer(r"\b(?:цен\w*|котировк\w*|сейчас|поддержк\w*|сопротивлен\w*|средн\w*|объем\w*|оборот\w*|активност\w*)\b", before))
            if not subjects or not subjects[-1].group().startswith(("цен", "котиров", "сейчас")):
                continue
            boundary = _float(match.group(2))
            if boundary is None:
                continue
            tolerance = max(abs(price), abs(boundary), 1e-12)*0.00001
            relation = match.group(1)
            if re.search(r"\bне\s*$", before):
                relation = "выше" if relation == "ниже" else "ниже"
            if (relation=="ниже" and price>boundary+tolerance) or (relation=="выше" and price<boundary-tolerance):
                reasons.append("price-level-relation-contradiction")
        named = re.search(r"\bцен\w*\b.{0,30}\b(выше|ниже)\s+(?:средневзвешенн\w*|vwap)\b",clause)
        boundary = _float(market.get("vwap"))
        if named and boundary is not None:
            if (named[1]=="ниже" and price>boundary) or (named[1]=="выше" and price<boundary):
                reasons.append("price-vwap-relation-contradiction")
        between = re.search(rf"\bмежду\s+(?:[^\d]{{0,20}})?({NUM})\s+и\s+({NUM})", clause)
        if between and not min(map(_float,between.groups())) <= price <= max(map(_float,between.groups())):
            reasons.append("price-outside-claimed-range")
        implicit = re.search(rf"\bмежду\s+(?:ней|нею|ними|поддержкой)\s+и\s+({NUM})", clause)
        support = _float(market.get("support"))
        if implicit and support is not None:
            other = _float(implicit.group(1))
            if not min(support,other) <= price <= max(support,other):
                reasons.append("price-outside-claimed-range")

    if market.get("vwap") is not None and not market.get("hour_average"):
        if re.search(r"средн\w*(?:\s+цен\w*)?\s+за\s+(?:один\s+)?час\b|часов\w*\s+средн", value):
            reasons.append("unprovided-hour-average")
    if not market.get("relative_trade_count_5m") and not market.get("relative_trade_count_15m"):
        if re.search(r"(?:числ\w*|количеств\w*)\s+сделок|сделок\s+(?:стало|больше|меньше)|всплеск\s+сделок", value):
            reasons.append("volume-is-not-trade-count")
    if not market.get('taker_buy_volume') and re.search(r"ускорени\w*\s+(?:продаж|покупок)|(?:объем|число)\s+(?:продаж|покупок).{0,15}(?:вырос|увеличил)",value):
        reasons.append('order-flow-not-in-package')
    return tuple(dict.fromkeys(reasons))
