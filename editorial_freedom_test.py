"""Offline test: DeepSeek is given creative latitude while facts remain protected."""
from unittest.mock import patch
from types import SimpleNamespace
import writer
import event_writer
from reader_experiment import EXPERIMENT_VERSION
from reach_editorial import editorial_reach_adjustment


def main():
    assert EXPERIMENT_VERSION == "v4"
    jobs = (
        (writer, {"market":{"ticker":"$BTC"}}, "TRADE", ["hot_take", "market_story"]),
        (event_writer, {"market_event":{"ticker":"$BTC"}, "optional_trade_plan":{"available":False}},
         "EVENT", ["event_pulse", "event_market_story"]),
    )
    for module, pkg, lane, formats in jobs:
        seen = []
        def fake_request(**kwargs):
            seen.append(kwargs)
            return SimpleNamespace(candidates=[{"format_id":x,"text":"$BTC — тестовый текст"}
                                               for x in formats])
        with patch.object(module, "has_ai_provider", return_value=True), patch.object(
            module, "request_candidates", side_effect=fake_request
        ), patch.dict("os.environ", {"ENABLE_READER_EXPERIMENT":"1"}):
            results = module._request_ai_candidates(package=pkg, formats=formats, recent_posts=[
                "$BTC — цена выросла, объём увеличился. Ждём подтверждения."
            ], attempt=1)
        assert len(results) == 2
        call = seen[0]
        assert "свобод" in call["system_prompt"].lower(), (lane, call["system_prompt"])
        assert "сам выбери" in str(call["user_payload"]).lower()
        assert all("optional_angle" in row for row in call["user_payload"]["requested_formats"])
        assert "recent_posts_to_avoid" in call["user_payload"]
        assert "факт" in str(call["user_payload"]["hard_constraints"]).lower()
        assert "не" in str(call["user_payload"]["hard_constraints"]).lower()
        assert call["temperature"] >= 0.65
    # Multiple indicators are no longer an automatic ranking advantage.
    plain = "$BTC — цена почти стоит на месте, но объём растёт. Это пока не делает движение устойчивым."
    jargon = plain + " RSI VWAP ADX ATR"
    assert editorial_reach_adjustment(plain).score > editorial_reach_adjustment(jargon).score
    print("EDITORIAL FREEDOM: OK | open structure + fact-lock + anti-jargon scoring")


if __name__ == "__main__":
    main()
