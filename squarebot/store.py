"""Durable editorial history, including in-flight story reservations."""
from __future__ import annotations

import json
import re
from pathlib import Path

from runtime import atomic_write_json, resolve_state_file
from .models import utcnow


class Store:
    def __init__(self, path: Path | None = None):
        self.path = path or resolve_state_file("EDITOR_STATE_FILE", "editorial_v13.json")
        self.data = {"schema": 1, "posts": [], "pending": {}}
        if self.path.exists():
            self.data = json.loads(self.path.read_text(encoding="utf-8"))
            if (not isinstance(self.data, dict) or not isinstance(self.data.get("posts"), list)
                    or not isinstance(self.data.get("pending"), dict)):
                raise ValueError("Editorial state is invalid; refusing to forget publication history")

    def save(self):
        self.data["posts"] = self.data["posts"][-1000:]
        atomic_write_json(self.path, self.data)

    def recent(self, limit=40):
        """Include legacy publications during migration; do not reset repeat memory."""
        rows = list(self.data["posts"])
        from performance_store import load_store
        rows.extend(p for p in load_store().get("posts", {}).values() if isinstance(p, dict))
        # The committed dashboard is a fallback if the Actions cache was evicted.
        if not rows:
            from runtime import PROJECT_DIR
            try:
                rows = json.loads((PROJECT_DIR / "dashboard/data.json").read_text()).get("posts", [])
            except (OSError, ValueError):
                pass
        unique = {}
        for row in sorted(rows, key=lambda r: str(r.get("published_at", "")), reverse=True):
            if row.get("text"):
                unique.setdefault(row.get("post_id") or row["text"], row)
        return list(unique.values())[:limit]

    def covered(self, story):
        keys = {story.id, story.event_key} - {""}
        for row in self.data["posts"] + list(self.data["pending"].values()):
            if keys.intersection({row.get("story_id"), row.get("event_key")}):
                return True
        return False

    def reserve(self, story, draft):
        self.data["pending"][story.id] = {
            "story_id": story.id, "event_key": story.event_key, "text": draft.text,
            "created_at": utcnow().isoformat(), "story": story.brief(),
            "draft": {"provider": draft.provider, "model": draft.model, "format": draft.format},
        }
        self.save()

    def confirm(self, story_id, post_id):
        row = self.data["pending"].pop(story_id)
        row.update(post_id=post_id, published_at=utcnow().isoformat())
        self.data["posts"].append(row)
        self.save()
        return row

    def reconcile(self):
        """A crash after Square accepted a post must not create a rewritten resend."""
        import publication_intent as intents
        receipts = intents.load_intents()
        posts = None
        for key, row in list(self.data["pending"].items()):
            intent = receipts.get(intents.fingerprint(row["text"]))
            if intent is None:
                # Reservation persisted before the transport was started.
                self.data["pending"].pop(key)
                continue
            post_id = intent.get("post_id", "")
            if intent.get("status") == "pending":
                if posts is None:
                    posts = intents._recent_posts()
                post_id = intents.reconcile(row["text"], intent, posts=posts)
            if post_id:
                self.confirm(key, post_id)
        self.save()


def word_shingles(text: str) -> set[tuple]:
    # Mask changing prices and tickers so a template with new numbers is still a repeat.
    text = re.sub(r"\$[A-Za-z0-9]+|[+-]?\d+(?:[.,]\d+)?", " ", text.lower())
    words = re.findall(r"[а-яёa-z]{2,}", text)
    return set(zip(words, words[1:], words[2:]))


def similarity(a: str, b: str) -> float:
    left, right = word_shingles(a), word_shingles(b)
    return len(left & right) / max(1, min(len(left), len(right)))
