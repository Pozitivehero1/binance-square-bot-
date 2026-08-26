"""v11.4.4 Recovery Selection production hotfix.

Fixes the v11.4.3 fallback regression, suppresses weak ordinary/stale cycles,
falls back from capacity-starved DeepSeek faster, and keeps the existing
v11.3 trading/outcome contract unchanged.
"""
from __future__ import annotations

import os
from pathlib import Path

from runtime import PROJECT_DIR


def _replace_optional(path: Path, old: str, new: str, *, label: str) -> bool:
    text = path.read_text(encoding="utf-8")
    if new in text:
        return False
    count = text.count(old)
    if count != 1:
        print(f"[v11.4.4 hotfix] warning: {label}: expected one source match, found {count}; skipped")
        return False
    updated = text.replace(old, new, 1)
    compile(updated, str(path), "exec")
    path.write_text(updated, encoding="utf-8")
    return True


def _patch_writer() -> bool:
    path = PROJECT_DIR / "writer.py"
    changed = False

    changed |= _replace_optional(
        path,
        '            required_ai_drafts = min(max(3, int(os.getenv("MIN_VALID_AI_DRAFTS", "4"))), len(ai_formats))\n',
        '            required_ai_drafts = min(max(2, int(os.getenv("MIN_VALID_AI_DRAFTS", "2"))), len(ai_formats))\n',
        label="trade AI pool target",
    )

    changed |= _replace_optional(
        path,
        '''    ai_count = sum(1 for draft in drafts if draft.source in {"mistral", "deepseek"})
    compare_slots = max(0, min(int(os.getenv("DETERMINISTIC_COMPARE_SLOTS", "2")), 4))
    healthy_ai_pool = ai_count >= max(2, int(os.getenv("MIN_VALID_AI_DRAFTS", "4")))
    deterministic_target = target_count if not healthy_ai_pool else min(target_count, len(drafts) + compare_slots)
''',
        '''    ai_count = sum(1 for draft in drafts if draft.source in {"mistral", "deepseek"})
    if ai_count >= 2:
        # Two independently validated AI drafts are enough to choose between them.
        # Do not let lower-performing deterministic copy re-enter the race.
        deterministic_target = len(drafts)
    elif ai_count == 1:
        # One valid AI draft gets one fact-perfect comparator, not a full fallback pool.
        deterministic_target = min(target_count, len(drafts) + 1)
    else:
        deterministic_target = target_count
''',
        label="trade deterministic fallback recovery",
    )

    changed |= _replace_optional(
        path,
        '            "Не обещай исход и время достижения цели: запрещены фразы вроде без потерь, дело времени, через час будет цель, вперёд к целям. Не используй прямые команды покупать/продавать. Проверь текст на явные опечатки перед ответом.",\n',
        '            "Не обещай исход и время достижения цели: запрещены фразы вроде без потерь, дело времени, через час будет цель, менее чем за полчаса, в первые часы, вперёд к целям и действовать быстро или пропустить. Не используй прямые команды покупать/продавать. Проверь текст на явные опечатки перед ответом.",\n',
        label="trade timing-promise prompt",
    )
    return changed


def _patch_event_writer() -> bool:
    path = PROJECT_DIR / "event_writer.py"
    changed = False

    changed |= _replace_optional(
        path,
        '            required_ai_drafts = min(max(3, int(os.getenv("EVENT_MIN_VALID_AI_DRAFTS", "4"))), len(ai_formats))\n',
        '            required_ai_drafts = min(max(2, int(os.getenv("EVENT_MIN_VALID_AI_DRAFTS", "2"))), len(ai_formats))\n',
        label="event AI pool target",
    )

    changed |= _replace_optional(
        path,
        '''    ai_count = sum(1 for draft in drafts if draft.source in {"mistral_event", "deepseek_event"})
    compare_slots = max(0, min(int(os.getenv("EVENT_DETERMINISTIC_COMPARE_SLOTS", "2")), 4))
    healthy_ai_pool = ai_count >= max(2, int(os.getenv("EVENT_MIN_VALID_AI_DRAFTS", "4")))
    deterministic_target = event_target_count if not healthy_ai_pool else min(event_target_count, len(drafts) + compare_slots)
''',
        '''    ai_count = sum(1 for draft in drafts if draft.source in {"mistral_event", "deepseek_event"})
    if ai_count >= 2:
        deterministic_target = len(drafts)
    elif ai_count == 1:
        deterministic_target = min(event_target_count, len(drafts) + 1)
    else:
        deterministic_target = event_target_count
''',
        label="event deterministic fallback recovery",
    )

    changed |= _replace_optional(
        path,
        '            "Не обещай исход и время достижения цели: запрещены фразы вроде без потерь, дело времени, через час будет цель, вперёд к целям. Не используй прямые команды покупать/продавать. Проверь текст на явные опечатки перед ответом.",\n',
        '            "Не обещай исход и время достижения цели: запрещены фразы вроде без потерь, дело времени, через час будет цель, менее чем за полчаса, в первые часы, вперёд к целям и действовать быстро или пропустить. Не используй прямые команды покупать/продавать. Проверь текст на явные опечатки перед ответом.",\n',
        label="event timing-promise prompt",
    )
    return changed


def _patch_main() -> bool:
    path = PROJECT_DIR / "main.py"
    changed = False
    changed |= _replace_optional(
        path,
        "from outcome_engine import process_outcomes\n",
        "from outcome_engine import process_outcomes\nfrom recovery_guard import evaluate_recovery_candidate\n",
        label="recovery guard import",
    )

    old = '''    logger.info("Distribution gate: %s", reach.reason)
    if not DRY_RUN and not reach.allowed:
        write_status(
            "skipped",
            reach.reason,
            symbol=symbol,
            lane=lane,
            reach_score=reach.score,
            market_score=opportunity.score,
            quality_score=quality_report.score,
        )
        return 0

    card_path: Optional[str] = None
'''
    new = '''    logger.info("Distribution gate: %s", reach.reason)
    if not DRY_RUN and not reach.allowed:
        write_status(
            "skipped",
            reach.reason,
            symbol=symbol,
            lane=lane,
            reach_score=reach.score,
            market_score=opportunity.score,
            quality_score=quality_report.score,
        )
        return 0

    recovery = evaluate_recovery_candidate(
        lane=lane,
        writer_source=selected_post.source,
        event_class=opportunity.event_class,
        micro_phase=micro.phase,
        opportunity_score=opportunity.score,
        audience_demand=opportunity.audience_demand,
        attention_score=attention.score,
        micro_score=micro.score,
        monetization_score=monetization.score,
        selection_score=selection_score,
        reach_score=float(reach.score or 0.0),
        plan_valid=plan_valid,
    )
    logger.info("Recovery gate: %s", recovery.reason)
    if not DRY_RUN and not recovery.allowed:
        write_status(
            "skipped",
            "v11.4.4 recovery gate: " + recovery.reason,
            symbol=symbol,
            lane=lane,
            writer_source=selected_post.source,
            event_class=opportunity.event_class,
            reach_score=reach.score,
            recovery_threshold=recovery.threshold,
            selection_score=selection_score,
            opportunity_score=opportunity.score,
            audience_demand=opportunity.audience_demand,
        )
        return 0

    card_path: Optional[str] = None
'''
    changed |= _replace_optional(path, old, new, label="post-selection recovery gate")
    return changed


def _patch_ai_provider() -> bool:
    path = PROJECT_DIR / "ai_provider.py"
    old = '''        retryable = status in {408, 409, 425, 429, 500, 502, 503, 504}
        if retryable and response is not None:
'''
    new = '''        retryable = status in {408, 409, 425, 429, 500, 502, 503, 504}
        # OrcaRouter uses HTTP 503 model_not_found when the free DeepSeek pool has
        # no capacity. Retrying the same unavailable model only burns freshness;
        # fall through to Mistral immediately while keeping retries for real
        # transient 429/5xx/network errors.
        if status == 503 and re.search(r"(?:model_not_found|no available capacity)", body, flags=re.IGNORECASE):
            retryable = False
        if retryable and response is not None:
'''
    return _replace_optional(path, old, new, label="DeepSeek no-capacity fast fallback")


def apply_v1144_hotfix() -> None:
    os.environ["BOT_VERSION"] = "v11.4.4"
    os.environ["MIN_VALID_AI_DRAFTS"] = "2"
    os.environ["EVENT_MIN_VALID_AI_DRAFTS"] = "2"
    os.environ["DETERMINISTIC_COMPARE_SLOTS"] = "0"
    os.environ["EVENT_DETERMINISTIC_COMPARE_SLOTS"] = "0"
    os.environ["AI_TEMPERATURE"] = "0.70"
    os.environ["EVENT_AI_TEMPERATURE"] = "0.70"

    changed = _patch_writer() | _patch_event_writer() | _patch_main() | _patch_ai_provider()
    if changed:
        print("[v11.4.4 hotfix] Recovery Selection applied: AI-first fallback fix + weak-cycle guard + fast capacity fallback")
    else:
        print("[v11.4.4 hotfix] Recovery Selection already applied or no compatible source changes found")


if __name__ == "__main__":
    apply_v1144_hotfix()
