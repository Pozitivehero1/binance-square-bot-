"""Compact outage copy: measured event, interpretation, one conditional plan."""
from __future__ import annotations


def market_narrative(*, ticker, move5, move15, volume5, volume15, price, level,
                     plan_available, direction, decision_mode, index):
    from writer import _fmt_pct, _fmt_price, _fmt_x

    change = _fmt_pct(move15)
    short = _fmt_pct(move5) if move5 is not None else None
    rising = move15 > 0
    action = "рост" if rising else "снижение" if move15 < 0 else "пауза"
    reversal = move5 is not None and move5 * move15 < 0
    volume = _fmt_x(volume15)
    point = _fmt_price(level)
    heads = (
        f"{ticker} — {change} за 15 минут: что видно по объёму",
        f"{ticker}: {action} на 15 минутах, объём {volume} обычного",
        f"{ticker} — короткое движение и проверка уровня {point}",
        f"{ticker}: {change} за 15 минут — разбираю реакцию цены",
        f"{ticker}: цена возле {point} — что изменилось за 15 минут",
        f"{ticker} — {action} и объём: проверяю, совпадают ли они",
        f"{ticker}: движение {change}, следующий ориентир — {point}",
        f"{ticker} — цена и активность на коротком участке",
    )
    headline = heads[index % len(heads)]
    if reversal:
        facts = f"За 5 минут {short}: цена пошла против 15-минутного движения ({change})."
    elif short is not None:
        facts = (
            f"За 5 минут {short}, за 15 минут {change}.",
            f"Последние 15 минут дали {change}; на 5 минутах {short}.",
            f"Изменение цены: {short} за 5 минут и {change} за 15 минут.",
        )[(index // 2) % 3]
    else:
        facts = f"Изменение за 15 минут {change}."

    if volume15 >= 1.5:
        evidence = (
            f"Объём за 15 минут {volume} обычного: активность повышена.",
            f"На 15 минутах объём {volume} нормы — торгуют активнее обычного.",
            f"Активность выше нормы: объём 15-минутной свечи {volume} обычного.",
        )[(index // 3) % 3]
    elif volume15 < 0.8:
        evidence = f"Объём за 15 минут {volume} обычного: активность ниже нормы."
    else:
        evidence = f"Объём за 15 минут {volume} обычного: близко к норме."

    relation = "выше" if price >= level else "ниже"
    close = _fmt_price(price)
    vol5 = _fmt_x(volume5) if volume5 is not None else None
    # Distinct factual angles, not interchangeable motivational introductions.
    # Each angle selects a different subset of the actual snapshot.
    angle = index % 16
    if angle == 1 and short is not None:
        headline = f"{ticker}: короткий участок {short} — сверяю с 15 минутами"
        facts = f"Более широкий отрезок дал {change}."
        evidence = ("Направления расходятся: короткое движение уже идёт против него."
                    if reversal else "Сопоставляю оба отрезка с объёмом, а не только последнюю свечу.")
    elif angle == 2:
        headline = f"{ticker}: закрытие {close}, ориентир рядом — {point}"
        facts = f"15-минутная свеча закрылась {relation} уровня. Изменение за 15 минут {change}."
        evidence = "Одно закрытие ещё не доказывает устойчивость движения."
    elif angle == 3 and vol5 is not None:
        headline = f"{ticker} — проверка объёма на разных отрезках"
        facts = f"На 5 минутах {vol5} обычного объёма; на 15 минутах {volume}."
        evidence = f"Цена за 15 минут изменилась на {change}. Это активность, а не гарантия продолжения."
    elif angle == 4:
        headline = f"{ticker}: {action} {change} — где проверять сценарий"
        facts = f"Ближайшая рабочая отметка — {point}; закрытие свечи {close}."
        evidence = "Сам размер движения не показывает, удержится ли цена за уровнем."
    elif angle == 5:
        headline = f"{ticker} — объём {volume}: что он подтверждает сейчас"
        facts = f"За 15 минут цена дала {change}."
        evidence = ("Торговая активность повышена, но объём сам по себе не показывает направление следующей свечи."
                    if volume15 >= 1.5 else "Повышенной активности на 15 минутах нет: один объём не подтверждает импульс.")
    elif angle == 6:
        headline = f"{ticker}: цена {relation} {point} — это условие, не результат"
        facts = f"Последнее закрытие — {close}, изменение за 15 минут {change}."
        evidence = "По одному снимку нельзя считать сценарий уже исполненным."
    elif angle == 7 and short is not None:
        headline = f"{ticker} — что осталось от движения на 5 минутах"
        facts = f"Свежая 5-минутная свеча: {short}. На 15-минутном отрезке {change}."
        evidence = ("Локальное направление сменилось; продолжение прежнего движения требует новой реакции."
                    if reversal else "Направление оцениваю вместе с реакцией на рабочую зону, без прогноза по одной свече.")
    elif angle == 8:
        headline = f"{ticker}: {change} на 15 минутах — движение уже произошло"
        facts = f"Объём этого участка {volume} обычного."
        evidence = "Прошедшее изменение нельзя считать будущей прибылью. Условия следующей сделки проверяю отдельно."
    elif angle == 9:
        headline = f"{ticker} — район {point} отделяет наблюдение от решения"
        facts = f"Закрытие {close} находится {relation} этой отметки. Объём на 15 минутах — {volume} нормы."
        evidence = "Проверяю именно поведение цены у зоны."
    elif angle == 10:
        headline = f"{ticker}: {action} и торговая активность — разные факты"
        facts = f"Изменение за 15 минут {change}; объём {volume} нормы."
        evidence = "Большой объём не равен покупкам: в каждой сделке есть обе стороны. Направление оцениваю по цене."
    elif angle == 11:
        headline = f"{ticker} — сценарий от цены {point}, без погони за свечой"
        facts = f"Последний 15-минутный отрезок дал {change}; закрытие — {close}."
        evidence = "Уже пройденный участок не использую как обещание повторения."
    elif angle == 12 and vol5 is not None and short is not None:
        headline = f"{ticker}: локальная активность — объём на 5 минутах {vol5}"
        facts = f"Изменение за тот же период {short}."
        evidence = "Этот отрезок описывает короткую реакцию. Для вывода по более широкому движению его недостаточно."
    elif angle == 13:
        headline = f"{ticker} — что подтверждено свечой, а что ещё предстоит проверить"
        facts = f"Закрытие на 15 минутах {close}; объём {volume} обычного."
        evidence = f"Следующая проверка — поведение возле {point}. Будущая реакция в эти данные ещё не входит."
    elif angle == 14:
        headline = f"{ticker}: {action} есть в данных, причины — нет"
        facts = f"За 15 минут {change}, объём {volume} нормы."
        evidence = "Этих цифр недостаточно для выводов о новостях или крупных покупателях. Разбираю только наблюдаемую цену."
    elif angle == 15:
        headline = f"{ticker} — уровень {point} важнее размера прошлой свечи"
        facts = f"Текущий снимок: закрытие {close} после изменения {change} за 15 минут."
        evidence = "Проверка сценария начинается с реакции у зоны; прошлая доходность её не заменяет."

    if plan_available:
        if decision_mode == "retest_hold":
            meaning = "Сценарий только после возврата в зону и удержания уровня."
        elif decision_mode == "retest_reject":
            meaning = "Сценарий только после возврата в зону и отклонения цены вниз."
        elif decision_mode in {"breakout_confirm", "breakdown_confirm"}:
            meaning = "Сценарий только после закрепления за уровнем; до этого жду."
        else:
            meaning = (
                "Цена у рабочей зоны; для сделки нужна реакция на уровень.",
                "Смотрю на реакцию в зоне: без неё сценарий не активирую.",
                "Для меня условие сделки — удержание нужной стороны зоны.",
            )[(index // 2) % 3]
        return f"{headline}\n\n{facts} {evidence}\n\n{meaning}"

    endings = (
        f"Цена {relation} {point}. Смотрю, удержится ли она с этой стороны уровня; само движение ещё не подтверждает продолжение.",
        f"Ориентир — {point}, цена сейчас {relation}. Если активность исчезнет у уровня, одного движения для вывода недостаточно.",
        f"Цена {relation} {point}. Следующая проверка — реакция на этот уровень: продолжение движения пока остаётся условием, а не фактом.",
        f"Наблюдаю за {point}: цена {relation} уровня. Если вернётся к нему, важна реакция цены вместе с объёмом, а не одна свеча.",
    )
    return f"{headline}\n\n{facts} {evidence}\n\n{endings[index % len(endings)]}"
