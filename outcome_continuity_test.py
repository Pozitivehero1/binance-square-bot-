"""Offline: accountable follow-ups are never hidden by depressed 24h reach."""
from unittest.mock import Mock, patch
import main


def main_test() -> None:
    memory, guard = Mock(), Mock()
    with patch("main.process_outcomes", return_value=True) as process, patch("main.write_status") as status:
        with patch.dict("main.os.environ", {"OUTCOME_IN_RECOVERY": "1"}):
            assert main._try_outcome_fallback(memory=memory, guard=guard, recovery_mode=True) is True
        process.assert_called_once_with(memory=memory, guard=guard, dry_run=main.DRY_RUN, refresh_only=False)
        status.assert_called_once()
    with patch("main.process_outcomes") as process:
        with patch.dict("main.os.environ", {"OUTCOME_IN_RECOVERY": "0"}):
            assert main._try_outcome_fallback(memory=memory, guard=guard, recovery_mode=True) is False
        process.assert_not_called()
    with patch("main.process_outcomes", return_value=False), patch.dict("main.os.environ", {"OUTCOME_IN_RECOVERY": "1"}):
        assert main._try_outcome_fallback(memory=memory, guard=guard, recovery_mode=True) is False
    print("OUTCOME CONTINUITY: OK | recovery-safe real outcome and opt-out")


if __name__ == "__main__":
    main_test()
