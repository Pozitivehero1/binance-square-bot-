from data import get_data
from indicators import build_indicators
from filters import score_signal
from writer import write_post
from publisher import publish
from trend import get_trending_symbols

import os

CACHE_FILE = "last_published.txt"

def get_last_published():
    if os.path.exists(CACHE_FILE):
        with open(CACHE_FILE, "r") as f:
            return f.read().strip()
    return None

def save_last_published(symbol):
    with open(CACHE_FILE, "w") as f:
        f.write(symbol)

symbols = get_trending_symbols(20)
print("TRENDING:")
print(symbols)

print("BOT STARTED")

candidates = []

for s in symbols:
    print(f"Analyzing {s}")
    raw = get_data(s)
    if raw is None:
        print(f"Skip {s}")
        continue

    d = build_indicators(raw)
    d["symbol"] = s
    score = score_signal(d)
    print(f"{s} score = {score}")

    if score >= 4:
        d["score"] = score
        candidates.append(d)

print("Candidates:", len(candidates))

if not candidates:
    print("No good setups found")
    exit()

candidates = sorted(candidates, key=lambda x: x["score"], reverse=True)
best = candidates[0]

# Проверка дубликата
last = get_last_published()
if last == best["symbol"]:
    print(f"Symbol {best['symbol']} already published last time. Skipping.")
    # Можно выбрать второго кандидата, если есть
    if len(candidates) > 1:
        best = candidates[1]
        print(f"Using next best: {best['symbol']}")
    else:
        print("No alternative candidate. Exiting.")
        exit()

print("Generating post for", best["symbol"])
post = write_post(best)
print("POST:")
print(post)

# Публикация
response = publish(post)
if response.status_code == 200:
    # Сохраняем символ, только если публикация успешна
    save_last_published(best["symbol"])
    print("DONE")
else:
    print("Publication failed, not saving symbol.")
