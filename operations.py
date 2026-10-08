"""Run telemetry and publication watch: a green workflow is not a posted article."""
from __future__ import annotations
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path

from runtime import atomic_write_json, resolve_state_file, write_status

LOG = logging.getLogger(__name__)
TELEMETRY_FILE = "run_telemetry.json"


def _load(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def _date(raw):
    try:
        value = datetime.fromisoformat(str(raw or "").replace("Z", "+00:00"))
        return (value if value.tzinfo else value.replace(tzinfo=timezone.utc)).astimezone(timezone.utc)
    except (ValueError, TypeError):
        return None


def last_publication_at():
    latest = []
    receipt = _load(resolve_state_file("PUBLICATION_STATE_FILE", "publication_state.json"))
    for row in receipt.get("publications", []):
        if isinstance(row, dict) and (d := _date(row.get("ts"))):
            latest.append(d)
    history = _load(resolve_state_file("PUBLISHED_HISTORY_FILE", "published_history.json"))
    for timestamp in history.values():
        if d := _date(timestamp):
            latest.append(d)
    return max(latest) if latest else None


def summarize(*, outcome: dict, last_post=None, now=None) -> dict:
    now = now or datetime.now(timezone.utc)
    recent = last_post or last_publication_at()
    age_hours = round((now - recent).total_seconds() / 3600, 2) if recent else None
    threshold = max(2.0, float(os.getenv("NO_POST_ALERT_HOURS", "6")))
    kind = str(outcome.get("status") or "unknown")
    return {
        "status": kind,
        "detail": str(outcome.get("detail") or ""),
        "post_id": str(outcome.get("post_id") or ""),
        "last_published_at": recent.isoformat() if recent else None,
        "hours_without_post": age_hours,
        "no_post_alert": bool(age_hours is not None and age_hours >= threshold),
    }


def record_run(started_at: datetime, exit_code: int) -> dict:
    now = datetime.now(timezone.utc)
    outcome = _load(resolve_state_file("BOT_STATUS_FILE", "status.json"))
    updated = _date(outcome.get("updated_at"))
    if updated is None or updated < started_at:
        outcome = {"status": "failed" if exit_code else "unknown", "detail": "no status produced this run"}
    if exit_code and outcome.get("status") not in {"failed"}:
        outcome = {"status": "failed", "detail": "bot returned nonzero exit status"}
    summary = summarize(outcome=outcome, now=now)
    summary.update(started_at=started_at.isoformat(), completed_at=now.isoformat(),
                   exit_code=int(exit_code))
    path = resolve_state_file("RUN_TELEMETRY_FILE", TELEMETRY_FILE)
    previous = _load(path)
    rows = previous.get("runs") if isinstance(previous.get("runs"), list) else []
    rows = [row for row in rows if isinstance(row, dict)][-119:] + [summary]
    atomic_write_json(path, {"runs": rows, "last": summary})
    LOG.info("RUN OUTCOME status=%s code=%s confirmed_post_id=%s no_post_hours=%s",
             summary["status"], exit_code, bool(summary["post_id"]),
             summary["hours_without_post"])
    return summary


def run_entrypoint(fn) -> int:
    started_at = datetime.now(timezone.utc)
    code = 1
    try:
        code = int(fn())
    except Exception as exc:
        LOG.exception("Bot run aborted: %s", type(exc).__name__)
        write_status("failed", "uncaught runtime error", error_type=type(exc).__name__)
    finally:
        try:
            record_run(started_at, code)
        except Exception:
            LOG.exception("Could not persist run telemetry")
    return code


def report() -> int:
    data = _load(resolve_state_file("RUN_TELEMETRY_FILE", TELEMETRY_FILE))
    outcome = data.get("last") if isinstance(data.get("last"), dict) else {}
    if not outcome:
        outcome = summarize(outcome=_load(resolve_state_file("BOT_STATUS_FILE", "status.json")))
    kind, detail = outcome.get("status", "unknown"), outcome.get("detail", "")
    print(f"Publication result: {kind} | {detail}")
    print(f"Confirmed post ID: {outcome.get('post_id') or 'none'}")
    print(f"Hours without confirmed publication: {outcome.get('hours_without_post')}")
    if outcome.get("no_post_alert"):
        print("::warning::No confirmed Square publication for the configured alert period")
    output = os.getenv("GITHUB_STEP_SUMMARY", "").strip()
    if output:
        with open(output, "a", encoding="utf-8") as handle:
            handle.write(
                "\n### Publication health\n\n"
                f"- Outcome: **{kind}** — {detail}\n"
                f"- Confirmed post: {outcome.get('post_id') or 'none'}\n"
                f"- Last successful publication: {outcome.get('last_published_at') or 'unknown'}\n"
                f"- Hours without a post: {outcome.get('hours_without_post')}\n"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(report())
