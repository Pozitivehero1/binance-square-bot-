"""Validate local configuration without exposing secrets or publishing anything."""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys

from dotenv import load_dotenv

load_dotenv()

from publisher import find_skill_dir


VALID_CONTENT_MODES = {"ai", "ai_first", "mistral", "deterministic"}
VALID_MEDIA_MODES = {"adaptive", "card", "chart", "both", "none"}
VALID_VOICES = {"calm", "direct", "analytical", "contrarian"}


def _bool(name: str, default: str) -> bool:
    return os.getenv(name, default).strip().lower() in {"1", "true", "yes", "on"}


def _number(name: str, default: str, cast, minimum, maximum, errors: list[str]):
    raw = os.getenv(name, default).strip()
    try:
        value = cast(raw)
    except ValueError:
        errors.append(f"{name}: не число ({raw!r})")
        return None
    if value < minimum or value > maximum:
        errors.append(f"{name}: {value} вне диапазона {minimum}..{maximum}")
    return value


def main() -> int:
    parser = argparse.ArgumentParser(description="Проверка конфигурации Binance Square bot")
    parser.add_argument(
        "--publishing",
        action="store_true",
        help="дополнительно потребовать API-ключ и установленный square-post skill",
    )
    args = parser.parse_args()

    errors: list[str] = []
    warnings: list[str] = []

    content_mode = os.getenv("CONTENT_MODE", "ai_first").strip().lower()
    media_mode = os.getenv("PUBLISH_MEDIA_MODE", "adaptive").strip().lower()
    author_voice = os.getenv("AUTHOR_VOICE", "analytical").strip().lower()
    dry_run = _bool("DRY_RUN", "1")
    publish_images = _bool("PUBLISH_IMAGES", "1")
    mistral_key = bool((os.getenv("MISTRAL_API") or os.getenv("MISTRAL_API_KEY") or "").strip())
    square_key = bool((os.getenv("SQUARE_API") or os.getenv("BINANCE_SQUARE_OPENAPI_KEY") or "").strip())
    skill_dir = find_skill_dir()

    if content_mode not in VALID_CONTENT_MODES:
        errors.append(f"CONTENT_MODE: неизвестный режим {content_mode!r}")
    if media_mode not in VALID_MEDIA_MODES:
        errors.append(f"PUBLISH_MEDIA_MODE: неизвестный режим {media_mode!r}")
    if author_voice not in VALID_VOICES:
        errors.append(f"AUTHOR_VOICE: неизвестный голос {author_voice!r}")

    post_variants = _number("POST_VARIANTS", "16", int, 4, 16, errors)
    max_similarity = _number("MAX_POST_SIMILARITY", "0.52", float, 0.35, 0.75, errors)
    min_quality = _number("MIN_POST_QUALITY", "78", float, 50, 100, errors)
    post_min = _number("POST_MIN_CHARS", "260", int, 180, 700, errors)
    post_max = _number("POST_MAX_CHARS", "920", int, 500, 1500, errors)
    if post_min is not None and post_max is not None and post_min >= post_max:
        errors.append("POST_MIN_CHARS должен быть меньше POST_MAX_CHARS")

    memory_path = Path(os.getenv("POST_MEMORY_FILE", "post_memory.json")).expanduser()
    history_path = Path(os.getenv("PUBLISHED_HISTORY_FILE", "published_history.json")).expanduser()
    for label, path in (("POST_MEMORY_FILE", memory_path), ("PUBLISHED_HISTORY_FILE", history_path)):
        parent = path.parent if str(path.parent) else Path(".")
        try:
            parent.mkdir(parents=True, exist_ok=True)
            probe = parent / f".{path.name}.write-test"
            probe.write_text("ok", encoding="utf-8")
            probe.unlink()
        except OSError as exc:
            errors.append(f"{label}: каталог недоступен для записи ({exc})")

    if content_mode != "deterministic" and not mistral_key:
        warnings.append("Mistral-ключ не задан: генератор автоматически использует локальный fallback")
    if not publish_images and media_mode != "none":
        warnings.append("PUBLISH_IMAGES=0: режим медиа будет проигнорирован")
    if not dry_run and not square_key:
        errors.append("DRY_RUN=0, но ключ Binance Square не задан")
    if not dry_run and not skill_dir:
        errors.append("DRY_RUN=0, но square-post skill не найден")
    if args.publishing:
        if not square_key:
            errors.append("Не задан SQUARE_API или BINANCE_SQUARE_OPENAPI_KEY")
        if not skill_dir:
            errors.append("Не найден установленный Binance square-post skill")

    print("CONFIGURATION")
    print(f"  CONTENT_MODE={content_mode} | Mistral key={'yes' if mistral_key else 'no'}")
    print(f"  AUTHOR_VOICE={author_voice}")
    print(f"  POST_VARIANTS={post_variants} | MIN_POST_QUALITY={min_quality} | MAX_POST_SIMILARITY={max_similarity}")
    print(f"  PUBLISH_MEDIA_MODE={media_mode} | PUBLISH_IMAGES={int(publish_images)}")
    print(f"  DRY_RUN={int(dry_run)} | Square key={'yes' if square_key else 'no'} | skill={'found' if skill_dir else 'not found'}")
    print(f"  memory={memory_path} | history={history_path}")

    for warning in warnings:
        print(f"WARNING: {warning}")
    for error in errors:
        print(f"ERROR: {error}")

    if errors:
        print(f"CONFIG CHECK: FAILED | errors={len(errors)}")
        return 1
    print(f"CONFIG CHECK: OK | warnings={len(warnings)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
