from __future__ import annotations

import hashlib
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "plugins" / "ai-video-channel-production"


class ContentPromptSkillTests(unittest.TestCase):
    def test_active_prompt_bundles_are_exact(self) -> None:
        manifest = json.loads(
            (PLUGIN / "assets" / "content-prompt-bundles.json").read_text(encoding="utf-8")
        )
        expected = ["content-review-edit", "content-title-description"]
        self.assertEqual(expected, manifest["sequence"])
        self.assertEqual(expected, [item["skillId"] for item in manifest["bundles"]])
        for item in manifest["bundles"]:
            prompt = PLUGIN / item["bundledPath"]
            payload = prompt.read_bytes()
            self.assertEqual(item["sizeBytes"], len(payload))
            self.assertEqual(item["sha256"], hashlib.sha256(payload).hexdigest())
            skill_text = (PLUGIN / "skills" / item["skillId"] / "SKILL.md").read_text(encoding="utf-8")
            self.assertIn(prompt.name, skill_text)

    def test_old_deconstruction_and_direction_skills_are_retired(self) -> None:
        skills_root = PLUGIN / "skills"
        self.assertFalse((skills_root / "content-deconstruct").exists())
        self.assertFalse((skills_root / "content-rewrite" / "references" / "prompt-v5.2.txt").exists())
        self.assertFalse((skills_root / "content-rewrite" / "references" / "rewrite-gates.md").exists())

        router = (skills_root / "channel-production" / "SKILL.md").read_text(encoding="utf-8")
        source = (skills_root / "content-source" / "SKILL.md").read_text(encoding="utf-8")
        rewrite = (skills_root / "content-rewrite" / "SKILL.md").read_text(encoding="utf-8")
        service = (PLUGIN / "mcp" / "aivcp_tools" / "service.py").read_text(encoding="utf-8")
        content = (PLUGIN / "mcp" / "aivcp_tools" / "content.py").read_text(encoding="utf-8")

        self.assertIn("旧内置拆解、仿写方向和频道内旧项目入口均不得成为新任务默认路线", router)
        self.assertIn("旧内置拆解和仿写方向能力已经移除", source)
        self.assertIn("content_workspace_get", rewrite)
        self.assertIn("不得调用 `channel_list`", rewrite)
        self.assertIn("task-prompt-guided", rewrite)
        self.assertIn("提示词正文", rewrite)
        self.assertIn("RETIRED_CONTENT_TOOL_PREFIXES", service)
        self.assertIn("if not name.startswith(RETIRED_CONTENT_TOOL_PREFIXES)", service)
        for route in (
            '"single-reference": {"available": False',
            '"multi-reference": {"available": False',
            '"book-deconstruction": {"available": False',
            '"imitation": {"available": False',
            '"direct-rewrite": {"available": False',
            '"synthesis-rewrite": {"available": False',
        ):
            self.assertIn(route, content)
        self.assertIn('"task-prompt-guided": {', content)
        self.assertIn('"promptBodiesInstalledAsSkills": False', content)

    def test_link_or_text_import_stops_after_source(self) -> None:
        skills_root = PLUGIN / "skills"
        router = (skills_root / "channel-production" / "SKILL.md").read_text(encoding="utf-8")
        source = (skills_root / "content-source" / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("保存完整规范正文及段落／时间证据索引后停止", router)
        self.assertIn("CONTENT_READY", source)
        self.assertIn("来源任务结束", source)
        self.assertIn("不自动交给拆解、方向推荐或正文生成", source)

    def test_writing_requires_current_confirmed_outline(self) -> None:
        rewrite = (PLUGIN / "skills" / "content-rewrite" / "SKILL.md").read_text(encoding="utf-8")
        for marker in (
            "不少于 80 字",
            "主角",
            "主要因果推进",
            "结局边界",
            "content_workspace_get",
            "content_workspace_document_save",
            "content_workspace_document_confirm",
            "不得调用 `channel_list`",
            "$content-review-edit",
        ):
            self.assertIn(marker, rewrite)

    def test_title_description_and_thumbnail_share_one_provider(self) -> None:
        registry = json.loads(
            (PLUGIN / "assets" / "content-extension-slots.json").read_text(encoding="utf-8")
        )
        slots = {item["skillId"]: item for item in registry["slots"]}
        for slot_id in ("content-title", "content-description", "content-thumbnail"):
            self.assertEqual("AVAILABLE", slots[slot_id]["status"])
            self.assertTrue(slots[slot_id]["discovered"])
            self.assertEqual("content-title-description", slots[slot_id]["providedBySkillId"])

    def test_hotspot_research_precedes_writing_and_production_settings_are_deferred(self) -> None:
        skills_root = PLUGIN / "skills"
        router = (skills_root / "channel-production" / "SKILL.md").read_text(encoding="utf-8")
        source = (skills_root / "content-source" / "SKILL.md").read_text(encoding="utf-8")
        handoff = (skills_root / "production-handoff" / "SKILL.md").read_text(encoding="utf-8")
        stage_contract = (
            skills_root / "channel-production" / "references" / "manual-stage-confirmations.md"
        ).read_text(encoding="utf-8")

        for marker in (
            "R0_RESEARCH_SELECTION",
            "00_热点检索与创作素材选择.md",
            "来源标题与可点击链接",
            "公开热度／趋势依据",
        ):
            self.assertIn(marker, router)
        self.assertIn("用户没有选择前不得写小说", source)
        self.assertIn("G5B_PRODUCTION", handoff)
        self.assertIn("内容阶段不得提前显示或确认这些设置", stage_contract)
        self.assertIn("仅确认视频提示词不得开启实际视频生成", handoff)
        self.assertIn("视频输入模式（仅首帧／首尾帧）", handoff)
        self.assertIn("不得静默退回仅首帧", handoff)
        self.assertIn("frameInputMode=first_last_frame", router)

    def test_manual_stage_confirmation_excludes_retired_gate(self) -> None:
        skills_root = PLUGIN / "skills"
        contract = (
            skills_root / "channel-production" / "references" / "manual-stage-confirmations.md"
        ).read_text(encoding="utf-8")
        self.assertIn("task:<taskId>:auto-remaining-workflow", contract)
        self.assertIn("新任务立即失效", contract)
        self.assertNotIn("D2_DECONSTRUCTION", contract)
        for gate in (
            "R0_RESEARCH_SELECTION",
            "D1_CHANNEL_DISTILLATION",
            "D2_TASK_PROMPT_ANALYSIS",
            "D3_TOPIC",
            "D4_REWRITE_DRAFT",
            "D5_FINAL_MANUSCRIPT",
            "P1_TITLE",
            "P2_DESCRIPTION",
            "P3_THUMBNAIL",
            "G5_PUBLISHING_ASSETS",
            "G5B_PRODUCTION",
            "G6_FINAL_CHINESE_REVIEW",
        ):
            self.assertIn(gate, contract)

    def test_user_prompt_files_are_task_local_and_never_bundled_as_skills(self) -> None:
        skills_root = PLUGIN / "skills"
        router = (skills_root / "channel-production" / "SKILL.md").read_text(encoding="utf-8")
        source = (skills_root / "content-source" / "SKILL.md").read_text(encoding="utf-8")
        for marker in (
            "content_workspace_prompt_register",
            "taskId + workspaceId + projectId + promptId + SHA-256",
            "不得复制提示词正文",
            "content_workspace_document_save",
            "不强制先生成分析或大纲",
        ):
            self.assertIn(marker, router)
        self.assertIn("提示词正文不得复制进 Skill", source)


if __name__ == "__main__":
    unittest.main()
