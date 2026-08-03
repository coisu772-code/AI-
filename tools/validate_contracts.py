from __future__ import annotations

import argparse
import copy
import hashlib
import json
import sys
from pathlib import Path
from typing import Any, Iterable

from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry, Resource


ROOT = Path(__file__).resolve().parents[1]
CONTRACTS_ROOT = ROOT / "contracts"


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def canonical_json_bytes(document: dict[str, Any]) -> bytes:
    payload = copy.deepcopy(document)
    payload.pop("contentHash", None)
    return json.dumps(
        payload,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def content_hash(document: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_json_bytes(document)).hexdigest()


def iter_contract_references(value: Any) -> Iterable[dict[str, Any]]:
    if isinstance(value, dict):
        keys = {
            "targetContractType",
            "targetId",
            "targetVersion",
            "targetSchemaVersion",
            "targetHash",
        }
        if keys.issubset(value):
            yield value
        for child in value.values():
            yield from iter_contract_references(child)
    elif isinstance(value, list):
        for child in value:
            yield from iter_contract_references(child)


def build_registry(schema_paths: Iterable[Path]) -> Registry:
    resources: list[tuple[str, Resource[Any]]] = []
    for path in schema_paths:
        schema = load_json(path)
        schema_id = schema.get("$id")
        if not schema_id:
            raise ValueError(f"Schema is missing $id: {path}")
        resources.append((schema_id, Resource.from_contents(schema)))
    return Registry().with_resources(resources)


def validate_contracts(examples_dir: Path) -> list[str]:
    catalog = load_json(CONTRACTS_ROOT / "contract-catalog.json")
    schema_paths = sorted((CONTRACTS_ROOT / "schemas").glob("*.schema.json"))
    registry = build_registry(schema_paths)
    contracts = {entry["contractType"]: entry for entry in catalog["contracts"]}

    documents: list[tuple[Path, dict[str, Any]]] = []
    index: dict[tuple[str, str, str], dict[str, Any]] = {}
    errors: list[str] = []

    for entry in catalog.get("packageDocuments", []):
        schema_path = CONTRACTS_ROOT / entry["schema"]
        if not schema_path.is_file():
            errors.append(f"{entry.get('documentType')}: schema is missing: {entry['schema']}")
            continue
        try:
            Draft202012Validator.check_schema(load_json(schema_path))
        except Exception as exc:  # noqa: BLE001 - report every broken package document schema
            errors.append(f"{entry.get('documentType')}: invalid schema: {exc}")

    for entry in catalog.get("rulesCatalogs", []):
        schema_path = CONTRACTS_ROOT / entry["schema"]
        document_path = CONTRACTS_ROOT / entry["document"]
        if not schema_path.is_file() or not document_path.is_file():
            errors.append(f"{entry.get('catalogType')}: catalog document or schema is missing")
            continue
        validator = Draft202012Validator(load_json(schema_path), registry=registry, format_checker=FormatChecker())
        for validation_error in validator.iter_errors(load_json(document_path)):
            location = "/".join(str(part) for part in validation_error.absolute_path) or "<root>"
            errors.append(f"{entry.get('catalogType')}:{location}: {validation_error.message}")

    for path in sorted(examples_dir.glob("*.json")):
        try:
            document = load_json(path)
        except Exception as exc:  # noqa: BLE001 - validation should report every input error
            errors.append(f"{path.name}: unreadable JSON: {exc}")
            continue
        documents.append((path, document))
        key = (document.get("contractType", ""), document.get("id", ""), document.get("version", ""))
        if key in index:
            errors.append(f"{path.name}: duplicate contract identity {key}")
        index[key] = document

    for path, document in documents:
        contract_type = document.get("contractType")
        catalog_entry = contracts.get(contract_type)
        if not catalog_entry:
            errors.append(f"{path.name}: unknown contractType {contract_type!r}")
            continue

        schema_path = CONTRACTS_ROOT / catalog_entry["schema"]
        schema = load_json(schema_path)
        validator = Draft202012Validator(schema, registry=registry, format_checker=FormatChecker())
        for validation_error in sorted(validator.iter_errors(document), key=lambda item: list(item.absolute_path)):
            location = "/".join(str(part) for part in validation_error.absolute_path) or "<root>"
            errors.append(f"{path.name}:{location}: {validation_error.message}")

        id_field = catalog_entry["idField"]
        if document.get("id") != document.get(id_field):
            errors.append(f"{path.name}: id must equal {id_field}")

        actual_hash = content_hash(document)
        if document.get("contentHash") != actual_hash:
            errors.append(
                f"{path.name}: contentHash mismatch; expected {actual_hash}, got {document.get('contentHash')}"
            )

        for reference in iter_contract_references(document):
            target_key = (
                reference["targetContractType"],
                reference["targetId"],
                reference["targetVersion"],
            )
            target = index.get(target_key)
            if target is None:
                errors.append(f"{path.name}: unresolved upstream reference {target_key}")
                continue
            if reference["targetSchemaVersion"] != target.get("schemaVersion"):
                errors.append(f"{path.name}: schema version mismatch for {target_key}")
            if reference["targetHash"] != target.get("contentHash"):
                errors.append(f"{path.name}: upstream hash mismatch for {target_key}")

    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate stage 1 cross-center contracts.")
    parser.add_argument(
        "--examples",
        type=Path,
        default=CONTRACTS_ROOT / "examples" / "valid",
        help="Directory containing contract JSON examples.",
    )
    args = parser.parse_args()

    errors = validate_contracts(args.examples.resolve())
    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        print(f"Contract validation failed with {len(errors)} error(s).")
        return 1

    count = len(list(args.examples.resolve().glob("*.json")))
    print(f"Contract validation passed: {count} example(s).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
