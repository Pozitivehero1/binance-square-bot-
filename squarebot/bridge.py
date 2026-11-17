"""Collect evidence and deliver one ChatGPT draft through the external cron."""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import logging
import os
import re
import subprocess
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from io import BytesIO

import requests
from pathlib import Path

from evidence_metrics import parse_time
from runtime import atomic_write_json
from . import market, news, visuals
from .models import Draft, Settings, Story, utcnow
from .validation import validate

LOG = logging.getLogger(__name__)
DATA_BRANCH = "square-bridge-data"
MAX_DRAFT_BYTES = 950_000
MAX_IMAGE_BYTES = 650_000


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def collect(destination):
    settings = Settings.from_env()
    stories = []
    with ThreadPoolExecutor(max_workers=2) as pool:
        tasks = [pool.submit(market.scan, settings), pool.submit(news.scan)]
        for task in tasks:
            try:
                stories.extend(task.result())
            except (OSError, RuntimeError, ValueError, requests.RequestException):
                LOG.exception("Source scan failed")
        news_rows = sorted((s for s in stories if s.kind == "news"), key=lambda s: -s.score)[:5]
    market_rows = sorted((s for s in stories if s.kind != "news"), key=lambda s: -s.score)
    top = []
    for row in market_rows:
        if sum(s.kind == row.kind for s in top) < 4:
            top.append(row)
    if not top and not news_rows:
        raise RuntimeError("No source facts available")
    public_rows = []
    charts = {}
    for story in top + news_rows:
        row = story.brief()
        row.pop("image_url")
        if row["source_text"]:
            row["source_text"] = " ".join(row["source_text"].split()[:25])
        if story.candles:
            candles = story.candles
            charts[story.id] = candles[-289:] if story.range_level is not None else candles[-49:]
            for hours in (1, 4):
                window = candles[-12 * hours:]
                low = market.price(min(c[3] for c in window))
                high = market.price(max(c[2] for c in window))
                row["facts"][f"range_{hours}h"] = (
                    f"${story.symbols[0]}: минимум {low} USDT, максимум {high} USDT за {'час' if hours == 1 else 'четыре часа'}."
                )
        public_rows.append(row)
    atomic_write_json(destination / "bridge/market.json", {
        "schema": 1, "created_at": utcnow().isoformat(), "stories": public_rows,
    })
    atomic_write_json(destination / "bridge/charts.json", charts)
    LOG.info("Collected %d market and %d news stories", len(top), len(news_rows))


def git(root, *args):
    return subprocess.check_output(["git", "-C", str(root), *args], text=True).strip()


def commit(root, paths, message):
    git(root, "add", "--", *paths)
    git(root, "commit", "-m", message)
    git(root, "push", "origin", f"HEAD:refs/heads/{DATA_BRANCH}")


def within(timestamp, now, minutes):
    date = parse_time(timestamp)
    return date is not None and -timedelta(seconds=30) <= now - date <= timedelta(minutes=minutes)


def load_draft(root, now):
    path = root / "bridge/draft.json"
    if not path.is_file():
        return None
    if path.stat().st_size > MAX_DRAFT_BYTES:
        raise ValueError("Draft package is too large")
    data = read_json(path)
    if data["schema"] != 1 or not within(data["created_at"], now, 40):
        return None
    sha = data["source_commit"]
    if not isinstance(sha, str) or not re.fullmatch(r"[0-9a-f]{40}", sha):
        raise ValueError("Expected an exact snapshot commit SHA")
    git(root, "merge-base", "--is-ancestor", sha, "HEAD")
    snapshot = json.loads(git(root, "show", f"{sha}:bridge/market.json"))
    if snapshot["schema"] != 1 or not within(snapshot["created_at"], now, 45):
        return None
    row = next((s for s in snapshot["stories"] if s["id"] == data["story_id"]), None)
    if row is None:
        raise ValueError("Unknown story in snapshot")
    story = Story(**row)
    if not within(story.observed_at, now, 24 * 60 if story.kind == "news" else 45):
        return None
    draft = Draft(story.id, data["text"], data.get("title", ""), evidence_quote=data.get("evidence_quote", ""))
    text, reasons = validate(draft, story, [])
    if reasons:
        raise ValueError("Draft rejected: " + ", ".join(reasons))
    return data, story, text


def prepare_image(data, story, root, output):
    from PIL import Image, ImageOps

    if data.get("image_base64"):
        raw = base64.b64decode(data["image_base64"], validate=True)
        if len(raw) > MAX_IMAGE_BYTES:
            raise ValueError("Image exceeds package limit")
        with Image.open(BytesIO(raw), formats=("JPEG", "PNG", "WEBP")) as image:
            if image.width * image.height > 8_000_000:
                raise ValueError("Image dimensions exceed package limit")
            picture = ImageOps.exif_transpose(image).convert("RGB")
            picture.thumbnail((1600, 1200))
            path = output / "post.jpg"
            picture.save(path, "JPEG", quality=90)
            return str(path)
    charts = json.loads(git(root, "show", f"{data['source_commit']}:bridge/charts.json"))
    story.candles = charts.get(story.id, [])
    chart = visuals.chart(story, output)
    if chart:
        return chart

    # A local editorial graphic uses only the supplied Russian title.
    import textwrap
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    figure = plt.figure(figsize=(12, 6.75), facecolor="#101725", dpi=100)
    try:
        figure.text(.09, .80, "$" + story.symbols[0] + "  /  НОВОСТИ",
                    color="#f3c95d", fontsize=20, weight="bold")
        figure.text(.09, .52, textwrap.fill(data["title"], 32, break_long_words=True),
                    color="#f3f6fc", fontsize=28, weight="bold", va="center")
        figure.text(.09, .13, "PozitiveHero  /  Binance Square", color="#aab8d0", fontsize=14)
        path = output / "news.png"
        figure.savefig(path, facecolor=figure.get_facecolor())
        return str(path)
    finally:
        plt.close(figure)


def deliver(root, output, live):
    package = load_draft(root, utcnow())
    if package is None:
        LOG.info("No fresh draft to deliver")
        return
    data, story, text = package
    if live and data.get("preview_only") is True:
        LOG.info("Draft is marked for preview only")
        return
    key = story.event_key or story.id
    receipt_name = hashlib.sha256(key.encode()).hexdigest()[:32]
    receipt = root / "bridge/receipts" / (receipt_name + ".json")
    from publication_intent import fingerprint

    text_id = fingerprint(text)
    text_claim = root / "bridge/text-claims" / (text_id + ".json")
    if live and (receipt.is_file() or text_claim.is_file()):
        LOG.info("Story already claimed or published")
        return
    output.mkdir(parents=True, exist_ok=True)
    image = prepare_image(data, story, root, output)
    (output / "post.txt").write_text(text + "\n", encoding="utf-8")
    if not live:
        LOG.info("Preview validated with image; no Binance call")
        return

    from publisher import find_skill_dir, publish

    if not find_skill_dir() or not os.getenv("SQUARE_API", "").strip():
        raise RuntimeError("Square publisher or API key is missing")
    now = utcnow()
    if not within(data["created_at"], now, 40) or (
        story.kind != "news" and not within(story.observed_at, now, 45)
    ):
        LOG.info("Draft expired while preparing media")
        return
    state = {"status": "claimed", "story_id": story.id, "claimed_at": now.isoformat()}
    atomic_write_json(receipt, state)
    relative = str(receipt.relative_to(root))
    # Winning the non-force push is required before any external send.
    atomic_write_json(text_claim, {"receipt": receipt_name})
    before_claim = git(root, "rev-parse", "HEAD")
    try:
        commit(root, [relative, str(text_claim.relative_to(root))], "Claim Binance Square post " + receipt_name)
    except subprocess.CalledProcessError:
        # A later collection step must not accidentally push a failed claim.
        git(root, "reset", "--hard", before_claim)
        raise
    result = publish(text, image_path=image, news=story.kind == "news")
    if not result or not result.post_id:
        raise RuntimeError("Square did not confirm publication; claim retained")
    state.update(status="published", post_id=result.post_id, published_at=utcnow().isoformat())
    atomic_write_json(receipt, state)
    # An editor may have updated the draft while Square handled the request.
    git(root, "pull", "--rebase", "--autostash", "origin", DATA_BRANCH)
    commit(root, [relative], "Record Binance Square post " + result.post_id)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("collect", "preview", "publish"))
    parser.add_argument("data", type=Path)
    parser.add_argument("--output", type=Path, default=Path("state/bridge-preview"))
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    if args.mode == "collect":
        collect(args.data)
        return
    if args.mode == "publish" and os.getenv("SQUARE_BRIDGE_LIVE") != "1":
        parser.error("SQUARE_BRIDGE_LIVE must be 1 for publication")
    deliver(args.data, args.output, live=args.mode == "publish")


if __name__ == "__main__":
    main()
