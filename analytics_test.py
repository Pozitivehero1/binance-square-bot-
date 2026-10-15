from __future__ import annotations

import os
import tempfile
from pathlib import Path

# Set isolated state before importing store.
tmp = tempfile.TemporaryDirectory()
os.environ["STATE_DIR"] = tmp.name
os.environ["LEARNING_ONLY"] = "1"
os.environ["BOT_VERSION"] = "v11.15"

from square_public_stats import parse_profile_payload, extract_symbol
from performance_store import merge_public_stats, load_store, build_learning_summary, record_publication
from dashboard_builder import build_dashboard_payload

payload = {
    "code": "000000",
    "data": {
        "contents": [
            {
                "id": 123,
                "bodyTextOnly": "$DOGE — тестовый пост",
                "viewCount": 184,
                "likeCount": 2,
                "commentCount": 1,
                "quoteCount": 0,
                "shareCount": 3,
                "createTime": 1786556489000,
                "imageList": ["https://example.invalid/test.png"],
                "lan": "ru",
            }
        ],
        "timeOffset": 1786556488999,
    },
}
rows, offset = parse_profile_payload(payload)
assert len(rows) == 1 and rows[0].post_id == "123"
assert rows[0].views == 184 and rows[0].symbol == "DOGE"
assert offset == 1786556488999
assert extract_symbol("abc $BROCCOLI714 test") == "BROCCOLI714"
merge_public_stats(rows, profile_uid="public-test")
record_publication(
    post_id="123",
    symbol="DOGE",
    market_symbol="DOGEUSDT",
    text="$DOGE — тестовый пост",
    lane="EVENT",
    direction="OBSERVATION",
    content_format="event_one_price",
    visual_style="minimal_chart",
    event_class="audience_breakout",
    writer_source="groq_event",
)
store = load_store()
assert "123" in store["posts"]
assert store["posts"]["123"]["stats"]["views"] == 184
assert store["posts"]["123"]["engine_version"] == "v11.15"
summary = build_learning_summary(store)
assert summary["learning_only"] is True
out = build_dashboard_payload()
assert out["posts"][0]["views"] == 184
assert out["posts"][0]["engine_version"] == "v11.15"
assert out["meta"]["profile_uid"] == "public-test"

# Comparable 2h/6h/24h cohorts must report hit rates and observed engagement
# from the actual narrow-window snapshot, never lifetime/early learning views.
from datetime import datetime, timedelta, timezone
from content_metrics import build_content_metrics
now = datetime(2026, 10, 15, 12, tzinfo=timezone.utc)
def observation(pid, views, age=1440, **engagement):
    return {
        "post_id": pid, "lane": "EVENT", "direction": "OBSERVATION",
        "published_at": (now - timedelta(days=2)).isoformat(),
        "content_milestones": {"24h": {"age_minutes": age, "views": views, **engagement}},
    }
cohort = build_content_metrics({"posts": {
    "a": observation("a", 50, likes=1),
    "b": observation("b", 150, likes=2, comments=1),
    "c": observation("c", 350, shares=1),
    "early": observation("early", 999, age=1200, likes=99),
}}, now)
rows = {g["kind"]: g for g in cohort["groups"]}
snap = rows["observation"]["milestones"]["24h"]
assert snap["samples"] == 3 and snap["median_views"] == 150, snap
assert snap["posts_100_plus"] == 2 and snap["rate_100_plus_pct"] == 66.7, snap
assert snap["posts_300_plus"] == 1 and snap["rate_300_plus_pct"] == 33.3, snap
assert snap["views_sum"] == 550 and snap["interactions"] == 5, snap
assert snap["interaction_rate_pct"] == 0.909, snap
assert rows["trade_plan"]["milestones"]["24h"]["rate_100_plus_pct"] is None

print("analytics_test: OK")
tmp.cleanup()
