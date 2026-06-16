import os
import json
from datetime import datetime, timedelta

HISTORY_FILE = "published_history.json"

def load_history():
    if os.path.exists(HISTORY_FILE):
        with open(HISTORY_FILE, "r") as f:
            return json.load(f)
    return {}

def save_history(history):
    with open(HISTORY_FILE, "w") as f:
        json.dump(history, f)

def get_recently_published(minutes=60):
    history = load_history()
    cutoff = datetime.now() - timedelta(minutes=minutes)
    return [s for s, ts in history.items() if datetime.fromisoformat(ts) > cutoff]

def add_published(symbol):
    history = load_history()
    history[symbol] = datetime.now().isoformat()
    save_history(history)

def cleanup_history(days=1):
    history = load_history()
    cutoff = datetime.now() - timedelta(days=days)
    to_delete = [s for s, ts in history.items() if datetime.fromisoformat(ts) < cutoff]
    for s in to_delete:
        del history[s]
    if to_delete:
        save_history(history)
