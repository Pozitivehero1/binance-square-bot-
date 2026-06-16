import requests
import os

MISTRAL_API = os.getenv("MISTRAL_API")

def write_post(data):
    prompt = f"""
Ты опытный криптоаналитик Binance Square.

Монета: {data['symbol']}
Цена: {data['price']}
Изменение: {round(data['change'], 2)}%
RSI: {round(data['rsi'], 2)}

Напиши аналитический пост на русском языке.

Требования:
- длина 700–1200 символов
- не используй фразу "не является финансовой рекомендацией"
- объясни причину движения цены
- упомяни возможные риски
- добавь вывод по монете
- **не добавляй хештеги** (вообще никаких #)
- **не используй звёздочки, жирный шрифт, курсив, маркдаун** — пиши обычным текстом, без форматирования
- стиль живого автора, а не робота
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

    response = r.json()
    text = response["choices"][0]["message"]["content"]

    # Дополнительная очистка от случайных звёздочек (на всякий случай)
    text = text.replace("*", "").replace("_", "").replace("`", "")

    return text
