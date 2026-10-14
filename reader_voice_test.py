"""Plain-language ranking must not censor genuine technical insight or plans."""
from reader_voice import assess_voice, prose_only
from reach_editorial import editorial_reach_adjustment
from editorial_policy import review_copy


def main():
    clear = (
        "$PUMP — торгов стало больше, но цена пока не закрепилась выше важной отметки"
        "\n\nЗа пять минут цена снизилась на 0.84%. Торгов было заметно больше обычного. "
        "Это повод посмотреть на движение внимательнее, но не доказательство будущего роста."
    )
    jargon = (
        "$PUMP — RSI 65.5, ADX 15.7, VWAP 0.005044"
        "\n\nРетест сетапа и дивергенция: силы есть, а тренда нет. "
        "Рынок решает, что делать дальше."
    )
    one_term = "$BTC — цена выросла, но RSI сам по себе не обещает продолжения движения."
    assert assess_voice(clear).tech_terms == 0
    assert assess_voice(one_term).tech_terms == 1
    assert assess_voice(clear).score > assess_voice(one_term).score > assess_voice(jargon).score
    assert editorial_reach_adjustment(clear).score > editorial_reach_adjustment(jargon).score
    assert review_copy(clear).allowed
    assert review_copy(jargon).allowed  # Style alone never blocks truthful text.
    plan = (
        clear + "\n\nLONG-план: зона 1.25–1.27, стоп 1.20"
        "\nЦели: TP1 1.33 → TP2 1.39 → TP3 1.44"
    )
    assert prose_only(plan) == clear
    assert assess_voice(plan) == assess_voice(clear)
    print("READER VOICE TEST: OK — accessible prose, accurate plans, no extra hard gate")


if __name__ == "__main__":
    main()
