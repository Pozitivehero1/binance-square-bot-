import os
import json
from datetime import datetime, timedelta

HISTORY_FILE = "published_history.json"

def load_history():
    """Загружает историю из файла."""
    if os.path.exists(HISTORY_FILE):
        with open(HISTORY_FILE, "r") as f:
            return json.load(f)
    return {}

def save_history(history):
    """Сохраняет историю в файл."""
    with open(HISTORY_FILE, "w") as f:
        json.dump(history, f)

def get_recently_published(minutes=60):
    """
    Возвращает список символов, опубликованных за последние minutes минут.
    """
    history = load_history()
    cutoff = datetime.now() - timedelta(minutes=minutes)
    recent = []
    for symbol, ts in history.items():
        pub_time = datetime.fromisoformat(ts)
        if pub_time > cutoff:
            recent.append(symbol)
    return recent

def add_published(symbol):
    """Добавляет символ в историю с текущим временем."""
    history = load_history()
    history[symbol] = datetime.now().isoformat()
    save_history(history)

def cleanup_history(days=1):
    """Удаляет старые записи (старше days дней)."""
    history = load_history()
    cutoff = datetime.now() - timedelta(days=days)
    to_delete = [s for s, ts in history.items() 
                 if datetime.fromisoformat(ts) < cutoff]
    for s in to_delete:
        del history[s]
    if to_delete:
        save_history(history)
