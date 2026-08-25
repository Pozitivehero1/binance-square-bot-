"""Add version-isolated reach/outcome metrics to dashboard JSON snapshots.

This runs after collect_stats/build_dashboard so new engine versions can be judged
without mixing them with the full historical account sample.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path
from statistics import median

from performance_store import load_store
from trade_journal import load_journal
from runtime import PROJECT_DIR, atomic_write_json


DASHBOARD_DIR = PROJECT_DIR / "dashboard"


def _parse(value: str):
    try:
        dt = datetime.fromisoformat(str(value or ""))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except (TypeError, ValueError):
        return None


def _views(post: dict) -> int:
    stats = post.get("stats") if isinstance(post.get("stats"), dict) else {}
    try:
        return int(stats.get("views", 0) or 0)
    except (TypeError, ValueError):
        return 0


def _reach_groups(now: datetime) -> dict:
    store = load_store()
    grouped: dict[str, list[dict]] = {}
    for post in (store.get("posts") or {}).values():
        if not isinstance(post, dict) or not post.get("learning_eligible", True):
            continue
        version = str(post.get("engine_version") or "").strip()
        if not version:
            continue
        grouped.setdefault(version, []).append(post)

    result = {}
    for version, rows in sorted(grouped.items()):
        last_24h = []
        mature = []
        for post in rows:
            published = _parse(post.get("published_at", ""))
            if not published:
                continue
            age_h = max(0.0, (now - published).total_seconds() / 3600.0)
            if age_h <= 24.0:
                last_24h.append(post)
            if age_h >= 6.0:
                mature.append(_views(post))
        writers = Counter(str(row.get("writer_source") or "UNKNOWN") for row in rows)
        values = [_views(row) for row in rows]
        result[version] = {
            "posts_total": len(rows),
            "posts_24h": len(last_24h),
            "views_on_24h_posts": sum(_views(row) for row in last_24h),
            "mature_6h_posts": len(mature),
            "median_views_6h_plus": round(float(median(mature)), 1) if mature else 0.0,
            "posts_300_plus": sum(1 for value in values if value >= 300),
            "posts_500_plus": sum(1 for value in values if value >= 500),
            "posts_1000_plus": sum(1 for value in values if value >= 1000),
            "writers": dict(writers.most_common()),
        }
    return result


def _outcome_groups() -> dict:
    journal = load_journal()
    grouped: dict[str, list[dict]] = {}
    for trade in (journal.get("trades") or {}).values():
        if not isinstance(trade, dict):
            continue
        version = str(trade.get("engine_version") or "").strip()
        if not version:
            continue
        grouped.setdefault(version, []).append(trade)

    result = {}
    for version, rows in sorted(grouped.items()):
        entered = [row for row in rows if row.get("entry_confirmed")]
        closed = [row for row in rows if row.get("status") in {"closed", "expired", "manual_review"}]
        tp1 = sum(1 for row in entered if (row.get("hits") or {}).get("tp1"))
        tp3 = sum(1 for row in entered if (row.get("hits") or {}).get("tp3"))
        stops = sum(1 for row in entered if (row.get("hits") or {}).get("stop"))
        completed = sum(1 for row in rows if row.get("close_reason") == "public_targets_complete")
        result[version] = {
            "setups": len(rows),
            "entered": len(entered),
            "active": sum(1 for row in rows if row.get("status") in {"active", "pending_entry"}),
            "closed": len(closed),
            "tp1_hits": tp1,
            "tp3_hits": tp3,
            "stops": stops,
            "target_complete": completed,
            "tp1_rate": round(tp1 / len(entered) * 100.0, 1) if entered else 0.0,
            "tp3_rate": round(tp3 / len(entered) * 100.0, 1) if entered else 0.0,
        }
    return result


def _code_version() -> str:
    path = PROJECT_DIR / "VERSION.txt"
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def enrich(path: Path) -> None:
    if not path.exists():
        return
    payload = json.loads(path.read_text(encoding="utf-8"))
    now = datetime.now(timezone.utc)
    payload["version_metrics"] = {
        "generated_at": now.isoformat(),
        "code_version": _code_version(),
        "reach": _reach_groups(now),
        "outcomes": _outcome_groups(),
        "note": "Version-isolated metrics use engine_version stamped on newly published posts/setups; older unversioned history is intentionally excluded.",
    }
    atomic_write_json(path, payload)


def main() -> int:
    enrich(DASHBOARD_DIR / "data.json")
    enrich(DASHBOARD_DIR / "summary.json")
    print("dashboard version metrics enriched")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
