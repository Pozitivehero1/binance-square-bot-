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
print("analytics_test: OK")
tmp.cleanup()
