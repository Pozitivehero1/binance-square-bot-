from text_integrity import artifact_reasons, sanitize_safe_markup
from publisher import normalize_square_cashtags


def main() -> None:
    assert sanitize_safe_markup("$ENA — **VWAP 0.1646**") == "$ENA — VWAP 0.1646"
    assert "prompt-word-exactly" in artifact_reasons("$SPK — **exactly** 0.02215")
    assert "percent-placeholder" in artifact_reasons("$AAVE уже +Y% сегодня")

    broken = "$LINK 11.64------_______<<>>#"
    reasons = artifact_reasons(broken)
    assert "symbol-run" in reasons
    assert "angle-bracket-run" in reasons

    assert normalize_square_cashtags("$BTC: цена") == "$BTC — цена"
    assert not artifact_reasons("$PENDLE — вход SHORT: 1.789–1.795 · стоп 1.81")
    print("text_integrity_test: OK")


if __name__ == "__main__":
    main()
