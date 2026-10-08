"""Publication watch distinguishes clean no-post cycles from confirmed IDs."""
from datetime import datetime, timezone, timedelta
import operations


def main():
    now = datetime(2026, 10, 8, tzinfo=timezone.utc)
    fresh = operations.summarize(outcome={"status": "published", "post_id": "123"},
        last_post=now - timedelta(minutes=10), now=now)
    assert fresh["post_id"] == "123" and not fresh["no_post_alert"]
    stale = operations.summarize(outcome={"status": "skipped", "detail": "AI unavailable"},
        last_post=now - timedelta(hours=9), now=now)
    assert stale["no_post_alert"] and stale["status"] == "skipped"
    print("operations_test: OK")


if __name__ == "__main__":
    main()
