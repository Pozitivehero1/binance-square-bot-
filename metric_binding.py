"""Validate explicit metric/timeframe associations against the writer package."""
import re

NUMBER = r"[-+−]?\d+(?:[.,]\d+)?"
FRAME = r"(?<!\d)(5|15|45|60)\s*[-–]?\s*(?:мин(?:ут\w*)?|[мm](?!\w))"


def _float(value):
    match = re.search(NUMBER, str(value))
    return float(match[0].replace(',', '.').replace('−', '-')) if match else None


def metric_binding_reasons(text, market):
    reasons = []
    text = re.sub(r'\bза\s+(?:последний\s+)?час\b', 'за 60 минут', text, flags=re.I)
    # Written timeframes have the same contract as digit timeframes.
    for word, digit in (("пять", "5"), ("пятнадцать", "15"), ("сорок пять", "45")):
        text = re.sub(r"\bза\s+" + word + r"\s+минут\b", "за " + digit + " минут", text, flags=re.I)
    # Work within clauses, preserving decimal commas and decimal points.
    clauses = re.split(r"[;\n!?]|(?<!\d)[.,]|[.,](?!\d)", text.lower().replace('ё', 'е'))
    for clause in clauses:
        frames = list(re.finditer(FRAME, clause))
        metrics = list(re.finditer(rf"({NUMBER})\s*%|[xх×]\s*({NUMBER})|({NUMBER})\s*[xх×](?!\w)|({NUMBER})\s*раз(?:а|\b)", clause))
        for metric in metrics:
            percent = metric.group(1) is not None
            observed = _float(next(v for v in metric.groups() if v is not None))
            # No explicit timeframe: the older allowed-number guard still applies.
            if not frames:
                continue
            # Only bind across words/punctuation; another metric is a boundary.
            adjacent = []
            for frame in frames:
                left, right = sorted((metric.start(), frame.start()))
                if not any(left < other.start() < right for other in metrics):
                    adjacent.append(frame)
            if len(adjacent) != 1:
                # A compact list can put two frames beside one metric. Prefer
                # an immediately attached 'за 5м', '15м: +1%' association.
                adjacent = [f for f in adjacent if re.fullmatch(r"\s*(?:за\s*)?[:—–=-]?\s*", clause[min(metric.end(), f.end()):max(metric.start(), f.start())])]
            if len(adjacent) != 1 and len(frames)==1 and re.search(r"за (?:это|то) же время", clause):
                adjacent = frames
            if len(adjacent) != 1:
                continue
            chosen = adjacent[0]
            bridge = clause[min(metric.end(), chosen.end()):max(metric.start(), chosen.start())]
            if re.search(r"сверя|сравн|сопостав|против|вместо", bridge):
                continue
            frame = chosen.group(1)
            key = ("change_" if percent else "relative_volume_") + frame + "m"
            if frame == '60':
                key = ('change_' if percent else 'relative_volume_') + '1h'
            previous = bool(re.search(r'предыдущ\w*|\bсначала\b', clause))
            if frame == '15' and previous and percent:
                key = 'previous_change_15m'
            # "снизилась на 4%" expresses -4%; the unsigned magnitude is
            # normal Russian prose, not a changed factual number.
            if percent:
                numeric = metric.group(1)
                prefix = clause[:metric.start()]
                falling = re.search(r"(?:сниз\w*|упал\w*|паден\w*|снижен\w*|потерял\w*|минус)\s*(?:на\s*)?$", prefix)
                rising = re.search(r"(?:вырос\w*|рост\w*|прибав\w*|поднял\w*|восстановлен\w*)\s*(?:на\s*)?$", prefix)
                if numeric and not numeric.startswith(('+','-','−')):
                    if falling:
                        observed = -abs(observed)
                    elif rising:
                        observed = abs(observed)
                elif (falling and observed > 0) or (rising and observed < 0):
                    reasons.append('direction-word-sign-contradiction:' + key)
            expected = _float(market.get(key))
            if frame == '15' and previous and not percent:
                expected = _float((market.get('observed_context') or {}).get('volume_vs_previous_15m'))
            if expected is None or abs(observed - expected) > 0.051:
                reasons.append("metric-timeframe-mismatch:" + key)
            prefix = re.sub(FRAME, "", clause[:metric.start()])
            if percent and re.search(r"\b(?:объем|оборот)\w*(?:\s+(?:за|на|вырос\w*|упал\w*|снизил\w*))*\s*$", prefix):
                reasons.append("volume-percent-not-in-package")
    # Numeric indicator values also belong to their named indicator.
    for name in ('rsi', 'adx'):
        for match in re.finditer(rf"\b{name}\b\s*[:=]?\s*({NUMBER})(?![\d.,]|\s*[мm])", text.lower()):
            expected = _float(market.get(name + '_15m'))
            if expected is not None and abs(_float(match.group(1)) - expected) > 0.051:
                reasons.append('indicator-value-mismatch:' + name)
    return tuple(dict.fromkeys(reasons))
