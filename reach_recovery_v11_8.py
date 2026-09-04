"""v11.8 distribution-recovery policy.

The market engine stays authoritative. This layer watches the account's initial
30m distribution and 30m->2h expansion, keeps deterministic outage copy from
flooding a depressed account, and hardens the TRADE AI handoff without allowing
models to own public Entry/SL/TP numbers.
"""
from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
import logging
import os
import re
from statistics import median
from typing import Optional

logger = logging.getLogger(__name__)

_ORIGINAL_RECOVERY_GATE = None
_ORIGINAL_WRITER_BUILD = None
_ORIGINAL_AI_REQUEST = None
_LAST_AI_PROVIDER = ""


def configure_environment() -> None:
    """Install one coherent v11.8 runtime configuration before imports."""
    os.environ["BOT_VERSION"] = "v11.8"
    os.environ["ADAPTIVE_MAX_TOTAL"] = "14"
    os.environ["ADAPTIVE_TICKER_MAX"] = "10"
    os.environ["ADAPTIVE_HOUR_MAX"] = "5"
    os.environ["ADAPTIVE_CONTENT_MAX_TOTAL"] = "9"
    os.environ["ADAPTIVE_FORMAT_MAX"] = "5"
    os.environ["ADAPTIVE_WRITER_MAX"] = "2.5"
    os.environ["ADAPTIVE_EVENT_CLASS_MAX"] = "2"
    os.environ["ADAPTIVE_DIRECTION_MAX"] = "1.5"

    # Provider retry and author retry are different things. Orca stays one-shot
    # because its current 503 is a capacity problem. Two author passes are kept
    # because OpenRouter may return valid JSON whose prose fails the local fact
    # lock; the second pass then rotates to another free-model batch.
    os.environ["ORCAROUTER_RETRIES"] = "1"
    os.environ["AI_RETRIES"] = "2"
    os.environ["EVENT_AI_RETRIES"] = "2"
    os.environ["DETERMINISTIC_COMPARE_SLOTS"] = "0"
    os.environ["EVENT_DETERMINISTIC_COMPARE_SLOTS"] = "0"

    os.environ["OUTCOME_POST_STOPS"] = "0"
    os.environ["OUTCOME_POST_PARTIAL_TARGETS"] = "0"


def _parse_dt(value: object) -> Optional[datetime]:
    try:
        dt = datetime.fromisoformat(str(value or ""))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except (TypeError, ValueError):
        return None


def distribution_health(now: Optional[datetime] = None) -> dict[str, float | int]:
    """Measure initial distribution and second-stage expansion."""
    from performance_store import load_store

    now = now or datetime.now(timezone.utc)
    early_cutoff = now - timedelta(hours=12)
    expansion_cutoff = now - timedelta(hours=18)
    baseline_cutoff = now - timedelta(days=7)

    recent30: list[float] = []
    base30: list[float] = []
    recent_expansion: list[float] = []
    base_expansion: list[float] = []

    for item in load_store().get("posts", {}).values():
        if not isinstance(item, dict) or not item.get("learning_eligible", True):
            continue
        published = _parse_dt(item.get("published_at"))
        if not published or published < baseline_cutoff or published > now:
            continue
        milestones = item.get("milestones") if isinstance(item.get("milestones"), dict) else {}
        row30 = milestones.get("30m")
        row2h = milestones.get("2h")

        views30 = 0.0
        if isinstance(row30, dict):
            try:
                views30 = float(row30.get("views", 0) or 0)
            except (TypeError, ValueError):
                views30 = 0.0
        if views30 > 0:
            (recent30 if published >= early_cutoff else base30).append(views30)

        if views30 <= 0 or not isinstance(row2h, dict):
            continue
        try:
            views2h = float(row2h.get("views", 0) or 0)
        except (TypeError, ValueError):
            continue
        if views2h <= 0:
            continue
        expansion = max(0.5, min(4.0, views2h / views30))
        (recent_expansion if published >= expansion_cutoff else base_expansion).append(expansion)

    recent30_med = float(median(recent30)) if recent30 else 0.0
    base30_med = float(median(base30)) if base30 else 0.0
    early_ratio = recent30_med / base30_med if recent30_med > 0 and base30_med > 0 else 1.0

    recent_exp_med = float(median(recent_expansion)) if recent_expansion else 0.0
    base_exp_med = float(median(base_expansion)) if base_expansion else 0.0
    expansion_ratio = recent_exp_med / base_exp_med if recent_exp_med > 0 and base_exp_med > 0 else 1.0

    return {
        "recent30": recent30_med,
        "baseline30": base30_med,
        "early_ratio": early_ratio,
        "early_n": len(recent30),
        "recent_expansion": recent_exp_med,
        "baseline_expansion": base_exp_med,
        "expansion_ratio": expansion_ratio,
        "expansion_n": len(recent_expansion),
    }


def evaluate_recovery_candidate_v118(*args, **kwargs):
    """Block weak outage copy and react to depressed distribution stages."""
    base = _ORIGINAL_RECOVERY_GATE(*args, **kwargs)

    source = str(kwargs.get("writer_source") or "").strip().lower()
    event = str(kwargs.get("event_class") or "ordinary").strip().lower()
    recovery_mode = bool(kwargs.get("recovery_mode", False))
    reach = float(kwargs.get("reach_score", 0.0) or 0.0)
    selection = float(kwargs.get("selection_score", 0.0) or 0.0)
    opportunity = float(kwargs.get("opportunity_score", 0.0) or 0.0)
    demand = float(kwargs.get("audience_demand", 0.0) or 0.0)
    attention = float(kwargs.get("attention_score", 0.0) or 0.0)
    micro = float(kwargs.get("micro_score", 0.0) or 0.0)

    health = distribution_health()
    early_n = int(health["early_n"])
    expansion_n = int(health["expansion_n"])
    early_ratio = float(health["early_ratio"])
    expansion_ratio = float(health["expansion_ratio"])
    initial_depressed = early_n >= 4 and early_ratio < 0.78
    expansion_depressed = expansion_n >= 4 and expansion_ratio < 0.80
    distribution_depressed = initial_depressed or expansion_depressed
    deterministic = source.startswith("deterministic")

    suffix = (
        f"; v11.8 30m={float(health['recent30']):.0f}/{float(health['baseline30']):.0f} "
        f"({early_ratio:.2f}, n={early_n}), "
        f"2h/30m={float(health['recent_expansion']):.2f}/{float(health['baseline_expansion']):.2f} "
        f"({expansion_ratio:.2f}, n={expansion_n})"
    )

    if deterministic and (recovery_mode or distribution_depressed):
        return replace(
            base,
            allowed=False,
            threshold=max(float(base.threshold), 82.0),
            reason="v11.8 provider-outage fallback blocked during reach recovery" + suffix,
        )
    if not base.allowed:
        return replace(base, reason=base.reason + suffix)

    strong_event = event in {"fresh_event", "audience_breakout", "high_demand_active"}
    activity = max(attention, micro)
    rescue_quality = (
        strong_event and reach >= 78.0 and selection >= 71.0 and opportunity >= 65.0
        and demand >= 62.0 and activity >= 58.0
    )
    exceptional = (
        strong_event and reach >= 83.0 and selection >= 76.0 and opportunity >= 70.0
        and demand >= 72.0 and activity >= 68.0
    )

    if distribution_depressed and not rescue_quality:
        stage = "initial" if initial_depressed else "expansion"
        return replace(
            base,
            allowed=False,
            threshold=max(float(base.threshold), 78.0),
            reason=f"v11.8 {stage}-distribution rescue block" + suffix,
        )
    if initial_depressed and expansion_depressed and not exceptional:
        return replace(
            base,
            allowed=False,
            threshold=max(float(base.threshold), 83.0),
            reason="v11.8 dual-stage distribution block" + suffix,
        )
    return replace(base, reason=base.reason + suffix)


def _track_ai_provider_v118(*args, **kwargs):
    """Remember provider for only the current TRADE author batch."""
    global _LAST_AI_PROVIDER
    _LAST_AI_PROVIDER = ""
    rows = _ORIGINAL_AI_REQUEST(*args, **kwargs)
    providers = {
        str(row.get("_provider") or "").strip().lower()
        for row in rows
        if isinstance(row, dict) and row.get("_provider")
    }
    _LAST_AI_PROVIDER = next(iter(providers)) if len(providers) == 1 else ""
    return rows


def _source_name_v118(source: str) -> str:
    raw = str(source or "").strip().lower()
    if _LAST_AI_PROVIDER == "openrouter_free" and raw == "mistral":
        return "openrouter"
    return raw


def _meaningful_ai_residue(text: str, ticker: str) -> bool:
    residue = str(text or "").replace(ticker, " ")
    words = re.findall(r"[A-Za-zА-Яа-яЁё]{3,}", residue)
    letters = re.sub(r"[^A-Za-zА-Яа-яЁё]", "", residue)
    return len(words) >= 7 and len(letters) >= 45


def _repair_ai_narrative_v118(
    raw_text: str, *, basic: str, direction: str, package: dict
) -> tuple[str, bool]:
    """Return (safe narrative, meaningful_ai_survived).

    A repaired candidate may use Python-owned connective prose, but it is still
    called AI only when meaningful model prose survived cleanup. If everything
    was stripped, return an empty narrative so deterministic analytics stay
    separate from AI analytics.
    """
    del package
    import writer

    text = re.sub(r"```(?:json|markdown|text)?", "", str(raw_text or ""), flags=re.IGNORECASE)
    text = re.sub(r"#[A-Za-zА-Яа-я0-9_]+", "", text)
    text = re.sub(r"[ \t]+", " ", text)
    lines = [line.strip(" -•\t") for line in text.splitlines() if line.strip()]

    opposite = ("short", "шорт") if direction == "long" else ("long", "лонг")
    plan_markers = re.compile(r"(?i)\b(?:tp\s*[123]|entry|stop(?:_loss)?|sl)\b|\b(?:вход|стоп|цель|цели)\b")
    kept: list[str] = []
    for line in lines:
        lowered = line.lower().replace("ё", "е")
        if plan_markers.search(line):
            continue
        if any(
            re.search(rf"(?i)(?<![A-Za-zА-Яа-я]){re.escape(token)}(?![A-Za-zА-Яа-я])", lowered)
            for token in opposite
        ):
            continue
        if writer._numeric_tokens(line):
            continue
        if any(item in lowered for item in writer._ROBOTIC):
            continue
        if any(re.search(pattern, lowered, flags=re.IGNORECASE) for pattern in writer._FORBIDDEN_PATTERNS):
            continue
        if any(re.search(pattern, lowered, flags=re.IGNORECASE) for pattern in writer._PREDICTIVE_PATTERNS):
            continue
        kept.append(line)

    ticker = writer._ticker(basic)
    if not kept:
        return "", False
    if ticker.lower() not in kept[0].lower():
        kept[0] = f"{ticker}: {kept[0]}"

    narrative = "\n\n".join(kept[:3]).strip()
    if not _meaningful_ai_residue(narrative, ticker):
        return "", False
    if len(narrative) > 235:
        narrative = narrative[:235].rstrip(" ,;:-") + "."
    if len(narrative) < 105:
        narrative += "\n\nМне важна реакция рынка у рабочей зоны: если сценарий не подтверждается, догонять движение не буду."
    return narrative, True


def _build_generated_v118(*args, **kwargs):
    """Repair rejected TRADE AI prose once without weakening the fact lock."""
    import writer

    source = _source_name_v118(str(kwargs.get("source") or ""))
    first_kwargs = dict(kwargs)
    first_kwargs["source"] = source
    generated = _ORIGINAL_WRITER_BUILD(*args, **first_kwargs)
    if generated is not None or source.startswith("deterministic"):
        return generated

    raw_text = str(kwargs.get("raw_text") or "")
    basic = str(kwargs.get("basic") or "")
    direction = str(kwargs.get("direction") or "")
    levels = kwargs.get("levels") or {}
    package = kwargs.get("package") or {}
    fmt = str(kwargs.get("format_id") or "")

    try:
        probe = writer._enforce_full_plan_block(raw_text, levels, direction, seed=f"probe|{source}|{fmt}")
        _, reasons = writer._validate_ai_post(
            probe, basic=basic, direction=direction, levels=levels, package=package, format_id=fmt,
        )
        logger.info("v11.8 AI draft rejected provider=%s format=%s reasons=%s", source, fmt, "; ".join(reasons))
    except Exception as exc:
        logger.info("v11.8 AI draft diagnostics provider=%s format=%s error=%s", source, fmt, exc)

    repaired, meaningful = _repair_ai_narrative_v118(
        raw_text, basic=basic, direction=direction, package=package
    )
    if not meaningful:
        logger.info(
            "v11.8 AI draft discarded provider=%s format=%s: no meaningful model prose survived fact-lock repair",
            source, fmt,
        )
        return None

    retry_kwargs = dict(first_kwargs)
    retry_kwargs["raw_text"] = repaired
    retry_kwargs["source"] = source if source.endswith("_repaired") else source + "_repaired"
    generated = _ORIGINAL_WRITER_BUILD(*args, **retry_kwargs)
    if generated is not None:
        logger.info("v11.8 repaired AI draft accepted provider=%s format=%s", retry_kwargs["source"], fmt)
    else:
        logger.info("v11.8 repaired AI draft still rejected provider=%s format=%s", retry_kwargs["source"], fmt)
    return generated


def prepare_originals() -> None:
    global _ORIGINAL_RECOVERY_GATE, _ORIGINAL_WRITER_BUILD, _ORIGINAL_AI_REQUEST
    if _ORIGINAL_RECOVERY_GATE is None:
        import recovery_guard
        _ORIGINAL_RECOVERY_GATE = recovery_guard.evaluate_recovery_candidate
    if _ORIGINAL_WRITER_BUILD is None or _ORIGINAL_AI_REQUEST is None:
        import writer
        _ORIGINAL_WRITER_BUILD = writer._build_generated
        _ORIGINAL_AI_REQUEST = writer._request_ai_candidates


def activate_reach_recovery() -> None:
    """Patch recovery policy and TRADE AI handoff; leave trade math stable."""
    prepare_originals()
    import recovery_guard
    import writer

    recovery_guard.evaluate_recovery_candidate = evaluate_recovery_candidate_v118
    writer._request_ai_candidates = _track_ai_provider_v118
    writer._build_generated = _build_generated_v118
    logger.info(
        "v11.8 distribution recovery active: conservative ranking, 30m/2h guard, truthful repaired-AI attribution"
    )
