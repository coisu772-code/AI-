from __future__ import annotations

import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from validate_contracts import CONTRACTS_ROOT, content_hash, load_json, validate_contracts  # noqa: E402
from validate_release_manifest import validate_release_manifest  # noqa: E402


class ContractValidationTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
