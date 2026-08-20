"""Cron entry point. Safe to call from any working directory."""
from __future__ import annotations

import os

from runtime import PROJECT_DIR, load_project_env

load_project_env()
os.chdir(PROJECT_DIR)

# Apply the v11.3 production hotfix before main imports outcome_engine/publisher.
# The patch is idempotent, so it becomes a no-op once these fixes are merged
# directly into the source files.
from runtime_hotfix_v113 import apply_v113_hotfix

apply_v113_hotfix()

from main import main


if __name__ == "__main__":
    raise SystemExit(main())