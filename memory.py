"""Persistent post memory for topic, title and wording diversity."""
from __future__ import annotations

import json
import logging
import os
import re
import tempfile
from datetime import datetime, timedelta, timezone
from difflib import SequenceMatcher
from pathlib import Path
from typing import List

logger = logging.getLogger(__name__)

MEMORY_FILE = Path(os.getenv("POST_MEMORY_FILE", "post_memory.json"))


class PostMemory:
    def __init__(self, path: Path = MEMORY_FILE, keep_days: int = 21, max_items: int = 80):
        self.path = Path(path)
        self.keep_days = max(1, int(keep_days))
        self.max_items = max(10, int(max_items))
        self.items: List[dict] = self._load()

    @staticmethod
    def _now() -> datetime:
        return datetime.now(timezone.utc)

    @staticmethod
    def _parse_timestamp(value: str) -> datetime:
        parsed = datetime.fromisoformat(value)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)

    @staticmethod
    def normalize_text(text: str) -> str:
        normalized = text.lower().replace("ё", "е")
        normalized = re.sub(r"\$[a-z0-9]+", "$ticker", normalized)
        normalized = re.sub(r"\b\d+(?:[.,]\d+)?\b", "#", normalized)
        normalized = re.sub(r"#[a-zа-я0-9_]+", "", normalized)
        normalized = re.sub(r"[^a-zа-я$#\s]", " ", normalized)
        normalized = re.sub(r"\s+", " ", normalized)
        return normalized.strip()

    def _load(self) -> List[dict]:
        if not self.path.exists():
            return []
        try:
            with self.path.open("r", encoding="utf-8") as handle:
                data = json.load(handle)
            if not isinstance(data, list):
                return []
            cutoff = self._now() - timedelta(days=self.keep_days)
            valid = []
            for item in data:
                if not isinstance(item, dict) or "ts" not in item:
                    continue
                try:
                    if self._parse_timestamp(item["ts"]) >= cutoff:
                        valid.append(item)
                except (TypeError, ValueError):
                    continue
            return valid[-self.max_items :]
        except Exception as exc:
            logger.warning("PostMemory load failed: %s", exc)
            return []

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = None
        try:
            with tempfile.NamedTemporaryFile(
                "w",
                encoding="utf-8",
                dir=str(self.path.parent),
                prefix=f".{self.path.name}.",
                suffix=".tmp",
                delete=False,
            ) as handle:
                temp_path = Path(handle.name)
                json.dump(self.items[-self.max_items :], handle, ensure_ascii=False, indent=2)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_path, self.path)
        except Exception as exc:
            logger.error("PostMemory save failed: %s", exc)
            if temp_path and temp_path.exists():
                try:
                    temp_path.unlink()
                except OSError:
                    pass

    def add_post(self, symbol: str, text: str) -> None:
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        title = lines[0] if lines else ""
        content_lines = [line for line in lines if not line.startswith("#")]
        cta = ""
        for line in reversed(content_lines[-5:]):
            if "?" in line:
                cta = line
                break

        self.items.append(
            {
                "ts": self._now().isoformat(),
                "symbol": symbol.upper(),
                "text": text,
                "title": title,
                "title_signature": self.normalize_text(title),
                "cta": cta,
                "text_signature": self.normalize_text(text),
            }
        )
        self.items = self.items[-self.max_items :]
        self._save()

    def recent_texts(self, n: int = 10) -> List[str]:
        return [str(item.get("text", "")) for item in self.items[-n:]]

    def recent_symbols(self, n: int = 20) -> List[str]:
        return [str(item.get("symbol", "")) for item in self.items[-n:]]

    def get_last_titles(self, n: int = 10) -> List[str]:
        return [str(item.get("title", "")) for item in self.items[-n:]]

    def get_last_ctas(self, n: int = 10) -> List[str]:
        return [str(item.get("cta", "")) for item in self.items[-n:] if item.get("cta")]

    def get_last_styles(self, n: int = 10) -> List[str]:
        # Backward-compatible method. Signatures are more useful than old MD5 hashes.
        return [str(item.get("text_signature", ""))[:80] for item in self.items[-n:]]

    def was_title_used(self, title: str, threshold: float = 0.86) -> bool:
        candidate = self.normalize_text(title)
        if not candidate:
            return False
        for item in self.items[-30:]:
            existing = item.get("title_signature") or self.normalize_text(item.get("title", ""))
            if SequenceMatcher(None, candidate, existing).ratio() >= threshold:
                return True
        return False

    def similarity_score(self, text: str) -> float:
        candidate = self.normalize_text(text)
        if not candidate:
            return 0.0
        candidate_tokens = set(candidate.split())
        best = 0.0
        for item in self.items[-30:]:
            existing = item.get("text_signature") or self.normalize_text(item.get("text", ""))
            if not existing:
                continue
            sequence_ratio = SequenceMatcher(None, candidate, existing).ratio()
            existing_tokens = set(existing.split())
            union = candidate_tokens | existing_tokens
            token_ratio = len(candidate_tokens & existing_tokens) / len(union) if union else 0.0
            best = max(best, sequence_ratio * 0.55 + token_ratio * 0.45)
        return best

    def is_similar(self, text: str, threshold: float = 0.60) -> bool:
        return self.similarity_score(text) >= threshold
