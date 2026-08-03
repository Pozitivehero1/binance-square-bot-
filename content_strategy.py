"""Editorial strategy for a non-repetitive Binance Square feed.

This module separates *what the post is trying to do* from the market signal.
A technical setup can therefore become a level story, a risk memo, a two-sided
scenario, a compact data brief or an educational note instead of every post
looking like the same LONG/SHORT alert.
"""
from __future__ import annotations

from dataclasses import dataclass
import os
import re
from typing import Dict, Iterable, List, Optional, Sequence


@dataclass(frozen=True)
class ContentFormat:
    id: str
    title: str
    family: str
    visual_style: str
    question_mode: str = "optional"  # required | optional | none
    weight: float = 1.0
    requires_btc: bool = False
    requires_previous_symbol: bool = False


CONTENT_FORMATS: Sequence[ContentFormat] = (
    ContentFormat("why_wait", "Почему я жду", "decision", "headline_card", "optional", 1.25),
    ContentFormat("level_story", "Один уровень решает всё", "level", "level_map", "optional", 1.20),
    ContentFormat("two_scenarios", "Два сценария", "scenario", "split_scenario", "required", 1.15),
    ContentFormat("risk_memo", "Риск-мемо", "risk", "risk_card", "none", 1.05),
    ContentFormat("trader_journal", "Запись трейдера", "personality", "journal_card", "optional", 1.15),
    ContentFormat("indicator_lesson", "Индикатор без магии", "education", "indicator_card", "required", 1.10),
    ContentFormat("market_context", "Сигнал в контексте рынка", "context", "context_chart", "optional", 1.00, requires_btc=True),
    ContentFormat("data_brief", "Короткий data-brief", "data", "data_card", "none", 0.95),
    ContentFormat("setup_plan", "Торговый план", "setup", "clean_chart", "optional", 0.90),
    ContentFormat("contrarian_take", "Неочевидный взгляд", "opinion", "headline_card", "required", 1.10),
    ContentFormat("mistake_to_avoid", "Ошибка, которую легко допустить", "education", "headline_card", "optional", 1.15),
    ContentFormat("execution_protocol", "Протокол исполнения", "process", "data_card", "none", 1.05),
    ContentFormat("signal_vs_trade", "Сигнал не равен сделке", "decision", "split_scenario", "required", 1.20),
    ContentFormat("liquidity_map", "Карта ликвидности", "level", "level_map", "optional", 1.10),
    ContentFormat("follow_up", "Продолжение прошлой идеи", "followup", "followup_card", "required", 1.30, requires_previous_symbol=True),
)

FORMAT_BY_ID = {item.id: item for item in CONTENT_FORMATS}


AUTHOR_VOICES = {
    "calm": {
        "label": "спокойный аналитик",
        "principle": "Я не угадываю свечу — жду подтверждение и заранее знаю точку ошибки.",
        "notes": (
            "Я не хочу покупать или продавать эмоцию; мне нужна реакция цены.",
            "Для меня отсутствие сделки лучше входа с испорченным риском.",
            "Я оцениваю не красоту графика, а то, насколько чётко рынок подтверждает план.",
            "Моя задача здесь — не быть первым, а войти там, где риск можно измерить.",
            "Я готов пропустить движение, если рынок не даст чистого подтверждения.",
            "Мне не нужна идеальная точка; нужна точка, где ошибка заранее ограничена.",
            "Я не оцениваю сценарий по одной свече — смотрю, удерживается ли структура после реакции.",
            "План остаётся рабочим только пока цена выполняет его условия, а не мои ожидания.",
        ),
    },
    "direct": {
        "label": "прямой трейдер",
        "principle": "Без подтверждения ордера нет. Уровень сломан — идея закрыта.",
        "notes": (
            "Я не догоняю эту свечу. Сначала рынок должен дать нормальную точку входа.",
            "Здесь всё просто: есть реакция — работаю, нет реакции — пропускаю.",
            "Плохой вход не становится хорошим только потому, что направление оказалось верным.",
            "Стоп не обсуждается после входа: он является частью сценария.",
            "Если цена не даёт подтверждение, кнопка остаётся нетронутой.",
            "Я не плачу рынку лишний риск за право войти чуть раньше.",
            "Сделка либо укладывается в план, либо её просто нет.",
            "Уровень сломан — спорить с графиком не собираюсь.",
        ),
    },
    "analytical": {
        "label": "системный аналитик",
        "principle": "Решение принимаю по совокупности структуры, импульса, объёма и риска.",
        "notes": (
            "Отдельный индикатор здесь ничего не решает; важна связка факторов.",
            "Я ищу не максимальную уверенность, а понятное соотношение подтверждения и риска.",
            "Для меня сценарий рабочий только пока данные не противоречат его основной логике.",
            "Сначала проверяю структуру, затем импульс и только потом точку исполнения.",
            "Сигнал для меня — это согласование факторов, а не один зелёный индикатор.",
            "Я отделяю направление от исполнения: правильная идея может иметь плохую цену входа.",
            "Решение появляется только после проверки уровня, объёма и старшего контекста.",
            "Если один из ключевых фильтров противоречит сценарию, размер позиции не компенсирует проблему.",
        ),
    },
    "contrarian": {
        "label": "контрарный наблюдатель",
        "principle": "Чем очевиднее выглядит движение, тем внимательнее я проверяю цену входа.",
        "notes": (
            "Самая опасная часть этого графика — то, насколько очевидным кажется направление.",
            "Я не спорю с трендом, но и не плачу рынку любую цену за вход.",
            "Когда всем хочется нажать кнопку сразу, я сначала ищу условие отмены.",
            "Сильная свеча привлекает внимание, но хороший вход обычно появляется после неё.",
            "Я особенно осторожен там, где направление кажется слишком очевидным.",
            "Погоня за ценой часто превращает верный анализ в плохую сделку.",
            "Чем громче импульс, тем важнее проверить, осталось ли место до цели.",
            "Я ищу слабое место сценария раньше, чем аргументы в его пользу.",
        ),
    },
}


def get_author_voice() -> Dict[str, object]:
    voice_id = os.getenv("AUTHOR_VOICE", "analytical").strip().lower()
    return AUTHOR_VOICES.get(voice_id, AUTHOR_VOICES["analytical"])


def author_note(index: int = 0) -> str:
    voice = get_author_voice()
    notes = voice["notes"]
    return notes[index % len(notes)]


def author_principle() -> str:
    return str(get_author_voice()["principle"])


def eligible_formats(*, has_btc: bool, has_previous_symbol: bool) -> List[ContentFormat]:
    result = []
    for item in CONTENT_FORMATS:
        if item.requires_btc and not has_btc:
            continue
        if item.requires_previous_symbol and not has_previous_symbol:
            continue
        result.append(item)
    return result


def rank_formats(
    recent_format_ids: Iterable[str],
    *,
    has_btc: bool,
    has_previous_symbol: bool,
) -> List[ContentFormat]:
    """Return eligible formats from least recently/repeated used to most used."""
    recent = [str(value) for value in recent_format_ids if value]
    frequency: Dict[str, int] = {}
    last_seen: Dict[str, int] = {}
    for position, format_id in enumerate(recent):
        frequency[format_id] = frequency.get(format_id, 0) + 1
        last_seen[format_id] = position

    formats = eligible_formats(has_btc=has_btc, has_previous_symbol=has_previous_symbol)
    return sorted(
        formats,
        key=lambda item: (
            frequency.get(item.id, 0) / max(item.weight, 0.1),
            last_seen.get(item.id, -1),
            item.id,
        ),
    )


def choose_formats(
    recent_format_ids: Iterable[str],
    count: int,
    *,
    has_btc: bool,
    has_previous_symbol: bool,
) -> List[ContentFormat]:
    ranked = rank_formats(
        recent_format_ids,
        has_btc=has_btc,
        has_previous_symbol=has_previous_symbol,
    )
    if not ranked:
        return [FORMAT_BY_ID["setup_plan"]]

    target = max(1, int(count))
    chosen: List[ContentFormat] = []
    used_ids: set[str] = set()
    used_visuals: set[str] = set()

    # First maximise visual diversity. With equal recency penalties this prevents
    # a candidate batch from containing several headline cards while omitting
    # scenario, journal or clean-chart layouts.
    for item in ranked:
        if item.visual_style in used_visuals:
            continue
        chosen.append(item)
        used_ids.add(item.id)
        used_visuals.add(item.visual_style)
        if len(chosen) >= target:
            return chosen

    # Then fill the remaining slots with the best-ranked unused formats.
    for item in ranked:
        if item.id in used_ids:
            continue
        chosen.append(item)
        used_ids.add(item.id)
        if len(chosen) >= target:
            return chosen

    # Requests may exceed the number of eligible formats. Cycle only then.
    index = 0
    while len(chosen) < target:
        chosen.append(ranked[index % len(ranked)])
        index += 1
    return chosen


def question_required(format_id: str) -> bool:
    item = FORMAT_BY_ID.get(format_id)
    return bool(item and item.question_mode == "required")


def question_forbidden(format_id: str) -> bool:
    item = FORMAT_BY_ID.get(format_id)
    return bool(item and item.question_mode == "none")


def visual_style_for(format_id: str) -> str:
    item = FORMAT_BY_ID.get(format_id)
    return item.visual_style if item else "clean_chart"


def headline_candidates(
    *,
    ticker: str,
    direction: str,
    format_id: str,
    key_level: str,
    risk_pct: str,
    reward_pct: str,
    rsi: float,
    adx: float,
    price_vs_vwap: str,
    angle_title: str,
) -> List[str]:
    """Build truthful, consequence-led first lines from code-controlled facts."""
    side = "LONG" if direction == "long" else "SHORT"
    action = "рост" if direction == "long" else "снижение"
    reverse_action = "падение" if direction == "long" else "отскок"

    by_format = {
        "why_wait": (
            f"{ticker}: {side} выглядит логично — но вход сейчас хуже самого сигнала",
            f"{ticker}: движение уже началось. Я не собираюсь его догонять",
            f"{ticker}: направление есть, нормальной точки входа пока нет",
        ),
        "level_story": (
            f"{ticker}: уровень {key_level} решит, продолжится ли {action}",
            f"{ticker} у ключевой границы: дальше рынок должен доказать сценарий",
            f"{ticker}: один уровень отделяет сетап от ложного движения",
        ),
        "two_scenarios": (
            f"{ticker}: два сценария, и только один даёт контролируемый вход",
            f"{ticker} на развилке: продолжение или возврат в диапазон",
            f"{ticker}: где подтверждается {side}, а где идея ломается",
        ),
        "risk_memo": (
            f"{ticker}: потенциальная цель {reward_pct}, риск до стопа {risk_pct}",
            f"{ticker}: сначала считаю риск, потом смотрю на направление",
            f"{ticker}: сильный сетап ничего не стоит без понятной точки ошибки",
        ),
        "trader_journal": (
            f"{ticker}: что я вижу на графике и почему пока не спешу",
            f"{ticker}: записываю план до того, как рынок включит эмоции",
            f"{ticker}: мой рабочий сценарий без попытки угадать свечу",
        ),
        "indicator_lesson": (
            f"{ticker}: почему RSI {rsi:.0f} сам по себе здесь ничего не решает",
            f"{ticker}: ADX {adx:.0f} подтверждает силу, но не точку входа",
            f"{ticker}: индикаторы дают направление, уровень даёт решение",
        ),
        "market_context": (
            f"{ticker}: хороший локальный сетап может сломать общий рынок",
            f"{ticker}: проверяю {side} не отдельно, а через фон BTC",
            f"{ticker}: старшие таймфреймы важнее красивой свечи на 15M",
        ),
        "data_brief": (
            f"{ticker}: коротко по цифрам — {angle_title.lower()}",
            f"{ticker}: данные за сетап без лишней истории",
            f"{ticker}: что реально подтверждает {side} прямо сейчас",
        ),
        "setup_plan": (
            f"{ticker}: готовый план на {side} с точкой отмены",
            f"{ticker}: сетап есть, но активируется только после подтверждения",
            f"{ticker}: вход, цели и стоп до открытия позиции",
        ),
        "contrarian_take": (
            f"{ticker}: очевидный {side} — не всегда хороший вход",
            f"{ticker}: чем сильнее выглядит {action}, тем опаснее догонять цену",
            f"{ticker}: главный риск сейчас — не {reverse_action}, а плохое исполнение",
        ),
        "mistake_to_avoid": (
            f"{ticker}: ошибка сейчас — спутать сильный сигнал с хорошим входом",
            f"{ticker}: где трейдер чаще всего портит этот сетап",
            f"{ticker}: правильное направление ещё не спасает от плохого исполнения",
        ),
        "execution_protocol": (
            f"{ticker}: четыре шага до открытия позиции {side}",
            f"{ticker}: протокол сделки без решений на эмоциях",
            f"{ticker}: что проверяю перед тем, как нажать кнопку",
        ),
        "signal_vs_trade": (
            f"{ticker}: сигнал уже есть, сделки пока нет",
            f"{ticker}: почему направление {side} ещё не означает вход",
            f"{ticker}: между анализом и ордером не хватает одного условия",
        ),
        "liquidity_map": (
            f"{ticker}: где цена ищет ликвидность и где ломается сценарий",
            f"{ticker}: карта уровней важнее прогноза следующей свечи",
            f"{ticker}: две границы, между которыми решается движение",
        ),
        "follow_up": (
            f"{ticker}: возвращаюсь к прошлой идее — структура уже изменилась",
            f"{ticker}: обновление сценария после нового движения цены",
            f"{ticker}: что осталось от прошлого плана и где теперь граница ошибки",
        ),
    }
    candidates = list(by_format.get(format_id, by_format["setup_plan"]))
    # Add one location-specific option. It stays factual because relation is code-controlled.
    candidates.append(f"{ticker}: цена {price_vs_vwap} VWAP, но решает реакция на уровне")
    return candidates


def choose_headline(candidates: Sequence[str], recent_titles: Iterable[str], index: int = 0) -> str:
    def signature(value: str) -> str:
        text = str(value).strip().lower().replace("ё", "е")
        text = re.sub(r"\$[a-z0-9]+", "$ticker", text)
        text = re.sub(r"\b\d+(?:[.,]\d+)?%?", "#", text)
        text = re.sub(r"\s+", " ", text)
        return text

    # Compare headline templates, not literal cashtags. Otherwise the same opening
    # can repeat for BTC, ETH and SOL while looking "new" to an exact-string check.
    used = {signature(title) for title in recent_titles if title}
    available = [item for item in candidates if signature(item) not in used]
    pool = available or list(candidates)
    return pool[index % len(pool)]
