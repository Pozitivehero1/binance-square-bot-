import requests
import os

MISTRAL_API = os.getenv("MISTRAL_API")

def write_post(data):
    prompt = f"""
Ты опытный криптоаналитик Binance Square.

Монета: {data['symbol']}
Цена: {data['price']}
Изменение за последние 10 свечей: {round(data['change'], 2)}%
RSI: {round(data['rsi'], 2)}
EMA20: {round(data['ema20'], 2)}
EMA50: {round(data['ema50'], 2)}

Напиши аналитический пост на русском языке строго по следующей структуре:

1. Краткий анализ текущей ситуации (что движет ценой, технические уровни, настроение). Перед названием монеты ставь знак $, например $BTC, $ETH. Не указывай монеты так: $BTCUSDT, указывай просто $BTC.
2. Вход (цена входа, причина, по какой стратегии входим).
3. TP1 (Take Profit 1) – ближайшая цель.
4. TP2 (Take Profit 2) – средняя цель.
5. TP3 (Take Profit 3) – максимальная цель (оптимистичный сценарий).
6. Стоп-лосс (уровень, при котором выходим в минус).
7. Вывод – итоговый вердикт, стоит ли торговать или наблюдать.

Требования:
- длина 500-700 символов
- не используй фразу "не является финансовой рекомендацией"
- не добавляй хештеги (#) вообще
- не используй звёздочки, жирный шрифт, курсив, маркдаун – пиши обычным текстом, без форматирования
- стиль живого автора, а не робота, где уместно добавляй смайлы
- числа и уровни указывай с двумя знаками после запятой (например, 1.23)
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
                {"role": "user", "content": prompt}
            ]
        },
        timeout=60
    )

    response = r.json()
    text = response["choices"][0]["message"]["content"]

    # Очистка от случайного форматирования
    for ch in ['*', '_', '`', '#']:
        text = text.replace(ch, '')

    return text
