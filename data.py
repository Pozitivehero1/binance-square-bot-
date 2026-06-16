import requests
import pandas as pd

# -------- BINANCE SPOT --------
def binance_spot(symbol):
    try:
        url = f"https://data-api.binance.vision/api/v3/klines?symbol={symbol}&interval=15m&limit=200"
        r = requests.get(url, timeout=10)
        data = r.json()

        if not isinstance(data, list):
            return None

        return data

    except:
        return None


# -------- BYBIT FALLBACK --------
def bybit(symbol):
    try:
        url = f"https://api.bybit.com/v5/market/kline?category=linear&symbol={symbol}&interval=15"
        r = requests.get(url, timeout=10)
        data = r.json()

        if "result" not in data:
            return None

        return data["result"]["list"]

    except:
        return None


# -------- COINGECKO FALLBACK --------
def coingecko(symbol):
    try:
        url = "https://api.coingecko.com/api/v3/simple/price"
        return None  # только как резерв будущего расширения
    except:
        return None


# -------- SMART FETCH --------
def get_data(symbol):

    data_sources = [
        binance_spot,
        bybit,
        coingecko
    ]

    for source in data_sources:
        data = source(symbol)

        if data:
            return data

    return None
