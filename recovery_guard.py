"""Quality-first reach recovery gate for v11.5.

The scanner runs on every cron tick. The guard blocks stale/ordinary filler, but
must not suppress a genuinely useful live candidate merely because one learned
reach component is a few points below a historical threshold.
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
    recovery_mode: bool = False,
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

    # Stale data is a hard quality problem, not something a high copy score can
    # hide. Keep only a genuinely exceptional high-demand/high-attention escape.
    if phase == "stale" or event == "stale_event":
        stale_escape = (
            demand >= 82.0
            and attention >= 72.0
            and opportunity >= 68.0
            and selection >= 72.0
            and reach >= 78.0
            and not deterministic
        )
        if not stale_escape:
            return RecoveryDecision(False, "stale market without exceptional demand", 78.0)

    # There is deliberately no cadence escape in v11.5. A cron tick is an
    # opportunity to publish, not an obligation to fill the slot.
    if not deterministic and not recovery_mode:
        broad_live_interest = (
            demand >= 75.0
            and opportunity >= 64.0
            and selection >= 64.0
            and monetization >= 50.0
            and activity >= 48.0
            and reach >= 71.0
        )
        actionable_live_plan = (
            plan_valid
            and demand >= 60.0
            and opportunity >= 64.0
            and selection >= 64.0
            and monetization >= 50.0
            and activity >= 48.0
            and reach >= 72.0
        )
        if broad_live_interest:
            return RecoveryDecision(
                True,
                f"live-interest recovery pass: reach={reach:.1f} selection={selection:.1f} opportunity={opportunity:.1f} demand={demand:.1f}",
                71.0,
            )
        if actionable_live_plan:
            return RecoveryDecision(
                True,
                f"actionable-plan recovery pass: reach={reach:.1f} selection={selection:.1f} opportunity={opportunity:.1f}",
                72.0,
            )

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

    # Observation-only ordinary events still need stronger evidence because they
    # have no actionable trade plan. Fresh/audience-breakout events are exempt.
    if lane_name == "event" and not plan_valid and not strong_event:
        threshold += 1.5
        min_selection += 1.5

    # Deterministic copy is an outage fallback, never a co-equal author.
    if deterministic:
        threshold += 4.0
        min_selection += 4.0
        min_opportunity += 2.0
        min_demand += 3.0

    if plan_valid and monetization >= 58.0 and not deterministic:
        threshold -= 1.0

    # While rolling reach is depressed, demand stronger evidence from every
    # ordinary candidate. Genuine fresh/breakout events keep a smaller uplift.
    if recovery_mode:
        uplift = 2.0 if strong_event else 4.0
        threshold += uplift
        min_selection += 3.0 if strong_event else 4.0
        min_opportunity += 2.0 if strong_event else 3.0
        if active_market and not strong_event:
            threshold += 1.0

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

    if not strong_event and not high_demand and activity < 50.0:
        reasons.append(f"activity {activity:.1f} < 50.0")

    if reasons:
        return RecoveryDecision(False, "; ".join(reasons), threshold)
    return RecoveryDecision(True, f"recovery quality passed ({reach:.1f} >= {threshold:.1f})", threshold)
