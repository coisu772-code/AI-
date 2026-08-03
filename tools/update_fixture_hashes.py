from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from validate_contracts import CONTRACTS_ROOT, content_hash, iter_contract_references, load_json


def main() -> int:
    catalog = load_json(CONTRACTS_ROOT / "contract-catalog.json")
    examples_dir = CONTRACTS_ROOT / "examples" / "valid"
    by_type = {
        load_json(path)["contractType"]: path
        for path in examples_dir.glob("*.json")
    }
    hashes: dict[tuple[str, str, str], str] = {}

    for entry in catalog["contracts"]:
        contract_type = entry["contractType"]
        path = by_type.get(contract_type)
        if path is None:
            raise SystemExit(f"Missing valid fixture for {contract_type}")
        document: dict[str, Any] = load_json(path)

        for reference in iter_contract_references(document):
            key = (
                reference["targetContractType"],
                reference["targetId"],
                reference["targetVersion"],
            )
            if key not in hashes:
                raise SystemExit(f"Fixture order is not topological; missing {key} for {path.name}")
            reference["targetHash"] = hashes[key]

        document["contentHash"] = content_hash(document)
        key = (document["contractType"], document["id"], document["version"])
        hashes[key] = document["contentHash"]
        path.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"Updated {path.name}: {document['contentHash']}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
