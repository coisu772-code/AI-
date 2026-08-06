from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import time
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PLUGIN_ROOT = ROOT / "plugins" / "ai-video-channel-production"
MCP_ROOT = PLUGIN_ROOT / "mcp"
sys.path.insert(0, str(MCP_ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from aivcp_tools.contracts import with_hash  # noqa: E402
from aivcp_tools.errors import ToolError  # noqa: E402
from aivcp_tools.production import ProductionCenter, production_package_hash  # noqa: E402
from aivcp_tools.service import LocalToolService, ServiceConfig, tool_definitions  # noqa: E402
from stage5_support import (  # noqa: E402
    build_stage5_context,
    export_identity,
    mutation_arguments,
)


THUMBNAIL = ROOT / "contracts" / "examples" / "valid" / "fixtures" / "confirmed-thumbnail-1600x900.png"


class Stage5ProductionHandoffTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="aivcp-stage5-")
        self.root = Path(self.temp.name)
        if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
            self.skipTest("Stage5 requires the installed workshop FFmpeg and ffprobe binaries")

    def tearDown(self) -> None:
        self.temp.cleanup()

    def context(self, language: str = "ja-JP", **kwargs):
        return build_stage5_context(
            self.root / language,
            language,
            plugin_root=PLUGIN_ROOT,
            local_tool_service=LocalToolService,
            service_config=ServiceConfig,
            thumbnail_path=THUMBNAIL,
            **kwargs,
        )

    def assert_tool_error(self, code: str, callback) -> ToolError:
        with self.assertRaises(ToolError) as caught:
            callback()
        self.assertEqual(code, caught.exception.code)
        return caught.exception

    def _package_copy(self, context, name: str) -> Path:
        destination = self.root / "mutations" / name
        shutil.copytree(context.package["packagePath"], destination)
        return destination

    @staticmethod
    def _refresh_package_manifest(root: Path) -> dict:
        manifest_path = root / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        descriptors = []
        import hashlib

        media_types = {".json": "application/json", ".png": "image/png"}
        for path in sorted((item for item in root.rglob("*") if item.is_file() and item.name != "manifest.json"), key=lambda item: item.relative_to(root).as_posix()):
            descriptors.append(
                {
                    "path": path.relative_to(root).as_posix(),
                    "sizeBytes": path.stat().st_size,
                    "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                    "mediaType": media_types.get(path.suffix, "application/octet-stream"),
                }
            )
        manifest["files"] = descriptors
        manifest["packageHash"] = production_package_hash(manifest)
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return manifest

    def _upstream_paths(self, context) -> tuple[Path, Path]:
        state = context.content.service.call(
            "content_project_get",
            {"channelProfileId": context.content.channel_id, "projectId": context.content.project_id},
        )["state"]
        return Path(state["activePackages"]["manuscript"]["path"]), Path(state["activePackages"]["publishing"]["path"])

    def _assemble_direct(self, context, manuscript: Path, publishing: Path):
        return context.content.service.production.assemble_package(
            manuscript_path=manuscript,
            publishing_path=publishing,
            production_config=context.production_config,
            production_preset={"id": "synthetic", "version": "1.0.0", "hash": "1" * 64, "targetRegion": "Japan"},
            workshop_compatibility={"interfaceVersion": "2.1", "workshopVersion": "0.5.0-stage5"},
            synthetic=True,
        )

    def test_surface_exposes_stage5_tools_and_publish_boundary(self) -> None:
        names = {definition["name"] for definition in tool_definitions()}
        expected = {
            "production_capabilities",
            "production_package_assemble",
            "production_task_start",
            "production_task_get",
            "production_task_run",
            "production_task_pause",
            "production_task_resume",
            "production_task_retry",
            "production_task_invalidate",
            "production_jianying_export_ingest",
            "production_result_validate",
        }
        self.assertTrue(expected.issubset(names))
        context = self.context()
        capabilities = context.content.service.call("production_capabilities")
        self.assertEqual("2.1", capabilities["contracts"]["productionPackage"])
        self.assertEqual([f"P{index}" for index in range(12)], capabilities["steps"])
        self.assertFalse(capabilities["boundaries"]["readyPackage"])
        self.assertFalse(capabilities["boundaries"]["upload"])

    def test_package_v21_contains_only_locked_target_language_inputs_and_is_idempotent(self) -> None:
        context = self.context()
        package_root = Path(context.package["packagePath"])
        manifest = context.content.service.production.validate_package(package_root)
        self.assertEqual("2.1", manifest["schemaVersion"])
        self.assertEqual(9, len(manifest["files"]))
        self.assertFalse(any("chinese" in item["path"] for item in manifest["files"]))
        manuscript_path, _ = self._upstream_paths(context)
        manuscript = json.loads(manuscript_path.read_text(encoding="utf-8"))
        package_lines = json.loads((package_root / "script_lines.json").read_text(encoding="utf-8"))["lines"]
        self.assertEqual(manuscript["targetScript"]["lines"], package_lines)
        characters = json.loads((package_root / "characters.json").read_text(encoding="utf-8"))["characters"]
        self.assertEqual(manuscript["characters"], [{key: value for key, value in item.items() if key != "voice"} for item in characters])
        second = context.content.service.production.import_package(package_root)
        self.assertTrue(second["duplicate"])
        self.assertTrue(second["roundTripValidated"])
        assembled_again = context.content.service.call(
            "production_package_assemble",
            {
                "taskId": context.content.task_id,
                "channelProfileId": context.content.channel_id,
                "bindingProof": context.content.proof,
                "projectId": context.content.project_id,
                "productionConfig": context.production_config,
                "productionPreset": {"id": "synthetic-jp-production", "version": "1.0.0", "hash": "1" * 64, "targetRegion": "Japan", "synthetic": True},
                "workshopCompatibility": {"interfaceVersion": "2.1", "workshopVersion": "0.5.0-stage5", "adapter": "novel-manga-workshop-cli"},
                "synthetic": True,
            },
        )
        self.assertTrue(assembled_again["idempotent"])
        self.assertEqual(manifest["packageHash"], assembled_again["manifest"]["packageHash"])

    def test_full_production_profile_is_normalized_to_source_reference(self) -> None:
        context = self.context()
        manuscript_path, publishing_path = self._upstream_paths(context)
        production_profile = context.content.service.store.get_channel(context.content.channel_id)["productionProfile"]
        assembled = context.content.service.production.assemble_package(
            manuscript_path=manuscript_path,
            publishing_path=publishing_path,
            production_config=context.production_config,
            production_preset=production_profile,
            workshop_compatibility={
                "interfaceVersion": "2.1",
                "workshopVersion": "0.5.0-stage5",
                "adapter": "novel-manga-workshop-cli",
            },
            synthetic=True,
        )
        source_lock = json.loads(
            (Path(assembled["packagePath"]) / "source_lock.json").read_text(encoding="utf-8")
        )
        self.assertEqual(
            {
                "targetContractType": "production-profile",
                "targetId": production_profile["id"],
                "targetVersion": production_profile["version"],
                "targetSchemaVersion": production_profile["schemaVersion"],
                "targetHash": production_profile["contentHash"],
            },
            source_lock["productionPreset"],
        )

    def test_actual_workshop_default_target_uses_declared_isolation_root(self) -> None:
        context = self.context()
        package_root = Path(context.package["packagePath"])
        isolation_root = self.root / "declared-workshop-isolation"
        isolation_root.mkdir()

        class RecordingBridge:
            def __init__(self, root: Path) -> None:
                self.isolation_root = root
                self.target: Path | None = None

            def import_package(self, _package: Path, target: Path, *, expected_project_id: str):
                self.target = target
                return {
                    "projectId": expected_project_id,
                    "roundTripValidated": True,
                    "publishingTriggered": False,
                }

        bridge = RecordingBridge(isolation_root)
        center = ProductionCenter(self.root / "separate-production-data", workshop_bridge=bridge)
        imported = center.import_package(package_root)
        assert bridge.target is not None
        self.assertEqual(
            ("workshop-projects", imported["projectId"], context.package["manifest"]["packageVersion"]),
            bridge.target.parts[-3:],
        )
        self.assertTrue(os.path.samefile(isolation_root, bridge.target.parents[2]))

    def test_auto_render_pause_restart_resume_video_ready_and_read_only_progress(self) -> None:
        context = self.context("ja-JP", delivery_mode="auto_render", selection_mode="none")
        args = mutation_arguments(context)
        paused = context.content.service.call("production_task_run", {**args, "pauseAfterStep": "P4"})["task"]
        self.assertEqual("PAUSED", paused["state"])
        task_path = context.content.service.production._task_path(context.production_task_id)
        before_stat = task_path.stat().st_mtime_ns
        before_hash = task_path.read_bytes()
        time.sleep(0.01)
        read_only = context.content.service.call("production_task_get", {"productionTaskId": context.production_task_id})
        self.assertTrue(read_only["progressReadOnly"])
        self.assertEqual(before_stat, task_path.stat().st_mtime_ns)
        self.assertEqual(before_hash, task_path.read_bytes())
        restarted = LocalToolService(
            ServiceConfig(
                data_root=context.content.root / "data",
                plugin_root=PLUGIN_ROOT,
                voice_catalog_path=context.content.root / "voice-catalog.json",
            )
        )
        restarted.call("production_task_resume", args)
        completed = restarted.call("production_task_run", args)["task"]
        self.assertEqual("VIDEO_READY", completed["state"])
        result_root = Path(completed["resultPackagePath"])
        validation = json.loads((result_root / "validation-report.json").read_text(encoding="utf-8"))
        self.assertEqual(1, validation["videoStreamCount"])
        self.assertEqual(1, validation["audioStreamCount"])
        self.assertEqual("16:9", validation["aspectRatio"])
        self.assertTrue(validation["timelineMapped"])
        self.assertFalse(any(path.suffix == ".ready" for path in result_root.rglob("*")))

    def test_video_scope_fallback_and_selective_publishing_invalidation(self) -> None:
        context = self.context(
            "zh-CN",
            delivery_mode="auto_render",
            selection_mode="project_first_n_storyboards",
            count=1,
            fallback_policy="use_static_image",
        )
        args = mutation_arguments(context)
        completed = context.content.service.call(
            "production_task_run",
            {**args, "failStoryboardIds": ["SB-E01-L001"]},
        )["task"]
        self.assertEqual("VIDEO_READY", completed["state"])
        self.assertEqual(["SB-E01-L001"], completed["selectedStoryboardIds"])
        self.assertEqual("use_static_image", completed["fallbacks"][0]["mode"])
        final_video = next(asset for asset in completed["assets"] if asset["assetId"] == "final-video")
        invalidation = context.content.service.call(
            "production_task_invalidate",
            {**args, "changes": ["publishing.title", "publishing.thumbnail"]},
        )
        self.assertTrue(invalidation["mediaPreserved"])
        after_video = next(asset for asset in invalidation["task"]["assets"] if asset["assetId"] == "final-video")
        self.assertEqual("COMPLETED", after_video["status"])
        self.assertEqual(final_video["sha256"], after_video["sha256"])
        publishing_ref = next(asset for asset in invalidation["task"]["assets"] if asset["assetId"] == "publishing-reference")
        self.assertEqual("INVALIDATED", publishing_ref["status"])

    def test_unauthorized_video_fallback_pauses_then_retries_only_failure(self) -> None:
        context = self.context(
            "en-US",
            delivery_mode="jianying_refine",
            selection_mode="all_storyboards",
            fallback_policy="pause",
        )
        args = mutation_arguments(context)
        first = context.content.service.call(
            "production_task_run",
            {**args, "failStoryboardIds": ["SB-E01-L001"]},
        )["task"]
        self.assertEqual("PAUSED", first["state"])
        self.assertEqual([], first["fallbacks"])
        failed = next(asset for asset in first["assets"] if asset["assetId"] == "storyboard-video-SB-E01-L001")
        completed_before = {asset["assetId"]: asset["attempts"] for asset in first["assets"] if asset["status"] == "COMPLETED"}
        context.content.service.call("production_task_retry", args)
        context.content.service.call("production_task_resume", args)
        second = context.content.service.call("production_task_run", args)["task"]
        self.assertEqual("AWAITING_JIANYING_EXPORT", second["state"])
        retried = next(asset for asset in second["assets"] if asset["assetId"] == failed["assetId"])
        self.assertEqual("COMPLETED", retried["status"])
        self.assertEqual(2, retried["attempts"])
        for asset in second["assets"]:
            if asset["assetId"] in completed_before:
                self.assertEqual(completed_before[asset["assetId"]], asset["attempts"])

    def test_jianying_draft_wrong_export_rejected_then_correct_export_video_ready(self) -> None:
        context = self.context("en-US", delivery_mode="jianying_refine", selection_mode="episode_first_n_storyboards", count=1)
        args = mutation_arguments(context)
        waiting = context.content.service.call("production_task_run", args)["task"]
        self.assertEqual("AWAITING_JIANYING_EXPORT", waiting["state"])
        draft_root = Path(waiting["jianyingDraftPackagePath"])
        self.assertTrue((draft_root / "native-subtitle-track.json").is_file())
        self.assertTrue((draft_root / "subtitles.srt").is_file())
        self.assertTrue((draft_root / "media" / "confirmed_thumbnail.png").is_file())
        export_path = self.root / "jianying-export" / "export.mp4"
        context.content.service.production._render_media(
            Path(context.package["packagePath"]) / "confirmed_thumbnail.png",
            export_path,
            duration_seconds=3.0,
            width=640,
            height=360,
            frame_rate=24,
        )
        wrong_identity = export_identity(context, export_path, project_id="wrong-project")
        wrong_path = export_path.parent / "wrong-identity.json"
        wrong_path.write_text(json.dumps(wrong_identity), encoding="utf-8")
        self.assert_tool_error(
            "PRODUCTION_JIANYING_EXPORT_IDENTITY_MISMATCH",
            lambda: context.content.service.call(
                "production_jianying_export_ingest",
                {**args, "exportPath": str(export_path), "identityPath": str(wrong_path)},
            ),
        )
        identity_path = export_path.parent / "export-identity.json"
        identity_path.write_text(json.dumps(export_identity(context, export_path)), encoding="utf-8")
        ingested = context.content.service.call(
            "production_jianying_export_ingest",
            {**args, "exportPath": str(export_path), "identityPath": str(identity_path)},
        )["task"]
        self.assertEqual("VIDEO_READY", ingested["state"])
        duplicate = context.content.service.call(
            "production_jianying_export_ingest",
            {**args, "exportPath": str(export_path), "identityPath": str(identity_path)},
        )
        self.assertTrue(duplicate["idempotent"])

    def test_four_video_selection_modes_persist_exact_ids(self) -> None:
        center = self.context().content.service.production
        storyboards = [
            {"storyboardId": "SB-1", "episodeNumber": 1},
            {"storyboardId": "SB-2", "episodeNumber": 1},
            {"storyboardId": "SB-3", "episodeNumber": 2},
            {"storyboardId": "SB-4", "episodeNumber": 2},
        ]
        self.assertEqual([], center._selected_storyboards(storyboards, {"enabled": False, "selectionMode": "none"}))
        self.assertEqual(["SB-1", "SB-2"], center._selected_storyboards(storyboards, {"enabled": True, "selectionMode": "project_first_n_storyboards", "count": 2}))
        self.assertEqual(["SB-1", "SB-3"], center._selected_storyboards(storyboards, {"enabled": True, "selectionMode": "episode_first_n_storyboards", "count": 1}))
        self.assertEqual(["SB-1", "SB-2", "SB-3", "SB-4"], center._selected_storyboards(storyboards, {"enabled": True, "selectionMode": "all_storyboards"}))

    def test_failure_matrix_upstream_and_package_hard_gates(self) -> None:
        context = self.context()
        manuscript_path, publishing_path = self._upstream_paths(context)

        bad_hash_root = self.root / "bad-upstream-hash"
        shutil.copytree(manuscript_path.parent, bad_hash_root)
        bad_manifest = json.loads((bad_hash_root / "manifest.json").read_text(encoding="utf-8"))
        bad_manifest["status"] = "tampered"
        (bad_hash_root / "manifest.json").write_text(json.dumps(bad_manifest), encoding="utf-8")
        self.assert_tool_error("PRODUCTION_UPSTREAM_HASH_MISMATCH", lambda: self._assemble_direct(context, bad_hash_root, publishing_path))

        unconfirmed_root = self.root / "unconfirmed-upstream"
        shutil.copytree(manuscript_path.parent, unconfirmed_root)
        unconfirmed = json.loads((unconfirmed_root / "manifest.json").read_text(encoding="utf-8"))
        unconfirmed["status"] = "MANUSCRIPT_PENDING"
        unconfirmed["confirmation"]["status"] = "PENDING"
        unconfirmed.pop("contentHash", None)
        unconfirmed = with_hash(unconfirmed)
        (unconfirmed_root / "manifest.json").write_text(json.dumps(unconfirmed), encoding="utf-8")
        self.assert_tool_error("PRODUCTION_UPSTREAM_NOT_CONFIRMED", lambda: self._assemble_direct(context, unconfirmed_root, publishing_path))

        audit_root = self._package_copy(context, "audit-mixed")
        (audit_root / "chinese-audit-script.json").write_text("{}", encoding="utf-8")
        self._refresh_package_manifest(audit_root)
        self.assert_tool_error("PRODUCTION_AUDIT_SCRIPT_FORBIDDEN", lambda: context.content.service.production.validate_package(audit_root))

        outside_root = self._package_copy(context, "outside-path")
        outside_manifest = json.loads((outside_root / "manifest.json").read_text(encoding="utf-8"))
        outside_manifest["files"][0]["path"] = "../outside.json"
        outside_manifest["packageHash"] = production_package_hash(outside_manifest)
        (outside_root / "manifest.json").write_text(json.dumps(outside_manifest), encoding="utf-8")
        self.assert_tool_error("PRODUCTION_PATH_INVALID", lambda: context.content.service.production.validate_package(outside_root))

        catalog_path = context.content.root / "voice-catalog.json"
        catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
        for engine in catalog["engines"]:
            engine["voices"] = []
        catalog.pop("contentHash", None)
        catalog = with_hash(catalog)
        catalog_path.write_text(json.dumps(catalog), encoding="utf-8")
        self.assert_tool_error("PRODUCTION_VOICE_UNKNOWN", lambda: self._assemble_direct(context, manuscript_path, publishing_path))

        self.assert_tool_error(
            "PRODUCTION_ACTIVE_TASK_EXISTS",
            lambda: context.content.service.production.start_task(
                production_task_id="another-active-task",
                package_root=Path(context.package["packagePath"]),
            ),
        )

    def test_failure_matrix_bad_media_subtitles_and_publish_overreach(self) -> None:
        context = self.context("ja-JP")
        args = mutation_arguments(context)
        task = context.content.service.call("production_task_run", args)["task"]
        task_root = context.content.service.production._task_root(context.production_task_id)
        render_root = task_root / "render"
        lines = json.loads((Path(context.package["packagePath"]) / "script_lines.json").read_text(encoding="utf-8"))["lines"]

        bad_video = self.root / "bad.mp4"
        bad_video.write_bytes(b"not-an-mp4")
        self.assert_tool_error(
            "PRODUCTION_VIDEO_DECODE_FAILED",
            lambda: context.content.service.production.validate_video(
                video_path=bad_video,
                subtitles_path=render_root / "subtitles.srt",
                timeline_path=render_root / "timeline-map.json",
                expected_lines=lines,
                expected_width=640,
                expected_height=360,
            ),
        )

        wrong_timeline = self.root / "wrong-timeline.json"
        timeline = json.loads((render_root / "timeline-map.json").read_text(encoding="utf-8"))
        timeline["items"][0]["lineId"] = "WRONG-LINE"
        wrong_timeline.write_text(json.dumps(timeline), encoding="utf-8")
        self.assert_tool_error(
            "PRODUCTION_SUBTITLE_MAPPING_MISMATCH",
            lambda: context.content.service.production.validate_video(
                video_path=render_root / "final-video.mp4",
                subtitles_path=render_root / "subtitles.srt",
                timeline_path=wrong_timeline,
                expected_lines=lines,
                expected_width=640,
                expected_height=360,
            ),
        )

        result_root = Path(task["resultPackagePath"])
        (result_root / "forbidden.ready").write_bytes(b"publish boundary violation")
        self.assert_tool_error(
            "PRODUCTION_PUBLISH_BOUNDARY_VIOLATION",
            lambda: context.content.service.production.validate_result_package(result_root),
        )

    def test_non_synthetic_task_requires_actual_workshop_bridge(self) -> None:
        context = self.context("ja-JP")
        package_root = self._package_copy(context, "formal-workshop-required")
        manifest_path = package_root / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["synthetic"] = False
        manifest["packageHash"] = production_package_hash(manifest)
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        center = ProductionCenter(
            self.root / "formal-center",
            voice_catalog_path=context.content.root / "voice-catalog.json",
        )
        self.assert_tool_error(
            "PRODUCTION_SYNTHETIC_MARKER_MISMATCH",
            lambda: center.start_task(production_task_id="formal-task", package_root=package_root),
        )

        config_path = package_root / "production_config.json"
        config = json.loads(config_path.read_text(encoding="utf-8"))
        config["syntheticFixtureRunner"] = False
        config_path.write_text(json.dumps(config, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        self._refresh_package_manifest(package_root)
        self.assert_tool_error(
            "PRODUCTION_WORKSHOP_UNAVAILABLE",
            lambda: center.start_task(production_task_id="formal-task", package_root=package_root),
        )


if __name__ == "__main__":
    unittest.main()
