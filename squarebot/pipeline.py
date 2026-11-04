"""Discover → choose topics → author → validate → send once → measure."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
import logging
import os
from pathlib import Path
import tempfile

from runtime import ProcessLock, atomic_write_json, resolve_state_file, write_status
from publisher import find_skill_dir, publish

from . import VERSION
from .author import Author, configured_providers
from .models import Settings, utcnow
from .store import Store, similarity
from .validation import validate
from . import market, news, visuals

LOG = logging.getLogger(__name__)


def shortlist(stories, store, recent, performance):
    from .metrics import ranking_lift
    ranked = []
    pending_symbols = {symbol for row in store.data["pending"].values()
                       for symbol in row.get("story", {}).get("symbols", [])}
    # Retain legacy unresolved sends even during migration to the new engine.
    from publication_intent import load_intents
    pending_symbols |= {symbol for row in load_intents().values() if row.get("status") == "pending"
                        for symbol in row.get("symbols", [])}
    for story in stories:
        if store.covered(story) or pending_symbols.intersection(story.symbols):
            continue
        if story.kind == "news" and any(
            previous.get("story", {}).get("kind") == "news" and
            similarity(story.headline, previous.get("story", {}).get("headline", "")) >= .6
            for previous in recent):
            continue
        kind_count = sum(p.get("story", {}).get("kind") == story.kind for p in recent[:10])
        ticker_count = sum(any("$"+s in p.get("text", "") for s in story.symbols) for p in recent[:6])
        score = story.score - kind_count*5 - ticker_count*3 + ranking_lift(story, performance)
        ranked.append((score, story))
    ranked.sort(key=lambda item: (-item[0], item[1].id))
    # More distinct topics in the prompt, fewer redundant drafts of one tiny move.
    chosen, counts = [], {}
    for _, story in ranked:
        if counts.get(story.kind, 0) >= 2:
            continue
        counts[story.kind] = counts.get(story.kind, 0)+1
        chosen.append(story)
        if len(chosen) == 8:
            break
    return chosen


def record_analytics(store):
    """Idempotent recovery if a process died after publication but before analytics."""
    from performance_store import record_publication, load_store, save_store
    from publication_guard import PublicationGuard
    guard = PublicationGuard()
    for row in store.data["posts"]:
        if row.get("analytics_recorded"):
            continue
        story, draft = row["story"], row["draft"]
        symbol = story["symbols"][0]
        visual = row.get("visual_style", "none")
        record_publication(post_id=row["post_id"], symbol=symbol,
                           market_symbol=story.get("chart_symbol") or symbol+"USDT",
                           text=row["text"], lane="NEWS" if story["kind"] == "news" else "EVENT",
                           direction="OBSERVATION", content_format=draft["format"], visual_style=visual,
                           event_class=story["kind"], writer_source=draft["provider"]+"/"+draft["model"],
                           fact_package=story)
        # Keep source send time when recovering an earlier confirmed receipt.
        analytics = load_store()
        analytics["posts"][row["post_id"]]["published_at"] = row.get("created_at") or row["published_at"]
        analytics["posts"][row["post_id"]]["engine_version"] = VERSION
        save_store(analytics)
        if not any(r.get("post_id") == row["post_id"] for r in guard.state.get("publications", [])):
            guard.record_success(symbol=symbol, direction="OBSERVATION", content_format=draft["format"],
                                     visual_style=visual, market_score=story["score"], quality_score=0,
                                     reach_score=0, post_id=row["post_id"])
        row["analytics_recorded"] = True
        store.save()


def run(settings=None):
    settings = settings or Settings.from_env()
    os.environ["BOT_VERSION"] = VERSION
    with ProcessLock() as lock:
        if not lock.acquired:
            write_status("locked", "Another editorial pass is running")
            return 0
        return editorial_pass(settings)


def editorial_pass(settings):
    report = {"version": VERSION, "started_at": utcnow().isoformat(), "dry_run": settings.dry_run,
              "source_errors": {}, "rejected": [], "candidates": []}
    def finish(status, detail, code=0, **extra):
        report.update(status=status, detail=detail, completed_at=utcnow().isoformat(), **extra)
        atomic_write_json(resolve_state_file("EDITOR_REPORT_FILE", "editorial_report.json"), report)
        write_status(status, detail, engine_version=VERSION, **extra)
        LOG.info("Editorial result=%s detail=%s", status, detail)
        return code

    providers = configured_providers()
    if not providers:
        return finish("failed", "No AI author configured", 1)
    if not settings.dry_run and (not find_skill_dir() or not (os.getenv("SQUARE_API") or os.getenv("BINANCE_SQUARE_OPENAPI_KEY"))):
        return finish("failed", "Square publisher or API key is missing", 1)
    store = Store()
    if not settings.dry_run:
        store.reconcile()
        record_analytics(store)
    recent = store.recent()
    from performance_store import load_store
    performance = list(load_store().get("posts", {}).values())
    stories = []
    with ThreadPoolExecutor(max_workers=2) as pool:
        work = {"market": pool.submit(market.scan, settings)}
        if settings.enable_news:
            work["news"] = pool.submit(news.scan)
        for name, future in work.items():
            try:
                stories.extend(future.result())
            except Exception as exc:
                report["source_errors"][name] = type(exc).__name__
                LOG.warning("Source unavailable name=%s error=%s", name, type(exc).__name__)
    if not stories:
        return finish("failed", "No current source facts available", 1)
    selected = shortlist(stories, store, recent, performance)
    report["candidates"] = [s.brief() for s in selected]
    if not selected:
        return finish("skipped", "All source events are already covered or have unresolved sends")
    by_id = {s.id: s for s in selected}
    author = Author(settings, providers)
    generator = author.drafts(selected, recent)
    feedback = None
    best = None
    try:
        while True:
            drafts = next(generator) if feedback is None else generator.send(feedback)
            feedback = []
            for draft in drafts:
                story = by_id.get(draft.story_id)
                if not story:
                    feedback.append({"story_id": draft.story_id, "reasons": ["unknown-story-id"]})
                    continue
                text, reasons = validate(draft, story, recent)
                if reasons:
                    row = {"story_id": draft.story_id, "provider": draft.provider, "reasons": list(reasons),
                           "text": draft.text[:1800], "evidence_quote": draft.evidence_quote[:600]}
                    report["rejected"].append(row)
                    feedback.append(row)
                    LOG.info("Draft factual/repetition rejection story=%s reasons=%s", story.id, ", ".join(reasons))
                    continue
                draft.text = text
                best = (story, draft)
                break
            if best:
                break
    except StopIteration:
        pass
    finally:
        generator.close()
        report["ai_calls"] = author.calls
        report["providers"] = author.events
    if not best:
        return finish("failed", "AI chain exhausted without a factual, distinct draft; inspect editorial_report.json", 1)
    story, draft = best
    report["chosen"] = {"story": story.brief(), "draft": asdict(draft)}
    if settings.dry_run:
        LOG.info("DRY RUN provider=%s story=%s\n%s", draft.provider, story.kind, draft.text)
        return finish("dry_run", "Draft validated; no send attempted", story_id=story.id, symbol=story.symbols[0])
    # A market draft must still describe fresh candles after slow model fallbacks.
    if story.kind != "news":
        from evidence_metrics import parse_time
        observed = parse_time(story.observed_at)
        if not observed or (utcnow()-observed).total_seconds() > 10*60:
            return finish("skipped", "Market facts aged during generation; next cron will refresh them")
    with tempfile.TemporaryDirectory() as directory:
        directory = Path(directory)
        if story.kind == "news":
            image = news.cover(story, directory)
        else:
            image = visuals.chart(story, directory)
        # Articles use an actual source cover. A missing cover is a short news post,
        # rather than silently suppressing every text-only RSS story.
        article_title = draft.title if story.kind == "news" and image else ""
        store.reserve(story, draft)
        result = publish(draft.text, image_path=image, article_title=article_title)
        if not result:
            return finish("failed", "Publication unconfirmed; story reserved to prevent a rewritten resend", 1,
                          story_id=story.id, symbol=story.symbols[0])
        row = store.confirm(story.id, result.post_id)
        row["visual_style"] = "rss_cover" if story.kind == "news" and image else "market_chart" if image else "none"
        store.save()
    try:
        record_analytics(store)
    except Exception as exc:
        # Sending succeeded. Retry only tracking on next run, never the post.
        report["analytics_error"] = type(exc).__name__
        LOG.exception("Confirmed post awaits analytics repair")
    return finish("published", "AI-authored story confirmed by Square", post_id=result.post_id,
                  story_id=story.id, symbol=story.symbols[0], lane="NEWS" if story.kind == "news" else "EVENT")
