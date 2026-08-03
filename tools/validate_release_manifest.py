from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker

from update_release_manifest import canonical_json_bytes, tree_digest


ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = ROOT / "release-manifests" / "release-v0.1.0-beta.1.json"
SCHEMA_PATH = ROOT / "release-manifests" / "release-manifest.schema.json"


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def validate_release_manifest() -> list[str]:
    manifest = load_json(MANIFEST_PATH)
    schema = load_json(SCHEMA_PATH)
    errors: list[str] = []

    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    for error in sorted(validator.iter_errors(manifest), key=lambda item: list(item.absolute_path)):
        location = "/".join(str(part) for part in error.absolute_path) or "<root>"
        errors.append(f"release-v0.1.0-beta.1.json:{location}: {error.message}")

    expected_hash = hashlib.sha256(canonical_json_bytes(manifest)).hexdigest()
    if manifest.get("contentHash") != expected_hash:
        errors.append(
            "release-v0.1.0-beta.1.json: contentHash mismatch; "
            f"expected {expected_hash}, got {manifest.get('contentHash')}"
        )

    component_ids = [component.get("componentId") for component in manifest.get("components", [])]
    if len(component_ids) != len(set(component_ids)):
        errors.append("release-v0.1.0-beta.1.json: componentId values must be unique")

    for component in manifest.get("components", []):
        artifacts = component.get("artifacts", [])
        if component.get("includedInRelease") and not artifacts:
            errors.append(f"{component.get('componentId')}: included component has no artifact")
        if not component.get("includedInRelease") and artifacts:
            errors.append(f"{component.get('componentId')}: excluded component must not carry artifacts")
        for artifact in artifacts:
            target = (ROOT / artifact["relativePath"]).resolve()
            try:
                target.relative_to(ROOT.resolve())
            except ValueError:
                errors.append(f"{component.get('componentId')}: artifact escapes repository root")
                continue
            if not target.exists():
                errors.append(f"{component.get('componentId')}: missing artifact {artifact['relativePath']}")
                continue
            if artifact["kind"] == "directory-tree":
                actual_hash, actual_size = tree_digest(target)
            else:
                actual_hash = hashlib.sha256(target.read_bytes()).hexdigest()
                actual_size = target.stat().st_size
            if artifact["sha256"] != actual_hash:
                errors.append(f"{component.get('componentId')}: artifact SHA-256 mismatch")
            if artifact["sizeBytes"] != actual_size:
                errors.append(f"{component.get('componentId')}: artifact size mismatch")

    plugin = load_json(ROOT / "plugins" / "ai-video-channel-production" / ".codex-plugin" / "plugin.json")
    if plugin.get("version") != manifest.get("productVersion"):
        errors.append("plugin version does not match productVersion")

    catalog = load_json(ROOT / "contracts" / "contract-catalog.json")
    manifest_versions = manifest.get("schemaVersions", {})
    catalog_types = {entry["contractType"] for entry in catalog["contracts"]}
    if set(manifest_versions) != catalog_types:
        errors.append("schemaVersions keys do not match the contract catalog")

    if manifest.get("releaseStatus") == "published" and manifest.get("gitCommit") is None:
        errors.append("published release requires gitCommit")
    return errors


def main() -> int:
    errors = validate_release_manifest()
    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        print(f"Release manifest validation failed with {len(errors)} error(s).")
        return 1
    print("Release manifest validation passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
