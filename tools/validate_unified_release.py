from __future__ import annotations

import argparse
import hashlib
import json
import re
import zipfile
from pathlib import Path, PurePosixPath

from jsonschema import Draft202012Validator, FormatChecker


ROOT = Path(__file__).resolve().parents[1]
SCHEMA = ROOT / "release-manifests" / "unified-release-manifest.schema.json"
EXPECTED_IDS = {"unified-installer", "core", "python-runtime", "workshop", "publisher-center"}
SENSITIVE_NAME = re.compile(r"(?:client[_-]?secret|access[_-]?token|refresh[_-]?token|credentials?\.json$|cookies?\.txt$|\.env$)", re.I)
SENSITIVE_BYTES = (
    re.compile(rb"-----BEGIN (?:RSA |OPENSSH )?PRIVATE KEY-----"),
    re.compile(rb"\bya29\.[A-Za-z0-9_-]{40,}"),
    re.compile(rb"\bAIza[0-9A-Za-z_-]{30,}"),
    re.compile(rb"\bGOCSPX-[A-Za-z0-9_-]{20,}"),
    re.compile(rb"\bgh[pousr]_[A-Za-z0-9]{30,}\b"),
    re.compile(rb"\bsk-[A-Za-z0-9_-]{24,}\b"),
)
DEV_PATHS = (b"E:\\\\", b"E:/", "E:\\小说漫全自动化生产".encode("utf-8"))


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def safe_zip_entries(archive_path: Path, expected_root: str, core: bool) -> tuple[list[str], dict[str, tuple[int, str]]]:
    errors: list[str] = []
    records: dict[str, tuple[int, str]] = {}
    with zipfile.ZipFile(archive_path) as archive:
        names = archive.namelist()
        if len(names) != len(set(names)):
            errors.append(f"{archive_path.name}: duplicate ZIP entry")
        for info in archive.infolist():
            name = info.filename.replace("\\", "/")
            path = PurePosixPath(name)
            if path.is_absolute() or ".." in path.parts or not name.startswith(expected_root + "/") or "\\" in info.filename:
                errors.append(f"{archive_path.name}: unsafe ZIP entry {info.filename}")
                continue
            mode = (info.external_attr >> 16) & 0xF000
            if mode == 0xA000:
                errors.append(f"{archive_path.name}: symbolic link {name}")
            relative = name[len(expected_root) + 1 :]
            if core and PurePosixPath(relative).suffix.lower() in {".exe", ".dll", ".msi"}:
                errors.append(f"core contains executable: {relative}")
            if SENSITIVE_NAME.search(PurePosixPath(relative).name):
                errors.append(f"sensitive-looking filename: {archive_path.name}:{relative}")
            digest = hashlib.sha256()
            total = 0
            with archive.open(info) as stream:
                for block in iter(lambda: stream.read(1024 * 1024), b""):
                    total += len(block)
                    digest.update(block)
                    text_candidate = PurePosixPath(relative).suffix.lower() in {".cmd", ".json", ".md", ".ps1", ".py", ".txt", ".yaml", ".yml", ".toml"}
                    if text_candidate and any(pattern.search(block) for pattern in SENSITIVE_BYTES):
                        errors.append(f"credential signature: {archive_path.name}:{relative}")
                    if text_candidate and any(marker in block for marker in DEV_PATHS):
                        errors.append(f"development absolute path: {archive_path.name}:{relative}")
            records[relative] = (total, digest.hexdigest())
    return errors, records


def validate(manifest_path: Path, asset_root: Path) -> dict[str, object]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    errors = [f"schema:{'/'.join(map(str, error.absolute_path)) or '<root>'}: {error.message}" for error in Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(manifest)]
    ids = [asset.get("assetId") for asset in manifest.get("assets", [])]
    if set(ids) != EXPECTED_IDS or len(ids) != len(set(ids)):
        errors.append(f"asset IDs must be exactly {sorted(EXPECTED_IDS)}")
    records_by_id: dict[str, dict[str, tuple[int, str]]] = {}
    for asset in manifest.get("assets", []):
        path = asset_root / asset["fileName"]
        if not path.is_file():
            errors.append(f"missing asset: {asset['fileName']}")
            continue
        if path.stat().st_size != asset["sizeBytes"]:
            errors.append(f"size mismatch: {asset['fileName']}")
        if sha256(path) != asset["sha256"]:
            errors.append(f"SHA-256 mismatch: {asset['fileName']}")
        zip_errors, zip_records = safe_zip_entries(path, asset["archiveRoot"], asset["assetId"] == "core")
        errors.extend(zip_errors)
        records_by_id[asset["assetId"]] = zip_records
    publisher = next((asset for asset in manifest.get("assets", []) if asset.get("assetId") == "publisher-center"), {})
    if publisher.get("license", {}).get("reviewStatus") != "manual-third-party-notice-review-required":
        errors.append("publisher third-party notice review must remain an explicit gate")
    if manifest.get("runtime", {}).get("requiresPreinstalledPython") or manifest.get("runtime", {}).get("requiresPreinstalledUv"):
        errors.append("clean installation must not require preinstalled Python or uv")
    workshop_records = records_by_id.get("workshop", {})
    workshop_root = next((asset.get("archiveRoot") for asset in manifest.get("assets", []) if asset.get("assetId") == "workshop"), "")
    del workshop_root
    for logical in manifest.get("logicalComponents", []):
        for file in logical.get("files", []):
            relative = file["relativeInstallPath"].replace("apps/workshop/", "", 1)
            record = workshop_records.get(relative)
            if record != (file["sizeBytes"], file["sha256"]):
                errors.append(f"logical component record mismatch: {file['relativeInstallPath']}")
    return {
        "schemaVersion":"1.0.0","status":"PASS" if not errors else "FAIL","productVersion":manifest.get("productVersion"),
        "manifestPath":str(manifest_path),"manifestSha256":sha256(manifest_path),"assetCount":len(ids),"errors":errors,
        "boundaries":{"credentialsPresent":False if not errors else None,"userDataPresent":False if not errors else None,"coreExecutablesPresent":False if not errors else None,"developmentAbsolutePathsPresent":False if not errors else None,"externalActionsExecuted":False},
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--asset-root", type=Path, required=True)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    result = validate(args.manifest.resolve(), args.asset_root.resolve())
    rendered = json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.report:
        args.report.resolve().write_text(rendered, encoding="utf-8", newline="\n")
    print(rendered, end="")
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
