from data import get_data
from indicators import build_indicators
from filters import score_signal
from writer import write_post
from publisher import publish

from trend import get_trending_symbols

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

candidates = sorted(
    candidates,
    key=lambda x: x["score"],
    reverse=True
)

best = candidates[0]

print("Generating post for", best["symbol"])

post = write_post(best)

print("POST:")
print(post)

publish(post)

print("DONE")
