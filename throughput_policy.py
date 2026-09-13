"""Runtime throughput policy for cron-driven Binance Square publishing.

The core orchestrator intentionally stays conservative.  This policy only raises
how many independent market candidates may be tried in one 20-minute cycle and
how many provider requests the scan may spend before falling back.  It does not
weaken text quality, fact-lock, live-price, public-plan or publisher safety gates.
"""
from __future__ import annotations

import builtins
import logging
import os
from functools import wraps

logger = logging.getLogger(__name__)


def install_throughput_policy() -> None:
    """Allow more candidate failover without changing publication safety gates."""
    import ai_provider
    import main as main_module

    attempts = max(3, min(int(os.getenv("PUBLICATION_CANDIDATE_ATTEMPTS", "6")), 10))
    ai_requests = max(8, min(int(os.getenv("AI_SCAN_MAX_REQUESTS", "14")), 24))

    # main._run_once currently owns a deliberately bounded `range(3)` candidate
    # failover loop.  Keep the upstream implementation intact and override only
    # that exact range call when its direct caller is _run_once.  Every other
    # range() use in main continues to behave exactly like builtins.range.
    if not getattr(main_module, "_throughput_range_installed", False):
        original_run_once_code = main_module._run_once.__code__

        def throughput_range(*args):
            import sys

            caller = sys._getframe(1)
            if caller.f_code is original_run_once_code and args == (3,):
                return builtins.range(attempts)
            return builtins.range(*args)

        main_module.range = throughput_range
        main_module._throughput_range_installed = True

    # _run_once imports start_scan_budget locally, so wrapping the provider
    # function here transparently raises only the scan-wide request allowance.
    if not getattr(ai_provider.start_scan_budget, "_throughput_policy", False):
        original_start_scan_budget = ai_provider.start_scan_budget

        @wraps(original_start_scan_budget)
        def start_scan_budget(deadline=None, max_requests=8):
            requested = ai_requests if int(max_requests) == 8 else int(max_requests)
            return original_start_scan_budget(deadline, max_requests=requested)

        start_scan_budget._throughput_policy = True  # type: ignore[attr-defined]
        ai_provider.start_scan_budget = start_scan_budget

    logger.info(
        "Throughput policy active: candidate attempts=%s, AI scan requests=%s; safety gates unchanged",
        attempts,
        ai_requests,
    )


def verify_throughput_policy() -> None:
    import ai_provider
    import main as main_module

    if not getattr(main_module, "_throughput_range_installed", False):
        raise RuntimeError("throughput candidate failover policy was not installed")
    if not getattr(ai_provider.start_scan_budget, "_throughput_policy", False):
        raise RuntimeError("throughput AI scan budget policy was not installed")
