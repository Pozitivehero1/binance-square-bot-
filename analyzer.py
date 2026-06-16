import requests
import pandas as pd
import ta

def get_symbol_data(symbol):

    url = f"https://fapi.binance.com/fapi/v1/klines?symbol={symbol}&interval=15m&limit=200"
    data = requests.get(url).json()

    df = pd.DataFrame(data)
    df.columns = ["t","o","h","l","c","v","ct","q","n","tb","tq","i"]

    close = df["c"].astype(float)
    high = df["h"].astype(float)
    low = df["l"].astype(float)
    volume = df["v"].astype(float)

    rsi = ta.momentum.RSIIndicator(close).rsi().iloc[-1]

    ema20 = close.ewm(span=20).mean().iloc[-1]
    ema50 = close.ewm(span=50).mean().iloc[-1]

    change = (close.iloc[-1] - close.iloc[-10]) / close.iloc[-10] * 100

    atr = ta.volatility.AverageTrueRange(high, low, close).average_true_range().iloc[-1]

    return {
        "symbol": symbol,
        "price": close.iloc[-1],
        "rsi": rsi,
        "ema20": ema20,
        "ema50": ema50,
        "change": change,
        "atr": atr,
        "volume": volume.mean()
    }
