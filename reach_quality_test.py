"""Focused regression checks for semantic reach quality."""
from semantic_quality import semantic_quality_reasons


BAD = [
    "Уровень ыхода для первой фиксации.",
    "Тогда вперёд к первым целям. Всё остальное — дело времени.",
    "Если стоп рядом, лучше выйти без потерь.",
    "Покупатели поведут к цели уже через час.",
    "LINK сорвётся к первым целям менее чем за полчаса.",
    "Первая цель TP1 даст почти полтора риска уже в первые часы.",
    "Это тот случай, когда нужно действовать быстро или пропустить момент.",
    "semantic_package available=true",
    "Покупай прямо сейчас.",
]

GOOD = [
    "$SOL — объём x3.00, а цена почти не меняется.",
    "Если цена удержит 95.14, сценарий останется актуальным.",
    "$PEPE — вход LONG: 0.00000413–0.00000415, стоп 0.0000041, TP1 0.00000423.",
    "Цена ниже VWAP; для меня это повод наблюдать, а не предсказывать следующую свечу.",
    "За 5 минут цена снизилась на 0.4%, объём вырос до x2.1.",
    "Если TP1 будет достигнут, результат зафиксируем отдельно.",
]


for text in BAD:
    assert semantic_quality_reasons(text), (text, semantic_quality_reasons(text))

for text in GOOD:
    assert not semantic_quality_reasons(text), (text, semantic_quality_reasons(text))

print("reach quality semantic checks passed")
