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
    assets_by_id = {asset.get("assetId"): asset for asset in manifest.get("assets", [])}
    publisher = assets_by_id.get("publisher-center", {})
    runtime_asset = assets_by_id.get("python-runtime", {})
    if publisher.get("license", {}).get("reviewStatus") != "technical-inventory-validated-release-owner-approval-required":
        errors.append("publisher technical inventory status or external release-owner gate is missing")
    if runtime_asset.get("license", {}).get("reviewStatus") != "technical-inventory-validated-release-owner-approval-required":
        errors.append("Python runtime technical inventory status or external release-owner gate is missing")
    if "release-license-owner-approval" not in manifest.get("publicationGates", []):
        errors.append("release-owner license approval gate is missing")
    publisher_source = publisher.get("source", {})
    expected_publisher_source = {
        "commit": "e6350fd290e2e75782334d712ba01ad0411a1efd",
        "componentManifestSha256": "9a9de05c3171c515952ae5bbf43606c96670ef5903b1a0e11f8704cab3d16b36",
        "constraintsSha256": "a57cf04014db7512b420771fe9f412e47a3bd69048b0d34fc9c4765085ad5e13",
    }
    if publisher_source.get("commit") != expected_publisher_source["commit"]:
        errors.append("publisher source commit mismatch")
    if publisher_source.get("componentManifest", {}).get("sha256") != expected_publisher_source["componentManifestSha256"]:
        errors.append("publisher component manifest mismatch")
    if publisher_source.get("constraintsCatalog", {}).get("sha256") != expected_publisher_source["constraintsSha256"]:
        errors.append("publisher constraints catalog mismatch")
    publisher_path = asset_root / publisher.get("fileName", "")
    if publisher_path.is_file():
        with zipfile.ZipFile(publisher_path) as archive:
            root = publisher.get("archiveRoot", "") + "/"
            file_names = [info.filename for info in archive.infolist() if not info.is_dir()]
            if len(file_names) != 112:
                errors.append(f"publisher file entry count mismatch: {len(file_names)}")
            for required in ("LICENSE.md", "THIRD-PARTY-NOTICES.json", "THIRD-PARTY-NOTICES.md"):
                if root + required not in file_names:
                    errors.append(f"publisher license evidence missing: {required}")
            license_texts = [name for name in file_names if name.startswith(root + "third-party-licenses/")]
            if len(license_texts) != 101:
                errors.append(f"publisher third-party license count mismatch: {len(license_texts)}")
            notices_name = root + "THIRD-PARTY-NOTICES.json"
            if notices_name in file_names:
                notices = json.loads(archive.read(notices_name))
                if notices.get("reviewRequired") != []:
                    errors.append("publisher technical license inventory still has review-required entries")
    runtime_path = asset_root / runtime_asset.get("fileName", "")
    if runtime_path.is_file():
        with zipfile.ZipFile(runtime_path) as archive:
            runtime_manifest_name = runtime_asset.get("archiveRoot", "") + "/RUNTIME-MANIFEST.json"
            runtime_manifest = json.loads(archive.read(runtime_manifest_name))
            inventory = runtime_manifest.get("technicalLicenseInventory", {})
            if inventory.get("packageCount") != 12 or inventory.get("licenseEntryCount") != 58 or inventory.get("reviewRequired") != 0:
                errors.append(f"Python runtime technical license inventory mismatch: {inventory}")
            if inventory.get("legalAdviceOrSignoff") is not False:
                errors.append("Python runtime inventory must not claim legal advice or signoff")
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
