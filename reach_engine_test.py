"""Focused v11.6 regressions for evidence-weighted reach learning."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import Mock, patch

from adaptive import _metric, score_content_performance
from outcome_engine import process_outcomes
from performance_store import reach_recovery_state
from reach_editorial import editorial_reach_adjustment


NOW = datetime(2026, 9, 2, 4, 30, tzinfo=timezone.utc)


def post(index: int, *, views: float, fmt: str, writer: str, published: datetime) -> dict:
    return {
        "post_id": str(index),
        "published_at": published.isoformat(),
        "symbol": f"T{index}",
        "lane": "TRADE",
        "direction": "LONG",
        "content_format": fmt,
        "writer_source": writer,
        "event_class": "active_market",
        "learning_eligible": True,
        "milestones": {"24h": {"views": views}},
        "stats": {"views": views},
    }


# The account-calibrated early projections must stay close to observed 24h
# growth, never return to the old x5/x3.2/x2 inflation.
early = {"published_at": NOW.isoformat(), "milestones": {"30m": {"views": 100}}}
assert _metric(early, NOW) == 125.0

posts = {}
for i in range(35):
    posts[f"g{i}"] = post(
        i, views=180 + i % 10, fmt="no_chase", writer="mistral",
        published=NOW - timedelta(hours=25 + i * 2),
    )
for i in range(35):
    posts[f"b{i}"] = post(
        100 + i, views=45 + i % 8, fmt="risk_first", writer="deterministic",
        published=NOW - timedelta(hours=26 + i * 2),
    )
store = {"posts": posts}
with patch("adaptive.load_store", return_value=store):
    good = score_content_performance(
        lane="TRADE", content_format="no_chase", writer_source="mistral",
        event_class="active_market", direction="LONG", now=NOW,
    )
    bad = score_content_performance(
        lane="TRADE", content_format="risk_first", writer_source="deterministic",
        event_class="active_market", direction="LONG", now=NOW,
    )
assert good.enabled and bad.enabled
assert good.total > 0 and bad.total < 0 and good.total > bad.total, (good, bad)

specific = editorial_reach_adjustment(
    "$ONG: объём x3,2, а цена держится около 0.088 после движения +1,4% за 15 минут.\n\n"
    "Именно этот уровень сейчас отделяет продолжение импульса от его затухания."
)
generic = editorial_reach_adjustment(
    "$ONG либо продолжит движение, либо вернётся назад. Первый сценарий даст чёткий план, "
    "а второй потребует новой структуры рынка."
)
assert specific.score > generic.score, (specific, generic)

# Recovery compares projected current reach with mature 24h daily buckets.
baseline_posts = {}
for day in range(1, 5):
    for j in range(3):
        item = post(
            day * 10 + j, views=100, fmt="no_chase", writer="mistral",
            published=NOW - timedelta(days=day, hours=2 + j),
        )
        baseline_posts[f"d{day}-{j}"] = item
weak = post(999, views=20, fmt="no_chase", writer="mistral", published=NOW - timedelta(minutes=35))
weak["milestones"] = {"30m": {"views": 20}}
baseline_posts["current"] = weak
with patch("performance_store.load_store", return_value={"posts": baseline_posts}):
    enabled, current, baseline = reach_recovery_state(now=NOW)
assert enabled and current == 25.0 and baseline == 300.0, (enabled, current, baseline)

# Outcome truth may refresh before the market scan, but publication must remain
# queued until the fresh TRADE/EVENT pipeline has had a chance to use the slot.
pending_trade = {
    "pending_followup": {
        "kind": "target_complete",
        "target_name": "TP3",
        "event_at": NOW.isoformat(),
    },
    "followups": [],
}
with patch("outcome_engine.load_journal", return_value={"trades": {"setup": pending_trade}}), \
     patch("outcome_engine._refresh_trade"), \
     patch("outcome_engine.save_journal"), \
     patch("outcome_engine.publish") as mocked_publish:
    published = process_outcomes(
        memory=Mock(), guard=Mock(), dry_run=False, refresh_only=True,
    )
assert published is False and mocked_publish.call_count == 0
assert pending_trade["pending_followup"] is not None

print(
    "REACH ENGINE: OK | early projection calibrated | content performance affects ranking | "
    "specific copy wins | recovery baseline uses mature buckets | outcomes cannot steal fresh slots"
)
