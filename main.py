from data import get_data
from indicators import build_indicators
from filters import score_signal
from writer import write_post
from publisher import publish
from trend import get_trending_symbols
from history import get_recently_published, add_published, cleanup_history

import os

# Очищаем историю старше суток (чтобы не раздувалась)
cleanup_history()

symbols = get_trending_symbols(50)
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

# Исключаем монеты, опубликованные за последний час
recent_published = get_recently_published(minutes=60)
print(f"Recently published (last hour): {recent_published}")

filtered = [c for c in candidates if c["symbol"] not in recent_published]

if not filtered:
    print("All candidates were published recently. Skipping.")
    exit()

# Сортируем по скору
filtered = sorted(filtered, key=lambda x: x["score"], reverse=True)
best = filtered[0]

print("Generating post for", best["symbol"])
post = write_post(best)
print("POST:")
print(post)

response = publish(post)
if response.status_code == 200:
    # Добавляем в историю после успешной публикации
    add_published(best["symbol"])
    print("DONE")
else:
    print("Publication failed, not saving symbol.")
