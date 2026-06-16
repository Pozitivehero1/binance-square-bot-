import requests
import pandas as pd
import ta
import os

MISTRAL_API = os.getenv("MISTRAL_API")
SQUARE_API = os.getenv("SQUARE_API")

SYMBOLS = [
    "BTCUSDT","ETHUSDT","SOLUSDT","BNBUSDT",
    "XRPUSDT","DOGEUSDT","PEPEUSDT","WIFUSDT"
]


# --- GET DATA ---
def get_data(symbol):
    url = f"https://fapi.binance.com/fapi/v1/klines?symbol={symbol}&interval=15m&limit=200"
    data = requests.get(url).json()

    df = pd.DataFrame(data)
    close = df[4].astype(float)

    rsi = ta.momentum.RSIIndicator(close).rsi().iloc[-1]

    return {
        "symbol": symbol,
        "price": float(close.iloc[-1]),
        "rsi": float(rsi)
    }


# --- AI POST ---
def generate_post(data):

    prompt = f"""
Ты криптоаналитик Binance Square.

Монета: {data['symbol']}
Цена: {data['price']}
RSI: {data['rsi']}

Напиши короткий аналитический пост на русском:
- без финансовых советов
- стиль: крипто Telegram
- добавь эмоции
- добавь хештеги
"""

    r = requests.post(
        "https://api.mistral.ai/v1/chat/completions",
        headers={"Authorization": f"Bearer {MISTRAL_API}"},
        json={
            "model": "mistral-small",
            "messages": [{"role": "user", "content": prompt}]
        }
    )

    return r.json()["choices"][0]["message"]["content"]


# --- POST TO BINANCE ---
def publish(text):

    url = "https://www.binance.com/bapi/composite/v1/public/pgc/openApi/content/add"

    headers = {
        "X-Square-OpenAPI-Key": SQUARE_API,
        "clienttype": "binanceSkill",
        "Content-Type": "application/json"
    }

    requests.post(url, headers=headers, json={
        "bodyTextOnly": text
    })


# --- MAIN LOGIC ---
def main():

    best = None

    for sym in SYMBOLS:
        d = get_data(sym)

        # фильтр "движения"
        if d["rsi"] > 60:
            best = d
            break

    if best:
        post = generate_post(best)
        publish(post)
        print("POSTED:", best["symbol"])


main()
