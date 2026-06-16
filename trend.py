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
        r.raise_for_status()          # вызовет исключение при статусе != 200
        data = r.json()
    except Exception as e:
        print(f"[ERROR] Не удалось получить тикеры: {e}")
        return []

    # Если ответ не список — выводим для диагностики и возвращаем пустой список
    if not isinstance(data, list):
        print(f"[ERROR] Неожиданный формат ответа: {data}")
        return []

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
            pairs.append({
                "symbol": symbol,
                "volume": volume,
                "change": change
            })
        except (TypeError, ValueError):
            continue

    pairs.sort(key=lambda x: (abs(x["change"]), x["volume"]), reverse=True)
    return [x["symbol"] for x in pairs[:limit]]
