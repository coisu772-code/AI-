from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import zipfile
from pathlib import PurePosixPath, Path


ROOT_NAME = "ai-video-channel-production"
FORBIDDEN_SUFFIXES = {".db", ".sqlite", ".sqlite3", ".exe", ".msi", ".mp3", ".wav", ".mp4", ".mov", ".mkv"}
SENSITIVE_NAME = re.compile(r"(?:secret|credential|cookie|client_secret|access_token|refresh_token)", re.I)
SENSITIVE_TEXT = (
    re.compile(rb"-----BEGIN (?:RSA |OPENSSH )?PRIVATE KEY-----"),
    re.compile(rb"\bya29\.[A-Za-z0-9_-]{40,}"),
    re.compile(rb"\bAIza[0-9A-Za-z_-]{30,}"),
    re.compile(rb"\bGOCSPX-[A-Za-z0-9_-]{20,}"),
    re.compile(rb"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(rb"\bgh[pousr]_[A-Za-z0-9]{30,}\b"),
    re.compile(rb"\bgithub_pat_[A-Za-z0-9_]{50,}\b"),
    re.compile(rb"\bsk-[A-Za-z0-9_-]{20,}\b"),
)


def scan(archive_path: Path) -> dict[str, object]:
    errors: list[str] = []
    with zipfile.ZipFile(archive_path) as archive:
        names = archive.namelist()
        if len(names) != len(set(names)):
            errors.append("duplicate ZIP entry")
        expected_prefix = ROOT_NAME + "/"
        for name in names:
            normalized = name.replace("\\", "/")
            path = PurePosixPath(normalized)
            if not normalized.startswith(expected_prefix) or path.is_absolute() or ".." in path.parts or "\\" in name:
                errors.append(f"unsafe ZIP path: {name}")
            relative = normalized[len(expected_prefix) :]
            suffix = PurePosixPath(relative).suffix.lower()
            if suffix in FORBIDDEN_SUFFIXES:
                errors.append(f"forbidden release file type: {relative}")
            if SENSITIVE_NAME.search(PurePosixPath(relative).name):
                errors.append(f"sensitive-looking filename: {relative}")
            payload = archive.read(name)
            if any(pattern.search(payload) for pattern in SENSITIVE_TEXT):
                errors.append(f"sensitive material signature: {relative}")
        manifest_name = f"{ROOT_NAME}/RC-ASSET-MANIFEST.json"
        if manifest_name not in names:
            errors.append("RC-ASSET-MANIFEST.json is missing")
            manifest = {}
        else:
            manifest = json.loads(archive.read(manifest_name).decode("utf-8"))
            if manifest.get("productName") != "AI 视频频道生产系统" or manifest.get("productVersion") != "0.8.0-rc.1":
                errors.append("asset manifest product identity mismatch")
            records = manifest.get("files") if isinstance(manifest, dict) else None
            if not isinstance(records, list):
                errors.append("asset manifest file list is invalid")
            else:
                expected = {record.get("path"): record for record in records if isinstance(record, dict)}
                actual_names = {name[len(expected_prefix) :] for name in names if name != manifest_name}
                if set(expected) != actual_names:
                    errors.append("asset manifest path set mismatch")
                for relative, record in expected.items():
                    payload = archive.read(expected_prefix + relative)
                    if len(payload) != record.get("sizeBytes") or hashlib.sha256(payload).hexdigest() != record.get("sha256"):
                        errors.append(f"asset manifest hash mismatch: {relative}")
    return {
        "status": "PASS" if not errors else "FAIL",
        "archivePath": str(archive_path),
        "archiveSha256": hashlib.sha256(archive_path.read_bytes()).hexdigest(),
        "entryCount": len(names),
        "errors": errors,
        "boundaries": {
            "credentialsPresent": False if not errors else None,
            "userDataPresent": False if not errors else None,
            "executablesPresent": False if not errors else None,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate Stage8 RC ZIP structure, hashes, and safety boundaries.")
    parser.add_argument("--archive", type=Path, required=True)
    args = parser.parse_args()
    result = scan(args.archive.resolve())
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
