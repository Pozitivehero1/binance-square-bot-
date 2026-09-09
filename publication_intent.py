"""Durable send intents: never blindly retry an unconfirmed Square request.

The caller holds the bot ProcessLock. Keep this file with the other runtime
state across restarts. Corrupt state fails closed rather than forgetting sends.
"""
from __future__ import annotations
import hashlib
import json
import os
import re
import time
from runtime import atomic_write_json, resolve_state_file


def fingerprint(text):
    return hashlib.sha256(" ".join(str(text).split()).encode()).hexdigest()


def _path():
    return resolve_state_file("PUBLICATION_INTENT_FILE", "publication_intents.json")


def load_intents():
    path = _path()
    if not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or any(not isinstance(v, dict) for v in payload.values()):
        raise ValueError("invalid publication intent state")
    for row in payload.values():
        if row.get("status") not in {"pending", "confirmed"} or not isinstance(row.get("text"), str) or not isinstance(row.get("created_at"), (int, float)) or not isinstance(row.get("symbols"), list):
            raise ValueError("invalid publication intent row")
    return payload


def unresolved_symbols():
    # Recheck uncertain sends on every scan, even when that symbol is not selected.
    pending = [row for row in load_intents().values() if row.get("status") == "pending"]
    if pending:
        posts = _recent_posts()
        for row in pending:
            reconcile(row["text"], row, posts=posts)
    return {symbol for row in load_intents().values() if row.get("status") == "pending" or time.time() - row.get("reconciled_at", 0) < 60 * int(os.getenv("COOLDOWN_MIN", "240"))
            for symbol in row.get("symbols", [])}


def begin(text):
    rows = load_intents()
    key = fingerprint(text)
    if key not in rows:
        rows[key] = {"status": "pending", "created_at": time.time(), "text": text,
                     "symbols": re.findall(r"\$([A-Za-z][A-Za-z0-9]{0,19})", text.upper())}
        atomic_write_json(_path(), rows)
    return rows[key]


def confirm(text, post_id):
    rows = load_intents()
    key = fingerprint(text)
    rows[key].update(status="confirmed", post_id=str(post_id))
    # Only prune old confirmed receipts; unresolved sends never expire silently.
    cutoff = time.time() - 30 * 86400
    rows = {k: v for k, v in rows.items() if v.get("status") == "pending" or v.get("created_at", 0) >= cutoff}
    atomic_write_json(_path(), rows)


def _recent_posts():
    uid = os.getenv("SQUARE_PROFILE_UID", "").strip()
    if not uid:
        return []
    try:
        from square_public_stats import BinanceSquarePublicClient
        return BinanceSquarePublicClient(timeout=8).recent_posts(uid, pages=2)
    except Exception:
        return []


def reconcile(text, intent, posts=None):
    try:
        posts = _recent_posts() if posts is None else posts
        matches = [post for post in posts if post.post_id
                   and post.published_ms >= (intent["created_at"] - 60) * 1000
                   and fingerprint(post.text) == fingerprint(text)]
        if len(matches) == 1:
            confirm(text, matches[0].post_id)
            rows = load_intents()
            rows[fingerprint(text)]["reconciled_at"] = time.time()
            atomic_write_json(_path(), rows)
            return matches[0].post_id
    except Exception:
        # Absence in a partial/error response never authorizes another send.
        pass
    return ""
