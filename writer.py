"""Fact-based Binance Square post generator with meaningful content diversity."""
from __future__ import annotations

from dataclasses import dataclass
import logging
import os
import random
import re
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

import requests

from content_variation import (
    CTA_VARIANTS,
    PLAN_TITLES,
    PostStyle,
    SignalAngle,
    choose,
    choose_post_style,
    choose_signal_angle,
    hashtags as varied_hashtags,
    HUMAN_HOOKS,
    PERSONAL_PHRASES,
)
from indicators import build_trade_levels
from memory import PostMemory

logger = logging.getLogger(__name__)

MISTRAL_API = os.getenv("MISTRAL_API", "").strip()
ENABLE_AI_POLISH = os.getenv("ENABLE_AI_POLISH", "0").strip().lower() in {"1", "true", "yes"}
POST_MAX_CHARS = int(os.getenv("POST_MAX_CHARS", "1600"))


@dataclass(frozen=True)
class GeneratedPost:
    text: str
    style_id: str
    signal_type: str
    angle_title: str


# ---------------------------------------------------------------------------
# Formatting and levels
# ---------------------------------------------------------------------------
def _fmt_price(value: float) -> str:
    price = float(value)
    absolute = abs(price)
    if absolute >= 1000:
        return f"{price:.2f}"
    if absolute >= 1:
        return f"{price:.4f}".rstrip("0").rstrip(".")
    if absolute >= 0.01:
        return f"{price:.6f}".rstrip("0").rstrip(".")
    return f"{price:.10f}".rstrip("0").rstrip(".")


def _levels(ind, direction: str) -> Dict[str, float]:
    return build_trade_levels(ind, direction)


def _format_ticker(basic: str) -> str:
    clean = re.sub(r"[^A-Za-z0-9]", "", str(basic)).upper()
    return f"${clean}"


def _fix_ticker_spacing(text: str) -> str:
    text = re.sub(r"(\$[A-Z0-9]{2,15})[,:;.!?]", r"\1", text)
    text = re.sub(r"\$[A-Z0-9]{2,15}", lambda match: match.group(0).replace(" ", ""), text)
    return text


def _mandatory_values(levels: Dict[str, float]) -> List[str]:
    return [
        _fmt_price(levels["entry"]),
        _fmt_price(levels["tp1"]),
        _fmt_price(levels["tp2"]),
        _fmt_price(levels["tp3"]),
        _fmt_price(levels["stop"]),
        f"{levels['risk_reward']:.2f}",
    ]


def _contains_required_content(text: str, levels: Dict[str, float]) -> bool:
    labels = ("Вход", "TP1", "TP2", "TP3", "Стоп", "R/R")
    return all(label.lower() in text.lower() for label in labels) and all(
        value in text for value in _mandatory_values(levels)
    )


def _pick_unused(options: Sequence[str], used: Iterable[str]) -> str:
    normalized_used = {PostMemory.normalize_text(item) for item in used if item}
    available = [item for item in options if PostMemory.normalize_text(item) not in normalized_used]
    return random.choice(available or list(options))


# ---------------------------------------------------------------------------
# Market facts
# ---------------------------------------------------------------------------
def _direction_terms(direction: str) -> Tuple[str, str, str, str]:
    if direction == "long":
        return "LONG", "выше", "ниже", "покупателей"
    return "SHORT", "ниже", "выше", "продавцов"


def _higher_tf_context(mtf, direction: str) -> Tuple[str, int, int]:
    labels: List[str] = []
    aligned_count = 0
    total = 0
    for label, indicator in (("1H", mtf.tf_1h), ("4H", mtf.tf_4h), ("1D", mtf.tf_1d)):
        if indicator is None:
            continue
        total += 1
        aligned = indicator.ema20 > indicator.ema50 if direction == "long" else indicator.ema20 < indicator.ema50
        aligned_count += int(aligned)
        labels.append(f"{label} {'✓' if aligned else '×'}")
    return (" · ".join(labels) if labels else "нет данных старших ТФ", aligned_count, total)


def _btc_context_text(btc, direction: str) -> str:
    if btc is None:
        return "Контекст BTC сейчас недоступен — решение строится только по структуре актива."
    compatible = (
        btc.bias == "neutral"
        or (btc.bias == "bullish" and direction == "long")
        or (btc.bias == "bearish" and direction == "short")
    )
    relation = "поддерживает направление" if compatible else "требует дополнительного подтверждения"
    return (
        f"BTC: {btc.bias}, 1H {btc.change_1h:+.2f}%, 4H {btc.change_4h:+.2f}% — "
        f"фон {relation}."
    )


def _market_metrics(ind) -> Dict[str, str]:
    atr_pct = ind.atr / ind.price * 100.0 if ind.price else 0.0
    return {
        "price": _fmt_price(ind.price),
        "change_1h": f"{ind.change_1h:+.2f}%",
        "change_4h": f"{ind.change_4h:+.2f}%",
        "change_24h": f"{ind.change_24h:+.2f}%",
        "volume": f"x{ind.volume_relative:.2f}",
        "rsi": f"{ind.rsi:.1f}",
        "adx": f"{ind.adx:.1f}",
        "atr_pct": f"{atr_pct:.2f}%",
        "vwap": _fmt_price(ind.vwap),
        "ema20": _fmt_price(ind.ema20),
        "ema50": _fmt_price(ind.ema50),
        "support": _fmt_price(ind.support),
        "resistance": _fmt_price(ind.resistance),
    }


def _angle_content(angle: SignalAngle, ind, direction: str, mtf) -> Dict[str, str]:
    ticker_side, supportive_side, failure_side, participants = _direction_terms(direction)
    metrics = _market_metrics(ind)
    higher_tf, aligned, total = _higher_tf_context(mtf, direction)
    key_level = ind.resistance if direction == "long" else ind.support
    opposite_level = ind.support if direction == "long" else ind.resistance

    default = {
        "hook": f"Рынок формирует {ticker_side}-сценарий у {_fmt_price(key_level)}",
        "thesis": (
            f"Цена находится {supportive_side} EMA20, MACD-гистограмма поддерживает направление, "
            f"а ADX {metrics['adx']} показывает наличие трендового движения."
        ),
        "evidence": (
            f"RSI {metrics['rsi']} · объём {metrics['volume']} · VWAP {metrics['vwap']} · "
            f"старшие ТФ: {higher_tf}."
        ),
        "confirmation": f"Подтверждение — удержание цены {supportive_side} {_fmt_price(key_level)}.",
        "failure": f"Слабость проявится при возврате {failure_side} {_fmt_price(opposite_level)}.",
    }

    if angle.id == "breakout":
        return {
            "hook": f"Пробой {_fmt_price(key_level)} переводит рынок в {ticker_side}-режим",
            "thesis": (
                f"Цена закрылась {supportive_side} ключевой границы диапазона. Это не просто движение внутри боковика: "
                f"уровень {_fmt_price(key_level)} теперь должен подтвердиться как опора сценария."
            ),
            "evidence": f"Объём {metrics['volume']} · ADX {metrics['adx']} · 1H {metrics['change_1h']} · {higher_tf}.",
            "confirmation": f"Главное подтверждение — повторное удержание {_fmt_price(key_level)} после возможного ретеста.",
            "failure": f"Возврат и закрепление {failure_side} пробитой границы отменит идею продолжения.",
        }

    if angle.id == "liquidity_reclaim":
        swept = ind.swing_low if direction == "long" else ind.swing_high
        return {
            "hook": f"После снятия ликвидности цена вернулась в пользу {participants}",
            "thesis": (
                f"Рынок проколол {_fmt_price(swept)}, но не удержался за экстремумом и вернулся обратно. "
                f"Такой возврат делает реакцию важнее самого прокола."
            ),
            "evidence": f"Текущая цена {metrics['price']} · VWAP {metrics['vwap']} · RSI {metrics['rsi']} · объём {metrics['volume']}.",
            "confirmation": f"Сценарий усиливается при удержании цены {supportive_side} EMA20 {_fmt_price(ind.ema20)}.",
            "failure": f"Повторный уход {failure_side} свипнутого экстремума вернёт преимущество противоположной стороне.",
        }

    if angle.id == "pullback":
        return {
            "hook": f"Не погоня за ценой: {ticker_side}-идея формируется на откате к EMA20",
            "thesis": (
                f"Основной тренд сохраняется, а цена вернулась к динамической зоне EMA20 {_fmt_price(ind.ema20)} "
                f"и пока удерживает её в сторону текущего движения."
            ),
            "evidence": f"EMA20/EMA50: {_fmt_price(ind.ema20)}/{_fmt_price(ind.ema50)} · RSI {metrics['rsi']} · {higher_tf}.",
            "confirmation": f"Нужна реакция от EMA20 и возврат импульса {supportive_side} текущей цены.",
            "failure": f"Закрепление {failure_side} EMA50 {_fmt_price(ind.ema50)} разрушит логику отката внутри тренда.",
        }

    if angle.id == "trend_continuation":
        return {
            "hook": f"Тренд ещё не сломан: структура остаётся в пользу {ticker_side}",
            "thesis": (
                f"EMA20 расположена в нужную сторону относительно EMA50, цена держится {supportive_side} EMA20, "
                f"а MACD не показывает разворота против сценария."
            ),
            "evidence": f"ADX {metrics['adx']} · RSI {metrics['rsi']} · 4H {metrics['change_4h']} · старшие ТФ: {higher_tf}.",
            "confirmation": f"Продолжение получит подтверждение после обновления локального экстремума по направлению сделки.",
            "failure": f"Потеря EMA20 и возврат к EMA50 ослабят трендовое преимущество.",
        }

    if angle.id == "volume_impulse":
        return {
            "hook": f"Объём вырос до {metrics['volume']} — проверяем, продолжится ли импульс",
            "thesis": (
                f"Текущая свеча проходит на объёме выше среднего. Сам по себе всплеск не гарантирует движение, "
                f"поэтому ключевым остаётся удержание цены у {_fmt_price(key_level)}."
            ),
            "evidence": f"Объём {metrics['volume']} · изменение 1H {metrics['change_1h']} · ADX {metrics['adx']} · RSI {metrics['rsi']}.",
            "confirmation": f"Полезное подтверждение — следующая реакция без резкого возврата {failure_side} ключевого уровня.",
            "failure": f"Если объём останется высоким, но цена вернётся в диапазон, импульс можно считать поглощённым.",
        }

    if angle.id == "mtf_alignment":
        return {
            "hook": f"{aligned} из {total} старших таймфреймов поддерживают {ticker_side}",
            "thesis": (
                f"Сигнал строится не на одном 15-минутном импульсе: направление EMA20/EMA50 совпадает "
                f"на нескольких старших периодах."
            ),
            "evidence": f"Согласованность: {higher_tf} · ADX 15M {metrics['adx']} · объём {metrics['volume']}.",
            "confirmation": f"Локальный вход имеет смысл только пока 15M не расходится со старшей структурой.",
            "failure": f"Разворот 15M против 1H/4H без быстрого восстановления повысит риск ложного входа.",
        }

    if angle.id == "vwap_control":
        return {
            "hook": f"Цена удерживается {supportive_side} VWAP {_fmt_price(ind.vwap)}",
            "thesis": (
                f"VWAP сейчас выступает ориентиром контроля внутри дня. Пока цена остаётся {supportive_side} него, "
                f"инициатива соответствует направлению {ticker_side}."
            ),
            "evidence": f"Цена {metrics['price']} · VWAP {metrics['vwap']} · EMA20 {metrics['ema20']} · объём {metrics['volume']}.",
            "confirmation": f"Лучшее подтверждение — реакция от VWAP с обновлением локального экстремума.",
            "failure": f"Закрепление {failure_side} VWAP ослабит внутридневную структуру.",
        }

    if angle.id == "range_edge":
        return {
            "hook": f"Цена подошла к границе диапазона {_fmt_price(key_level)}",
            "thesis": (
                f"Сейчас важна не скорость движения, а реакция у края диапазона {metrics['support']}–{metrics['resistance']}. "
                f"Именно здесь станет понятно, есть ли продолжение {ticker_side}."
            ),
            "evidence": f"До ключевой границы менее двух ATR · ATR {metrics['atr_pct']} · объём {metrics['volume']}.",
            "confirmation": f"Подтверждение — закрытие и удержание {supportive_side} {_fmt_price(key_level)}.",
            "failure": f"Отбой от границы с возвратом к середине диапазона отменит идею немедленного продолжения.",
        }

    if angle.id == "momentum":
        return {
            "hook": f"Моментум поддерживает {ticker_side}, но вход решает уровень",
            "thesis": (
                f"RSI {metrics['rsi']} и MACD-гистограмма направлены в сторону сценария. "
                f"Моментум подтверждает движение, но не заменяет контроль риска."
            ),
            "evidence": f"RSI {metrics['rsi']} · ADX {metrics['adx']} · 1H {metrics['change_1h']} · VWAP {metrics['vwap']}.",
            "confirmation": f"Импульс должен сохраниться при тесте {_fmt_price(key_level)}.",
            "failure": f"Дивергенция цены и моментума либо возврат {failure_side} VWAP ослабят сигнал.",
        }

    if angle.id == "volatility_expansion":
        return {
            "hook": f"Волатильность расширяется: ATR достиг {metrics['atr_pct']}",
            "thesis": (
                f"Диапазон свечей увеличился одновременно с ADX {metrics['adx']}. Это создаёт потенциал движения, "
                f"но требует меньшего размера позиции из-за более широкого стопа."
            ),
            "evidence": f"ATR {metrics['atr_pct']} · объём {metrics['volume']} · диапазон {metrics['support']}–{metrics['resistance']}.",
            "confirmation": f"Сценарий подтверждается только при направленном выходе без мгновенного возврата в диапазон.",
            "failure": f"Резкое сжатие диапазона после выхода укажет на отсутствие продолжения.",
        }

    return default


def _level_block(levels: Dict[str, float], title: str) -> str:
    return (
        f"{title}\n"
        f"Вход: {_fmt_price(levels['entry'])} USDT\n"
        f"TP1: {_fmt_price(levels['tp1'])} USDT\n"
        f"TP2: {_fmt_price(levels['tp2'])} USDT\n"
        f"TP3: {_fmt_price(levels['tp3'])} USDT\n"
        f"Стоп: {_fmt_price(levels['stop'])} USDT\n"
        f"R/R: {levels['risk_reward']:.2f}"
    )


def _risk_block(ind, direction: str, levels: Dict[str, float]) -> str:
    failure_side = "ниже" if direction == "long" else "выше"
    return (
        f"Отмена сценария: закрепление {failure_side} стоп-уровня {_fmt_price(levels['stop'])}. "
        f"Диапазон наблюдения: {_fmt_price(ind.support)}–{_fmt_price(ind.resistance)}. "
        "Размер позиции рассчитывается от допустимого риска, а не от силы формулировки сигнала."
    )


def _render_style(
    *,
    style: PostStyle,
    angle: SignalAngle,
    ticker: str,
    direction_label: str,
    angle_copy: Dict[str, str],
    metrics: Dict[str, str],
    context: str,
    level_block: str,
    risk_block: str,
    cta: str,
) -> str:
    header = f"{ticker} | {direction_label} | {angle.title}"

    if style.id == "numbers_first":
        return "\n\n".join(
            (
                header,
                f"Цена {metrics['price']} USDT · 1H {metrics['change_1h']} · объём {metrics['volume']} · RSI {metrics['rsi']}",
                level_block,
                f"Что стоит за цифрами: {angle_copy['thesis']}",
                angle_copy["confirmation"],
                context,
                risk_block,
                cta,
            )
        )

    if style.id == "scenario_tree":
        return "\n\n".join(
            (
                header,
                angle_copy["hook"],
                f"Базовый сценарий: {angle_copy['confirmation']}",
                f"Альтернативный сценарий: {angle_copy['failure']}",
                angle_copy["evidence"],
                level_block,
                context,
                risk_block,
                cta,
            )
        )

    if style.id == "checklist":
        return "\n\n".join(
            (
                header,
                angle_copy["hook"],
                "Чек-лист сетапа:\n"
                f"✓ направление: {direction_label}\n"
                f"✓ главный фактор: {angle.title.lower()}\n"
                f"✓ метрики: {angle_copy['evidence']}\n"
                f"→ подтверждение: {angle_copy['confirmation']}",
                level_block,
                context,
                risk_block,
                cta,
            )
        )

    if style.id == "level_focus":
        return "\n\n".join(
            (
                f"{ticker} | Уровень решает больше, чем прогноз",
                angle_copy["hook"],
                f"Почему уровень важен: {angle_copy['thesis']}",
                f"Реакция для подтверждения: {angle_copy['confirmation']}",
                level_block,
                angle_copy["evidence"],
                context,
                risk_block,
                cta,
            )
        )

    if style.id == "thesis":
        return "\n\n".join(
            (
                header,
                f"Тезис: {angle_copy['thesis']}",
                "Аргументы:\n"
                f"1) {angle_copy['evidence']}\n"
                f"2) {angle_copy['confirmation']}\n"
                f"3) {context}",
                level_block,
                f"Контраргумент: {angle_copy['failure']}",
                risk_block,
                cta,
            )
        )

    if style.id == "risk_first":
        return "\n\n".join(
            (
                f"{ticker} | {direction_label}: сначала точка отмены",
                risk_block,
                angle_copy["hook"],
                angle_copy["thesis"],
                angle_copy["evidence"],
                level_block,
                context,
                cta,
            )
        )

    if style.id == "compact_brief":
        return "\n\n".join(
            (
                header,
                f"Суть: {angle_copy['hook']}. {angle_copy['thesis']}",
                f"Подтверждение: {angle_copy['confirmation']}",
                f"Факты: {angle_copy['evidence']}",
                level_block,
                risk_block,
                cta,
            )
        )

    # market_note
    return "\n\n".join(
        (
            header,
            angle_copy["hook"],
            angle_copy["thesis"],
            angle_copy["evidence"],
            context,
            level_block,
            f"Что подтвердит идею: {angle_copy['confirmation']}",
            risk_block,
            cta,
        )
    )


# ---------------------------------------------------------------------------
# Optional AI polish
# ---------------------------------------------------------------------------
def _clean_ai_text(text: str) -> str:
    cleaned = text.strip()
    cleaned = re.sub(r"```.*?```", "", cleaned, flags=re.DOTALL)
    cleaned = cleaned.replace("**", "").replace("__", "").replace("`", "")
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


def _polish_with_ai(text: str, basic: str, levels: Dict[str, float], style: PostStyle, angle: SignalAngle) -> str:
    if not MISTRAL_API:
        return text
    required = "\n".join(
        (
            f"Вход: {_fmt_price(levels['entry'])} USDT",
            f"TP1: {_fmt_price(levels['tp1'])} USDT",
            f"TP2: {_fmt_price(levels['tp2'])} USDT",
            f"TP3: {_fmt_price(levels['tp3'])} USDT",
            f"Стоп: {_fmt_price(levels['stop'])} USDT",
            f"R/R: {levels['risk_reward']:.2f}",
        )
    )
    prompt = f"""
Отредактируй пост для Binance Square на русском языке.
Сохрани формат «{style.title}» и главную тему «{angle.title}» — не превращай текст в стандартный шаблон.
Не добавляй новости, китов, инсайды, гарантии и вероятность прибыли.
Сохрани тикер ${basic.upper()}, направление, вопрос аудитории и все числа ТОЧНО.
Максимум 2 эмодзи. Не добавляй хэштеги.

Обязательные строки:
{required}

Пост:
{text}
""".strip()
    response = requests.post(
        "https://api.mistral.ai/v1/chat/completions",
        headers={"Authorization": f"Bearer {MISTRAL_API}", "Content-Type": "application/json"},
        json={
            "model": os.getenv("MISTRAL_MODEL", "mistral-small-latest"),
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.72,
            "max_tokens": 750,
        },
        timeout=45,
    )
    response.raise_for_status()
    polished = _clean_ai_text(response.json()["choices"][0]["message"]["content"])
    if not _contains_required_content(polished, levels):
        raise ValueError("AI response lost mandatory trade levels")
    if f"${basic.upper()}" not in polished.upper():
        raise ValueError("AI response lost the ticker")
    return polished


# ---------------------------------------------------------------------------
# Public generation API
# ---------------------------------------------------------------------------
def generate_post_draft(
    *,
    symbol: str,
    basic: str,
    mtf,
    score,
    memory: Optional[PostMemory] = None,
    levels: Optional[Dict[str, float]] = None,
    btc=None,
    variant_index: int = 0,
) -> GeneratedPost:
    del symbol
    ind = mtf.tf_15m
    if ind is None:
        raise ValueError("15m indicators are required")

    direction = score.direction
    direction_label = "LONG" if direction == "long" else "SHORT"
    levels = dict(levels or _levels(ind, direction))
    levels.setdefault("risk_reward", score.risk_reward)

    recent_signal_types = memory.get_last_signal_types(16) if memory else []
    recent_styles = memory.get_last_post_styles(12) if memory else []
    angle = choose_signal_angle(ind, direction, mtf, recent_signal_types, variant_index)
    style = choose_post_style(recent_styles, variant_index)

    used_ctas = memory.get_last_ctas(24) if memory else []
    cta = _pick_unused(CTA_VARIANTS, used_ctas)
    plan_title = choose(PLAN_TITLES)

    angle_copy = _angle_content(angle, ind, direction, mtf)
    metrics = _market_metrics(ind)
    higher_tf, _, _ = _higher_tf_context(mtf, direction)
    context = f"Контекст: {higher_tf}. {_btc_context_text(btc, direction)}"
    level_block = _level_block(levels, plan_title)
    risk_block = _risk_block(ind, direction, levels)

    # Добавляем естественные вариации речи, чтобы посты не выглядели как один шаблон.
    human_prefix = random.choice(HUMAN_HOOKS)
    personal_note = random.choice(PERSONAL_PHRASES)
    post = _render_style(
        style=style,
        angle=angle,
        ticker=_format_ticker(basic),
        direction_label=direction_label,
        angle_copy=angle_copy,
        metrics=metrics,
        context=context,
        level_block=level_block,
        risk_block=risk_block,
        cta=f"{cta}\n\n{personal_note}",
    )
    if random.random() > 0.35:
        post = human_prefix + "\n\n" + post
    post = re.sub(r"[ \t]+\n", "\n", post).strip()

    if ENABLE_AI_POLISH and MISTRAL_API:
        try:
            polished = _polish_with_ai(post, basic, levels, style, angle)
            if len(polished) <= POST_MAX_CHARS:
                post = polished
        except Exception as exc:
            logger.warning("AI polish rejected; using deterministic text: %s", exc)

    hashtags = varied_hashtags(basic, direction)
    full_post = _fix_ticker_spacing(f"{post}\n\n{hashtags}").strip()

    if len(full_post) > POST_MAX_CHARS:
        compact_style = PostStyle("compact_brief", "Короткий бриф")
        post = _render_style(
            style=compact_style,
            angle=angle,
            ticker=_format_ticker(basic),
            direction_label=direction_label,
            angle_copy=angle_copy,
            metrics=metrics,
            context=context,
            level_block=level_block,
            risk_block=risk_block,
            cta=cta,
        )
        full_post = _fix_ticker_spacing(f"{post}\n\n{hashtags}").strip()
        style = compact_style

    if len(full_post) > POST_MAX_CHARS:
        raise ValueError(f"Post exceeds POST_MAX_CHARS={POST_MAX_CHARS}")
    if not _contains_required_content(full_post, levels):
        raise ValueError("Generated post is incomplete")

    return GeneratedPost(
        text=full_post,
        style_id=style.id,
        signal_type=angle.id,
        angle_title=angle.title,
    )


def generate_post_with_memory(
    *,
    symbol: str,
    basic: str,
    mtf,
    score,
    memory: Optional[PostMemory] = None,
    levels: Optional[Dict[str, float]] = None,
    btc=None,
    variant_index: int = 0,
) -> str:
    """Backward-compatible wrapper returning only text."""
    return generate_post_draft(
        symbol=symbol,
        basic=basic,
        mtf=mtf,
        score=score,
        memory=memory,
        levels=levels,
        btc=btc,
        variant_index=variant_index,
    ).text
