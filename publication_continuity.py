"""A quality-gated outage probe prevents recovery from requiring its own exit."""
from __future__ import annotations

from datetime import datetime, timezone


def allow_outage_probe(*, now=None, **candidate) -> bool:
    from performance_store import load_store

    # Normal selection, factual, repetition and base recovery gates must ALSO
    # pass. Silence alone cannot make weak/ordinary copy publishable.
    if not str(candidate.get("writer_source", "")).startswith("deterministic"):
        return False
    if candidate.get("event_class") not in {"fresh_event", "audience_breakout", "high_demand_active"}:
        return False
    if candidate.get("micro_phase") not in {"fresh", "developing"}:
        return False
    floors = {"reach_score": 75, "selection_score": 70, "opportunity_score": 65,
              "audience_demand": 60, "monetization_score": 50}
    if any(float(candidate.get(name, 0) or 0) < floor for name, floor in floors.items()):
        return False
    if max(float(candidate.get("attention_score", 0)), float(candidate.get("micro_score", 0))) < 58:
        return False
    now = now or datetime.now(timezone.utc)
    dates = []
    for row in load_store().get("posts", {}).values():
        try:
            dt = datetime.fromisoformat(str(row.get("published_at", "")).replace("Z", "+00:00"))
            dates.append(dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt)
        except (TypeError, ValueError, AttributeError):
            continue
    # Missing publication history is not evidence of a quiet account.
    return bool(dates) and (now - max(dates)).total_seconds() >= 120 * 60
