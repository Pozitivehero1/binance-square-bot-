"""Run the complete offline v9 regression suite."""
from __future__ import annotations

import subprocess
import sys

TESTS = [
    "attention_test.py",
    "micro_attention_test.py",
    "opportunity_test.py",
    "trade_plan_test.py",
    "w2e_test.py",
    "human_copy_test.py",
    "emoji_test.py",
    "presentation_test.py",
    "visual_test.py",
    "cron_test.py",
    "self_test.py",
    "repetition_test.py",
]


def main() -> int:
    for test in TESTS:
        print(f"\n=== {test} ===", flush=True)
        result = subprocess.run([sys.executable, test], check=False)
        if result.returncode != 0:
            print(f"FAILED: {test}")
            return result.returncode
    print("\nALL V9 OFFLINE TESTS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
