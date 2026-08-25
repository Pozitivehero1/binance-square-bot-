"""v11.4.3 Language + Reach Guard production hotfix.

Closes mixed RU/EN prompt leakage, prefers a larger pool of valid AI drafts before
falling back to deterministic copy, and stamps new records with v11.4.3.
Trading geometry and outcome publication rules remain untouched.
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
        print(f"[v11.4.3 hotfix] warning: {label}: expected one source match, found {count}; skipped")
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
        "from semantic_quality import semantic_quality_reasons\n",
        "from semantic_quality import semantic_quality_reasons\nfrom language_quality import language_quality_reasons\n",
        label="trade language-quality import",
    )
    changed |= _replace_optional(
        path,
        '            "Не обещай исход и время достижения цели: запрещены фразы вроде без потерь, дело времени, через час будет цель, вперёд к целям. Не используй прямые команды покупать/продавать. Проверь текст на явные опечатки перед ответом.",\n',
        '            "Не обещай исход и время достижения цели: запрещены фразы вроде без потерь, дело времени, через час будет цель, вперёд к целям. Не используй прямые команды покупать/продавать. Проверь текст на явные опечатки перед ответом.",\n            "Основной язык — русский. Английские рыночные термины LONG/SHORT/VWAP/TP допустимы, но не смешивай служебные английские связки с русским текстом: никаких in тогда, or рынок, and потом, a второй и подобных конструкций.",\n',
        label="trade Russian-language prompt",
    )
    changed |= _replace_optional(
        path,
        '''    semantic = semantic_quality_reasons(text)
    if semantic:
        reasons.append("semantic quality: " + ",".join(semantic))
    lowered = text.lower().replace("ё", "е")
''',
        '''    semantic = semantic_quality_reasons(text)
    if semantic:
        reasons.append("semantic quality: " + ",".join(semantic))
    language = language_quality_reasons(text)
    if language:
        reasons.append("language quality: " + ",".join(language))
    lowered = text.lower().replace("ё", "е")
''',
        label="trade language validator",
    )
    changed |= _replace_optional(
        path,
        '            if len(drafts) >= min(3, len(ai_formats)):\n                break\n',
        '            required_ai_drafts = min(max(3, int(os.getenv("MIN_VALID_AI_DRAFTS", "4"))), len(ai_formats))\n            if len(drafts) >= required_ai_drafts:\n                break\n',
        label="trade valid AI pool target",
    )
    changed |= _replace_optional(
        path,
        '''    ai_count = sum(1 for draft in drafts if draft.source in {"mistral", "deepseek"})
    compare_slots = max(0, min(int(os.getenv("DETERMINISTIC_COMPARE_SLOTS", "2")), 4))
    deterministic_target = target_count if ai_count == 0 else min(target_count, len(drafts) + compare_slots)
''',
        '''    ai_count = sum(1 for draft in drafts if draft.source in {"mistral", "deepseek"})
    compare_slots = max(0, min(int(os.getenv("DETERMINISTIC_COMPARE_SLOTS", "2")), 4))
    healthy_ai_pool = ai_count >= max(2, int(os.getenv("MIN_VALID_AI_DRAFTS", "4")))
    deterministic_target = target_count if not healthy_ai_pool else min(target_count, len(drafts) + compare_slots)
''',
        label="trade degraded-AI fallback pool",
    )
    return changed


def _patch_event_writer() -> bool:
    path = PROJECT_DIR / "event_writer.py"
    changed = False
    changed |= _replace_optional(
        path,
        "from semantic_quality import semantic_quality_reasons\n",
        "from semantic_quality import semantic_quality_reasons\nfrom language_quality import language_quality_reasons\n",
        label="event language-quality import",
    )
    changed |= _replace_optional(
        path,
        '            "Не обещай исход и время достижения цели: запрещены фразы вроде без потерь, дело времени, через час будет цель, вперёд к целям. Не используй прямые команды покупать/продавать. Проверь текст на явные опечатки перед ответом.",\n',
        '            "Не обещай исход и время достижения цели: запрещены фразы вроде без потерь, дело времени, через час будет цель, вперёд к целям. Не используй прямые команды покупать/продавать. Проверь текст на явные опечатки перед ответом.",\n            "Основной язык — русский. Английские рыночные термины LONG/SHORT/VWAP/TP допустимы, но не смешивай служебные английские связки с русским текстом: никаких in тогда, or рынок, and потом, a второй и подобных конструкций.",\n',
        label="event Russian-language prompt",
    )
    changed |= _replace_optional(
        path,
        '''    semantic = semantic_quality_reasons(text)
    if semantic:
        reasons.append("semantic quality: " + ",".join(semantic))
    lowered = text.lower().replace("ё", "е")
''',
        '''    semantic = semantic_quality_reasons(text)
    if semantic:
        reasons.append("semantic quality: " + ",".join(semantic))
    language = language_quality_reasons(text)
    if language:
        reasons.append("language quality: " + ",".join(language))
    lowered = text.lower().replace("ё", "е")
''',
        label="event language validator",
    )
    changed |= _replace_optional(
        path,
        '            if len(drafts) >= min(3, len(ai_formats)):\n                break\n',
        '            required_ai_drafts = min(max(3, int(os.getenv("EVENT_MIN_VALID_AI_DRAFTS", "4"))), len(ai_formats))\n            if len(drafts) >= required_ai_drafts:\n                break\n',
        label="event valid AI pool target",
    )
    changed |= _replace_optional(
        path,
        '''    ai_count = sum(1 for draft in drafts if draft.source in {"mistral_event", "deepseek_event"})
    compare_slots = max(0, min(int(os.getenv("EVENT_DETERMINISTIC_COMPARE_SLOTS", "2")), 4))
    deterministic_target = event_target_count if ai_count == 0 else min(event_target_count, len(drafts) + compare_slots)
''',
        '''    ai_count = sum(1 for draft in drafts if draft.source in {"mistral_event", "deepseek_event"})
    compare_slots = max(0, min(int(os.getenv("EVENT_DETERMINISTIC_COMPARE_SLOTS", "2")), 4))
    healthy_ai_pool = ai_count >= max(2, int(os.getenv("EVENT_MIN_VALID_AI_DRAFTS", "4")))
    deterministic_target = event_target_count if not healthy_ai_pool else min(event_target_count, len(drafts) + compare_slots)
''',
        label="event degraded-AI fallback pool",
    )
    return changed


def _patch_publisher() -> bool:
    path = PROJECT_DIR / "publisher.py"
    changed = False
    changed |= _replace_optional(
        path,
        "from semantic_quality import semantic_quality_reasons\n",
        "from semantic_quality import semantic_quality_reasons\nfrom language_quality import language_quality_reasons\n",
        label="publisher language-quality import",
    )
    changed |= _replace_optional(
        path,
        "    reasons = tuple(dict.fromkeys((*artifact_reasons(normalized), *semantic_quality_reasons(normalized))))\n",
        "    reasons = tuple(dict.fromkeys((*artifact_reasons(normalized), *semantic_quality_reasons(normalized), *language_quality_reasons(normalized))))\n",
        label="publisher final language gate",
    )
    return changed


def apply_v1143_hotfix() -> None:
    os.environ["BOT_VERSION"] = "v11.4.3"
    os.environ["MIN_VALID_AI_DRAFTS"] = "4"
    os.environ["EVENT_MIN_VALID_AI_DRAFTS"] = "4"

    changed = _patch_writer() | _patch_event_writer() | _patch_publisher()
    if changed:
        print("[v11.4.3 hotfix] Language + Reach Guard applied: RU/EN leak rejection + stronger AI retry pool")
    else:
        print("[v11.4.3 hotfix] Language + Reach Guard already applied or no compatible source changes found")


if __name__ == "__main__":
    apply_v1143_hotfix()
