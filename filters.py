def filter_signal(d):

    score = 0

    # тренд
    if d["ema20"] > d["ema50"]:
        score += 2

    # импульс
    if abs(d["change"]) > 2:
        score += 2

    # активность
    if d["volume"] > 100000:
        score += 1

    # не перегрето
    if 45 < d["rsi"] < 75:
        score += 2

    # слишком шумно — выкидываем
    if d["rsi"] > 85:
        return 0

    return score
