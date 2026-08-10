"""Market-attention ranking for Binance Square.

The technical engine answers "is there a defensible setup?".  This module asks a
separate question: "is this the market event people are likely to care about
*now*?"  The score intentionally combines relative audience demand with fresh
15-minute behaviour instead of treating a technically clean setup as a good
content topic by default.

No private Binance recommendation signals are assumed here.  Everything comes
from public 24h ticker metadata plus closed candles already fetched by the bot.
"""
from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass
import math
from typing import Iterable, Sequence

from attention import AttentionSnapshot
from trend import TrendingMarket


@dataclass(frozen=True)
class MarketOpportunitySnapshot:
    score: float
    audience_demand: float
    fresh_attention: float
    volume_anomaly: float
    move_quality: float
    actionability: float
    saturation_penalty: float
    event_class: str
    reason: str


def _clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, float(value)))


def _percentile(value: float, values: Iterable[float], *, log_scale: bool = False) -> float:
    clean = [max(0.0, float(item)) for item in values if math.isfinite(float(item))]
    if not clean:
        return 50.0
    if log_scale:
        clean = [math.log10(max(item, 1.0)) for item in clean]
        value = math.log10(max(float(value), 1.0))
    clean.sort()
    if len(clean) == 1:
        return 50.0
    position = bisect_right(clean, float(value)) - 1
    return _clamp(position / (len(clean) - 1) * 100.0)


def audience_demand_score(meta: TrendingMarket | None, universe: Sequence[TrendingMarket]) -> float:
    """Relative demand proxy using liquidity, transactions and trend rank.

    Percentiles are used so a mid-cap that is unusually active can compete with
    BTC/ETH without pretending absolute volume is irrelevant.
    """
    if meta is None:
        return 18.0
    quote_pct = _percentile(meta.quote_volume, (item.quote_volume for item in universe), log_scale=True)
    trades_pct = _percentile(meta.trade_count, (item.trade_count for item in universe), log_scale=True)
    size = max(1, len(universe))
    rank_score = _clamp((1.0 - (max(1, meta.rank) - 1) / max(1, size - 1)) * 100.0)
    return _clamp(quote_pct * 0.44 + trades_pct * 0.38 + rank_score * 0.18)


def volume_anomaly_score(spike: float) -> float:
    """Map x-volume to a smooth 0-100 event score.

    Around x2 is noteworthy, x4-x8 is strong and x16+ is exceptional.  Values
    below normal are intentionally weak even when the technical setup is clean.
    """
    ratio = max(0.05, float(spike))
    return _clamp(32.0 + math.log2(ratio) * 22.0)


def _move_leg_score(move: float, *, sweet_low: float, sweet_high: float, hard_high: float) -> float:
    value = abs(float(move))
    if value < 0.20:
        return 15.0 + value / 0.20 * 15.0
    if value < sweet_low:
        return 30.0 + (value - 0.20) / max(0.01, sweet_low - 0.20) * 55.0
    if value <= sweet_high:
        return 85.0 + (value - sweet_low) / max(0.01, sweet_high - sweet_low) * 15.0
    if value <= hard_high:
        return 100.0 - (value - sweet_high) / max(0.01, hard_high - sweet_high) * 30.0
    return _clamp(70.0 - (value - hard_high) * 3.0, 22.0, 70.0)


def move_quality_score(change_15m: float, change_45m: float) -> float:
    # The sample that performed best for this account clustered around fresh,
    # visible moves rather than already-exhausted double-digit 15m candles.  This
    # is therefore a *soft* sweet spot, not a hard rejection of large moves.
    score15 = _move_leg_score(change_15m, sweet_low=0.75, sweet_high=4.5, hard_high=9.0)
    score45 = _move_leg_score(change_45m, sweet_low=1.2, sweet_high=10.0, hard_high=20.0)
    return _clamp(score15 * 0.68 + score45 * 0.32)


def saturation_penalty(attention: AttentionSnapshot) -> float:
    move15 = abs(float(attention.change_15m))
    move45 = abs(float(attention.change_45m))
    penalty = 0.0
    if move15 > 8.0:
        penalty += min(18.0, (move15 - 8.0) * 1.8)
    if move45 > 18.0:
        penalty += min(10.0, (move45 - 18.0) * 0.8)
    if attention.overextended:
        penalty += 4.5
    # Exceptional live volume keeps an extended move interesting as a *story*,
    # even when it is not a good chase entry.
    if attention.volume_spike >= 8.0:
        penalty *= 0.65
    return min(24.0, penalty)


def _event_class(attention: AttentionSnapshot, volume_score: float) -> str:
    move = abs(float(attention.change_15m))
    if volume_score >= 88 and move >= 0.75:
        return "volume_shock"
    if attention.score >= 80 and move >= 1.0:
        return "fresh_impulse"
    if attention.score >= 68 or volume_score >= 70:
        return "active_market"
    return "ordinary"


def score_market_opportunity(
    *,
    meta: TrendingMarket | None,
    universe: Sequence[TrendingMarket],
    attention: AttentionSnapshot,
    technical_score: float,
    risk_reward: float,
    strict_setup: bool,
    btc_compatible: bool = True,
) -> MarketOpportunitySnapshot:
    demand = audience_demand_score(meta, universe)
    volume = volume_anomaly_score(attention.volume_spike)
    move_quality = move_quality_score(attention.change_15m, attention.change_45m)
    rr = max(0.0, float(risk_reward))
    actionability = 48.0 + min(max(rr - 1.0, 0.0) * 24.0, 36.0)
    if rr < 1.10:
        actionability -= 22.0
    if attention.overextended:
        actionability -= 8.0
    actionability = _clamp(actionability)

    penalty = saturation_penalty(attention)
    score = (
        demand * 0.27
        + float(attention.score) * 0.25
        + _clamp(technical_score) * 0.18
        + volume * 0.14
        + move_quality * 0.10
        + actionability * 0.06
    )
    if strict_setup:
        score += 2.5
    if not btc_compatible:
        # BTC disagreement is context, not an automatic ban for a hot alt.
        score -= 4.0
    score -= penalty
    score = _clamp(score)

    event = _event_class(attention, volume)
    reason = (
        f"demand={demand:.0f}, fresh={attention.score:.0f}, vol_event={volume:.0f}, "
        f"move={move_quality:.0f}, actionable={actionability:.0f}, saturation=-{penalty:.1f}, "
        f"event={event}"
    )
    return MarketOpportunitySnapshot(
        score=round(score, 2),
        audience_demand=round(demand, 2),
        fresh_attention=round(float(attention.score), 2),
        volume_anomaly=round(volume, 2),
        move_quality=round(move_quality, 2),
        actionability=round(actionability, 2),
        saturation_penalty=round(penalty, 2),
        event_class=event,
        reason=reason,
    )


def preliminary_interest_score(
    *,
    technical_score: float,
    attention: AttentionSnapshot,
    meta: TrendingMarket | None,
    universe: Sequence[TrendingMarket],
) -> float:
    """Cheap pre-4h/1d shortlist score so hot markets are not discarded early."""
    demand = audience_demand_score(meta, universe)
    volume = volume_anomaly_score(attention.volume_spike)
    move = move_quality_score(attention.change_15m, attention.change_45m)
    penalty = saturation_penalty(attention) * 0.55
    score = (
        _clamp(technical_score) * 0.38
        + float(attention.score) * 0.30
        + demand * 0.18
        + volume * 0.09
        + move * 0.05
        - penalty
    )
    return _clamp(score)
