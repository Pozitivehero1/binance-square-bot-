"""Resilience patch for EVENT AI authoring.

A single valid AI draft is better than replacing the whole pool with
provider-outage deterministic templates.  Keep strict event validation/ranking,
but allow one valid AI draft to constitute a usable pool and give the event
author one extra generation attempt when a free provider returns too few rows.
"""
from __future__ import annotations

from dataclasses import replace
import logging

logger = logging.getLogger(__name__)

_ORIGINAL_GENERATE = None


def _normalize_sources(drafts):
    """Preserve truthful writer_source for OpenRouter EVENT drafts."""
    out = []
    for draft in drafts:
        style_id = str(getattr(draft, "style_id", "") or "").lower()
        source = str(getattr(draft, "source", "") or "").lower()
        if style_id.startswith("openrouter_free_event_") and source == "mistral_event":
            try:
                draft = replace(draft, source="openrouter_event")
            except TypeError:
                # Tests or future draft implementations may be mutable rather
                # than dataclasses.  Prefer truthful metadata when possible.
                try:
                    draft.source = "openrouter_event"
                except Exception:
                    pass
        out.append(draft)
    return out


def _generate_event_candidates_resilient(*args, **kwargs):
    return _normalize_sources(_ORIGINAL_GENERATE(*args, **kwargs))


def install_event_ai_resilience() -> None:
    """Install the EVENT-only resilience policy before main imports its symbol."""
    global _ORIGINAL_GENERATE
    import event_writer

    # One structurally valid AI draft is enough to avoid deterministic outage
    # copy.  It still has to pass the normal quality, appeal, conversion,
    # similarity and reach gates later in the pipeline.
    event_writer.EVENT_MIN_VALID_AI_DRAFTS = 1

    # If the first successful free-provider response contains only one/zero
    # usable rows, make one fresh generation request.  Do not loop indefinitely.
    event_writer.EVENT_AI_RETRIES = max(2, int(event_writer.EVENT_AI_RETRIES))

    if _ORIGINAL_GENERATE is None:
        _ORIGINAL_GENERATE = event_writer.generate_event_candidates
        event_writer.generate_event_candidates = _generate_event_candidates_resilient

    logger.info(
        "EVENT AI resilience active: min_valid_ai_drafts=1, generation_retries=%s, truthful OpenRouter source",
        event_writer.EVENT_AI_RETRIES,
    )
