from analyzer import get_symbol_data
from filters import filter_signal
from writer import generate_post
from publisher import publish

symbols = [
    "BTCUSDT","ETHUSDT","SOLUSDT","BNBUSDT",
    "XRPUSDT","DOGEUSDT","PEPEUSDT","WIFUSDT",
    "ARBUSDT","OPUSDT","TIAUSDT"
]

candidates = []

for s in symbols:

    d = get_symbol_data(s)
    score = filter_signal(d)

    if score >= 4:
        d["score"] = score
        candidates.append(d)

# сортировка по качеству
candidates = sorted(candidates, key=lambda x: x["score"], reverse=True)

# публикуем максимум 3 поста
for c in candidates[:3]:

    post = generate_post(c)
    publish(post)

    print("POSTED:", c["symbol"])
