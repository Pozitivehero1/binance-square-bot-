"""Text variation engine for Binance Square posts."""
from __future__ import annotations
import random

HOOK_VARIANTS = [
    "{ticker}: рынок подошёл к важной зоне, где решится следующий импульс",
    "{ticker}: текущий уровень показывает борьбу покупателей и продавцов",
    "{ticker}: наблюдаем реакцию цены возле ключевой области",
    "{ticker}: интересная зона для отслеживания ближайшего движения",
    "{ticker}: структура рынка формирует новый торговый сценарий",
]

PLAN_TITLES = [
    "🎯 План по уровням:",
    "📍 Торговый план:",
    "🎯 Ключевые уровни сценария:",
    "📊 План сделки:",
]

ENTRY_LABELS = ["Вход:", "Entry:", "Точка входа:", "Цена активации:"]
STOP_LABELS = ["Стоп:", "Stoploss:", "Stop Loss:", "Уровень отмены:"]

CTA_VARIANTS = [
    "Какой сценарий видите вы после реакции цены?",
    "Будете ждать подтверждение или вход от уровня?",
    "Какой уровень считаете самым важным?",
    "Интересно ваше мнение по этому сценарию.",
]

TAG_GROUPS = [
    ["#Crypto", "#MarketAnalysis", "#Trading"],
    ["#CryptoTrading", "#TechnicalAnalysis", "#MarketUpdate"],
    ["#Web3", "#TradingView", "#CryptoCommunity"],
    ["#Altcoins", "#CryptoNews", "#Trading"],
]

def choose(items, used=None):
    used = set(used or [])
    available = [x for x in items if x not in used]
    return random.choice(available or items)

def hashtags(symbol, direction):
    groups = TAG_GROUPS.copy()
    random.shuffle(groups)
    d = "LONG" if direction == "long" else "SHORT"
    return " ".join([f"#{symbol.upper()}", f"#{d}"] + groups[0])
