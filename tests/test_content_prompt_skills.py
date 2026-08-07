from __future__ import annotations

import hashlib
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "plugins" / "ai-video-channel-production"


class ContentPromptSkillTests(unittest.TestCase):
    def test_four_prompt_bundles_are_exact_and_routed_in_order(self) -> None:
        manifest = json.loads(
            (PLUGIN / "assets" / "content-prompt-bundles.json").read_text(encoding="utf-8")
        )
        expected = [
            "content-deconstruct",
            "content-rewrite",
            "content-review-edit",
            "content-title-description",
        ]
        self.assertEqual(expected, manifest["sequence"])
        self.assertEqual(expected, [item["skillId"] for item in manifest["bundles"]])
        for item in manifest["bundles"]:
            prompt = PLUGIN / item["bundledPath"]
            payload = prompt.read_bytes()
            self.assertEqual(item["sizeBytes"], len(payload))
            self.assertEqual(item["sha256"], hashlib.sha256(payload).hexdigest())
            skill_text = (PLUGIN / "skills" / item["skillId"] / "SKILL.md").read_text(encoding="utf-8")
            self.assertIn(prompt.name, skill_text)

        router = (PLUGIN / "skills" / "channel-production" / "SKILL.md").read_text(encoding="utf-8")
        positions = [router.index(f"{index}. {skill}") for index, skill in enumerate(expected, start=1)]
        self.assertEqual(positions, sorted(positions))
        self.assertFalse((PLUGIN / "skills" / "production-text").exists())

    def test_title_description_and_thumbnail_share_one_provider(self) -> None:
        registry = json.loads(
            (PLUGIN / "assets" / "content-extension-slots.json").read_text(encoding="utf-8")
        )
        slots = {item["skillId"]: item for item in registry["slots"]}
        for slot_id in ("content-title", "content-description", "content-thumbnail"):
            self.assertEqual("AVAILABLE", slots[slot_id]["status"])
            self.assertTrue(slots[slot_id]["discovered"])
            self.assertEqual("content-title-description", slots[slot_id]["providedBySkillId"])

    def test_three_tier_adaptation_contract_is_generic_and_enforced(self) -> None:
        deconstruct_skill = (
            PLUGIN / "skills" / "content-deconstruct" / "SKILL.md"
        ).read_text(encoding="utf-8")
        deconstruct_prompt = (
            PLUGIN / "skills" / "content-deconstruct" / "references" / "prompt-v2.2.txt"
        ).read_text(encoding="utf-8")
        deconstruct_contract = (
            PLUGIN / "skills" / "content-deconstruct" / "references" / "deconstruction-contract.md"
        ).read_text(encoding="utf-8")
        rewrite_skill = (
            PLUGIN / "skills" / "content-rewrite" / "SKILL.md"
        ).read_text(encoding="utf-8")
        rewrite_prompt = (
            PLUGIN / "skills" / "content-rewrite" / "references" / "prompt-v5.2.txt"
        ).read_text(encoding="utf-8")
        rewrite_gates = (
            PLUGIN / "skills" / "content-rewrite" / "references" / "rewrite-gates.md"
        ).read_text(encoding="utf-8")
        router = (PLUGIN / "skills" / "channel-production" / "SKILL.md").read_text(
            encoding="utf-8"
        )
        review_documents = (
            PLUGIN
            / "skills"
            / "channel-production"
            / "references"
            / "user-review-documents.md"
        ).read_text(encoding="utf-8")

        all_contract_text = "\n".join(
            (
                deconstruct_skill,
                deconstruct_prompt,
                deconstruct_contract,
                rewrite_skill,
                rewrite_prompt,
                rewrite_gates,
                router,
                review_documents,
            )
        )
        for marker in (
            "close-structure",
            "balanced-reconstruction",
            "free-original",
            "mustPreserve",
            "allowedToChange",
            "mustRebuild",
            "protectedExpressionBoundary",
            "sourceFidelityEvidence",
            "nonCopyEvidence",
            "directionDistinctnessMatrix",
            "sourceStoryDNA",
            "expansionSeams",
            "sourceAnchorRefs",
            "naturalExpansionRationale",
            "genericTemplateRisk",
        ):
            self.assertIn(marker, all_contract_text)

        for group_marker in ("A1—A5", "B1—B5", "C1—C5"):
            self.assertIn(group_marker, deconstruct_prompt)
        self.assertIn("共15个方向", deconstruct_prompt)
        self.assertIn("组内与跨组两两去重", deconstruct_prompt)
        self.assertIn("不以“相似度越低越好”为目标", rewrite_gates)
        self.assertIn("不把“与原文有相似结构或桥段”本身判为失败", rewrite_skill)
        self.assertIn("不绑定晚年情感、异世界、职场或任何固定题材模板", deconstruct_skill)
        for narrative_scope in (
            "异世界轻小说",
            "情感故事",
            "现实逆转",
            "纪实",
            "口播文案",
        ):
            self.assertIn(narrative_scope, deconstruct_prompt)
            self.assertIn(narrative_scope, rewrite_prompt)
        self.assertNotIn("不少于六个迁移方向", router)
        self.assertNotIn("不少于六个实质不同方向", review_documents)
        self.assertNotIn("必须输出不少于6个方向", deconstruct_prompt)
        self.assertNotIn("所有主要人物的姓名、身份、职业", rewrite_prompt)
        self.assertNotIn("开局 → 第一目标 → 初次受阻 → 第一次反馈", deconstruct_prompt)
        self.assertNotIn("默认一次性输出完整 4 章", rewrite_prompt)
        self.assertIn("不得给全部方向套统一九段式", deconstruct_prompt)
        self.assertIn("高贴合方向至少绑定 3 个事实锚点", deconstruct_skill)

    def test_video_or_text_imitation_never_routes_to_material_reconstruction(self) -> None:
        skills_root = PLUGIN / "skills"
        router = (skills_root / "channel-production" / "SKILL.md").read_text(encoding="utf-8")
        source_skill = (skills_root / "content-source" / "SKILL.md").read_text(encoding="utf-8")
        for marker in ("下载字幕", "完全仿写", "$content-source → $content-deconstruct"):
            self.assertIn(marker, router)
        self.assertIn("不得改走“素材研究与原创重构”", router)
        self.assertIn("不得自行选择第 2 项", router)
        self.assertIn("不得静默换算", router)
        self.assertIn("固定交给 `$content-deconstruct`", source_skill)
        self.assertIn("不能只交一段主题摘要", source_skill)

    def test_manual_stage_confirmation_is_default_and_covers_every_handoff(self) -> None:
        skills_root = PLUGIN / "skills"
        router = (skills_root / "channel-production" / "SKILL.md").read_text(encoding="utf-8")
        contract = (
            skills_root
            / "channel-production"
            / "references"
            / "manual-stage-confirmations.md"
        ).read_text(encoding="utf-8")

        self.assertIn("默认使用审核模式", router)
        self.assertNotIn("按上图连续执行", router)
        self.assertIn("task:<taskId>:auto-remaining-workflow", contract)
        self.assertIn("新任务立即失效", contract)
        for gate in (
            "D1_CHANNEL_DISTILLATION",
            "D2_DECONSTRUCTION",
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

        for skill_id in (
            "channel-onboarding",
            "content-source",
            "content-deconstruct",
            "content-rewrite",
            "content-review-edit",
            "content-title-description",
            "publishing-assets",
            "production-handoff",
            "publish-video",
        ):
            skill_text = (skills_root / skill_id / "SKILL.md").read_text(encoding="utf-8")
            self.assertIn("manual-stage-confirmations.md", skill_text, skill_id)

        title_skill = (skills_root / "content-title-description" / "SKILL.md").read_text(
            encoding="utf-8"
        )
        for gate in ("P1_TITLE", "P2_DESCRIPTION", "P3_THUMBNAIL"):
            self.assertIn(gate, title_skill)


if __name__ == "__main__":
    unittest.main()
