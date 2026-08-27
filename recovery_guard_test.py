"""Focused regression checks for v11.4.5 recovery selection."""
from recovery_guard import evaluate_recovery_candidate


def decision(**overrides):
    payload = {
        "lane": "trade",
        "writer_source": "mistral",
        "event_class": "ordinary",
        "micro_phase": "ordinary",
        "opportunity_score": 72.0,
        "audience_demand": 60.0,
        "attention_score": 65.0,
        "micro_score": 58.0,
        "monetization_score": 60.0,
        "selection_score": 75.0,
        "reach_score": 76.0,
        "plan_valid": True,
    }
    payload.update(overrides)
    return evaluate_recovery_candidate(**payload)


# Healthy ordinary AI trade remains publishable.
assert decision().allowed

# Fresh/audience breakout events keep a low-friction escape hatch.
assert decision(
    lane="event",
    writer_source="mistral_event",
    event_class="audience_breakout",
    opportunity_score=64.0,
    audience_demand=62.0,
    attention_score=58.0,
    micro_score=74.0,
    monetization_score=55.0,
    selection_score=70.0,
    reach_score=72.0,
).allowed

# Real high-demand live event should pass.
assert decision(
    lane="event",
    writer_source="mistral_event",
    event_class="high_demand_active",
    micro_phase="developing",
    opportunity_score=68.1,
    audience_demand=75.9,
    attention_score=59.3,
    micro_score=69.3,
    monetization_score=63.2,
    selection_score=71.2,
    reach_score=77.0,
    plan_valid=False,
).allowed

# v11.4.5 regression: a live high-demand AI event must not be killed merely
# because selection/reach miss the old ordinary-event thresholds by a few points.
assert decision(
    lane="event",
    writer_source="mistral_event",
    event_class="ordinary",
    micro_phase="developing",
    opportunity_score=66.0,
    audience_demand=80.2,
    attention_score=44.5,
    micro_score=60.2,
    monetization_score=56.8,
    selection_score=66.7,
    reach_score=74.9,
    plan_valid=False,
).allowed

# Weak ordinary high-volume/event cycle remains blocked even when its copy/reach
# score is superficially decent.
assert not decision(
    lane="event",
    writer_source="mistral_event",
    event_class="ordinary",
    micro_phase="fresh",
    opportunity_score=60.4,
    audience_demand=63.8,
    attention_score=46.5,
    micro_score=78.1,
    monetization_score=52.7,
    selection_score=55.1,
    reach_score=74.2,
    plan_valid=False,
).allowed

# Weak ordinary trade should not pass merely because volume inflates reach.
assert not decision(
    event_class="ordinary",
    opportunity_score=64.0,
    audience_demand=45.0,
    attention_score=55.0,
    micro_score=65.0,
    monetization_score=52.0,
    selection_score=66.0,
    reach_score=78.0,
).allowed

# Deterministic copy needs a clearly stronger market than AI copy.
assert not decision(
    lane="event",
    writer_source="deterministic_event",
    event_class="high_demand_active",
    opportunity_score=65.0,
    audience_demand=72.0,
    attention_score=55.0,
    micro_score=60.0,
    monetization_score=53.0,
    selection_score=69.0,
    reach_score=72.0,
    plan_valid=False,
).allowed

# Stale markets are skipped unless the demand/attention exception is genuinely strong.
assert not decision(
    micro_phase="stale",
    event_class="stale_event",
    opportunity_score=70.0,
    audience_demand=75.0,
    attention_score=70.0,
    micro_score=10.0,
    selection_score=75.0,
    reach_score=80.0,
).allowed

assert decision(
    lane="event",
    writer_source="mistral_event",
    micro_phase="stale",
    event_class="stale_event",
    opportunity_score=72.0,
    audience_demand=86.0,
    attention_score=78.0,
    micro_score=20.0,
    monetization_score=62.0,
    selection_score=76.0,
    reach_score=81.0,
    plan_valid=False,
).allowed

print("recovery guard checks passed")
