from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MCP_ROOT = ROOT / "plugins" / "ai-video-channel-production" / "mcp"
if str(MCP_ROOT) not in sys.path:
    sys.path.insert(0, str(MCP_ROOT))

from aivcp_tools.production import ProductionCenter, _classify_workshop_error  # noqa: E402


class ProductionHistoryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.center = ProductionCenter(Path(self.temporary.name))
        self.task_id = "history-test"
        self.center._task_root(self.task_id).mkdir(parents=True)
        self.task = {
            "schemaVersion": "1.0.0",
            "productionTaskId": self.task_id,
            "state": "RUNNING",
            "revision": 0,
            "history": [],
            "queue": {"schemaVersion": "2.0", "status": "RUNNING"},
        }

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_repeated_workshop_observations_are_coalesced(self) -> None:
        details = {"status": "running", "taskPresent": True, "requestId": "request-1"}
        self.center._save_task(self.task, event="WORKSHOP_STATUS_OBSERVED", details=details)
        self.center._save_task(self.task, event="WORKSHOP_STATUS_OBSERVED", details=details)
        stored = json.loads(self.center._task_path(self.task_id).read_text(encoding="utf-8"))
        self.assertEqual(1, stored["revision"])
        self.assertEqual(1, len(stored["history"]))
        self.assertEqual(1, stored["historySummary"]["suppressedDuplicateEvents"]["WORKSHOP_STATUS_OBSERVED"])
        self.assertEqual(2, stored["eventCoalescing"]["WORKSHOP_STATUS_OBSERVED"]["occurrences"])

    def test_history_is_archived_and_read_only_queries_are_paged(self) -> None:
        for index in range(130):
            self.center._save_task(self.task, event=f"SEMANTIC_{index}", details={"index": index})
        stored = json.loads(self.center._task_path(self.task_id).read_text(encoding="utf-8"))
        self.assertEqual(100, len(stored["history"]))
        self.assertEqual(30, stored["historyArchive"]["eventCount"])
        self.assertTrue((self.center._task_root(self.task_id) / "history.ndjson").is_file())

        summary = self.center.get_task(self.task_id)
        self.assertNotIn("history", summary["task"])
        self.assertEqual(130, summary["task"]["historyAvailable"])
        page = self.center.get_task(self.task_id, include_history=True, history_limit=7)
        self.assertEqual(7, len(page["historyPage"]["events"]))
        self.assertTrue(page["historyPage"]["hasMore"])

    def test_prompt_failures_have_actionable_categories(self) -> None:
        partial = _classify_workshop_error("AI 本批仍缺少 2 条有效提示词，继续时只补齐缺失内容")
        self.assertEqual("partial_prompt_generation", partial["category"])
        self.assertTrue(partial["recoverable"])
        exhausted = _classify_workshop_error("PROMPT_RETRY_EXHAUSTED：提示词已达到有限重试上限")
        self.assertEqual("prompt_retry_exhausted", exhausted["category"])
        self.assertFalse(exhausted["recoverable"])
        self.assertEqual("repair_listed_storyboards", exhausted["recommendedAction"])


if __name__ == "__main__":
    unittest.main()
