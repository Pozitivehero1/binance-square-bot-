"""Test faithful headline reflow and noninventive language edits."""
from editorial_repair import normalize_headline, fix_russian_time


def main():
    src = "$BTC — " + ("важное движение цены с подтверждённым объёмом " * 4) + "1.234"
    output = normalize_headline(src)
    first, rest = output.split("\n\n", 1)
    assert first.startswith("$BTC") and len(first) <= 110
    assert rest.endswith("1.234")
    assert "".join(output.split()) == "".join(src.split())
    assert normalize_headline("$BTC — уже вырос на 1.4%") == "$BTC — уже вырос на 1.4%"
    assert fix_russian_time("за 45 минуты и 15 минуты, за 2 минуты") == "за 45 минут и 15 минут, за 2 минуты"
    print("editorial_repair_test: OK")


if __name__ == "__main__":
    main()
