import requests
import os

MISTRAL_API = os.getenv("MISTRAL_API")

def generate_post(data):

    prompt = f"""
Ты криптоаналитик Binance Square.

Сделай короткий пост (очень качественный, не шаблон).

Монета: {data['symbol']}
Цена: {data['price']}
Изменение: {data['change']}%
RSI: {data['rsi']}
ATR: {data['atr']}

Требования:
- объясни, почему происходит движение
- упомяни ликвидность или импульс
- не давай прямых обещаний роста
- стиль: уверенный аналитик
- добавь риск-фактор
- добавь хештеги
"""

    r = requests.post(
        "https://api.mistral.ai/v1/chat/completions",
        headers={"Authorization": f"Bearer {MISTRAL_API}"},
        json={
            "model": "mistral-medium",
            "messages": [{"role": "user", "content": prompt}]
        }
    )

    return r.json()["choices"][0]["message"]["content"]
