"""Fresh-vs-stale 5m event regression test."""
from __future__ import annotations

import numpy as np
import pandas as pd

from attention import compute_micro_attention


def frame(*, fresh: bool) -> pd.DataFrame:
    rng = np.random.default_rng(51 if fresh else 52)
    n = 72
    close = 100 + np.cumsum(rng.normal(0, 0.07, n))
    open_ = np.r_[close[0], close[:-1]]
    high = np.maximum(open_, close) + 0.08
    low = np.minimum(open_, close) - 0.08
    volume = rng.uniform(900, 1200, n)
    if fresh:
        close[-1] = close[-2] * 1.012
        high[-1] = max(open_[-1], close[-1]) * 1.001
        volume[-1] = 6500
    else:
        # Huge event happened 25 minutes ago; latest candle cooled off.
        close[-6] = close[-7] * 1.018
        high[-6] = max(open_[-6], close[-6]) * 1.001
        volume[-6] = 24_000
        for i in range(-5, 0):
            close[i] = close[i - 1] * (1 + rng.normal(0, 0.00015))
            open_[i] = close[i - 1]
            high[i] = max(open_[i], close[i]) * 1.0003
            low[i] = min(open_[i], close[i]) * 0.9997
            volume[i] = 650
    idx = pd.date_range("2026-08-11", periods=n, freq="5min", tz="UTC")
    return pd.DataFrame({"open": open_, "high": high, "low": low, "close": close, "volume": volume}, index=idx)


def main() -> None:
    fresh = compute_micro_attention(frame(fresh=True))
    stale = compute_micro_attention(frame(fresh=False))
    assert fresh.phase == "fresh", fresh
    assert fresh.event_age_bars <= 1, fresh
    assert stale.event_age_bars >= 3, stale
    assert stale.phase == "stale", stale
    assert fresh.score > stale.score + 20, (fresh, stale)
    assert stale.stale_penalty >= 12, stale
    print(
        f"MICRO ATTENTION: OK | fresh={fresh.score:.1f}/{fresh.phase} "
        f"stale={stale.score:.1f}/{stale.phase} penalty={stale.stale_penalty:.1f}"
    )


if __name__ == "__main__":
    main()
