"""Reach recovery gate for v11.4.4.

The scanner still runs on every cron tick. This gate only suppresses publication
when the winning candidate is too ordinary/weak for the current account reach
baseline. Fresh audience events remain free to break through.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RecoveryDecision:
    allowed: bool
    reason: str
    threshold: float


def evaluate_recovery_candidate(
    *,
    lane: str,
    writer_source: str,
    event_class: str,
    micro_phase: str,
    opportunity_score: float,
    audience_demand: float,
    attention_score: float,
    micro_score: float,
    monetization_score: float,
    selection_score: float,
    reach_score: float,
    plan_valid: bool,
) -> RecoveryDecision:
    lane_name = str(lane or "").strip().lower()
    source = str(writer_source or "").strip().lower()
    event = str(event_class or "ordinary").strip().lower()
    phase = str(micro_phase or "ordinary").strip().lower()

    opportunity = float(opportunity_score)
    demand = float(audience_demand)
    attention = float(attention_score)
    micro = float(micro_score)
    monetization = float(monetization_score)
    selection = float(selection_score)
    reach = float(reach_score)
    activity = max(attention, micro)

    strong_event = event in {"fresh_event", "audience_breakout"}
    high_demand = event == "high_demand_active"
    active_market = event == "active_market"
    deterministic = source.startswith("deterministic")

    # Truly stale candidates should almost never consume a publication slot.
    # A very high-demand/high-attention exception keeps this a soft guard instead
    # of a permanent ban on large coins during an unusual move.
    if phase == "stale" or event == "stale_event":
        stale_escape = (
            demand >= 82.0
            and attention >= 72.0
            and opportunity >= 68.0
            and selection >= 72.0
            and reach >= 78.0
        )
        if not stale_escape:
            return RecoveryDecision(False, "stale market without exceptional demand", 78.0)

    if strong_event:
        threshold = 68.0
        min_selection = 60.0
        min_opportunity = 57.0
        min_demand = 18.0
    elif high_demand:
        threshold = 70.0
        min_selection = 65.0
        min_opportunity = 60.0
        min_demand = 65.0
    elif active_market:
        threshold = 72.0
        min_selection = 68.0
        min_opportunity = 63.0
        min_demand = 45.0
    elif lane_name == "event":
        threshold = 74.0
        min_selection = 70.0
        min_opportunity = 66.0
        min_demand = 55.0
    else:
        threshold = 74.0
        min_selection = 70.0
        min_opportunity = 67.0
        min_demand = 48.0

    # Observation-only EVENT posts need a little more evidence because they have
    # lower trading intent and historically weaker reach when the market is ordinary.
    if lane_name == "event" and not plan_valid and not strong_event:
        threshold += 1.5
        min_selection += 1.5

    # Deterministic copy is an outage fallback, not a co-equal author. Historical
    # account data shows a large reach gap, so only publish it on stronger markets.
    if deterministic:
        threshold += 4.0
        min_selection += 4.0
        min_opportunity += 2.0
        min_demand += 3.0

    # A healthy W2E/actionable plan can earn a tiny concession, but never enough
    # to rescue a genuinely weak market candidate.
    if plan_valid and monetization >= 58.0 and not deterministic:
        threshold -= 1.0

    threshold = max(66.0, min(82.0, threshold))

    reasons = []
    if reach < threshold:
        reasons.append(f"reach {reach:.1f} < {threshold:.1f}")
    if selection < min_selection:
        reasons.append(f"selection {selection:.1f} < {min_selection:.1f}")
    if opportunity < min_opportunity:
        reasons.append(f"opportunity {opportunity:.1f} < {min_opportunity:.1f}")
    if demand < min_demand:
        reasons.append(f"demand {demand:.1f} < {min_demand:.1f}")

    # Ordinary posts also need some live activity. Strong-event classes already
    # encode that evidence and are intentionally exempt from this extra condition.
    if not strong_event and not high_demand and activity < 50.0:
        reasons.append(f"activity {activity:.1f} < 50.0")

    if reasons:
        return RecoveryDecision(False, "; ".join(reasons), threshold)
    return RecoveryDecision(True, f"recovery quality passed ({reach:.1f} >= {threshold:.1f})", threshold)
