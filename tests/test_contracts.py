from __future__ import annotations

import copy
import hashlib
import json
import os
import struct
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "plugins" / "ai-video-channel-production" / "mcp"))

from validate_contracts import CONTRACTS_ROOT, content_hash, load_json, validate_contracts  # noqa: E402
from validate_release_manifest import validate_release_manifest  # noqa: E402
from aivcp_tools.contracts import resolve_contracts_root  # noqa: E402


class ContractValidationTests(unittest.TestCase):
    def _validate_fixture_mutation(self, filename: str, mutate) -> list[str]:
        source_dir = CONTRACTS_ROOT / "examples" / "valid"
        with tempfile.TemporaryDirectory() as temp_dir:
            target_dir = Path(temp_dir)
            for source in source_dir.glob("*.json"):
                document = load_json(source)
                if source.name == filename:
                    mutate(document)
                    document["contentHash"] = content_hash(document)
                (target_dir / source.name).write_text(
                    json.dumps(document, ensure_ascii=False), encoding="utf-8"
                )
            return validate_contracts(target_dir)

    def test_valid_fixture_chain(self) -> None:
        errors = validate_contracts(CONTRACTS_ROOT / "examples" / "valid")
        self.assertEqual([], errors)

    def test_hash_changes_after_mutation(self) -> None:
        fixture = load_json(CONTRACTS_ROOT / "examples" / "valid" / "channel-profile.json")
        original_hash = content_hash(fixture)
        mutated = copy.deepcopy(fixture)
        mutated["displayName"] = "Changed example"
        self.assertNotEqual(original_hash, content_hash(mutated))

    def test_invalid_hash_fixture_is_rejected(self) -> None:
        invalid = load_json(CONTRACTS_ROOT / "examples" / "valid" / "channel-profile.json")
        invalid["contentHash"] = "0" * 64
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "channel-profile.json"
            path.write_text(__import__("json").dumps(invalid, ensure_ascii=False), encoding="utf-8")
            errors = validate_contracts(Path(temp_dir))
        self.assertTrue(any("contentHash mismatch" in error for error in errors), errors)

    def test_release_manifest(self) -> None:
        self.assertEqual([], validate_release_manifest())

    def test_contract_root_falls_back_from_codex_cache_to_installed_product(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            cached_plugin = root / "cache" / "marketplace" / "plugin" / "version"
            cached_plugin.mkdir(parents=True)
            installed_contracts = root / "product" / "current" / "contracts"
            installed_contracts.mkdir(parents=True)
            previous = os.environ.get("AIVCP_INSTALL_ROOT")
            os.environ["AIVCP_INSTALL_ROOT"] = str(root / "product")
            try:
                self.assertEqual(installed_contracts.resolve(), resolve_contracts_root(cached_plugin))
            finally:
                if previous is None:
                    os.environ.pop("AIVCP_INSTALL_ROOT", None)
                else:
                    os.environ["AIVCP_INSTALL_ROOT"] = previous

    def test_upstream_hash_mismatch_is_rejected(self) -> None:
        source_dir = CONTRACTS_ROOT / "examples" / "valid"
        with tempfile.TemporaryDirectory() as temp_dir:
            target_dir = Path(temp_dir)
            for source in source_dir.glob("*.json"):
                document = load_json(source)
                if source.name == "topic-package.json":
                    document["upstream"][0]["targetHash"] = "0" * 64
                    document["contentHash"] = content_hash(document)
                (target_dir / source.name).write_text(
                    json.dumps(document, ensure_ascii=False), encoding="utf-8"
                )
            errors = validate_contracts(target_dir)
        self.assertTrue(any("upstream hash mismatch" in error for error in errors), errors)

    def test_missing_required_field_is_rejected(self) -> None:
        invalid = load_json(CONTRACTS_ROOT / "examples" / "valid" / "channel-profile.json")
        invalid.pop("displayName")
        invalid["contentHash"] = content_hash(invalid)
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "channel-profile.json"
            path.write_text(json.dumps(invalid, ensure_ascii=False), encoding="utf-8")
            errors = validate_contracts(Path(temp_dir))
        self.assertTrue(any("displayName" in error and "required" in error for error in errors), errors)

    def test_partial_source_requires_explicit_user_acceptance(self) -> None:
        def mutate(document: dict) -> None:
            document["sourceInputs"][0]["acceptedStatus"] = "PARTIAL"

        errors = self._validate_fixture_mutation("topic-package.json", mutate)
        self.assertTrue(any("partialAcceptance" in error and "required" in error for error in errors), errors)

    def test_selected_topic_requires_g3_confirmation(self) -> None:
        def mutate(document: dict) -> None:
            document["selectionConfirmation"]["status"] = "PENDING"
            document["selectionConfirmation"].pop("confirmedAt")

        errors = self._validate_fixture_mutation("topic-package.json", mutate)
        self.assertTrue(any("selectionConfirmation/status" in error and "APPROVED" in error for error in errors), errors)

    def test_auto_approval_requires_explicit_authorization_reference(self) -> None:
        def mutate(document: dict) -> None:
            document["selectionConfirmation"]["mode"] = "auto"

        errors = self._validate_fixture_mutation("topic-package.json", mutate)
        self.assertTrue(any("authorizationRef" in error and "required" in error for error in errors), errors)

    def test_selected_channel_route_requires_ten_real_candidate_records(self) -> None:
        def mutate(document: dict) -> None:
            document["sourceMode"] = "channel-library"
            document["route"] = "channel-profile-anchored"

        errors = self._validate_fixture_mutation("topic-package.json", mutate)
        self.assertTrue(any("candidates" in error and "too short" in error for error in errors), errors)
        self.assertTrue(any("checkpoints/completedUnits" in error for error in errors), errors)

    def test_failed_line_mapping_cannot_be_script_ready(self) -> None:
        def mutate(document: dict) -> None:
            document["lineMapping"]["checks"]["speakersMatch"] = False

        errors = self._validate_fixture_mutation("manuscript-package.json", mutate)
        self.assertTrue(any("speakersMatch" in error and "True was expected" in error for error in errors), errors)

    def test_chinese_target_uses_target_script_without_duplicate_audit_files(self) -> None:
        def mutate(document: dict) -> None:
            document["targetLanguage"] = "zh-CN"
            audit = document["auditScript"]
            audit["mode"] = "same-as-target"
            audit["duplicateFileCreated"] = False
            audit["targetScriptReference"] = "targetScript"
            audit.pop("asset")
            audit.pop("textAsset")
            audit.pop("lines")
            document["lineMapping"]["mappingMode"] = "same-as-target"

        errors = self._validate_fixture_mutation("manuscript-package.json", mutate)
        self.assertFalse(any(error.startswith("manuscript-package.json:") for error in errors), errors)

    def test_chinese_target_rejects_duplicate_audit_files(self) -> None:
        def mutate(document: dict) -> None:
            document["targetLanguage"] = "zh-CN"
            document["auditScript"]["mode"] = "same-as-target"
            document["auditScript"]["duplicateFileCreated"] = False
            document["auditScript"]["targetScriptReference"] = "targetScript"
            document["lineMapping"]["mappingMode"] = "same-as-target"

        errors = self._validate_fixture_mutation("manuscript-package.json", mutate)
        self.assertTrue(any("auditScript" in error and "should not be valid" in error for error in errors), errors)

    def test_hashtag_count_is_enforced(self) -> None:
        def mutate(document: dict) -> None:
            document["hashtags"] = document["hashtags"][:7]

        errors = self._validate_fixture_mutation("publishing-asset-package.json", mutate)
        self.assertTrue(any("publishing-asset-package.json:hashtags" in error for error in errors), errors)

    def test_description_hashtags_and_custom_thumbnail_may_all_be_omitted(self) -> None:
        def mutate(document: dict) -> None:
            document["descriptionBody"] = ""
            document["hashtags"] = []
            document["thumbnailProvider"] = None
            document["thumbnailStrategy"] = None
            document["thumbnailCandidates"] = []
            document["thumbnailSelection"] = None
            document["thumbnail"] = {
                "mode": "youtube_auto",
                "reason": "user-did-not-request-custom-thumbnail",
            }
            document["ctrReview"] = {
                "status": "NOT_APPLICABLE",
                "conclusion": "No custom thumbnail was requested.",
            }
            document["productionHandoff"] = {
                "eligible": True,
                "assessedAt": "2026-08-03T15:05:00Z",
                "blockers": [],
            }

        errors = self._validate_fixture_mutation("publishing-asset-package.json", mutate)
        publishing_errors = [error for error in errors if error.startswith("publishing-asset-package.json:")]
        self.assertEqual([], publishing_errors)

    def test_thumbnail_aspect_ratio_declaration_is_enforced(self) -> None:
        def mutate(document: dict) -> None:
            document["thumbnail"]["aspectRatio"] = "4:3"

        errors = self._validate_fixture_mutation("publishing-asset-package.json", mutate)
        self.assertTrue(any("thumbnail" in error and "not valid under any" in error for error in errors), errors)

    def test_prompt_only_thumbnail_cannot_be_handoff_ready(self) -> None:
        def mutate(document: dict) -> None:
            document["thumbnail"] = {
                "mode": "prompt_only",
                "prompt": "Synthetic prompt without a rendered image.",
                "providerStatus": "not_requested",
            }
            document["productionHandoff"] = {
                "eligible": False,
                "assessedAt": "2026-08-03T15:05:00Z",
                "blockers": ["A real thumbnail is required."],
            }

        errors = self._validate_fixture_mutation("publishing-asset-package.json", mutate)
        self.assertTrue(any("status" in error and "AWAITING_THUMBNAIL" in error for error in errors), errors)

    def test_contracts_reject_long_term_learning_write_payloads(self) -> None:
        def mutate(document: dict) -> None:
            document["channelLearningWrite"] = {"scope": "channel_default"}

        errors = self._validate_fixture_mutation("topic-package.json", mutate)
        self.assertTrue(any("channelLearningWrite" in error and "Unevaluated" in error for error in errors), errors)

    def test_current_project_change_cannot_escalate_to_channel_default(self) -> None:
        def mutate(document: dict) -> None:
            document["learningContext"]["currentProjectChanges"][0]["scope"] = "channel_default"
            document["learningContext"]["longTermWriteAllowed"] = True

        errors = self._validate_fixture_mutation("topic-package.json", mutate)
        self.assertTrue(any("learningContext" in error for error in errors), errors)

    def test_missing_book_or_style_skill_must_be_declared_unavailable(self) -> None:
        def mutate(document: dict) -> None:
            document["extensionCapabilities"] = [
                item for item in document["extensionCapabilities"] if item["capability"] != "book-analysis"
            ]

        errors = self._validate_fixture_mutation("topic-package.json", mutate)
        self.assertTrue(any("extensionCapabilities" in error and "too short" in error for error in errors), errors)

    def test_synthetic_thumbnail_fixture_is_real_readable_16_by_9_and_hashed(self) -> None:
        publishing = load_json(CONTRACTS_ROOT / "examples" / "valid" / "publishing-asset-package.json")
        thumbnail = publishing["thumbnail"]
        fixture_path = CONTRACTS_ROOT / "examples" / "valid" / thumbnail["asset"]["relativePath"]
        payload = fixture_path.read_bytes()
        self.assertEqual(b"\x89PNG\r\n\x1a\n", payload[:8])
        width, height = struct.unpack(">II", payload[16:24])
        self.assertEqual((1600, 900), (width, height))
        self.assertEqual(16 * height, 9 * width)
        self.assertEqual(len(payload), thumbnail["asset"]["sizeBytes"])
        self.assertEqual(hashlib.sha256(payload).hexdigest(), thumbnail["asset"]["sha256"])


if __name__ == "__main__":
    unittest.main()
