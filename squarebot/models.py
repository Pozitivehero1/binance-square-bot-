from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class Story:
    id: str
    kind: str
    symbols: list[str]
    headline: str
    facts: dict[str, str]
    observed_at: str
    score: float = 0.0
    source_url: str = ""
    source_text: str = ""
    image_url: str = ""
    event_key: str = ""
    chart_symbol: str = ""
    # Frames stay out of prompts and persisted JSON.
    candles: list = field(default_factory=list, repr=False)

    def brief(self) -> dict:
        data = asdict(self)
        data.pop("candles")
        return data


@dataclass
class Draft:
    story_id: str
    text: str
    title: str = ""
    format: str = ""
    evidence_quote: str = ""
    provider: str = ""
    model: str = ""
    tokens: int = 0


@dataclass(frozen=True)
class Settings:
    dry_run: bool = True
    universe_size: int = 40
    workers: int = 8
    max_ai_calls: int = 8
    ai_seconds: int = 160
    enable_news: bool = True

    @classmethod
    def from_env(cls):
        import os
        def integer(name, default, low, high):
            return max(low, min(high, int(os.getenv(name, str(default)))))
        return cls(
            dry_run=os.getenv("DRY_RUN", "1").lower() in {"1", "true", "yes"},
            universe_size=integer("EDITOR_UNIVERSE_SIZE", 40, 12, 80),
            workers=integer("EDITOR_DATA_WORKERS", 8, 1, 12),
            max_ai_calls=integer("EDITOR_MAX_AI_CALLS", 8, 1, 16),
            ai_seconds=integer("EDITOR_AI_SECONDS", 160, 15, 300),
            enable_news=os.getenv("ENABLE_NEWS_ARTICLES", "1") == "1",
        )
