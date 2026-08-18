"""Synthetic regression tests for the bounded adaptive performance layer."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import os
from unittest.mock import patch

from adaptive import score_adaptive


def _post(symbol: str, views: float, published: datetime, lane: str = "EVENT") -> dict:
    return {
        "symbol": symbol,
        "published_at": published.isoformat(),
        "lane": lane,
        "milestones": {"24h": {"views": views}},
        "stats": {"views": views},
    }


def main() -> None:
    now = datetime(2026, 8, 17, 0, 15, tzinfo=timezone.utc)  # 03:15 UTC+3
    posts = {}
    idx = 0
    # Account baseline around 80, enough mature samples for adaptive mode.
    for d in range(1, 8):
        for j in range(12):
            idx += 1
            sym = f"ALT{idx}"
            published = (now - timedelta(days=d)).replace(hour=10 + (j % 6), minute=0)
            posts[str(idx)] = _post(sym, 74 + (j % 4) * 4, published, "EVENT" if j % 2 else "TRADE")
    # Proven winner and loser with meaningful sample sizes.
    for j, v in enumerate([118, 124, 131, 142, 115, 136, 128, 122]):
        idx += 1
        posts[str(idx)] = _post("TUT", v, (now - timedelta(days=1 + j // 3)).replace(hour=12 + (j % 3), minute=0), "EVENT")
    for j, v in enumerate([28, 36, 41, 33, 45, 30, 38, 35]):
        idx += 1
        posts[str(idx)] = _post("BTC", v, (now - timedelta(days=1 + j // 3)).replace(hour=15 + (j % 3), minute=0), "EVENT")
    # Strong local-hour 03 sample (UTC hour 00).
    for j, v in enumerate([110, 125, 140, 118, 132, 121]):
        idx += 1
        posts[str(idx)] = _post(f"H{j}", v, now - timedelta(days=1 + j), "EVENT")

    store = {"posts": posts}
    env = {
        "ENABLE_ADAPTIVE_RANKING": "1",
        "LEARNING_ONLY": "0",
        "ADAPTIVE_MIN_MATURE_SAMPLES": "80",
        "ANALYTICS_TZ_OFFSET": "3",
    }
    # Outcome journal: TUT has several verified stops while other symbols provide
    # enough global history to activate the soft signal-quality component.
    trades = {}
    for j in range(4):
        trades[f"tut{j}"] = {
            "tracking_version": 2, "public_plan_complete": True, "status": "closed",
            "close_reason": "stop", "symbol": "TUT",
            "published_at": (now - timedelta(hours=6 + j)).isoformat(),
            "hits": {"tp1": False, "tp2": False, "tp3": False, "stop": True},
        }
    for j in range(4):
        trades[f"win{j}"] = {
            "tracking_version": 2, "public_plan_complete": True, "status": "closed",
            "close_reason": "public_targets_complete", "symbol": f"WIN{j}",
            "published_at": (now - timedelta(hours=8 + j)).isoformat(),
            "hits": {"tp1": True, "tp2": True, "tp3": True, "stop": False},
        }
    journal = {"schema_version": 2, "trades": trades}

    with patch.dict(os.environ, env, clear=False), patch("adaptive.load_store", return_value=store), patch("adaptive.load_journal", return_value=journal):
        tut = score_adaptive(symbol="TUT", lane="EVENT", live_score=75, micro_score=76, now=now)
        tut_plan = score_adaptive(symbol="TUT", lane="EVENT", live_score=75, micro_score=76, plan_valid=True, now=now)
        btc = score_adaptive(symbol="BTC", lane="EVENT", live_score=75, micro_score=76, now=now)
        new = score_adaptive(symbol="NEWCOIN", lane="EVENT", live_score=82, micro_score=84, event_class="fresh_event", now=now)

    assert tut.enabled and btc.enabled and new.enabled
    assert tut.ticker_component > 0, tut
    assert btc.ticker_component < 0, btc
    assert tut.hour_component > 0, tut
    assert tut_plan.total < tut.total, (tut_plan, tut)
    assert "outcome=" in tut_plan.reason
    assert 0 < new.exploration_component <= 2.5, new
    assert abs(tut.total) <= 14 and abs(btc.total) <= 14
    print(f"ADAPTIVE: OK | TUT reach {tut.total:+.1f} plan {tut_plan.total:+.1f} | BTC {btc.total:+.1f} | explore {new.exploration_component:+.1f}")


if __name__ == "__main__":
    main()
