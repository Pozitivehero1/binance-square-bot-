"""Focused regression checks for v11.4.3 Russian-language integrity."""
from language_quality import language_quality_reasons


BAD = [
    "$AMP либо пробивает уровень и идёт дальше:\nin тогда первый take-profit успевает закрыться,\na второй и третий могут стать реальностью;\nor рынок возвращает контроль продавцам.",
    "in тогда рынок удерживает уровень, or продавцы возвращаются.",
    "and потом цена идёт выше.",
]

GOOD = [
    "$SOL — объём x3.00, цена возле VWAP. LONG-план: вход 102.6–102.9, стоп 101, TP1 104.5.",
    "$PEPE — ретест уровня. Если удержание есть, LONG остаётся рабочим.",
    "SHORT-план: Entry 11.64–11.66, Stop 11.70, TP1 11.55 / TP2 11.48 / TP3 11.40.",
    "Bitcoin сейчас выше VWAP, но без чистого входа.",
]

for text in BAD:
    assert language_quality_reasons(text), (text, language_quality_reasons(text))

for text in GOOD:
    assert not language_quality_reasons(text), (text, language_quality_reasons(text))

print("language quality checks passed")
