"""Cron entry point for the v13 editorial engine, independent of the working directory."""
from __future__ import annotations

import argparse
from dataclasses import replace
import os

from runtime import PROJECT_DIR, load_project_env, setup_logging


def main(argv=None):
    load_project_env()
    os.chdir(PROJECT_DIR)
    setup_logging()
    from squarebot import VERSION
    from squarebot.author import configured_providers
    from squarebot.models import Settings
    os.environ["BOT_VERSION"] = VERSION
    parser = argparse.ArgumentParser(description="Binance Square editorial engine")
    parser.add_argument("--check", action="store_true", help="Check provider/publisher configuration; no network or send")
    parser.add_argument("--dry-run", action="store_true", help="Discover, author and validate without sending")
    parser.add_argument("--scan-only", action="store_true", help="Discover facts without calling an AI or publisher")
    args = parser.parse_args(argv)
    settings = Settings.from_env()
    if args.dry_run:
        settings = replace(settings, dry_run=True)
    if args.check:
        from publisher import find_skill_dir
        providers = configured_providers()
        print(f"Engine={VERSION} dry_run={settings.dry_run} AI providers={len(providers)}")
        print("Author chain="+" -> ".join(p.name+"/"+p.model for p in providers))
        square_ready = bool(find_skill_dir() and (os.getenv("SQUARE_API") or os.getenv("BINANCE_SQUARE_OPENAPI_KEY")))
        print(f"Square publisher ready={square_ready}")
        return 0 if providers and (settings.dry_run or square_ready) else 1
    if args.scan_only:
        from squarebot import market, news
        from runtime import atomic_write_json, resolve_state_file
        stories = market.scan(settings)
        if settings.enable_news:
            stories += news.scan()
        path = resolve_state_file("EDITOR_SCAN_FILE", "editorial_scan.json")
        atomic_write_json(path, {"version": VERSION, "stories": [s.brief() for s in stories]})
        print(f"Measured stories={len(stories)}; AI calls=0; sends=0")
        return 0 if stories else 1
    from operations import run_entrypoint
    from squarebot.pipeline import run
    return run_entrypoint(lambda: run(settings))


if __name__ == "__main__":
    raise SystemExit(main())
