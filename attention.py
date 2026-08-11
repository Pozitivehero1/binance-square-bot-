"""Fresh-market attention signals for Binance Square.

The 15-minute snapshot is kept for technical compatibility.  v9 also adds a
5-minute *micro* snapshot whose only job is to answer a different question:
"is the interesting part happening now, or did it already happen several
candles ago?"  This helps avoid over-ranking stale x20 volume spikes.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Optional

import pandas as pd


@dataclass(frozen=True)
class AttentionSnapshot:
    score: float
    change_15m: float
    change_45m: float
    volume_spike: float
    range_expansion: float
    turnover_1h: float
    distance_atr: float
    label: str
    overextended: bool


@dataclass(frozen=True)
class MicroAttentionSnapshot:
    score: float
    change_5m: float
    change_15m: float
    volume_spike_5m: float
    return_impulse: float
    volume_impulse: float
    acceleration: float
    event_age_bars: int
    phase: str
    stale_penalty: float


def _clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, float(value)))


def _safe_ratio(value: float, baseline: float, default: float = 1.0) -> float:
    if not math.isfinite(value) or not math.isfinite(baseline) or baseline <= 0:
        return default
    return max(0.01, value / baseline)


def _pct(current: float, previous: float) -> float:
    if not math.isfinite(current) or not math.isfinite(previous) or previous == 0:
        return 0.0
    return (current - previous) / previous * 100.0


def _label(score: float, volume_spike: float, change_15m: float) -> str:
    if score >= 78 and volume_spike >= 2.0:
        return "резкий всплеск внимания"
    if score >= 66:
        return "активное движение"
    if score >= 54:
        return "растущий интерес"
    if abs(change_15m) >= 0.7:
        return "движение без сильного объёма"
    return "обычная рыночная активность"


def _clean_frame(frame: Optional[pd.DataFrame], minimum: int) -> Optional[pd.DataFrame]:
    if frame is None or len(frame) < minimum:
        return None
    data = frame.copy()
    for column in ("open", "high", "low", "close", "volume"):
        if column not in data.columns:
            return None
        data[column] = pd.to_numeric(data[column], errors="coerce")
    data = data.dropna(subset=["open", "high", "low", "close", "volume"]).sort_index()
    return data if len(data) >= minimum else None


def compute_attention(frame: Optional[pd.DataFrame], indicator, direction: str) -> AttentionSnapshot:
    """Return a 0-100 current-attention score from closed 15m candles."""
    data = _clean_frame(frame, 24)
    if data is None:
        return AttentionSnapshot(35.0, 0.0, 0.0, 1.0, 1.0, 0.0, 0.0, "нет данных о свежем импульсе", False)

    data = data.tail(80)
    close = data["close"]
    high = data["high"]
    low = data["low"]
    volume = data["volume"]

    change_15m = _pct(float(close.iloc[-1]), float(close.iloc[-2]))
    change_45m = _pct(float(close.iloc[-1]), float(close.iloc[-4]))

    previous_volume = float(volume.iloc[-21:-1].median())
    volume_spike = _safe_ratio(float(volume.iloc[-1]), previous_volume)

    ranges = (high - low).abs()
    previous_range = float(ranges.iloc[-21:-1].median())
    range_expansion = _safe_ratio(float(ranges.iloc[-1]), previous_range)

    turnover_1h = float((close.tail(4) * volume.tail(4)).sum())
    turnover_component = _clamp((math.log10(max(turnover_1h, 1.0)) - 4.5) * 28.0)

    motion_component = _clamp(abs(change_15m) * 45.0 + abs(change_45m) * 18.0)
    volume_component = _clamp(48.0 + math.log2(max(volume_spike, 0.05)) * 24.0)
    range_component = _clamp(46.0 + math.log2(max(range_expansion, 0.05)) * 20.0)

    aligned = (direction == "long" and change_15m > 0 and change_45m > 0) or (
        direction == "short" and change_15m < 0 and change_45m < 0
    )
    alignment_bonus = 7.0 if aligned else -5.0

    atr = max(float(getattr(indicator, "atr", 0.0) or 0.0), 1e-12)
    ema20 = float(getattr(indicator, "ema20", close.iloc[-1]) or close.iloc[-1])
    price = float(getattr(indicator, "price", close.iloc[-1]) or close.iloc[-1])
    distance_atr = abs(price - ema20) / atr
    rsi = float(getattr(indicator, "rsi", 50.0) or 50.0)
    overextended = distance_atr >= 2.7 or (direction == "long" and rsi >= 80.0) or (
        direction == "short" and rsi <= 20.0
    )
    overextension_penalty = 13.0 if overextended else 0.0
    if overextended and volume_spike >= 2.8 and abs(change_15m) >= 0.8:
        overextension_penalty = 5.0

    score = (
        motion_component * 0.34
        + volume_component * 0.27
        + range_component * 0.14
        + turnover_component * 0.25
        + alignment_bonus
        - overextension_penalty
    )
    score = _clamp(score)
    return AttentionSnapshot(
        score=score,
        change_15m=change_15m,
        change_45m=change_45m,
        volume_spike=volume_spike,
        range_expansion=range_expansion,
        turnover_1h=turnover_1h,
        distance_atr=distance_atr,
        label=_label(score, volume_spike, change_15m),
        overextended=overextended,
    )



def compute_event_attention(frame: Optional[pd.DataFrame], indicator) -> AttentionSnapshot:
    """Direction-neutral 15m attention for the EVENT lane.

    ``compute_attention`` intentionally includes a small LONG/SHORT alignment
    bonus because it was designed for trade selection. Audience events should
    not disappear just because the technical direction inferred from higher
    timeframes is weak or opposite to the current impulse. Averaging the two
    directional views removes that bias while keeping the same motion, volume,
    turnover and overextension information.
    """
    long_view = compute_attention(frame, indicator, "long")
    short_view = compute_attention(frame, indicator, "short")
    score = _clamp((float(long_view.score) + float(short_view.score)) / 2.0)
    return AttentionSnapshot(
        score=round(score, 2),
        change_15m=long_view.change_15m,
        change_45m=long_view.change_45m,
        volume_spike=long_view.volume_spike,
        range_expansion=long_view.range_expansion,
        turnover_1h=long_view.turnover_1h,
        distance_atr=long_view.distance_atr,
        label=_label(score, long_view.volume_spike, long_view.change_15m),
        overextended=bool(long_view.overextended or short_view.overextended),
    )

def compute_micro_attention(frame_5m: Optional[pd.DataFrame]) -> MicroAttentionSnapshot:
    """Score how fresh the current event is using only closed 5m candles.

    Huge historical volume gets diminishing credit.  The score is high when the
    latest 5m candle or the immediately preceding candle is where price/volume
    acceleration is occurring.  If the biggest shock happened 20-30 minutes ago
    and current activity is cooling, the stale penalty rises.
    """
    data = _clean_frame(frame_5m, 30)
    if data is None:
        return MicroAttentionSnapshot(50.0, 0.0, 0.0, 1.0, 1.0, 1.0, 1.0, 6, "unknown", 0.0)

    data = data.tail(72)
    close = data["close"].astype(float)
    volume = data["volume"].astype(float)
    returns = close.pct_change().fillna(0.0) * 100.0

    change_5m = float(returns.iloc[-1])
    change_15m = _pct(float(close.iloc[-1]), float(close.iloc[-4]))

    hist_returns = returns.iloc[-31:-1].abs()
    median_abs_return = max(float(hist_returns.median()), 0.015)
    return_impulse = max(0.05, abs(change_5m) / median_abs_return)

    hist_volume = volume.iloc[-31:-1]
    median_volume = max(float(hist_volume.median()), 1e-12)
    volume_spike = max(0.05, float(volume.iloc[-1]) / median_volume)

    recent3 = abs(float(returns.iloc[-3:].sum()))
    prior3 = abs(float(returns.iloc[-6:-3].sum()))
    acceleration = (recent3 + median_abs_return) / (prior3 + median_abs_return)

    # Age of the most conspicuous candle among the last 6 bars.  Price and volume
    # are combined so a single old volume print does not dominate forever.
    recent_returns = returns.iloc[-6:].abs().to_numpy()
    recent_volumes = (volume.iloc[-6:] / median_volume).to_numpy()
    salience = recent_returns / median_abs_return + recent_volumes.clip(0, 12) * 0.30
    best_index = int(salience.argmax())
    event_age_bars = 5 - best_index

    return_score = _clamp(28.0 + math.log2(max(return_impulse, 0.10)) * 20.0)
    # x3-x8 is already a strong signal; x30 is not worth ten times as much.
    volume_impulse = _clamp(35.0 + math.log2(max(volume_spike, 0.10)) * 17.0)
    acceleration_score = _clamp(45.0 + math.log2(max(acceleration, 0.10)) * 24.0)
    recency_score = _clamp(100.0 - event_age_bars * 16.0)

    stale_penalty = 0.0
    if event_age_bars >= 3:
        stale_penalty += (event_age_bars - 2) * 7.0
    if volume_spike < 0.75 and event_age_bars >= 2:
        stale_penalty += 8.0
    if acceleration < 0.65:
        stale_penalty += 8.0
    stale_penalty = min(30.0, stale_penalty)

    score = (
        return_score * 0.30
        + volume_impulse * 0.25
        + acceleration_score * 0.23
        + recency_score * 0.22
        - stale_penalty
    )
    score = _clamp(score)

    if event_age_bars <= 1 and score >= 70:
        phase = "fresh"
    elif event_age_bars <= 2 and score >= 55:
        phase = "developing"
    elif stale_penalty >= 12:
        phase = "stale"
    else:
        phase = "ordinary"

    return MicroAttentionSnapshot(
        score=round(score, 2),
        change_5m=round(change_5m, 4),
        change_15m=round(change_15m, 4),
        volume_spike_5m=round(volume_spike, 3),
        return_impulse=round(return_impulse, 3),
        volume_impulse=round(volume_impulse, 2),
        acceleration=round(acceleration, 3),
        event_age_bars=event_age_bars,
        phase=phase,
        stale_penalty=round(stale_penalty, 2),
    )


def format_turnover(value: float) -> str:
    value = max(0.0, float(value))
    if value >= 1_000_000_000:
        return f"${value / 1_000_000_000:.2f}B"
    if value >= 1_000_000:
        return f"${value / 1_000_000:.1f}M"
    if value >= 1_000:
        return f"${value / 1_000:.0f}K"
    return f"${value:.0f}"
