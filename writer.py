import requests
import os

MISTRAL_API = os.getenv("MISTRAL_API")

def write_post(data):

    prompt = f"""
Ты профессиональный криптоаналитик Binance Square.

Данные:

Монета: {data['symbol']}
Цена: {data['price']}
Изменение за период: {round(data['change'],2)}%
RSI: {round(data['rsi'],2)}

Напиши пост на русском языке.

Требования:

- 500-1000 символов
- не как бот
- объясни движение цены
- объясни настроение рынка
- упомяни риск
- не давай финансовых советов
- добавь вывод
- используй эмодзи
- в конце 5-8 хештегов

Стиль:
как опытный трейдер, который делится наблюдениями.
"""

    r = requests.post(
        "https://api.mistral.ai/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {MISTRAL_API}",
            "Content-Type": "application/json"
        },
        json={
            "model": "mistral-small",
            "messages": [
                {
                    "role": "user",
                    "content": prompt
                }
            ]
        },
        timeout=60
    )

    return r.json()["choices"][0]["message"]["content"]
