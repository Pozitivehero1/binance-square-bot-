import requests

def get_trending_symbols(limit=20):
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    }
    try:
        r = requests.get(
            "https://api.binance.com/api/v3/ticker/24hr",
            headers=headers,
            timeout=30
        )
        r.raise_for_status()  # raise if status != 200
        data = r.json()
    except Exception as e:
        print(f"Error fetching tickers: {e}")
        return []

    # Ensure data is a list of tickers
    if not isinstance(data, list):
        print(f"Unexpected response format: {data}")
        return []

    pairs = []
    for item in data:
        # item should be a dict; skip if not
        if not isinstance(item, dict):
            continue
        symbol = item.get("symbol")
        if not symbol or not symbol.endswith("USDT"):
            continue
        try:
            volume = float(item.get("quoteVolume", 0))
            change = float(item.get("priceChangePercent", 0))
            pairs.append({
                "symbol": symbol,
                "volume": volume,
                "change": change
            })
        except (TypeError, ValueError):
            continue

    pairs.sort(
        key=lambda x: (abs(x["change"]), x["volume"]),
        reverse=True
    )
    return [x["symbol"] for x in pairs[:limit]]
