"""Focused regression checks for Russian-language integrity."""
from language_quality import language_quality_reasons


BAD = [
    "$AMP либо пробивает уровень и идёт дальше:\nin тогда первый take-profit успевает закрыться,\na второй и третий могут стать реальностью;\nor рынок возвращает контроль продавцам.",
    "in тогда рынок удерживает уровень, or продавцы возвращаются.",
    "and потом цена идёт выше.",
    "$ORCA: Оверсаттеринг момента -- Окоражилась ошибка RSI при росте цены выше рабочего уровня",
    "Важно услышать про уровень XA/RVAB где текущая цена сидит высоко относительно динамики",
    "Cashtag @oracetrade",
    "Это классическое срезы сопротивления перед возможным отскоком к рабочей зоне ШОРТА ($HEMI≈v00397).",
    "Зона входа фиксирована как [v00389;v00405]",
    "$DASH Cashbag позволяет реализовать эту.",
]

GOOD = [
    "$SOL — объём x3.00, цена возле VWAP. LONG-план: вход 102.6–102.9, стоп 101, TP1 104.5.",
    "$PEPE — ретест уровня. Если удержание есть, LONG остаётся рабочим.",
    "SHORT-план: Entry 11.64–11.66, Stop 11.70, TP1 11.55 / TP2 11.48 / TP3 11.40.",
    "Bitcoin сейчас выше VWAP, но без чистого входа.",
    "$TAO уже сделал +2.9% за 45 минут, и именно поэтому лонг от текущих не беру.",
]

for text in BAD:
    assert language_quality_reasons(text), (text, language_quality_reasons(text))

for text in GOOD:
    assert not language_quality_reasons(text), (text, language_quality_reasons(text))

print("language quality checks passed")
