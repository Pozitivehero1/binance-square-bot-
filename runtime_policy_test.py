"""The production entry point must use the new engine without import-time patches."""
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch


def main():
    with patch.dict(os.environ, {"BOT_VERSION": "untouched", "DRY_RUN": "1"}):
        import run_bot
        assert os.environ["BOT_VERSION"] == "untouched"
        assert "groq_primary" not in sys.modules
        assert "reach_recovery_v11_8" not in sys.modules
        assert callable(run_bot.main)
    source = Path("run_bot.py").read_text()
    assert "from squarebot.pipeline import run" in source
    assert "install_" not in source
    result = subprocess.run([sys.executable, "run_bot.py", "--help"], capture_output=True, text=True)
    assert result.returncode == 0 and "--dry-run" in result.stdout and "--scan-only" in result.stdout
    print("RUNTIME POLICY: OK | v13 explicit pipeline | imports do not patch legacy modules")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
