from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PLUGIN_ROOT = ROOT / "plugins" / "ai-video-channel-production"
sys.path.insert(0, str(PLUGIN_ROOT / "mcp"))
sys.path.insert(0, str(ROOT / "tests"))

from aivcp_tools.errors import ToolError  # noqa: E402
from aivcp_tools.service import LocalToolService, ServiceConfig, tool_definitions  # noqa: E402
from stage4_support import create_service  # noqa: E402
from stage5_support import production_config  # noqa: E402


class WorkspaceProductionBridgeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="aivcp-workspace-production-bridge-")
        self.root = Path(self.temp.name)
        self.service, self.task_id, self.channel_id, self.channel_proof = create_service(
            self.root,
            "en-US",
            plugin_root=PLUGIN_ROOT,
            local_tool_service=LocalToolService,
            service_config=ServiceConfig,
        )
        self.project_id = "workspace-production-bridge"
        started = self.service.call(
            "content_workspace_start",
            {"taskId": self.task_id, "projectId": self.project_id},
        )
        self.workspace_id = started["workspace"]["workspaceId"]
        self.workspace_proof = started["workspaceBindingProof"]
        self.target_lines = [
            {
                "lineId": "E01-L001",
                "episodeNumber": 1,
                "sequence": 1,
                "speakerId": "narrator",
                "lineType": "narration",
                "emotion": "concerned",
                "text": "The neighborhood station posted its final broadcast date on a quiet Monday morning.",
            },
            {
                "lineId": "E01-L002",
                "episodeNumber": 1,
                "sequence": 2,
                "speakerId": "protagonist",
                "lineType": "dialogue",
                "emotion": "determined",
                "text": "Maya asked every resident to record the small memories the city had overlooked.",
            },
            {
                "lineId": "E01-L003",
                "episodeNumber": 1,
                "sequence": 3,
                "speakerId": "narrator",
                "lineType": "narration",
                "emotion": "hopeful",
                "text": "One verified agreement protected the studio, and the station reopened as a community cooperative.",
            },
        ]
        self.audit_lines = [
            {**self.target_lines[0], "text": "社区电台在一个安静的周一早晨公布了最后播出日期。"},
            {**self.target_lines[1], "text": "玛雅请每位居民录下这座城市曾经忽略的小小记忆。"},
            {**self.target_lines[2], "text": "一份经过核验的协议保护了演播室，电台最终以社区合作社的形式重新开放。"},
        ]

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _production_settings(self) -> dict:
        config = production_config(sound_effects_enabled=False)
        config["settingsContractVersion"] = "2.0"
        config["productionMode"] = {"id": "balanced", "selectionSource": "user", "confirmed": True}
        config["deliveryModeSelectionSource"] = "user"
        config["promptGeneration"] = {
            "image": False,
            "video": False,
            "selectionSource": "user",
            "confirmed": True,
        }
        config["videoGeneration"].update({"selectionSource": "user", "confirmed": True, "count": 0})
        config["sceneImageCadence"] = {
            "mode": "semantic_auto",
            "selectionSource": "user",
            "confirmed": True,
        }
        config["soundEffects"] = {
            "enabled": False,
            "selectionSource": "user",
            "confirmed": True,
            "backgroundMusicEnabled": False,
        }
        config["privacyStatus"] = "private"
        config["uploadPolicy"] = "REQUIRE_REVIEW"
        return config

    def _quality_gate(self) -> dict:
        return {
            "passed": True,
            "episodes": [
                {
                    "episode": 1,
                    "passed": True,
                    "revisionCount": 0,
                    "checks": {
                        "locked-facts": True,
                        "story-progress": True,
                        "character-voice": True,
                        "target-language-naturalness": True,
                        "regional-expression": True,
                        "terminology-consistency": True,
                        "tts-semantic-lines": True,
                        "audience-reward": True,
                    },
                }
            ],
        }

    def _foreign_quality_gate(self) -> dict:
        return {
            "passed": True,
            "reviewMode": "independent-second-pass",
            "independentFromAuthoring": True,
            "authoringPassId": "workspace-authoring-pass",
            "reviewPassId": "workspace-independent-review-pass",
            "summaryZh": "独立二次审校确认英语语法、地区表达、术语、习语、称谓、TTS 可读性及中文审核映射全部通过。",
            "episodes": [
                {
                    "episode": 1,
                    "passed": True,
                    "revisionCount": 0,
                    "findingsZh": "英语正式稿表达自然，结构化行与中文审核稿逐项一致。",
                    "checks": {
                        "grammar-and-syntax": True,
                        "regional-naturalness": True,
                        "naming-and-terminology": True,
                        "idiom-and-collocation": True,
                        "translationese-avoidance": True,
                        "cultural-address": True,
                        "tts-readability": True,
                        "chinese-review-consistency": True,
                    },
                }
            ],
        }

    def _characters(self) -> list[dict]:
        catalog = json.loads((self.root / "voice-catalog.json").read_text(encoding="utf-8"))
        voice = {
            "engineId": "fixture-tts",
            "voiceId": "fixture-us-001",
            "voiceName": "Synthetic en-US Voice",
            "catalogVersion": "1.0.0",
            "catalogHash": catalog["contentHash"],
        }
        return [
            {
                "characterId": "narrator",
                "targetLanguageName": "Narrator",
                "role": "narration",
                "goal": "guide the audience through the verified story",
                "relationship": "connect the audience to the community",
                "speakingStyle": "clear and warm",
                "visualConsistencyRequired": False,
                "voice": voice,
            },
            {
                "characterId": "protagonist",
                "targetLanguageName": "Maya",
                "role": "community radio host",
                "goal": "preserve the station for public use",
                "relationship": "organizes residents into a cooperative",
                "speakingStyle": "direct, calm, and determined",
                "visualConsistencyRequired": True,
                "visualAnchorPromptZh": "单人，年轻社区电台主持人，深色短发，坚定而温暖的眼神，简洁日常服装",
                "voice": voice,
            },
        ]

    def _prepare_workspace(self) -> tuple[str, dict]:
        narration_content = "\n".join(item["text"] for item in self.target_lines)
        saved = self.service.call(
            "content_workspace_document_save",
            {
                "taskId": self.task_id,
                "workspaceId": self.workspace_id,
                "workspaceBindingProof": self.workspace_proof,
                "documentId": "formal-manuscript",
                "title": "Confirmed formal manuscript",
                "stage": "final",
                "purpose": "sole production source",
                "language": "en-US",
                "content": narration_content,
                "mediaType": "text/plain",
            },
        )["document"]
        self.service.call(
            "content_workspace_document_confirm",
            {
                "taskId": self.task_id,
                "workspaceId": self.workspace_id,
                "workspaceBindingProof": self.workspace_proof,
                "documentId": "formal-manuscript",
                "confirmation": {
                    "confirmed": True,
                    "confirmationRef": f"task:{self.task_id}:confirm-content:{self.workspace_id}:formal-manuscript:v001",
                    "sha256": saved["sha256"],
                },
            },
        )
        config = self._production_settings()
        bound = self.service.call(
            "content_workspace_bind_production",
            {
                "taskId": self.task_id,
                "workspaceId": self.workspace_id,
                "workspaceBindingProof": self.workspace_proof,
                "channelProfileId": self.channel_id,
                "channelBindingProof": self.channel_proof,
                "productionSourceDocumentId": "formal-manuscript",
                "productionConfig": config,
                "confirmation": {
                    "confirmed": True,
                    "confirmationRef": f"task:{self.task_id}:start-production:{self.workspace_id}:{self.channel_id}",
                    "channelSerial": "01",
                },
            },
        )
        self.service.call(
            "content_workspace_narration_prepare",
            {
                "taskId": self.task_id,
                "workspaceId": self.workspace_id,
                "workspaceBindingProof": self.workspace_proof,
                "sourceDocumentId": "formal-manuscript",
                "language": "en-US",
                "narrationTitle": "One Recording Saved the Station",
                "narrationTitleChinese": "一段录音挽救了社区电台",
                "narrationContent": narration_content,
            },
        )
        return bound["productionHandoffPath"], config

    def _materialize(self, handoff_path: str) -> dict:
        return self.service.call(
            "content_workspace_production_materialize",
            {
                "taskId": self.task_id,
                "channelProfileId": self.channel_id,
                "bindingProof": self.channel_proof,
                "workspaceId": self.workspace_id,
                "workspaceBindingProof": self.workspace_proof,
                "productionHandoffPath": handoff_path,
                "storyBible": {
                    "lockedFacts": ["The station faces closure and a verified agreement protects its public use."],
                    "worldRules": ["Only verified records can change the public decision."],
                    "relationships": ["Maya and the residents move from farewell to cooperative ownership."],
                    "timeline": ["Closure is announced.", "Residents record memories.", "The agreement is verified.", "The station reopens."],
                    "foreshadowing": ["The first recording mentions an old public-use promise."],
                    "climax": "The forgotten agreement is verified before the final broadcast.",
                    "ending": "The station reopens as a community cooperative.",
                },
                "characters": self._characters(),
                "targetScript": self.target_lines,
                "chineseAuditScript": self.audit_lines,
                "qualityGate": self._quality_gate(),
                "foreignLanguageQualityGate": self._foreign_quality_gate(),
                "authoringMode": "target-language-native",
                "soundEffects": {"enabled": False, "selectionSource": "user", "confirmed": True},
            },
        )

    def test_workspace_narration_materializes_and_assembles_without_manual_topic_flow(self) -> None:
        definitions = {item["name"] for item in tool_definitions()}
        self.assertIn("content_workspace_production_materialize", definitions)
        handoff_path, config = self._prepare_workspace()
        materialized = self._materialize(handoff_path)
        self.assertFalse(materialized["idempotent"])
        self.assertEqual("creative-workspace-confirmed-manuscript", materialized["package"]["confirmation"]["source"])
        self.assertEqual("spoken-lines", materialized["package"]["workspaceHandoffBinding"]["narrationBindingMode"])
        second = self._materialize(handoff_path)
        self.assertTrue(second["idempotent"])
        self.service.call(
            "content_publishing_finalize",
            {
                "taskId": self.task_id,
                "channelProfileId": self.channel_id,
                "bindingProof": self.channel_proof,
                "projectId": self.project_id,
                "title": "One Recording Saved the Station",
                "titleChinese": "一段录音挽救了社区电台",
                "titleSource": "confirmed_narration",
                "storySummaryChinese": "社区电台面临关闭，玛雅组织居民保存记忆并找到经过核验的公共使用协议，最终让电台以合作社形式重新开放。",
                "confirmation": {"confirmed": True, "mode": "review", "confirmedBy": "synthetic-fixture-user"},
            },
        )
        integrity = self.service.call(
            "content_integrity_check",
            {"channelProfileId": self.channel_id, "projectId": self.project_id},
        )
        handoff = self.service.call(
            "content_handoff_check",
            {"channelProfileId": self.channel_id, "projectId": self.project_id},
        )
        self.assertEqual("PASS", integrity["status"])
        self.assertTrue(handoff["eligible"])
        assembled = self.service.call(
            "production_package_assemble",
            {
                "taskId": self.task_id,
                "channelProfileId": self.channel_id,
                "bindingProof": self.channel_proof,
                "projectId": self.project_id,
                "productionConfig": config,
                "productionPreset": {
                    "id": "synthetic-workspace-production",
                    "version": "1.0.0",
                    "hash": "1" * 64,
                    "targetRegion": "United States",
                },
                "workshopCompatibility": {"interfaceVersion": "2.1", "workshopVersion": "workspace-bridge-fixture"},
                "synthetic": True,
            },
        )
        package_root = Path(assembled["packagePath"])
        source_lock = json.loads((package_root / "source_lock.json").read_text(encoding="utf-8"))
        self.assertEqual(self.workspace_id, source_lock["workspaceHandoffBinding"]["workspaceId"])
        self.assertEqual(materialized["package"]["targetScript"]["lines"], json.loads((package_root / "script_lines.json").read_text(encoding="utf-8"))["lines"])

    def test_structured_lines_must_match_frozen_narration(self) -> None:
        handoff_path, _ = self._prepare_workspace()
        self.target_lines[1]["text"] = "This unauthorized rewrite must be rejected."
        with self.assertRaises(ToolError) as caught:
            self._materialize(handoff_path)
        self.assertEqual("NARRATION_STRUCTURED_LINES_MISMATCH", caught.exception.code)


if __name__ == "__main__":
    unittest.main()
