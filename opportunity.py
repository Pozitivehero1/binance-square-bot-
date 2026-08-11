"""Audience-first market opportunity ranking for Binance Square v9.1.

The selector deliberately separates three ideas:
1) audience demand -- is there a large enough pool of readers/traders around it;
2) freshness -- is the interesting move happening *now* rather than 30m ago;
3) technical actionability -- can we express a coherent plan without chasing.

A raw x-volume spike is only a supporting signal.  It saturates quickly and can
never overpower poor audience demand plus stale 5m behaviour by itself.
"""
from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass
import math
from typing import Iterable, Sequence

from attention import AttentionSnapshot, MicroAttentionSnapshot
from trend import TrendingMarket


@dataclass(frozen=True)
class MarketOpportunitySnapshot:
    score: float
    audience_demand: float
    fresh_attention: float
    micro_freshness: float
    volume_anomaly: float
    move_quality: float
    actionability: float
    saturation_penalty: float
    stale_penalty: float
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
    """Relative demand proxy: liquidity + real trade activity + current rank."""
    if meta is None:
        return 15.0
    quote_pct = _percentile(meta.quote_volume, (item.quote_volume for item in universe), log_scale=True)
    trades_pct = _percentile(meta.trade_count, (item.trade_count for item in universe), log_scale=True)
    size = max(1, len(universe))
    rank_score = _clamp((1.0 - (max(1, meta.rank) - 1) / max(1, size - 1)) * 100.0)

    # 24h movement is a weak demand proxy only.  Extremely large completed moves
    # are not rewarded linearly because they can already be saturated.
    move24 = abs(float(meta.change_pct))
    if move24 <= 10:
        move_interest = _clamp(move24 / 10.0 * 100.0)
    elif move24 <= 25:
        move_interest = 100.0 - (move24 - 10.0) * 1.4
    else:
        move_interest = max(35.0, 79.0 - (move24 - 25.0) * 1.5)

    return _clamp(
        quote_pct * 0.39
        + trades_pct * 0.34
        + rank_score * 0.19
        + move_interest * 0.08
    )


def volume_anomaly_score(spike: float) -> float:
    """Saturating x-volume score. x4 is strong; x30 is not 7.5x better."""
    ratio = max(0.05, float(spike))
    return _clamp(38.0 + math.log2(ratio) * 16.0)


def _move_leg_score(move: float, *, sweet_low: float, sweet_high: float, hard_high: float) -> float:
    value = abs(float(move))
    if value < 0.20:
        return 15.0 + value / 0.20 * 15.0
    if value < sweet_low:
        return 30.0 + (value - 0.20) / max(0.01, sweet_low - 0.20) * 55.0
    if value <= sweet_high:
        return 85.0 + (value - sweet_low) / max(0.01, sweet_high - sweet_low) * 15.0
    if value <= hard_high:
        return 100.0 - (value - sweet_high) / max(0.01, hard_high - sweet_high) * 35.0
    return _clamp(65.0 - (value - hard_high) * 3.5, 18.0, 65.0)


def move_quality_score(change_15m: float, change_45m: float) -> float:
    score15 = _move_leg_score(change_15m, sweet_low=0.70, sweet_high=4.0, hard_high=8.0)
    score45 = _move_leg_score(change_45m, sweet_low=1.2, sweet_high=9.0, hard_high=18.0)
    return _clamp(score15 * 0.70 + score45 * 0.30)


def saturation_penalty(attention: AttentionSnapshot) -> float:
    move15 = abs(float(attention.change_15m))
    move45 = abs(float(attention.change_45m))
    penalty = 0.0
    if move15 > 7.0:
        penalty += min(20.0, (move15 - 7.0) * 2.0)
    if move45 > 16.0:
        penalty += min(12.0, (move45 - 16.0) * 0.9)
    if attention.overextended:
        penalty += 5.0
    # Fresh volume keeps the event worth *discussing*, but does not erase chase risk.
    if attention.volume_spike >= 8.0:
        penalty *= 0.78
    return min(28.0, penalty)


def _event_class(
    attention: AttentionSnapshot,
    micro: MicroAttentionSnapshot | None,
    demand: float,
) -> str:
    micro_score = float(micro.score) if micro else 50.0
    phase = micro.phase if micro else "unknown"
    if demand >= 68 and micro_score >= 72 and phase == "fresh":
        return "audience_breakout"
    if micro_score >= 75 and attention.score >= 70 and phase in {"fresh", "developing"}:
        return "fresh_event"
    if demand >= 72 and attention.score >= 58:
        return "high_demand_active"
    if attention.score >= 70:
        return "active_market"
    if phase == "stale":
        return "stale_event"
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
    micro: MicroAttentionSnapshot | None = None,
) -> MarketOpportunitySnapshot:
    demand = audience_demand_score(meta, universe)
    volume = volume_anomaly_score(attention.volume_spike)
    move_quality = move_quality_score(attention.change_15m, attention.change_45m)
    micro_score = float(micro.score) if micro else 50.0
    stale = float(micro.stale_penalty) if micro else 0.0

    rr = max(0.0, float(risk_reward))
    actionability = 45.0 + min(max(rr - 1.0, 0.0) * 22.0, 40.0)
    if rr < 1.20:
        actionability -= 18.0
    if attention.overextended:
        actionability -= 7.0
    actionability = _clamp(actionability)

    penalty = saturation_penalty(attention)
    score = (
        demand * 0.34
        + float(attention.score) * 0.20
        + _clamp(technical_score) * 0.17
        + micro_score * 0.13
        + move_quality * 0.08
        + volume * 0.04
        + actionability * 0.04
    )
    if strict_setup:
        score += 2.0
    if not btc_compatible:
        score -= 3.0
    score -= penalty
    score -= stale * 0.45
    score = _clamp(score)

    event = _event_class(attention, micro, demand)
    reason = (
        f"demand={demand:.0f}, fresh15={attention.score:.0f}, micro={micro_score:.0f}, "
        f"vol={volume:.0f}, move={move_quality:.0f}, actionable={actionability:.0f}, "
        f"saturation=-{penalty:.1f}, stale=-{stale:.1f}, event={event}"
    )
    return MarketOpportunitySnapshot(
        score=round(score, 2),
        audience_demand=round(demand, 2),
        fresh_attention=round(float(attention.score), 2),
        micro_freshness=round(micro_score, 2),
        volume_anomaly=round(volume, 2),
        move_quality=round(move_quality, 2),
        actionability=round(actionability, 2),
        saturation_penalty=round(penalty, 2),
        stale_penalty=round(stale, 2),
        event_class=event,
        reason=reason,
    )



def score_audience_event(
    *,
    meta: TrendingMarket | None,
    universe: Sequence[TrendingMarket],
    attention: AttentionSnapshot,
    technical_score: float,
    micro: MicroAttentionSnapshot | None = None,
) -> MarketOpportunitySnapshot:
    """Score a publishable *market event* independently of trade gates.

    This lane answers a different question from ``score_market_opportunity``:
    "is something worth talking about on Square right now?"  ADX, R/R and
    relative-volume hard gates are deliberately not publication prerequisites
    here.  Technical quality is only a small sanity/context component.

    Stale activity and already-saturated moves are still penalized heavily so
    the event lane cannot turn into a generic trending-coin spam feed.
    """
    demand = audience_demand_score(meta, universe)
    volume = volume_anomaly_score(attention.volume_spike)
    move_quality = move_quality_score(attention.change_15m, attention.change_45m)
    micro_score = float(micro.score) if micro else 50.0
    stale = float(micro.stale_penalty) if micro else 0.0
    penalty = saturation_penalty(attention)

    # Event content does not need a valid trade.  A neutral actionability value
    # keeps the shared snapshot schema useful without smuggling fake R/R into
    # the score.
    actionability = 50.0
    score = (
        demand * 0.36
        + float(attention.score) * 0.24
        + micro_score * 0.20
        + move_quality * 0.10
        + volume * 0.04
        + _clamp(technical_score) * 0.06
    )
    score -= penalty * 0.85
    score -= stale * 0.62
    score = _clamp(score)

    event = _event_class(attention, micro, demand)
    reason = (
        f"demand={demand:.0f}, fresh15={attention.score:.0f}, micro={micro_score:.0f}, "
        f"vol={volume:.0f}, move={move_quality:.0f}, tech_context={_clamp(technical_score):.0f}, "
        f"saturation=-{penalty:.1f}, stale=-{stale:.1f}, event={event}"
    )
    return MarketOpportunitySnapshot(
        score=round(score, 2),
        audience_demand=round(demand, 2),
        fresh_attention=round(float(attention.score), 2),
        micro_freshness=round(micro_score, 2),
        volume_anomaly=round(volume, 2),
        move_quality=round(move_quality, 2),
        actionability=actionability,
        saturation_penalty=round(penalty, 2),
        stale_penalty=round(stale, 2),
        event_class=event,
        reason=reason,
    )

def preliminary_interest_score(
    *,
    technical_score: float,
    attention: AttentionSnapshot,
    meta: TrendingMarket | None,
    universe: Sequence[TrendingMarket],
    micro: MicroAttentionSnapshot | None = None,
) -> float:
    """Cheap first-pass score that keeps both high-demand and genuinely fresh events."""
    demand = audience_demand_score(meta, universe)
    volume = volume_anomaly_score(attention.volume_spike)
    move = move_quality_score(attention.change_15m, attention.change_45m)
    micro_score = float(micro.score) if micro else 50.0
    stale = float(micro.stale_penalty) if micro else 0.0
    penalty = saturation_penalty(attention) * 0.45
    score = (
        demand * 0.30
        + _clamp(technical_score) * 0.25
        + float(attention.score) * 0.20
        + micro_score * 0.15
        + move * 0.06
        + volume * 0.04
        - penalty
        - stale * 0.25
    )
    return _clamp(score)
