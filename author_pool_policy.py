"""Production author-pool policy for Binance Square.

Invariant: deterministic copy is an outage safety net, never a co-equal
competitor. If at least one AI-authored draft survives factual validation, only
AI drafts are allowed into final ranking. A single valid AI draft is enough;
quality/appeal/conversion/reach gates still decide whether it may publish.
"""
from __future__ import annotations

from dataclasses import replace
from functools import wraps
import logging

logger = logging.getLogger(__name__)


def _is_ai(draft) -> bool:
    return not str(getattr(draft, "source", "") or "").lower().startswith("deterministic")


def _truthful_event_source(draft):
    """Normalize OpenRouter EVENT metadata without changing the post text."""
    style_id = str(getattr(draft, "style_id", "") or "").lower()
    source = str(getattr(draft, "source", "") or "").lower()
    if style_id.startswith("openrouter_free_event_") and source == "mistral_event":
        try:
            return replace(draft, source="openrouter_event")
        except TypeError:
            try:
                draft.source = "openrouter_event"
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


def install_author_pool_policy() -> None:
    """Install one consistent author policy for TRADE and EVENT before main import."""
    import writer
    import event_writer

    # One valid AI draft is sufficient because later ranking still enforces all
    # factual, quality, appeal, conversion, similarity and reach requirements.
    writer.MIN_VALID_AI_DRAFTS = 1
    event_writer.EVENT_MIN_VALID_AI_DRAFTS = 1

    # A second author pass helps when a free model returns parseable but unusable
    # prose. Provider-level retries remain bounded independently.
    writer.AI_RETRIES = max(2, int(writer.AI_RETRIES))
    event_writer.EVENT_AI_RETRIES = max(2, int(event_writer.EVENT_AI_RETRIES))

    # Deterministic templates must never compete with an accepted AI draft.
    writer.DETERMINISTIC_COMPARE_SLOTS = 0
    event_writer.EVENT_DETERMINISTIC_COMPARE_SLOTS = 0

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
        "Author pool policy active: AI min-valid=1, author retries trade=%s event=%s, deterministic competes only when AI pool is empty",
        writer.AI_RETRIES,
        event_writer.EVENT_AI_RETRIES,
    )
