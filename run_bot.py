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
from openrouter_fallback_chain import install_openrouter_fallback_chain
from reach_recovery_v11_8 import activate_reach_recovery

# OpenRouter now receives an ordered free-model fallback chain. Provider-level
# failures are handled inside OpenRouter; repeated requests rotate the first
# model so unusable successful responses do not monopolize every retry.
install_openrouter_fallback_chain()

# v11.8 intentionally keeps the pre-v11.7 market/adaptive ranking bounds and
# patches only the final recovery publication gate.  The external cron, trade
# levels, signal math and publisher remain untouched.
activate_reach_recovery()


if __name__ == "__main__":
    raise SystemExit(main())
