"""Fact-based Binance Square post generator with diversity and completeness checks."""
from __future__ import annotations

import logging
import os
import random
import re
from typing import Dict, List, Optional, Sequence

import requests

from indicators import build_trade_levels
from memory import PostMemory
from content_variation import hashtags as varied_hashtags, choose, PLAN_TITLES

logger = logging.getLogger(__name__)

MISTRAL_API = os.getenv("MISTRAL_API", "").strip()
ENABLE_AI_POLISH = os.getenv("ENABLE_AI_POLISH", "0").strip().lower() in {"1", "true", "yes"}
POST_MAX_CHARS = int(os.getenv("POST_MAX_CHARS", "1600"))


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
    """Compatibility wrapper used by main.py and external callers."""
    return build_trade_levels(ind, direction)


def _hashtags(basic: str, direction: str) -> str:
    direction_tag = "LONG" if direction == "long" else "SHORT"
    return varied_hashtags(basic, direction)


def _format_ticker(basic: str) -> str:
    """Binance Square ticker formatting.

    Binance recognizes $TICKER better when punctuation is not attached
    directly after it. Always returns a ticker separated by a space.
    """
    clean = re.sub(r"[^A-Za-z0-9]", "", str(basic)).upper()
    return f"${clean} "


def _fix_ticker_spacing(text: str) -> str:
    """Normalize Binance Square tickers without breaking symbols."""
    import re

    text = re.sub(r"(\$[A-Z0-9]{2,15})[,:;.!?]", r"\1", text)
    text = re.sub(r"\$[A-Z0-9]{2,15}", lambda m: m.group(0).replace(" ", ""), text)

    return text


# ---------------------------------------------------------------------------
# Truthful engagement templates
# ---------------------------------------------------------------------------
HOOKS = [
    "{ticker}: зона решения рядом — смотрим реакцию цены",
    "{ticker} {direction}: ключевой уровень перед движением",
    "{ticker}: цена у важной зоны, где ломается сценарий",
    "{ticker}: главный уровень, который нельзя потерять",
    "{ticker}: рынок дал точку, где идея становится понятной",
    "{ticker}: импульс есть, но решает реакция у уровня",
    "{ticker}: почему этот уровень сейчас важнее движения",
    "{ticker}: сетап {direction} с понятным планом",
]


CTA_LIST = [
    "Ждёте продолжение движения или реакцию от уровня?",
    "Какой уровень здесь главный для подтверждения сценария?",
    "Вы бы ждали пробой зоны или вход от реакции?",
    "Какой вариант видите первым: продолжение или возврат?",
    "Где для вас находится ключевая точка решения?",
]


STRUCTURES: Sequence[Sequence[str]] = (
    ("hook", "snapshot", "trigger", "context", "plan", "invalidation", "risk_note", "cta"),
    ("hook", "context", "snapshot", "trigger", "plan", "risk_note", "invalidation", "cta"),
    ("hook", "trigger", "snapshot", "plan", "context", "invalidation", "risk_note", "cta"),
    ("hook", "snapshot", "plan", "trigger", "invalidation", "context", "risk_note", "cta"),
)

_FORBIDDEN_CLAIMS = (
    "90% точности",
    "гарантирован",
    "без риска",
    "точно вырастет",
    "точно упадет",
    "крупные игроки начали",
    "киты покупают",
    "киты продают",
    "я заработал",
    "экспертный прогноз",
)


def _pick_unused(options: Sequence[str], used: Sequence[str]) -> str:
    normalized_used = {PostMemory.normalize_text(item) for item in used if item}
    available = [item for item in options if PostMemory.normalize_text(item) not in normalized_used]
    return random.choice(available or list(options))


def _trigger_text(ind, direction: str) -> str:
    reasons: List[str] = []
    if direction == "long":
        if ind.breakout_up:
            reasons.append("закрытие выше сопротивления")
        if ind.pullback_long:
            reasons.append("удержание EMA20 после отката")
        if ind.trend_continuation_long:
            reasons.append("бычье продолжение тренда")
        if ind.liquidity_sweep_down:
            reasons.append("возврат выше уровня после свипа снизу")
    else:
        if ind.breakout_down:
            reasons.append("закрытие ниже поддержки")
        if ind.pullback_short:
            reasons.append("отбой от EMA20 в нисходящем тренде")
        if ind.trend_continuation_short:
            reasons.append("медвежье продолжение тренда")
        if ind.liquidity_sweep_up:
            reasons.append("возврат ниже уровня после свипа сверху")

    if not reasons:
        if direction == "long":
            reasons.append("EMA20 выше EMA50 и цена удерживается в бычьей структуре")
        else:
            reasons.append("EMA20 ниже EMA50 и цена остаётся в медвежьей структуре")
    return ", ".join(reasons[:3])


def _higher_tf_context(mtf, direction: str) -> str:
    labels = []
    for label, indicator in (("1H", mtf.tf_1h), ("4H", mtf.tf_4h), ("1D", mtf.tf_1d)):
        if indicator is None:
            continue
        aligned = indicator.ema20 > indicator.ema50 if direction == "long" else indicator.ema20 < indicator.ema50
        labels.append(f"{label} {'✓' if aligned else '×'}")
    return " · ".join(labels) if labels else "старшие таймфреймы недоступны"


def _btc_context_text(btc, direction: str) -> str:
    if btc is None:
        return "Контекст BTC: данные временно недоступны."
    compatibility = (
        "не противоречит сценарию"
        if btc.bias == "neutral"
        or (btc.bias == "bullish" and direction == "long")
        or (btc.bias == "bearish" and direction == "short")
        else "противоречит сценарию"
    )
    return (
        f"BTC: {btc.bias}, 1H {btc.change_1h:+.2f}%, 4H {btc.change_4h:+.2f}% — "
        f"контекст {compatibility}."
    )


def _select_hook(
    *,
    basic: str,
    direction: str,
    trigger: str,
    ind,
    level: float,
    memory: Optional[PostMemory],
) -> str:
    candidates = []
    direction_label = "LONG" if direction == "long" else "SHORT"
    for template in HOOKS:
        candidates.append(
            template.format(
                ticker=_format_ticker(basic),
                trigger=trigger,
                direction=direction_label,
                volume=f"{ind.volume_relative:.2f}",
                level=_fmt_price(level),
                change=f"{ind.change_1h:+.2f}",
            )
        )
    random.shuffle(candidates)
    if memory:
        for candidate in candidates:
            if not memory.was_title_used(candidate):
                return candidate
    return candidates[0]


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
    if not all(label.lower() in text.lower() for label in labels):
        return False
    return all(value in text for value in _mandatory_values(levels))


def _clean_ai_text(text: str) -> str:
    cleaned = text.strip()
    cleaned = re.sub(r"```.*?```", "", cleaned, flags=re.DOTALL)
    cleaned = cleaned.replace("**", "").replace("__", "").replace("`", "")
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


def _polish_with_ai(text: str, basic: str, levels: Dict[str, float]) -> str:
    if not MISTRAL_API:
        return text

    required = "\n".join(
        [
            f"Вход: {_fmt_price(levels['entry'])} USDT",
            f"TP1: {_fmt_price(levels['tp1'])} USDT",
            f"TP2: {_fmt_price(levels['tp2'])} USDT",
            f"TP3: {_fmt_price(levels['tp3'])} USDT",
            f"Стоп: {_fmt_price(levels['stop'])} USDT",
            f"R/R: {levels['risk_reward']:.2f}",
        ]
    )
    prompt = f"""
Перепиши пост для Binance Square на русском языке.
Требования:
- ясная структура и короткие абзацы;
- без обещаний прибыли, без выдуманных новостей, китов и инсайдов;
- не называй внутренний скор вероятностью успеха;
- сохрани все строки с уровнями и все числа ТОЧНО;
- сохрани фразу «Не финансовая рекомендация.»;
- максимум 2 эмодзи;
- не добавляй хэштеги.

Обязательные строки:
{required}

Исходный пост:
{text}
""".strip()

    response = requests.post(
        "https://api.mistral.ai/v1/chat/completions",
        headers={"Authorization": f"Bearer {MISTRAL_API}", "Content-Type": "application/json"},
        json={
            "model": os.getenv("MISTRAL_MODEL", "mistral-small-latest"),
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.45,
            "max_tokens": 650,
        },
        timeout=45,
    )
    response.raise_for_status()
    payload = response.json()
    polished = _clean_ai_text(payload["choices"][0]["message"]["content"])
    if not _contains_required_content(polished, levels):
        raise ValueError("AI response lost mandatory trade levels")
    if any(claim in polished.lower() for claim in _FORBIDDEN_CLAIMS):
        raise ValueError("AI response introduced an unsupported claim")
    if f"${basic.upper()}" not in polished:
        raise ValueError("AI response lost the ticker")
    return polished


def generate_post_with_memory(
    *,
    symbol: str,
    basic: str,
    mtf,
    score,
    memory: Optional[PostMemory] = None,
    levels: Optional[Dict[str, float]] = None,
    btc=None,
) -> str:
    """Generate a complete, fact-based post suitable for automated publication."""
    del symbol  # kept in the public signature for backward compatibility
    ind = mtf.tf_15m
    if ind is None:
        raise ValueError("15m indicators are required")

    direction = score.direction
    direction_label = "LONG" if direction == "long" else "SHORT"
    levels = dict(levels or _levels(ind, direction))
    levels.setdefault("risk_reward", score.risk_reward)

    trigger = _trigger_text(ind, direction)
    key_level = ind.resistance if direction == "long" else ind.support
    hook = _select_hook(
        basic=basic,
        direction=direction,
        trigger=trigger,
        ind=ind,
        level=key_level,
        memory=memory,
    )

    used_ctas = memory.get_last_ctas(20) if memory else []
    cta = _pick_unused(CTA_LIST, used_ctas)
    structure = random.choice(STRUCTURES)

    vwap_position = "выше" if ind.price >= ind.vwap else "ниже"
    trend_strength = "выраженный" if ind.adx >= 25 else "умеренный"
    setup_score = min(max(float(score.total), 0.0), 100.0)

    sections = {
        "hook": hook,
        "snapshot": (
            f"📊 Сценарий: {direction_label}\n"
            f"Цена: {_fmt_price(ind.price)} USDT · 1H: {ind.change_1h:+.2f}% · "
            f"объём: x{ind.volume_relative:.2f}"
        ),
        "trigger": (
            f"Почему сетап появился: {trigger}. RSI {ind.rsi:.1f}, ADX {ind.adx:.1f} "
            f"({trend_strength} тренд), цена {vwap_position} VWAP {_fmt_price(ind.vwap)}."
        ),
        "context": (
            f"Согласованность: {_higher_tf_context(mtf, direction)}.\n"
            f"{_btc_context_text(btc, direction)}"
        ),
        "plan": (
            f"{choose(PLAN_TITLES)}\n"
            f"Вход: {_fmt_price(levels['entry'])} USDT\n"
            f"TP1: {_fmt_price(levels['tp1'])} USDT\n"
            f"TP2: {_fmt_price(levels['tp2'])} USDT\n"
            f"TP3: {_fmt_price(levels['tp3'])} USDT\n"
            f"Стоп: {_fmt_price(levels['stop'])} USDT\n"
            f"R/R: {levels['risk_reward']:.2f}"
        ),
        "invalidation": (
            f"Отмена сценария: закрепление цены "
            f"{'ниже' if direction == 'long' else 'выше'} стоп-уровня. "
            f"Ближайшие границы диапазона: {_fmt_price(ind.support)}–{_fmt_price(ind.resistance)}."
        ),
        "risk_note": (
            "⚠️ Сценарий действует только пока ключевой уровень удерживается."
        ),
        "cta": cta,
    }

    post = "\n\n".join(sections[key] for key in structure)
    post = re.sub(r"[ \t]+\n", "\n", post).strip()

    if ENABLE_AI_POLISH and MISTRAL_API:
        try:
            polished = _polish_with_ai(post, basic, levels)
            if len(polished) <= POST_MAX_CHARS:
                post = polished
        except Exception as exc:
            logger.warning("AI polish rejected; using deterministic text: %s", exc)

    if memory and memory.is_similar(post, threshold=0.60):
        for _ in range(3):
            alternative_hook = _select_hook(
                basic=basic,
                direction=direction,
                trigger=trigger,
                ind=ind,
                level=key_level,
                memory=memory,
            )
            post = post.replace(hook, alternative_hook, 1)
            post = post.replace(cta, _pick_unused(CTA_LIST, memory.get_last_ctas(20)), 1)
            if not memory.is_similar(post, threshold=0.60):
                break

    if not _contains_required_content(post, levels):
        raise ValueError("Generated post is incomplete")

    hashtags = _hashtags(basic, direction)
    full_post = _fix_ticker_spacing(f"{post}\n\n{hashtags}").strip()
    if len(full_post) > POST_MAX_CHARS:
        # Never slice a post in the middle of a level. Remove only optional context.
        shorter_structure = ("hook", "snapshot", "trigger", "plan", "invalidation", "risk_note", "cta")
        post = "\n\n".join(sections[key] for key in shorter_structure)
        full_post = _fix_ticker_spacing(f"{post}\n\n{hashtags}").strip()
    if len(full_post) > POST_MAX_CHARS:
        raise ValueError(f"Post exceeds POST_MAX_CHARS={POST_MAX_CHARS}")

    return full_post
