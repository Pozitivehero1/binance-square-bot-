"""Fact-locked Binance Square EVENT writer — v11 Outcome Adaptive Engine.

Python decides whether an audience event is worth discussing and owns any
optional trade plan. DeepSeek V4 Pro is the primary prose author; Mistral is
used only when the primary API is unavailable. Observation-only posts may not
invent direction, entry, stop or targets.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import logging
import os
import re
from typing import Any, Dict, List, Optional, Sequence, Tuple


from attention import AttentionSnapshot, MicroAttentionSnapshot, format_turnover
from ai_provider import has_ai_provider, request_candidates
from engagement import FeedAppealEvaluator
from memory import PostMemory
from quality import QualityReport
from writer import GeneratedPost, _fmt_pct, _fmt_price, _fmt_x, phrase_family_penalty

logger = logging.getLogger(__name__)

POST_MAX_CHARS = int(os.getenv("POST_MAX_CHARS", "560"))
POST_MIN_CHARS = int(os.getenv("POST_MIN_CHARS", "150"))
EVENT_AI_VARIANTS = max(3, min(int(os.getenv("EVENT_AI_VARIANTS", "6")), 10))
EVENT_AI_RETRIES = max(1, min(int(os.getenv("EVENT_AI_RETRIES", "2")), 3))
AI_TIMEOUT = max(10, min(int(os.getenv("AI_TIMEOUT", "55")), 120))
AI_TEMPERATURE = max(0.20, min(float(os.getenv("EVENT_AI_TEMPERATURE", "0.72")), 0.90))
EMOJI_RATE = max(0.0, min(float(os.getenv("EMOJI_RATE", "0.16")), 0.30))

EVENT_FORMAT_SPECS: Dict[str, Dict[str, str]] = {
    "event_pulse": {
        "brief": "Короткая живая реакция: что именно изменилось прямо сейчас и почему тикер стоит открыть. Не выдумывай сделку.",
        "visual": "event_chart",
    },
    "event_price_volume": {
        "brief": "Сопоставь поведение цены и объёма. Объём — контекст, а не автоматический сигнал. 2-4 коротких абзаца.",
        "visual": "event_chart",
    },
    "event_one_price": {
        "brief": "Сделай центром поста одну реально переданную цену/уровень и объясни, почему сейчас смотришь именно туда.",
        "visual": "minimal_chart",
    },
    "event_market_story": {
        "brief": "Расскажи мини-историю о смене темпа/активности рынка без сухого перечня индикаторов.",
        "visual": "context_chart",
    },
    "event_no_trade": {
        "brief": "Событие интересное, но чистой сделки пока нет. Скажи это уверенно и полезно, без шаблона 'жду подтверждения'.",
        "visual": "clean_chart",
    },
    "event_trade_bridge": {
        "brief": "Начни с события. Если optional_trade_plan.available=true, можно естественно дать часть готового плана. Если false — никаких входов/TP/стопа.",
        "visual": "scenario_chart",
    },
}
EVENT_FORMAT_ORDER = tuple(EVENT_FORMAT_SPECS)

_FORBIDDEN_PATTERNS = (
    r"\bгарант\w*", r"\bбез\s+риска\b", r"\bточно\s+(?:выраст|упад|пойд)",
    r"\bсрочно\s+(?:покуп|прода)", r"\b100\s*%", r"\bинсайд\w*", r"\bлистинг\w*",
    r"\bкиты\s+(?:покуп|прода)", r"\bпамп\s+неизбеж", r"\bлегк\w+\s+деньг",
    r"\bдонат\w*", r"\bчаев\w*", r"\btip\b", r"поддерж\w+\s+автор",
    r"постав\w+\s+лайк", r"остав\w+\s+коммент", r"подпиш\w+\s+на",
)
_PREDICTIVE_PATTERNS = (
    r"\bпокупатели\s+удержат\b", r"\bпродавцы\s+удержат\b",
    r"\bретест\w*\s+состо", r"\bцена\s+(?:точно\s+)?пойд[её]т\b",
    r"\bдвижение\s+продолжится\b", r"\bпробой\s+будет\b",
)
_ROBOTIC = (
    "направление у идеи", "граница ошибки", "диапазон контроля", "параметры сценария",
    "карта исполнения", "правило исполнения", "что вижу сейчас", "факты для выбора",
)


def _api_key() -> str:
    return "configured" if has_ai_provider() else ""


def _content_mode() -> str:
    default = "ai_author" if _api_key() else "deterministic"
    return os.getenv("CONTENT_MODE", default).strip().lower()


def _ticker(basic: str) -> str:
    return "$" + re.sub(r"[^A-Za-z0-9]", "", str(basic)).upper()


def _ticker_count(text: str, basic: str) -> int:
    pattern = rf"(?<![A-Za-z0-9_])\${re.escape(str(basic).upper())}(?![A-Za-z0-9_])"
    return len(re.findall(pattern, text.upper()))


def _clean_json(text: str) -> str:
    text = re.sub(r"^```(?:json)?\s*", "", text.strip(), flags=re.IGNORECASE)
    text = re.sub(r"\s*```$", "", text.strip())
    start = text.find("{")
    end = text.rfind("}")
    return text[start:end + 1] if start >= 0 and end > start else text


def _canonical_number(token: str) -> str:
    raw = str(token).strip().lower().replace(",", ".")
    is_x = raw.startswith("x")
    if is_x:
        raw = raw[1:]
    sign = ""
    if raw.startswith(("+", "-")):
        sign, raw = raw[0], raw[1:]
    try:
        number = float(raw)
    except ValueError:
        return str(token).strip().lower().replace(",", ".")
    body = f"{number:.10f}".rstrip("0").rstrip(".")
    if body == "-0":
        body = "0"
    return ("x" if is_x else "") + sign + body


def _extract_numeric_tokens(text: str) -> List[str]:
    pattern = r"(?i)(?<![A-Za-zА-Яа-я0-9])x\d+(?:[.,]\d+)?|(?<![A-Za-zА-Яа-я0-9])[-+]?\d+(?:[.,]\d+)?"
    return [_canonical_number(token) for token in re.findall(pattern, str(text or ""))]


def _allowed_numeric_values(package: Dict[str, Any]) -> set[str]:
    values: set[str] = {_canonical_number(item) for item in ("1", "4", "5", "15", "45")}

    def walk(value: Any) -> None:
        if isinstance(value, dict):
            for item in value.values():
                walk(item)
        elif isinstance(value, (list, tuple)):
            for item in value:
                walk(item)
        elif isinstance(value, str):
            values.update(_extract_numeric_tokens(value))

    walk(package)
    return values


def event_decision_level(indicator) -> float:
    """Choose one truthful nearby chart level for observation posts."""
    price = float(indicator.price)
    candidates = []
    for value in (
        getattr(indicator, "support", None),
        getattr(indicator, "resistance", None),
        getattr(indicator, "vwap", None),
        getattr(indicator, "ema20", None),
    ):
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            continue
        if numeric <= 0:
            continue
        distance_pct = abs(numeric - price) / max(price, 1e-12) * 100.0
        candidates.append((distance_pct, numeric))
    if not candidates:
        return price
    candidates.sort(key=lambda item: item[0])
    # A level 10% away is not a useful 'decision now' anchor.  In that case the
    # chart marks current price instead of inventing relevance.
    return candidates[0][1] if candidates[0][0] <= 4.5 else price


def _semantic_package(
    *,
    basic: str,
    mtf,
    direction: str,
    levels: Optional[Dict[str, Any]],
    btc,
    attention: AttentionSnapshot,
    micro: MicroAttentionSnapshot,
    opportunity,
    monetization,
) -> Dict[str, Any]:
    ind = mtf.tf_15m
    key_level = event_decision_level(ind)
    market: Dict[str, Any] = {
        "ticker": _ticker(basic),
        "current_price": _fmt_price(ind.price),
        "key_level": _fmt_price(key_level),
        "support": _fmt_price(ind.support) if getattr(ind, "support", None) else None,
        "resistance": _fmt_price(ind.resistance) if getattr(ind, "resistance", None) else None,
        "vwap": _fmt_price(ind.vwap) if getattr(ind, "vwap", None) else None,
        "change_5m": _fmt_pct(micro.change_5m),
        "change_15m": _fmt_pct(attention.change_15m),
        "change_45m": _fmt_pct(attention.change_45m),
        "relative_volume_5m": _fmt_x(micro.volume_spike_5m),
        "relative_volume_15m": _fmt_x(attention.volume_spike),
        "turnover_1h": format_turnover(attention.turnover_1h),
        "rsi_15m": f"{ind.rsi:.1f}",
        "adx_15m": f"{ind.adx:.1f}",
        "price_vs_vwap": "выше" if ind.price >= ind.vwap else "ниже",
        "micro_freshness": f"{micro.score:.0f}/100",
        "event_phase": micro.phase,
        "audience_demand": f"{float(opportunity.audience_demand):.0f}/100",
        "event_class": str(opportunity.event_class),
        "w2e_market_score": f"{float(monetization.score):.0f}/100",
        "overextended": bool(attention.overextended),
    }
    if btc is not None:
        market["btc_context"] = {
            "bias": str(btc.bias),
            "change_1h": _fmt_pct(btc.change_1h),
            "change_4h": _fmt_pct(btc.change_4h),
        }

    plan_available = bool(levels and levels.get("plan_valid", False))
    plan: Dict[str, Any] = {
        "available": plan_available,
        "directional_bias": direction.upper(),
    }
    if plan_available and levels is not None:
        plan.update({
            "entry": _fmt_price(levels["plan_entry"]),
            "entry_zone": [
                _fmt_price(levels["entry_zone_low"]),
                _fmt_price(levels["entry_zone_high"]),
            ],
            "stop_loss": _fmt_price(levels["stop"]),
            "tp1": _fmt_price(levels["tp1"]),
            "tp2": _fmt_price(levels["tp2"]),
            "tp3": _fmt_price(levels["tp3"]),
            "rr_tp1": f"{float(levels.get('rr_tp1', 0.0)):.2f}",
            "rr_tp2": f"{float(levels.get('rr_tp2', 0.0)):.2f}",
            "rr_tp3": f"{float(levels.get('rr_tp3', levels.get('public_rr', 0.0))):.2f}",
            "risk_pct": f"{float(levels.get('public_risk_pct', 0.0)):.2f}%",
            "decision_mode": str(levels.get("decision_mode", "at_level")),
        })
    else:
        plan["rule"] = (
            "OBSERVATION_ONLY: clean public trade plan is unavailable. Do not write LONG/SHORT, "
            "entry, stop-loss or TP targets. It is valid to say there is no clean trade yet."
        )
    return {"market_event": market, "optional_trade_plan": plan}


def _format_rotation(memory: Optional[PostMemory], count: int) -> List[str]:
    recent = memory.get_last_content_formats(18) if memory else []
    frequency = {fmt: recent.count(fmt) for fmt in EVENT_FORMAT_ORDER}
    last = recent[-1] if recent else ""
    ranked = sorted(
        EVENT_FORMAT_ORDER,
        key=lambda fmt: (frequency.get(fmt, 0) + (3 if fmt == last else 0), EVENT_FORMAT_ORDER.index(fmt)),
    )
    out: List[str] = []
    while len(out) < count:
        for fmt in ranked:
            if len(out) >= count:
                break
            out.append(fmt)
    return out


def _request_ai_candidates(
    *,
    package: Dict[str, Any],
    formats: Sequence[str],
    recent_posts: Sequence[str],
    attempt: int,
) -> List[dict]:
    if not has_ai_provider():
        return []
    plan_available = bool(package.get("optional_trade_plan", {}).get("available"))
    payload = {
        "task": "Напиши готовые посты для Binance Square по живому рыночному событию. Каждый текст придумай с нуля.",
        "semantic_package": package,
        "formats_in_order": [
            {"format_id": fmt, "brief": EVENT_FORMAT_SPECS[fmt]["brief"]} for fmt in formats
        ],
        "recent_posts_to_avoid": [str(item)[:650] for item in recent_posts[-10:]],
        "attempt": attempt,
        "rules": [
            "Пиши на русском как живой практикующий трейдер, а не как бот/терминал.",
            "Первая строка — сильный самостоятельный хук и обязательно содержит основной cashtag.",
            "Используй только числа из semantic_package. Не пересчитывай, не округляй по-своему и не придумывай числа.",
            "Не обязан перечислять показатели. Выбери 1-3 факта, которые лучше всего объясняют, почему событие интересно сейчас.",
            "Не утверждай будущее. Только наблюдение и условные формулировки.",
            "Не используй одинаковую композицию, открывающую фразу и финал из recent_posts_to_avoid.",
            "Не пиши шаблон 'жду подтверждения → уровень → цель → отмена' просто по привычке.",
            "Не добавляй новости, китов, ликвидации, инсайды, причины движения и другие факты, которых нет в пакете.",
            "Не выпрашивай лайки, комментарии, подписки, донаты или чаевые и не упоминай Write to Earn/вознаграждение автора.",
            "Не добавляй хэштеги и эмодзи. Код сам решит, нужен ли один акцент.",
            "Вопрос в конце не обязателен и допустим максимум в одном варианте партии.",
            f"Длина каждого поста {POST_MIN_CHARS}-{POST_MAX_CHARS} символов.",
        ],
        "trade_rule": (
            "optional_trade_plan.available=true: торговый план уже рассчитан Python. Можешь использовать часть или весь план, "
            "если это естественно для выбранного формата; никогда не меняй direction/entry/stop/TP."
            if plan_available else
            "optional_trade_plan.available=false: это observation-only пост. Запрещены LONG/SHORT, вход, стоп и TP. "
            "Не выдумывай сделку ради призыва к торговле."
        ),
        "json_shape": {
            "candidates": [
                {"format_id": formats[0] if formats else "event_pulse", "text": "готовый многоабзацный пост"}
            ]
        },
    }
    result = request_candidates(
        system_prompt=(
            "Ты автор трейдерского аккаунта Binance Square. Пиши живые и разные посты из строго заданных фактов. "
            "Никаких выдуманных рыночных данных и обещаний. Если чистой сделки нет, ценность поста — в наблюдении, "
            "а не в искусственно придуманном сигнале. Не проси донаты, лайки, комментарии или подписки. "
            "Верни только валидный JSON."
        ),
        user_payload=payload,
        temperature=AI_TEMPERATURE,
        max_tokens=3200,
        timeout=AI_TIMEOUT,
        presence_penalty=0.65,
        frequency_penalty=0.50,
    )
    return result.candidates


def _decorate_headline(text: str, *, format_id: str, attention: AttentionSnapshot, micro: MicroAttentionSnapshot, index: int) -> Tuple[str, str]:
    parts = text.splitlines()
    first_index = next((i for i, line in enumerate(parts) if line.strip()), None)
    if first_index is None:
        return text, ""
    headline = parts[first_index].strip()
    token = f"event|{headline}|{format_id}|{index}".encode("utf-8")
    bucket = int(hashlib.sha1(token).hexdigest()[:8], 16) / 0xFFFFFFFF
    if bucket < EMOJI_RATE and not any(mark in headline for mark in ("⚡", "⚠️", "👀")):
        if micro.score >= 76 or attention.volume_spike >= 5:
            mark = "⚡"
        elif attention.overextended:
            mark = "⚠️"
        elif format_id == "event_one_price":
            mark = "👀"
        else:
            mark = ""
        if mark:
            headline = f"{mark} {headline}"
            parts[first_index] = headline
    return "\n".join(parts).strip(), headline


def _validate_event_post(
    text: str,
    *,
    basic: str,
    direction: str,
    package: Dict[str, Any],
) -> Tuple[bool, Tuple[str, ...]]:
    reasons: List[str] = []
    text = str(text or "").strip()
    lowered = text.lower().replace("ё", "е")
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    first = lines[0] if lines else ""
    ticker = _ticker(basic)
    plan_available = bool(package.get("optional_trade_plan", {}).get("available"))

    if not first or ticker.lower() not in first.lower():
        reasons.append("ticker missing from headline")
    if not 1 <= _ticker_count(text, basic) <= 2:
        reasons.append("ticker count")
    if not POST_MIN_CHARS <= len(text) <= POST_MAX_CHARS:
        reasons.append(f"length {len(text)}")
    if len(first) > 130:
        reasons.append("headline too long")
    if text.count("?") > 1:
        reasons.append("too many questions")
    if re.search(r"#[A-Za-zА-Яа-я0-9_]+", text):
        reasons.append("hashtags forbidden")
    if len(re.findall(r"[\U0001F300-\U0001FAFF\u2600-\u27BF]", text)) > 0:
        reasons.append("AI emoji forbidden")
    if any(item in lowered for item in _ROBOTIC):
        reasons.append("robotic wording")
    if any(re.search(pattern, lowered, flags=re.IGNORECASE) for pattern in _FORBIDDEN_PATTERNS):
        reasons.append("unsupported/pushy claim")
    if any(re.search(pattern, lowered, flags=re.IGNORECASE) for pattern in _PREDICTIVE_PATTERNS):
        reasons.append("predictive claim")

    expected = ("long", "лонг") if direction == "long" else ("short", "шорт")
    opposite = ("short", "шорт") if direction == "long" else ("long", "лонг")
    has_direction = any(re.search(rf"\b{term}\b", lowered) for term in expected + opposite)
    if plan_available:
        if any(re.search(rf"\b{term}\b", lowered) for term in opposite):
            reasons.append("opposite direction")
    else:
        # No clean plan = no manufactured call to trade.  The post may still
        # discuss price/volume/levels from the factual package.
        if has_direction:
            reasons.append("direction forbidden without public plan")
        if any(token in lowered for token in ("tp1", "tp2", "tp3", "стоп", "stop-loss", "стоп-лосс", "r/r", "р/р", "тейк-профит")):
            reasons.append("trade targets forbidden without public plan")
        if re.search(r"\bвход(?:а|у|ом|е)?\b", lowered):
            reasons.append("entry forbidden without public plan")
        if re.search(r"\b(?:покупаю|продаю|вхожу|открываю\s+позици\w*)\b", lowered):
            reasons.append("trade action forbidden without public plan")

    allowed = _allowed_numeric_values(package)
    unexpected = set(_extract_numeric_tokens(text)) - allowed
    if unexpected:
        reasons.append("unexpected numbers: " + ",".join(sorted(unexpected)))
    return not reasons, tuple(reasons)


def _deterministic_event_candidate(
    *,
    basic: str,
    mtf,
    direction: str,
    levels: Optional[Dict[str, Any]],
    attention: AttentionSnapshot,
    micro: MicroAttentionSnapshot,
    format_id: str,
    index: int,
) -> str:
    ind = mtf.tf_15m
    ticker = _ticker(basic)
    move5 = _fmt_pct(micro.change_5m)
    move15 = _fmt_pct(attention.change_15m)
    vol5 = _fmt_x(micro.volume_spike_5m)
    vol15 = _fmt_x(attention.volume_spike)
    level = _fmt_price(event_decision_level(ind))
    variant = index % 4
    plan_available = bool(levels and levels.get("plan_valid", False))

    if format_id == "event_price_volume":
        heads = (
            f"{ticker}: объём изменился заметнее цены — и именно это сейчас интересно",
            f"В {ticker} активность выросла, но свеча пока не рассказывает всю историю",
            f"{ticker}: смотрю не на сам x-объём, а на то, что цена делает рядом с {level}",
            f"По {ticker} объём заметен, но решение пока больше в поведении цены",
        )
        bodies = (
            f"За 5 минут {move5}, за 15 — {move15}. Объём на коротком участке около {vol5} нормы.\n\nПока слежу за {level}: если активность останется, именно реакция цены там даст больше информации, чем ещё одна цифра объёма.",
            f"15-минутное изменение {move15}, объём около {vol15} обычного.\n\nДля меня это повод открыть график, а не автоматически открыть позицию. Район {level} сейчас полезнее любого поспешного ярлыка сделки.",
            f"На 5 минутах {move5}, объём около {vol5} нормы.\n\nЕсли цена продолжит крутиться возле {level} при повышенной активности, там и будет следующий полезный ответ рынка.",
            f"За 15 минут {move15}, объём около {vol15} нормы.\n\nСобытие есть, но чистой сделки из одного всплеска объёма я не делаю. Смотрю, как поведёт себя {level}.",
        )
    elif format_id == "event_one_price":
        heads = (
            f"{ticker}: сейчас мне достаточно одной цены — {level}",
            f"В {ticker} вся короткая история для меня свелась к {level}",
            f"{ticker} стал активнее; вместо десятка индикаторов смотрю на {level}",
            f"По {ticker} сейчас важнее не прогноз, а реакция на {level}",
        )
        bodies = (
            f"За 15 минут {move15}, объём около {vol15} нормы.\n\nПока цена рядом, мне интереснее увидеть, изменится ли поведение рынка у этой зоны. Чистой сделки до этого не форсирую.",
            f"На 5 минутах {move5}, активность около {vol5} обычной.\n\nЭтот уровень сейчас даёт больше контекста, чем попытка угадать следующую свечу. Если рынок уйдёт от него без структуры, просто пропущу.",
            f"Последние 15 минут дали {move15}.\n\nНе хочу превращать сам факт движения в сигнал. Сначала смотрю, как цена взаимодействует с {level}; дальше уже будет понятно, есть ли вообще что торговать.",
            f"Короткий импульс: {move15}; объём примерно {vol15} нормы.\n\nПока {level} остаётся рядом с ценой, это моя точка наблюдения. Не обязан торговать каждое заметное движение.",
        )
    elif format_id == "event_no_trade":
        heads = (
            f"{ticker} привлёк внимание, но чистой сделки здесь пока нет — и это нормально",
            f"По {ticker} событие есть; торговый план я бы пока не выжимал из него силой",
            f"{ticker}: активность стала выше, а хороший вход пока не появился",
            f"В {ticker} сейчас есть что наблюдать, но ещё нечего исполнять",
        )
        bodies = (
            f"За 5 минут {move5}, за 15 — {move15}; объём около {vol15} нормы.\n\nДля меня этого достаточно, чтобы держать тикер на экране, но недостаточно, чтобы выдумывать сделку. Следующая полезная проверка — район {level}.",
            f"Объём около {vol15} обычного, изменение за 15 минут {move15}.\n\nСейчас ценность скорее в наблюдении: если структура станет чище, вернусь к плану. Пока не заставляю рынок дать мне вход.",
            f"На коротком участке {move5}, объём около {vol5} нормы.\n\nЭто заметное изменение режима, но не готовый сигнал. Смотрю, сохранится ли активность около {level}.",
            f"15 минут: {move15}; объём около {vol15} нормы.\n\nСильнее всего здесь мне нравится возможность ничего не делать. Тикер интересный, сделка — пока нет.",
        )
    else:
        heads = (
            f"{ticker} сменил темп — пока это повод открыть график, а не нажать кнопку",
            f"В {ticker} появилось движение, которое стоит проверить ещё одной свечой",
            f"{ticker}: короткая активность выросла, но я пока читаю рынок, а не торгую его",
            f"По {ticker} сейчас интересен сам переход к более активному режиму",
        )
        bodies = (
            f"За 5 минут {move5}, за 15 — {move15}; объём около {vol15} нормы.\n\nСмотрю, сохранится ли этот темп возле {level}. Если нет — событие быстро потеряет для меня ценность.",
            f"На 15 минутах {move15}, короткий объём около {vol5} обычного.\n\nПока это наблюдение, а не готовый прогноз. Район {level} покажет больше, чем попытка догнать текущую свечу.",
            f"Свежие 5 минут дали {move5}, объём около {vol5} нормы.\n\nЕсли импульс быстро погаснет, ничего интересного не останется. Если рынок продолжит активно торговаться у {level}, вернусь к нему внимательнее.",
            f"Изменение за 15 минут {move15}; объём около {vol15} обычного.\n\nМне важен не сам размер свечи, а то, что активность изменилась прямо сейчас. Слежу за {level} без обязательства входить.",
        )

    text = heads[variant] + "\n\n" + bodies[variant]
    if plan_available and format_id == "event_trade_bridge" and levels is not None:
        entry = _fmt_price(levels["plan_entry"])
        tp1 = _fmt_price(levels["tp1"])
        stop = _fmt_price(levels["stop"])
        side = "LONG" if direction == "long" else "SHORT"
        text += f"\n\nЕсли захочу перевести наблюдение в {side}, готовый план у меня уже есть: вход около {entry}, TP1 {tp1}, стоп {stop}."
    return text


def generate_event_candidates(
    *,
    basic: str,
    mtf,
    direction: str,
    levels: Optional[Dict[str, Any]],
    memory: Optional[PostMemory],
    btc,
    attention: AttentionSnapshot,
    micro: MicroAttentionSnapshot,
    opportunity,
    monetization,
    variant_count: int = 12,
) -> List[GeneratedPost]:
    if mtf.tf_15m is None:
        return []
    count = max(4, min(int(variant_count), 18))
    formats = _format_rotation(memory, count)
    package = _semantic_package(
        basic=basic,
        mtf=mtf,
        direction=direction,
        levels=levels,
        btc=btc,
        attention=attention,
        micro=micro,
        opportunity=opportunity,
        monetization=monetization,
    )
    recent_posts = memory.recent_texts(10) if memory else []
    drafts: List[GeneratedPost] = []

    mode = _content_mode()
    if mode in {"ai_author", "ai_first", "ai", "mistral"} and _api_key():
        ai_formats = formats[: min(EVENT_AI_VARIANTS, len(formats))]
        for attempt in range(1, EVENT_AI_RETRIES + 1):
            try:
                raw_candidates = _request_ai_candidates(
                    package=package,
                    formats=ai_formats,
                    recent_posts=recent_posts,
                    attempt=attempt,
                )
            except Exception as exc:
                logger.warning("AI event-author attempt %s failed: %s", attempt, exc)
                break
            for raw in raw_candidates:
                fmt = str(raw.get("format_id", "")).strip()
                if fmt not in ai_formats or fmt not in EVENT_FORMAT_SPECS:
                    continue
                text = re.sub(r"\n{3,}", "\n\n", str(raw.get("text", "") or "").strip())
                valid, reasons = _validate_event_post(
                    text,
                    basic=basic,
                    direction=direction,
                    package=package,
                )
                if not valid:
                    logger.debug("Rejected AI event candidate %s: %s", fmt, "; ".join(reasons))
                    continue
                text, headline = _decorate_headline(
                    text,
                    format_id=fmt,
                    attention=attention,
                    micro=micro,
                    index=len(drafts),
                )
                draft = GeneratedPost(
                    text=text,
                    style_id=f"{str(raw.get('_provider', 'ai'))}_event_{fmt}_{len(drafts) % 5}",
                    signal_type=f"event_{opportunity.event_class}",
                    angle_title=str(opportunity.event_class).replace("_", " "),
                    content_format=fmt,
                    visual_style=EVENT_FORMAT_SPECS[fmt]["visual"],
                    headline=headline,
                    question_mode="optional",
                    source=("deepseek_event" if str(raw.get("_provider", "")) == "deepseek_v4_pro" else "mistral_event"),
                )
                if all(PostMemory.compare_texts(draft.text, item.text) < 0.78 for item in drafts):
                    drafts.append(draft)
            if len(drafts) >= min(3, len(ai_formats)):
                break

    # Safety net.  AI remains the preferred source, but one API hiccup must
    # not make the market scanner fragile.
    for index, fmt in enumerate(formats):
        if len(drafts) >= max(6, min(count, 14)):
            break
        raw = _deterministic_event_candidate(
            basic=basic,
            mtf=mtf,
            direction=direction,
            levels=levels,
            attention=attention,
            micro=micro,
            format_id=fmt,
            index=(len(memory.items) if memory else 0) + index,
        )
        valid, reasons = _validate_event_post(
            raw,
            basic=basic,
            direction=direction,
            package=package,
        )
        if not valid:
            logger.debug("Rejected deterministic event candidate %s: %s", fmt, "; ".join(reasons))
            continue
        raw, headline = _decorate_headline(
            raw,
            format_id=fmt,
            attention=attention,
            micro=micro,
            index=index + 23,
        )
        draft = GeneratedPost(
            text=raw,
            style_id=f"det_event_{fmt}_{index % 5}",
            signal_type=f"event_{opportunity.event_class}",
            angle_title=str(opportunity.event_class).replace("_", " "),
            content_format=fmt,
            visual_style=EVENT_FORMAT_SPECS[fmt]["visual"],
            headline=headline,
            question_mode="optional",
            source="deterministic_event",
        )
        if all(PostMemory.compare_texts(draft.text, item.text) < 0.78 for item in drafts):
            drafts.append(draft)
    return drafts


def event_conversion_score(text: str, basic: str, *, plan_available: bool) -> float:
    """Event-lane W2E proxy without pretending every post must be a signal."""
    clean = str(text or "").strip()
    lowered = clean.lower().replace("ё", "е")
    ticker = _ticker(basic)
    match = re.search(re.escape(ticker), clean, flags=re.IGNORECASE)
    discoverability = 100.0 if match and match.start() <= 80 else 72.0 if match else 0.0

    interest_markers = (
        "сейчас", "объём", "объем", "активност", "цена", "уров", "темп",
        "смотрю", "интерес", "график", "движ", "рынок", "наблюд",
    )
    interest = min(100.0, 40.0 + sum(marker in lowered for marker in interest_markers) * 6.0)

    decision_markers = (
        "для меня", "я бы", "смотрю", "не откры", "не торг", "пропущ",
        "пока", "если ", "без сделки", "чистой сделки",
    )
    decision = min(100.0, 38.0 + sum(marker in lowered for marker in decision_markers) * 7.0)
    if plan_available and any(marker in lowered for marker in ("long", "лонг", "short", "шорт", "tp1", "стоп")):
        decision = min(100.0, decision + 8.0)

    trust = 100.0
    if any(re.search(pattern, lowered, flags=re.IGNORECASE) for pattern in _FORBIDDEN_PATTERNS):
        trust -= 70.0
    if any(item in lowered for item in _ROBOTIC):
        trust -= 25.0
    if clean.count("!") >= 2:
        trust -= 12.0

    readability = 100.0
    if len(clean) > 520:
        readability -= min(35.0, (len(clean) - 520) / 4.0)
    if len(clean) < 160:
        readability -= min(20.0, (160 - len(clean)) / 3.0)

    score = discoverability * 0.34 + interest * 0.25 + decision * 0.18 + trust * 0.15 + readability * 0.08
    return round(max(0.0, min(100.0, score)), 2)


def event_quality_report(text: str, basic: str) -> QualityReport:
    appeal = FeedAppealEvaluator().report(text)
    clean = str(text or "").strip()
    lines = [line.strip() for line in clean.splitlines() if line.strip()]
    first = lines[0] if lines else ""
    ticker_ok = _ticker(basic).lower() in first.lower() if first else False
    length_ok = POST_MIN_CHARS <= len(clean) <= POST_MAX_CHARS
    hard_valid = ticker_ok and length_ok and not re.search(r"#[A-Za-zА-Яа-я0-9_]+", clean)

    headline_score = 100.0 if ticker_ok and 28 <= len(first) <= 125 else 72.0 if ticker_ok else 15.0
    readability = 100.0
    paragraphs = [part for part in clean.split("\n\n") if part.strip()]
    if len(paragraphs) < 2:
        readability -= 20.0
    if len(paragraphs) > 6:
        readability -= (len(paragraphs) - 6) * 7.0
    human = 78.0 + (12.0 if any(marker in clean.lower() for marker in ("я ", "мне", "для меня", "смотрю")) else 0.0)
    trust = 100.0 if not any(item in clean.lower() for item in _ROBOTIC) else 55.0
    score = (
        (100.0 if hard_valid else 45.0) * 0.18
        + headline_score * 0.17
        + max(25.0, readability) * 0.13
        + min(100.0, human) * 0.13
        + trust * 0.14
        + appeal.score * 0.25
    )
    reasons: Tuple[str, ...] = () if hard_valid else ("event hard validation",)
    return QualityReport(
        score=round(max(0.0, min(100.0, score)), 2),
        valid=hard_valid,
        reasons=reasons,
        components={
            "factual_contract": 100.0 if hard_valid else 45.0,
            "headline": headline_score,
            "readability": max(25.0, readability),
            "human_voice": min(100.0, human),
            "credibility": trust,
            "feed_appeal": appeal.score,
        },
    )


def rank_event_candidates(
    *,
    drafts: Sequence[GeneratedPost],
    basic: str,
    memory: PostMemory,
    min_feed_appeal: float,
    min_conversion: float,
    min_quality: float,
    max_similarity: float,
    plan_available: bool,
) -> Optional[Tuple[GeneratedPost, QualityReport]]:
    appeal_evaluator = FeedAppealEvaluator()
    recent_texts = memory.recent_texts(10)
    recent_formats = memory.get_last_content_formats(24)
    recent_visuals = memory.get_last_visual_styles(16)
    ranked: List[Tuple[float, GeneratedPost, QualityReport]] = []

    for draft in drafts:
        report = event_quality_report(draft.text, basic)
        appeal = appeal_evaluator.report(draft.text)
        conversion = event_conversion_score(draft.text, basic, plan_available=plan_available)
        similarity = memory.similarity_score(draft.text)
        phrase_pen = phrase_family_penalty(draft.text, recent_texts)
        novelty_pen = recent_formats.count(draft.content_format) * 1.7 + recent_visuals.count(draft.visual_style) * 0.8
        if recent_formats[-1:] == [draft.content_format]:
            novelty_pen += 5.0
        if recent_visuals[-1:] == [draft.visual_style]:
            novelty_pen += 2.0

        adjusted = (
            report.score * 0.45
            + appeal.score * 0.28
            + conversion * 0.27
            - max(0.0, similarity - 0.26) * 78.0
            - phrase_pen
            - min(12.0, novelty_pen)
        )
        logger.info(
            "Event copy candidate format=%s source=%s quality=%.1f appeal=%.1f conversion=%.1f similarity=%.3f adjusted=%.1f",
            draft.content_format, draft.source, report.score, appeal.score, conversion, similarity, adjusted,
        )
        if (
            report.valid
            and report.score >= min_quality
            and appeal.score >= min_feed_appeal
            and conversion >= min_conversion
            and similarity < max_similarity
        ):
            ranked.append((adjusted, draft, report))

    if not ranked:
        return None
    ranked.sort(key=lambda item: item[0], reverse=True)
    _, draft, report = ranked[0]
    return draft, report
