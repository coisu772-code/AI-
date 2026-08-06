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

    def test_title_and_description_share_one_provider_while_thumbnail_stays_reserved(self) -> None:
        registry = json.loads(
            (PLUGIN / "assets" / "content-extension-slots.json").read_text(encoding="utf-8")
        )
        slots = {item["skillId"]: item for item in registry["slots"]}
        for slot_id in ("content-title", "content-description"):
            self.assertEqual("AVAILABLE", slots[slot_id]["status"])
            self.assertTrue(slots[slot_id]["discovered"])
            self.assertEqual("content-title-description", slots[slot_id]["providedBySkillId"])
        self.assertEqual("PLANNED_UNAVAILABLE", slots["content-thumbnail"]["status"])
        self.assertFalse(slots["content-thumbnail"]["discovered"])


if __name__ == "__main__":
    unittest.main()
