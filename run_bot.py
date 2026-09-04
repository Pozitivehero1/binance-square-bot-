"""Cron entry point. Safe to call from any working directory."""
from __future__ import annotations

import os

from runtime import PROJECT_DIR, load_project_env

load_project_env()
os.chdir(PROJECT_DIR)

# Activate release defaults before importing writer/orchestrator modules.
from runtime_release import activate_release

activate_release()

# Install every runtime policy before main imports writer functions by name.
from openrouter_fallback_chain import install_openrouter_fallback_chain, verify_openrouter_fallback_chain
from reach_recovery_v11_8 import activate_reach_recovery
from author_pool_policy import install_author_pool_policy, verify_author_policy
from reach_recovery_live_exit import activate_live_recovery_exit

install_openrouter_fallback_chain()
activate_reach_recovery()
install_author_pool_policy()
activate_live_recovery_exit()

# Fail before an expensive market scan if patch ordering silently broke a core
# production invariant. A workflow failure is diagnosable; a silent no-post loop
# is not.
verify_openrouter_fallback_chain()
verify_author_policy()

import recovery_guard
import writer

if not getattr(recovery_guard.evaluate_recovery_candidate, "_v118_live_recovery_exit", False):
    raise RuntimeError("live recovery exit was not installed")
if writer._build_generated.__module__ != "reach_recovery_v11_8":
    raise RuntimeError("v11.8 TRADE AI handoff was not installed")

from main import main


if __name__ == "__main__":
    raise SystemExit(main())
