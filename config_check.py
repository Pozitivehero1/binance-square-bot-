"""Validate production configuration without exposing secrets or publishing."""
from __future__ import annotations

import argparse
import os
from pathlib import Path

from runtime import PROJECT_DIR, load_project_env, resolve_project_file, resolve_state_file

load_project_env()

from publication_guard import PublicationGuard
from publisher import find_skill_dir
from openrouter_fallback_chain import configured_openrouter_models

VALID_CONTENT_MODES = {"ai_author", "ai", "ai_first", "mistral", "deterministic"}
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


def _writable(label: str, path: Path, errors: list[str]) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        probe = path.parent / f".{path.name}.write-test"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
    except OSError as exc:
        errors.append(f"{label}: каталог недоступен для записи ({exc})")


def main() -> int:
    parser = argparse.ArgumentParser(description="Проверка конфигурации Binance Square bot")
    parser.add_argument("--publishing", action="store_true")
    args = parser.parse_args()

    errors: list[str] = []
    warnings: list[str] = []

    orca_key = bool((os.getenv("ORCAROUTER_API_KEY") or os.getenv("ORCA_API_KEY") or "").strip())
    openrouter_key = bool((os.getenv("OPENROUTER_API_KEY") or "").strip())
    mistral_key = bool((os.getenv("MISTRAL_API") or os.getenv("MISTRAL_API_KEY") or "").strip())
    ai_key = orca_key or openrouter_key or mistral_key
    default_content_mode = "ai_author" if ai_key else "deterministic"
    content_mode = os.getenv("CONTENT_MODE", default_content_mode).strip().lower()
    media_mode = os.getenv("PUBLISH_MEDIA_MODE", "chart").strip().lower()
    author_voice = os.getenv("AUTHOR_VOICE", "direct").strip().lower()
    dry_run = _bool("DRY_RUN", "1")
    enable_pacing = _bool("ENABLE_PACING_LIMITS", "0")
    enable_reach_gate = _bool("ENABLE_REACH_GATE", "1")
    publish_images = _bool("PUBLISH_IMAGES", "1")
    outcome_enabled = _bool("ENABLE_OUTCOME_ENGINE", "1")
    allow_technical = _bool("ALLOW_TECHNICAL_FORMATS", "0")
    square_key = bool((os.getenv("SQUARE_API") or os.getenv("BINANCE_SQUARE_OPENAPI_KEY") or "").strip())
    skill_dir = find_skill_dir()

    if content_mode not in VALID_CONTENT_MODES:
        errors.append(f"CONTENT_MODE: неизвестный режим {content_mode!r}")
    if media_mode not in VALID_MEDIA_MODES:
        errors.append(f"PUBLISH_MEDIA_MODE: неизвестный режим {media_mode!r}")
    if author_voice not in VALID_VOICES:
        errors.append(f"AUTHOR_VOICE: неизвестный голос {author_voice!r}")

    post_variants = _number("POST_VARIANTS", "16", int, 4, 16, errors)
    max_similarity = _number("MAX_POST_SIMILARITY", "0.46", float, 0.35, 0.75, errors)
    min_quality = _number("MIN_POST_QUALITY", "84", float, 50, 100, errors)
    min_feed = _number("MIN_FEED_APPEAL", "76", float, 40, 100, errors)
    min_conversion = _number("MIN_CONVERSION_INTENT", "75", float, 40, 100, errors)
    min_w2e = _number("MIN_W2E_MARKET_SCORE", "56", float, 0, 100, errors)
    soft_w2e = _number("W2E_SOFT_FLOOR", "40", float, 0, 100, errors)
    hot_w2e = _number("HOT_W2E_FLOOR", "34", float, 0, 100, errors)
    min_opportunity = _number("MIN_OPPORTUNITY_SCORE", "63", float, 0, 100, errors)
    min_demand = _number("MIN_AUDIENCE_DEMAND", "24", float, 0, 100, errors)
    min_event = _number("MIN_EVENT_SCORE", "60", float, 0, 100, errors)
    event_w2e = _number("EVENT_W2E_FLOOR", "42", float, 0, 100, errors)
    event_demand = _number("EVENT_MIN_DEMAND", "20", float, 0, 100, errors)
    event_advantage = _number("EVENT_LANE_ADVANTAGE", "1.5", float, -10, 15, errors)
    event_min_quality = _number("EVENT_MIN_POST_QUALITY", "80", float, 50, 100, errors)
    event_min_feed = _number("EVENT_MIN_FEED_APPEAL", "74", float, 40, 100, errors)
    event_min_conversion = _number("EVENT_MIN_CONVERSION", "72", float, 40, 100, errors)
    min_public_rr = _number("MIN_PUBLIC_PLAN_RR", "1.30", float, 1.0, 5.0, errors)
    min_tp3_rr = _number("MIN_PUBLIC_TP3_RR", "1.65", float, 1.0, 8.0, errors)
    max_public_risk = _number("MAX_PUBLIC_RISK_PCT", "7.0", float, 1.0, 25.0, errors)
    decision_near_atr = _number("DECISION_NEAR_ATR", "0.24", float, 0.05, 1.5, errors)
    decision_near_pct = _number("DECISION_NEAR_PCT", "0.20", float, 0.05, 2.0, errors)
    stop_buffer_atr = _number("PUBLIC_STOP_BUFFER_ATR", "0.75", float, 0.25, 2.0, errors)
    emoji_rate = _number("EMOJI_RATE", "0.16", float, 0, 0.5, errors)
    question_every = _number("QUESTION_EVERY", "9", int, 4, 50, errors)
    post_min = _number("POST_MIN_CHARS", "220", int, 120, 700, errors)
    post_max = _number("POST_MAX_CHARS", "430", int, 300, 1500, errors)
    min_interval = _number("MIN_GLOBAL_INTERVAL_MIN", "20", int, 20, 1440, errors)
    max_daily = _number("MAX_POSTS_PER_DAY", "72", int, 1, 72, errors)
    min_reach = _number("MIN_REACH_SCORE", "69", float, 0, 100, errors)
    cooldown = _number("COOLDOWN_MIN", "240", int, 20, 10080, errors)
    adaptive_max = _number("ADAPTIVE_MAX_TOTAL", "14", float, 0, 25, errors)
    adaptive_ticker = _number("ADAPTIVE_TICKER_MAX", "10", float, 0, 15, errors)
    adaptive_hour = _number("ADAPTIVE_HOUR_MAX", "5", float, 0, 10, errors)
    adaptive_lane = _number("ADAPTIVE_LANE_MAX", "2.5", float, 0, 6, errors)
    adaptive_explore = _number("ADAPTIVE_EXPLORATION_MAX", "2.5", float, 0, 5, errors)
    adaptive_saturation = _number("ADAPTIVE_SATURATION_MAX", "5", float, 0, 10, errors)
    w2e_proxy_bonus = _number("W2E_PROXY_MAX_BONUS", "5", float, 0, 10, errors)
    w2e_proxy_penalty = _number("W2E_PROXY_MAX_PENALTY", "3", float, 0, 10, errors)
    orca_retries = _number("ORCAROUTER_RETRIES", "1", int, 1, 6, errors)
    openrouter_retries = _number("OPENROUTER_RETRIES", "2", int, 1, 6, errors)
    ai_retries = _number("AI_RETRIES", "2", int, 1, 6, errors)
    event_ai_retries = _number("EVENT_AI_RETRIES", "2", int, 1, 6, errors)
    min_valid_ai = _number("MIN_VALID_AI_DRAFTS", "1", int, 1, 6, errors)
    event_min_valid_ai = _number("EVENT_MIN_VALID_AI_DRAFTS", "1", int, 1, 6, errors)
    outcome_gap = _number("OUTCOME_MIN_FOLLOWUP_GAP_MIN", "45", float, 20, 720, errors)
    outcome_pending = _number("OUTCOME_PENDING_ENTRY_HOURS", "18", float, 2, 168, errors)
    outcome_max_age = _number("OUTCOME_MAX_AGE_HOURS", "72", float, 4, 336, errors)
    outcome_max_followups = _number("OUTCOME_MAX_FOLLOWUPS_PER_TRADE", "2", int, 1, 3, errors)

    if post_min is not None and post_max is not None and post_min >= post_max:
        errors.append("POST_MIN_CHARS должен быть меньше POST_MAX_CHARS")
    if None not in (hot_w2e, soft_w2e, min_w2e) and not (hot_w2e <= soft_w2e <= min_w2e):
        errors.append("W2E thresholds: HOT <= SOFT <= MIN")
    if min_valid_ai != 1 or event_min_valid_ai != 1:
        warnings.append("Один валидный AI draft должен быть достаточен; runtime v11.8 принудительно ставит 1")
    if ai_retries != 2 or event_ai_retries != 2:
        warnings.append("v11.8 runtime использует два author pass для TRADE и EVENT")

    paths = {
        "POST_MEMORY_FILE": resolve_state_file("POST_MEMORY_FILE", "post_memory.json"),
        "PUBLISHED_HISTORY_FILE": resolve_state_file("PUBLISHED_HISTORY_FILE", "published_history.json"),
        "PUBLICATION_STATE_FILE": resolve_state_file("PUBLICATION_STATE_FILE", "publication_state.json"),
        "BOT_STATUS_FILE": resolve_state_file("BOT_STATUS_FILE", "status.json"),
        "RUN_LOCK_FILE": resolve_state_file("RUN_LOCK_FILE", "bot.lock"),
        "TRADE_JOURNAL_FILE": resolve_state_file("TRADE_JOURNAL_FILE", "trade_journal.json"),
        "LOG_FILE": resolve_project_file("LOG_FILE", "logs/bot.log"),
    }
    for label, path in paths.items():
        _writable(label, path, errors)

    guard = PublicationGuard(path=paths["PUBLICATION_STATE_FILE"])
    if os.getenv("PUBLISH_WINDOWS", "").strip() and not guard.windows:
        errors.append("PUBLISH_WINDOWS: не удалось распознать HH:MM-HH:MM")

    if content_mode != "deterministic" and not ai_key:
        warnings.append("AI-режим выбран без OrcaRouter/OpenRouter/Mistral ключей")
    if content_mode != "deterministic" and not openrouter_key:
        warnings.append("OPENROUTER_API_KEY не задан: бесплатная multi-model fallback цепочка недоступна")
    if not publish_images and media_mode != "none":
        warnings.append("PUBLISH_IMAGES=0: режим медиа будет проигнорирован")

    avatar_raw = (os.getenv("OUTCOME_AVATAR_PATH") or "assets/pozitivehero_avatar.png").strip()
    avatar_path = Path(avatar_raw).expanduser()
    if not avatar_path.is_absolute():
        avatar_path = PROJECT_DIR / avatar_path
    if outcome_enabled and not avatar_path.is_file():
        warnings.append(f"Outcome Engine: avatar не найден ({avatar_path}); follow-up сможет выйти без карточки")
    if outcome_max_age is not None and outcome_pending is not None and outcome_max_age < outcome_pending:
        errors.append("OUTCOME_MAX_AGE_HOURS должен быть >= OUTCOME_PENDING_ENTRY_HOURS")
    if cooldown is not None and min_interval is not None and cooldown < min_interval:
        warnings.append("COOLDOWN_MIN меньше глобального интервала")
    if not dry_run and not square_key:
        errors.append("DRY_RUN=0, но ключ Binance Square не задан")
    if not dry_run and not skill_dir:
        errors.append("DRY_RUN=0, но square-post skill не найден")
    if args.publishing:
        if not square_key:
            errors.append("Не задан SQUARE_API или BINANCE_SQUARE_OPENAPI_KEY")
        if not skill_dir:
            errors.append("Не найден установленный Binance square-post skill")

    providers = []
    if orca_key:
        providers.append("DeepSeek/Orca")
    if openrouter_key:
        providers.append(f"OpenRouter[{len(configured_openrouter_models())} models]")
    if mistral_key:
        providers.append("Mistral")
    provider_chain = " -> ".join(providers) if providers else "deterministic only"

    print("CONFIGURATION")
    print(f"  project={PROJECT_DIR}")
    print(f"  cron command=python {PROJECT_DIR / 'run_bot.py'}")
    print(f"  CONTENT_MODE={content_mode} | AI chain={provider_chain}")
    print(
        f"  retries: ORCA={orca_retries} OPENROUTER={openrouter_retries} "
        f"TRADE_AUTHOR={ai_retries} EVENT_AUTHOR={event_ai_retries} | min-valid={min_valid_ai}/{event_min_valid_ai}"
    )
    print(f"  AUTHOR_VOICE={author_voice} | ALLOW_TECHNICAL_FORMATS={int(allow_technical)}")
    print(
        f"  POST_VARIANTS={post_variants} | MIN_POST_QUALITY={min_quality} | MIN_FEED_APPEAL={min_feed} | "
        f"MIN_CONVERSION_INTENT={min_conversion} | MAX_POST_SIMILARITY={max_similarity}"
    )
    print(
        f"  W2E={min_w2e} | soft={soft_w2e} | hot={hot_w2e} | opportunity={min_opportunity} | demand={min_demand}"
    )
    print(
        f"  EVENT score={min_event} | W2E={event_w2e} | demand={event_demand} | lane_advantage={event_advantage} | "
        f"copy={event_min_quality}/{event_min_feed}/{event_min_conversion}"
    )
    print(
        f"  PUBLIC_PLAN_RR={min_public_rr} | TP3_RR={min_tp3_rr} | MAX_PUBLIC_RISK={max_public_risk}% | "
        f"near={decision_near_atr}ATR/{decision_near_pct}% | stop_buffer={stop_buffer_atr}ATR"
    )
    print(f"  EMOJI_RATE={emoji_rate} | QUESTION_EVERY={question_every}")
    print(
        f"  ENABLE_PACING_LIMITS={int(enable_pacing)} | MIN_GLOBAL_INTERVAL_MIN={min_interval} | MAX_POSTS_PER_DAY={max_daily} | "
        f"ENABLE_REACH_GATE={int(enable_reach_gate)} | MIN_REACH_SCORE={min_reach} | COOLDOWN_MIN={cooldown}"
    )
    print(
        f"  ADAPTIVE enabled={int(_bool('ENABLE_ADAPTIVE_RANKING', '1'))} | learning_only={int(_bool('LEARNING_ONLY', '0'))} | "
        f"max={adaptive_max} ticker={adaptive_ticker} hour={adaptive_hour} lane={adaptive_lane} explore={adaptive_explore} "
        f"saturation={adaptive_saturation} | W2E proxy={w2e_proxy_bonus}/-{w2e_proxy_penalty}"
    )
    print(f"  PUBLISH_MEDIA_MODE={media_mode} | PUBLISH_IMAGES={int(publish_images)}")
    print(
        f"  OUTCOME_ENGINE={int(outcome_enabled)} | gap={outcome_gap}m | pending={outcome_pending}h | "
        f"max_age={outcome_max_age}h | max_followups={outcome_max_followups}"
    )
    print(f"  DRY_RUN={int(dry_run)} | Square key={'yes' if square_key else 'no'} | skill={'found' if skill_dir else 'not found'}")
    for label, path in paths.items():
        print(f"  {label}={path}")
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
