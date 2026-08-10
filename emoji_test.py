"""Emoji accents must be sparse, contextual and never use the old push-pin."""
from __future__ import annotations

from attention import AttentionSnapshot
from writer import _maybe_decorate_headline


def main() -> None:
    attention = AttentionSnapshot(
        score=80.0,
        change_15m=1.8,
        change_45m=3.0,
        volume_spike=7.0,
        range_expansion=2.0,
        turnover_1h=1_000_000.0,
        distance_atr=1.5,
        label="всплеск внимания",
        overextended=False,
    )
    outputs = [
        _maybe_decorate_headline(
            f"$TEST вариант {i}",
            format_id="hot_reaction",
            attention=attention,
            variant_index=i,
        )
        for i in range(100)
    ]
    decorated = [x for x in outputs if x.startswith(("⚡", "⚠️", "👀"))]
    assert 8 <= len(decorated) <= 35, len(decorated)
    assert all("📌" not in x for x in outputs)
    assert all(sum(x.count(e) for e in ("⚡", "⚠️", "👀")) <= 1 for x in outputs)
    print(f"EMOJI: OK | decorated={len(decorated)}/100 | contextual | no push-pin")


if __name__ == "__main__":
    main()
