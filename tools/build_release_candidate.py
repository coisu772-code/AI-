from __future__ import annotations

import argparse
import hashlib
import json
import stat
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
VERSION = "0.8.0-rc.1"
PACKAGE_ROOT = "ai-video-channel-production"
TEXT_SUFFIXES = {".cmd", ".json", ".md", ".ps1", ".py", ".txt", ".yaml", ".yml"}
PAYLOAD_ITEMS = (
    ".agents",
    "plugins",
    "contracts",
    "installer",
    "release-manifests",
    "docs",
    "README.md",
    "CHANGELOG.md",
    "LICENSE.md",
)
FIXED_ZIP_TIME = (2026, 8, 4, 0, 0, 0)


def normalized_bytes(path: Path) -> bytes:
    data = path.read_bytes()
    if path.suffix.lower() not in TEXT_SUFFIXES:
        return data
    return data.decode("utf-8-sig").replace("\r\n", "\n").replace("\r", "\n").encode("utf-8")


def excluded(relative: str) -> bool:
    name = Path(relative).name.lower()
    return relative.startswith("docs/phase") and "validation" in name


def source_files() -> list[tuple[str, bytes]]:
    files: list[tuple[str, bytes]] = []
    for item in PAYLOAD_ITEMS:
        source = ROOT / item
        if not source.exists():
            raise RuntimeError(f"release payload is missing: {item}")
        candidates = [source] if source.is_file() else [path for path in source.rglob("*") if path.is_file()]
        for path in candidates:
            relative = path.relative_to(ROOT).as_posix()
            if excluded(relative) or "__pycache__" in path.parts or path.suffix.lower() == ".pyc":
                continue
            files.append((relative, normalized_bytes(path)))
    return sorted(files, key=lambda item: item[0])


def zip_info(name: str) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(name, FIXED_ZIP_TIME)
    info.compress_type = zipfile.ZIP_DEFLATED
    info.create_system = 3
    info.external_attr = (stat.S_IFREG | 0o644) << 16
    info.flag_bits |= 0x800
    return info


def build(output_root: Path) -> dict[str, object]:
    output_root.mkdir(parents=True, exist_ok=True)
    archive_name = f"ai-video-channel-production-v{VERSION}-windows.zip"
    archive_path = output_root / archive_name
    files = source_files()
    manifest = {
        "schemaVersion": "1.0.0",
        "productId": "ai-video-channel-production",
        "productName": "AI 视频频道生产系统",
        "productVersion": VERSION,
        "fixtureDataIncluded": False,
        "userDataIncluded": False,
        "credentialsIncluded": False,
        "archiveRoot": PACKAGE_ROOT,
        "hashAlgorithm": "SHA-256",
        "files": [
            {"path": relative, "sizeBytes": len(payload), "sha256": hashlib.sha256(payload).hexdigest()}
            for relative, payload in files
        ],
    }
    manifest_bytes = (json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
    entries = files + [("RC-ASSET-MANIFEST.json", manifest_bytes)]
    with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9, strict_timestamps=True) as archive:
        for relative, payload in sorted(entries, key=lambda item: item[0]):
            archive.writestr(zip_info(f"{PACKAGE_ROOT}/{relative}"), payload)
    archive_hash = hashlib.sha256(archive_path.read_bytes()).hexdigest()
    checksums = output_root / "SHA256SUMS.txt"
    checksums.write_text(f"{archive_hash}  {archive_name}\n", encoding="ascii", newline="\n")
    result = {
        "productVersion": VERSION,
        "archivePath": str(archive_path),
        "archiveSha256": archive_hash,
        "archiveSizeBytes": archive_path.stat().st_size,
        "fileCount": len(entries),
        "assetManifestSha256": hashlib.sha256(manifest_bytes).hexdigest(),
        "checksumsPath": str(checksums),
        "reproducibleZip": True,
    }
    (output_root / "release-candidate-build.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n"
    )
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a deterministic local Stage8 release candidate ZIP.")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(build(args.output.resolve()), ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
