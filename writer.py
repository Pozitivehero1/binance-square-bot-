import requests
import os

MISTRAL_API = os.getenv("MISTRAL_API")

def write_post(data):

    prompt = f"""
Ты опытный криптоаналитик Binance Square.

Монета: {data['symbol']}
Цена: {data['price']}
Изменение: {round(data['change'],2)}%
RSI: {round(data['rsi'],2)}

Напиши аналитический пост на русском языке.

Требования:

- 700-1200 символов
- не использовать фразы "не является финансовой рекомендацией"
- объяснить причину движения
- упомянуть риски
- добавить вывод
- добавить 5-8 хештегов
- стиль живого автора, а не бота
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
