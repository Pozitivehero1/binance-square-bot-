"""Refresh public Square metrics and optionally build the static dashboard."""
from __future__ import annotations

import argparse
import logging
import os
from datetime import datetime, timezone

from runtime import load_project_env, setup_logging
from performance_store import merge_public_stats, load_store
from square_public_stats import BinanceSquarePublicClient

load_project_env()
logger = setup_logging()


def due_post_ids(store, seen_ids, *, now=None, limit=8):
    """Older posts can leave the first pages before their 24h observation."""
    from evidence_metrics import WINDOWS, observation, parse_time
    now = now or datetime.now(timezone.utc)
    due=[]
    for post in (store.get('posts') or {}).values():
        post_id=str(post.get('post_id') or '')
        published=parse_time(post.get('published_at'))
        if not post_id.isdigit() or post_id in seen_ids or not published or not post.get('tracked_from_publish'):
            continue
        age=(now-published).total_seconds()/60
        for label,(low,high) in WINDOWS.items():
            if low<=age<=high and observation(post,label) is None:
                due.append((high-age,post_id))
                break
    return [pid for _,pid in sorted(due)[:limit]]


def refresh(pages: int) -> int:
    uid = str(os.getenv("SQUARE_PROFILE_UID", "")).strip()
    if not uid:
        logger.warning("SQUARE_PROFILE_UID is empty; public analytics refresh skipped")
        return 0
    try:
        client = BinanceSquarePublicClient()
        rows = client.recent_posts(uid, pages=pages)
        for post_id in due_post_ids(load_store(), {row.post_id for row in rows}):
            try:
                detail = client.post_detail(post_id)
                if detail is not None:
                    rows.append(detail)
            except Exception as exc:
                logger.warning("Due post metric unavailable: %s (%s)", post_id, type(exc).__name__)
        result = merge_public_stats(rows, profile_uid=uid)
        logger.info(
            "Square analytics refreshed: %s public posts merged, %s total stored",
            result.get("merged", 0), result.get("posts", 0),
        )
        return 0
    except Exception as exc:
        logger.warning("Square analytics refresh failed (non-fatal): %s", exc)
        return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pages", type=int, default=int(os.getenv("STATS_REFRESH_PAGES", "4")))
    parser.add_argument("--build-dashboard", action="store_true")
    args = parser.parse_args()
    refresh(args.pages)
    if args.build_dashboard:
        from dashboard_builder import build_dashboard_data
        output = build_dashboard_data()
        logger.info("Dashboard data written to %s", output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
