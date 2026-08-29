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

from aivcp_tools.production_queue_worker import ProductionQueueDispatcher  # noqa: E402


class _FakeCenter:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.calls: list[str] = []
        self.owner_done = False

    def run_task(self, task_id: str) -> dict:
        self.calls.append(task_id)
        path = self.root / "tasks" / task_id / "production-task.json"
        task = json.loads(path.read_text(encoding="utf-8"))
        if task_id == "task-one":
            task["state"] = "VIDEO_READY" if self.owner_done else "RUNNING"
        else:
            task["state"] = "RUNNING"
        path.write_text(json.dumps(task), encoding="utf-8")
        return {"task": task}


class ProductionQueueWorkerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.production_root = Path(self.temporary.name) / "production"
        self.center = _FakeCenter(self.production_root)
        for index, task_id in enumerate(("task-one", "task-two"), start=1):
            root = self.production_root / "tasks" / task_id
            root.mkdir(parents=True)
            (root / "production-task.json").write_text(
                json.dumps(
                    {
                        "productionTaskId": task_id,
                        "createdAt": f"2026-08-29T00:00:0{index}Z",
                        "state": "READY_TO_PRODUCE",
                        "queue": {"schemaVersion": "2.0", "status": "QUEUED"},
                    }
                ),
                encoding="utf-8",
            )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_second_task_auto_dispatches_after_owner_terminal_without_second_run_request(self) -> None:
        dispatcher = ProductionQueueDispatcher(self.center)
        first = dispatcher.process_once()
        self.assertEqual("task-one", first["productionTaskId"])
        self.assertEqual(["task-one"], self.center.calls)
        blocked = dispatcher.process_once()
        self.assertEqual("task-one", blocked["productionTaskId"])
        self.center.owner_done = True
        completed = dispatcher.process_once()
        self.assertEqual("VIDEO_READY", completed["state"])
        next_item = dispatcher.process_once()
        self.assertEqual("task-two", next_item["productionTaskId"])
        self.assertEqual("RUNNING", next_item["state"])

    def test_old_tasks_are_not_migrated_or_dispatched(self) -> None:
        legacy_root = self.production_root / "tasks" / "legacy-task"
        legacy_root.mkdir(parents=True)
        (legacy_root / "production-task.json").write_text(
            json.dumps({"productionTaskId": "legacy-task", "createdAt": "2020", "state": "READY_TO_PRODUCE"}),
            encoding="utf-8",
        )
        dispatcher = ProductionQueueDispatcher(self.center)
        dispatcher.process_once()
        self.assertNotIn("legacy-task", self.center.calls)

    def test_same_wake_cycle_drains_completed_owner_and_starts_next_task(self) -> None:
        self.center.owner_done = True
        dispatcher = ProductionQueueDispatcher(self.center)
        drained = dispatcher.drain_until_blocked()
        self.assertEqual("drained", drained["action"])
        self.assertEqual(2, drained["dispatchCount"])
        self.assertTrue(drained["laneBlocked"])
        self.assertEqual("task-two", drained["lastResult"]["productionTaskId"])
        self.assertEqual(["task-one", "task-two"], self.center.calls)


if __name__ == "__main__":
    unittest.main()
