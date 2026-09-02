"""Cron entry point. Safe to call from any working directory."""
from __future__ import annotations

import os

from runtime import PROJECT_DIR, load_project_env

load_project_env()
os.chdir(PROJECT_DIR)

# The cumulative release ships source directly. Startup performs one read-only
# release verification instead of rewriting files through a hotfix chain.
from runtime_release import activate_release

activate_release()

from main import main


if __name__ == "__main__":
    raise SystemExit(main())
