"""Cron entry point. Safe to call from any working directory."""
from __future__ import annotations

import os

from runtime import PROJECT_DIR, load_project_env

load_project_env()
os.chdir(PROJECT_DIR)

# Activate release defaults before importing the writer/orchestrator modules.
from runtime_release import activate_release

activate_release()

# Install every runtime policy before main imports writer functions by name.
# This avoids stale references and makes startup order explicit and testable.
from openrouter_fallback_chain import install_openrouter_fallback_chain
from reach_recovery_v11_8 import activate_reach_recovery
from author_pool_policy import install_author_pool_policy
from reach_recovery_live_exit import activate_live_recovery_exit

install_openrouter_fallback_chain()
activate_reach_recovery()
install_author_pool_policy()
activate_live_recovery_exit()

from main import main


if __name__ == "__main__":
    raise SystemExit(main())
