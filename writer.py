"""Fact-locked Binance Square trade writer — v11.1 Outcome Integrity Engine.

Architecture:
    Python = analyst + risk manager
    DeepSeek V4 Pro (OrcaRouter) = primary author
    Mistral = API fallback only
    Python = validator / final editor

The AI receives a complete semantic package and writes the whole post from
scratch. Entry, stop, TP1/TP2/TP3 and every market number remain Python-owned.
Invalid drafts are rejected; deterministic copy is the final outage safety net.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import logging
import math
import os
import re
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from dotenv import load_dotenv

from attention import AttentionSnapshot, MicroAttentionSnapshot, format_turnover
from ai_provider import has_ai_provider, request_candidates
from content_variation import SignalAngle, detect_signal_angles
from memory import PostMemory
from trade_plan import build_public_trade_plan

load_dotenv()
logger = logging.getLogger(__name__)

POST_MAX_CHARS = int(os.getenv("POST_MAX_CHARS", "430"))
POST_MIN_CHARS = int(os.getenv("POST_MIN_CHARS", "220"))
EMOJI_RATE = max(0.0, min(float(os.getenv("EMOJI_RATE", "0.16")), 0.30))
QUESTION_EVERY = max(5, int(os.getenv("QUESTION_EVERY", "9")))
AI_VARIANTS = max(3, min(int(os.getenv("AI_VARIANTS", "6")), 10))
AI_RETRIES = max(1, min(int(os.getenv("AI_RETRIES", "2")), 3))
MIN_VALID_AI_DRAFTS = max(1, min(int(os.getenv("MIN_VALID_AI_DRAFTS", "2")), 6))
DETERMINISTIC_COMPARE_SLOTS = max(0, min(int(os.getenv("DETERMINISTIC_COMPARE_SLOTS", "0")), 3))
AI_TIMEOUT = max(10, min(int(os.getenv("AI_TIMEOUT", "55")), 120))
AI_TEMPERATURE = max(0.15, min(float(os.getenv("AI_TEMPERATURE", "0.70")), 0.85))

# Legacy style hint only. In v11.1 every valid public trade plan carries the full ladder.
FULL_PLAN_FORMATS: set[str] = set(FORMAT_SPECS) if False else {"trade_map", "risk_first"}

FORMAT_SPECS: Dict[str, Dict[str, str]] = {
    "hot_take": {
        "brief": "Живая реакция на событие. Начни с того, что реально удивляет или заставляет не спешить. 3-4 абзаца.",
        "visual": "event_chart",
    },
    "trade_map": {
        "brief": "Объясни наблюдаемый факт и условие сценария. Таблицу входа, стопа и целей добавит Python.",
        "visual": "trade_map",
    },
    "one_level": {
        "brief": "Сделай центром поста один переданный уровень. Объясни реакцию на него, без собственного блока торговых чисел.",
        "visual": "minimal_chart",
    },
    "no_chase": {
        "brief": "Контрарная заметка против позднего входа/FOMO. Не повторяй шаблон 'жду подтверждения'. Дай конкретный план.",
        "visual": "clean_chart",
    },
    "two_paths": {
        "brief": "Два условных исхода без гадания будущего. Один ведёт к сделке, второй отменяет идею.",
        "visual": "scenario_chart",
    },
    "risk_first": {
        "brief": "Начни с ограничения сценария: какое наблюдение его ослабляет. Полный торговый план добавит Python.",
        "visual": "trade_map",
    },
    "market_story": {
        "brief": "Расскажи, что изменилось в рынке и почему это стоит внимания. Затем коротко привяжи к сделке.",
        "visual": "context_chart",
    },
    "micro_note": {
        "brief": "Одна конкретная мысль из рыночного снимка и условие её проверки. Не дублируй торговые строки Python.",
        "visual": "minimal_chart",
    },
    "volume_read": {
        "brief": "Объём — только контекст, не главный герой. Объясни, что цена делает на фоне объёма, затем план.",
        "visual": "event_chart",
    },
}
FORMAT_ORDER = tuple(FORMAT_SPECS)


@dataclass(frozen=True)
class GeneratedPost:
    text: str
    style_id: str
    signal_type: str
    angle_title: str
    content_format: str = "hot_take"
    visual_style: str = "clean_chart"
    headline: str = ""
    question_mode: str = "optional"
    source: str = "deterministic"


def _fmt_price(value: float) -> str:
    price = float(value)
    absolute = abs(price)
    if absolute >= 1000:
        decimals = 1
    elif absolute >= 100:
        decimals = 1
    elif absolute >= 10:
        decimals = 2
    elif absolute >= 1:
        decimals = 3
    elif absolute >= 0.1:
        decimals = 4
    elif absolute >= 0.01:
        decimals = 5
    elif absolute >= 0.001:
        decimals = 6
    else:
        decimals = 8
    return f"{price:.{decimals}f}".rstrip("0").rstrip(".")


def _fmt_pct(value: float) -> str:
    value = float(value)
    return f"{value:+.1f}%" if abs(value) >= 1.0 else f"{value:+.2f}%"


def _fmt_x(value: float) -> str:
    value = max(0.0, float(value))
    return f"x{value:.1f}" if value >= 10 else f"x{value:.2f}"


def _fmt_x_human(value: float) -> str:
    return _fmt_x(value).replace(".", ",")


def _ticker(basic: str) -> str:
    return "$" + re.sub(r"[^A-Za-z0-9]", "", str(basic)).upper()


def _ticker_count(text: str, basic: str) -> int:
    pattern = rf"(?<![A-Za-z0-9_])\${re.escape(str(basic).upper())}(?![A-Za-z0-9_])"
    return len(re.findall(pattern, text.upper()))


def _price_in_text(text: str, value: float) -> bool:
    normalized = str(text or "").replace(",", ".")
    return _fmt_price(value).replace(",", ".") in normalized


def _full_plan_is_present(text: str, levels: Dict[str, Any], direction: str) -> bool:
    # Use the same strict contract as the Outcome journal so publication and
    # follow-up tracking can never disagree about what was visible to readers.
    try:
        from trade_journal import validate_public_plan_text
        return bool(validate_public_plan_text(text, levels, direction)[0])
    except Exception:
        return False


def _plan_block(levels: Dict[str, Any], direction: str, seed: str = "") -> str:
    side = direction.upper()
    low = _fmt_price(levels["entry_zone_low"])
    high = _fmt_price(levels["entry_zone_high"])
    stop = _fmt_price(levels["stop"])
    tp1 = _fmt_price(levels["tp1"])
    tp2 = _fmt_price(levels["tp2"])
    tp3 = _fmt_price(levels["tp3"])
    variants = (
        f"План {side}: вход {low}–{high} | стоп {stop}\nTP1 {tp1} | TP2 {tp2} | TP3 {tp3}",
        f"{side}-план: зона {low}–{high}, стоп {stop}\nЦели: TP1 {tp1} → TP2 {tp2} → TP3 {tp3}",
        f"Вход {side}: {low}–{high} · стоп {stop}\nФиксация: TP1 {tp1} / TP2 {tp2} / TP3 {tp3}",
        f"{side} только в зоне {low}–{high}; отмена на {stop}\nTP1 {tp1} · TP2 {tp2} · TP3 {tp3}",
    )
    token = hashlib.sha1(f"{seed}|{side}|{low}|{high}|{stop}".encode("utf-8")).hexdigest()
    return variants[int(token[:8], 16) % len(variants)]


def _fit_narrative_with_plan(text: str, block: str) -> str:
    base = re.sub(r"\n{3,}", "\n\n", str(text or "").strip())
    if len(base) + 2 + len(block) <= POST_MAX_CHARS:
        return f"{base}\n\n{block}".strip()
    budget = max(70, POST_MAX_CHARS - len(block) - 2)
    paragraphs = [part.strip() for part in base.split("\n\n") if part.strip()]
    kept: List[str] = []
    for paragraph in paragraphs:
        candidate = "\n\n".join([*kept, paragraph]) if kept else paragraph
        if len(candidate) <= budget:
            kept.append(paragraph)
        else:
            break
    narrative = "\n\n".join(kept).strip()
    if not narrative:
        cut = base[:budget].rstrip()
        for marker in (". ", "! ", "? ", "; ", ", "):
            pos = cut.rfind(marker)
            if pos >= max(35, budget // 2):
                cut = cut[: pos + 1]
                break
        narrative = cut.rstrip(" ,;:-") + "."
    return f"{narrative}\n\n{block}".strip()


def _enforce_full_plan_block(text: str, levels: Dict[str, Any], direction: str, *, seed: str = "") -> str:
    """Hard W2E/public-contract guard: every valid plan exposes entry, SL and TP1/2/3."""
    clean = re.sub(r"\n{3,}", "\n\n", str(text or "").strip())
    if _full_plan_is_present(clean, levels, direction):
        return clean
    from production_guard import strip_embedded_trade_plan
    clean = strip_embedded_trade_plan(clean)
    return _fit_narrative_with_plan(clean, _plan_block(levels, direction, seed or clean[:80]))


def _levels(ind, direction: str) -> Dict[str, Any]:
    return build_public_trade_plan(ind, direction)


def _decision_mode(levels: Dict[str, Any]) -> str:
    return str(levels.get("decision_mode", "at_level"))


def _event_strength(attention: Optional[AttentionSnapshot], micro: Optional[MicroAttentionSnapshot] = None) -> str:
    if attention is None:
        return "quiet"
    move = abs(float(attention.change_15m))
    micro_score = float(micro.score) if micro else 50.0
    if move >= 3.0 or (move >= 1.1 and micro_score >= 70) or attention.score >= 84:
        return "strong"
    if move >= 0.5 or attention.score >= 60:
        return "active"
    return "quiet"


def _maybe_decorate_headline(
    headline: str,
    *,
    format_id: str,
    attention: Optional[AttentionSnapshot],
    variant_index: int,
    micro: Optional[MicroAttentionSnapshot] = None,
) -> str:
    """Sparse, contextual accent: never more than one emoji."""
    if EMOJI_RATE <= 0 or any(mark in headline for mark in ("⚡", "⚠️", "👀")):
        return headline
    token = f"{headline}|{format_id}|{variant_index}".encode("utf-8")
    bucket = int(hashlib.sha1(token).hexdigest()[:8], 16) / 0xFFFFFFFF
    if bucket >= EMOJI_RATE:
        return headline
    strength = _event_strength(attention, micro)
    if format_id in {"one_level", "micro_note"}:
        emoji = "👀"
    elif format_id in {"no_chase", "risk_first"} and strength == "strong":
        emoji = "⚠️"
    elif attention and (attention.volume_spike >= 5.0 or (micro and micro.score >= 75)):
        emoji = "⚡"
    else:
        return headline
    return f"{emoji} {headline}"


def _apply_headline_decoration(
    text: str,
    *,
    format_id: str,
    attention: Optional[AttentionSnapshot],
    micro: Optional[MicroAttentionSnapshot],
    variant_index: int,
) -> Tuple[str, str]:
    parts = text.splitlines()
    first_index = next((i for i, line in enumerate(parts) if line.strip()), None)
    if first_index is None:
        return text, ""
    decorated = _maybe_decorate_headline(
        parts[first_index].strip(),
        format_id=format_id,
        attention=attention,
        variant_index=variant_index,
        micro=micro,
    )
    parts[first_index] = decorated
    return "\n".join(parts).strip(), decorated


def _api_key() -> str:
    return "configured" if has_ai_provider() else ""


def _content_mode() -> str:
    default = "ai_author" if _api_key() else "deterministic"
    return os.getenv("CONTENT_MODE", default).strip().lower()


def _clean_json(text: str) -> str:
    text = re.sub(r"^```(?:json)?\s*", "", text.strip(), flags=re.IGNORECASE)
    text = re.sub(r"\s*```$", "", text.strip())
    start = text.find("{")
    end = text.rfind("}")
    return text[start:end + 1] if start >= 0 and end > start else text


def _higher_tf_context(mtf, direction: str) -> str:
    items = []
    for label, ind in (("1H", getattr(mtf, "tf_1h", None)), ("4H", getattr(mtf, "tf_4h", None)), ("1D", getattr(mtf, "tf_1d", None))):
        if ind is None:
            continue
        aligned = ind.ema20 > ind.ema50 if direction == "long" else ind.ema20 < ind.ema50
        items.append(f"{label}:{'за' if aligned else 'против'}")
    return ", ".join(items) if items else "нет данных"


def _state_instruction(levels: Dict[str, Any], direction: str) -> str:
    mode = _decision_mode(levels)
    if mode == "at_level":
        return "Цена уже у рабочей зоны. Нельзя писать, что будущий ретест ещё должен состояться; говори об удержании/реакции сейчас."
    if mode == "retest_hold":
        return "Цена выше рабочей зоны. Допустимо условно говорить о возврате/ретесте зоны и удержании для LONG."
    if mode == "retest_reject":
        return "Цена ниже рабочей зоны. Допустимо условно говорить о возврате/ретесте зоны и отказе от роста для SHORT."
    if mode == "breakout_confirm":
        return "Цена ещё ниже уровня входа для LONG. Нужен условный пробой/закрепление выше; не называй это ретестом."
    if mode == "breakdown_confirm":
        return "Цена ещё выше уровня входа для SHORT. Нужен условный пробой/закрепление ниже; не называй это ретестом."
    return f"Пиши только условно о сценарии {direction.upper()}, не предсказывай будущее."


def _semantic_package(
    *,
    basic: str,
    mtf,
    direction: str,
    levels: Dict[str, Any],
    btc,
    attention: Optional[AttentionSnapshot],
    micro: Optional[MicroAttentionSnapshot],
    opportunity,
    monetization,
) -> Dict[str, Any]:
    ind = mtf.tf_15m
    ticker = _ticker(basic)
    entry = _fmt_price(levels["plan_entry"])
    zone_low = _fmt_price(levels["entry_zone_low"])
    zone_high = _fmt_price(levels["entry_zone_high"])
    stop = _fmt_price(levels["stop"])
    tp1 = _fmt_price(levels["tp1"])
    tp2 = _fmt_price(levels["tp2"])
    tp3 = _fmt_price(levels["tp3"])

    market: Dict[str, Any] = {
        "ticker": ticker,
        "current_price": _fmt_price(ind.price),
        "change_15m": _fmt_pct(attention.change_15m) if attention else _fmt_pct(ind.change_1h / 4.0),
        "change_45m": _fmt_pct(attention.change_45m) if attention else _fmt_pct(ind.change_1h * 0.75),
        "relative_volume_15m": _fmt_x(attention.volume_spike) if attention else _fmt_x(ind.volume_relative),
        "turnover_1h": format_turnover(attention.turnover_1h) if attention else "n/a",
        "rsi_15m": f"{ind.rsi:.1f}",
        "adx_15m": f"{ind.adx:.1f}",
        "price_vs_vwap": "выше" if ind.price >= ind.vwap else "ниже",
        "higher_timeframes": _higher_tf_context(mtf, direction),
        "overextended": bool(attention.overextended) if attention else False,
    }
    if micro:
        market.update({
            "change_5m": _fmt_pct(micro.change_5m),
            "relative_volume_5m": _fmt_x(micro.volume_spike_5m),
            "micro_freshness": f"{micro.score:.0f}/100",
            "event_phase": micro.phase,
        })
    if opportunity is not None:
        market.update({
            "audience_demand": f"{float(opportunity.audience_demand):.0f}/100",
            "event_class": str(opportunity.event_class),
        })
    if monetization is not None:
        market["w2e_market_score"] = f"{float(monetization.score):.0f}/100"
    if btc is not None:
        market["btc_context"] = {
            "bias": str(btc.bias),
            "change_1h": _fmt_pct(btc.change_1h),
            "change_4h": _fmt_pct(btc.change_4h),
        }

    trade = {
        "direction": direction.upper(),
        "trade_state": str(levels.get("trade_state", "waiting_confirmation")),
        "decision_mode": _decision_mode(levels),
        "entry": entry,
        "entry_zone": [zone_low, zone_high],
        "stop_loss": stop,
        "tp1": tp1,
        "tp2": tp2,
        "tp3": tp3,
        "rr_tp1": f"{float(levels.get('rr_tp1', 0.0)):.2f}",
        "rr_tp2": f"{float(levels.get('rr_tp2', 0.0)):.2f}",
        "rr_tp3": f"{float(levels.get('rr_tp3', levels.get('public_rr', 0.0))):.2f}",
        "risk_pct": f"{float(levels.get('public_risk_pct', 0.0)):.2f}%",
        "state_rule": _state_instruction(levels, direction),
    }
    return {"market": market, "trade_plan": trade}


def _recent_phrase_families(text: str) -> set[str]:
    lowered = text.lower().replace("ё", "е")
    families = set()
    mapping = {
        "confirmation": ("подтвержд", "закреп"),
        "waiting": ("не спеш", "подожд", "жду ", "дожд"),
        "level_control": ("кто удерж", "удержание", "удержит", "удержат"),
        "chase": ("не догон", "fomo", "вслед за свеч"),
        "mistake": ("ошибка", "ловушка"),
        "one_level": ("всё решает", "один уровень", "одна цена"),
        "no_forecast": ("не нужен прогноз", "не угады"),
        "signal_not_trade": ("сигнал", "ещё не сделк", "пока наблюдени"),
        "volume_hook": ("объём", "объем"),
    }
    for name, markers in mapping.items():
        if any(marker in lowered for marker in markers):
            families.add(name)
    return families


def phrase_family_penalty(text: str, recent_texts: Sequence[str]) -> float:
    current = _recent_phrase_families(text)
    if not current or not recent_texts:
        return 0.0
    recent_sets = [_recent_phrase_families(item) for item in recent_texts[-10:]]
    penalty = 0.0
    for family in current:
        hits = sum(family in item for item in recent_sets)
        if hits >= 3:
            penalty += min(9.0, (hits - 2) * 2.4)
    first = next((line.strip() for line in text.splitlines() if line.strip()), "")
    if recent_texts:
        recent_first = next((line.strip() for line in recent_texts[-1].splitlines() if line.strip()), "")
        if first and recent_first and PostMemory.compare_texts(first, recent_first) >= 0.55:
            penalty += 7.0
    return min(22.0, penalty)


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
    # x-volume is extracted explicitly; plain numbers preceded by letters are
    # ignored so TP1/TP2/TP3 labels do not look like fabricated market facts.
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


def _numeric_tokens(text: str) -> List[str]:
    return _extract_numeric_tokens(text)

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


def _validate_ai_post(
    text: str,
    *,
    basic: str,
    direction: str,
    levels: Dict[str, Any],
    package: Dict[str, Any],
    format_id: str,
) -> Tuple[bool, Tuple[str, ...]]:
    reasons: List[str] = []
    text = str(text or "").strip()
    from production_guard import final_text_reasons
    from fact_consistency import fact_consistency_reasons
    reasons.extend(final_text_reasons(text))
    reasons.extend(fact_consistency_reasons(text, package))
    lowered = text.lower().replace("ё", "е")
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    first = lines[0] if lines else ""

    if not first or _ticker(basic).lower() not in first.lower():
        reasons.append("ticker missing from headline")
    if not 1 <= _ticker_count(text, basic) <= 2:
        reasons.append("ticker count")
    if not POST_MIN_CHARS <= len(text) <= POST_MAX_CHARS:
        reasons.append(f"length {len(text)}")
    if len(first) > 130:
        reasons.append("headline too long")

    expected = ("long", "лонг") if direction == "long" else ("short", "шорт")
    opposite = ("short", "шорт") if direction == "long" else ("long", "лонг")
    if not any(term in lowered for term in expected):
        reasons.append("missing direction")
    if any(re.search(rf"\b{term}\b", lowered) for term in opposite):
        reasons.append("opposite direction")

    # v11.1 hard public-plan contract: if Python marks a plan valid, the reader
    # must see direction + entry context + stop + all three targets in the text.
    entry_values = {
        _fmt_price(levels["plan_entry"]),
        _fmt_price(levels["entry_zone_low"]),
        _fmt_price(levels["entry_zone_high"]),
    }
    normalized_text = text.replace(",", ".")
    if not any(value.replace(",", ".") in normalized_text for value in entry_values):
        reasons.append("missing entry context")
    if _fmt_price(levels["stop"]).replace(",", ".") not in normalized_text:
        reasons.append("missing stop")
    for name in ("tp1", "tp2", "tp3"):
        if _fmt_price(levels[name]).replace(",", ".") not in normalized_text:
            reasons.append(f"missing {name.upper()}")

    if text.count("?") > 1:
        reasons.append("too many questions")
    if len(re.findall(r"#[A-Za-zА-Яа-я0-9_]+", text)) > 0:
        reasons.append("hashtags forbidden")
    if len(re.findall(r"[\U0001F300-\U0001FAFF\u2600-\u27BF]", text)) > 1:
        reasons.append("too many emojis")
    if any(item in lowered for item in _ROBOTIC):
        reasons.append("robotic wording")
    if any(re.search(pattern, lowered, flags=re.IGNORECASE) for pattern in _FORBIDDEN_PATTERNS):
        reasons.append("unsupported/pushy claim")
    if any(re.search(pattern, lowered, flags=re.IGNORECASE) for pattern in _PREDICTIVE_PATTERNS):
        reasons.append("predictive claim")

    mode = _decision_mode(levels)
    if mode in {"at_level", "breakout_confirm", "breakdown_confirm"} and any(
        token in lowered for token in ("ретест", "после отката", "на откате", "возврат к уровню")
    ):
        reasons.append("retest conflicts with state")

    allowed = _allowed_numeric_values(package)
    unexpected = set(_numeric_tokens(text)) - allowed
    if unexpected:
        reasons.append("unexpected numbers: " + ",".join(sorted(unexpected)))

    return not reasons, tuple(reasons)


def _format_rotation(memory: Optional[PostMemory], count: int) -> List[str]:
    recent = memory.get_last_content_formats(18) if memory else []
    frequency = {fmt: recent.count(fmt) for fmt in FORMAT_ORDER}
    last = recent[-1] if recent else ""
    ranked = sorted(
        FORMAT_ORDER,
        key=lambda fmt: (frequency.get(fmt, 0) + (3 if fmt == last else 0), FORMAT_ORDER.index(fmt)),
    )
    out: List[str] = []
    while len(out) < count:
        for fmt in ranked:
            if len(out) >= count:
                break
            out.append(fmt)
    return out


def _visual_for(format_id: str, memory: Optional[PostMemory], index: int) -> str:
    preferred = FORMAT_SPECS.get(format_id, {}).get("visual", "clean_chart")
    recent = memory.get_last_visual_styles(5) if memory else []
    alternatives = [preferred, "minimal_chart", "event_chart", "clean_chart", "context_chart", "trade_map", "scenario_chart"]
    unique = []
    for item in alternatives:
        if item not in unique:
            unique.append(item)
    if recent and preferred == recent[-1]:
        for item in unique:
            if item != recent[-1] and recent.count(item) <= recent.count(preferred):
                return item
    return unique[index % len(unique)] if index >= len(FORMAT_ORDER) else preferred


def _request_ai_candidates(
    *,
    package: Dict[str, Any],
    formats: Sequence[str],
    recent_posts: Sequence[str],
    attempt: int,
) -> List[dict]:
    if not has_ai_provider():
        return []

    format_briefs = [{"format_id": fmt, "brief": FORMAT_SPECS[fmt]["brief"]} for fmt in formats]
    payload = {
        "task": "Напиши готовые посты для Binance Square. Не редактируй шаблон — каждый текст придумай с нуля по фактам.",
        "semantic_package": package,
        "formats_in_order": format_briefs,
        "recent_posts_to_avoid": [str(item)[:650] for item in recent_posts[-8:]],
        "attempt": attempt,
        "rules": [
            "Пиши на русском как живой практикующий трейдер. Без канцелярита и без одинакового ритма абзацев.",
            "Первая строка: cashtag и конкретное изменение рынка. Никаких вводных о том, как важно иметь план.",
            "Текст объясняет наблюдаемый факт, его ограничение и условие сценария. Не описывай собственную торговлю или прибыль.",
            "Используй только числа из semantic_package и не пересчитывай их. Можно использовать запятую вместо точки в десятичной дроби.",
            "Направление, entry, entry_zone, stop_loss, TP1/TP2/TP3 заданы Python и не могут быть изменены.",
            "Напиши только вступление и объяснение события. НЕ пиши строки входа, стопа и TP: Python добавит полный план сам.",
            "Обязательно включи хотя бы один конкретный рыночный факт из market с его периодом. Никаких общих советов вместо события.",
            "Не утверждай будущее. Только условия: если/пока/при закреплении/при потере уровня.",
            "Следуй trade_plan.state_rule. Если цена уже у уровня, не обещай будущий ретест этого же уровня.",
            "Не используй штампы: 'направление идеи', 'граница ошибки', 'диапазон контроля', 'параметры сценария'.",
            "Не выпрашивай лайки, комментарии, подписки, донаты или чаевые и не упоминай Write to Earn/вознаграждение автора.",
            "Не заканчивай каждый пост вопросом. В этой партии вопрос допустим максимум в одном варианте.",
            "Не добавляй хэштеги и эмодзи. Код сам решит, нужен ли один визуальный акцент.",
            "Длина авторской части 150–240 символов, 2 коротких абзаца. Полный план будет добавлен программой.",
            "Не ссылайся на новости, китов, инсайды, ликвидации или причины движения, если их нет в semantic_package.",
            "Не копируй синтаксис, открывающие фразы и смысловую композицию recent_posts_to_avoid.",
        ],
        "json_shape": {
            "candidates": [
                {"format_id": formats[0] if formats else "hot_take", "text": "готовый многоабзацный пост"}
            ]
        },
    }
    result = request_candidates(
        system_prompt=(
            "Ты автор трейдерского аккаунта Binance Square. Твоя задача — живой, разнообразный, полезный текст, "
            "который помогает читателю понять сделку. Все торговые числа уже рассчитаны программой: никогда не меняй их "
            "и не придумывай новые. Не обещай доходность, не дави на читателя и не проси донаты/лайки/комментарии. "
            "Верни только валидный JSON."
        ),
        user_payload=payload,
        temperature=AI_TEMPERATURE,
        max_tokens=3200,
        timeout=AI_TIMEOUT,
        presence_penalty=0.55,
        frequency_penalty=0.45,
    )
    return result.candidates


def _natural_state_line(levels: Dict[str, Any], direction: str, variant: int) -> str:
    entry = _fmt_price(levels["plan_entry"])
    mode = _decision_mode(levels)
    if direction == "long":
        lines = {
            "at_level": (f"Сейчас цена уже у {entry}; мне важна реакция покупателей здесь.", f"{entry} уже в игре — дальше смотрю на удержание этой зоны."),
            "retest_hold": (f"Цена выше {entry}; на возврате к зоне хочу увидеть покупателей.", f"Для меня интересен откат к {entry}, но только если уровень не отдадут."),
            "breakout_confirm": (f"Пока цена ниже {entry}, LONG для меня не активирован.", f"Для LONG сначала нужна устойчивость выше {entry}."),
        }
        pool = lines.get(mode, lines["at_level"])
    else:
        lines = {
            "at_level": (f"Сейчас цена уже у {entry}; мне важна реакция продавцов здесь.", f"{entry} уже в игре — дальше смотрю, останется ли цена под зоной."),
            "retest_reject": (f"Цена ниже {entry}; на возврате к зоне хочу увидеть продавцов.", f"Для меня интересен возврат к {entry}, если выше не пустят."),
            "breakdown_confirm": (f"Пока цена выше {entry}, SHORT для меня не активирован.", f"Для SHORT сначала нужна устойчивость ниже {entry}."),
        }
        pool = lines.get(mode, lines["at_level"])
    return pool[variant % len(pool)]


def _trade_sentences(
    direction: str,
    key_level: str,
    levels: Dict[str, Any],
    attention: Optional[AttentionSnapshot],
    variant_index: int,
    format_id: str = "",
) -> Tuple[str, str]:
    """Backward-compatible compact plan sentence used by tests/fallback copy."""
    del attention, format_id
    target = _fmt_price(levels["tp1"])
    stop = _fmt_price(levels["stop"])
    mode = _decision_mode(levels)
    if direction == "long":
        if mode == "retest_hold":
            entry = f"Если на возврате к {key_level} покупателей хватит — LONG смотрю к {target}."
        elif mode == "breakout_confirm":
            entry = f"Если цена закрепится выше {key_level} — LONG смотрю к {target}."
        else:
            entry = f"Если {key_level} удержат сейчас — LONG смотрю к {target}."
        invalid = (f"Стоп — {stop}.", f"Ниже {stop} идею LONG закрываю.")[variant_index % 2]
    else:
        if mode == "retest_reject":
            entry = f"Если возврат к {key_level} продавцы встретят — SHORT смотрю к {target}."
        elif mode == "breakdown_confirm":
            entry = f"Если цена закрепится ниже {key_level} — SHORT смотрю к {target}."
        else:
            entry = f"Если цена останется ниже {key_level} — SHORT смотрю к {target}."
        invalid = (f"Стоп — {stop}.", f"Выше {stop} идею SHORT закрываю.")[variant_index % 2]
    return entry, invalid


def _deterministic_candidate(
    *,
    basic: str,
    mtf,
    direction: str,
    levels: Dict[str, Any],
    attention: Optional[AttentionSnapshot],
    micro: Optional[MicroAttentionSnapshot],
    format_id: str,
    index: int,
) -> str:
    from factual_copy import market_narrative

    ind = mtf.tf_15m
    plan_available = bool(levels and levels.get("plan_valid", False))
    text = market_narrative(
        ticker=_ticker(basic),
        move5=micro.change_5m if micro else None,
        move15=attention.change_15m if attention else ind.change_1h / 4.0,
        volume5=micro.volume_spike_5m if micro else None,
        volume15=attention.volume_spike if attention else ind.volume_relative,
        price=ind.price,
        level=levels["plan_entry"],
        plan_available=plan_available,
        direction=direction,
        decision_mode=str((levels or {}).get("decision_mode", "at_level")),
        index=index,
    )
    if plan_available:
        text = _enforce_full_plan_block(text, levels, direction, seed=f"facts|{format_id}|{index}")
    return text


def _build_generated(
    *,
    raw_text: str,
    basic: str,
    direction: str,
    levels: Dict[str, Any],
    package: Dict[str, Any],
    format_id: str,
    visual_style: str,
    angle: SignalAngle,
    index: int,
    attention: Optional[AttentionSnapshot],
    micro: Optional[MicroAttentionSnapshot],
    source: str,
) -> Optional[GeneratedPost]:
    text = re.sub(r"[ \t]+\n", "\n", str(raw_text or "").strip())
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = _enforce_full_plan_block(text, levels, direction, seed=f"{source}|{format_id}|{index}")
    valid, reasons = _validate_ai_post(
        text,
        basic=basic,
        direction=direction,
        levels=levels,
        package=package,
        format_id=format_id,
    )
    if not valid:
        logger.debug("Rejected %s writer candidate %s: %s", source, format_id, "; ".join(reasons))
        return None
    text, headline = _apply_headline_decoration(
        text,
        format_id=format_id,
        attention=attention,
        micro=micro,
        variant_index=index,
    )
    return GeneratedPost(
        text=text,
        style_id=f"{source}_{format_id}_{index % 5}",
        signal_type=angle.id,
        angle_title=angle.title,
        content_format=format_id,
        visual_style=visual_style,
        headline=headline,
        question_mode="optional",
        source=source,
    )


def generate_post_candidates(
    *,
    symbol: str,
    basic: str,
    mtf,
    score,
    memory: Optional[PostMemory] = None,
    levels: Optional[Dict[str, Any]] = None,
    btc=None,
    attention: Optional[AttentionSnapshot] = None,
    micro: Optional[MicroAttentionSnapshot] = None,
    opportunity=None,
    monetization=None,
    variant_count: int = 12,
) -> List[GeneratedPost]:
    del symbol
    ind = mtf.tf_15m
    if ind is None:
        return []
    levels = levels or _levels(ind, score.direction)
    if not levels.get("plan_valid", False):
        return []

    angles = detect_signal_angles(ind, score.direction, mtf)
    if not angles:
        return []
    formats = _format_rotation(memory, max(1, min(int(variant_count), 24)))
    package = _semantic_package(
        basic=basic,
        mtf=mtf,
        direction=score.direction,
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
        ai_formats = formats[: min(AI_VARIANTS, len(formats))]
        for attempt in range(1, AI_RETRIES + 1):
            try:
                raw_candidates = _request_ai_candidates(
                    package=package,
                    formats=ai_formats,
                    recent_posts=recent_posts,
                    attempt=attempt,
                )
            except Exception as exc:
                logger.warning("AI author attempt %s failed: %s", attempt, exc)
                continue

            for raw in raw_candidates:
                fmt = str(raw.get("format_id", "")).strip()
                if fmt not in ai_formats or fmt not in FORMAT_SPECS:
                    continue
                text = str(raw.get("text", "") or "").strip()
                index = len(drafts)
                angle = angles[index % min(len(angles), 6)]
                generated = _build_generated(
                    raw_text=text,
                    basic=basic,
                    direction=score.direction,
                    levels=levels,
                    package=package,
                    format_id=fmt,
                    visual_style=_visual_for(fmt, memory, index),
                    angle=angle,
                    index=index,
                    attention=attention,
                    micro=micro,
                    source=("deepseek" if str(raw.get("_provider", "")) == "deepseek_v4_pro" else "mistral"),
                )
                if generated and all(PostMemory.compare_texts(generated.text, item.text) < 0.78 for item in drafts):
                    drafts.append(generated)
            if len(drafts) >= min(3, len(ai_formats)):
                break

    # Deterministic copy is an outage fallback, not a co-equal author. When the
    # AI pool is healthy, honour DETERMINISTIC_COMPARE_SLOTS (zero in production)
    # instead of quietly filling half the ranking pool with weaker templates.
    target_count = max(6, min(int(variant_count), 24))
    healthy_ai_pool = len(drafts) >= MIN_VALID_AI_DRAFTS
    deterministic_limit = DETERMINISTIC_COMPARE_SLOTS if healthy_ai_pool else target_count
    deterministic_added = 0
    for index, fmt in enumerate(formats):
        if len(drafts) >= target_count or deterministic_added >= deterministic_limit:
            break
        angle = angles[(index + len(drafts)) % min(len(angles), 6)]
        fallback_seed = (len(memory.items) * 7 if memory else 0) + index
        text = _deterministic_candidate(
            basic=basic,
            mtf=mtf,
            direction=score.direction,
            levels=levels,
            attention=attention,
            micro=micro,
            format_id=fmt,
            index=fallback_seed,
        )
        generated = _build_generated(
            raw_text=text,
            basic=basic,
            direction=score.direction,
            levels=levels,
            package=package,
            format_id=fmt,
            visual_style=_visual_for(fmt, memory, index),
            angle=angle,
            index=index + 17,
            attention=attention,
            micro=micro,
            source="deterministic",
        )
        if generated and all(PostMemory.compare_texts(generated.text, item.text) < 0.80 for item in drafts):
            drafts.append(generated)
            deterministic_added += 1

    return drafts[:target_count]


def generate_post_draft(**kwargs) -> Optional[GeneratedPost]:
    drafts = generate_post_candidates(**kwargs, variant_count=1)
    return drafts[0] if drafts else None


def generate_post_with_memory(**kwargs) -> str:
    draft = generate_post_draft(**kwargs)
    return draft.text if draft else ""
