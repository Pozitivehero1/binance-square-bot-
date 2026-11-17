"""Offline checks of the queue and publication boundary."""
import base64
import json
import tempfile
import unittest
from datetime import timedelta
from io import BytesIO
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from publisher import PublishResult
from production_guard import final_text_reasons
from runtime import atomic_write_json
from squarebot import bridge
from squarebot.models import utcnow


class BridgeTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.output = self.root / "output"
        self.now = utcnow()
        self.sha = "a" * 40
        self.story = {"id": "spot-id", "kind": "mover", "symbols": ["BTC"], "headline": "Движение",
                      "observed_at": self.now.isoformat(), "facts": {"f1": "$BTC: изменение за час +1.50%."}}
        self.story["facts"].update({
            "low_1h": "$BTC: минимум 97000 USDT за час.",
            "high_1h": "$BTC: максимум 98500 USDT за час.",
            "high_4h": "$BTC: максимум 99000 USDT за четыре часа.",
            "high_24h": "$BTC: максимум 100000 USDT за двадцать четыре часа.",
        })
        self.snapshot = {"schema": 1, "created_at": self.now.isoformat(), "stories": [self.story]}
        raw = BytesIO()
        Image.new("RGB", (32, 24), "blue").save(raw, "JPEG")
        self.draft = {
            "schema": 2, "source_commit": self.sha, "created_at": self.now.isoformat(), "story_id": "spot-id",
            "title": "$BTC у верхней границы диапазона",
            "text": ("На четырёхчасовом графике верхняя отметка составляет 99000 USDT.\n\n"
                     "На часовом графике $BTC вырос за час на 1.50% и достиг 98500 USDT.\n\n"
                     "После резкого движения стоит дождаться закрытия свечи для проверки уровня."),
            "plan": {"direction": "long", "entry": ["high_1h"], "targets": ["high_4h", "high_24h"], "stop": "low_1h"},
            "closing": "Следующий час покажет, сохранится ли импульс. Какой уровень вы бы отслеживали?",
            "image_base64": base64.b64encode(raw.getvalue()).decode(),
        }
        self.save()
        self.git = patch.object(bridge, "git", side_effect=self.git_response).start()
        self.addCleanup(patch.stopall)

    def git_response(self, root, *args):
        return json.dumps(self.snapshot) if args[0] == "show" else ""

    def save(self):
        atomic_write_json(self.root / "bridge/draft.json", self.draft)

    def test_preview_preserves_text_and_image_without_send(self):
        with patch("publisher.publish") as send:
            bridge.deliver(self.root, self.output, live=False)
        send.assert_not_called()
        text = (self.output / "post.txt").read_text()
        self.assertLess(text.index("Лонг рассматриваю"), text.index("Какой уровень"))
        self.assertIn("TP2 — 100000 USDT, максимум последних суток", text)
        self.assertFalse(final_text_reasons(text))
        self.assertEqual((self.output / "title.txt").read_text().strip(), self.draft["title"])
        self.assertTrue((self.output / "post.jpg").exists())

    def test_stale_snapshot_is_not_delivered(self):
        self.snapshot["created_at"] = (self.now - timedelta(minutes=46)).isoformat()
        with patch("publisher.publish") as send:
            bridge.deliver(self.root, self.output, live=True)
        send.assert_not_called()

    def test_preview_only_draft_cannot_be_published(self):
        self.draft["preview_only"] = True
        self.save()
        with patch("publisher.publish") as send:
            bridge.deliver(self.root, self.output, live=True)
        send.assert_not_called()
        self.assertFalse((self.root / "bridge/receipts").exists())

    def test_market_article_requires_one_plan(self):
        self.draft.pop("plan")
        self.save()
        with self.assertRaisesRegex(ValueError, "conditional long or short"):
            bridge.deliver(self.root, self.output, live=False)

    def test_plan_is_a_single_paragraph_before_conclusion_and_question(self):
        self.draft["closing"] = ("Следующий час покажет, сохранится ли импульс.\n\n"
                                 "Что подтвердит выход из диапазона?")
        self.save()
        bridge.deliver(self.root, self.output, live=False)
        text = (self.output / "post.txt").read_text()
        plan = next(paragraph for paragraph in text.split("\n\n") if "Вход" in paragraph)
        self.assertNotIn("\n", plan)
        self.assertIn("TP2", plan)
        self.assertIn("Стоп-лосс", plan)
        self.assertIn("импульс.\n\nЧто подтвердит", text)

    def test_list_marker_is_rejected(self):
        self.draft["text"] = "• " + self.draft["text"]
        self.save()
        with self.assertRaisesRegex(ValueError, "Lists are not allowed"):
            bridge.deliver(self.root, self.output, live=False)

    def test_missing_cover_cannot_fall_back_to_a_chart(self):
        self.draft["image_base64"] = ""
        self.save()
        with patch("publisher.publish") as send, self.assertRaisesRegex(ValueError, "cover"):
            bridge.deliver(self.root, self.output, live=True)
        send.assert_not_called()
        self.assertFalse((self.root / "bridge/receipts").exists())

    def test_inverted_plan_is_rejected(self):
        self.draft["plan"]["direction"] = "short"
        self.save()
        with self.assertRaisesRegex(ValueError, "inconsistent"):
            bridge.deliver(self.root, self.output, live=False)

    def test_news_article_needs_cover_but_no_trade_plan(self):
        self.story["kind"] = "news"
        self.story["headline"] = "Binance expands spot fee rebates"
        self.story["source_text"] = "Binance announced lower spot fees for selected pairs in a statement released today."
        self.draft.update(
            title="$BTC и торговые комиссии Binance",
            text=("Binance объявила о снижении комиссий для отдельных спотовых пар. "
                  "Для читателей $BTC важен список пар, к которым применяется это изменение."),
            evidence_quote="Binance announced lower spot fees for selected pairs",
        )
        self.draft.pop("plan")
        self.save()
        with patch("publisher.publish") as send:
            bridge.deliver(self.root, self.output, live=False)
        send.assert_not_called()
        self.assertNotIn("TP1", (self.output / "post.txt").read_text())
        self.assertTrue((self.output / "post.jpg").exists())

    def test_legacy_draft_does_not_publish(self):
        self.draft["schema"] = 1
        self.save()
        with patch("publisher.publish") as send:
            bridge.deliver(self.root, self.output, live=True)
        send.assert_not_called()

    def test_claim_is_saved_before_send_and_blocks_duplicates(self):
        def send(*args, **kwargs):
            receipt = next((self.root / "bridge/receipts").glob("*.json"))
            self.assertEqual(bridge.read_json(receipt)["status"], "claimed")
            self.assertTrue(Path(kwargs["image_path"]).exists())
            self.assertEqual(kwargs["article_title"], self.draft["title"])
            return PublishResult(True, "123")
        with patch.dict("os.environ", {"SQUARE_API": "test"}), \
                patch("publisher.find_skill_dir", return_value="local"), \
                patch("publisher.publish", side_effect=send) as publish:
            bridge.deliver(self.root, self.output, live=True)
            bridge.deliver(self.root, self.output, live=True)
        publish.assert_called_once()
        self.assertEqual(bridge.read_json(next((self.root / "bridge/receipts").glob("*.json")))["post_id"], "123")


if __name__ == "__main__":
    unittest.main()
