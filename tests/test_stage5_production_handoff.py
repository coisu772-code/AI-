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
from aivcp_tools.production import (  # noqa: E402
    ProductionCenter,
    _normalize_codex_visual_plan,
    _subtitles_cover_spoken_lines_in_order,
    _validate_sound_effect_scene_bindings,
    production_package_hash,
)
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

    def test_subtitle_coverage_allows_interleaved_sound_effect_cues(self) -> None:
        spoken_lines = [
            {"lineId": "E01-L001", "text": "彼は扉を見上げた。"},
            {"lineId": "E01-L002", "text": "光が差し込んだ。"},
        ]
        subtitles_with_sfx = "彼は扉を見上げた。【sound：扉が開く音】光が差し込んだ。"
        self.assertTrue(_subtitles_cover_spoken_lines_in_order(subtitles_with_sfx, spoken_lines))
        self.assertFalse(
            _subtitles_cover_spoken_lines_in_order(
                "光が差し込んだ。【sound：扉が開く音】彼は扉を見上げた。",
                spoken_lines,
            )
        )

    def test_sound_effect_must_share_the_trigger_scene(self) -> None:
        lines = [
            {"lineId": "E01-L001", "episodeNumber": 1, "lineType": "narration"},
            {"lineId": "E01-SFX01", "episodeNumber": 1, "lineType": "sound_effect"},
            {"lineId": "E01-L002", "episodeNumber": 1, "lineType": "dialogue"},
        ]
        _validate_sound_effect_scene_bindings(
            lines,
            {"E01-L001": "SCENE-01", "E01-SFX01": "SCENE-01", "E01-L002": "SCENE-02"},
        )
        error = self.assert_tool_error(
            "PRODUCTION_CODEX_VISUAL_PLAN_INVALID",
            lambda: _validate_sound_effect_scene_bindings(
                lines,
                {"E01-L001": "SCENE-01", "E01-SFX01": "SCENE-02", "E01-L002": "SCENE-02"},
            ),
        )
        self.assertEqual("E01-L001", error.details["triggerLineId"])

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
        self.assertEqual(20, capabilities["productionConcurrency"]["maximum"])
        self.assertEqual(20, capabilities["productionConcurrency"]["recommendedImage"])
        self.assertTrue(capabilities["gridBatch"]["episodeTemplateOverrides"])
        self.assertFalse(capabilities["boundaries"]["readyPackage"])
        self.assertFalse(capabilities["boundaries"]["upload"])
        self.assertEqual("1.5", capabilities["codexVisualPlan"]["schemaVersion"])
        self.assertEqual("identity_only", capabilities["codexVisualPlan"]["referenceUsage"])
        self.assertTrue(capabilities["codexVisualPlan"]["mangaImpactDirection"])
        self.assertTrue(capabilities["codexVisualPlan"]["singleVisualFocus"])
        self.assertTrue(capabilities["codexVisualPlan"]["exaggeratedFacialActing"])
        self.assertTrue(capabilities["codexVisualPlan"]["semanticSceneGrouping"])
        self.assertEqual("semantic_visual_beat_v2", capabilities["codexVisualPlan"]["semanticGroupingMode"])
        self.assertTrue(capabilities["codexVisualPlan"]["semanticGroupingBeforeContinuity"])
        self.assertFalse(capabilities["codexVisualPlan"]["ttsLineBreakCreatesScene"])
        self.assertFalse(capabilities["codexVisualPlan"]["lineCountHardCap"])
        self.assertTrue(capabilities["codexVisualPlan"]["fullSeriesContext"])
        self.assertTrue(capabilities["codexVisualPlan"]["visualSequencePlanning"])
        self.assertTrue(capabilities["codexVisualPlan"]["continuityStateChain"])
        self.assertTrue(capabilities["codexVisualPlan"]["temporalSequenceInSingleImageForbidden"])
        self.assertTrue(capabilities["codexVisualPlan"]["combatEffectsContract"])
        self.assertTrue(capabilities["codexVisualPlan"]["combatKeyMomentsOnly"])
        self.assertFalse(capabilities["codexVisualPlan"]["combatAllPhasesRequired"])
        self.assertFalse(capabilities["codexVisualPlan"]["combatPhaseChangeMayForceStoryboard"])
        self.assertTrue(capabilities["codexVisualPlan"]["combatIntermediatePhasesMayBeOmitted"])
        self.assertTrue(capabilities["codexVisualPlan"]["nonGraphicCombatEffectsPreserved"])
        self.assertEqual("failed_scene_only", capabilities["codexVisualPlan"]["failedPromptRepairScope"])
        self.assertTrue(capabilities["codexVisualPlan"]["placeholderContentRejected"])
        self.assertTrue(capabilities["codexVisualPlan"]["imagePromptSoftMinimumEnforced"])
        self.assertEqual(0.90, capabilities["codexVisualPlan"]["imagePromptMinimumUniqueRatio"])
        self.assertTrue(capabilities["codexVisualPlan"]["mechanicalLineGroupingRejected"])
        self.assertTrue(capabilities["codexVisualPlan"]["shotRoleBalanceGate"])
        self.assertTrue(capabilities["codexVisualPlan"]["impactArcGate"])
        self.assertTrue(capabilities["codexVisualPlan"]["sceneCostumeGroundingRequired"])
        self.assertTrue(capabilities["codexVisualPlan"]["storyPromptPrecedesReferenceMaterial"])
        self.assertTrue(capabilities["codexVisualPlan"]["atomicImageReplacement"])
        self.assertFalse(capabilities["codexVisualPlan"]["speechDurationMaySplitStoryboard"])
        self.assertFalse(capabilities["codexVisualPlan"]["soundEffectStandaloneStoryboard"])
        self.assertTrue(capabilities["audioRouting"]["humanVoiceEngineSelectedByUser"])
        self.assertEqual("seed_audio", capabilities["audioRouting"]["soundEffectEngine"])
        self.assertEqual(5.0, capabilities["audioRouting"]["soundEffectMaxDurationSeconds"])
        self.assertFalse(capabilities["codexVisualPlan"]["workshopMayRewriteLockedPrompts"])
        self.assertFalse(capabilities["codexVisualPlan"]["postGenerationVisualAudit"])

        sound_lines = context.content.service.content._validate_lines(
            [
                {"lineId": "E01-L001", "episodeNumber": 1, "sequence": 1, "speakerId": "narrator", "lineType": "narration", "emotion": "紧张", "text": "她停在门前。"},
                {"lineId": "E01-SFX01", "episodeNumber": 1, "sequence": 2, "speakerId": "sfx", "lineType": "sound_effect", "text": "【sound：门锁突然崩断；时长1.2秒】"},
            ],
            1,
            field="targetScript",
        )
        self.assertEqual("seed_audio", sound_lines[1]["audioEngine"])
        self.assertEqual(1.2, sound_lines[1]["durationSeconds"])
        self.assertFalse(sound_lines[1]["visualGenerationAllowed"])
        cheer_lines = context.content.service.content._validate_lines(
            [
                {"lineId": "E01-SFX01", "episodeNumber": 1, "sequence": 1, "speakerId": "sfx", "lineType": "sound_effect", "text": "【sound：人群突然欢呼；时长1秒】"},
                {"lineId": "E01-L001", "episodeNumber": 1, "sequence": 2, "speakerId": "narrator", "lineType": "narration", "emotion": "喜悦", "text": "旗帜升起。"},
            ],
            1,
            field="targetScript",
        )
        self.assertEqual(2.5, cheer_lines[0]["durationSeconds"])
        self.assertEqual("【sound：人群突然欢呼；时长2.5秒】", cheer_lines[0]["text"])
        self.assert_tool_error(
            "SCRIPT_SOUND_EFFECT_INVALID",
            lambda: context.content.service.content._validate_lines(
                [
                    {"lineId": "E01-L001", "episodeNumber": 1, "sequence": 1, "speakerId": "narrator", "lineType": "narration", "emotion": "紧张", "text": "她停在门前。"},
                    {"lineId": "E01-SFX01", "episodeNumber": 1, "sequence": 2, "speakerId": "sfx", "lineType": "sound_effect", "text": "【sound：过长的风声；时长6秒】"},
                ],
                1,
                field="targetScript",
            ),
        )

    def test_no_probe_voicevox_is_selectable_from_installed_catalog(self) -> None:
        catalog = {
            "engines": [
                {
                    "engineId": "voicevox_external",
                    "displayName": "VOICEVOX 本地配音",
                    "installed": True,
                    "voices": [{"voiceId": "1"}, {"voiceId": "2"}],
                },
                {
                    "engineId": "edge_tts",
                    "displayName": "Edge TTS 在线配音",
                    "installed": True,
                    "voices": [{"voiceId": "ja-JP-KeitaNeural"}],
                },
                {
                    "engineId": "seed_audio",
                    "displayName": "Seed Audio",
                    "installed": True,
                    "voices": [{"voiceId": "seed-ja-01"}],
                },
            ]
        }
        workshop = {
            "externalServiceProbeExecuted": False,
            "voiceEngines": [
                {"engine": "voicevox_external", "configured": True, "available": False},
                {"engine": "edge_tts", "configured": True, "available": True},
                {"engine": "seed_audio", "configured": True, "available": True},
            ],
        }
        view = LocalToolService._production_voice_selection_view(catalog, workshop)
        by_id = {item["engineId"]: item for item in view["humanVoiceEngines"]}
        self.assertEqual("not_probed_is_not_unavailable", view["availabilityRule"])
        self.assertTrue(by_id["voicevox_external"]["humanVoiceSelectable"])
        self.assertEqual("not_probed", by_id["voicevox_external"]["runtimeStatus"])
        self.assertEqual("configured_runtime_check_deferred", by_id["voicevox_external"]["selectionStatus"])
        self.assertTrue(by_id["edge_tts"]["humanVoiceSelectable"])
        self.assertFalse(by_id["seed_audio"]["humanVoiceSelectable"])
        self.assertEqual("reserved_for_sound_effects", by_id["seed_audio"]["selectionStatus"])

    def test_probed_unavailable_voice_engine_is_not_selectable(self) -> None:
        catalog = {
            "engines": [
                {
                    "engineId": "voicevox_external",
                    "displayName": "VOICEVOX 本地配音",
                    "installed": True,
                    "voices": [{"voiceId": "1"}],
                }
            ]
        }
        workshop = {
            "externalServiceProbeExecuted": True,
            "voiceEngines": [{"engine": "voicevox_external", "configured": True, "available": False}],
        }
        view = LocalToolService._production_voice_selection_view(catalog, workshop)
        choice = view["humanVoiceEngines"][0]
        self.assertFalse(choice["humanVoiceSelectable"])
        self.assertEqual("unavailable", choice["runtimeStatus"])
        self.assertEqual("runtime_unavailable", choice["selectionStatus"])

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
            "schemaVersion": "1.5",
            "author": "codex",
            "visualDirection": {
                "mode": "manga_impact",
                "panelMode": "single_panel",
                "singleFocalPoint": True,
                "expressionMode": "exaggerated_story_driven",
                "backgroundSimplification": "impact_adaptive",
                "compositionMode": "story_driven",
                "mangaDeviceLimit": 3,
            },
            "characterDesigns": [
                {
                    "characterId": item["characterId"],
                    "personId": item.get("personId", item["characterId"]),
                    "appearanceId": item.get("appearanceId", item["characterId"]),
                    "lifePhase": item.get("lifePhase", "current_life"),
                    "ageStage": item.get("ageStage", "unspecified"),
                    "referencePolicy": item.get("referencePolicy", "required"),
                    "designIntentZh": "从人物身份与性格建立漫画轮廓记忆点和近景记忆点。",
                    "identityAnchorPromptZh": "漫画人物比例，独特脸型与眼型，分层发束，固定服装轮廓与配色。",
                    "referenceSheetPromptZh": "单画布中一个角色只出现一次，单一正面略偏四分之三视角，只穿一套主服装，清楚服装层次与固定配饰，无剧情背景和可读文字。",
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
            "seriesVisualPlan": {
                "planningMode": "full_series_then_sequence_then_shot",
                "allEpisodesRead": True,
                "episodeNumbers": list(dict.fromkeys(line["episodeNumber"] for line in manuscript["targetScript"]["lines"])),
                "timelineSummaryZh": "完整读取全部集数，按正式稿顺序冻结事件、伏笔与回收关系。",
                "crossEpisodeContinuityZh": "跨集保持角色身份、服装、道具、地点与情绪结果连续。",
            },
            "scenePlans": [],
        }
        visual_ids = {item["characterId"] for item in visual_characters}
        costume_by_character = {item["characterId"]: f"CST-{index:02d}" for index, item in enumerate(visual_characters, start=1)}
        all_lines = manuscript["targetScript"]["lines"]
        previous_scene_by_episode: dict[int, str] = {}
        previous_exit_state_by_episode: dict[int, str] = {}
        for index, line in enumerate(manuscript["targetScript"]["lines"], start=1):
            visible = [line["speakerId"]] if line["speakerId"] in visual_ids else []
            beat_id = "BEAT-HOOK" if index == 1 else "BEAT-REL" if index == 2 else "BEAT-CONFLICT"
            narrative_function = "hook" if index == 1 else "relationship" if index == 2 else "conflict"
            shot_scale = ("close_up", "wide", "medium")[(index - 1) % 3]
            shot_view = ("three_quarter", "back_view", "over_the_shoulder")[(index - 1) % 3]
            episode_number = line["episodeNumber"]
            scene_id = f"CVP-E{episode_number:02d}-S{index:03d}"
            sequence_id = f"SEQ-E{episode_number:02d}-01"
            entry_state_id = previous_exit_state_by_episode.get(episode_number, f"STATE-E{episode_number:02d}-START")
            exit_state_id = f"STATE-E{episode_number:02d}-S{index:03d}-OUT"
            plan["scenePlans"].append(
                {
                    "sceneId": scene_id,
                    "episodeNumber": episode_number,
                    "sequenceId": sequence_id,
                    "shotRole": "climax" if index == 1 else "reaction" if index == 2 else "action",
                    "semanticGroupId": f"VG-E{episode_number:02d}-{index:03d}",
                    "scriptLineIds": [line["lineId"]],
                    "visibleCharacterIds": visible,
                    "appearanceBindings": [
                        {
                            "characterId": character_id,
                            "personId": next(item for item in visual_characters if item["characterId"] == character_id).get("personId", character_id),
                            "appearanceId": next(item for item in visual_characters if item["characterId"] == character_id).get("appearanceId", character_id),
                            "lifePhase": next(item for item in visual_characters if item["characterId"] == character_id).get("lifePhase", "current_life"),
                            "ageStage": next(item for item in visual_characters if item["characterId"] == character_id).get("ageStage", "unspecified"),
                            "referencePolicy": next(item for item in visual_characters if item["characterId"] == character_id).get("referencePolicy", "required"),
                        }
                        for character_id in visible
                    ],
                    "primaryCharacterId": visible[0] if visible else "",
                    "complexityScore": 4,
                    "impactLevel": 5 if index == 1 else 3,
                    "expressionExaggeration": 5 if index == 1 and visible else 3 if visible else 1,
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
                    "continuityState": {
                        "entryStateId": entry_state_id,
                        "entryStateZh": "人物位置、朝向、视线、道具和环境状态承接上一镜。",
                        "exitStateId": exit_state_id,
                        "exitStateZh": "当前唯一动作完成后留下可供下一镜继承的状态。",
                        "characterBlockingZh": "主角位于画面右侧，互动对象位于左侧，人物距离与力量方向明确。",
                        "screenDirectionZh": "人物运动和压力方向保持由左向右，不无故跳轴。",
                        "eyelineZh": "主角视线指向左侧互动对象或关键物。",
                        "propStateZh": "关键物由当前持有人保持在因果视线方向。",
                        "lightingStateZh": "同一场景主光方向、冷暖和明暗关系保持连续。",
                        "carryOverFromSceneId": previous_scene_by_episode.get(episode_number, ""),
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
                    "mangaComposition": {
                        "coreMomentZh": "当前正式稿对应的唯一剧情瞬间",
                        "singleVisualFocusZh": "主要角色骤变的眼神" if visible else "环境中突然出现的关键物",
                        "primaryActionZh": "主要角色完成一个清晰动作" if visible else "关键物改变环境状态",
                        "interactionZh": "主要角色与关系对象形成明确力量方向" if visible else "环境变化预示即将发生的冲突",
                        "shotDesignZh": "单幅漫画分镜，以强透视和有意义留白保持单一焦点",
                        "backgroundMode": "abstract_impact" if index == 1 else "selective_detail",
                        "backgroundTreatmentZh": "高冲击镜头把背景压缩为抽象冲击线" if index == 1 else "只保留解释地点所需的空间特征",
                        "continuityEssentialsZh": "保留当前地点、服装和关键物的固定特征",
                        "clutterControlZh": "移除无关人物、装饰和不承担因果的道具",
                        "mangaDevices": ["impact_burst", "heavy_shadow"] if index == 1 else [],
                    },
                    "facialActing": {
                        "eyeShapeZh": "眼睑随情绪强度明显张开",
                        "pupilZh": "瞳孔收紧并锁定互动对象",
                        "browZh": "眉形产生不对称挤压",
                        "mouthJawZh": "嘴角绷紧、下颌发力",
                        "faceTensionZh": "眼下与嘴角肌肉出现可见张力",
                        "exaggerationTechniqueZh": "以眼口比例和面部线条变化放大剧情冲击",
                    } if visible else {},
                    "bodyActing": {
                        "lineOfActionZh": "身体形成指向互动对象的明确动作线",
                        "centerOfGravityZh": "重心随情绪从后脚移向前脚",
                        "shoulderSpineZh": "肩背从防御收缩转为主动展开",
                        "handTensionZh": "手指由松弛转为明显收紧",
                        "secondaryMotionZh": "头发和衣角沿动作方向产生次级运动",
                    } if visible else {},
                    "combatDirection": {"active": False, "phase": "none"},
                    "promptComponents": {
                        "subjectActionZh": f"第{index}镜主体抬起握紧的右手并把肩线压向左侧关系对象",
                        "visualStoryZh": f"第{index}镜用双方距离收窄和关键物受力呈现冲突因果",
                        "performanceZh": f"第{index}镜瞳孔收紧、眉心下压、嘴角绷住且前脚承重",
                        "cameraCompositionZh": f"第{index}镜采用{shot_scale}景别与{shot_view}视向形成单一面部焦点",
                        "continuityEnvironmentZh": f"第{index}镜保留主要场景冷侧光、轮廓和配色固定、关键物位置",
                        "lightingColorZh": f"第{index}镜冷色主光从右后方切入并压暗左侧压力对象",
                        "keyObjectZh": f"第{index}镜关键物停在两人视线交点并承担唯一因果提示",
                        "battleEffectsZh": "",
                    },
                    "imagePromptZh": "",
                    "videoPromptZh": "人物完成一次明确的表情与重心变化，镜头缓慢推进后停稳。",
                }
            )
            previous_scene_by_episode[episode_number] = scene_id
            previous_exit_state_by_episode[episode_number] = exit_state_id
        for fixture_index, scene in enumerate(plan["scenePlans"], start=1):
            components = scene["promptComponents"]
            scene["imagePromptZh"] = (
                f"单幅漫画静态关键瞬间，第{fixture_index}镜只冻结主体抬手压向关系对象的一刻，唯一视觉焦点位于主体骤紧的眼神与握紧指节；"
                f"{components['subjectActionZh']}；{components['visualStoryZh']}；{components['performanceZh']}；"
                f"{components['cameraCompositionZh']}；{components['continuityEnvironmentZh']}；{components['lightingColorZh']}；"
                f"{components['keyObjectZh']}；人物左右位置、视线高度和压力方向清楚，背景只保留解释地点的石墙轮廓与冷光入口，"
                f"次要装饰、旁观者、招牌和无关道具全部降级，画面禁止可读文字、字母、数字、字幕、对白气泡、标志与水印。"
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
            "pageCountRationaleZh": "先判断相邻行能否共享一个视觉时刻，再只为重要因果、关系和情绪变化保留画面。",
            "semanticGrouping": {
                "mode": "semantic_visual_beat_v2",
                "ttsLineBreakCreatesScene": False,
                "durationCreatesScene": False,
                "mergeBeforeContinuityPlanning": True,
                "lineCountHardCap": False,
                "actionPhaseChangeCreatesScene": False,
                "splitOnlyForImportantVisibleChange": True,
            },
            "combatSelectionPolicy": {
                "mode": "key_moments_only",
                "allPhasesRequired": False,
                "phaseChangeCreatesScene": False,
                "intermediatePhasesMayBeOmitted": True,
            },
            "semanticBeatGroups": [
                {
                    "groupId": scene["semanticGroupId"],
                    "episodeNumber": scene["episodeNumber"],
                    "sourceLineIds": list(scene["scriptLineIds"]),
                    "visualMomentZh": "该行本身承担一个不可被相邻画面替代的重要视觉结果。",
                    "decision": "intentional_single",
                    "reason": "intentional_single_line_impact",
                    "decisionReasonZh": "测试夹具将该行锁为独立重点画面，不以换行或时长作为理由。",
                    "boundaryFromPrevious": "episode_start" if not scene["continuityState"]["carryOverFromSceneId"] else "causal_result_change",
                }
                for scene in plan["scenePlans"]
            ],
            "storyBeats": [
                {"beatId": "BEAT-HOOK", "type": "hook", "summaryZh": "首镜建立观看钩子", "sourceLineIds": [all_lines[0]["lineId"]], "sceneIds": [first_scene_id]},
                {"beatId": "BEAT-REL", "type": "relationship", "summaryZh": "交代人物关系", "sourceLineIds": [all_lines[1]["lineId"]], "sceneIds": [second_scene_id]},
                {"beatId": "BEAT-CONFLICT", "type": "conflict", "summaryZh": "呈现核心冲突与推进", "sourceLineIds": [line["lineId"] for line in all_lines[2:]] or [all_lines[1]["lineId"]], "sceneIds": remaining_scene_ids},
            ],
            "visualSequences": [
                {
                    "sequenceId": f"SEQ-E{episode_number:02d}-01",
                    "episodeNumber": episode_number,
                    "sceneIds": [scene["sceneId"] for scene in plan["scenePlans"] if scene["episodeNumber"] == episode_number],
                    "locationId": "LOC-01",
                    "timeLightingZh": "同一时段，主光方向和环境明暗保持连续。",
                    "paletteContrastZh": "环境综合色调固定，冲击镜头只提高局部明暗反差。",
                    "spatialAxisZh": "主角保持画面右侧、互动对象保持左侧，运动方向不跳轴。",
                    "openingStateId": next(scene for scene in plan["scenePlans"] if scene["episodeNumber"] == episode_number)["continuityState"]["entryStateId"],
                    "closingStateId": [scene for scene in plan["scenePlans"] if scene["episodeNumber"] == episode_number][-1]["continuityState"]["exitStateId"],
                    "continuityFromPreviousZh": "本集首个连续场景承接全剧时间线中的人物、服装与道具状态。",
                    "shotLadder": [scene["shotRole"] for scene in plan["scenePlans"] if scene["episodeNumber"] == episode_number],
                    "impactArc": [scene["impactLevel"] for scene in plan["scenePlans"] if scene["episodeNumber"] == episode_number],
                }
                for episode_number in list(dict.fromkeys(scene["episodeNumber"] for scene in plan["scenePlans"]))
            ],
            "promptCompiler": {
                "mode": "manga_structured_budgeted_merge",
                "imagePromptMaxChars": 600,
                "imagePromptSoftMinChars": 280,
                "imagePromptSoftMaxChars": 450,
                "videoPromptMaxChars": 500,
                "globalStyleRepeatedPerScene": False,
                "identityFullProfileRepeatedPerScene": False,
                "singlePanelDirectiveRequired": True,
                "singleFocalPointRequired": True,
                "clutterControlRequired": True,
                "fullSeriesContextRequired": True,
                "sequencePlanRequired": True,
                "continuityStateRequired": True,
                "temporalSequenceForbidden": True,
                "shotRoleRequired": True,
                "semanticBeatGroupingRequired": True,
                "lineBreakSplitForbidden": True,
                "lineCountHardCapDisabled": True,
                "combatEffectsContractRequired": True,
                "combatKeyMomentSelectionRequired": True,
                "failureRepairScope": "failed_scene_only",
            },
        }
        normalized = _normalize_codex_visual_plan(
            plan,
            manuscript=manuscript,
            production_config=config,
            synthetic=False,
        )
        self.assertEqual("identity_only", normalized["referenceUsage"])
        self.assertEqual("manga_impact", normalized["visualDirection"]["mode"])
        self.assertFalse(normalized["locks"]["workshopMayRewritePrompts"])
        self.assertTrue(normalized["locks"]["singleVisualFocusRequired"])
        self.assertTrue(normalized["locks"]["sequenceContinuityRequired"])
        self.assertEqual("failed_scene_only", normalized["locks"]["failedPromptRepairScope"])
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
        narrator_character = next(item for item in package_characters if item["characterId"] == "narrator")
        self.assertEqual("narrator", narrator_character["personId"])
        self.assertEqual("narrator", narrator_character["appearanceId"])
        self.assertEqual("current_life", narrator_character["lifePhase"])
        self.assertEqual("unspecified", narrator_character["ageStage"])
        self.assertEqual("none", narrator_character["referencePolicy"])
        visual_review = Path(assembled["userReviewDocuments"]["directory"]) / "11B_Codex角色设计与分镜提示词方案.md"
        self.assertTrue(visual_review.is_file())
        self.assertIn("只锁身份，不锁表情", visual_review.read_text(encoding="utf-8"))
        combat = json.loads(json.dumps(plan, ensure_ascii=False))
        combat_scene = combat["scenePlans"][1]
        battle_effects = "蓝白能量集中撞上护盾中央，环形冲击波、定向火星与石屑向外迸开，地面尘雾沿受力方向后压，强光勾出双方轮廓"
        combat_scene["combatDirection"] = {
            "active": True,
            "phase": "impact",
            "frozenMomentZh": "护盾在单一命中点向内凹陷并迸出环形冲击光的瞬间",
            "effectSourceZh": "画面左前方武器释放的蓝白能量",
            "trajectoryZh": "能量沿左下至右上的对角线压向护盾",
            "impactPointZh": "护盾中央偏右的单一高亮接触点",
            "effectShapeColorZh": "蓝白核心、青色外缘的锥形能量与环形冲击波",
            "scaleLayeringZh": "前景飞散火星，中景护盾形变，后景压力波压暗空间",
            "particlesDebrisZh": "接触点喷出短促火星、细碎石屑和定向烟尘",
            "environmentalResponseZh": "地面尘土沿冲击方向掀起，附近旗帜被气浪压向后方",
            "lightingInteractionZh": "蓝白强光照亮双方轮廓，并在背光侧形成深阴影",
            "attackerKineticsZh": "攻方肩胯同向压入，动作线集中指向接触点",
            "defenderResponseZh": "守方前脚陷地、双臂内收，护盾受力但仍保持防线",
            "safetyBoundaryZh": "全年龄非血腥冲突，不呈现伤口、肢体损伤或痛苦过程",
        }
        combat_scene["promptComponents"]["battleEffectsZh"] = battle_effects
        combat_components = combat_scene["promptComponents"]
        combat_scene["imagePromptZh"] = (
            f"单幅漫画静态冲击瞬间，只冻结护盾在单一命中点向内凹陷的一刻，唯一焦点落在蓝白高亮接触点；{battle_effects}；"
            f"{combat_components['subjectActionZh']}；{combat_components['visualStoryZh']}；{combat_components['performanceZh']}；"
            f"{combat_components['cameraCompositionZh']}；{combat_components['continuityEnvironmentZh']}；{combat_components['lightingColorZh']}；"
            "前景火星、中景护盾形变与后景压力波形成清楚尺度，次要人物和无关装饰全部降级，禁止可读文字、字母、数字、字幕、对白气泡、标志与水印。"
        )
        combat_scene["videoPromptZh"] = f"镜头短促推进并停在护盾接触点；{battle_effects}。"
        normalized_combat = _normalize_codex_visual_plan(
            combat,
            manuscript=manuscript,
            production_config=config,
            synthetic=False,
        )
        self.assertTrue(normalized_combat["scenePlans"][1]["combatDirection"]["active"])
        self.assertEqual("impact", normalized_combat["scenePlans"][1]["combatDirection"]["phase"])
        missing_combat_effects = json.loads(json.dumps(combat, ensure_ascii=False))
        missing_scene = missing_combat_effects["scenePlans"][1]
        missing_components = missing_scene["promptComponents"]
        missing_scene["imagePromptZh"] = (
            "单幅漫画静态冲击瞬间，只冻结护盾在单一命中点向内凹陷的一刻，唯一焦点落在盾面中央；"
            f"{missing_components['subjectActionZh']}；{missing_components['visualStoryZh']}；{missing_components['performanceZh']}；"
            f"{missing_components['cameraCompositionZh']}；{missing_components['continuityEnvironmentZh']}；{missing_components['lightingColorZh']}；"
            "前景只保留握紧的手和盾缘，中景突出守方受力姿态，后景压暗为空间压力，移除旁观者、招牌、装饰和无关道具，"
            "禁止可读文字、字母、数字、字幕、对白气泡、标志、水印与签名。"
        )
        self.assert_tool_error(
            "PRODUCTION_CODEX_VISUAL_PLAN_INVALID",
            lambda: _normalize_codex_visual_plan(
                missing_combat_effects,
                manuscript=manuscript,
                production_config=config,
                synthetic=False,
            ),
        )
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
        invalid_character_reference = json.loads(json.dumps(plan, ensure_ascii=False))
        invalid_character_reference["characterDesigns"][0]["referenceSheetPromptZh"] = "多视角角色设定页：正面、三分之二侧面、侧面、全身，并展示两套服装。"
        self.assert_tool_error(
            "PRODUCTION_CODEX_VISUAL_PLAN_INVALID",
            lambda: _normalize_codex_visual_plan(
                invalid_character_reference,
                manuscript=manuscript,
                production_config=config,
                synthetic=False,
            ),
        )
        stage_mismatch = json.loads(json.dumps(plan, ensure_ascii=False))
        first_bound_scene = next(item for item in stage_mismatch["scenePlans"] if item["appearanceBindings"])
        first_bound_scene["appearanceBindings"][0]["ageStage"] = "wrong_age_stage"
        self.assert_tool_error(
            "PRODUCTION_CODEX_VISUAL_PLAN_INVALID",
            lambda: _normalize_codex_visual_plan(
                stage_mismatch,
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
        prompt_under_quality_floor = json.loads(json.dumps(plan, ensure_ascii=False))
        prompt_under_quality_floor["scenePlans"][0]["imagePromptZh"] = "单幅漫画静态关键瞬间，无可读文字。"
        self.assert_tool_error(
            "PRODUCTION_CODEX_VISUAL_PLAN_INVALID",
            lambda: _normalize_codex_visual_plan(
                prompt_under_quality_floor,
                manuscript=manuscript,
                production_config=config,
                synthetic=False,
            ),
        )
        placeholder_content = json.loads(json.dumps(plan, ensure_ascii=False))
        placeholder_content["characterDesigns"][0]["fixedFeatures"][0] = "x"
        self.assert_tool_error(
            "PRODUCTION_CODEX_VISUAL_PLAN_INVALID",
            lambda: _normalize_codex_visual_plan(
                placeholder_content,
                manuscript=manuscript,
                production_config=config,
                synthetic=False,
            ),
        )
        ungrounded_prompt = json.loads(json.dumps(plan, ensure_ascii=False))
        ungrounded_prompt["scenePlans"][0]["imagePromptZh"] = (
            "单幅漫画静态关键瞬间，主体站在石墙前保持中性表情，画面使用柔和侧光与清楚轮廓，背景保持简洁，"
            "人物服装与发型整洁，构图稳定，色彩协调，画面具有商业插画完成度；只保留一个人物和一个道具，"
            "去除旁观者、装饰、招牌和杂乱物体；禁止可读文字、字母、数字、字幕、对白气泡、标志、水印与签名。" * 2
        )[:450]
        self.assert_tool_error(
            "PRODUCTION_CODEX_VISUAL_PLAN_INVALID",
            lambda: _normalize_codex_visual_plan(
                ungrounded_prompt,
                manuscript=manuscript,
                production_config=config,
                synthetic=False,
            ),
        )
        temporal_sequence = json.loads(json.dumps(plan, ensure_ascii=False))
        temporal_sequence["scenePlans"][0]["imagePromptZh"] = "角色先走近石台，然后伸手触碰，随后光芒爆发。"
        self.assert_tool_error(
            "PRODUCTION_CODEX_VISUAL_PLAN_INVALID",
            lambda: _normalize_codex_visual_plan(
                temporal_sequence,
                manuscript=manuscript,
                production_config=config,
                synthetic=False,
            ),
        )
        broken_state_chain = json.loads(json.dumps(plan, ensure_ascii=False))
        broken_state_chain["scenePlans"][1]["continuityState"]["entryStateId"] = "STATE-BROKEN"
        self.assert_tool_error(
            "PRODUCTION_CODEX_VISUAL_PLAN_INVALID",
            lambda: _normalize_codex_visual_plan(
                broken_state_chain,
                manuscript=manuscript,
                production_config=config,
                synthetic=False,
            ),
        )
        cluttered = json.loads(json.dumps(plan, ensure_ascii=False))
        cluttered["scenePlans"][0]["mangaComposition"]["clutterControlZh"] = ""
        self.assert_tool_error(
            "PRODUCTION_CODEX_VISUAL_PLAN_INVALID",
            lambda: _normalize_codex_visual_plan(
                cluttered,
                manuscript=manuscript,
                production_config=config,
                synthetic=False,
            ),
        )
        flat_high_impact = json.loads(json.dumps(plan, ensure_ascii=False))
        flat_high_impact["scenePlans"][0]["expressionExaggeration"] = 2
        if flat_high_impact["scenePlans"][0]["visibleCharacterIds"]:
            self.assert_tool_error(
                "PRODUCTION_CODEX_VISUAL_PLAN_INVALID",
                lambda: _normalize_codex_visual_plan(
                    flat_high_impact,
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

    def test_package_v21_allows_empty_description_hashtags_and_no_custom_thumbnail(self) -> None:
        context = self.context(omit_optional_publishing_assets=True)
        package_root = Path(context.package["packagePath"])
        manifest = context.content.service.production.validate_package(package_root)
        publishing = json.loads((package_root / "publishing.json").read_text(encoding="utf-8"))
        self.assertEqual(8, len(manifest["files"]))
        self.assertEqual("", publishing["descriptionBody"])
        self.assertEqual([], publishing["hashtags"])
        self.assertEqual("", publishing["thumbnail"])
        self.assertEqual("youtube_auto", publishing["thumbnailMode"])
        self.assertFalse((package_root / "confirmed_thumbnail.png").exists())
        imported = context.content.service.production.import_package(package_root)
        self.assertTrue(imported["roundTripValidated"])

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

    def test_real_renderer_invalidation_schedules_a_fresh_selective_workshop_request(self) -> None:
        context = self.context("ja-JP")
        args = mutation_arguments(context)
        completed = context.content.service.call("production_task_run", args)["task"]
        task_path = context.content.service.production._task_path(context.production_task_id)
        task = json.loads(task_path.read_text(encoding="utf-8"))
        task["synthetic"] = False
        task["workshop"] = {
            "requestId": "stage5-old-render-request",
            "lastStatus": {"status": "completed"},
            "artifactSnapshot": {"finalVideoSha256": "f" * 64},
        }
        task_path.write_text(json.dumps(task, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

        invalidation = context.content.service.production.invalidate(
            context.production_task_id,
            changes=["render_engine"],
        )
        updated = invalidation["task"]
        self.assertEqual("RETRYING", updated["state"])
        self.assertIsNone(updated["resultPackagePath"])
        self.assertNotIn("requestId", updated["workshop"])
        self.assertNotIn("lastStatus", updated["workshop"])
        self.assertNotIn("artifactSnapshot", updated["workshop"])
        self.assertEqual("stage5-old-render-request", updated["workshop"]["previousRequestId"])
        final_video = next(asset for asset in updated["assets"] if asset["assetId"] == "final-video")
        self.assertEqual("INVALIDATED", final_video["status"])
        self.assertEqual(completed["productionTaskId"], updated["productionTaskId"])

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

        per_episode = json.loads(json.dumps(config))
        per_episode["gridBatch"] = {
            "template": "wide_16_9_4",
            "selectionSource": "user",
        }
        per_episode["gridBatch"]["episodeTemplates"] = {"E01": "wide_16_9_1", "E02": "wide_16_9_4"}
        per_episode["concurrency"]["image"] = 20
        validated_per_episode = center._validate_production_config(per_episode)
        self.assertEqual({"E01": "wide_16_9_1", "E02": "wide_16_9_4"}, validated_per_episode["gridBatch"]["episodeTemplates"])
        self.assertEqual(20, validated_per_episode["concurrency"]["image"])

        too_much_concurrency = json.loads(json.dumps(per_episode))
        too_much_concurrency["concurrency"]["image"] = 21
        self.assert_tool_error(
            "PRODUCTION_CONFIG_INVALID",
            lambda: center._validate_production_config(too_much_concurrency),
        )

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
            def __init__(self) -> None:
                self.start_calls = 0
                self.status_value = "running"
                self.task_present = True
                self.last_selected_steps = []
                self.last_selected_episodes = []

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

            def start_production(self, _project_path, *, selected_step_ids, selected_episode_ids=(), request_id, **_kwargs):
                self.start_calls += 1
                self.assert_no_placeholder_steps(selected_step_ids)
                self.last_selected_steps = list(selected_step_ids)
                self.last_selected_episodes = list(selected_episode_ids)
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
                    "taskPresent": self.task_present,
                    "status": self.status_value,
                    "error": "fixture failure" if self.status_value == "failed" else "",
                    "message": "",
                }

        bridge = FakeWorkshopBridge()
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

        bridge.task_present = False
        bridge.status_value = "not_started"
        missing_once = center.run_task("formal-routing-task")
        missing_twice = center.run_task("formal-routing-task")
        missing_thrice = center.run_task("formal-routing-task")
        self.assertTrue(missing_once["workshopStartConfirmationPending"])
        self.assertTrue(missing_twice["workshopStartConfirmationPending"])
        self.assertEqual("NEEDS_REPAIR", missing_thrice["task"]["state"])
        self.assertEqual("workshop_task_missing", missing_thrice["task"]["workshop"]["lastErrorDetail"]["category"])
        self.assertEqual(1, bridge.start_calls)

        bridge.task_present = True
        bridge.status_value = "running"
        recovered_observation = center.run_task("formal-routing-task")
        self.assertTrue(recovered_observation["workshopRunning"])
        self.assertEqual("RUNNING", recovered_observation["task"]["state"])

        center.request_pause("formal-routing-task")
        bridge.task_present = False
        resumed = center.resume_task("formal-routing-task")
        self.assertEqual("READY_TO_PRODUCE", resumed["state"])
        self.assertNotIn("requestId", resumed["workshop"])
        restarted_after_pause = center.run_task("formal-routing-task")
        self.assertTrue(restarted_after_pause["workshopStarted"])
        self.assertEqual(2, bridge.start_calls)

        bridge.task_present = True
        bridge.status_value = "failed"
        failed = center.run_task("formal-routing-task")
        self.assertTrue(failed["workshopNeedsAttention"])
        self.assertEqual("unknown", failed["task"]["workshop"]["lastErrorDetail"]["category"])
        self.assertEqual("fixture failure", failed["task"]["history"][-1]["details"]["error"]["message"])
        project_path = Path(failed["task"]["import"]["projectPath"])
        (project_path.parent / "selective-rework-scope.json").write_text(
            json.dumps(
                {
                    "schemaVersion": "1.0",
                    "taskId": "test-task",
                    "projectId": failed["task"]["projectId"],
                    "automaticRemainingWorkflowAuthorization": "task:test-task:auto-remaining-workflow",
                    "authorizationBoundToProjectId": failed["task"]["projectId"],
                    "uploadAuthorized": False,
                    "hardExclusions": ["audio", "storyboard"],
                    "command": {
                        "steps": ["grid_image", "final_render"],
                        "episodes": ["E01"],
                        "skipCompleted": True,
                    },
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        center.retry_failed("formal-routing-task")
        restarted = center.run_task("formal-routing-task")
        self.assertTrue(restarted["workshopStarted"])
        self.assertEqual(3, bridge.start_calls)
        self.assertEqual(["grid_image", "final_render"], bridge.last_selected_steps)
        self.assertEqual(["E01"], bridge.last_selected_episodes)
        self.assertTrue(restarted["task"]["workshop"]["selectiveReworkScope"]["sha256"])


if __name__ == "__main__":
    unittest.main()
