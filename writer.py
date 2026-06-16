import requests
import os

MISTRAL_API = os.getenv("MISTRAL_API")

def write_post(data):

    prompt = f"""
Ты аналитик Binance Square.

Монета: {data['symbol']}
Цена: {data['price']}
Изменение: {data['change']}%
RSI: {data['rsi']}

Напиши пост:

- объясни движение
- упомяни ликвидность / импульс / тренд
- без гарантий роста
- стиль: уверенный аналитик
- добавь риск-фактор
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
