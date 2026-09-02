"""Main orchestration for Binance Square Bot v11.6 cumulative release.

Pipeline:
1. Scan a broad liquid USDT universe on 5m/15m/1h.
2. Rank by live audience demand/freshness and W2E-oriented market quality.
3. Apply a bounded historical ticker/hour/lane adjustment with exploration and saturation protection.
4. Build a Python-owned entry zone / stop / TP1 / TP2 / TP3 plan when valid.
5. Let DeepSeek V4 Pro write from locked facts; use Mistral only if the primary API is unavailable.
6. Fact-check, anti-template rank, render a chart and publish.
7. Track explicitly published trade targets and post verified outcome follow-ups.
"""
from __future__ import annotations

import logging
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, Iterable, List, Optional, Tuple

import pandas as pd

from runtime import PROJECT_DIR, ProcessLock, load_project_env, setup_logging, write_status

load_project_env()

from btc_context import get_btc_context, get_funding_rate, is_direction_compatible
from attention import (
    AttentionSnapshot, MicroAttentionSnapshot, compute_attention, compute_event_attention,
    compute_micro_attention,
)
from card import generate_card
from chart import generate_chart
from data import get_data
from filters import SignalFilter, SignalScore, get_top_candidates
from history import add_published, cleanup_history, get_recently_published
from indicators import MultiTimeframeIndicators, calculate_multi_timeframe
from memory import PostMemory
from publisher import publish
from publication_guard import PublicationGuard
from quality import PostQualityEvaluator, QualityReport
from engagement import FeedAppealEvaluator
from monetization import ConversionIntentEvaluator, MarketMonetizationSnapshot, score_market_monetization
from opportunity import (
    MarketOpportunitySnapshot, audience_demand_score, preliminary_interest_score,
    score_market_opportunity, score_audience_event,
)
from trend import TrendingMarket, get_base_asset, get_trending_market
from content_variation import detect_signal_angles
from writer import GeneratedPost, _levels, generate_post_candidates, phrase_family_penalty
from trade_plan import plan_summary
from event_writer import (
    event_decision_level, generate_event_candidates, rank_event_candidates,
)
from performance_store import record_publication, reach_recovery_state
from adaptive import AdaptiveAdjustment, score_adaptive, score_content_performance
from reach_editorial import editorial_reach_adjustment
from trade_journal import record_trade_setup, validate_public_plan_text
from outcome_engine import process_outcomes

logger = setup_logging()

PRIMARY_TIMEFRAMES = ("5m", "15m", "1h")
CONFIRMATION_TIMEFRAMES = ("4h", "1d")
COOLDOWN_MIN = int(os.getenv("COOLDOWN_MIN", "240"))
TOP_SYMBOLS = int(os.getenv("TOP_SYMBOLS", "120"))
SHORTLIST_SIZE = int(os.getenv("SHORTLIST_SIZE", "36"))
FINAL_CANDIDATES = int(os.getenv("FINAL_CANDIDATES", "20"))
DATA_WORKERS = max(1, min(int(os.getenv("DATA_WORKERS", "8")), 12))
KLINE_LIMIT = max(220, min(int(os.getenv("KLINE_LIMIT", "260")), 500))
MAX_FUNDING_ABS = float(os.getenv("MAX_FUNDING_ABS", "0.001"))
ENABLE_BALANCED_FALLBACK = os.getenv("ENABLE_BALANCED_FALLBACK", "1").lower() in {
    "1", "true", "yes"
}
POST_VARIANTS = max(4, min(int(os.getenv("POST_VARIANTS", "16")), 16))
MAX_POST_SIMILARITY = float(os.getenv("MAX_POST_SIMILARITY", "0.46"))
MIN_POST_QUALITY = float(os.getenv("MIN_POST_QUALITY", "84"))
MIN_FEED_APPEAL = float(os.getenv("MIN_FEED_APPEAL", "76"))
MIN_W2E_MARKET_SCORE = float(os.getenv("MIN_W2E_MARKET_SCORE", "56"))
W2E_SOFT_FLOOR = float(os.getenv("W2E_SOFT_FLOOR", "40"))
HOT_W2E_FLOOR = float(os.getenv("HOT_W2E_FLOOR", "34"))
MIN_CONVERSION_INTENT = float(os.getenv("MIN_CONVERSION_INTENT", "75"))
MIN_OPPORTUNITY_SCORE = float(os.getenv("MIN_OPPORTUNITY_SCORE", "63"))
MIN_AUDIENCE_DEMAND = float(os.getenv("MIN_AUDIENCE_DEMAND", "24"))
# Event lane is deliberately independent from ADX/R/R hard gates.
MIN_EVENT_SCORE = float(os.getenv("MIN_EVENT_SCORE", "60"))
EVENT_W2E_FLOOR = float(os.getenv("EVENT_W2E_FLOOR", "42"))
EVENT_MIN_DEMAND = float(os.getenv("EVENT_MIN_DEMAND", "20"))
EVENT_LANE_ADVANTAGE = float(os.getenv("EVENT_LANE_ADVANTAGE", "1.5"))
EVENT_MIN_POST_QUALITY = float(os.getenv("EVENT_MIN_POST_QUALITY", "80"))
EVENT_MIN_FEED_APPEAL = float(os.getenv("EVENT_MIN_FEED_APPEAL", "74"))
EVENT_MIN_CONVERSION = float(os.getenv("EVENT_MIN_CONVERSION", "72"))
PRELIM_MIN_SCORE = float(os.getenv("PRELIM_MIN_SCORE", "38"))
W2E_PROXY_MAX_BONUS = float(os.getenv("W2E_PROXY_MAX_BONUS", "5.0"))
W2E_PROXY_MAX_PENALTY = float(os.getenv("W2E_PROXY_MAX_PENALTY", "3.0"))
VALID_PLAN_EVENT_BONUS = float(os.getenv("VALID_PLAN_EVENT_BONUS", "0"))
OBSERVATION_ONLY_EVENT_PENALTY = float(os.getenv("OBSERVATION_ONLY_EVENT_PENALTY", "0"))
STRICT_BTC_FILTER = os.getenv("STRICT_BTC_FILTER", "0").lower() in {"1", "true", "yes"}
DRY_RUN = os.getenv("DRY_RUN", "1").lower() in {"1", "true", "yes"}
PUBLISH_IMAGES = os.getenv("PUBLISH_IMAGES", "1").lower() in {"1", "true", "yes"}
PUBLISH_MEDIA_MODE = os.getenv("PUBLISH_MEDIA_MODE", "chart").strip().lower()
if PUBLISH_MEDIA_MODE not in {"adaptive", "card", "chart", "both", "none"}:
    logger.warning("Unknown PUBLISH_MEDIA_MODE=%s; using adaptive", PUBLISH_MEDIA_MODE)
    PUBLISH_MEDIA_MODE = "adaptive"


def _fetch_symbol_timeframes(symbol: str, intervals: Iterable[str]) -> Dict[str, pd.DataFrame]:
    frames: Dict[str, pd.DataFrame] = {}
    for interval in intervals:
        frame = get_data(symbol, interval=interval, limit=KLINE_LIMIT)
        if frame is None:
            continue
        # Every indicator set uses EMA-50 and other rolling windows. Keeping
        # shorter histories would only create noisy warnings and incomplete setups.
        if len(frame) < 60:
            logger.info(
                "Skip %s %s: only %s closed candles, 60 required",
                symbol,
                interval,
                len(frame),
            )
            continue
        frames[interval] = frame
    return frames


def _fetch_many(symbols: List[str], intervals: Iterable[str]) -> Dict[str, Dict[str, pd.DataFrame]]:
    result: Dict[str, Dict[str, pd.DataFrame]] = {}
    if not symbols:
        return result

    with ThreadPoolExecutor(max_workers=DATA_WORKERS, thread_name_prefix="market-data") as executor:
        futures = {
            executor.submit(_fetch_symbol_timeframes, symbol, tuple(intervals)): symbol
            for symbol in symbols
        }
        for future in as_completed(futures):
            symbol = futures[future]
            try:
                frames = future.result()
                if frames:
                    result[symbol] = frames
            except Exception as exc:
                logger.warning("Data fetch failed for %s: %s", symbol, exc)
    return result


def _preliminary_shortlist(
    primary_data: Dict[str, Dict[str, pd.DataFrame]],
    market_meta: Dict[str, TrendingMarket],
    market_universe: List[TrendingMarket],
) -> List[str]:
    """Build a blended shortlist from audience and live-event baskets.

    One global score can accidentally let many obscure x-volume spikes crowd out
    liquid coins, or do the opposite and hide a genuinely fresh breakout. v9
    explicitly reserves room for both groups, then fills the rest by the combined
    score.
    """
    signal_filter = SignalFilter(min_score=PRELIM_MIN_SCORE)
    rows: List[Tuple[str, float, float, float, float]] = []
    for symbol, frames in primary_data.items():
        if "15m" not in frames or "1h" not in frames:
            continue
        mtf = calculate_multi_timeframe(symbol, frames)
        score = signal_filter.evaluate(mtf)
        if score is None:
            continue
        attention = compute_event_attention(frames.get("15m"), mtf.tf_15m)
        micro = compute_micro_attention(frames.get("5m"))
        meta = market_meta.get(symbol)
        demand = audience_demand_score(meta, market_universe)
        interest = preliminary_interest_score(
            technical_score=score.total, attention=attention, meta=meta,
            universe=market_universe, micro=micro,
        )
        live_event = (
            micro.score * 0.48
            + attention.score * 0.34
            + min(abs(attention.change_15m) * 7.0, 18.0)
        )
        if (
            score.total >= PRELIM_MIN_SCORE
            or demand >= 60.0
            or attention.score >= 66
            or micro.score >= 68
            or (micro.phase == "fresh" and micro.volume_spike_5m >= 2.0)
        ):
            rows.append((symbol, interest, demand, live_event, score.total))
            logger.debug(
                "Prelim %s tech=%.1f attention=%.1f micro=%.1f/%s demand=%.1f vol15=x%.2f vol5=x%.2f interest=%.1f",
                symbol, score.total, attention.score, micro.score, micro.phase, demand,
                attention.volume_spike, micro.volume_spike_5m, interest,
            )

    if not rows:
        return []

    audience_quota = max(6, int(SHORTLIST_SIZE * 0.35))
    event_quota = max(6, int(SHORTLIST_SIZE * 0.35))
    trade_quota = max(4, int(SHORTLIST_SIZE * 0.20))
    selected: List[str] = []
    seen: set[str] = set()

    def add_from(items: List[Tuple[str, float, float, float, float]], limit: int) -> None:
        added = 0
        for symbol, _, _, _, _ in items:
            if symbol in seen:
                continue
            selected.append(symbol)
            seen.add(symbol)
            added += 1
            if added >= limit or len(selected) >= SHORTLIST_SIZE:
                return

    audience_rows = sorted(rows, key=lambda row: (row[2], row[1]), reverse=True)
    event_rows = sorted(rows, key=lambda row: (row[3], row[1]), reverse=True)
    trade_rows = sorted(rows, key=lambda row: (row[4], row[1]), reverse=True)
    overall_rows = sorted(rows, key=lambda row: row[1], reverse=True)
    add_from(audience_rows, audience_quota)
    add_from(event_rows, event_quota)
    add_from(trade_rows, trade_quota)
    add_from(overall_rows, SHORTLIST_SIZE)
    return selected[:SHORTLIST_SIZE]

def _build_full_candidates(
    shortlist: List[str],
    primary_data: Dict[str, Dict[str, pd.DataFrame]],
    confirmation_data: Dict[str, Dict[str, pd.DataFrame]],
) -> List[MultiTimeframeIndicators]:
    candidates: List[MultiTimeframeIndicators] = []
    for symbol in shortlist:
        frames = dict(primary_data.get(symbol, {}))
        frames.update(confirmation_data.get(symbol, {}))
        if "15m" not in frames:
            continue
        mtf = calculate_multi_timeframe(symbol, frames)
        if mtf.tf_15m is not None:
            candidates.append(mtf)
    return candidates


def _w2e_proxy_adjustment(monetization: MarketMonetizationSnapshot, *, plan_valid: bool) -> float:
    """Small revenue-proxy nudge; market opportunity and factual safety still dominate."""
    centered = (float(monetization.score) - 50.0) * 0.055
    actionable = (float(monetization.actionability_score) - 50.0) * 0.035
    # W2E cannot be learned directly from the web account view, so this is only
    # a bounded proxy: actionable, fully publishable plans get a modest preference.
    plan = 1.5 if plan_valid else -1.2
    value = centered + actionable + plan
    return max(-W2E_PROXY_MAX_PENALTY, min(W2E_PROXY_MAX_BONUS, value))


def _w2e_candidate_gate(
    score: SignalScore,
    attention: AttentionSnapshot,
    micro: MicroAttentionSnapshot,
    monetization: MarketMonetizationSnapshot,
    opportunity: MarketOpportunitySnapshot,
) -> Tuple[bool, str]:
    """Audience-first W2E gate with a controlled fresh-event escape hatch.

    Normal posts need both a strong opportunity and reasonable W2E market quality.
    A genuinely fresh 5m event may pass with lower baseline demand, but stale raw
    volume spikes cannot.
    """
    if micro.phase == "stale" and opportunity.audience_demand < 78.0:
        return False, "stale event"

    if opportunity.score >= MIN_OPPORTUNITY_SCORE and monetization.score >= W2E_SOFT_FLOOR:
        return True, "standard"

    if (
        opportunity.event_class == "audience_breakout"
        and opportunity.audience_demand >= 58.0
        and monetization.score >= 42.0
        and score.total >= 58.0
    ):
        return True, "audience breakout"

    if (
        opportunity.event_class == "high_demand_active"
        and opportunity.audience_demand >= 70.0
        and opportunity.score >= MIN_OPPORTUNITY_SCORE - 5.0
        and monetization.score >= 45.0
    ):
        return True, "high-demand active"

    if (
        opportunity.event_class == "fresh_event"
        and micro.phase in {"fresh", "developing"}
        and micro.score >= 74.0
        and opportunity.audience_demand >= 18.0
        and attention.score >= 66.0
        and score.total >= 62.0
        and monetization.score >= HOT_W2E_FLOOR
    ):
        return True, "fresh-event override"

    return False, "below audience/opportunity/W2E gates"

def _choose_market_candidate(
    ranked: List[Tuple[MultiTimeframeIndicators, SignalScore]],
    strict_symbols: set[str],
    btc,
    memory: PostMemory,
    primary_data: Dict[str, Dict[str, pd.DataFrame]],
    market_meta: Dict[str, TrendingMarket],
    market_universe: List[TrendingMarket],
) -> Optional[Tuple[
    MultiTimeframeIndicators,
    SignalScore,
    Optional[float],
    AttentionSnapshot,
    MicroAttentionSnapshot,
    MarketMonetizationSnapshot,
    MarketOpportunitySnapshot,
    Dict[str, object],
    float,
    AdaptiveAdjustment,
]]:
    """Choose the best TRADE-lane candidate among technically defensible setups."""
    frequencies = memory.signal_type_frequency(24)
    last_signal_types = memory.get_last_signal_types(5)
    eligible = []

    for mtf, score in ranked:
        btc_compatible = not btc or is_direction_compatible(score.direction, btc)
        if STRICT_BTC_FILTER and not btc_compatible:
            logger.info(
                "Skip %s: %s setup conflicts with BTC %s bias",
                mtf.symbol, score.direction, btc.bias,
            )
            continue

        funding = get_funding_rate(mtf.symbol)
        if funding is not None and abs(funding) > MAX_FUNDING_ABS:
            crowded = (funding > 0 and score.direction == "long") or (
                funding < 0 and score.direction == "short"
            )
            if crowded:
                logger.info(
                    "Skip %s: crowded %s funding %.4f%%",
                    mtf.symbol, score.direction, funding * 100.0,
                )
                continue

        angles = detect_signal_angles(mtf.tf_15m, score.direction, mtf)
        best_angle = min(
            angles[:4],
            key=lambda item: (frequencies.get(item.id, 0), -item.weight),
        )
        repeat_count = frequencies.get(best_angle.id, 0)
        immediate_repeat = 1 if best_angle.id in last_signal_types[-2:] else 0
        diversity_penalty = min(9.0, repeat_count * 1.25 + immediate_repeat * 3.0)

        raw_15m = primary_data.get(mtf.symbol, {}).get("15m")
        raw_5m = primary_data.get(mtf.symbol, {}).get("5m")
        attention = compute_attention(raw_15m, mtf.tf_15m, score.direction)
        micro = compute_micro_attention(raw_5m)

        # v9 validates the *public* plan before the market event can win the race.
        # Internal TP3 R/R is not enough if the post would show a 1:1 first target
        # or a stop wider than we are willing to present to readers.
        levels = _levels(mtf.tf_15m, score.direction)
        if not levels.get("plan_valid", False):
            logger.info("Skip %s: public plan rejected: %s", mtf.symbol, plan_summary(levels))
            continue

        meta = market_meta.get(mtf.symbol)
        universe_size = max(1, len(market_universe))
        if meta is None:
            monetization = score_market_monetization(
                quote_volume_24h=attention.turnover_1h * 24.0,
                trade_count_24h=0.0,
                abs_change_24h=abs(attention.change_45m) * 8.0,
                trend_rank=universe_size,
                trend_universe_size=universe_size,
                attention_score=attention.score,
                change_15m=attention.change_15m,
                volume_spike=attention.volume_spike,
                risk_reward=float(levels.get("public_rr", score.risk_reward)),
                overextended=attention.overextended,
                micro_freshness=micro.score,
            )
        else:
            monetization = score_market_monetization(
                quote_volume_24h=meta.quote_volume,
                trade_count_24h=meta.trade_count,
                abs_change_24h=abs(meta.change_pct),
                trend_rank=meta.rank,
                trend_universe_size=universe_size,
                attention_score=attention.score,
                change_15m=attention.change_15m,
                volume_spike=attention.volume_spike,
                risk_reward=float(levels.get("public_rr", score.risk_reward)),
                overextended=attention.overextended,
                micro_freshness=micro.score,
            )

        opportunity = score_market_opportunity(
            meta=meta,
            universe=market_universe,
            attention=attention,
            technical_score=score.total,
            risk_reward=float(levels.get("public_rr", score.risk_reward)),
            strict_setup=mtf.symbol in strict_symbols,
            btc_compatible=btc_compatible,
            micro=micro,
        )
        gate_allowed, gate_mode = _w2e_candidate_gate(score, attention, micro, monetization, opportunity)

        # Public plan quality is a small tie-breaker. Market attention still leads,
        # but a cleaner actionable plan beats an equally hot 1.3-R/R alternative.
        plan_rr = float(levels.get("public_rr", 0.0))
        plan_bonus = min(4.0, max(0.0, (plan_rr - 1.30) * 2.0))
        event_bonus = {
            "audience_breakout": 5.0,
            "fresh_event": 3.0,
            "high_demand_active": 2.0,
            "active_market": 0.5,
            "stale_event": -7.0,
        }.get(opportunity.event_class, 0.0)
        demand_bonus = min(4.0, max(0.0, (opportunity.audience_demand - 65.0) / 8.0))
        adaptive = score_adaptive(
            symbol=get_base_asset(mtf.symbol), lane="TRADE", live_score=opportunity.score,
            event_class=opportunity.event_class, micro_score=micro.score,
        )
        w2e_proxy_bonus = _w2e_proxy_adjustment(monetization, plan_valid=True)
        adjusted_score = (
            opportunity.score - diversity_penalty + plan_bonus + event_bonus + demand_bonus
            + adaptive.total + w2e_proxy_bonus
        )

        logger.info(
            "Candidate %s tech=%.1f attention=%.1f micro=%.1f/%s demand=%.1f w2e=%.1f opportunity=%.1f final=%.1f "
            "adaptive=%+.1f w2e_proxy=%+.1f gate=%s profile=%s angle=%s 5m=%+.2f%% 15m=%+.2f%% vol15=x%.2f vol5=x%.2f "
            "plan_R3=%.2f state=%s [%s] [%s]",
            mtf.symbol, score.total, attention.score, micro.score, micro.phase, opportunity.audience_demand,
            monetization.score, opportunity.score, adjusted_score, adaptive.total, w2e_proxy_bonus, gate_mode,
            "strict" if mtf.symbol in strict_symbols else "balanced", best_angle.id,
            micro.change_5m, attention.change_15m, attention.volume_spike, micro.volume_spike_5m,
            float(levels.get("rr_tp3", levels.get("public_rr", 0.0))), levels.get("trade_state"), opportunity.reason, adaptive.reason,
        )

        if not gate_allowed:
            logger.info(
                "Skip %s: opportunity %.1f / W2E %.1f not strong enough",
                mtf.symbol, opportunity.score, monetization.score,
            )
            continue

        # Very low baseline demand is allowed only for a true live event.
        if opportunity.audience_demand < MIN_AUDIENCE_DEMAND:
            fresh_exception = (
                opportunity.event_class == "fresh_event"
                and micro.phase in {"fresh", "developing"}
                and micro.score >= 78.0
                and attention.score >= 72.0
            )
            if not fresh_exception:
                logger.info(
                    "Skip %s: audience demand %.1f < %.1f without exceptional fresh event",
                    mtf.symbol, opportunity.audience_demand, MIN_AUDIENCE_DEMAND,
                )
                continue

        eligible.append((
            adjusted_score, mtf, score, funding, best_angle.id, attention, micro, monetization, opportunity, levels, adaptive
        ))

    if not eligible:
        return None

    eligible.sort(key=lambda item: item[0], reverse=True)
    selection_score, mtf, score, funding, _, attention, micro, monetization, opportunity, levels, adaptive = eligible[0]
    return mtf, score, funding, attention, micro, monetization, opportunity, levels, float(selection_score), adaptive


def _event_candidate_gate(
    score: SignalScore,
    attention: AttentionSnapshot,
    micro: MicroAttentionSnapshot,
    monetization: MarketMonetizationSnapshot,
    opportunity: MarketOpportunitySnapshot,
) -> Tuple[bool, str]:
    """Gate the EVENT lane without requiring ADX/R/R/volume trade gates.

    The lane still needs a real audience or a genuinely fresh event. A popular
    but dead ticker (for example high demand with stale 5m activity) does not
    pass just because the coin is large.
    """
    if micro.phase == "stale" and attention.score < 72.0:
        return False, "stale event"

    if (
        opportunity.score >= MIN_EVENT_SCORE
        and monetization.score >= EVENT_W2E_FLOOR
        and (
            opportunity.audience_demand >= 55.0
            or attention.score >= 70.0
            or micro.score >= 72.0
        )
    ):
        return True, "event standard"

    if (
        opportunity.audience_demand >= 72.0
        and opportunity.score >= MIN_EVENT_SCORE - 3.0
        and attention.score >= 48.0
        and micro.score >= 45.0
        and monetization.score >= 44.0
    ):
        return True, "high-demand event"

    if (
        opportunity.event_class in {"fresh_event", "audience_breakout"}
        and micro.phase in {"fresh", "developing"}
        and micro.score >= 72.0
        and attention.score >= 62.0
        and opportunity.audience_demand >= EVENT_MIN_DEMAND
        and opportunity.score >= MIN_EVENT_SCORE - 1.5
        and monetization.score >= 35.0
    ):
        return True, "fresh-event override"

    return False, "below event audience/freshness gates"


def _broad_signal_scores(
    candidates: List[MultiTimeframeIndicators],
) -> Dict[str, SignalScore]:
    """Score every shortlist item without using publication hard gates."""
    broad_filter = SignalFilter(min_score=0.0, profile="balanced")
    result: Dict[str, SignalScore] = {}
    for mtf in candidates:
        score = broad_filter.evaluate(mtf)
        if score is not None:
            result[mtf.symbol] = score
    return result


def _choose_event_candidate(
    candidates: List[MultiTimeframeIndicators],
    broad_scores: Dict[str, SignalScore],
    btc,
    memory: PostMemory,
    primary_data: Dict[str, Dict[str, pd.DataFrame]],
    market_meta: Dict[str, TrendingMarket],
    market_universe: List[TrendingMarket],
) -> Optional[Tuple[
    MultiTimeframeIndicators,
    SignalScore,
    AttentionSnapshot,
    MicroAttentionSnapshot,
    MarketMonetizationSnapshot,
    MarketOpportunitySnapshot,
    Dict[str, object],
    float,
    AdaptiveAdjustment,
]]:
    """Choose an audience/event candidate independently of signal gates."""
    eligible = []
    recent_formats = memory.get_last_content_formats(6)
    recent_event_count = sum(str(fmt).startswith("event_") for fmt in recent_formats[-4:])

    for mtf in candidates:
        score = broad_scores.get(mtf.symbol)
        if score is None or mtf.tf_15m is None:
            continue
        raw_15m = primary_data.get(mtf.symbol, {}).get("15m")
        raw_5m = primary_data.get(mtf.symbol, {}).get("5m")
        attention = compute_event_attention(raw_15m, mtf.tf_15m)
        micro = compute_micro_attention(raw_5m)
        meta = market_meta.get(mtf.symbol)
        universe_size = max(1, len(market_universe))

        # Optional plan: event content can use it if it is clean, but the event
        # itself is never rejected merely because the plan is not clean.
        levels = _levels(mtf.tf_15m, score.direction)
        plan_valid = bool(levels.get("plan_valid", False))
        rr_for_market = float(levels.get("public_rr", score.risk_reward)) if plan_valid else 0.0

        if meta is None:
            monetization = score_market_monetization(
                quote_volume_24h=attention.turnover_1h * 24.0,
                trade_count_24h=0.0,
                abs_change_24h=abs(attention.change_45m) * 8.0,
                trend_rank=universe_size,
                trend_universe_size=universe_size,
                attention_score=attention.score,
                change_15m=attention.change_15m,
                volume_spike=attention.volume_spike,
                risk_reward=rr_for_market,
                overextended=attention.overextended,
                micro_freshness=micro.score,
                observation_only=not plan_valid,
            )
        else:
            monetization = score_market_monetization(
                quote_volume_24h=meta.quote_volume,
                trade_count_24h=meta.trade_count,
                abs_change_24h=abs(meta.change_pct),
                trend_rank=meta.rank,
                trend_universe_size=universe_size,
                attention_score=attention.score,
                change_15m=attention.change_15m,
                volume_spike=attention.volume_spike,
                risk_reward=rr_for_market,
                overextended=attention.overextended,
                micro_freshness=micro.score,
                observation_only=not plan_valid,
            )

        opportunity = score_audience_event(
            meta=meta,
            universe=market_universe,
            attention=attention,
            technical_score=score.total,
            micro=micro,
        )
        allowed, gate_mode = _event_candidate_gate(score, attention, micro, monetization, opportunity)

        event_bonus = {
            "audience_breakout": 6.0,
            "fresh_event": 4.5,
            "high_demand_active": 3.0,
            "active_market": 1.0,
            "stale_event": -8.0,
        }.get(opportunity.event_class, 0.0)
        demand_bonus = min(5.0, max(0.0, (opportunity.audience_demand - 65.0) / 7.0))
        plan_bonus = VALID_PLAN_EVENT_BONUS if plan_valid else -OBSERVATION_ONLY_EVENT_PENALTY
        rotation_adjustment = 0.0
        if recent_event_count >= 2:
            rotation_adjustment -= 7.0
        elif recent_formats and str(recent_formats[-1]).startswith("event_"):
            rotation_adjustment -= 3.0
        elif recent_event_count == 0:
            rotation_adjustment += 1.5
        adaptive = score_adaptive(
            symbol=get_base_asset(mtf.symbol), lane="EVENT", live_score=opportunity.score,
            event_class=opportunity.event_class, micro_score=micro.score,
        )
        w2e_proxy_bonus = _w2e_proxy_adjustment(monetization, plan_valid=plan_valid)
        selection_score = (
            opportunity.score + event_bonus + demand_bonus + plan_bonus + rotation_adjustment
            + adaptive.total + w2e_proxy_bonus
        )

        logger.info(
            "Event candidate %s tech_context=%.1f attention=%.1f micro=%.1f/%s demand=%.1f w2e=%.1f event_score=%.1f final=%.1f "
            "adaptive=%+.1f w2e_proxy=%+.1f gate=%s plan=%s tech_gates=%s 5m=%+.2f%% 15m=%+.2f%% vol15=x%.2f vol5=x%.2f [%s] [%s]",
            mtf.symbol, score.total, attention.score, micro.score, micro.phase, opportunity.audience_demand,
            monetization.score, opportunity.score, selection_score, adaptive.total, w2e_proxy_bonus, gate_mode,
            "valid" if plan_valid else "observation_only",
            "pass" if score.passed_gates else "bypassed",
            micro.change_5m, attention.change_15m, attention.volume_spike, micro.volume_spike_5m,
            opportunity.reason, adaptive.reason,
        )
        if not allowed:
            continue
        eligible.append((
            selection_score, mtf, score, attention, micro, monetization, opportunity, levels, adaptive
        ))

    if not eligible:
        return None
    eligible.sort(key=lambda item: item[0], reverse=True)
    selection_score, mtf, score, attention, micro, monetization, opportunity, levels, adaptive = eligible[0]
    return mtf, score, attention, micro, monetization, opportunity, levels, float(selection_score), adaptive


def _best_event_post_variant(
    *,
    basic: str,
    mtf: MultiTimeframeIndicators,
    score: SignalScore,
    levels: Dict[str, object],
    memory: PostMemory,
    btc,
    attention: AttentionSnapshot,
    micro: MicroAttentionSnapshot,
    opportunity: MarketOpportunitySnapshot,
    monetization: MarketMonetizationSnapshot,
) -> Optional[Tuple[GeneratedPost, QualityReport]]:
    try:
        drafts = generate_event_candidates(
            basic=basic,
            mtf=mtf,
            direction=score.direction,
            levels=levels,
            memory=memory,
            btc=btc,
            attention=attention,
            micro=micro,
            opportunity=opportunity,
            monetization=monetization,
            variant_count=POST_VARIANTS,
        )
    except Exception as exc:
        logger.error("Event post candidate generation failed: %s", exc)
        return None
    return rank_event_candidates(
        drafts=drafts,
        basic=basic,
        memory=memory,
        min_feed_appeal=EVENT_MIN_FEED_APPEAL,
        min_conversion=EVENT_MIN_CONVERSION,
        min_quality=EVENT_MIN_POST_QUALITY,
        max_similarity=MAX_POST_SIMILARITY,
        plan_available=bool(levels.get("plan_valid", False)),
        event_class=opportunity.event_class,
        direction=score.direction if levels.get("plan_valid", False) else "observation",
    )


def _text_similarity(left: str, right: str) -> float:
    return PostMemory.compare_texts(left, right)


def _best_post_variant(
    *,
    symbol: str,
    basic: str,
    mtf: MultiTimeframeIndicators,
    score: SignalScore,
    levels: Dict[str, float],
    memory: PostMemory,
    btc,
    attention: AttentionSnapshot,
    micro: MicroAttentionSnapshot,
    opportunity: MarketOpportunitySnapshot,
    monetization: MarketMonetizationSnapshot,
) -> Optional[Tuple[GeneratedPost, QualityReport]]:
    evaluator = PostQualityEvaluator()
    appeal_evaluator = FeedAppealEvaluator()
    conversion_evaluator = ConversionIntentEvaluator()
    variants: List[Tuple[GeneratedPost, QualityReport, float]] = []
    generated_texts: List[str] = []
    recent_styles = memory.get_last_post_styles(24)
    recent_signals = memory.get_last_signal_types(24)
    recent_formats = memory.get_last_content_formats(30)
    recent_visuals = memory.get_last_visual_styles(20)
    recent_texts = memory.recent_texts(8)
    recent_had_emoji = any(any(mark in text for mark in ("⚡", "⚠️", "👀")) for text in recent_texts)

    try:
        drafts = generate_post_candidates(
            symbol=symbol,
            basic=basic,
            mtf=mtf,
            score=score,
            memory=memory,
            levels=levels,
            btc=btc,
            attention=attention,
            micro=micro,
            opportunity=opportunity,
            monetization=monetization,
            variant_count=POST_VARIANTS,
        )
    except Exception as exc:
        logger.error("Post candidate generation failed: %s", exc)
        return None

    for index, draft in enumerate(drafts):
        try:
            report = evaluator.report(
                draft.text,
                basic=basic,
                direction=score.direction,
                levels=levels,
                content_format=draft.content_format,
                headline=draft.headline,
            )
            memory_similarity = memory.similarity_score(draft.text)
            local_similarity = max(
                (_text_similarity(draft.text, other) for other in generated_texts),
                default=0.0,
            )
            generated_texts.append(draft.text)

            similarity_penalty = max(0.0, memory_similarity - 0.28) * 72.0
            similarity_penalty += max(0.0, local_similarity - 0.52) * 25.0

            style_repeats = recent_styles.count(draft.style_id)
            signal_repeats = recent_signals.count(draft.signal_type)
            format_repeats = recent_formats.count(draft.content_format)
            visual_repeats = recent_visuals.count(draft.visual_style)
            novelty_penalty = min(5.0, style_repeats * 0.8)
            novelty_penalty += min(5.0, signal_repeats * 0.9)
            novelty_penalty += min(12.0, format_repeats * 2.0)
            novelty_penalty += min(6.0, visual_repeats * 1.0)
            if recent_formats[-1:] == [draft.content_format]:
                novelty_penalty += 5.0
            if recent_visuals[-1:] == [draft.visual_style]:
                novelty_penalty += 2.5
            if recent_signals[-1:] == [draft.signal_type]:
                novelty_penalty += 2.0

            # v9: factual validity is a hard gate. Ranking rewards a post that
            # fits the live event *and* differs semantically from recent output.
            editorial_bonus = 3.0 if draft.content_format not in recent_formats[-7:] else 0.0
            context_bonus = 0.0
            if opportunity.event_class in {"audience_breakout", "fresh_event"}:
                if draft.content_format in {"hot_take", "market_story", "volume_read", "micro_note"}:
                    context_bonus += 7.0
            if attention.overextended or abs(attention.change_15m) >= 3.0:
                if draft.content_format in {"no_chase", "two_paths", "risk_first"}:
                    context_bonus += 6.0
            if levels.get("trade_state") == "decision_now" and draft.content_format in {"one_level", "trade_map", "risk_first"}:
                context_bonus += 4.0
            if opportunity.audience_demand >= 70 and draft.content_format in {"hot_take", "micro_note", "market_story"}:
                context_bonus += 3.0

            appeal = appeal_evaluator.report(draft.text)
            conversion = conversion_evaluator.report(draft.text, basic)

            human_format_bonus = 5.0 if draft.content_format in {
                "hot_take", "one_level", "no_chase", "two_paths",
                "market_story", "micro_note", "volume_read",
            } else 2.0

            # Mobile-first sweet spot: enough substance to be useful, short enough
            # to scan before the chart.
            length_bonus = 4.0 if 190 <= len(draft.text) <= 500 else 0.0
            if len(draft.text) > 520:
                length_bonus -= min(10.0, (len(draft.text) - 520) / 5.0)

            has_emoji = any(mark in draft.headline for mark in ("⚡", "⚠️", "👀"))
            aesthetic_bonus = 0.0
            if has_emoji and not recent_had_emoji:
                aesthetic_bonus = 1.6
            elif has_emoji and recent_had_emoji:
                aesthetic_bonus = -2.0

            robotic_penalty = 0.0
            lowered_text = draft.text.lower().replace("ё", "е")
            for phrase in (
                "направление у идеи", "граница ошибки", "диапазон контроля",
                "параметры сценария", "карта исполнения", "правило исполнения",
            ):
                if phrase in lowered_text:
                    robotic_penalty += 12.0

            phrase_penalty = phrase_family_penalty(draft.text, recent_texts)
            author_bonus = 1.0 if not draft.source.startswith("deterministic") else 0.0
            content_adaptive = score_content_performance(
                lane="TRADE",
                content_format=draft.content_format,
                writer_source=draft.source,
                event_class=opportunity.event_class,
                direction=score.direction,
            )
            editorial = editorial_reach_adjustment(draft.text)

            adjusted_score = (
                report.score * 0.30
                + appeal.score * 0.34
                + conversion.score * 0.36
                - similarity_penalty
                - novelty_penalty
                - robotic_penalty
                - phrase_penalty
                + editorial_bonus
                + context_bonus
                + human_format_bonus
                + length_bonus
                + aesthetic_bonus
                + author_bonus
                + content_adaptive.total
                + editorial.score
            )
            logger.info(
                "Post candidate %s: source=%s format=%s visual=%s angle=%s quality=%.1f appeal=%.1f conversion=%.1f valid=%s "
                "memory_sim=%.2f local_sim=%.2f phrase_penalty=%.1f content_adaptive=%+.1f editorial=%+.1f adjusted=%.1f [%s] [%s]",
                index + 1,
                draft.source,
                draft.content_format,
                draft.visual_style,
                draft.signal_type,
                report.score,
                appeal.score,
                conversion.score,
                report.valid,
                memory_similarity,
                local_similarity,
                phrase_penalty,
                content_adaptive.total,
                editorial.score,
                adjusted_score,
                content_adaptive.reason,
                editorial.reason,
            )

            if (
                report.valid
                and memory_similarity < MAX_POST_SIMILARITY
                and appeal.score >= MIN_FEED_APPEAL
                and conversion.score >= MIN_CONVERSION_INTENT
            ):
                variants.append((draft, report, adjusted_score))
            elif report.valid and conversion.score < MIN_CONVERSION_INTENT:
                logger.info(
                    "Candidate %s rejected for low W2E conversion intent: %.1f < %.1f",
                    index + 1, conversion.score, MIN_CONVERSION_INTENT,
                )
            elif report.valid and appeal.score < MIN_FEED_APPEAL:
                logger.info(
                    "Candidate %s rejected for low feed appeal: %.1f < %.1f",
                    index + 1, appeal.score, MIN_FEED_APPEAL,
                )
            elif report.valid:
                logger.info(
                    "Candidate %s rejected as too similar: %.3f >= %.3f",
                    index + 1,
                    memory_similarity,
                    MAX_POST_SIMILARITY,
                )
            else:
                logger.warning(
                    "Candidate %s rejected reasons: %s",
                    index + 1,
                    ", ".join(report.reasons),
                )
        except Exception as exc:
            logger.warning("Post candidate %s failed: %s", index + 1, exc)

    if not variants:
        return None
    variants.sort(key=lambda item: item[2], reverse=True)
    best_draft, best_report, _ = variants[0]
    if best_report.score < MIN_POST_QUALITY:
        logger.info(
            "Best post quality %.1f is below MIN_POST_QUALITY %.1f",
            best_report.score,
            MIN_POST_QUALITY,
        )
        return None
    return best_draft, best_report



def _log_near_misses(candidates: List[MultiTimeframeIndicators], limit: int = 3) -> None:
    """Explain the strongest rejected setups without changing publication rules."""
    signal_filter = SignalFilter(profile="strict")
    near = []
    for mtf in candidates:
        score = signal_filter.evaluate(mtf)
        if score is None:
            continue
        near.append((score.total, mtf.symbol, score))
    near.sort(key=lambda item: item[0], reverse=True)
    for total, symbol, score in near[: max(1, limit)]:
        reasons = "; ".join(score.gate_reasons) if score.gate_reasons else "score below threshold"
        logger.info(
            "Near miss %s score=%.1f direction=%s: %s",
            symbol,
            total,
            score.direction,
            reasons,
        )

def _cleanup_files(paths: Iterable[Optional[str]]) -> None:
    for path in paths:
        if not path:
            continue
        try:
            if os.path.exists(path):
                os.remove(path)
        except OSError as exc:
            logger.debug("Temporary file cleanup failed for %s: %s", path, exc)


def _try_outcome_fallback(*, memory: PostMemory, guard: PublicationGuard, recovery_mode: bool) -> bool:
    """Publish a queued TP3 only when no fresh post won and reach is healthy."""
    if recovery_mode:
        logger.info("Outcome follow-up postponed while reach recovery mode is active")
        return False
    try:
        if process_outcomes(memory=memory, guard=guard, dry_run=DRY_RUN, refresh_only=False):
            write_status("published", "verified trade outcome fallback published", lane="outcome")
            return True
    except Exception as exc:
        logger.warning("Outcome fallback cycle failed: %s", exc)
    return False


def _run_once() -> int:
    cleanup_history()
    memory = PostMemory()
    guard = PublicationGuard(memory.items)
    recovery_mode, rolling_reach, reach_baseline = reach_recovery_state()
    logger.info(
        "Run start project=%s cwd=%s dry_run=%s memory=%s",
        PROJECT_DIR,
        os.getcwd(),
        DRY_RUN,
        memory.path,
    )
    if not DRY_RUN:
        pacing = guard.preflight()
        if not pacing.allowed:
            next_time = pacing.next_allowed_at.isoformat() if pacing.next_allowed_at else "n/a"
            logger.info("Cron check skipped: %s; next=%s", pacing.reason, next_time)
            write_status("skipped", pacing.reason, next_allowed_at=next_time)
            return 0
        logger.info("Publication guard: %s", pacing.reason)

    # Refresh outcome truth first, but never let a queued TP3 steal a slot from a
    # live market candidate. Publication is a fallback after fresh selection.
    try:
        process_outcomes(memory=memory, guard=guard, dry_run=DRY_RUN, refresh_only=True)
    except Exception as exc:
        # Outcome tracking is additive. A transient market-data/card failure must
        # never block the normal Square publishing pipeline.
        logger.warning("Outcome Engine cycle failed; continuing fresh scan: %s", exc)

    trending_market = get_trending_market(limit=TOP_SYMBOLS)
    if not trending_market:
        logger.error("No trending symbols found")
        return 1
    market_meta = {item.symbol: item for item in trending_market}
    symbols = [item.symbol for item in trending_market]

    recent = set(get_recently_published(minutes=COOLDOWN_MIN))
    symbols = [symbol for symbol in symbols if symbol not in recent]
    logger.info("Symbols after cooldown: %s", len(symbols))
    if not symbols:
        _try_outcome_fallback(memory=memory, guard=guard, recovery_mode=recovery_mode)
        return 0

    btc = get_btc_context()
    if btc:
        logger.info(
            "BTC bias=%s, 1h=%+.2f%%, 4h=%+.2f%%, 24h=%+.2f%%",
            btc.bias,
            btc.change_1h,
            btc.change_4h,
            btc.change_24h,
        )

    primary_data = _fetch_many(symbols, PRIMARY_TIMEFRAMES)
    shortlist = _preliminary_shortlist(primary_data, market_meta, trending_market)
    logger.info("Preliminary shortlist: %s", ", ".join(shortlist) if shortlist else "empty")
    if not shortlist:
        _try_outcome_fallback(memory=memory, guard=guard, recovery_mode=recovery_mode)
        return 0

    confirmation_data = _fetch_many(shortlist, CONFIRMATION_TIMEFRAMES)
    candidates = _build_full_candidates(shortlist, primary_data, confirmation_data)
    # ---------------------------------------------------------------
    # v9.1 DUAL LANE
    # TRADE: strict/balanced technical gates + clean public plan.
    # EVENT: every shortlist item is evaluated for audience/freshness even
    #        when ADX/R/R/relative-volume gates rejected it as a trade.
    # ---------------------------------------------------------------
    broad_scores = _broad_signal_scores(candidates)

    strict_ranked = get_top_candidates(
        candidates,
        top_n=FINAL_CANDIDATES,
        require_gates=True,
        profile="strict",
    )
    strict_symbols = {mtf.symbol for mtf, _ in strict_ranked}
    ranked = list(strict_ranked)

    if ENABLE_BALANCED_FALLBACK:
        balanced_ranked = get_top_candidates(
            candidates,
            top_n=FINAL_CANDIDATES,
            require_gates=True,
            profile="balanced",
        )
        existing = {mtf.symbol for mtf, _ in ranked}
        ranked.extend((mtf, score) for mtf, score in balanced_ranked if mtf.symbol not in existing)

    logger.info(
        "Trade pool: %s candidates (%s strict, %s balanced-only); Event pool: %s shortlist candidates",
        len(ranked), len(strict_symbols), max(0, len(ranked) - len(strict_symbols)), len(broad_scores),
    )

    trade_chosen = (
        _choose_market_candidate(
            ranked, strict_symbols, btc, memory, primary_data, market_meta, trending_market
        )
        if ranked else None
    )
    event_chosen = _choose_event_candidate(
        candidates, broad_scores, btc, memory, primary_data, market_meta, trending_market
    )

    if trade_chosen is None and event_chosen is None:
        logger.info("No TRADE or EVENT candidate passed publication gates")
        _log_near_misses(candidates)
        write_status("skipped", "no candidate passed dual-lane market selection")
        _try_outcome_fallback(memory=memory, guard=guard, recovery_mode=recovery_mode)
        return 0

    lane = "trade"
    funding: Optional[float] = None
    if trade_chosen is not None:
        (
            trade_mtf, trade_score, trade_funding, trade_attention, trade_micro,
            trade_monetization, trade_opportunity, trade_levels, trade_selection_score, trade_adaptive,
        ) = trade_chosen
    else:
        trade_selection_score = float("-inf")

    if event_chosen is not None:
        (
            event_mtf, event_score, event_attention, event_micro, event_monetization,
            event_opportunity, event_levels, event_selection_score, event_adaptive,
        ) = event_chosen
    else:
        event_selection_score = float("-inf")

    # Two consecutive TRADE publications saturate the feed. Prefer a genuinely
    # eligible EVENT next; never manufacture an event merely for rotation.
    recent_lanes = memory.get_last_lanes(2)
    if recent_lanes == ["TRADE", "TRADE"] and event_chosen is not None:
        event_selection_score += 8.0
        logger.info("Lane saturation: two recent TRADE posts, EVENT receives +8.0")

    if event_chosen is not None and (
        trade_chosen is None or event_selection_score >= trade_selection_score + EVENT_LANE_ADVANTAGE
    ):
        lane = "event"
        best_mtf = event_mtf
        best_score = event_score
        attention = event_attention
        micro = event_micro
        monetization = event_monetization
        opportunity = event_opportunity
        levels = event_levels
        selection_score = event_selection_score
        adaptive = event_adaptive
    else:
        lane = "trade"
        best_mtf = trade_mtf
        best_score = trade_score
        funding = trade_funding
        attention = trade_attention
        micro = trade_micro
        monetization = trade_monetization
        opportunity = trade_opportunity
        levels = trade_levels
        selection_score = trade_selection_score
        adaptive = trade_adaptive

    symbol = best_mtf.symbol
    basic = get_base_asset(symbol)
    indicator = best_mtf.tf_15m
    if indicator is None:
        return 1
    plan_valid = bool(levels.get("plan_valid", False))

    logger.info(
        "LANE WINNER=%s symbol=%s selection=%.1f trade_best=%s event_best=%s plan=%s",
        lane.upper(), symbol, selection_score,
        f"{trade_selection_score:.1f}" if trade_chosen is not None else "n/a",
        f"{event_selection_score:.1f}" if event_chosen is not None else "n/a",
        "valid" if plan_valid else "observation_only",
    )

    if plan_valid:
        logger.info("PUBLIC PLAN %s", plan_summary(levels))
    else:
        logger.info(
            "EVENT OBSERVATION %s: no clean public trade plan; writer may not invent entry/SL/TP",
            symbol,
        )

    logger.info(
        "BEST %s lane=%s tech=%.1f attention=%.1f micro=%.1f/%s demand=%.1f w2e=%.1f opportunity=%.1f adaptive=%+.1f "
        "directional_bias=%s 5m=%+.2f%% 15m=%+.2f%% vol15=x%.2f vol5=x%.2f funding=%s",
        symbol, lane, best_score.total, attention.score, micro.score, micro.phase,
        opportunity.audience_demand, monetization.score, opportunity.score, adaptive.total, best_score.direction,
        micro.change_5m, attention.change_15m, attention.volume_spike, micro.volume_spike_5m,
        f"{funding * 100:.4f}%" if funding is not None else "n/a",
    )

    if lane == "event":
        generated = _best_event_post_variant(
            basic=basic,
            mtf=best_mtf,
            score=best_score,
            levels=levels,
            memory=memory,
            btc=btc,
            attention=attention,
            micro=micro,
            opportunity=opportunity,
            monetization=monetization,
        )
    else:
        generated = _best_post_variant(
            symbol=symbol,
            basic=basic,
            mtf=best_mtf,
            score=best_score,
            levels=levels,
            memory=memory,
            btc=btc,
            attention=attention,
            micro=micro,
            opportunity=opportunity,
            monetization=monetization,
        )

    if generated is None:
        logger.info("No publication-quality %s post was generated", lane)
        _try_outcome_fallback(memory=memory, guard=guard, recovery_mode=recovery_mode)
        return 0
    selected_post, quality_report = generated
    post_text = selected_post.text
    logger.info(
        "Selected post quality: %.1f | source=%s | format=%s | visual=%s | signal=%s",
        quality_report.score,
        selected_post.source,
        selected_post.content_format,
        selected_post.visual_style,
        selected_post.signal_type,
    )
    logger.debug("Post preview:\n%s", post_text)

    # Final pre-publication safety contract. Writers already enforce this, but the
    # orchestrator independently blocks any valid-plan post that loses Entry/SL/TP1-3.
    if plan_valid:
        public_ok, public_reasons = validate_public_plan_text(post_text, levels, best_score.direction)
        if not public_ok:
            logger.error(
                "HARD BLOCK %s: valid plan is not fully public in text (%s)",
                symbol, "; ".join(public_reasons),
            )
            write_status(
                "skipped", "full public trade plan contract failed",
                symbol=symbol, lane=lane, reasons=list(public_reasons),
            )
            _try_outcome_fallback(memory=memory, guard=guard, recovery_mode=recovery_mode)
            return 0
        logger.info(
            "PUBLIC TEXT CONTRACT PASS %s: direction + entry + SL + TP1/TP2/TP3 are explicit", symbol
        )

    reach = guard.evaluate_candidate(
        market_score=opportunity.score,
        quality_score=quality_report.score,
        volume_relative=max(indicator.volume_relative, attention.volume_spike),
        change_1h=max(abs(indicator.change_1h), abs(attention.change_15m) * 2.0),
    )
    logger.info("Distribution gate: %s", reach.reason)
    if not DRY_RUN and not reach.allowed:
        write_status(
            "skipped",
            reach.reason,
            symbol=symbol,
            lane=lane,
            reach_score=reach.score,
            market_score=opportunity.score,
            quality_score=quality_report.score,
        )
        _try_outcome_fallback(memory=memory, guard=guard, recovery_mode=recovery_mode)
        return 0

    logger.info(
        "Reach recovery mode=%s rolling24h=%.0f baseline=%.0f",
        recovery_mode, rolling_reach, reach_baseline,
    )

    from recovery_guard import evaluate_recovery_candidate
    recovery = evaluate_recovery_candidate(
        lane=lane,
        writer_source=selected_post.source,
        event_class=opportunity.event_class,
        micro_phase=micro.phase,
        opportunity_score=opportunity.score,
        audience_demand=opportunity.audience_demand,
        attention_score=attention.score,
        micro_score=micro.score,
        monetization_score=monetization.score,
        selection_score=selection_score,
        reach_score=reach.score,
        plan_valid=plan_valid,
        recovery_mode=recovery_mode,
        hour_affinity=adaptive.hour_affinity,
        hour_samples=adaptive.hour_samples,
    )
    logger.info("v11.6 recovery gate: %s", recovery.reason)
    if not DRY_RUN and not recovery.allowed:
        write_status(
            "skipped", "v11.6 recovery gate: " + recovery.reason,
            symbol=symbol, lane=lane, recovery_mode=recovery_mode,
            rolling_reach=rolling_reach, reach_baseline=reach_baseline,
            reach_score=reach.score, selection_score=selection_score,
        )
        _try_outcome_fallback(memory=memory, guard=guard, recovery_mode=recovery_mode)
        return 0

    card_path: Optional[str] = None
    chart_path: Optional[str] = None
    images: List[str] = []
    try:
        if PUBLISH_IMAGES:
            card_visuals = {
                "headline_card", "split_scenario", "risk_card", "journal_card",
                "indicator_card", "data_card", "followup_card", "pulse_card",
            }
            if PUBLISH_MEDIA_MODE == "adaptive":
                human_chart_formats = {
                    "hot_reaction", "one_problem", "crowd_trap", "chart_story",
                    "why_wait", "level_story", "contrarian_take", "mistake_to_avoid",
                    "signal_vs_trade", "two_scenarios", "liquidity_map", "trader_journal",
                }
                if selected_post.content_format in human_chart_formats:
                    effective_media = "chart"
                else:
                    effective_media = "card" if selected_post.visual_style in card_visuals else "chart"
            else:
                effective_media = PUBLISH_MEDIA_MODE

            # Observation-only events never show fake TP/SL cards.
            if lane == "event" and not plan_valid:
                effective_media = "chart"

            if effective_media in {"card", "both"} and plan_valid:
                try:
                    card_path = generate_card(
                        basic=basic,
                        direction=best_score.direction,
                        entry=levels.get("plan_entry", levels["entry"]),
                        tp1=levels["tp1"],
                        tp2=levels["tp2"],
                        tp3=levels["tp3"],
                        stop=levels["stop"],
                        rr=levels.get("public_rr", levels["risk_reward"]),
                        confidence=best_score.total,
                        change_1h=indicator.change_1h,
                        post_style=selected_post.style_id,
                        signal_label=selected_post.angle_title,
                        content_format=selected_post.content_format,
                        visual_style=selected_post.visual_style,
                        headline=selected_post.headline,
                        rsi=indicator.rsi,
                        adx=indicator.adx,
                        volume_relative=indicator.volume_relative,
                        change_15m=attention.change_15m,
                        fresh_volume=attention.volume_spike,
                        attention_score=attention.score,
                    )
                except Exception as exc:
                    logger.warning("Card generation failed: %s", exc)

            if effective_media in {"chart", "both"}:
                raw_15m = primary_data.get(symbol, {}).get("15m")
                if raw_15m is None:
                    raw_15m = get_data(symbol, interval="15m", limit=KLINE_LIMIT)
                try:
                    chart_path = generate_chart(
                        symbol,
                        raw_15m,
                        basic,
                        entry=levels.get("plan_entry") if plan_valid else None,
                        entry_zone_low=levels.get("entry_zone_low") if plan_valid else None,
                        entry_zone_high=levels.get("entry_zone_high") if plan_valid else None,
                        tp1=levels.get("tp1") if plan_valid else None,
                        tp2=levels.get("tp2") if plan_valid else None,
                        tp3=levels.get("tp3") if plan_valid else None,
                        stop=levels.get("stop") if plan_valid else None,
                        direction=best_score.direction,
                        support=indicator.support,
                        resistance=indicator.resistance,
                        decision_level=(
                            levels.get("decision") if plan_valid else event_decision_level(indicator)
                        ),
                        decision_mode=str(levels.get("decision_mode", "at_level")) if plan_valid else "at_level",
                        vol_rel=attention.volume_spike,
                        indicator=indicator,
                        visual_style=selected_post.visual_style,
                        headline=selected_post.headline,
                        signal_label=selected_post.angle_title,
                    )
                except Exception as exc:
                    logger.warning("Chart generation failed: %s", exc)

            # Adaptive mode publishes one strong thumbnail. "both" remains available
            # for users who explicitly want the card and the chart together.
            images = [path for path in (card_path, chart_path) if path and os.path.isfile(path)]

        if DRY_RUN:
            logger.info("DRY_RUN enabled; publication skipped")
            write_status(
                "dry_run",
                "post generated but not published",
                symbol=symbol,
                lane=lane,
                reach_score=reach.score,
                quality_score=quality_report.score,
                w2e_market_score=monetization.score,
                opportunity_score=opportunity.score,
                micro_freshness=micro.score,
                audience_demand=opportunity.audience_demand,
                public_rr=levels.get("public_rr"),
                decision_mode=levels.get("decision_mode"),
            )
            print(post_text)
            return 0

        published = publish(post_text, image_path=images if images else None)
        if not published:
            logger.error("Publication failed")
            return 2

        try:
            record_publication(
                post_id=published.post_id,
                symbol=basic,
                market_symbol=symbol,
                text=post_text,
                lane=lane,
                direction=best_score.direction if plan_valid else "observation",
                content_format=selected_post.content_format,
                visual_style=selected_post.visual_style,
                event_class=opportunity.event_class,
                writer_source=selected_post.source,
                signal_type=selected_post.signal_type,
                opportunity_score=opportunity.score,
                audience_demand=opportunity.audience_demand,
                attention_score=attention.score,
                micro_freshness=micro.score,
                w2e_market_score=monetization.score,
                change_5m=micro.change_5m,
                change_15m=attention.change_15m,
                volume_5m=micro.volume_spike_5m,
                volume_15m=attention.volume_spike,
                public_rr=levels.get("public_rr") if plan_valid else None,
                decision_mode=str(levels.get("decision_mode", "")) if plan_valid else "observation",
                adaptive_total=adaptive.total,
                ticker_affinity=adaptive.ticker_affinity,
                hour_affinity=adaptive.hour_affinity,
                lane_affinity=adaptive.lane_affinity,
                adaptive_reason=adaptive.reason,
                w2e_proxy_score=monetization.score,
            )
        except Exception as exc:
            logger.warning("Could not record publication analytics metadata: %s", exc)

        # v11.1 Outcome Engine tracks only exact post_id-bound plans whose full
        # Entry/SL/TP1/TP2/TP3 ladder is explicit in the published text. Media never
        # substitutes for missing text, and no historical backfill is attempted.
        if plan_valid:
            try:
                tracked = record_trade_setup(
                    post_id=published.post_id,
                    symbol=basic,
                    market_symbol=symbol,
                    direction=best_score.direction,
                    lane=lane,
                    text=post_text,
                    levels=levels,
                    writer_source=selected_post.source,
                )
                if tracked is None:
                    logger.error(
                        "Outcome tracking refused for published post %s; publication remains valid but no follow-up will be generated",
                        published.post_id,
                    )
            except Exception as exc:
                logger.warning("Could not record trade setup for Outcome Engine: %s", exc)

        add_published(symbol)
        memory.add_post(
            symbol,
            post_text,
            post_style=selected_post.style_id,
            signal_type=selected_post.signal_type,
            content_format=selected_post.content_format,
            visual_style=selected_post.visual_style,
            direction=best_score.direction if plan_valid else "",
            lane=lane,
            levels=levels if plan_valid else {},
            market_price=indicator.price,
        )
        guard.record_success(
            symbol=symbol,
            direction=best_score.direction if plan_valid else "observation",
            content_format=selected_post.content_format,
            visual_style=selected_post.visual_style,
            market_score=opportunity.score,
            quality_score=quality_report.score,
            reach_score=float(reach.score or 0.0),
            post_id=published.post_id,
        )
        write_status(
            "published",
            "publication completed",
            symbol=symbol,
            lane=lane,
            direction=best_score.direction if plan_valid else "observation",
            post_id=published.post_id,
            reach_score=reach.score,
            quality_score=quality_report.score,
            w2e_market_score=monetization.score,
            opportunity_score=opportunity.score,
            adaptive_total=adaptive.total,
            ticker_affinity=adaptive.ticker_affinity,
            hour_affinity=adaptive.hour_affinity,
            audience_demand=opportunity.audience_demand,
            event_class=opportunity.event_class,
            micro_freshness=micro.score,
            writer_source=selected_post.source,
            content_format=selected_post.content_format,
            visual_style=selected_post.visual_style,
            public_rr=levels.get("public_rr"),
            decision_mode=levels.get("decision_mode"),
        )
        logger.info("Published %s successfully (post_id=%s)", symbol, published.post_id or "n/a")
        return 0
    finally:
        _cleanup_files((card_path, chart_path))


def main() -> int:
    with ProcessLock() as lock:
        if not lock.acquired:
            logger.info("Another bot process is still running; cron launch skipped")
            write_status("skipped", "another bot process is still running")
            return 0
        try:
            return _run_once()
        except Exception as exc:
            logger.exception("Unhandled bot failure")
            write_status("error", str(exc))
            return 3


if __name__ == "__main__":
    raise SystemExit(main())
