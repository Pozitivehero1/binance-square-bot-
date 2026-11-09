"""Small spot-market scan with comparable, closed-candle measurements."""
from __future__ import annotations

import hashlib
import logging
import math
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone

import requests

from .models import Story, utcnow

LOG = logging.getLogger(__name__)
BASES = ("https://data-api.binance.vision", "https://api.binance.com")
STABLES = {"USDT", "USDC", "USD1", "USDE", "USDS", "FDUSD", "TUSD", "BUSD", "DAI",
           "USDP", "PYUSD", "EUR", "EURI", "AEUR", "EURC", "PAXG", "XAUT"}
EQUITIES = {x + "B" for x in ("AAPL", "AMZN", "GOOGL", "META", "MSFT", "NVDA", "TSLA",
                            "COIN", "CRCL", "MSTR", "SPY", "QQQ", "SOXL", "SOXS", "SNDK", "SKHY")}
CORE = ("BTC", "ETH", "BNB", "SOL", "XRP", "DOGE", "ADA", "LINK", "AVAX", "TRX", "SUI")
LEVERAGED = {asset+suffix for asset in CORE for suffix in ("UP", "DOWN", "BULL", "BEAR")}


def get_json(path, params=None):
    for base in BASES:
        try:
            response = requests.get(base + path, params=params, timeout=(4, 12))
            response.raise_for_status()
            return response.json()
        except (requests.RequestException, ValueError):
            continue
    raise RuntimeError("Binance public market data unavailable")


def liquid_universe(rows, limit):
    eligible = []
    for row in rows:
        symbol = str(row.get("symbol", ""))
        base = symbol[:-4]
        try:
            volume, price = float(row["quoteVolume"]), float(row["lastPrice"])
            change = float(row["priceChangePercent"])
        except (KeyError, ValueError, TypeError):
            continue
        if (not symbol.endswith("USDT") or base in STABLES | EQUITIES
                or base in LEVERAGED
                or not all(math.isfinite(v) for v in (volume, price, change))
                or volume < 5_000_000 or price <= 0):
            continue
        eligible.append(dict(symbol=symbol, base=base, volume=volume, change=change))
    by_volume = sorted(eligible, key=lambda x: x["volume"], reverse=True)
    # Reserve room for liquid movers; do not let a tail of tiny tokens dominate.
    movers = sorted(eligible, key=lambda x: abs(x["change"]), reverse=True)[:max(3, limit // 4)]
    core = [x for x in by_volume if x["base"] in CORE]
    unique = {x["symbol"]: x for x in core + movers + by_volume}
    return list(unique.values())[:limit]


def closed_candles(rows, now_ms):
    result = []
    for row in rows:
        try:
            if len(row) < 8 or int(row[6]) >= now_ms:
                continue
            o, h, low, c, vol, quote = (float(row[i]) for i in (1, 2, 3, 4, 5, 7))
            if (not all(math.isfinite(x) for x in (o, h, low, c, vol, quote))
                    or min(o, h, low, c) <= 0 or min(vol, quote) < 0
                    or h < max(o, c) or low > min(o, c)):
                raise ValueError("Invalid candle geometry")
            result.append([int(row[0]), o, h, low, c, vol, int(row[6]), quote])
        except (TypeError, IndexError, ValueError):
            raise ValueError("Malformed Binance candle") from None
    result.sort(key=lambda x: x[0])
    if len(result) < 289:
        raise ValueError("Need a full closed day and a comparison candle")
    if any(b[0] - a[0] != 300_000 for a, b in zip(result, result[1:])):
        raise ValueError("Missing or duplicate five-minute candles")
    if not 0 < now_ms - result[-1][6] <= 390_000:
        raise ValueError("Stale market data")
    return result[-300:]


def measure(meta, rows):
    def change(n):
        return (rows[-1][4] / rows[-n-1][4] - 1) * 100
    return dict(meta, rows=rows, c15=change(3), c1h=change(12), c4h=change(48), c24h=change(288),
                previous_hour=(rows[-13][4] / rows[-25][4] - 1) * 100,
                price=rows[-1][4], prior_high=max(r[2] for r in rows[-289:-1]),
                prior_low=min(r[3] for r in rows[-289:-1]),
                closed_at=datetime.fromtimestamp((rows[-1][6]+1)/1000, timezone.utc).isoformat())


def pct(value):
    return f"{value:+.2f}%"


def price(value):
    return f"{value:.8f}".rstrip("0").rstrip(".")


def build_stories(measurements, now=None):
    now = now or utcnow()
    by_base = {m["base"]: m for m in measurements}
    stories = []
    def add(kind, symbols, headline, facts, score, chart=None, direction="", level=None):
        stamp = chart["closed_at"] if chart else max(m["closed_at"] for m in measurements)
        key = f"{kind}:{','.join(symbols)}:{direction}:{now:%Y-%m-%d-%H}"
        stories.append(Story(hashlib.sha256((key+stamp).encode()).hexdigest()[:16], kind, symbols,
                             headline, {f"f{i}": s for i, s in enumerate(facts, 1)}, stamp, score,
                             event_key=key, chart_symbol=chart["symbol"] if chart else "",
                             range_level=level,
                             candles=chart["rows"] if chart else []))
    for m in measurements:
        base = m["base"]
        facts = [f"${base}: изменение за час {pct(m['c1h'])}.",
                 f"${base}: изменение за четыре часа {pct(m['c4h'])}.",
                 f"${base}: изменение за пятнадцать минут {pct(m['c15'])}.",
                 f"${base}: цена закрытия пятиминутной свечи {price(m['price'])} USDT."]
        liquid_bonus = min(12, max(0, math.log10(m["volume"])-6)*3)
        if abs(m["c1h"]) >= .15 or abs(m["c4h"]) >= .5:
            add("mover", [base], "Движение цены в контексте последних часов", facts[:2],
                30+min(28, abs(m["c1h"])*4)+liquid_bonus+(6 if base in CORE else 0), m,
                "up" if m["c1h"] > 0 else "down")
        if m["price"] > m["prior_high"] or m["price"] < m["prior_low"]:
            up = m["price"] > m["prior_high"]
            bound = m["prior_high"] if up else m["prior_low"]
            breakout = f"${base}: последняя пятиминутная свеча закрылась {'выше максимума' if up else 'ниже минимума'} предыдущих двадцати четырёх часов ({price(bound)} USDT)."
            add("range_break", [base], "Закрытие за пределами предыдущего суточного диапазона",
                [facts[0], breakout, facts[3]], 52+liquid_bonus+min(15, abs(m["c1h"])*3),
                m, "up" if up else "down", bound)
        rows = m["rows"]
        if len(rows) >= 290:
            # Compare both closes to the same range, excluding both event candles.
            prior = rows[-290:-2]
            high, low = max(r[2] for r in prior), min(r[3] for r in prior)
            outside, current = rows[-2][4], rows[-1][4]
            if low <= current <= high and not low <= outside <= high:
                above = outside > high
                level = high if above else low
                add("range_return", [base], "Цена закрылась обратно внутри суточного диапазона", [
                    f"${base}: предыдущая пятиминутная свеча закрылась {'выше максимума' if above else 'ниже минимума'} "
                    f"суточного диапазона ({price(level)} USDT), на {price(outside)} USDT.",
                    f"${base}: последняя пятиминутная свеча закрылась внутри того же диапазона, на {price(current)} USDT.",
                    facts[0],
                ], 56+liquid_bonus+min(15, abs(m["c1h"])*3), m, "from_above" if above else "from_below", level)
        if m["c1h"] * m["previous_hour"] < 0 and min(abs(m["c1h"]), abs(m["previous_hour"])) >= .6:
            if m["c1h"] * m["c4h"] < 0:
                focused = facts[:2]
            else:
                focused = [facts[0], f"${base}: за предшествующий час изменение составляло {pct(m['previous_hour'])}."]
            add("reversal", [base], "Последний час изменил направление движения", focused,
                48+liquid_bonus+min(15, abs(m["c1h"])*3), m, "up" if m["c1h"] > 0 else "down")
    if "BTC" in by_base and "ETH" in by_base:
        btc, eth = by_base["BTC"], by_base["ETH"]
        # Same close time is essential for every cross-asset comparison.
        aligned = [m for m in measurements if m["closed_at"] == btc["closed_at"]]
        if eth["closed_at"] == btc["closed_at"] and len(aligned) >= 12:
            gainers = sum(m["c1h"] > 0 for m in aligned)
            add("market_map", ["BTC", "ETH"], "Рынок целиком: лидеры и ширина движения", [
                f"$BTC: изменение за час {pct(btc['c1h'])}.",
                f"$ETH: изменение за час {pct(eth['c1h'])}.",
                f"В выборке из {len(aligned)} ликвидных пар Binance за час выросли {gainers}; остальные не выросли.",
            ], 45+min(16, abs(btc["c1h"])*5), btc,
                "broad_up" if gainers > len(aligned)/2 else "broad_down")
            diff = eth["c1h"] - btc["c1h"]
            if abs(diff) >= .25:
                add("relative_strength", ["ETH", "BTC"], "Сравнение Ethereum и Bitcoin за одинаковый час", [
                    f"$ETH: изменение за час {pct(eth['c1h'])}.",
                    f"$BTC: изменение за час {pct(btc['c1h'])}.",
                    f"Доходность $ETH за час {'выше' if diff>0 else 'ниже'} доходности $BTC на {abs(diff):.2f} процентного пункта.",
                ], 50+min(15, abs(diff)*6), eth, "eth_leads" if diff>0 else "btc_leads")
    return stories


def scan(settings):
    universe = liquid_universe(get_json("/api/v3/ticker/24hr"), settings.universe_size)
    results, errors = [], 0
    def fetch(meta):
        rows = get_json("/api/v3/klines", {"symbol": meta["symbol"], "interval": "5m", "limit": 300})
        return measure(meta, closed_candles(rows, int(utcnow().timestamp()*1000)))
    with ThreadPoolExecutor(max_workers=settings.workers) as pool:
        futures = {pool.submit(fetch, m): m for m in universe}
        for future in as_completed(futures):
            try:
                results.append(future.result())
            except (RuntimeError, ValueError, requests.RequestException):
                errors += 1
    LOG.info("Market scan liquid_pairs=%s measured=%s unavailable=%s", len(universe), len(results), errors)
    if not results:
        raise RuntimeError("No current market measurements")
    return build_stories(results)
