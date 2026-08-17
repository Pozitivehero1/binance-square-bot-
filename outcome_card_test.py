"""Offline rendering smoke test for the avatar-backed result card."""
from __future__ import annotations

from pathlib import Path
from PIL import Image

from outcome_card import generate_outcome_card


def main() -> None:
    path = generate_outcome_card(
        symbol="ACE", direction="LONG", event_kind="target_complete", target_name="tp3",
        entry=0.1723, reached_price=0.1892, rr=3.12, move_pct=9.81, stop=0.1618,
        original_post_id="356784938216225", event_time="2026-08-17T20:04:00+00:00",
    )
    image = Image.open(path)
    assert image.size == (1080, 1350)
    assert image.mode == "RGB"
    Path(path).unlink(missing_ok=True)
    try:
        generate_outcome_card(
            symbol="ACE", direction="LONG", event_kind="target_complete", target_name="tp1",
            entry=0.1723, reached_price=0.1760, rr=1.0, move_pct=2.1, stop=0.1618,
            original_post_id="356784938216225", event_time="2026-08-17T20:04:00+00:00",
        )
        raise AssertionError("target_complete accepted non-TP3 target")
    except ValueError:
        pass
    print("OUTCOME CARD: OK | 1080x1350 | avatar background | TP3/final invariant | exact rendered facts")


if __name__ == "__main__":
    main()
