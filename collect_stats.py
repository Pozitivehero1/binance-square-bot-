"""Refresh public Square metrics and optionally build the static dashboard."""
from __future__ import annotations

import argparse
import logging
import os

from runtime import load_project_env, setup_logging
from performance_store import merge_public_stats
from square_public_stats import BinanceSquarePublicClient

load_project_env()
logger = setup_logging()


def refresh(pages: int) -> int:
    uid = str(os.getenv("SQUARE_PROFILE_UID", "")).strip()
    if not uid:
        logger.warning("SQUARE_PROFILE_UID is empty; public analytics refresh skipped")
        return 0
    try:
        rows = BinanceSquarePublicClient().recent_posts(uid, pages=pages)
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
