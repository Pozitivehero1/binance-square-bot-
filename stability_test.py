"""Regressions for observed outages and published corruption; no live requests."""
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

import pandas as pd
import requests

import ai_provider
from data import candles_are_current
from factual_copy import market_narrative
from openrouter_fallback_chain import _model_error_is_fallbackable
from production_guard import final_text_reasons
from provider_health import ProviderCooldown, check_cooldown, remember_failure
from publication_continuity import allow_outage_probe
from publisher import publish


def response(status, body):
    result = requests.Response()
    result.status_code = status
    result._content = json.dumps(body).encode()
    return result


class StabilityTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.env = patch.dict(os.environ, {"PROVIDER_HEALTH_FILE": self.directory.name + "/health.json", "PUBLICATION_INTENT_FILE": self.directory.name + "/intents.json", "SQUARE_PROFILE_UID": ""})
        self.env.start()
        self.addCleanup(self.env.stop)

    def test_daily_limit_stops_model_walk_and_outer_retry(self):
        reply = response(429, {"error": {"message": "free-models-per-day"}})
        exc = requests.HTTPError(response=reply)
        self.assertFalse(_model_error_is_fallbackable(exc))
        self.assertFalse(ai_provider._retry_delay(exc, 1, "OPENROUTER")[0])

    def test_upstream_rate_limit_still_fails_over(self):
        exc = requests.HTTPError(response=response(429, {"error": {"message": "upstream capacity"}}))
        self.assertTrue(_model_error_is_fallbackable(exc))
        self.assertTrue(ai_provider._retry_delay(exc, 1, "OPENROUTER")[0])

    def test_quota_persists_and_expires_without_saving_secret(self):
        now = 1800000000.0
        reply = response(429, {"error": {"message": "free-models-per-day", "metadata": {
            "headers": {"X-RateLimit-Reset": str(int((now + 1200) * 1000))}}}})
        with patch("provider_health.time.time", return_value=now):
            remember_failure("https://openrouter.ai/api/v1/chat/completions", "test-secret", "one", reply)
            with self.assertRaises(ProviderCooldown):
                check_cooldown("https://openrouter.ai/api/v1/chat/completions", "test-secret", "two")
            check_cooldown("https://openrouter.ai/api/v1/chat/completions", "rotated-key", "one")
        with patch("provider_health.time.time", return_value=now + 1201):
            check_cooldown("https://openrouter.ai/api/v1/chat/completions", "test-secret", "one")
        self.assertNotIn("test-secret", Path(os.environ["PROVIDER_HEALTH_FILE"]).read_text())

    def test_unavailable_model_does_not_disable_other_models(self):
        remember_failure("https://openrouter.ai/api/v1/chat/completions", "k", "bad", response(404, {}))
        with self.assertRaises(ProviderCooldown) as raised:
            check_cooldown("https://openrouter.ai/api/v1/chat/completions", "k", "bad")
        self.assertTrue(_model_error_is_fallbackable(raised.exception))
        check_cooldown("https://openrouter.ai/api/v1/chat/completions", "k", "good")

    def test_daily_cooldown_prevents_actual_http_request(self):
        url = "https://openrouter.ai/api/v1/chat/completions"
        remember_failure(url, "k", "one", response(429, {"error": {"message": "free-models-per-day"}}))
        with patch("ai_provider.requests.post") as post:
            with self.assertRaises(ProviderCooldown):
                ai_provider._request(url=url, key="k", body={"model": "two"}, timeout=5, provider="OpenRouter")
            post.assert_not_called()

    def test_placeholder_and_gibberish_blocked_before_publisher(self):
        for text in ("$SOPH Фиксация по уровням ${tp_list}.", "Cashtag @oracetrade", "$ORCA Оверсаттеринг момента."):
            with self.subTest(text=text), patch("publisher.subprocess.run") as process:
                self.assertFalse(publish(text))
                process.assert_not_called()

    def test_publisher_requires_content_confirmation(self):
        root = Path(self.directory.name)
        (root / "scripts").mkdir()
        (root / "scripts/post-text.mjs").touch()
        for stdout, expected in (("", False), ("Usage: post-text", False), ('{"id":"request-id"}', False),
                                 ('{"success":false,"postId":"123"}', False),
                                 ("Success!\nID: unavailable\nLink: unavailable", False),
                                 ("Success!\nID: 123456789\nLink: https://www.binance.com/square/post/123456789", True),
                                 ("Success! Content ID: 123456789", True)):
            Path(os.environ["PUBLICATION_INTENT_FILE"]).unlink(missing_ok=True)
            with self.subTest(stdout=stdout), patch("publisher.find_skill_dir", return_value=str(root)), \
                    patch.dict(os.environ, {"SQUARE_API": "fake"}), \
                    patch("publisher.subprocess.run", return_value=Mock(stdout=stdout, stderr="", returncode=0)):
                self.assertEqual(bool(publish("$BTC — наблюдаю за ценой.")), expected)

    def test_normal_decimal_sentence_is_not_truncated_number(self):
        self.assertFalse(final_text_reasons("TP1 1.1 | TP2 1.2 | TP3 1.3."))
        self.assertTrue(final_text_reasons("TP1 1.1 | TP2 1.2 | TP3 1,"))

    def test_recovery_probe_needs_silence_and_real_quality(self):
        now = datetime.now(timezone.utc)
        candidate = dict(writer_source="deterministic_event", event_class="audience_breakout", micro_phase="fresh",
                         reach_score=76, selection_score=72, opportunity_score=67, audience_demand=76,
                         monetization_score=56, attention_score=46, micro_score=76)
        for minutes, expected in ((119, False), (120, True), (200, True), (-1, False)):
            store = {"posts": {"one": {"published_at": (now - timedelta(minutes=minutes)).isoformat()}}}
            with patch("performance_store.load_store", return_value=store):
                self.assertEqual(allow_outage_probe(now=now, **candidate), expected)
                self.assertFalse(allow_outage_probe(now=now, **{**candidate, "micro_phase": "stale"}))
                self.assertFalse(allow_outage_probe(now=now, **{**candidate, "reach_score": 50}))
        with patch("performance_store.load_store", return_value={"posts": {}}):
            self.assertFalse(allow_outage_probe(now=now, **candidate))

    def test_closed_candles_must_also_be_current(self):
        now = pd.Timestamp("2026-09-08T12:10:10Z")
        for timestamp, expected in (("12:05:00", True), ("12:00:00", True), ("11:55:00", False), ("12:10:00", False)):
            frame = pd.DataFrame({"close": [1]}, index=pd.to_datetime([f"2026-09-08T{timestamp}Z"]))
            self.assertEqual(candles_are_current(frame, "5m", now), expected)

    def test_outage_copy_matches_volume_and_does_not_invent_trade(self):
        text = market_narrative(ticker="$TEST", move5=-0.4, move15=1.2, volume5=2, volume15=0.5,
                                price=100, level=99, plan_available=False, direction="long", decision_mode="at_level", index=0)
        self.assertIn("против 15-минутного", text)
        self.assertIn("активность ниже нормы", text)
        self.assertIn("Цена выше 99", text)
        self.assertNotIn("LONG", text)
        self.assertFalse(final_text_reasons(text))

    def test_real_writers_run_integrity_guards(self):
        from self_test import _build_setup, _market_context
        from indicators import calculate_multi_timeframe
        from filters import SignalFilter
        import writer
        import event_writer
        frames = _build_setup("long")
        mtf = calculate_multi_timeframe("TESTUSDT", frames)
        score = SignalFilter(min_score=0).evaluate(mtf)
        levels, attention, micro, opportunity, monetization = _market_context(mtf, frames, score)
        args = dict(basic="TEST", mtf=mtf, direction="long", levels=levels, btc=None,
                    attention=attention, micro=micro, opportunity=opportunity, monetization=monetization)
        package = writer._semantic_package(**args)
        event_package = event_writer._semantic_package(**args)
        text = writer._deterministic_candidate(**{k: v for k, v in args.items() if k not in ("btc", "opportunity", "monetization")}, format_id="hot_take", index=0)
        for target in ("TP1", "TP2", "TP3"):
            self.assertEqual(text.count(target), 1)
        for bad in ("${tp_list}", "Оверсаттеринг момента.", "ADX подтверждает рост."):
            corrupted = text.replace("\n\n", f" {bad}\n\n", 1)
            self.assertFalse(writer._validate_ai_post(corrupted, basic="TEST", direction="long", levels=levels, package=package, format_id="hot_take")[0])
            self.assertFalse(event_writer._validate_event_post(corrupted, basic="TEST", direction="long", package=event_package)[0])


if __name__ == "__main__":
    unittest.main()
