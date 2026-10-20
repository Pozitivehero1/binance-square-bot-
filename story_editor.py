"""Evidence-led story selection and semantic repetition ranking; no pacing."""
from __future__ import annotations

import math
import re
from copy import deepcopy


def author_fact_package(package: dict) -> dict:
    """Expose observed market facts, not ranking/phase labels, to prose authors."""
    allowed = {'ticker','current_price','key_level','support','resistance','vwap',
               'vwap_definition','volume_definition','change_5m','change_15m','change_45m',
               'relative_volume_5m','relative_volume_15m','turnover_1h','price_vs_vwap',
               'btc_context','higher_timeframes'}
    clean = deepcopy(package)
    for key in ('market', 'market_event'):
        if isinstance(clean.get(key),dict):
            clean[key]={name:value for name,value in clean[key].items() if name in allowed}
    clean.pop('editorial_arm',None)
    clean.pop('editorial_experiment_version',None)
    return clean


def _n(value, default=0.0):
    match = re.search(r"[-+]?\d+(?:[.,]\d+)?", str(value))
    number = float(match[0].replace(",", ".")) if match else default
    return number if math.isfinite(number) else default


def story_brief(market: dict) -> dict:
    d5, d15, d45 = (_n(market.get("change_"+frame)) for frame in ("5m", "15m", "45m"))
    v5, v15 = (_n(market.get("relative_volume_"+frame),1) for frame in ("5m", "15m"))
    price, support, resistance = (_n(market.get(k)) for k in ("current_price","support","resistance"))
    if support and price < support:
        kind, question = "below_range", "Что изменилось после закрытия ниже нижней границы наблюдаемого диапазона?"
    elif resistance and price > resistance:
        kind, question = "above_range", "Что показывает закрытие выше верхней границы наблюдаемого диапазона?"
    elif d5*d15 < 0 and abs(d5)>=0.3:
        kind, question = "counter_move", "Какая часть движения уже откатилась на коротком отрезке? Не называй это разворотом."
    elif max(v5,v15)>=2.8:
        kind, question = "volume_shock", "Что произошло с ценой на фоне необычного объёма? Не приписывай объёму число сделок или покупателей."
    elif abs(d15)>=1.5 or abs(d45)>=3:
        kind, question = "price_displacement", "Насколько заметно изменился рынок и какой риск создаёт уже пройденное движение?"
    else:
        kind, question = "market_context", "Какой проверяемый контекст делает это небольшое движение полезным читателю? Не преувеличивай."
    keys = {
        "counter_move": ["change_5m","change_15m","relative_volume_5m"],
        "volume_shock": ["relative_volume_5m","relative_volume_15m","change_5m","change_15m"],
        "above_range": ["current_price","resistance","change_15m"],
        "below_range": ["current_price","support","change_15m"],
        "price_displacement": ["change_15m","change_45m","relative_volume_15m"],
        "market_context": ["change_15m","relative_volume_15m","current_price"],
    }[kind]
    return {"kind":kind,"reader_question":question,
            "evidence":{k:market[k] for k in keys if k in market},
            "instruction":"Выбери одну мысль и объясни её конкретное значение. Не перечисляй все метрики и не добавляй пустой финал о наблюдении. Отсутствие торгового плана не нужно объявлять в каждом посте."}


def market_story_adjustment(attention, micro, opportunity, *, recent_story_kinds=(), market=None) -> float:
    # Rank stronger evidence within the existing eligible pool. This function
    # never rejects a candidate or changes the publication schedule.
    d5, d15 = abs(float(micro.change_5m)), abs(float(attention.change_15m))
    v5, v15 = max(.1,float(micro.volume_spike_5m)), max(.1,float(attention.volume_spike))
    evidence = min(4,d15*1.5)+min(3,d5)+min(3,max(0,math.log2(max(v5,v15))))
    if micro.change_5m*attention.change_15m < 0 and d5>=.3:
        evidence += 1.5
    if getattr(micro,"phase","")=="stale":
        evidence -= 4
    demand = max(-2,min(2,(float(opportunity.audience_demand)-50)/20))
    facts = dict(market or {}, change_5m=micro.change_5m, change_15m=attention.change_15m,
                 change_45m=attention.change_45m, relative_volume_5m=v5,relative_volume_15m=v15)
    kind = story_brief(facts)['kind']
    repetition = min(6,list(recent_story_kinds)[-8:].count(kind)*1.5)
    return round(max(-9,min(12,evidence+demand-3-repetition)),2)


def _shape(text):
    value = str(text).lower().replace("ё","е")
    value = re.sub(r"\$[a-z0-9]+|[-+]?\d+(?:[.,]\d+)?\s*%?", " ", value)
    return set(re.findall(r"[а-я]{4,}",value))


def prioritize_formats(formats, kind):
    """A counter-move is a price/volume story, not automatically a VWAP post."""
    priorities = {
        'counter_move': ['event_price_volume','event_market_story','event_pulse'],
        'volume_shock': ['event_price_volume','event_pulse','event_market_story'],
        'price_displacement': ['event_market_story','event_pulse','event_price_volume'],
        'above_range': ['event_one_price','event_market_story','event_pulse'],
        'below_range': ['event_one_price','event_market_story','event_pulse'],
    }.get(kind, [])
    unique=list(dict.fromkeys(formats))
    ordered=[fmt for fmt in priorities if fmt in unique]+[fmt for fmt in unique if fmt not in priorities]
    return [ordered[i % len(ordered)] for i in range(len(formats))] if ordered else []


def copy_adjustment(text: str, recent_texts=()) -> tuple[float, str]:
    value = str(text).lower().replace("ё","е")
    shape = _shape(value)
    similar = 0
    for previous in list(recent_texts)[-10:]:
        old = _shape(previous)
        if len(shape & old)/max(1,min(len(shape),len(old))) >= .65:
            similar += 1
    generic = sum(bool(re.search(p,value)) for p in (
        r"(?:чист\w* сделк\w*|сделки.{0,12}нет)",
        r"наблюд\w* честнее|честнее наблюд|полезнее.*наблюд",
        r"не просто (?:цифр|отметк)|решается больше, чем кажется",
        r"смотреть.{0,15}пока не на что|рынок решает",
        r"важнее сам\w* движен|есть повод открыть тикер",
        r"свежий сигнал отсутствует|чистого сигнала нет",
    ))
    # Reward explanation rather than ticker/keyword presence. These are
    # editorial diagnostics, explicitly not probabilities of reach/conversion.
    evidence = len(re.findall(r"[-+]?\d+(?:[.,]\d+)?\s*%|[xх]\s*\d",value))
    explanation = bool(re.search(r"означает|показывает|поэтому|при этом|однако|но\b|огранич|риск|разниц",value))
    score = min(4,evidence)+ (3 if explanation else -3) -generic*4-min(12,similar*4)
    return float(max(-24,min(7,score))), f"evidence={evidence} explanation={int(explanation)} generic={generic} semantic_repeats={similar}"
