import requests

def get_trending_symbols(limit=50):
    """
    Получает список самых активных монет (USDT-пары).
    Сначала пробует Binance, при ошибке использует Bybit.
    """
    try:
        return _get_trending_binance(limit)
    except Exception as e:
        print(f"[WARN] Binance failed: {e}, switching to Bybit...")
        return _get_trending_bybit(limit)


def _get_trending_binance(limit):
    headers = {"User-Agent": "Mozilla/5.0"}
    r = requests.get(
        "https://data-api.binance.vision/api/v3/ticker/24hr",
        headers=headers,
        timeout=30
    )
    r.raise_for_status()
    data = r.json()

    if not isinstance(data, list):
        raise ValueError("Unexpected response format from Binance")

    pairs = []
    for item in data:
        if not isinstance(item, dict):
            continue
        symbol = item.get("symbol")
        if not symbol or not symbol.endswith("USDT"):
            continue
        try:
            volume = float(item.get("quoteVolume", 0))
            change = float(item.get("priceChangePercent", 0))
            pairs.append({"symbol": symbol, "volume": volume, "change": change})
        except (TypeError, ValueError):
            continue

    pairs.sort(key=lambda x: (abs(x["change"]), x["volume"]), reverse=True)
    return [x["symbol"] for x in pairs[:limit]]


def _get_trending_bybit(limit):
    headers = {"User-Agent": "Mozilla/5.0"}
    r = requests.get(
        "https://api.bybit.com/v5/market/tickers?category=linear",
        headers=headers,
        timeout=30
    )
    r.raise_for_status()
    data = r.json()

    if data.get("retCode") != 0:
        raise ValueError(f"Bybit error: {data.get('retMsg')}")

    tickers = data.get("result", {}).get("list", [])
    pairs = []

    for item in tickers:
        if not isinstance(item, dict):
            continue
        symbol = item.get("symbol")
        if not symbol or not symbol.endswith("USDT"):
            continue
        try:
            # turnover24h – объём в USDT за сутки
            volume = float(item.get("turnover24h", 0))
            # price24hPcnt – изменение цены в долях, переводим в проценты
            change = float(item.get("price24hPcnt", 0)) * 100
            pairs.append({"symbol": symbol, "volume": volume, "change": change})
        except (TypeError, ValueError):
            continue

    pairs.sort(key=lambda x: (abs(x["change"]), x["volume"]), reverse=True)
    return [x["symbol"] for x in pairs[:limit]]
