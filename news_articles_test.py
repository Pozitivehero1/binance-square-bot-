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
    return {"title": "Bitcoin network update", "summary": "Bitcoin adoption news with independently reported background.",
            "link": link, "image": "https://example.org/cover.jpg", "age": 100}


def sample_article():
    return ("Биткоин и новые возможности инфраструктуры",
            "$BTC: " + "Новая публикация описывает развитие инфраструктуры цифровых активов. " * 9)


class NewsTests(unittest.TestCase):
    def test_draft_uses_verified_candidate_protocol(self):
        title, body = sample_article()
        response = SimpleNamespace(candidates=[{"title": title, "text": body}], provider="deepseek_local")
        with patch.object(news, "request_candidates", return_value=response) as req:
            self.assertEqual(news._draft(news_item(), ["BTC"]), (title, body))
            self.assertEqual(req.call_count, 1)

    def test_draft_rejects_missing_cashtag(self):
        title, body = sample_article()
        response = SimpleNamespace(candidates=[{"title": title, "text": body.replace("$BTC", "BTC")}],
                                   provider="deepseek_local")
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
             patch.object(news, "atomic_write_json") as save:
            self.assertTrue(news.maybe_publish_news())
            self.assertEqual(draft.call_count, 2)
            self.assertEqual(publish.call_count, 2)
            self.assertEqual(save.call_count, 1)


class CreatorTests(unittest.TestCase):
    def test_post_in_article_with_short_link_still_extracted(self):
        parser = creator._ProfileParser()
        parser.feed('<article><a href="/en/square/post/123">post</a><p>' +
                    "Price observation about this market and new verified developments. " * 2 +
                    '</p></article>')
        self.assertEqual(len(parser.links), 1)
        self.assertEqual(parser.links[0]["url"], "https://www.binance.com/en/square/post/123")

    def test_public_profile_topics_not_accepted_from_other_domain(self):
        creator._CACHE.update(at=0.0, topics=[])
        fake_response = SimpleNamespace(
            status_code=200, content=b"x" * 300,
            text='<article><a href="https://evil.example/square/post/123">' +
                 "Long unsafe external link pretending to be a Binance post." * 2 +
                 '</a></article>',
            raise_for_status=lambda: None)
        with patch.object(creator.requests, "get", return_value=fake_response):
            self.assertEqual(creator.recent_creator_topics(limit=5), [])
        creator._CACHE.update(at=0.0, topics=[])


if __name__ == "__main__":
    unittest.main()
