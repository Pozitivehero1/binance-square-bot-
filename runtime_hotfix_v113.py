"""Production hotfix for v11.3.

Applied before importing main so the cron runner gets the fixes immediately even when
older cached/source files are present. The patch is idempotent and becomes a no-op if
the same changes are already present in the source tree.
"""
from __future__ import annotations

from pathlib import Path

from runtime import PROJECT_DIR


def _replace_once(text: str, old: str, new: str, *, label: str) -> tuple[str, bool]:
    if new in text:
        return text, False
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"v11.3 hotfix: {label}: expected one source match, found {count}")
    return text.replace(old, new, 1), True


def _patch_outcomes() -> bool:
    path = PROJECT_DIR / "outcome_engine.py"
    text = path.read_text(encoding="utf-8")
    changed = False

    old = 'POST_STOPS = os.getenv("OUTCOME_POST_STOPS", "1").strip().lower() in {"1", "true", "yes", "on"}\n'
    new = (
        old
        + 'POST_PARTIAL_TARGETS = os.getenv("OUTCOME_POST_PARTIAL_TARGETS", "0").strip().lower() in {"1", "true", "yes", "on"}\n'
    )
    text, did = _replace_once(text, old, new, label="partial-target policy flag")
    changed |= did

    old = '''            # If a partial target follow-up has already been sent, suppress further
            # partial updates and reserve the second slot for final/stop outcome.
            sent_target = any((f.get("kind") == "target") for f in (trade.get("followups") or []))
            if event["kind"] == "target_complete" or not sent_target:
                _queue_event(trade, event)
'''
    new = '''            # v11.3: TP1/TP2 remain journal-only by default. The public feed gets
            # only the verified full TP3 completion unless explicitly re-enabled.
            if event["kind"] == "target_complete" or POST_PARTIAL_TARGETS:
                _queue_event(trade, event)
'''
    text, did = _replace_once(text, old, new, label="final-only target queue")
    changed |= did

    old = '''        if not isinstance(event, dict):
            continue
        if len(trade.get("followups") or []) >= MAX_FOLLOWUPS:
'''
    new = '''        if not isinstance(event, dict):
            continue
        # Remove events queued by an older policy before they can consume a cron slot.
        kind = str(event.get("kind") or "")
        if kind == "target" and not POST_PARTIAL_TARGETS:
            trade["pending_followup"] = None
            continue
        if kind in {"stop", "stop_after_target"} and not POST_STOPS:
            trade["pending_followup"] = None
            continue
        if len(trade.get("followups") or []) >= MAX_FOLLOWUPS:
'''
    text, did = _replace_once(text, old, new, label="stale outcome queue purge")
    changed |= did

    compile(text, str(path), "exec")
    if changed:
        path.write_text(text, encoding="utf-8")
    return changed


def _patch_publisher() -> bool:
    path = PROJECT_DIR / "publisher.py"
    text = path.read_text(encoding="utf-8")
    changed = False

    marker = "def normalize_square_cashtags(text: str) -> str:"
    if marker not in text:
        old = "def publish(text: str, image_path: ImageInput = None) -> PublishResult:\n"
        new = '''def normalize_square_cashtags(text: str) -> str:
    """Keep Binance Square cashtags isolated from colon punctuation."""
    value = str(text or "")
    # Binance Square can miss a cashtag when a colon is attached, e.g. "$BTC:".
    # Keep the meaning/style but force whitespace after the cashtag token.
    return re.sub(r"(\\$[A-Za-z][A-Za-z0-9]{0,19})\\s*[:：]", r"\\1 —", value)


def publish(text: str, image_path: ImageInput = None) -> PublishResult:
'''
        text, did = _replace_once(text, old, new, label="cashtag sanitizer function")
        changed |= did

    call_marker = "normalized = normalize_square_cashtags(text)"
    if call_marker not in text:
        old = '''    if not text or not text.strip():
        logger.error("Refusing to publish an empty post")
        return PublishResult(False, stderr="empty post")

    skill_dir = find_skill_dir()
'''
        new = '''    if not text or not text.strip():
        logger.error("Refusing to publish an empty post")
        return PublishResult(False, stderr="empty post")

    normalized = normalize_square_cashtags(text)
    if normalized != text:
        logger.info("Normalized Square cashtag punctuation before publish")
    text = normalized

    skill_dir = find_skill_dir()
'''
        text, did = _replace_once(text, old, new, label="cashtag sanitizer call")
        changed |= did

    compile(text, str(path), "exec")
    if changed:
        path.write_text(text, encoding="utf-8")
    return changed


def apply_v113_hotfix() -> None:
    changed = _patch_outcomes() | _patch_publisher()
    if changed:
        print("[v11.3 hotfix] final-only outcomes + clickable cashtags applied")


if __name__ == "__main__":
    apply_v113_hotfix()
