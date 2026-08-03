from __future__ import annotations

import hashlib
import json
import struct
import sys
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry, Resource


ROOT = Path(__file__).resolve().parents[1]
CONTRACTS = ROOT / "contracts"
PACKAGES = ROOT / "tests" / "fixtures" / "stage4" / "packages"


def read_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError(f"not an object: {path}")
    return value


def canonical_hash(value: dict[str, Any]) -> str:
    payload = dict(value)
    payload.pop("contentHash", None)
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, allow_nan=False, separators=(",", ":"), sort_keys=True).encode("utf-8")
    ).hexdigest()


def file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def registry_and_schemas() -> tuple[Registry, dict[str, dict[str, Any]]]:
    resources = []
    schemas = {}
    for path in sorted((CONTRACTS / "schemas").glob("*.schema.json")):
        schema = read_json(path)
        resources.append((schema["$id"], Resource.from_contents(schema)))
        schemas[path.name] = schema
    return Registry().with_resources(resources), schemas


def validate_asset(root: Path, descriptor: dict[str, Any], label: str, errors: list[str]) -> None:
    path = root / descriptor["relativePath"]
    if not path.is_file():
        errors.append(f"{label}: missing asset {descriptor['relativePath']}")
        return
    if path.stat().st_size != descriptor["sizeBytes"] or file_hash(path) != descriptor["sha256"]:
        errors.append(f"{label}: asset hash/size mismatch {descriptor['relativePath']}")


def validate_stage4_packages(packages_root: Path = PACKAGES) -> list[str]:
    errors: list[str] = []
    index_path = packages_root / "fixture-index.json"
    if not index_path.is_file():
        return ["fixture-index.json is missing"]
    index = read_json(index_path)
    if index.get("syntheticFixture") is not True or index.get("onlineData") is not False or index.get("userData") is not False:
        errors.append("fixture index does not explicitly declare synthetic/non-online/non-user data")
    markets = index.get("markets")
    if not isinstance(markets, list) or len(markets) != 3:
        errors.append("fixture index must list exactly three markets")
        return errors
    registry, schemas = registry_and_schemas()
    contract_specs = (
        ("topic-package", "topic-package.schema.json", "topic-package"),
        ("manuscript-package", "manuscript-package.schema.json", "manuscript-package"),
        ("publishing-asset-package", "publishing-asset-package.schema.json", "publishing-asset-package"),
    )
    for market in markets:
        language = market.get("language")
        root = packages_root / str(market.get("path"))
        label = str(language)
        validation_path = root / "validation.json"
        if not validation_path.is_file():
            errors.append(f"{label}: validation.json missing")
            continue
        validation = read_json(validation_path)
        if validation.get("syntheticFixture") is not True or validation.get("integrity", {}).get("status") != "PASS" or validation.get("handoff", {}).get("eligible") is not True:
            errors.append(f"{label}: stored validation result is not PASS/eligible synthetic data")
        source = read_json(root / "source-package" / "manifest.json")
        if canonical_hash(source) != source.get("contentHash") or source.get("status") != "CONTENT_READY":
            errors.append(f"{label}: source package hash/status invalid")
        for asset in source.get("assets", []):
            validate_asset(root / "source-package", asset, label, errors)
        contracts = {}
        for directory, schema_name, contract_type in contract_specs:
            package_root = root / directory
            manifest = read_json(package_root / "manifest.json")
            contracts[contract_type] = manifest
            if canonical_hash(manifest) != manifest.get("contentHash"):
                errors.append(f"{label}: {contract_type} canonical hash mismatch")
            validator = Draft202012Validator(schemas[schema_name], registry=registry, format_checker=FormatChecker())
            for item in validator.iter_errors(manifest):
                location = "/".join(str(part) for part in item.absolute_path) or "<root>"
                errors.append(f"{label}: {contract_type}:{location}: {item.message}")
        topic = contracts["topic-package"]
        manuscript = contracts["manuscript-package"]
        publishing = contracts["publishing-asset-package"]
        source_refs = [item for item in topic["upstream"] if item["targetContractType"] == "source-package"]
        if len(source_refs) != 1 or source_refs[0]["targetHash"] != source["contentHash"]:
            errors.append(f"{label}: Topic does not bind the exported Source Package")
        if manuscript["upstream"][0]["targetHash"] != topic["contentHash"]:
            errors.append(f"{label}: Manuscript does not bind Topic hash")
        if publishing["upstream"][0]["targetHash"] != manuscript["contentHash"]:
            errors.append(f"{label}: Publishing does not bind Manuscript hash")
        manuscript_root = root / "manuscript-package"
        for group in ("targetScript", "auditScript"):
            for key in ("asset", "textAsset"):
                descriptor = manuscript[group].get(key)
                if descriptor:
                    validate_asset(manuscript_root, descriptor, label, errors)
        if language.startswith("zh"):
            if manuscript["auditScript"]["mode"] != "same-as-target" or (manuscript_root / "chinese-audit-script.json").exists() or (manuscript_root / "chinese-audit-script.txt").exists():
                errors.append(f"{label}: Chinese manuscript duplicated an audit file")
        elif manuscript["auditScript"]["mode"] != "backtranslation":
            errors.append(f"{label}: non-Chinese manuscript lacks line backtranslation")
        publishing_root = root / "publishing-asset-package"
        thumbnail = publishing["thumbnail"]
        validate_asset(publishing_root, thumbnail["asset"], label, errors)
        thumbnail_path = publishing_root / thumbnail["asset"]["relativePath"]
        with thumbnail_path.open("rb") as handle:
            header = handle.read(24)
        if len(header) != 24 or header[:8] != b"\x89PNG\r\n\x1a\n":
            errors.append(f"{label}: confirmed thumbnail is not readable PNG")
        else:
            width, height = struct.unpack(">II", header[16:24])
            if width * 9 != height * 16 or width != thumbnail["widthPixels"] or height != thumbnail["heightPixels"]:
                errors.append(f"{label}: thumbnail dimensions are not verified 16:9")
        if not 8 <= len(publishing["hashtags"]) <= 12 or len(publishing["thumbnailCandidates"]) != 5:
            errors.append(f"{label}: publishing counts are invalid")
        if publishing["confirmation"]["status"] != "APPROVED" or publishing["productionHandoff"]["eligible"] is not True:
            errors.append(f"{label}: publishing confirmation/handoff gate invalid")
    return errors


def main() -> int:
    errors = validate_stage4_packages()
    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        print(f"Stage4 fixture package validation failed with {len(errors)} error(s).")
        return 1
    print("Stage4 fixture package validation passed: 3 markets, 9 frozen packages.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
