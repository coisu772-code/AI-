from __future__ import annotations

import json
import sys
import tempfile
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
MCP_ROOT = ROOT / "plugins" / "ai-video-channel-production" / "mcp"
if str(MCP_ROOT) not in sys.path:
    sys.path.insert(0, str(MCP_ROOT))

from aivcp_tools.errors import ToolError  # noqa: E402
from aivcp_tools.workshop_bridge import WorkshopBridge  # noqa: E402


class _Completed:
    def __init__(self, returncode: int = 0, stdout: str = "", stderr: str = "") -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


class _RunningProcess:
    pid = 4242

    def poll(self) -> None:
        return None


class WorkshopBridgeTests(unittest.TestCase):
    PACKAGE_HASH = "a" * 64
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.executable = self.root / "workshop.exe"
        self.executable.write_bytes(b"fixture executable")
        self.isolation = self.root / "isolated"
        self.bridge = WorkshopBridge(self.executable, self.isolation)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    @staticmethod
    def _write_result(argv: list[str], payload: dict) -> _Completed:
        result_path = Path(argv[argv.index("--result-file") + 1])
        result_path.write_text(json.dumps(payload), encoding="utf-8")
        return _Completed()

    def _write_package_manifest(self, package: Path, project_id: str = "fixture-project") -> None:
        package.mkdir(exist_ok=True)
        (package / "manifest.json").write_text(
            json.dumps(
                {
                    "schemaVersion": "2.1",
                    "projectId": project_id,
                    "packageVersion": "v001",
                    "packageHash": self.PACKAGE_HASH,
                }
            ),
            encoding="utf-8",
        )

    def _official_import_meta(self) -> dict:
        return {
            "source": "production_package",
            "schemaVersion": "2.1",
            "packageVersion": "v001",
            "packageHash": self.PACKAGE_HASH,
            "contentLocked": True,
            "roundTripValidated": True,
        }

    def test_health_check_is_read_only_and_redacts_local_paths(self) -> None:
        def fake_run(argv: list[str], **_kwargs: object) -> _Completed:
            self.assertEqual("health-check", argv[1])
            return self._write_result(
                argv,
                {
                    "success": True,
                    "application": "Z Manga Workshop",
                    "version": "1.0.0",
                    "frontendEmbedded": True,
                    "ffmpegAvailable": True,
                    "ffmpegPath": "C:/private/ffmpeg.exe",
                    "ffprobePath": "C:/private/ffprobe.exe",
                },
            )

        with patch("aivcp_tools.workshop_bridge.subprocess.run", side_effect=fake_run):
            result = self.bridge.health_check()
        self.assertTrue(result["ffmpegAvailable"])
        self.assertTrue(result["ffmpegPathSet"])
        self.assertNotIn("C:/private", json.dumps(result))
        self.assertEqual("read_only_no_external_services", result["boundary"])

    def test_capabilities_forces_no_probe(self) -> None:
        def fake_run(argv: list[str], **_kwargs: object) -> _Completed:
            self.assertEqual("get-production-capabilities", argv[1])
            self.assertIn("--no-probe", argv)
            return self._write_result(
                argv,
                {
                    "success": True,
                    "voiceEngines": [{"engine": "fixture", "available": False}],
                    "supportedPackageVersions": ["2.1"],
                    "supportedCodexVisualPlanSchemas": ["1.3", "1.4", "1.5"],
                },
            )

        with patch("aivcp_tools.workshop_bridge.subprocess.run", side_effect=fake_run):
            result = self.bridge.capabilities()
        self.assertFalse(result["externalServiceProbeExecuted"])
        self.assertEqual(["2.1"], result["supportedPackageVersions"])
        self.assertEqual(["1.3", "1.4", "1.5"], result["supportedCodexVisualPlanSchemas"])

    def test_import_is_limited_to_isolation_and_preserves_duplicate_flag(self) -> None:
        package = self.root / "production-package"
        self._write_package_manifest(package)
        target = self.isolation / "workshop-project"

        def fake_run(argv: list[str], **_kwargs: object) -> _Completed:
            project_path = target / "novel_manga_project.json"
            project_path.write_text(
                json.dumps(
                    {
                        "id": "fixture-project",
                        "importMeta": self._official_import_meta(),
                    }
                ),
                encoding="utf-8",
            )
            return self._write_result(
                argv,
                {
                    "success": True,
                    "projectId": "fixture-project",
                    "projectName": "Fixture",
                    "projectPath": str(target / "novel_manga_project.json"),
                    "episodesImported": 1,
                    "charactersImported": 2,
                    "scriptLinesImported": 3,
                    "duplicate": True,
                    "packageVersion": "v001",
                    "packageHash": self.PACKAGE_HASH,
                    "roundTripValidated": True,
                    "warnings": [],
                },
            )

        with patch("aivcp_tools.workshop_bridge.subprocess.run", side_effect=fake_run):
            result = self.bridge.import_package(package, target, expected_project_id="fixture-project")
        self.assertTrue(result["duplicate"])
        self.assertFalse(result["publishingTriggered"])

    def test_import_rejects_target_outside_isolation_before_process_start(self) -> None:
        package = self.root / "production-package"
        self._write_package_manifest(package)
        with patch("aivcp_tools.workshop_bridge.subprocess.run") as run:
            with self.assertRaises(ToolError) as caught:
                self.bridge.import_package(
                    package,
                    self.root / "real-projects",
                    expected_project_id="fixture-project",
                )
        self.assertEqual("WORKSHOP_TARGET_NOT_ISOLATED", caught.exception.code)
        run.assert_not_called()

    def test_import_rejects_publisher_ready_package(self) -> None:
        package = self.root / "publisher-package.ready"
        self._write_package_manifest(package)
        with patch("aivcp_tools.workshop_bridge.subprocess.run") as run:
            with self.assertRaises(ToolError) as caught:
                self.bridge.import_package(
                    package,
                    self.isolation / "workshop-project",
                    expected_project_id="fixture",
                )
        self.assertEqual("PUBLISHING_PACKAGE_FORBIDDEN", caught.exception.code)
        run.assert_not_called()

    def test_import_rejects_project_identity_mismatch(self) -> None:
        package = self.root / "production-package"
        self._write_package_manifest(package)
        target = self.isolation / "workshop-project"

        def fake_run(argv: list[str], **_kwargs: object) -> _Completed:
            return self._write_result(
                argv,
                {
                    "success": True,
                    "projectId": "wrong-project",
                    "projectPath": str(target / "novel_manga_project.json"),
                },
            )

        with patch("aivcp_tools.workshop_bridge.subprocess.run", side_effect=fake_run):
            with self.assertRaises(ToolError) as caught:
                self.bridge.import_package(package, target, expected_project_id="fixture-project")
        self.assertEqual("WORKSHOP_IMPORT_PROJECT_MISMATCH", caught.exception.code)

    def test_policy_has_no_publish_or_upload_escape_hatch(self) -> None:
        with self.assertRaises(ToolError) as caught:
            self.bridge._run_json("assemble-youtube-publish-package", [])
        self.assertEqual("WORKSHOP_COMMAND_FORBIDDEN", caught.exception.code)

    def test_start_production_uses_direct_argv_and_isolated_project(self) -> None:
        project = self.isolation / "workshop-project" / "novel_manga_project.json"
        project.parent.mkdir(parents=True)
        project.write_text(
            json.dumps({
                "id": "fixture-project",
                "importMeta": {
                    **self._official_import_meta(),
                    "productionContract": {"gridBatch": {"template": "wide_16_9_1"}},
                },
            }),
            encoding="utf-8",
        )

        def fake_popen(argv: list[str], **_kwargs: object) -> _RunningProcess:
            self.assertEqual("run-production", argv[1])
            self.assertIn("--auto-start", argv)
            self.assertIn("audio,storyboard", argv)
            self.assertEqual("wide_16_9_1", argv[argv.index("--grid-template") + 1])
            result_path = Path(argv[argv.index("--result-file") + 1])
            result_path.write_text(
                json.dumps({"success": True, "processId": 4242, "forwarded": True, "status": "accepted"}),
                encoding="utf-8",
            )
            return _RunningProcess()

        with patch("aivcp_tools.workshop_bridge.subprocess.Popen", side_effect=fake_popen):
            result = self.bridge.start_production(
                project,
                selected_step_ids=["audio", "storyboard"],
                selected_episode_ids=["ep_001"],
                request_id="task-run-001",
                expected_project_id="fixture-project",
            )
        self.assertEqual(4242, result["processId"])
        self.assertTrue(result["forwarded"])
        self.assertFalse(result["publishingTriggered"])

    def test_start_production_reuses_running_project_without_new_process(self) -> None:
        project = self.isolation / "workshop-project" / "novel_manga_project.json"
        project.parent.mkdir(parents=True)
        project.write_text(
            json.dumps(
                {
                    "id": "fixture-project",
                    "importMeta": self._official_import_meta(),
                    "autoProductionTask": {
                        "externalRequestId": "task-existing-001",
                        "status": "running",
                        "selectedStepIds": ["audio"],
                        "selectedEpisodeIds": ["ep_001"],
                    },
                }
            ),
            encoding="utf-8",
        )
        with patch("aivcp_tools.workshop_bridge.subprocess.Popen") as popen:
            result = self.bridge.start_production(
                project,
                selected_step_ids=["audio"],
                request_id="task-new-002",
                expected_project_id="fixture-project",
            )
        popen.assert_not_called()
        self.assertEqual("already_running", result["status"])
        self.assertEqual("task-existing-001", result["requestId"])
        self.assertTrue(result["joinedExisting"])

    def test_start_timeout_keeps_lease_and_blocks_duplicate_process(self) -> None:
        project = self.isolation / "workshop-project" / "novel_manga_project.json"
        project.parent.mkdir(parents=True)
        project.write_text(
            json.dumps({"id": "fixture-project", "importMeta": self._official_import_meta()}),
            encoding="utf-8",
        )
        with patch("aivcp_tools.workshop_bridge.subprocess.Popen", return_value=_RunningProcess()) as popen:
            first = self.bridge.start_production(
                project,
                selected_step_ids=["audio"],
                request_id="task-pending-001",
                expected_project_id="fixture-project",
                startup_timeout_seconds=1,
            )
            second = self.bridge.start_production(
                project,
                selected_step_ids=["audio"],
                request_id="task-pending-002",
                expected_project_id="fixture-project",
                startup_timeout_seconds=1,
            )
        self.assertEqual(1, popen.call_count)
        self.assertEqual("start_pending", first["status"])
        self.assertEqual("start_pending", second["status"])
        self.assertEqual("task-pending-001", second["requestId"])
        self.assertFalse(first["startConfirmed"])

    def test_different_projects_share_one_global_workshop_owner(self) -> None:
        owner = self.isolation / "owner-project" / "novel_manga_project.json"
        waiting = self.isolation / "waiting-project" / "novel_manga_project.json"
        owner.parent.mkdir(parents=True)
        waiting.parent.mkdir(parents=True)
        owner.write_text(
            json.dumps({"id": "owner-project", "importMeta": self._official_import_meta()}),
            encoding="utf-8",
        )
        waiting.write_text(
            json.dumps({"id": "waiting-project", "importMeta": self._official_import_meta()}),
            encoding="utf-8",
        )

        def fake_popen(argv: list[str], **_kwargs: object) -> _RunningProcess:
            result_path = Path(argv[argv.index("--result-file") + 1])
            result_path.write_text(
                json.dumps({"success": True, "processId": 4242, "forwarded": True, "status": "accepted"}),
                encoding="utf-8",
            )
            return _RunningProcess()

        with patch("aivcp_tools.workshop_bridge.subprocess.Popen", side_effect=fake_popen) as popen:
            self.bridge.start_production(
                owner,
                selected_step_ids=["audio"],
                request_id="owner-request-001",
                expected_project_id="owner-project",
            )
            with self.assertRaises(ToolError) as caught:
                self.bridge.start_production(
                    waiting,
                    selected_step_ids=["audio"],
                    request_id="waiting-request-001",
                    expected_project_id="waiting-project",
                )
        self.assertEqual("WORKSHOP_BUSY", caught.exception.code)
        self.assertTrue(caught.exception.retryable)
        self.assertEqual("owner-project", caught.exception.details["ownerProjectId"])
        self.assertEqual(1, popen.call_count)

    def test_simultaneous_different_project_claims_launch_exactly_one_process(self) -> None:
        projects: list[Path] = []
        for project_id in ("project-a", "project-b"):
            project = self.isolation / project_id / "novel_manga_project.json"
            project.parent.mkdir(parents=True)
            project.write_text(
                json.dumps({"id": project_id, "importMeta": self._official_import_meta()}),
                encoding="utf-8",
            )
            projects.append(project)

        def fake_popen(argv: list[str], **_kwargs: object) -> _RunningProcess:
            result_path = Path(argv[argv.index("--result-file") + 1])
            result_path.write_text(
                json.dumps({"success": True, "processId": 4242, "forwarded": True, "status": "accepted"}),
                encoding="utf-8",
            )
            return _RunningProcess()

        def start(index: int) -> str:
            try:
                result = self.bridge.start_production(
                    projects[index],
                    selected_step_ids=["audio"],
                    request_id=f"request-{index}",
                    expected_project_id=f"project-{'a' if index == 0 else 'b'}",
                )
                return str(result.get("status") or "accepted")
            except ToolError as exc:
                return exc.code

        with patch("aivcp_tools.workshop_bridge.subprocess.Popen", side_effect=fake_popen) as popen:
            with ThreadPoolExecutor(max_workers=2) as executor:
                outcomes = list(executor.map(start, (0, 1)))
        self.assertEqual(1, sum(outcome == "WORKSHOP_BUSY" for outcome in outcomes))
        self.assertEqual(1, sum(outcome == "accepted" for outcome in outcomes))
        self.assertEqual(1, popen.call_count)

    def test_next_project_starts_after_global_owner_snapshot_completes(self) -> None:
        owner = self.isolation / "owner-project" / "novel_manga_project.json"
        next_project = self.isolation / "next-project" / "novel_manga_project.json"
        owner.parent.mkdir(parents=True)
        next_project.parent.mkdir(parents=True)
        owner.write_text(
            json.dumps({"id": "owner-project", "importMeta": self._official_import_meta()}),
            encoding="utf-8",
        )
        next_project.write_text(
            json.dumps({"id": "next-project", "importMeta": self._official_import_meta()}),
            encoding="utf-8",
        )

        def fake_popen(argv: list[str], **_kwargs: object) -> _RunningProcess:
            result_path = Path(argv[argv.index("--result-file") + 1])
            result_path.write_text(
                json.dumps({"success": True, "processId": 4242, "forwarded": True, "status": "accepted"}),
                encoding="utf-8",
            )
            return _RunningProcess()

        with patch("aivcp_tools.workshop_bridge.subprocess.Popen", side_effect=fake_popen) as popen:
            self.bridge.start_production(
                owner,
                selected_step_ids=["audio"],
                request_id="owner-request-001",
                expected_project_id="owner-project",
            )
            owner.write_text(
                json.dumps(
                    {
                        "id": "owner-project",
                        "importMeta": self._official_import_meta(),
                        "autoProductionTask": {
                            "externalRequestId": "owner-request-001",
                            "status": "completed",
                        },
                    }
                ),
                encoding="utf-8",
            )
            started = self.bridge.start_production(
                next_project,
                selected_step_ids=["audio"],
                request_id="next-request-001",
                expected_project_id="next-project",
            )
        self.assertEqual("next-request-001", started["requestId"])
        self.assertEqual(2, popen.call_count)

    def test_stale_crashed_owner_is_recovered_before_next_project_launch(self) -> None:
        stale = self.isolation / "stale-project" / "novel_manga_project.json"
        next_project = self.isolation / "next-project" / "novel_manga_project.json"
        stale.parent.mkdir(parents=True)
        next_project.parent.mkdir(parents=True)
        stale.write_text(
            json.dumps({"id": "stale-project", "importMeta": self._official_import_meta()}),
            encoding="utf-8",
        )
        next_project.write_text(
            json.dumps({"id": "next-project", "importMeta": self._official_import_meta()}),
            encoding="utf-8",
        )
        lease_path = self.bridge._start_lease_path(stale)
        lease_path.write_text(
            json.dumps(
                {
                    "requestId": "stale-request",
                    "projectId": "stale-project",
                    "projectPath": str(stale),
                    "processId": 0,
                    "createdAtEpoch": time.time() - 3600,
                    "updatedAtEpoch": time.time() - 3600,
                    "status": "start_pending",
                }
            ),
            encoding="utf-8",
        )

        def fake_popen(argv: list[str], **_kwargs: object) -> _RunningProcess:
            result_path = Path(argv[argv.index("--result-file") + 1])
            result_path.write_text(
                json.dumps({"success": True, "processId": 4242, "forwarded": True, "status": "accepted"}),
                encoding="utf-8",
            )
            return _RunningProcess()

        with patch("aivcp_tools.workshop_bridge.subprocess.Popen", side_effect=fake_popen) as popen:
            started = self.bridge.start_production(
                next_project,
                selected_step_ids=["audio"],
                request_id="next-request",
                expected_project_id="next-project",
            )
        self.assertEqual("next-request", started["requestId"])
        self.assertEqual(1, popen.call_count)

    def test_production_status_is_read_only(self) -> None:
        project = self.isolation / "workshop-project" / "novel_manga_project.json"
        project.parent.mkdir(parents=True)
        project.write_text(
            json.dumps(
                {
                    "id": "fixture-project",
                    "importMeta": self._official_import_meta(),
                    "autoProductionTask": {
                        "id": "workshop-task-1",
                        "externalRequestId": "task-run-001",
                        "status": "paused",
                        "currentEpisodeId": "ep_001",
                        "currentStepId": "audio",
                        "selectedStepIds": ["audio"],
                        "selectedEpisodeIds": ["ep_001"],
                        "episodeStates": {"ep_001": {"audio": "failed"}},
                    },
                }
            ),
            encoding="utf-8",
        )
        before = project.read_bytes()
        result = self.bridge.production_status(
            project,
            expected_project_id="fixture-project",
            expected_request_id="task-run-001",
        )
        after = project.read_bytes()
        self.assertEqual(before, after)
        self.assertTrue(result["readOnly"])
        self.assertEqual("paused", result["status"])

    def test_start_production_rejects_publish_named_step(self) -> None:
        project = self.isolation / "workshop-project" / "novel_manga_project.json"
        project.parent.mkdir(parents=True)
        project.write_text(
            json.dumps({"id": "fixture-project", "importMeta": self._official_import_meta()}),
            encoding="utf-8",
        )
        with patch("aivcp_tools.workshop_bridge.subprocess.Popen") as popen:
            with self.assertRaises(ToolError) as caught:
                self.bridge.start_production(project, selected_step_ids=["publish"])
        self.assertEqual("WORKSHOP_COMMAND_FORBIDDEN", caught.exception.code)
        popen.assert_not_called()

    def test_start_production_rejects_legacy_manual_project(self) -> None:
        project = self.isolation / "manual-project" / "novel_manga_project.json"
        project.parent.mkdir(parents=True)
        project.write_text(json.dumps({"id": "fixture-project"}), encoding="utf-8")
        with patch("aivcp_tools.workshop_bridge.subprocess.Popen") as popen:
            with self.assertRaises(ToolError) as caught:
                self.bridge.start_production(
                    project,
                    selected_step_ids=["audio"],
                    expected_project_id="fixture-project",
                )
        self.assertEqual("WORKSHOP_COMPATIBILITY_PROJECT_FORBIDDEN", caught.exception.code)
        popen.assert_not_called()

    def test_production_status_rejects_stale_workshop_run(self) -> None:
        project = self.isolation / "workshop-project" / "novel_manga_project.json"
        project.parent.mkdir(parents=True)
        project.write_text(
            json.dumps(
                {
                    "id": "fixture-project",
                    "importMeta": self._official_import_meta(),
                    "autoProductionTask": {
                        "externalRequestId": "old-run",
                        "status": "running",
                    },
                }
            ),
            encoding="utf-8",
        )
        before = project.read_bytes()
        with self.assertRaises(ToolError) as caught:
            self.bridge.production_status(
                project,
                expected_project_id="fixture-project",
                expected_request_id="current-run",
            )
        self.assertEqual("WORKSHOP_STATUS_TASK_MISMATCH", caught.exception.code)

    def test_completed_artifacts_are_isolated_real_and_traceable(self) -> None:
        project = self.isolation / "workshop-project" / "novel_manga_project.json"
        project.parent.mkdir(parents=True)
        image_a = project.parent / "scene-a.png"
        image_b = project.parent / "scene-b.png"
        image_a.write_bytes(b"real storyboard image a")
        image_b.write_bytes(b"real storyboard image b")
        upload = project.parent / "upload-package"
        report_dir = upload / "05-report"
        report_dir.mkdir(parents=True)
        video = upload / "final.mp4"
        subtitles = upload / "subtitles.srt"
        video.write_bytes(b"real workshop mp4 fixture")
        subtitles.write_text("1\n00:00:00,000 --> 00:00:01,000\nline one\n", encoding="utf-8")
        report = {
            "status": "completed",
            "videoPath": str(video),
            "subtitlePath": str(subtitles),
            "sceneCount": 2,
            "subtitleCount": 1,
            "durationSec": 1.0,
            "resolution": "1920x1080",
            "renderHash": "b" * 64,
        }
        (report_dir / "upload_package_report.json").write_text(json.dumps(report), encoding="utf-8")
        project.write_text(
            json.dumps(
                {
                    "id": "fixture-project",
                    "importMeta": self._official_import_meta(),
                    "autoProductionTask": {
                        "id": "workshop-task-1",
                        "externalRequestId": "task-run-001",
                        "status": "completed",
                    },
                    "lastFinalVideoPath": str(video),
                    "lastUploadPackagePath": str(upload),
                    "scenes": [
                        {"id": "scene-a", "splitImagePath": str(image_a)},
                        {"id": "scene-b", "splitImagePath": str(image_b)},
                    ],
                    "scriptLines": [{"id": "line-1", "durationSec": 1.0, "audioPath": "audio.wav"}],
                }
            ),
            encoding="utf-8",
        )
        before = project.read_bytes()
        result = self.bridge.production_artifacts(
            project,
            expected_project_id="fixture-project",
            expected_request_id="task-run-001",
        )
        self.assertEqual(before, project.read_bytes())
        self.assertEqual("workshop", result["provenance"])
        self.assertEqual(2, len(result["storyboardImages"]))
        self.assertEqual(2, len({item["sha256"] for item in result["storyboardImages"]}))
        self.assertFalse(result["publishingTriggered"])
        self.assertEqual(before, project.read_bytes())

    def test_completed_artifacts_allow_explicit_no_subtitle_result(self) -> None:
        project = self.isolation / "workshop-project" / "novel_manga_project.json"
        project.parent.mkdir(parents=True)
        image = project.parent / "scene.png"
        image.write_bytes(b"real storyboard image")
        upload = project.parent / "upload-package"
        report_dir = upload / "05-report"
        report_dir.mkdir(parents=True)
        video = upload / "final.mp4"
        video.write_bytes(b"real workshop mp4 fixture")
        report = {
            "status": "completed",
            "videoPath": str(video),
            "subtitlePath": "",
            "subtitleMode": "none",
            "subtitleCount": 0,
            "sceneCount": 1,
            "durationSec": 1.0,
            "resolution": "1920x1080",
            "renderHash": "c" * 64,
        }
        (report_dir / "upload_package_report.json").write_text(json.dumps(report), encoding="utf-8")
        project.write_text(
            json.dumps(
                {
                    "id": "fixture-project",
                    "importMeta": self._official_import_meta(),
                    "exportSettings": {"includeSubtitles": False},
                    "autoProductionTask": {
                        "id": "workshop-task-1",
                        "externalRequestId": "task-run-no-subtitles",
                        "status": "completed",
                    },
                    "lastFinalVideoPath": str(video),
                    "lastUploadPackagePath": str(upload),
                    "scenes": [{"id": "scene", "splitImagePath": str(image)}],
                    "scriptLines": [{"id": "line-1", "durationSec": 1.0, "audioPath": "audio.wav"}],
                }
            ),
            encoding="utf-8",
        )
        result = self.bridge.production_artifacts(
            project,
            expected_project_id="fixture-project",
            expected_request_id="task-run-no-subtitles",
        )
        self.assertEqual("", result["subtitlePath"])
        self.assertEqual(str(video.resolve()), result["finalVideoPath"])


if __name__ == "__main__":
    unittest.main()
