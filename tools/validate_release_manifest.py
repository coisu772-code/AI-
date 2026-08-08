from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker

from update_release_manifest import canonical_json_bytes, tree_digest


ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = ROOT / "release-manifests" / "release-manifest.schema.json"


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def current_manifest_path() -> Path:
    plugin = load_json(ROOT / "plugins" / "ai-video-channel-production" / ".codex-plugin" / "plugin.json")
    return ROOT / "release-manifests" / f"release-v{plugin['version']}.json"


def validate_release_manifest(manifest_path: Path | None = None) -> list[str]:
    plugin = load_json(ROOT / "plugins" / "ai-video-channel-production" / ".codex-plugin" / "plugin.json")
    if plugin.get("version") == "0.11.0-rc.4" and manifest_path is None:
        selected = ROOT / "release-manifests" / "unified-release-v0.11.0-rc.4.json"
        if not selected.is_file():
            return ["unified-release-v0.11.0-rc.4.json is missing"]
        manifest = load_json(selected)
        schema = load_json(ROOT / "release-manifests" / "unified-release-manifest.schema.json")
        errors = []
        for error in Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(manifest):
            location = "/".join(str(part) for part in error.absolute_path) or "<root>"
            errors.append(f"{selected.name}:{location}: {error.message}")
        ids = [asset.get("assetId") for asset in manifest.get("assets", [])]
        if set(ids) != {"unified-installer", "core", "python-runtime", "workshop", "publisher-center"} or len(ids) != len(set(ids)):
            errors.append("unified release must contain exactly the five locked asset IDs")
        if any(asset.get("assetId") in {"workshop", "publisher-center"} and not asset.get("install") for asset in manifest.get("assets", [])):
            errors.append("workshop and publisher center must be installed release assets")
        publisher = next((asset for asset in manifest.get("assets", []) if asset.get("assetId") == "publisher-center"), {})
        if publisher.get("license", {}).get("reviewStatus") != "technical-inventory-validated-release-owner-approval-required":
            errors.append("publisher technical inventory status or external release-owner gate is missing")
        source = publisher.get("source", {})
        if source.get("commit") != "00adafe9fa6b358991616793d545e0ef0def9ee9":
            errors.append("publisher source commit is not locked to the final candidate")
        component_attestation = source.get("componentManifest", {})
        if (
            component_attestation.get("fileName") != "publisher-component-manifest-v0.9.0-rc.2.json"
            or component_attestation.get("sha256") != "f72626579dc4fd4cd3e8a52a75266209469d99cdf37b2f9b815f25c9ada36748"
        ):
            errors.append("publisher component reuse attestation is not locked")
        if source.get("constraintsCatalog", {}).get("sha256") != "28788480458f37ba86584b4c63e0ef998081ac521ecd9fd0b1724c2a6074b99a":
            errors.append("publisher constraints catalog is not locked")
        if "release-license-owner-approval" not in manifest.get("publicationGates", []):
            errors.append("technical license validation must retain external release-owner approval")
        return errors
    selected_path = manifest_path or current_manifest_path()
    manifest = load_json(selected_path)
    manifest_name = selected_path.name
    schema = load_json(SCHEMA_PATH)
    errors: list[str] = []

    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    for error in sorted(validator.iter_errors(manifest), key=lambda item: list(item.absolute_path)):
        location = "/".join(str(part) for part in error.absolute_path) or "<root>"
        errors.append(f"{manifest_name}:{location}: {error.message}")

    expected_hash = hashlib.sha256(canonical_json_bytes(manifest)).hexdigest()
    if manifest.get("contentHash") != expected_hash:
        errors.append(
            f"{manifest_name}: contentHash mismatch; "
            f"expected {expected_hash}, got {manifest.get('contentHash')}"
        )

    component_ids = [component.get("componentId") for component in manifest.get("components", [])]
    if len(component_ids) != len(set(component_ids)):
        errors.append(f"{manifest_name}: componentId values must be unique")

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
