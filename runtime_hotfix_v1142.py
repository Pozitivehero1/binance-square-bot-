"""v11.4.2 Reach Quality production hotfix.

Keeps the v11.3 trading/outcome contract intact while using mature reach data
more decisively and refusing semantically broken AI copy.
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
        print(f"[v11.4.2 hotfix] warning: {label}: expected one source match, found {count}; skipped")
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
        "from text_integrity import artifact_reasons\n",
        "from text_integrity import artifact_reasons\nfrom semantic_quality import semantic_quality_reasons\n",
        label="trade semantic-quality import",
    )
    changed |= _replace_optional(
        path,
        '            "Пиши только чистым plain text: без Markdown (**/__/#/```), без английских служебных слов вроде exactly, без X%/Y%/TODO/TBD и без цепочек ----, ____, <<>> или другого технического мусора.",\n',
        '            "Пиши только чистым plain text: без Markdown (**/__/#/```), без английских служебных слов вроде exactly, без X%/Y%/TODO/TBD и без цепочек ----, ____, <<>> или другого технического мусора.",\n            "Не обещай исход и время достижения цели: запрещены фразы вроде без потерь, дело времени, через час будет цель, вперёд к целям. Не используй прямые команды покупать/продавать. Проверь текст на явные опечатки перед ответом.",\n',
        label="trade semantic prompt",
    )
    changed |= _replace_optional(
        path,
        '''    integrity = artifact_reasons(text)
    if integrity:
        reasons.append("text artifacts: " + ",".join(integrity))
    lowered = text.lower().replace("ё", "е")
''',
        '''    integrity = artifact_reasons(text)
    if integrity:
        reasons.append("text artifacts: " + ",".join(integrity))
    semantic = semantic_quality_reasons(text)
    if semantic:
        reasons.append("semantic quality: " + ",".join(semantic))
    lowered = text.lower().replace("ё", "е")
''',
        label="trade semantic validator",
    )
    return changed


def _patch_event_writer() -> bool:
    path = PROJECT_DIR / "event_writer.py"
    changed = False
    changed |= _replace_optional(
        path,
        "from text_integrity import artifact_reasons\n",
        "from text_integrity import artifact_reasons\nfrom semantic_quality import semantic_quality_reasons\n",
        label="event semantic-quality import",
    )
    changed |= _replace_optional(
        path,
        '            "Пиши только чистым plain text: без Markdown (**/__/#/```), без английских служебных слов вроде exactly, без X%/Y%/TODO/TBD и без цепочек ----, ____, <<>> или другого технического мусора.",\n',
        '            "Пиши только чистым plain text: без Markdown (**/__/#/```), без английских служебных слов вроде exactly, без X%/Y%/TODO/TBD и без цепочек ----, ____, <<>> или другого технического мусора.",\n            "Не обещай исход и время достижения цели: запрещены фразы вроде без потерь, дело времени, через час будет цель, вперёд к целям. Не используй прямые команды покупать/продавать. Проверь текст на явные опечатки перед ответом.",\n',
        label="event semantic prompt",
    )
    changed |= _replace_optional(
        path,
        '''    integrity = artifact_reasons(text)
    if integrity:
        reasons.append("text artifacts: " + ",".join(integrity))
    lowered = text.lower().replace("ё", "е")
''',
        '''    integrity = artifact_reasons(text)
    if integrity:
        reasons.append("text artifacts: " + ",".join(integrity))
    semantic = semantic_quality_reasons(text)
    if semantic:
        reasons.append("semantic quality: " + ",".join(semantic))
    lowered = text.lower().replace("ё", "е")
''',
        label="event semantic validator",
    )
    return changed


def _patch_publisher() -> bool:
    path = PROJECT_DIR / "publisher.py"
    changed = False
    changed |= _replace_optional(
        path,
        "from text_integrity import artifact_reasons, sanitize_safe_markup\n",
        "from text_integrity import artifact_reasons, sanitize_safe_markup\nfrom semantic_quality import semantic_quality_reasons\n",
        label="publisher semantic-quality import",
    )
    changed |= _replace_optional(
        path,
        "    reasons = artifact_reasons(normalized)\n",
        "    reasons = tuple(dict.fromkeys((*artifact_reasons(normalized), *semantic_quality_reasons(normalized))))\n",
        label="publisher final semantic gate",
    )
    return changed


def _patch_adaptive() -> bool:
    path = PROJECT_DIR / "adaptive.py"
    old = '''    ticker_aff, ticker_comp, ticker_n = _affinity(ticker_rows, baseline, prior=5.0, max_component=MAX_TICKER)
    hour_aff, hour_comp, hour_n = _affinity(hour_rows, baseline, prior=12.0, max_component=MAX_HOUR)
    lane_aff, lane_comp, lane_n = _affinity(lane_rows, baseline, prior=35.0, max_component=MAX_LANE)
'''
    new = '''    ticker_aff, ticker_comp, ticker_n = _affinity(ticker_rows, baseline, prior=5.0, max_component=MAX_TICKER)
    hour_aff, hour_comp, hour_n = _affinity(hour_rows, baseline, prior=12.0, max_component=MAX_HOUR)
    lane_aff, lane_comp, lane_n = _affinity(lane_rows, baseline, prior=35.0, max_component=MAX_LANE)

    # v11.4.2: mature reach history should matter more once a pattern is proven.
    # This is still a soft ranking prior: a genuinely fresh/high-demand event can
    # escape the extra penalty, so history never becomes a permanent blacklist.
    reach_live_strength = max(float(live_score), float(micro_score))
    live_escape = (
        event_class in {"fresh_event", "audience_breakout"}
        and reach_live_strength >= 74.0
    ) or (
        event_class == "high_demand_active"
        and reach_live_strength >= 78.0
    )

    if ticker_n >= 6 and ticker_aff <= 35.0:
        if live_escape:
            ticker_comp = max(float(ticker_comp) - 0.5, -8.0)
        else:
            ticker_comp = max(-MAX_TICKER, float(ticker_comp) - 4.0)
    elif ticker_n >= 5 and ticker_aff >= 60.0 and live_score >= 62.0:
        ticker_comp = min(MAX_TICKER, float(ticker_comp) + min(2.0, 0.5 + (ticker_aff - 60.0) / 12.0))

    if hour_n >= 16 and hour_aff <= 40.0:
        if live_escape:
            hour_comp = max(float(hour_comp) - 0.25, -3.5)
        else:
            hour_comp = max(-MAX_HOUR, float(hour_comp) - 2.5)
    elif hour_n >= 15 and hour_aff >= 56.0:
        hour_comp = min(MAX_HOUR, float(hour_comp) + min(1.5, 0.5 + (hour_aff - 56.0) / 10.0))

    ticker_comp = round(float(ticker_comp), 2)
    hour_comp = round(float(hour_comp), 2)
'''
    return _replace_optional(path, old, new, label="reach history priors")


def _patch_performance_store() -> bool:
    path = PROJECT_DIR / "performance_store.py"
    return _replace_optional(
        path,
        '            "source": "bot",\n',
        '            "source": "bot",\n            "engine_version": str(os.getenv("BOT_VERSION", "")).strip(),\n',
        label="publication engine version",
    )


def _patch_trade_journal() -> bool:
    path = PROJECT_DIR / "trade_journal.py"
    return _replace_optional(
        path,
        '        "writer_source": str(writer_source or ""),\n        "status": "active" if immediate else "pending_entry",\n',
        '        "writer_source": str(writer_source or ""),\n        "engine_version": str(os.getenv("BOT_VERSION", "")).strip(),\n        "status": "active" if immediate else "pending_entry",\n',
        label="outcome engine version",
    )


def apply_v1142_hotfix() -> None:
    # Reach-focused tuning. Existing trade geometry and outcome rules are untouched.
    os.environ["BOT_VERSION"] = "v11.4.2"
    os.environ["DETERMINISTIC_COMPARE_SLOTS"] = "1"
    os.environ["EVENT_DETERMINISTIC_COMPARE_SLOTS"] = "1"
    os.environ["AI_AUTHOR_BONUS"] = "9.0"
    os.environ["EVENT_AI_AUTHOR_BONUS"] = "10.0"
    os.environ["AI_VARIANTS"] = "8"
    os.environ["EVENT_AI_VARIANTS"] = "8"
    os.environ["ADAPTIVE_TICKER_MAX"] = "12.0"
    os.environ["ADAPTIVE_HOUR_MAX"] = "6.5"
    os.environ["ADAPTIVE_MAX_TOTAL"] = "17.0"

    changed = (
        _patch_writer()
        | _patch_event_writer()
        | _patch_publisher()
        | _patch_adaptive()
        | _patch_performance_store()
        | _patch_trade_journal()
    )
    if changed:
        print("[v11.4.2 hotfix] Reach Quality applied: stronger priors + semantic gate + AI-first selection")
    else:
        print("[v11.4.2 hotfix] Reach Quality already applied or no compatible source changes found")


if __name__ == "__main__":
    apply_v1142_hotfix()
