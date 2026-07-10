"""離線測試：extraction 失敗的 GUID 不可被標記為已處理。

不打任何 LLM API — extract_events / fetch_all_feeds 全部以假物件替換。
執行方式: python tests/test_fetch_state.py
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import extractor
import fetch
from models import ExtractedEvent, ExtractedEventList, RSSItem

FEED_CFG = {"name": "Test-Feed", "url": "http://example.invalid/rss", "lang": "en", "type": "digest"}


def make_item(guid: str) -> RSSItem:
    return RSSItem(
        source_name="Test-Feed",
        guid=guid,
        title=f"Title for {guid}",
        link=f"http://example.invalid/{guid}",
        pub_date=datetime(2026, 7, 10, tzinfo=timezone.utc),
        content="Some article content long enough to pass filters.",
    )


def make_event() -> ExtractedEvent:
    return ExtractedEvent(
        company="TestCorp",
        product="TestProduct",
        action="release",
        headline="TestCorp releases TestProduct",
        summary="TestCorp released TestProduct. It matters for tests.",
        significance=2,
        tags=["model-release"],
    )


class FetchStateTest(unittest.TestCase):
    """fetch.main 的 processed-marking 邏輯。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        tmp_path = Path(self.tmp.name)
        self._orig = {
            "STATE_DIR": fetch.STATE_DIR,
            "STATE_FILE": fetch.STATE_FILE,
            "VAULT_PATH": fetch.VAULT_PATH,
            "extract_events": fetch.extract_events,
            "fetch_all_feeds": fetch.fetch_all_feeds,
        }
        fetch.STATE_DIR = tmp_path / "state"
        fetch.STATE_FILE = fetch.STATE_DIR / "processed.json"
        fetch.VAULT_PATH = tmp_path / "vault"

    def tearDown(self):
        for name, value in self._orig.items():
            setattr(fetch, name, value)
        self.tmp.cleanup()

    def _run_main(self, results_by_guid: dict):
        """跑 fetch.main，results_by_guid: guid -> list | None（None = 模擬提取失敗）。"""
        items = [make_item(g) for g in results_by_guid]
        fetch.fetch_all_feeds = lambda processed: [(FEED_CFG, items)]
        fetch.extract_events = lambda cfg, item: results_by_guid[item.guid]
        fetch.main(dry_run=False)
        return set(json.loads(fetch.STATE_FILE.read_text(encoding="utf-8"))["processed_guids"])

    def test_failed_extraction_guid_not_persisted(self):
        """失敗的 GUID 不落地；成功（零事件）的 GUID 照常落地。"""
        processed = self._run_main({"guid-fail": None, "guid-zero-events": []})
        self.assertNotIn("guid-fail", processed)
        self.assertIn("guid-zero-events", processed)

    def test_failed_guid_not_persisted_on_full_write_path(self):
        """有事件寫入 vault 的完整路徑上，失敗的 GUID 一樣不落地。"""
        processed = self._run_main({"guid-fail-2": None, "guid-with-event": [make_event()]})
        self.assertNotIn("guid-fail-2", processed)
        self.assertIn("guid-with-event", processed)
        self.assertTrue(any((fetch.VAULT_PATH / "Events").glob("*TestCorp*.md")))

    def test_all_failed_state_untouched(self):
        """全部失敗 → 不新增任何 GUID。"""
        processed = self._run_main({"guid-a": None, "guid-b": None})
        self.assertEqual(processed, set())


class ExtractorFailureSignalTest(unittest.TestCase):
    """extractor.extract_events 的失敗訊號：raise → None，成功零事件 → []。"""

    def tearDown(self):
        extractor.call_llm = self._orig_call_llm

    def setUp(self):
        self._orig_call_llm = extractor.call_llm

    def test_llm_exception_returns_none(self):
        def boom(prompt, schema):
            raise RuntimeError("simulated LLM failure (offline)")

        extractor.call_llm = boom
        self.assertIsNone(extractor.extract_events(FEED_CFG, make_item("g1")))

    def test_zero_events_returns_empty_list(self):
        extractor.call_llm = lambda prompt, schema: ExtractedEventList(events=[])
        self.assertEqual(extractor.extract_events(FEED_CFG, make_item("g2")), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
