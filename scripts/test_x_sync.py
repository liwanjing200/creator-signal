import argparse
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import creator_signal


class XSyncTest(unittest.TestCase):
    def test_dry_run_normalizes_public_post(self):
        responses = [
            {"data": {"id": "44196397", "name": "Elon Musk", "username": "elonmusk", "public_metrics": {"followers_count": 1}}},
            {"data": [{"id": "123", "text": "Hello", "created_at": "2026-01-01T00:00:00Z", "public_metrics": {"like_count": 2}}]},
        ]
        args = argparse.Namespace(dry_run=True, force=False, max_videos=3, retries=0, manifest_dir=".")
        creator = {"id": "creator", "name": "elonmusk", "profile_url": "https://x.com/elonmusk", "platform_creator_id": "elonmusk"}
        with patch.object(creator_signal, "x_api", side_effect=responses):
            counts, manifest = creator_signal.crawl_x_creator(None, creator, args)
        self.assertEqual(counts.success, 1)
        self.assertEqual(manifest["records"][0]["post_id"], "123")


if __name__ == "__main__":
    unittest.main()
