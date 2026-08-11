"""Write-to-Earn oriented market and copy scoring for Binance Square v9.

W2E itself is not a views program: the useful observable funnel is
reader -> cashtag -> market -> qualified trade.  We therefore reward early
cashtag discoverability, a coherent trade plan, trust and readability while
avoiding pushy or spam-like copy.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
import re
from typing import Dict


@dataclass(frozen=True)
class MarketMonetizationSnapshot:
    score: float
    trend_rank_score: float
    liquidity_score: float
    activity_score: float
    movement_score: float
    freshness_score: float
    actionability_score: float
    reason: str


@dataclass(frozen=True)
class ConversionIntentReport:
    score: float
    components: Dict[str, float]


def _clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, float(value)))


def _log_score(value: float, floor_log: float, ceiling_log: float) -> float:
    if value <= 0:
        return 0.0
    x = math.log10(value)
    if ceiling_log <= floor_log:
        return 0.0
    return _clamp((x - floor_log) / (ceiling_log - floor_log) * 100.0)


def score_market_monetization(
    *,
    quote_volume_24h: float,
    trade_count_24h: float,
    abs_change_24h: float,
    trend_rank: int,
    trend_universe_size: int,
    attention_score: float,
    change_15m: float,
    volume_spike: float,
    risk_reward: float,
    overextended: bool,
    micro_freshness: float = 50.0,
) -> MarketMonetizationSnapshot:
    size = max(1, int(trend_universe_size))
    rank = max(1, min(int(trend_rank), size))
    rank_score = _clamp((1.0 - (rank - 1) / max(1, size - 1)) * 100.0)

    liquidity = _log_score(float(quote_volume_24h), 6.2, 10.0)
    activity = _log_score(float(trade_count_24h), 3.0, 6.9)

    move = min(abs(float(abs_change_24h)), 35.0)
    movement = _clamp(move / 10.0 * 100.0)
    if move > 22.0:
        movement -= min(25.0, (move - 22.0) * 1.6)
    movement = _clamp(movement)

    # Freshness intentionally saturates raw x-volume.  The v8 feedback sample
    # showed x30+ did not automatically outperform x3-x5 events.
    volume_bonus = min(max(math.log2(max(float(volume_spike), 1.0)), 0.0) * 4.0, 12.0)
    freshness = _clamp(
        float(attention_score) * 0.58
        + float(micro_freshness) * 0.28
        + min(abs(float(change_15m)) * 5.0, 10.0)
        + volume_bonus
    )

    rr = max(0.0, float(risk_reward))
    actionability = 42.0 + min(max(rr - 1.0, 0.0) * 22.0, 42.0)
    if rr < 1.20:
        actionability -= 18.0
    if overextended:
        actionability -= 9.0
    actionability = _clamp(actionability)

    score = (
        rank_score * 0.16
        + liquidity * 0.22
        + activity * 0.16
        + movement * 0.06
        + freshness * 0.28
        + actionability * 0.12
    )
    score = _clamp(score)
    reason = (
        f"rank={rank}/{size}, liq={liquidity:.0f}, activity={activity:.0f}, "
        f"fresh={freshness:.0f}, actionable={actionability:.0f}"
    )
    return MarketMonetizationSnapshot(
        score=round(score, 2),
        trend_rank_score=round(rank_score, 2),
        liquidity_score=round(liquidity, 2),
        activity_score=round(activity, 2),
        movement_score=round(movement, 2),
        freshness_score=round(freshness, 2),
        actionability_score=round(actionability, 2),
        reason=reason,
    )


class ConversionIntentEvaluator:
    """Score a useful, non-pushy click-to-market journey."""

    ACTION_MARKERS = (
        "если ", "пока ", "вход", "зона", "стоп", "stop", "tp1", "tp2", "tp3",
        "цель", "отмена", "сценар", "лонг", "long", "шорт", "short",
    )
    DECISION_MARKERS = (
        "для меня", "я бы", "смотрю", "пропущ", "не хочу", "не беру", "не открываю",
        "интересен", "интересна", "рабочий", "рабочая",
    )
    SPAM_MARKERS = (
        "100%", "гарант", "без риска", "точно даст", "легкие деньги", "лёгкие деньги",
        "срочно покуп", "срочно прода", "заходи сейчас", "иксы гарант", "не упусти",
    )
    ROBOTIC_MARKERS = (
        "направление у идеи", "граница ошибки", "диапазон контроля",
        "параметры сценария", "карта исполнения", "правило исполнения",
    )

    def report(self, text: str, basic: str) -> ConversionIntentReport:
        clean = text.strip()
        lowered = clean.lower().replace("ё", "е")
        ticker = "$" + re.sub(r"[^A-Za-z0-9]", "", str(basic)).upper()
        ticker_matches = list(re.finditer(re.escape(ticker), clean, flags=re.IGNORECASE))

        discoverability = 10.0
        if ticker_matches:
            discoverability += 52.0
            first_pos = ticker_matches[0].start()
            if first_pos <= 70:
                discoverability += 30.0
            elif first_pos <= 150:
                discoverability += 18.0
            if 1 <= len(ticker_matches) <= 2:
                discoverability += 8.0
            elif len(ticker_matches) > 3:
                discoverability -= 18.0
        discoverability = _clamp(discoverability)

        actionability = 24.0
        actionability += min(42.0, sum(1 for marker in self.ACTION_MARKERS if marker in lowered) * 4.5)
        number_count = len(re.findall(r"(?<!\w)[+-]?\d+(?:[.,]\d+)?%?", clean))
        if 3 <= number_count <= 8:
            actionability += 12.0
        if re.search(r"\b(?:tp1|tp2|tp3)\b", lowered) or "первая цель" in lowered:
            actionability += 8.0
        if any(marker in lowered for marker in ("стоп", "отмена", "сценарий отмен", "идея отмен")):
            actionability += 10.0
        actionability = _clamp(actionability)

        decision_context = 25.0 + min(65.0, sum(1 for marker in self.DECISION_MARKERS if marker in lowered) * 8.0)
        decision_context = _clamp(decision_context)

        trust = 98.0
        if any(marker in lowered for marker in self.SPAM_MARKERS):
            trust -= 75.0
        if any(marker in lowered for marker in self.ROBOTIC_MARKERS):
            trust -= 28.0
        if clean.count("!") >= 2:
            trust -= 12.0
        if len(re.findall(r"\b(?:LONG|SHORT|ЛОНГ|ШОРТ)\b", clean, flags=re.IGNORECASE)) >= 4:
            trust -= 10.0
        trust = _clamp(trust)

        readability = 100.0
        if len(clean) > 560:
            readability -= min(45.0, (len(clean) - 560) / 4.0)
        if number_count > 10:
            readability -= min(38.0, (number_count - 10) * 5.0)
        label_hits = sum(lowered.count(marker) for marker in (
            "направление:", "ключевой уровень:", "r/r:", "параметры:",
        ))
        readability -= min(30.0, label_hits * 10.0)
        readability = _clamp(readability)

        score = (
            discoverability * 0.30
            + actionability * 0.34
            + decision_context * 0.14
            + trust * 0.14
            + readability * 0.08
        )
        return ConversionIntentReport(
            score=round(_clamp(score), 2),
            components={
                "discoverability": round(discoverability, 2),
                "actionability": round(actionability, 2),
                "decision_context": round(decision_context, 2),
                "trust": round(trust, 2),
                "readability": round(readability, 2),
            },
        )
