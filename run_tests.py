"""Run the practical offline regression suite.

Set RUN_STRESS_TESTS=1 to append the longer repetition stress tests.
"""
from __future__ import annotations

import os
import subprocess
import sys

STANDARD_TESTS = [
    "attention_test.py",
    "micro_attention_test.py",
    "opportunity_test.py",
    "dual_lane_test.py",
    "event_author_test.py",
    "event_ai_resilience_test.py",
    "author_pool_policy_test.py",
    "public_plan_contract_test.py",
    "event_visual_test.py",
    "trade_plan_test.py",
    "w2e_test.py",
    "human_copy_test.py",
    "emoji_test.py",
    "presentation_test.py",
    "visual_test.py",
    "cron_test.py",
    "analytics_test.py",
    "provider_test.py",
    "openrouter_fallback_chain_test.py",
    "adaptive_test.py",
    "outcome_test.py",
    "outcome_card_test.py",
    "text_integrity_test.py",
    "reach_quality_test.py",
    "language_quality_test.py",
    "recovery_guard_test.py",
    "reach_engine_test.py",
    "reach_recovery_v11_7_test.py",
    "reach_recovery_v11_8_test.py",
    "reach_recovery_live_exit_test.py",
    "production_guard_test.py",
    "self_test.py",
]

STRESS_TESTS = [
    "repetition_test.py",
    "event_repetition_test.py",
]


def main() -> int:
    tests = list(STANDARD_TESTS)
    if os.getenv("RUN_STRESS_TESTS", "0").strip().lower() in {"1", "true", "yes"}:
        tests.extend(STRESS_TESTS)

    for test in tests:
        print(f"\n=== {test} ===", flush=True)
        result = subprocess.run([sys.executable, test], check=False)
        if result.returncode != 0:
            print(f"FAILED: {test}")
            return result.returncode

    print("\nALL STANDARD OFFLINE TESTS PASSED")
    if tests == STANDARD_TESTS:
        print("Long repetition stress tests are available with RUN_STRESS_TESTS=1 python run_tests.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
