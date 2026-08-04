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
    args = parser.parse_args()
    if not re.fullmatch(r"[0-9a-f]{40}", args.source_commit):
        raise SystemExit("source commit must be 40 lowercase hexadecimal characters")
    root = args.asset_root.resolve()
    manifest_path = root / "unified-release-v0.8.0-rc.2.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    changed = 0
    for asset in manifest["assets"]:
        source = asset.get("source", {})
        if source.get("commit") == "LOCAL_COMMIT_TO_BE_RECORDED":
            source["commit"] = args.source_commit
            changed += 1
    gates = manifest["publicationGates"]
    if "replace-local-commit-placeholders" in gates:
        gates[gates.index("replace-local-commit-placeholders")] = "tag-to-source-commit-verification"
    if changed not in {0, 2}:
        raise SystemExit(f"unexpected number of source placeholders: {changed}")
    rendered = json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    manifest_path.write_text(rendered, encoding="utf-8", newline="\n")
    names = [asset["fileName"] for asset in manifest["assets"]] + [manifest_path.name]
    (root / "SHA256SUMS.txt").write_text(
        "".join(f"{sha256(root / name)}  {name}\n" for name in sorted(names)), encoding="ascii", newline="\n"
    )
    print(json.dumps({"status":"BOUND","sourceCommit":args.source_commit,"manifestSha256":sha256(manifest_path)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
