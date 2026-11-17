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
        self.snapshot = {"schema": 1, "created_at": self.now.isoformat(), "stories": [self.story]}
        raw = BytesIO()
        Image.new("RGB", (32, 24), "blue").save(raw, "JPEG")
        self.draft = {
            "schema": 1, "source_commit": self.sha, "created_at": self.now.isoformat(), "story_id": "spot-id",
            "text": ("$BTC вырос за час на 1.50%. После резкого движения стоит дождаться закрытия "
                     "следующей свечи и проверить, сохранится ли этот импульс."),
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
        self.assertIn("импульс", (self.output / "post.txt").read_text())
        self.assertTrue((self.output / "post.jpg").exists())

    def test_stale_snapshot_is_not_delivered(self):
        self.snapshot["created_at"] = (self.now - timedelta(minutes=46)).isoformat()
        with patch("publisher.publish") as send:
            bridge.deliver(self.root, self.output, live=True)
        send.assert_not_called()

    def test_claim_is_saved_before_send_and_blocks_duplicates(self):
        def send(*args, **kwargs):
            receipt = next((self.root / "bridge/receipts").glob("*.json"))
            self.assertEqual(bridge.read_json(receipt)["status"], "claimed")
            self.assertTrue(Path(kwargs["image_path"]).exists())
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
