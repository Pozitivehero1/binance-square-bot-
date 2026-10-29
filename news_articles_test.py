"""Offline tests for the news and creator-content lanes (no network or publishing)."""
from __future__ import annotations

import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import news_articles as news
import square_creator_inspiration as creator
from publisher import PublishResult


def news_item(link="https://example.org/news/one"):
    return {"title": "Company launches Bitcoin network service", "summary": "The company launched a Bitcoin infrastructure service after testing the network.",
            "link": link, "image": "https://example.org/cover.jpg", "age": 100}


def sample_article():
    return ("Биткоин и новые возможности инфраструктуры",
            "$BTC: Компания запустила сервис инфраструктуры после тестирования сети. "
            "Публикация описывает запуск нового продукта и предшествовавшую проверку его работы. "
            "Информации о финансовых показателях сервиса в исходном сообщении нет.")


class NewsTests(unittest.TestCase):
    def test_draft_uses_verified_candidate_protocol(self):
        title, body = sample_article()
        response = SimpleNamespace(candidates=[{"title": title, "text": body, "evidence_quote": news_item()["summary"]}], provider="deepseek_local")
        with patch.object(news, "request_candidates", return_value=response) as req:
            self.assertEqual(news._draft(news_item(), ["BTC"]), (title, body.strip()+"\n\nИсточник: example.org"))
            self.assertEqual(req.call_count, 1)

    def test_news_uses_configured_groq_when_deepseek_unavailable(self):
        title, body = sample_article()
        item = news_item()
        response = SimpleNamespace(
            candidates=[{"title": title, "text": body, "evidence_quote": item["summary"]}],
            provider="groq", model="test-model",
        )
        with patch.dict(os.environ, {"ENABLE_NEWS_ARTICLES": "1"}), \
             patch.object(news, "configured", return_value=False), \
             patch.object(news.ai_provider, "has_ai_provider", return_value=True), \
             patch.object(news.ai_provider, "request_candidates", return_value=response) as routed, \
             patch.object(news, "_load", return_value={"seen": {}, "last_news_at": ""}), \
             patch.object(news, "_fetch", return_value=[item]), \
             patch.object(news, "_cover", return_value="/tmp/cover.jpg"), \
             patch.object(news, "publish", return_value=PublishResult(True, post_id="456")), \
             patch.object(news, "atomic_write_json"), \
             patch.object(news, "write_status"), \
             patch("performance_store.record_publication") as tracking:
            self.assertTrue(news.maybe_publish_news())
            self.assertEqual(routed.call_count, 1)
            self.assertEqual(tracking.call_args.kwargs["writer_source"], "groq")
            self.assertEqual(tracking.call_args.kwargs["fact_package"]["evidence_quote"], item["summary"])

    def test_draft_repairs_missing_cashtag_from_verified_rss_ticker(self):
        title, body = sample_article()
        response = SimpleNamespace(
            candidates=[{"title": title, "text": body.replace("$BTC", "BTC"),
                         "evidence_quote": news_item()["summary"]}],
            provider="groq",
        )
        with patch.object(news, "request_candidates", return_value=response):
            article = news._draft(news_item(), ["BTC"])
        self.assertIsNotNone(article)
        self.assertEqual(article[0], title)
        self.assertTrue(article[1].startswith("$BTC — "))
        self.assertIn("Источник: example.org", article[1])

    def test_draft_does_not_bypass_event_evidence_for_missing_cashtag(self):
        title, body = sample_article()
        response = SimpleNamespace(
            candidates=[{"title": title, "text": body.replace("$BTC", "BTC"),
                         "evidence_quote": "Not a quote from the actual RSS event"}],
            provider="groq",
        )
        with patch.object(news, "request_candidates", return_value=response):
            self.assertIsNone(news._draft(news_item(), ["BTC"]))

    def test_news_falls_back_after_timeout_without_retry_storm(self):
        items = [news_item(str(x)) for x in range(6)]
        with patch.dict(os.environ, {"ENABLE_NEWS_ARTICLES": "1", "NEWS_MAX_DRAFT_ATTEMPTS": "3"}), \
             patch.object(news, "configured", return_value=True), \
             patch.object(news, "_load", return_value={"seen": {}, "last_news_at": ""}), \
             patch.object(news, "_fetch", return_value=items), \
             patch.object(news, "_cover", return_value="/tmp/cover.jpg"), \
             patch.object(news, "_draft", side_effect=__import__("requests").ReadTimeout()) as draft:
            self.assertFalse(news.maybe_publish_news())
            self.assertEqual(draft.call_count, 1)

    def test_news_provider_failure_backoff_persists_across_runs(self):
        state = {"seen": {}, "last_news_at": ""}
        with patch.dict(os.environ, {"ENABLE_NEWS_ARTICLES": "1"}), \
             patch.object(news, "configured", return_value=True), \
             patch.object(news, "_load", return_value=state), \
             patch.object(news, "_fetch", return_value=[news_item()]) as fetch, \
             patch.object(news, "_cover", return_value="/tmp/cover.jpg"), \
             patch.object(news, "_draft", side_effect=RuntimeError("provider unavailable")) as draft, \
             patch.object(news, "atomic_write_json") as save:
            self.assertFalse(news.maybe_publish_news())
            self.assertIn("provider_retry_at", state)
            self.assertEqual(save.call_count, 1)
            # A separate cron invocation must skip the broken news provider,
            # while market publication remains available to the caller.
            self.assertFalse(news.maybe_publish_news())
            self.assertEqual(draft.call_count, 1)
            self.assertEqual(fetch.call_count, 1)
            # Expired cooldown retries normally instead of disabling news forever.
            state["provider_retry_at"] = "2000-01-01T00:00:00+00:00"
            self.assertFalse(news.maybe_publish_news())
            self.assertEqual(draft.call_count, 2)
            self.assertEqual(fetch.call_count, 2)

    def test_article_rejection_continues_to_next_story(self):
        title, body = sample_article()
        items = [news_item("https://example.org/one"), news_item("https://example.org/two")]
        fake_failure = PublishResult(False, stderr="text integrity: language:unexpected-english-density")
        fake_success = PublishResult(True, post_id="123")
        with patch.dict(os.environ, {"ENABLE_NEWS_ARTICLES": "1", "NEWS_MAX_DRAFT_ATTEMPTS": "2"}), \
             patch.object(news, "configured", return_value=True), \
             patch.object(news, "_load", return_value={"seen": {}, "last_news_at": ""}), \
             patch.object(news, "_fetch", return_value=items), \
             patch.object(news, "_cover", return_value="/tmp/cover.jpg"), \
             patch.object(news, "_draft", return_value=(title, body)) as draft, \
             patch.object(news, "publish", side_effect=[fake_failure, fake_success]) as publish, \
             patch.object(news, "atomic_write_json") as save, \
             patch.object(news, "write_status") as status, \
             patch("performance_store.record_publication") as tracking:
            self.assertTrue(news.maybe_publish_news())
            self.assertEqual(draft.call_count, 2)
            self.assertEqual(publish.call_count, 2)
            self.assertEqual(save.call_count, 1)
            self.assertEqual(status.call_count, 1)
            self.assertEqual(tracking.call_count, 1)


class CreatorTests(unittest.TestCase):
    NOW_MS = 1792485000000

    def _post(self, ident, body, age_minutes=5):
        return {"id": ident, "bodyTextOnly": body,
                "firstReleaseTime": self.NOW_MS - age_minutes * 60_000}

    def test_parses_recent_posts_without_importing_trade_prices(self):
        rows = [
            self._post("123", "$AVA bounced strongly from 0.3793 and is moving towards resistance. The author discusses a possible recovery."),
            self._post("124", "$SUI LONG TRADE SIGNAL! Buyers may be watching a correction, but the trade carries risks and needs verification."),
            self._post("125", "Please join our Premium group with a free trial and price alerts for every market."),
            self._post("126", "$ETH old news about market momentum, and this is deliberately older than the allowed freshness.", age_minutes=3000),
        ]
        topics = [creator._topic_from_post(row, self.NOW_MS) for row in rows]
        self.assertEqual(sum(item is not None for item in topics), 2)
        self.assertEqual(topics[0]["tickers"], ["AVA"])
        self.assertIn("восстановления", topics[0]["topic"])
        self.assertNotIn("0.3793", topics[0]["topic"])
        self.assertIn("SUI", topics[1]["tickers"])

    def test_public_profile_and_posts_api_end_to_end_mock(self):
        creator._CACHE.update(at=0.0, topics=[])
        class Response:
            def __init__(self, data):
                self.data = data
            def raise_for_status(self):
                return None
            def json(self):
                return self.data
        class FakeSession:
            headers = {}
            def __enter__(self):
                return self
            def __exit__(self, *args):
                return None
            def post(self, url, **kwargs):
                self._post_kwargs = kwargs
                return Response({"code": "000000", "success": True,
                                 "data": {"squareUid": "SampleAuthorUid-42"}})
            def get(self, url, **kwargs):
                if "queryUserProfilePageContentsWithFilter" in url:
                    self._get_kwargs = kwargs
                    return Response({"code": "000000", "success": True,
                                     "data": {"contents": [
                                         CreatorTests()._post("246",
                                             "$ADA is correcting and traders are watching a recovery attempt. The scenario requires confirmation.")
                                     ]}})
                return Response({})
        fake = FakeSession()
        with patch.object(creator.requests, "Session", return_value=fake), \
             patch.object(creator.time, "time", return_value=self.NOW_MS / 1000):
            rows = creator.recent_creator_topics(limit=5)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["url"], "https://www.binance.com/en/square/post/246")
        self.assertEqual(rows[0]["tickers"], ["ADA"])
        self.assertEqual(fake._post_kwargs["json"]["username"], "cryptonexus_btc")
        self.assertEqual(fake._get_kwargs["params"]["targetSquareUid"], "SampleAuthorUid-42")
        creator._CACHE.update(at=0.0, topics=[])

    def test_invalid_user_and_api_response_fail_closed(self):
        self.assertEqual(creator._fetch_creator("not/valid", self.NOW_MS), [])
        with self.assertRaises(ValueError):
            creator._request_data(
                type("Resp", (), {"raise_for_status": lambda self: None,
                                  "json": lambda self: {"code": "BAD_CODE", "data": {}}})(),
                "profile")


if __name__ == "__main__":
    unittest.main()
