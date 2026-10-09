"""Headlines are reflowed only at sentence boundaries; never inside phrases."""
from editorial_repair import normalize_headline, fix_russian_time


def main():
    src = (
        "$BTC — объём вырос в 2 раза, но цену ещё нужно проверить. "
        "За последние 5 минут цена прибавила 1.2%, поэтому важно увидеть "
        "закрепление выше уровня 102.5."
    )
    result = normalize_headline(src)
    headline, body = result.split("\n\n", 1)
    assert headline.endswith("проверить."), repr(headline)
    assert "За последние 5 минут" in body
    assert 27 <= len(headline) <= 110
    assert "".join(result.split()) == "".join(src.split())

    # No safe sentence boundary means no reflow: the regular validators may
    # reject the model draft, but malformed prose never gets published.
    unbreakable = "$BTC — " + ("серьёзный всплеск объёма за последние 5 минут " * 4)
    assert normalize_headline(unbreakable) == unbreakable.strip()

    # A complete sentence that is too short is not a valid headline.
    tiny = "$BTC растёт. " + ("Что будет с уровнем и объёмом на рынке сейчас " * 4)
    assert normalize_headline(tiny) == tiny.strip()

    assert normalize_headline("$BTC — уже вырос на 1.4%") == "$BTC — уже вырос на 1.4%"
    assert fix_russian_time("за 45 минуты и 15 минуты, за 2 минуты") == (
        "за 45 минут и 15 минут, за 2 минуты"
    )
    print("editorial_repair_test: OK")


if __name__ == "__main__":
    main()
