from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PLUGIN_ROOT = ROOT / "plugins" / "ai-video-channel-production"
sys.path.insert(0, str(PLUGIN_ROOT / "mcp"))

from aivcp_tools.creative_workspace import CreativeWorkspace  # noqa: E402
from aivcp_tools.errors import ToolError  # noqa: E402
from aivcp_tools.service import tool_definitions  # noqa: E402
from aivcp_tools.store import ChannelStore  # noqa: E402


class CreativeWorkspaceFlowTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="aivcp-creative-workspace-")
        self.store = ChannelStore(Path(self.temp.name) / "data")
        self.workspace = CreativeWorkspace(self.store)
        started = self.workspace.start(task_id="task-free-001", project_id="project-free-001")
        self.workspace_id = started["workspace"]["workspaceId"]
        self.proof = started["workspaceBindingProof"]

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _save_and_confirm(self) -> dict:
        saved = self.workspace.save_document(
            task_id="task-free-001",
            workspace_id=self.workspace_id,
            binding_proof=self.proof,
            document_id="formal-manuscript",
            title="正式稿",
            stage="final",
            purpose="后续制作来源",
            language="zh-CN",
            content="这是已经确认的正式文稿。",
        )["document"]
        ref = f"task:task-free-001:confirm-content:{self.workspace_id}:formal-manuscript:v001"
        return self.workspace.confirm_document(
            task_id="task-free-001",
            workspace_id=self.workspace_id,
            binding_proof=self.proof,
            document_id="formal-manuscript",
            confirmation={"confirmed": True, "confirmationRef": ref, "sha256": saved["sha256"]},
        )["document"]

    def test_new_workspace_is_channel_free_and_does_not_touch_channel_list(self) -> None:
        state = self.workspace.get(workspace_id=self.workspace_id)["workspace"]
        self.assertEqual("UNBOUND", state["channelBindingStatus"])
        self.assertIsNone(state["channelProfileId"])
        self.assertEqual([], self.store.list_channels())
        with self.assertRaises(ToolError) as caught:
            self.workspace.assert_legacy_project_start_allowed(
                task_id="task-free-001",
                channel_profile_id="ch_not_selected",
            )
        self.assertEqual("CONTENT_WORKSPACE_PRODUCTION_HANDOFF_REQUIRED", caught.exception.code)

    def test_new_document_version_invalidates_old_confirmation(self) -> None:
        self._save_and_confirm()
        updated = self.workspace.save_document(
            task_id="task-free-001",
            workspace_id=self.workspace_id,
            binding_proof=self.proof,
            document_id="formal-manuscript",
            title="正式稿",
            stage="final",
            purpose="后续制作来源",
            language="zh-CN",
            content="这是用户修改后的第二版正式文稿。",
        )["document"]
        self.assertEqual(2, updated["version"])
        self.assertFalse(updated["confirmation"]["confirmed"])

    def test_production_binding_requires_explicit_channel_and_gate_then_narration(self) -> None:
        self._save_and_confirm()
        auth_ref = f"task:task-free-001:auto-upload:{self.workspace_id}"
        self.workspace.authorize_auto_upload(
            task_id="task-free-001",
            workspace_id=self.workspace_id,
            binding_proof=self.proof,
            authorization={
                "authorized": True,
                "explicitUserInstruction": True,
                "confirmationRef": auth_ref,
                "sourceText": "完成制作后自动上传",
            },
        )
        channel, _ = self.store.create_pending_channel(
            publisher_channel={
                "publisherProfileId": "publisher-01",
                "channelSerial": "01",
                "youtubeChannelId": "UC1234567890",
                "displayName": "测试频道",
            },
            target_region="JP",
            output_language="ja-JP",
        )
        channel_binding = self.store.bind_task(task_id="task-free-001", channel_profile_id=channel["channelProfileId"])
        gate_ref = f"task:task-free-001:start-production:{self.workspace_id}:{channel['channelProfileId']}"
        result = self.workspace.bind_for_production(
            task_id="task-free-001",
            workspace_id=self.workspace_id,
            binding_proof=self.proof,
            channel_profile_id=channel["channelProfileId"],
            channel_binding_proof=channel_binding["bindingProof"],
            production_source_document_id="formal-manuscript",
            production_config={
                "voice": "voice-01",
                "imageStyle": "visual_01",
                "uploadPolicy": "AUTO",
                "privacyStatus": "private",
            },
            confirmation={"confirmed": True, "confirmationRef": gate_ref, "channelSerial": "01"},
        )
        self.assertEqual("BOUND_FOR_PRODUCTION", result["productionHandoff"]["status"])
        self.assertFalse(result["autoUploadReconfirmationRequired"])
        self.workspace.assert_legacy_project_start_allowed(
            task_id="task-free-001",
            channel_profile_id=channel["channelProfileId"],
            production_handoff_path=result["productionHandoffPath"],
        )
        narration = self.workspace.prepare_narration(
            task_id="task-free-001",
            workspace_id=self.workspace_id,
            binding_proof=self.proof,
            source_document_id="formal-manuscript",
            language="ja-JP",
            narration_content="制作に使うナレーション本文です。",
        )["narration"]
        self.assertTrue(narration["productionUseAllowed"])

    def test_unapproved_spoken_chapter_heading_is_blocked(self) -> None:
        self.test_production_binding_requires_explicit_channel_and_gate_then_narration()
        with self.assertRaises(ToolError) as caught:
            self.workspace.prepare_narration(
                task_id="task-free-001",
                workspace_id=self.workspace_id,
                binding_proof=self.proof,
                source_document_id="formal-manuscript",
                language="zh-CN",
                narration_content="第一章\n这是正文。",
            )
        self.assertEqual("NARRATION_SPOKEN_HEADING_FOUND", caught.exception.code)

    def test_default_tool_surface_exposes_free_workspace_before_legacy_project(self) -> None:
        definitions = {item["name"]: item for item in tool_definitions()}
        self.assertIn("content_workspace_start", definitions)
        self.assertNotIn("channelProfileId", definitions["content_workspace_start"]["inputSchema"]["required"])
        self.assertIn("content_workspace_narration_prepare", definitions)


if __name__ == "__main__":
    unittest.main()
