import requests

def get_trending_symbols(limit=20):

    r = requests.get(
        "https://api.binance.com/api/v3/ticker/24hr",
        timeout=30
    )

    data = r.json()

    pairs = []

    for item in data:

        symbol = item["symbol"]

        if not symbol.endswith("USDT"):
            continue

        try:
            volume = float(item["quoteVolume"])
            change = float(item["priceChangePercent"])

            pairs.append({
                "symbol": symbol,
                "volume": volume,
                "change": change
            })

        except:
            continue

    pairs.sort(
        key=lambda x: (
            abs(x["change"]),
            x["volume"]
        ),
        reverse=True
    )

    return [x["symbol"] for x in pairs[:limit]]
