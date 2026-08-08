from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description="Bind deterministic unified assets to the verified source commit.")
    parser.add_argument("--asset-root", type=Path, required=True)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--metadata-commit")
    args = parser.parse_args()
    if not re.fullmatch(r"[0-9a-f]{40}", args.source_commit):
        raise SystemExit("source commit must be 40 lowercase hexadecimal characters")
    if args.metadata_commit and not re.fullmatch(r"[0-9a-f]{40}", args.metadata_commit):
        raise SystemExit("metadata commit must be 40 lowercase hexadecimal characters")
    root = args.asset_root.resolve()
    manifest_path = root / "unified-release-v0.11.0-rc.4.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    bound_assets = 0
    changed = 0
    for asset in manifest["assets"]:
        source = asset.get("source", {})
        if asset.get("assetId") in {"unified-installer", "core"}:
            current = source.get("commit")
            if current != "LOCAL_COMMIT_TO_BE_RECORDED" and not isinstance(current, str):
                raise SystemExit(f"invalid source commit binding for {asset.get('assetId')}")
            if current != "LOCAL_COMMIT_TO_BE_RECORDED" and not re.fullmatch(r"[0-9a-f]{40}", current):
                raise SystemExit(f"invalid source commit binding for {asset.get('assetId')}")
            bound_assets += 1
            if current != args.source_commit:
                source["commit"] = args.source_commit
                changed += 1
        if args.metadata_commit and asset["assetId"] == "core":
            source["metadataCommit"] = args.metadata_commit
    gates = manifest["publicationGates"]
    if "replace-local-commit-placeholders" in gates:
        gates[gates.index("replace-local-commit-placeholders")] = "tag-to-source-commit-verification"
    if bound_assets != 2 or changed not in {0, 2}:
        raise SystemExit(f"unexpected source binding state: assets={bound_assets}, changed={changed}")
    rendered = json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    manifest_path.write_text(rendered, encoding="utf-8", newline="\n")
    names = [asset["fileName"] for asset in manifest["assets"]]
    for package in manifest.get("optionalRuntimePackages", []):
        if not package.get("source", {}).get("releaseTag"):
            names.append(package["manifest"]["fileName"])
            names.extend(part["fileName"] for part in package["parts"])
    names.append(manifest_path.name)
    (root / "SHA256SUMS.txt").write_text(
        "".join(f"{sha256(root / name)}  {name}\n" for name in sorted(names)), encoding="ascii", newline="\n"
    )
    print(json.dumps({"status":"BOUND","sourceCommit":args.source_commit,"metadataCommit":args.metadata_commit,"manifestSha256":sha256(manifest_path)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
