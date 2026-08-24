# v11.4.1 Text Integrity production hotfix.
from __future__ import annotations

from pathlib import Path

from runtime import PROJECT_DIR


def _replace_optional(path: Path, old: str, new: str, *, label: str) -> bool:
    text = path.read_text(encoding="utf-8")
    if new in text:
        return False
    count = text.count(old)
    if count != 1:
        print(f"[v11.4.1 hotfix] warning: {label}: expected one source match, found {count}; skipped")
        return False
    updated = text.replace(old, new, 1)
    compile(updated, str(path), "exec")
    path.write_text(updated, encoding="utf-8")
    return True


def _patch_writer() -> bool:
    path = PROJECT_DIR / "writer.py"
    changed = False
    changed |= _replace_optional(path, "from trade_plan import build_public_trade_plan\n", "from trade_plan import build_public_trade_plan\nfrom text_integrity import artifact_reasons\n", label="trade text-integrity import")
    changed |= _replace_optional(
        path,
        '            "Первая строка — сильнейший факт поста: конкретное движение, необычная активность, ключевой уровень или понятный конфликт. Основной cashtag обязателен. Не начинай с пустых общих фраз.",\n',
        '            "Первая строка — сильнейший факт поста: конкретное движение, необычная активность, ключевой уровень или понятный конфликт. Основной cashtag обязателен. Не начинай с пустых общих фраз.",\n            "Пиши только чистым plain text: без Markdown (**/__/#/```), без английских служебных слов вроде exactly, без X%/Y%/TODO/TBD и без цепочек ----, ____, <<>> или другого технического мусора.",\n',
        label="trade plain-text prompt",
    )
    changed |= _replace_optional(
        path,
        '    reasons: List[str] = []\n    text = str(text or "").strip()\n    lowered = text.lower().replace("ё", "е")\n',
        '    reasons: List[str] = []\n    text = str(text or "").strip()\n    integrity = artifact_reasons(text)\n    if integrity:\n        reasons.append("text artifacts: " + ",".join(integrity))\n    lowered = text.lower().replace("ё", "е")\n',
        label="trade AI artifact validator",
    )
    return changed


def _patch_event_writer() -> bool:
    path = PROJECT_DIR / "event_writer.py"
    changed = False
    changed |= _replace_optional(path, "from writer import GeneratedPost, _enforce_full_plan_block, _fmt_pct, _fmt_price, _fmt_x, phrase_family_penalty\n", "from writer import GeneratedPost, _enforce_full_plan_block, _fmt_pct, _fmt_price, _fmt_x, phrase_family_penalty\nfrom text_integrity import artifact_reasons\n", label="event text-integrity import")
    changed |= _replace_optional(
        path,
        '            "Первая строка — самый сильный факт события: резкое изменение темпа, необычный объём, важная цена или ясный конфликт. Основной cashtag обязателен. Не начинай с пустых общих фраз.",\n',
        '            "Первая строка — самый сильный факт события: резкое изменение темпа, необычный объём, важная цена или ясный конфликт. Основной cashtag обязателен. Не начинай с пустых общих фраз.",\n            "Пиши только чистым plain text: без Markdown (**/__/#/```), без английских служебных слов вроде exactly, без X%/Y%/TODO/TBD и без цепочек ----, ____, <<>> или другого технического мусора.",\n',
        label="event plain-text prompt",
    )
    changed |= _replace_optional(
        path,
        '    reasons: List[str] = []\n    text = str(text or "").strip()\n    lowered = text.lower().replace("ё", "е")\n',
        '    reasons: List[str] = []\n    text = str(text or "").strip()\n    integrity = artifact_reasons(text)\n    if integrity:\n        reasons.append("text artifacts: " + ",".join(integrity))\n    lowered = text.lower().replace("ё", "е")\n',
        label="event AI artifact validator",
    )
    return changed


def apply_v1141_hotfix() -> None:
    changed = _patch_writer() | _patch_event_writer()
    if changed:
        print("[v11.4.1 hotfix] Text Integrity applied: artifact rejection + plain-text prompts")
    else:
        print("[v11.4.1 hotfix] Text Integrity already applied or no compatible source changes found")


if __name__ == "__main__":
    apply_v1141_hotfix()
