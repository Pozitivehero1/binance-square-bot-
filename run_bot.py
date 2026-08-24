"""Cron entry point. Safe to call from any working directory."""
from __future__ import annotations

import os

from runtime import PROJECT_DIR, load_project_env

load_project_env()
os.chdir(PROJECT_DIR)

# Apply production hotfixes before main imports outcome/writer modules.
from runtime_hotfix_v113 import apply_v113_hotfix
from runtime_hotfix_v114 import apply_v114_hotfix
from runtime_hotfix_v1141 import apply_v1141_hotfix

apply_v113_hotfix()
apply_v114_hotfix()
apply_v1141_hotfix()

from main import main


if __name__ == "__main__":
    raise SystemExit(main())
