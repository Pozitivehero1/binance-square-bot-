"""Offline smoke test for all v9 chart compositions. No network/publication."""
from __future__ import annotations

import os

from attention import compute_attention
from chart import generate_chart
from filters import SignalFilter
from indicators import calculate_multi_timeframe
from self_test import _build_setup
from writer import _levels


STYLES = ("minimal_chart", "event_chart", "trade_map", "scenario_chart", "context_chart", "clean_chart")


def main() -> None:
    frames = _build_setup("long")
    mtf = calculate_multi_timeframe("TESTUSDT", frames)
    score = SignalFilter(min_score=0).evaluate(mtf)
    assert score is not None
    levels = _levels(mtf.tf_15m, score.direction)
    attention = compute_attention(frames["15m"], mtf.tf_15m, score.direction)
    paths = []
    try:
        for style in STYLES:
            path = generate_chart(
                "TESTUSDT", frames["15m"], "TEST",
                entry=levels["plan_entry"], entry_zone_low=levels["entry_zone_low"],
                entry_zone_high=levels["entry_zone_high"], tp1=levels["tp1"],
                tp2=levels["tp2"], tp3=levels["tp3"], stop=levels["stop"],
                direction=score.direction, decision_level=levels["decision"],
                decision_mode=levels["decision_mode"], vol_rel=attention.volume_spike,
                indicator=mtf.tf_15m, visual_style=style,
                headline="$TEST: визуальный smoke test", signal_label="проверка уровня",
            )
            assert path and os.path.exists(path), style
            assert os.path.getsize(path) > 10_000, (style, os.path.getsize(path))
            paths.append(path)
        print(f"VISUALS: OK | styles={len(STYLES)} | all files >10KB")
    finally:
        for path in paths:
            try:
                os.remove(path)
            except OSError:
                pass


if __name__ == "__main__":
    main()
