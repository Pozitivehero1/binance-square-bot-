"""Production author-pool and EVENT resilience policy.

Invariants:
- deterministic copy is an outage safety net, never a co-equal competitor;
- one valid AI draft is enough for TRADE or EVENT;
- provider metadata must describe what actually wrote the final prose;
- weak free-model EVENT replies are repaired only when meaningful AI prose
  survives; a fully stripped/reconstructed reply is never masqueraded as AI.
"""
from __future__ import annotations

from dataclasses import replace
from functools import wraps
import logging
import re
from typing import Any, Dict, Iterable, Optional

logger = logging.getLogger(__name__)

_EMOJI_RE = re.compile(r"[\U0001F300-\U0001FAFF\u2600-\u27BF]")
_CASHTAG_RE = re.compile(r"\$[A-Za-z][A-Za-z0-9]{0,19}")
_HASHTAG_RE = re.compile(r"#[A-Za-zА-Яа-я0-9_]+")
_NUMBER_RE = re.compile(r"(?<![A-Za-zА-Яа-яЁё])[-+]?\d+(?:[.,]\d+)?%?")
_PLAN_LINE_RE = re.compile(
    r"(?iu)(?:\b(?:long|short|лонг|шорт)\b|\b(?:tp[123]|stop(?:-loss)?|sl)\b|"
    r"\b(?:вход\w*|стоп\w*|цел\w*|тейк\w*|фиксац\w*)\b)"
)
_TRADE_ACTION_RE = re.compile(
    r"(?iu)\b(?:покупаю|продаю|вхожу|открываю\s+позици\w*|лонгую|шорчу)\b"
)
_ROBOTIC_FRAGMENTS = (
    "semantic_package", "optional_trade_plan", "json_shape", "directional_bias",
    "направление у идеи", "граница ошибки", "диапазон контроля", "параметры сценария",
    "карта исполнения", "правило исполнения", "что вижу сейчас", "факты для выбора",
)
_UNSAFE_FRAGMENTS = (
    "гарант", "без риска", "точно выраст", "точно упад", "точно пойд",
    "инсайд", "киты покуп", "киты прода", "памп неизбеж", "срочно покуп",
    "срочно прода", "поставь лайк", "оставь комментар", "подпиш",
)
_SAFE_EVENT_FILLERS = (
    "Мне здесь важнее качество самой реакции, чем желание немедленно превратить движение в сигнал.",
    "Пока это наблюдение: без чистой структуры я не пытаюсь выжать сделку из одного всплеска активности.",
    "Если интерес быстро исчезнет, сам импульс для меня ничего не доказывает; если сохранится — график останется в наблюдении.",
)


def _is_ai(draft) -> bool:
    return not str(getattr(draft, "source", "") or "").lower().startswith("deterministic")


def _truthful_event_source(draft):
    """Normalize EVENT writer_source from the provider embedded in style_id."""
    style_id = str(getattr(draft, "style_id", "") or "").lower()
    desired = ""
    if style_id.startswith("openrouter_free_repaired_event_"):
        desired = "openrouter_event_repaired"
    elif style_id.startswith("openrouter_free_event_"):
        desired = "openrouter_event"
    elif style_id.startswith("deepseek_v4_pro_repaired_event_"):
        desired = "deepseek_event_repaired"
    elif style_id.startswith("deepseek_v4_pro_event_"):
        desired = "deepseek_event"
    elif style_id.startswith("mistral_repaired_event_"):
        desired = "mistral_event_repaired"
    elif style_id.startswith("mistral_event_"):
        desired = "mistral_event"

    if not desired or str(getattr(draft, "source", "") or "").lower() == desired:
        return draft
    try:
        return replace(draft, source=desired)
    except TypeError:
        try:
            draft.source = desired
        except Exception:
            pass
        return draft


def _ai_authoritative(drafts, lane: str):
    rows = list(drafts or [])
    if lane == "EVENT":
        rows = [_truthful_event_source(row) for row in rows]
    ai_rows = [row for row in rows if _is_ai(row)]
    if ai_rows:
        dropped = len(rows) - len(ai_rows)
        if dropped:
            logger.info(
                "%s author pool: %s valid AI draft(s); removed %s deterministic competitor(s)",
                lane, len(ai_rows), dropped,
            )
        else:
            logger.info("%s author pool: %s valid AI draft(s); deterministic fallback not needed", lane, len(ai_rows))
        return ai_rows
    logger.warning("%s author pool: zero valid AI drafts; deterministic outage fallback may be considered", lane)
    return rows


def _text_has_meaningful_ai_residue(text: str, ticker: str) -> bool:
    stripped = str(text or "").replace(ticker, " ")
    words = re.findall(r"[A-Za-zА-Яа-яЁё]{3,}", stripped)
    letters = re.sub(r"[^A-Za-zА-Яа-яЁё]", "", stripped)
    return len(words) >= 7 and len(letters) >= 48


def _normalize_event_headline(text: str, ticker: str) -> str:
    parts = [part.strip() for part in re.split(r"\n+", str(text or "")) if part.strip()]
    if not parts:
        return ""
    headline = parts[0]
    # Remove hallucinated cashtags and keep the target exactly once in headline.
    headline = _CASHTAG_RE.sub(lambda m: ticker if m.group(0).upper() == ticker.upper() else "", headline)
    headline = re.sub(r"\s{2,}", " ", headline).strip(" —-:;,. ")
    if ticker.lower() not in headline.lower():
        headline = f"{ticker} — {headline}" if headline else f"{ticker} — рынок снова привлёк внимание"
    body = "\n\n".join(parts[1:])
    if body:
        body = re.sub(re.escape(ticker), "эта монета", body, flags=re.IGNORECASE)
        body = _CASHTAG_RE.sub("", body)
        body = re.sub(r"[ \t]{2,}", " ", body)
        return f"{headline}\n\n{body}".strip()
    return headline


def _repair_event_narrative(raw_text: str, *, ticker: str, plan_available: bool) -> Optional[str]:
    """Return safe AI-derived narrative, or None when no AI prose survives.

    We deliberately remove model-authored numbers and trade-plan rows. For a
    plan-valid EVENT the canonical Python plan is appended later by event_writer.
    For observation-only EVENT no trade action is allowed at all.
    """
    source = re.sub(r"```(?:json)?|```", "", str(raw_text or ""), flags=re.IGNORECASE)
    source = _HASHTAG_RE.sub("", source)
    source = _EMOJI_RE.sub("", source)
    source = re.sub(r"\r\n?", "\n", source)

    kept: list[str] = []
    for raw_line in source.splitlines():
        line = re.sub(r"[ \t]+", " ", raw_line).strip()
        if not line:
            continue
        lowered = line.lower().replace("ё", "е")
        if any(fragment in lowered for fragment in _ROBOTIC_FRAGMENTS):
            continue
        if any(fragment in lowered for fragment in _UNSAFE_FRAGMENTS):
            continue
        if _PLAN_LINE_RE.search(line):
            continue
        if not plan_available and _TRADE_ACTION_RE.search(line):
            continue
        # Numeric market claims from a free model are not trusted during repair.
        # The clean path still preserves exact package numbers when the original
        # candidate already passes validation.
        if _NUMBER_RE.search(line):
            continue
        kept.append(line)

    narrative = "\n\n".join(kept).strip()
    narrative = _normalize_event_headline(narrative, ticker)
    if not narrative or not _text_has_meaningful_ai_residue(narrative, ticker):
        return None

    # Add only neutral Python-owned connective prose when the surviving AI text
    # is too short for the feed contract. This is explicitly labelled repaired.
    for filler in _SAFE_EVENT_FILLERS:
        if len(narrative) >= 235:
            break
        if filler.lower() not in narrative.lower():
            narrative = f"{narrative}\n\n{filler}".strip()
    if len(narrative) > 390:
        paragraphs = [p.strip() for p in narrative.split("\n\n") if p.strip()]
        out: list[str] = []
        for paragraph in paragraphs:
            candidate = "\n\n".join([*out, paragraph]) if out else paragraph
            if len(candidate) > 390:
                break
            out.append(paragraph)
        narrative = "\n\n".join(out).strip()
    return narrative or None


def _float_value(value: Any) -> float:
    return float(str(value).replace(",", ".").replace("%", "").strip())


def _package_levels(package: Dict[str, Any]) -> Optional[Dict[str, float]]:
    plan = package.get("optional_trade_plan") if isinstance(package.get("optional_trade_plan"), dict) else {}
    if not plan.get("available"):
        return None
    try:
        zone = plan.get("entry_zone") or []
        entry = _float_value(plan.get("entry"))
        return {
            "plan_valid": True,
            "plan_entry": entry,
            "entry": entry,
            "entry_zone_low": _float_value(zone[0]),
            "entry_zone_high": _float_value(zone[1]),
            "stop": _float_value(plan.get("stop_loss")),
            "tp1": _float_value(plan.get("tp1")),
            "tp2": _float_value(plan.get("tp2")),
            "tp3": _float_value(plan.get("tp3")),
        }
    except (TypeError, ValueError, IndexError):
        return None


def _event_candidate_validation_text(text: str, package: Dict[str, Any]) -> str:
    """Mirror event_writer's canonical-plan append for pre-validation."""
    import event_writer

    plan = package.get("optional_trade_plan") if isinstance(package.get("optional_trade_plan"), dict) else {}
    levels = _package_levels(package)
    if not plan.get("available") or levels is None:
        return str(text or "").strip()
    direction = str(plan.get("directional_bias") or "long").lower()
    return event_writer._enforce_full_plan_block(str(text or "").strip(), levels, direction, seed="event-resilience")


def _event_row_is_valid(row: Dict[str, Any], package: Dict[str, Any]) -> tuple[bool, tuple[str, ...]]:
    import event_writer

    market = package.get("market_event") if isinstance(package.get("market_event"), dict) else {}
    plan = package.get("optional_trade_plan") if isinstance(package.get("optional_trade_plan"), dict) else {}
    ticker = str(market.get("ticker") or "").strip().upper()
    basic = ticker.lstrip("$")
    direction = str(plan.get("directional_bias") or "long").lower()
    if not basic:
        return False, ("missing ticker in semantic package",)
    candidate = _event_candidate_validation_text(str(row.get("text") or ""), package)
    return event_writer._validate_event_post(candidate, basic=basic, direction=direction, package=package)


def _repair_event_rows(rows: Iterable[dict], package: Dict[str, Any], formats: Iterable[str]) -> list[dict]:
    """Make free-model EVENT output usable without weakening factual validation."""
    allowed_formats = {str(item) for item in formats}
    market = package.get("market_event") if isinstance(package.get("market_event"), dict) else {}
    plan = package.get("optional_trade_plan") if isinstance(package.get("optional_trade_plan"), dict) else {}
    ticker = str(market.get("ticker") or "").strip().upper()
    plan_available = bool(plan.get("available"))
    out: list[dict] = []

    for raw in rows or []:
        if not isinstance(raw, dict):
            continue
        fmt = str(raw.get("format_id") or "").strip()
        if fmt not in allowed_formats:
            logger.info("EVENT AI candidate dropped: unknown/unrequested format=%s", fmt or "<empty>")
            continue
        clean_row = dict(raw)
        clean_row["text"] = re.sub(r"\n{3,}", "\n\n", str(raw.get("text") or "").strip())
        valid, reasons = _event_row_is_valid(clean_row, package)
        if valid:
            out.append(clean_row)
            continue

        repaired = _repair_event_narrative(clean_row["text"], ticker=ticker, plan_available=plan_available)
        if repaired is None:
            logger.info("EVENT AI candidate dropped after repair: %s", "; ".join(reasons))
            continue
        repaired_row = dict(clean_row)
        repaired_row["text"] = repaired
        provider = str(repaired_row.get("_provider") or "ai").strip()
        if not provider.endswith("_repaired"):
            repaired_row["_provider"] = provider + "_repaired"
        valid2, reasons2 = _event_row_is_valid(repaired_row, package)
        if valid2:
            logger.info(
                "EVENT AI candidate repaired provider=%s format=%s chars=%s",
                repaired_row.get("_provider"), fmt, len(_event_candidate_validation_text(repaired, package)),
            )
            out.append(repaired_row)
        else:
            logger.info("EVENT AI candidate still invalid after repair %s: %s", fmt, "; ".join(reasons2))
    return out


def install_author_pool_policy() -> None:
    """Install one consistent author policy for TRADE and EVENT before main import."""
    import writer
    import event_writer

    writer.MIN_VALID_AI_DRAFTS = 1
    event_writer.EVENT_MIN_VALID_AI_DRAFTS = 1
    writer.AI_RETRIES = max(2, int(writer.AI_RETRIES))
    event_writer.EVENT_AI_RETRIES = max(2, int(event_writer.EVENT_AI_RETRIES))
    writer.DETERMINISTIC_COMPARE_SLOTS = 0
    event_writer.EVENT_DETERMINISTIC_COMPARE_SLOTS = 0

    if not getattr(event_writer._request_ai_candidates, "_event_resilience", False):
        original_event_request = event_writer._request_ai_candidates

        @wraps(original_event_request)
        def event_request(*args, **kwargs):
            rows = original_event_request(*args, **kwargs)
            package = kwargs.get("package") if isinstance(kwargs.get("package"), dict) else {}
            formats = kwargs.get("formats") or []
            return _repair_event_rows(rows, package, formats)

        event_request._event_resilience = True  # type: ignore[attr-defined]
        event_writer._request_ai_candidates = event_request

    if not getattr(writer.generate_post_candidates, "_ai_authoritative_pool", False):
        original_trade = writer.generate_post_candidates

        @wraps(original_trade)
        def trade_generate(*args, **kwargs):
            return _ai_authoritative(original_trade(*args, **kwargs), "TRADE")

        trade_generate._ai_authoritative_pool = True  # type: ignore[attr-defined]
        writer.generate_post_candidates = trade_generate

    if not getattr(event_writer.generate_event_candidates, "_ai_authoritative_pool", False):
        original_event = event_writer.generate_event_candidates

        @wraps(original_event)
        def event_generate(*args, **kwargs):
            return _ai_authoritative(original_event(*args, **kwargs), "EVENT")

        event_generate._ai_authoritative_pool = True  # type: ignore[attr-defined]
        event_writer.generate_event_candidates = event_generate

    logger.info(
        "Author policy active: min-valid=1; retries trade=%s event=%s; EVENT repair=yes; deterministic only when AI pool is empty",
        writer.AI_RETRIES,
        event_writer.EVENT_AI_RETRIES,
    )


def verify_author_policy() -> None:
    """Fail fast if startup patch ordering silently disables a production policy."""
    import writer
    import event_writer

    checks = {
        "trade-authoritative-pool": getattr(writer.generate_post_candidates, "_ai_authoritative_pool", False),
        "event-authoritative-pool": getattr(event_writer.generate_event_candidates, "_ai_authoritative_pool", False),
        "event-resilience": getattr(event_writer._request_ai_candidates, "_event_resilience", False),
        "trade-min-valid": int(writer.MIN_VALID_AI_DRAFTS) == 1,
        "event-min-valid": int(event_writer.EVENT_MIN_VALID_AI_DRAFTS) == 1,
        "trade-no-deterministic-competition": int(writer.DETERMINISTIC_COMPARE_SLOTS) == 0,
        "event-no-deterministic-competition": int(event_writer.EVENT_DETERMINISTIC_COMPARE_SLOTS) == 0,
    }
    failed = [name for name, ok in checks.items() if not ok]
    if failed:
        raise RuntimeError("author policy startup invariant failed: " + ", ".join(failed))
