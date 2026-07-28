"""Content strategy and variation engine for Binance Square posts.

The module separates two kinds of diversity:
1. signal angle — what market fact the post is primarily about;
2. post style — how that fact is presented to the reader.

Every angle is derived from calculated indicators. No narrative is invented merely
for variety.
"""
from __future__ import annotations

from dataclasses import dataclass
import random
from typing import Dict, Iterable, List, Sequence, Tuple


@dataclass(frozen=True)
class SignalAngle:
    id: str
    title: str
    short_label: str
    weight: float


@dataclass(frozen=True)
class PostStyle:
    id: str
    title: str


POST_STYLES: Tuple[PostStyle, ...] = (
    PostStyle("market_note", "Рыночная заметка"),
    PostStyle("numbers_first", "Сначала цифры"),
    PostStyle("scenario_tree", "Два сценария"),
    PostStyle("checklist", "Чек-лист подтверждений"),
    PostStyle("level_focus", "Фокус на уровне"),
    PostStyle("thesis", "Тезис и аргументы"),
    PostStyle("risk_first", "Сначала риск"),
    PostStyle("compact_brief", "Короткий бриф"),
)

PLAN_TITLES = (
    "🎯 План по уровням:",
    "📍 Карта сделки:",
    "План исполнения:",
    "Ключевые цены:",
    "Уровни сценария:",
)

CTA_VARIANTS = (
    "Вы бы ждали подтверждение или работали от реакции у уровня?",
    "Какой уровень для вас здесь является решающим?",
    "Что выглядит сильнее: продолжение импульса или возврат в диапазон?",
    "Вы рассматриваете этот сетап или пропускаете без дополнительного подтверждения?",
    "Какой сигнал подтверждения вы бы добавили перед входом?",
    "Где, по-вашему, рынок окончательно сломает этот сценарий?",
    "Какой вариант движения считаете базовым на ближайшие часы?",
    "Согласны с направлением или видите контраргумент?",
)

TAG_GROUPS = (
    ("#TechnicalAnalysis", "#Trading"),
    ("#CryptoTrading", "#MarketUpdate"),
    ("#Altcoins", "#PriceAction"),
    ("#Crypto", "#TradingPlan"),
    ("#MarketAnalysis", "#RiskManagement"),
)


def choose(items: Sequence[str], used: Iterable[str] | None = None) -> str:
    values = list(items)
    if not values:
        raise ValueError("Cannot choose from an empty sequence")
    used_set = {str(item) for item in (used or []) if item}
    available = [item for item in values if item not in used_set]
    return random.choice(available or values)


def hashtags(symbol: str, direction: str) -> str:
    direction_tag = "LONG" if direction == "long" else "SHORT"
    group = random.choice(TAG_GROUPS)
    return " ".join((f"#{symbol.upper()}", f"#{direction_tag}", *group))


def _higher_tf_alignment_count(mtf, direction: str) -> Tuple[int, int]:
    aligned = 0
    total = 0
    for indicator in (getattr(mtf, "tf_1h", None), getattr(mtf, "tf_4h", None), getattr(mtf, "tf_1d", None)):
        if indicator is None:
            continue
        total += 1
        is_aligned = indicator.ema20 > indicator.ema50 if direction == "long" else indicator.ema20 < indicator.ema50
        if is_aligned:
            aligned += 1
    return aligned, total


def detect_signal_angles(ind, direction: str, mtf=None) -> List[SignalAngle]:
    """Return truthful, eligible content angles ordered by relevance."""
    angles: List[SignalAngle] = []
    is_long = direction == "long"

    if (is_long and ind.breakout_up) or ((not is_long) and ind.breakout_down):
        angles.append(SignalAngle("breakout", "Пробой ключевой границы", "пробой", 10.0))

    if (is_long and ind.liquidity_sweep_down) or ((not is_long) and ind.liquidity_sweep_up):
        angles.append(SignalAngle("liquidity_reclaim", "Снятие ликвидности и возврат", "свип", 9.5))

    if (is_long and ind.pullback_long) or ((not is_long) and ind.pullback_short):
        angles.append(SignalAngle("pullback", "Откат внутри тренда", "откат", 9.0))

    if (is_long and ind.trend_continuation_long) or ((not is_long) and ind.trend_continuation_short):
        angles.append(SignalAngle("trend_continuation", "Продолжение тренда", "продолжение", 7.2))

    if ind.volume_relative >= 1.35:
        weight = 8.6 if ind.volume_relative >= 1.8 else 7.4
        angles.append(SignalAngle("volume_impulse", "Импульс на повышенном объёме", "объём", weight))

    aligned, total = _higher_tf_alignment_count(mtf, direction) if mtf is not None else (0, 0)
    if total >= 2 and aligned >= 2:
        angles.append(SignalAngle("mtf_alignment", "Согласованность таймфреймов", "MTF", 8.0 + aligned * 0.2))

    vwap_supports = ind.price >= ind.vwap if is_long else ind.price <= ind.vwap
    if vwap_supports:
        distance = abs(ind.price - ind.vwap) / max(ind.atr, 1e-12)
        if distance <= 1.4:
            angles.append(SignalAngle("vwap_control", "Контроль цены относительно VWAP", "VWAP", 6.8))

    key_level = ind.resistance if is_long else ind.support
    level_distance = abs(ind.price - key_level) / max(ind.atr, 1e-12)
    if level_distance <= 1.8:
        angles.append(SignalAngle("range_edge", "Реакция у границы диапазона", "граница", 7.0))

    momentum_supports = (
        (is_long and ind.macd_hist > 0 and ind.rsi >= 48)
        or ((not is_long) and ind.macd_hist < 0 and ind.rsi <= 52)
    )
    if momentum_supports:
        angles.append(SignalAngle("momentum", "Подтверждение импульса", "моментум", 6.5))

    atr_pct = ind.atr / ind.price * 100.0 if ind.price else 0.0
    if ind.adx >= 24 and atr_pct >= 0.45:
        angles.append(SignalAngle("volatility_expansion", "Расширение волатильности", "волатильность", 6.2))

    if not angles:
        angles.append(SignalAngle("trend_structure", "Структура тренда", "структура", 5.0))

    # Deduplicate while preserving the strongest occurrence.
    best: Dict[str, SignalAngle] = {}
    for angle in angles:
        previous = best.get(angle.id)
        if previous is None or angle.weight > previous.weight:
            best[angle.id] = angle
    return sorted(best.values(), key=lambda item: item.weight, reverse=True)


def choose_signal_angle(ind, direction: str, mtf=None, recent_ids: Iterable[str] | None = None, variant_index: int = 0) -> SignalAngle:
    candidates = detect_signal_angles(ind, direction, mtf)
    recent = list(recent_ids or [])
    recent_penalty: Dict[str, float] = {}
    for offset, angle_id in enumerate(reversed(recent[-12:])):
        recent_penalty[angle_id] = max(recent_penalty.get(angle_id, 0.0), 4.0 - min(offset, 6) * 0.45)

    scored = []
    for position, angle in enumerate(candidates):
        novelty = -recent_penalty.get(angle.id, 0.0)
        scored.append((angle.weight + novelty, angle))
    scored.sort(key=lambda item: item[0], reverse=True)

    # Different variant_index values explore several truthful angles, not merely
    # paraphrases of the strongest one. Weak tail angles are capped at six.
    exploration_pool = [item[1] for item in scored[: min(6, len(scored))]]
    return exploration_pool[variant_index % len(exploration_pool)]


def choose_post_style(recent_ids: Iterable[str] | None = None, variant_index: int = 0) -> PostStyle:
    recent = list(recent_ids or [])
    # Keep all layouts in every batch, but put recently published ones at the end.
    # This guarantees eight unique candidates while still favouring novelty.
    last_position = {style_id: position for position, style_id in enumerate(recent)}
    ordered = sorted(
        POST_STYLES,
        key=lambda style: (style.id in last_position, last_position.get(style.id, -1)),
    )
    return ordered[variant_index % len(ordered)]
