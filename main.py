from data import get_data
from indicators import build_indicators
from filters import score_signal
from writer import write_post
from publisher import publish

symbols = [
    "BTCUSDT","ETHUSDT","SOLUSDT","BNBUSDT",
    "XRPUSDT","DOGEUSDT","PEPEUSDT","WIFUSDT"
]

candidates = []

for s in symbols:

    raw = get_data(s)

    if raw is None:
        continue

    d = build_indicators(raw)
    d["symbol"] = s

    score = score_signal(d)

    if score >= 4:
        d["score"] = score
        candidates.append(d)

candidates = sorted(candidates, key=lambda x: x["score"], reverse=True)

for c in candidates[:3]:

    post = write_post(c)
    publish(post)

    print("POSTED:", c["symbol"])
