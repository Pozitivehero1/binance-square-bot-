"""v11.4 Reach Writer production hotfix."""
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
        print(f"[v11.4 hotfix] warning: {label}: expected one source match, found {count}; skipped")
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
        '            "Первая строка — самостоятельный хук и обязательно содержит основной cashtag.",\n',
        '            "Первая строка — сильнейший факт поста: конкретное движение, необычная активность, ключевой уровень или понятный конфликт. Основной cashtag обязателен. Не начинай с пустых общих фраз.",\n',
        label="trade AI hook brief",
    )
    changed |= _replace_optional(
        path,
        '''            except Exception as exc:
                logger.warning("AI author attempt %s failed: %s", attempt, exc)
                break
''',
        '''            except Exception as exc:
                logger.warning("AI author attempt %s failed: %s", attempt, exc)
                if attempt < AI_RETRIES:
                    continue
                break
''',
        label="trade provider retry",
    )
    changed |= _replace_optional(
        path,
        '''    # Always create deterministic alternatives. They are a safety net when the
    # API is down and also give the selector something fact-perfect to compare.
    target_count = max(6, min(int(variant_count), 24))
    for index, fmt in enumerate(formats):
        if len(drafts) >= target_count:
            break
''',
        '''    # v11.4 Reach Writer: when AI is healthy, keep only a small deterministic
    # comparison set. During an AI outage the full fact-perfect fallback pool remains.
    target_count = max(6, min(int(variant_count), 24))
    ai_count = sum(1 for draft in drafts if draft.source in {"mistral", "deepseek"})
    compare_slots = max(0, min(int(os.getenv("DETERMINISTIC_COMPARE_SLOTS", "2")), 4))
    deterministic_target = target_count if ai_count == 0 else min(target_count, len(drafts) + compare_slots)
    for index, fmt in enumerate(formats):
        if len(drafts) >= deterministic_target:
            break
''',
        label="trade deterministic comparison budget",
    )
    return changed


def _patch_event_writer() -> bool:
    path = PROJECT_DIR / "event_writer.py"
    changed = False
    changed |= _replace_optional(
        path,
        '            "Первая строка — сильный самостоятельный хук и обязательно содержит основной cashtag.",\n',
        '            "Первая строка — самый сильный факт события: резкое изменение темпа, необычный объём, важная цена или ясный конфликт. Основной cashtag обязателен. Не начинай с пустых общих фраз.",\n',
        label="event AI hook brief",
    )
    changed |= _replace_optional(
        path,
        '''            except Exception as exc:
                logger.warning("AI event-author attempt %s failed: %s", attempt, exc)
                break
''',
        '''            except Exception as exc:
                logger.warning("AI event-author attempt %s failed: %s", attempt, exc)
                if attempt < EVENT_AI_RETRIES:
                    continue
                break
''',
        label="event provider retry",
    )
    changed |= _replace_optional(
        path,
        '''    # Safety net.  AI remains the preferred source, but one API hiccup must
    # not make the market scanner fragile.
    for index, fmt in enumerate(formats):
        if len(drafts) >= max(6, min(count, 14)):
            break
''',
        '''    # v11.4 Reach Writer: AI copy has materially outperformed deterministic
    # EVENT copy, so keep only a small deterministic comparison set when AI is healthy.
    event_target_count = max(6, min(count, 14))
    ai_count = sum(1 for draft in drafts if draft.source in {"mistral_event", "deepseek_event"})
    compare_slots = max(0, min(int(os.getenv("EVENT_DETERMINISTIC_COMPARE_SLOTS", "2")), 4))
    deterministic_target = event_target_count if ai_count == 0 else min(event_target_count, len(drafts) + compare_slots)
    for index, fmt in enumerate(formats):
        if len(drafts) >= deterministic_target:
            break
''',
        label="event deterministic comparison budget",
    )
    changed |= _replace_optional(
        path,
        '''        adjusted = (
            report.score * 0.45
            + appeal.score * 0.28
            + conversion * 0.27
            - max(0.0, similarity - 0.26) * 78.0
''',
        '''        author_bonus = (
            float(os.getenv("EVENT_AI_AUTHOR_BONUS", "8.0"))
            if draft.source in {"mistral_event", "deepseek_event"} else 0.0
        )
        adjusted = (
            report.score * 0.45
            + appeal.score * 0.28
            + conversion * 0.27
            + author_bonus
            - max(0.0, similarity - 0.26) * 78.0
''',
        label="event AI author bonus",
    )
    return changed


def _patch_main() -> bool:
    path = PROJECT_DIR / "main.py"
    return _replace_optional(
        path,
        '            author_bonus = 4.0 if draft.source == "mistral" else 0.0\n',
        '            author_bonus = float(os.getenv("AI_AUTHOR_BONUS", "7.0")) if draft.source in {"mistral", "deepseek"} else 0.0\n',
        label="trade AI author bonus",
    )


def apply_v114_hotfix() -> None:
    os.environ["DETERMINISTIC_COMPARE_SLOTS"] = "2"
    os.environ["EVENT_DETERMINISTIC_COMPARE_SLOTS"] = "2"
    os.environ["AI_AUTHOR_BONUS"] = "7.0"
    os.environ["EVENT_AI_AUTHOR_BONUS"] = "8.0"
    changed = _patch_writer() | _patch_event_writer() | _patch_main()
    if changed:
        print("[v11.4 hotfix] Reach Writer applied: AI-first copy + stronger hooks + bounded deterministic fallback")
    else:
        print("[v11.4 hotfix] Reach Writer already applied or no compatible source changes found")


if __name__ == "__main__":
    apply_v114_hotfix()
