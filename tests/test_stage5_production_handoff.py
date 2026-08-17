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
from aivcp_tools.production import ProductionCenter, _normalize_codex_visual_plan, production_package_hash  # noqa: E402
from aivcp_tools.review_documents import save_review_document  # noqa: E402
from aivcp_tools.service import LocalToolService, ServiceConfig, tool_definitions  # noqa: E402
from stage5_support import (  # noqa: E402
    build_stage5_context,
    export_identity,
    mutation_arguments,
    production_config,
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
        self.assertEqual("identity_only", capabilities["codexVisualPlan"]["referenceUsage"])
        self.assertFalse(capabilities["codexVisualPlan"]["workshopMayRewriteLockedPrompts"])
        self.assertFalse(capabilities["codexVisualPlan"]["postGenerationVisualAudit"])

    def test_codex_visual_plan_locks_manga_design_and_scene_performance(self) -> None:
        context = self.context()
        manuscript_path, _ = self._upstream_paths(context)
        manuscript = json.loads(manuscript_path.read_text(encoding="utf-8"))
        config = context.content.service.production._validate_production_config(
            {
                **context.production_config,
                "promptGeneration": {"image": True, "video": True},
            }
        )
        visual_characters = [item for item in manuscript["characters"] if item.get("visualConsistencyRequired")]
        plan = {
            "schemaVersion": "1.1",
            "author": "codex",
            "characterDesigns": [
                {
                    "characterId": item["characterId"],
                    "designIntentZh": "从人物身份与性格建立漫画轮廓记忆点和近景记忆点。",
                    "identityAnchorPromptZh": "漫画人物比例，独特脸型与眼型，分层发束，固定服装轮廓与配色。",
                    "referenceSheetPromptZh": "单角色漫画设定图，清楚服装层次与固定配饰，无剧情背景和可读文字。",
                    "storyboardIdentityPromptZh": "保留脸型、眼型、发型、服装轮廓、配色和固定配饰。",
                    "fixedFeatures": ["独特眼型", "分层发束", "固定服装轮廓"],
                }
                for item in visual_characters
            ],
            "continuityBible": {
                "locations": [{"locationId": "LOC-01", "nameZh": "主要场景", "fixedFeatures": ["空间结构与主色固定"]}],
                "costumes": [
                    {"costumeId": f"CST-{index:02d}", "characterId": item["characterId"], "nameZh": "常服", "fixedFeatures": ["轮廓和配色固定"]}
                    for index, item in enumerate(visual_characters, start=1)
                ],
                "props": [{"propId": "PROP-01", "nameZh": "剧情关键物", "fixedFeatures": ["外形和颜色固定"]}],
            },
            "scenePlans": [],
        }
        visual_ids = {item["characterId"] for item in visual_characters}
        costume_by_character = {item["characterId"]: f"CST-{index:02d}" for index, item in enumerate(visual_characters, start=1)}
        all_lines = manuscript["targetScript"]["lines"]
        for index, line in enumerate(manuscript["targetScript"]["lines"], start=1):
            visible = [line["speakerId"]] if line["speakerId"] in visual_ids else []
            beat_id = "BEAT-HOOK" if index == 1 else "BEAT-REL" if index == 2 else "BEAT-CONFLICT"
            narrative_function = "hook" if index == 1 else "relationship" if index == 2 else "conflict"
            shot_scale = ("close_up", "wide", "medium")[(index - 1) % 3]
            shot_view = ("three_quarter", "back_view", "over_the_shoulder")[(index - 1) % 3]
            plan["scenePlans"].append(
                {
                    "sceneId": f"CVP-E{line['episodeNumber']:02d}-S{index:03d}",
                    "episodeNumber": line["episodeNumber"],
                    "scriptLineIds": [line["lineId"]],
                    "visibleCharacterIds": visible,
                    "primaryCharacterId": visible[0] if visible else "",
                    "complexityScore": 4,
                    "narrativeFunction": narrative_function,
                    "storyBeatIds": [beat_id],
                    "shot": {
                        "scale": shot_scale,
                        "angle": "dutch_angle" if index == 1 else "eye_level",
                        "view": shot_view,
                        "dialogueStaging": "reaction" if index == 1 else "action",
                        "breakingComposition": index == 1,
                        "breakingCompositionZh": "首镜斜切画框" if index == 1 else "常规画框内保持强焦点",
                        "focalPointZh": "人物眼神与关键动作",
                        "depthCompositionZh": "前景关键物、主体人物、后景关系对象形成三层",
                        "posterCompositionZh": "明确单一焦点、冲突方向和有意义留白",
                    },
                    "visualReadability": {
                        "storyInformationZh": "人物的动作与环境变化交代当前事件",
                        "relationshipCueZh": "人物距离与朝向交代关系",
                        "conflictOrCauseEffectCueZh": "关键物与反应动作交代因果",
                        "withoutDialogueReadable": True,
                    },
                    "continuity": {
                        "locationId": "LOC-01",
                        "costumeIdsByCharacter": {character_id: costume_by_character[character_id] for character_id in visible},
                        "propIds": ["PROP-01"],
                        "changeJustificationZh": "延续同一场景、服装和关键物状态",
                    },
                    "emotionalBeat": {
                        "category": "shock" if index == 1 else "none",
                        "visualSignals": ["pupil_constriction", "step_back", "light_color_shift"] if index == 1 else [],
                    },
                    "performance": {
                        "internalEmotion": "正在压住真实情绪",
                        "visibleEmotion": "眼神由迟疑转为坚定",
                        "intensity": 3,
                        "gaze": "看向当前互动对象",
                        "eyes": "虹膜高光收紧",
                        "brows": "眉心轻收",
                        "mouth": "嘴角绷紧",
                        "headPose": "下巴略抬",
                        "bodyPose": "重心从后脚移向前脚",
                        "handGesture": "手指缓慢收紧",
                        "interactionTarget": "当前对话对象",
                        "changeFromPrevious": "从防御姿态转为主动回应",
                    },
                    "promptComponents": {
                        "subjectActionZh": "主体完成与当前正式稿对应的明确动作",
                        "visualStoryZh": "用人物距离、动作与关键物呈现事件因果",
                        "performanceZh": "表情、视线、手势和身体重心可见",
                        "cameraCompositionZh": "使用当前镜头合同形成焦点和空间层次",
                        "continuityEnvironmentZh": "保持地点、服装和关键物连续",
                        "lightingColorZh": "光色辅助当前情绪而不代替表演",
                        "keyObjectZh": "关键物位于因果视线方向",
                    },
                    "imagePromptZh": "漫画分镜静态关键瞬间，人物表情与姿态服从当前剧情，无可读文字。",
                    "videoPromptZh": "人物完成一次明确的表情与重心变化，镜头缓慢推进后停稳。",
                }
            )
        first_scene_id = plan["scenePlans"][0]["sceneId"]
        second_scene_id = plan["scenePlans"][1]["sceneId"]
        remaining_scene_ids = [item["sceneId"] for item in plan["scenePlans"][2:]] or [second_scene_id]
        plan["storyVisualPlan"] = {
            "openingHookSceneId": first_scene_id,
            "relationshipConflictSceneIds": [second_scene_id, remaining_scene_ids[0]],
            "complexityLevel": 4,
            "pageCountMode": "complexity_adaptive",
            "plannedPageCount": len(plan["scenePlans"]),
            "pageCountRationaleZh": "复杂关系、冲突与情绪节点一行一镜，保证画面因果清楚。",
            "storyBeats": [
                {"beatId": "BEAT-HOOK", "type": "hook", "summaryZh": "首镜建立观看钩子", "sourceLineIds": [all_lines[0]["lineId"]], "sceneIds": [first_scene_id]},
                {"beatId": "BEAT-REL", "type": "relationship", "summaryZh": "交代人物关系", "sourceLineIds": [all_lines[1]["lineId"]], "sceneIds": [second_scene_id]},
                {"beatId": "BEAT-CONFLICT", "type": "conflict", "summaryZh": "呈现核心冲突与推进", "sourceLineIds": [line["lineId"] for line in all_lines[2:]] or [all_lines[1]["lineId"]], "sceneIds": remaining_scene_ids},
            ],
            "promptCompiler": {
                "mode": "structured_budgeted_merge",
                "imagePromptMaxChars": 600,
                "videoPromptMaxChars": 500,
                "globalStyleRepeatedPerScene": False,
                "identityFullProfileRepeatedPerScene": False,
            },
        }
        normalized = _normalize_codex_visual_plan(
            plan,
            manuscript=manuscript,
            production_config=config,
            synthetic=False,
        )
        self.assertEqual("identity_only", normalized["referenceUsage"])
        self.assertFalse(normalized["locks"]["workshopMayRewritePrompts"])
        self.assertEqual(
            [line["lineId"] for line in manuscript["targetScript"]["lines"]],
            [line_id for scene in normalized["scenePlans"] for line_id in scene["scriptLineIds"]],
        )
        self.assertEqual(
            ["expression", "gaze", "headPose", "bodyPose", "handGesture", "framing", "lighting", "background"],
            normalized["characterDesigns"][0]["flexibleFeatures"],
        )
        _, publishing_path = self._upstream_paths(context)
        assembled = context.content.service.production.assemble_package(
            manuscript_path=manuscript_path,
            publishing_path=publishing_path,
            production_config={
                **context.production_config,
                "promptGeneration": {"image": True, "video": True},
                "codexVisualPlan": plan,
            },
            production_preset={"id": "synthetic-codex-visual", "version": "1.0.0", "hash": "1" * 64, "targetRegion": "Japan"},
            workshop_compatibility={"interfaceVersion": "2.1", "workshopVersion": "0.5.0-stage5"},
            synthetic=True,
        )
        package_root = Path(assembled["packagePath"])
        package_config = json.loads((package_root / "production_config.json").read_text(encoding="utf-8"))
        package_characters = json.loads((package_root / "characters.json").read_text(encoding="utf-8"))["characters"]
        self.assertEqual("codex", package_config["codexVisualPlan"]["author"])
        self.assertEqual(
            normalized["characterDesigns"][0]["referenceSheetPromptZh"],
            next(item for item in package_characters if item["characterId"] == normalized["characterDesigns"][0]["characterId"])["referenceSheetPromptZh"],
        )
        visual_review = Path(assembled["userReviewDocuments"]["directory"]) / "11B_Codex角色设计与分镜提示词方案.md"
        self.assertTrue(visual_review.is_file())
        self.assertIn("只锁身份，不锁表情", visual_review.read_text(encoding="utf-8"))
        invalid = json.loads(json.dumps(plan, ensure_ascii=False))
        invalid["scenePlans"] = invalid["scenePlans"][:-1]
        self.assert_tool_error(
            "PRODUCTION_CODEX_VISUAL_PLAN_INVALID",
            lambda: _normalize_codex_visual_plan(
                invalid,
                manuscript=manuscript,
                production_config=config,
                synthetic=False,
            ),
        )
        repeated_emotion = json.loads(json.dumps(plan, ensure_ascii=False))
        repeated_emotion["scenePlans"][1]["emotionalBeat"] = {
            "category": "shock",
            "visualSignals": ["gaze_change", "clenched_hand"],
        }
        repeated_emotion["scenePlans"][1]["shot"]["scale"] = "close_up"
        repeated_emotion["scenePlans"][1]["shot"]["breakingComposition"] = True
        self.assert_tool_error(
            "PRODUCTION_CODEX_VISUAL_PLAN_INVALID",
            lambda: _normalize_codex_visual_plan(
                repeated_emotion,
                manuscript=manuscript,
                production_config=config,
                synthetic=False,
            ),
        )
        prompt_over_budget = json.loads(json.dumps(plan, ensure_ascii=False))
        prompt_over_budget["scenePlans"][0]["imagePromptZh"] = "画" * 601
        self.assert_tool_error(
            "PRODUCTION_CODEX_VISUAL_PLAN_INVALID",
            lambda: _normalize_codex_visual_plan(
                prompt_over_budget,
                manuscript=manuscript,
                production_config=config,
                synthetic=False,
            ),
        )

    def test_real_package_video_scope_requires_current_task_authorization_and_retired_style_is_rejected(self) -> None:
        context = self.context(selection_mode="project_first_n_storyboards", count=1)
        arguments = {
            "taskId": context.content.task_id,
            "channelProfileId": context.content.channel_id,
            "bindingProof": context.content.proof,
            "projectId": context.content.project_id,
            "productionConfig": context.production_config,
            "productionPreset": {"id": "real-production", "version": "1.0.0", "hash": "1" * 64, "targetRegion": "Japan"},
            "workshopCompatibility": {"interfaceVersion": "2.1", "workshopVersion": "2.1.0"},
            "synthetic": False,
        }
        self.assert_tool_error(
            "VIDEO_GENERATION_AUTHORIZATION_REQUIRED",
            lambda: context.content.service.call("production_package_assemble", arguments),
        )

        retired = json.loads(json.dumps(context.production_config))
        retired["videoGeneration"] = {"enabled": False, "selectionMode": "none", "fallbackPolicy": "pause"}
        retired["imageStyle"]["presetId"] = "gpt2_01"
        self.assert_tool_error(
            "PRODUCTION_IMAGE_STYLE_RETIRED",
            lambda: context.content.service.production._validate_production_config(retired),
        )

    def test_package_v21_contains_only_locked_target_language_inputs_and_is_idempotent(self) -> None:
        context = self.context()
        package_root = Path(context.package["packagePath"])
        manifest = context.content.service.production.validate_package(package_root)
        self.assertEqual("2.1", manifest["schemaVersion"])
        self.assertEqual(9, len(manifest["files"]))
        self.assertFalse(any("chinese" in item["path"] for item in manifest["files"]))
        review_root = Path(context.package["userReviewDocuments"]["directory"])
        production_overview = review_root / "11_完整生产资料总览.md"
        self.assertTrue(production_overview.is_file())
        overview_text = production_overview.read_text(encoding="utf-8")
        self.assertIn("script_lines.json", overview_text)
        self.assertIn("07_正式稿_目标语言.txt", overview_text)
        self.assertIn("08_正式稿_中文版.txt", overview_text)
        self.assertIn("唯一用于配音、字幕和分镜", overview_text)
        self.assertIn("角色形象提示词", overview_text)
        self.assertIn(manifest["packageHash"], overview_text)
        manuscript_path, _ = self._upstream_paths(context)
        manuscript = json.loads(manuscript_path.read_text(encoding="utf-8"))
        package_lines = json.loads((package_root / "script_lines.json").read_text(encoding="utf-8"))["lines"]
        self.assertEqual(manuscript["targetScript"]["lines"], package_lines)
        source_lock = json.loads((package_root / "source_lock.json").read_text(encoding="utf-8"))
        self.assertEqual(manuscript["targetScript"]["contentHash"], source_lock["targetScriptBinding"]["targetScriptContentHash"])
        self.assertEqual("final-script-target", source_lock["targetScriptBinding"]["userReviewDocumentId"])
        self.assertTrue(source_lock["targetScriptBinding"]["productionUseAllowed"])
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

    def test_package_assembly_rejects_user_visible_script_that_differs_from_machine_master(self) -> None:
        context = self.context()
        manuscript_path, publishing_path = self._upstream_paths(context)
        project_root = Path(context.package["userReviewDocuments"]["contextRoot"])
        save_review_document(
            project_root,
            document_id="final-script-target",
            content="[E01-L001] narrator: This is not the locked production manuscript.",
            language="ja-JP",
            updated_at="2026-08-08T08:30:00Z",
        )
        self.assert_tool_error(
            "PRODUCTION_REVIEW_DOCUMENT_MISMATCH",
            lambda: self._assemble_direct(context, manuscript_path, publishing_path),
        )

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

    def test_first_last_frame_video_config_is_explicit_and_never_silently_downgraded(self) -> None:
        center = self.context().content.service.production
        config = production_config(selection_mode="project_first_n_storyboards", count=1)
        config["videoGeneration"].update({
            "frameInputMode": "first_last_frame",
            "endFrameSource": "dedicated_generated",
        })
        validated = center._validate_production_config(config)
        self.assertEqual("first_last_frame", validated["videoGeneration"]["frameInputMode"])
        self.assertEqual("dedicated_generated", validated["videoGeneration"]["endFrameSource"])
        self.assertEqual("wide_16_9_4", validated["gridBatch"]["template"])

        missing_end_source = json.loads(json.dumps(config))
        missing_end_source["videoGeneration"]["endFrameSource"] = ""
        self.assert_tool_error(
            "PRODUCTION_VIDEO_END_FRAME_INVALID",
            lambda: center._validate_production_config(missing_end_source),
        )

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

    def test_formal_task_starts_workshop_once_and_never_runs_placeholder_executors(self) -> None:
        context = self.context("zh-CN")
        package_root = self._package_copy(context, "formal-workshop-routing")
        config_path = package_root / "production_config.json"
        config = json.loads(config_path.read_text(encoding="utf-8"))
        config["syntheticFixtureRunner"] = False
        config["promptGeneration"] = {"image": False, "video": False}
        config_path.write_text(json.dumps(config, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        manifest_path = package_root / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["synthetic"] = False
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        self._refresh_package_manifest(package_root)

        class FakeWorkshopBridge:
            def __init__(self, isolation_root: Path) -> None:
                self.start_calls = 0
                self.status_value = "running"
                self.isolation_root = isolation_root

            def import_package(self, _package_root, target_root, *, expected_project_id):
                target_root.mkdir(parents=True, exist_ok=True)
                project_path = target_root / "novel_manga_project.json"
                project_path.write_text(json.dumps({"id": expected_project_id}), encoding="utf-8")
                return {
                    "projectId": expected_project_id,
                    "projectPath": str(project_path),
                    "roundTripValidated": True,
                    "publishingTriggered": False,
                    "duplicate": False,
                }

            def start_production(self, _project_path, *, selected_step_ids, request_id, **_kwargs):
                self.start_calls += 1
                self.assert_no_placeholder_steps(selected_step_ids)
                return {
                    "requestId": request_id,
                    "joinedExisting": False,
                    "startConfirmed": True,
                    "publishingTriggered": False,
                }

            @staticmethod
            def assert_no_placeholder_steps(selected_step_ids):
                if any(step.startswith("P") for step in selected_step_ids):
                    raise AssertionError("formal workshop must receive Workshop step IDs")

            def production_status(self, _project_path, **_kwargs):
                return {
                    "taskPresent": True,
                    "status": self.status_value,
                    "error": "fixture failure" if self.status_value == "failed" else "",
                    "message": "",
                }

        bridge = FakeWorkshopBridge(self.root / "formal-routing-workshop")
        center = ProductionCenter(
            self.root / "formal-routing-center",
            voice_catalog_path=context.content.root / "voice-catalog.json",
            ffmpeg_path=shutil.which("ffmpeg"),
            ffprobe_path=shutil.which("ffprobe"),
            workshop_bridge=bridge,
        )
        center.start_task(production_task_id="formal-routing-task", package_root=package_root)
        first = center.run_task("formal-routing-task")
        self.assertTrue(first["workshopStarted"])
        self.assertEqual(1, bridge.start_calls)
        second = center.run_task("formal-routing-task")
        self.assertTrue(second["workshopRunning"])
        self.assertEqual(1, bridge.start_calls)
        self.assertFalse((center._task_root("formal-routing-task") / "assets" / "storyboard-images").exists())

        bridge.status_value = "failed"
        failed = center.run_task("formal-routing-task")
        self.assertTrue(failed["workshopNeedsAttention"])
        center.retry_failed("formal-routing-task")
        restarted = center.run_task("formal-routing-task")
        self.assertTrue(restarted["workshopStarted"])
        self.assertEqual(2, bridge.start_calls)


if __name__ == "__main__":
    unittest.main()
