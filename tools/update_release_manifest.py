from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
TEXT_SUFFIXES = {".cmd", ".json", ".md", ".ps1", ".py", ".txt", ".yaml", ".yml"}


def current_manifest_path() -> Path:
    plugin = json.loads(
        (ROOT / "plugins" / "ai-video-channel-production" / ".codex-plugin" / "plugin.json").read_text(
            encoding="utf-8"
        )
    )
    return ROOT / "release-manifests" / f"release-v{plugin['version']}.json"


def canonical_json_bytes(document: dict[str, Any]) -> bytes:
    payload = dict(document)
    payload.pop("contentHash", None)
    return json.dumps(
        payload,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def normalized_file_bytes(path: Path) -> bytes:
    data = path.read_bytes()
    if path.suffix.lower() not in TEXT_SUFFIXES:
        return data
    text = data.decode("utf-8-sig")
    return text.replace("\r\n", "\n").replace("\r", "\n").encode("utf-8")


def tree_digest(path: Path) -> tuple[str, int]:
    records: list[str] = []
    total_size = 0
    files = [
        item
        for item in path.rglob("*")
        if item.is_file()
        and "__pycache__" not in item.relative_to(path).parts
        and item.suffix.lower() != ".pyc"
    ]
    for file_path in sorted(files, key=lambda item: item.relative_to(path).as_posix()):
        relative = file_path.relative_to(path).as_posix()
        payload = normalized_file_bytes(file_path)
        size = len(payload)
        digest = hashlib.sha256(payload).hexdigest()
        records.append(f"{relative}\t{size}\t{digest}\n")
        total_size += size
    tree_hash = hashlib.sha256("".join(records).encode("utf-8")).hexdigest()
    return tree_hash, total_size


def main() -> int:
    manifest_path = current_manifest_path()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["generatedAt"] = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    for component in manifest["components"]:
        for artifact in component["artifacts"]:
            target = ROOT / artifact["relativePath"]
            if artifact["kind"] == "file":
                artifact["sha256"] = hashlib.sha256(target.read_bytes()).hexdigest()
                artifact["sizeBytes"] = target.stat().st_size
            else:
                artifact["sha256"], artifact["sizeBytes"] = tree_digest(target)
    manifest["contentHash"] = hashlib.sha256(canonical_json_bytes(manifest)).hexdigest()
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    index_path = ROOT / "release-manifests" / "version-index.json"
    if index_path.is_file():
        index = json.loads(index_path.read_text(encoding="utf-8"))
        for entry in index.get("versions", []):
            entry_path = ROOT / "release-manifests" / entry["manifest"]
            if not entry_path.is_file():
                raise FileNotFoundError(entry_path)
            entry_manifest = json.loads(entry_path.read_text(encoding="utf-8"))
            entry["manifestContentHash"] = entry_manifest["contentHash"]
            entry["manifestFileSha256"] = hashlib.sha256(entry_path.read_bytes()).hexdigest()
        index_path.write_text(json.dumps(index, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Updated {manifest_path.name}: {manifest['contentHash']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
