"""Recent mature data should nudge, never force, EVENT vs TRADE."""
from datetime import datetime, timezone, timedelta
from content_strategy import lane_bonus


def _store(ev, tr, n=20):
    now = datetime(2026, 10, 8, tzinfo=timezone.utc)
    posts = {}
    for lane, views in (("EVENT", ev), ("TRADE", tr)):
        for i in range(n):
            posts[f"{lane}{i}"] = {"lane": lane,
                "published_at": (now - timedelta(days=3)).isoformat(),
                "milestones": {"24h": {"views": views}}, "learning_eligible": True}
    return {"posts": posts}, now


def main():
    s, now = _store(110, 60)
    plus, _ = lane_bonus(s, now=now)
    assert 0 < plus <= 4, plus
    s, now = _store(40, 120)
    minus, _ = lane_bonus(s, now=now)
    assert -4 <= minus < 0, minus
    s, now = _store(1000, 1, n=5)
    blank, _ = lane_bonus(s, now=now)
    assert blank == 0
    print("content_strategy_test: OK")


if __name__ == "__main__":
    main()
