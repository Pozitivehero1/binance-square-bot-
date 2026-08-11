"""Observation-only EVENT chart must render without fake TP/SL levels."""
from __future__ import annotations

import os

from chart import generate_chart
from event_writer import event_decision_level
from indicators import calculate_multi_timeframe
from self_test import _build_setup


def main() -> None:
    frames = _build_setup("long")
    mtf = calculate_multi_timeframe("TSTUSDT", frames)
    ind = mtf.tf_15m
    assert ind is not None
    path = generate_chart(
        "TSTUSDT",
        frames["15m"],
        "TST",
        entry=None,
        tp1=None,
        tp2=None,
        tp3=None,
        stop=None,
        direction="long",
        support=ind.support,
        resistance=ind.resistance,
        decision_level=event_decision_level(ind),
        decision_mode="at_level",
        vol_rel=3.8,
        indicator=ind,
        visual_style="event_chart",
        headline="$TST стал активнее — пока наблюдение, а не готовая сделка",
        signal_label="fresh event",
    )
    try:
        assert path and os.path.isfile(path)
        assert os.path.getsize(path) > 10_000
    finally:
        if path and os.path.exists(path):
            os.remove(path)
    print("EVENT VISUAL: OK | observation-only chart rendered without TP/SL")


if __name__ == "__main__":
    main()
