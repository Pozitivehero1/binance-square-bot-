"""v11.4.5 Production Guard hotfix.

Canonicalizes every public trade plan at the Python boundary, blocks malformed
plan duplication at publish time, rejects state/indicator contradictions, and
keeps all v11.3 outcome semantics intact.
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
        print(f"[v11.4.5 hotfix] warning: {label}: expected one source match, found {count}; skipped")
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
        "from semantic_quality import semantic_quality_reasons\nfrom production_guard import strip_embedded_trade_plan\nfrom fact_consistency import fact_consistency_reasons\n",
        label="production plan/fact guard imports",
    )

    old = '''def _enforce_full_plan_block(text: str, levels: Dict[str, Any], direction: str, *, seed: str = "") -> str:
    """Hard W2E/public-contract guard: every valid plan exposes entry, SL and TP1/2/3."""
    clean = re.sub(r"\\n{3,}", "\\n\\n", str(text or "").strip())
    if _full_plan_is_present(clean, levels, direction):
        return clean
    return _fit_narrative_with_plan(clean, _plan_block(levels, direction, seed or clean[:80]))
'''
    new = '''def _enforce_full_plan_block(text: str, levels: Dict[str, Any], direction: str, *, seed: str = "") -> str:
    """Make Python the single owner of the visible Entry/SL/TP ladder.

    AI prose may contain a correct-looking but duplicated or truncated plan. We
    therefore remove all embedded plan rows and append exactly one canonical
    Python block. This makes the final text contract independent of model
    formatting quirks.
    """
    clean = strip_embedded_trade_plan(text)
    clean = re.sub(r"\\n{3,}", "\\n\\n", clean.strip())
    block = _plan_block(levels, direction, seed or clean[:80])
    return _fit_narrative_with_plan(clean, block)
'''
    changed |= _replace_optional(path, old, new, label="canonical single public plan")

    changed |= _replace_optional(
        path,
        '''    language = language_quality_reasons(text)
    if language:
        reasons.append("language quality: " + ",".join(language))
    lowered = text.lower().replace("ё", "е")
''',
        '''    language = language_quality_reasons(text)
    if language:
        reasons.append("language quality: " + ",".join(language))
    fact_consistency = fact_consistency_reasons(text, package)
    if fact_consistency:
        reasons.append("fact consistency: " + ",".join(fact_consistency))
    lowered = text.lower().replace("ё", "е")
''',
        label="trade context fact validator",
    )

    changed |= _replace_optional(
        path,
        '            "Основной язык — русский. Английские рыночные термины LONG/SHORT/VWAP/TP допустимы, но не смешивай служебные английские связки с русским текстом: никаких in тогда, or рынок, and потом, a второй и подобных конструкций.",\n',
        '            "Основной язык — русский. Английские рыночные термины LONG/SHORT/VWAP/TP допустимы, но не смешивай служебные английские связки с русским текстом: никаких in тогда, or рынок, and потом, a второй и подобных конструкций.",\n            "Это новый публичный план, а не уже открытая позиция: нельзя писать, что сделка уже работает, вход уже исполнен или позиция уже в прибыли. Не придумывай исторические закономерности вроде часто предшествует/обычно приводит. ADX показывает силу, а не направление тренда; не переинтерпретируй RSI/ADX против переданных значений.",\n',
        label="trade state/fact prompt",
    )
    return changed


def _patch_event_writer() -> bool:
    path = PROJECT_DIR / "event_writer.py"
    changed = False
    changed |= _replace_optional(
        path,
        "from language_quality import language_quality_reasons\n",
        "from language_quality import language_quality_reasons\nfrom fact_consistency import fact_consistency_reasons\n",
        label="event fact guard import",
    )
    changed |= _replace_optional(
        path,
        '''    language = language_quality_reasons(text)
    if language:
        reasons.append("language quality: " + ",".join(language))
    lowered = text.lower().replace("ё", "е")
''',
        '''    language = language_quality_reasons(text)
    if language:
        reasons.append("language quality: " + ",".join(language))
    fact_consistency = fact_consistency_reasons(text, package)
    if fact_consistency:
        reasons.append("fact consistency: " + ",".join(fact_consistency))
    lowered = text.lower().replace("ё", "е")
''',
        label="event context fact validator",
    )
    changed |= _replace_optional(
        path,
        '            "Основной язык — русский. Английские рыночные термины LONG/SHORT/VWAP/TP допустимы, но не смешивай служебные английские связки с русским текстом: никаких in тогда, or рынок, and потом, a второй и подобных конструкций.",\n',
        '            "Основной язык — русский. Английские рыночные термины LONG/SHORT/VWAP/TP допустимы, но не смешивай служебные английские связки с русским текстом: никаких in тогда, or рынок, and потом, a второй и подобных конструкций.",\n            "Если в пакете есть торговый план, это всё ещё новый план, а не подтверждённая открытая позиция. Не утверждай, что сделка уже работает. Не придумывай статистические закономерности. ADX показывает силу, а не направление; RSI/ADX трактуй только согласованно с переданными значениями.",\n',
        label="event state/fact prompt",
    )
    return changed


def _patch_publisher() -> bool:
    path = PROJECT_DIR / "publisher.py"
    changed = False
    changed |= _replace_optional(
        path,
        "from semantic_quality import semantic_quality_reasons\n",
        "from semantic_quality import semantic_quality_reasons\nfrom production_guard import final_text_reasons\n",
        label="publisher production guard import",
    )
    # v11.4.3 adds language_quality_reasons before this hotfix runs, so the
    # structural guard must extend that full final-boundary tuple rather than the
    # older v11.4.2-only expression.
    changed |= _replace_optional(
        path,
        "    reasons = tuple(dict.fromkeys((*artifact_reasons(normalized), *semantic_quality_reasons(normalized), *language_quality_reasons(normalized))))\n",
        "    reasons = tuple(dict.fromkeys((*artifact_reasons(normalized), *semantic_quality_reasons(normalized), *language_quality_reasons(normalized), *final_text_reasons(normalized))))\n",
        label="publisher structural final gate",
    )
    return changed


def _patch_main() -> bool:
    path = PROJECT_DIR / "main.py"
    return _replace_optional(
        path,
        '            "v11.4.4 recovery gate: " + recovery.reason,\n',
        '            "v11.4.5 recovery gate: " + recovery.reason,\n',
        label="recovery status version",
    )


def apply_v1145_hotfix() -> None:
    os.environ["BOT_VERSION"] = "v11.4.5"
    # Keep the v11.3 final-only outcome policy explicit at the newest boundary.
    os.environ["OUTCOME_POST_STOPS"] = "0"
    os.environ["OUTCOME_POST_PARTIAL_TARGETS"] = "0"

    changed = _patch_writer() | _patch_event_writer() | _patch_publisher() | _patch_main()
    if changed:
        print("[v11.4.5 hotfix] Production Guard applied: canonical plan + fact consistency + final structural gate")
    else:
        print("[v11.4.5 hotfix] Production Guard already applied or no compatible source changes found")


if __name__ == "__main__":
    apply_v1145_hotfix()
