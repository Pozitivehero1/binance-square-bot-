"""Focused regressions for the v11.4.5 final production text guard."""
from production_guard import final_text_reasons, strip_embedded_trade_plan
from semantic_quality import semantic_quality_reasons


BROKEN_SOL = """$SOL уверенно топчется у ключевой отметки вверх от VWAP.
Первый путь — покупатели закрепятся выше зоны входа и потянут к первой цели.
LONG | вход 97,87–98,03 | стоп 97,58
TP1 98,99 | TP2 99,58 | TP3 100,

LONG-план: зона 97.87–98.03, стоп 97.58
Цели: TP1 98.99 → TP2 99.58 → TP3 100.2"""

cleaned = strip_embedded_trade_plan(BROKEN_SOL)
assert "$SOL" in cleaned
assert "TP1" not in cleaned and "TP2" not in cleaned and "TP3" not in cleaned
assert "LONG-план" not in cleaned
assert "LONG | вход" not in cleaned

# The malformed production example is caught even if it somehow reaches the
# final publisher without canonicalization.
assert final_text_reasons(BROKEN_SOL)

CANONICAL = """$SOL — цена у рабочей зоны; смотрю на реакцию без прогноза.

LONG-план: зона 97.87–98.03, стоп 97.58
Цели: TP1 98.99 → TP2 99.58 → TP3 100.2"""
assert not final_text_reasons(CANONICAL)

BAD_NARRATIVES = [
    "$XRP — покупатели Ripple решили именно сейчас заявить о себе, а продавцы не успели среагировать.",
    "$XRP — движение началось после обеда по местному рынку.",
    "$RE — стоп ставлю у сопротивления третьего порядка.",
    "$RE — выхожу при малейшей слабости рынка.",
]
for text in BAD_NARRATIVES:
    assert semantic_quality_reasons(text), (text, semantic_quality_reasons(text))

GOOD_NARRATIVES = [
    "$SOL — объём x3.00, а цена почти не меняется.",
    "$ENA — цена выше VWAP; для LONG важна реакция в рабочей зоне.",
]
for text in GOOD_NARRATIVES:
    assert not semantic_quality_reasons(text), (text, semantic_quality_reasons(text))

print("production guard checks passed")
