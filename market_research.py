"""Reproducible research facts from consecutive closed 15m candles."""
from __future__ import annotations
import math
import pandas as pd


def candle_research(data) -> dict:
    if data is None or len(data) < 6:
        return {}
    recent = data.tail(6)
    if not isinstance(recent.index, pd.DatetimeIndex):
        return {}
    if not ((recent.index[1:] - recent.index[:-1]).total_seconds() == 900).all():
        return {}
    try:
        close, high, low, volume = (recent[k].astype(float) for k in ('close','high','low','volume'))
        if not all(math.isfinite(v) for v in [*close,*high,*low,*volume]) or (close <= 0).any() or (volume < 0).any():
            return {}
        pct = lambda a,b: f'{(a/b-1)*100:+.2f}%'
        price = lambda n: f'{n:.10f}'.rstrip('0').rstrip('.')
        return {
            'change_1h': pct(close.iloc[-1], close.iloc[-5]),
            'previous_change_15m': pct(close.iloc[-2], close.iloc[-3]),
            'prior_1h_high': price(high.iloc[-5:-1].max()),
            'prior_1h_low': price(low.iloc[-5:-1].min()),
            'window_definition': 'Скользящий диапазон четырех свечей непосредственно перед последней, не календарный час и не отметка час назад. История не доказывает удержание цены за его границей. previous_change_15m — непосредственно предыдущая закрытая свеча того же периода.',
            **({'volume_vs_previous_15m': f'x{volume.iloc[-1]/volume.iloc[-2]:.2f}'} if volume.iloc[-2]>0 else {}),
        }
    except (ValueError, TypeError, KeyError, ZeroDivisionError):
        return {}


def attach_research(market, attention):
    context = getattr(attention, 'research', None)
    if context:
        market['observed_context'] = dict(context)
        market['change_1h'] = context['change_1h']
        market['previous_change_15m'] = context['previous_change_15m']
