from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import stat
import subprocess
import tempfile
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
VERSION = "0.10.1-rc.1"
PYTHON_VERSION = "3.12.13"
PYTHON_BUILD = "20260610"
FIXED_TIME = (2026, 8, 6, 0, 0, 0)
TEXT_SUFFIXES = {".cmd", ".json", ".md", ".ps1", ".py", ".txt", ".yaml", ".yml"}
EXACT_BYTE_TEXT_PATHS = {"contracts/youtube-constraints/catalog-2026.08.04.1.json"}
RUNTIME_LICENSE_NAME_MARKERS = ("license", "copying", "notice", "copyright", "patent", "authors")
CORE_ITEMS = (".agents", "plugins", "contracts", "installer", "release-manifests", "docs", "README.md", "CHANGELOG.md", "LICENSE.md")
BOOTSTRAP_FILES = (
    "installer/Common.ps1",
    "installer/CodexCli.ps1",
    "installer/Install-AIVideoChannelProduction.ps1",
    "installer/install.cmd",
)
WORKSHOP_VERSION = "2.3.1-rc.1"
WORKSHOP_NAME = "Z-Manga-Workshop-2.3.1-rc.1-for-AIVCP-0.10.1-rc.1-windows-x64-portable.zip"
WORKSHOP_SHA = "6d7a5100821c590a99fc9e96d742503282da2526f5582f7585437abf7a0b109f"
WORKSHOP_SIZE = 94959814
WORKSHOP_ROOT = "Z-Manga-Workshop-2.3.1-rc.1-for-AIVCP-0.10.1-rc.1-windows-x64-portable"
WORKSHOP_SOURCE_COMMIT = "01ef170a797da4a9b7210135babd58d6a0ab3277"
PUBLISHER_VERSION = "0.8.0-rc.2"
PUBLISHER_NAME = "youtube-publisher-center-v0.8.0-rc.2-windows-amd64.zip"
PUBLISHER_SHA = "8d2644c11310fd5ee31f6e39250f75a000ccf038cd8c35a9eed8f0f23388c48d"
PUBLISHER_SIZE = 32585503
PUBLISHER_ROOT = "youtube-publisher-center-v0.8.0-rc.2-windows-amd64"
PUBLISHER_SOURCE_COMMIT = "e6350fd290e2e75782334d712ba01ad0411a1efd"
PUBLISHER_COMPONENT_MANIFEST_NAME = "publisher-component-reuse-attestation-v0.8.0-rc.2.json"
PUBLISHER_COMPONENT_MANIFEST_SHA = "fac82b06df0516fc137bc56620a3d1aedf7bc7d260cd442278403f3e7e644816"
PUBLISHER_CONSTRAINTS_SHA = "a57cf04014db7512b420771fe9f412e47a3bd69048b0d34fc9c4765085ad5e13"
KOKORO_VARIANTS = ("cpu", "nvidia", "nvidia-blackwell")
KOKORO_REUSE_VERSION = "0.10.0-rc.1"
KOKORO_REUSE_MANIFEST = f"unified-release-v{KOKORO_REUSE_VERSION}.json"
KOKORO_REUSE_MANIFEST_SHA = "a145f756030e4b8c630031906352d42b3ab5212aba353708d1a045730bd2af5d"
YT_DLP_VERSION = "2026.7.4"
DENO_VERSION = "2.9.4"
DENO_ARCHIVE_NAME = "deno-x86_64-pc-windows-msvc.zip"
DENO_ARCHIVE_URL = f"https://github.com/denoland/deno/releases/download/v{DENO_VERSION}/{DENO_ARCHIVE_NAME}"
DENO_ARCHIVE_SIZE = 42599274
DENO_ARCHIVE_SHA = "68ed08b05c56cf887e9aa509947dc3f468f7e12f47a13e5c1abd51d46d1453ef"
DENO_EXE_SIZE = 97175328
DENO_EXE_SHA = "4a2757fe99afc2c62c46500c8221cfa0189ac4bfb7064141875ad9c0f04b60ef"
DENO_LICENSE_SHA = "f62497fffecc0852960c8d3e6934b9db86d16396e9b604072e923892cae3a588"
EXPECTED_RUNTIME_PACKAGE_NAMES = {
    "attrs", "brotli", "certifi", "charset-normalizer", "idna", "jsonschema",
    "jsonschema-specifications", "lxml", "mutagen", "pip", "pycryptodomex", "pypdf",
    "python-docx", "pyyaml", "referencing", "requests", "rpds-py",
    "typing_extensions", "tzdata", "urllib3", "websockets", "yt-dlp", "yt-dlp-ejs",
}
EXPECTED_RUNTIME_LICENSE_ENTRIES = 72


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def normalized(path: Path) -> bytes:
    data = path.read_bytes()
    relative = path.relative_to(ROOT).as_posix() if path.is_relative_to(ROOT) else ""
    if path.suffix.lower() in TEXT_SUFFIXES and relative not in EXACT_BYTE_TEXT_PATHS:
        data = data.decode("utf-8-sig").replace("\r\n", "\n").replace("\r", "\n").encode("utf-8")
    return data


def zip_info(name: str) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(name, FIXED_TIME)
    info.compress_type = zipfile.ZIP_DEFLATED
    info.create_system = 3
    info.external_attr = (stat.S_IFREG | 0o644) << 16
    info.flag_bits |= 0x800
    return info


def deterministic_zip(target: Path, root_name: str, files: list[tuple[str, bytes]]) -> dict[str, object]:
    target.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9, strict_timestamps=True) as archive:
        for relative, payload in sorted(files):
            archive.writestr(zip_info(f"{root_name}/{relative}"), payload)
    return {"fileName": target.name, "sizeBytes": target.stat().st_size, "sha256": sha256(target)}


def excluded(path: Path, relative: str) -> bool:
    return (
        "__pycache__" in path.parts
        or path.suffix.lower() == ".pyc"
        or relative.startswith("docs/phase") and "validation" in path.name.lower()
        or relative == "docs/baseline-inventory-2026-08-03.md"
        or relative.startswith("docs/final-acceptance-approval-checklist-v")
        or relative.startswith("release-manifests/unified-release-v")
    )


def build_core(output: Path) -> dict[str, object]:
    files: list[tuple[str, bytes]] = []
    for item in CORE_ITEMS:
        source = ROOT / item
        candidates = [source] if source.is_file() else [path for path in source.rglob("*") if path.is_file()]
        for path in candidates:
            relative = path.relative_to(ROOT).as_posix()
            if not excluded(path, relative):
                files.append((relative, normalized(path)))
    manifest = {
        "schemaVersion": "2.0.0",
        "productId": "ai-video-channel-production",
        "productVersion": VERSION,
        "credentialsIncluded": False,
        "userDataIncluded": False,
        "executablesIncluded": False,
        "files": [{"path": name, "sizeBytes": len(data), "sha256": hashlib.sha256(data).hexdigest()} for name, data in sorted(files)],
    }
    files.append(("CORE-ASSET-MANIFEST.json", (json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode()))
    target = output / f"ai-video-channel-production-core-v{VERSION}-windows.zip"
    result = deterministic_zip(target, "ai-video-channel-production-core", files)
    return result | {"path": str(target), "fileCount": len(files)}


def build_bootstrap(output: Path) -> dict[str, object]:
    files = [(Path(relative).name, normalized(ROOT / relative)) for relative in BOOTSTRAP_FILES]
    readme = (
        "AI Video Channel Production unified installer\n\n"
        "Online: download only this installer ZIP, extract it, and double-click install.cmd.\n"
        f"The entry retrieves the manifest only from the version-specific v{VERSION} Release URL, then verifies every missing asset.\n"
        f"Offline: keep unified-release-v{VERSION}.json and all four component ZIP files beside install.cmd.\n"
        "No Token, API key, OAuth or upload is performed.\n"
    ).encode("utf-8")
    files.append(("README-INSTALL.txt", readme))
    target = output / f"AI-Video-Channel-Production-Unified-Installer-v{VERSION}.zip"
    result = deterministic_zip(target, f"AI-Video-Channel-Production-Unified-Installer-v{VERSION}", files)
    return result | {"path": str(target), "fileCount": len(files)}


def download_locked_asset(url: str, target: Path, expected_size: int, expected_sha: str) -> Path:
    parsed = urllib.parse.urlsplit(url)
    if url != DENO_ARCHIVE_URL or parsed.scheme != "https" or parsed.hostname != "github.com" or parsed.username or parsed.password or parsed.port or parsed.query or parsed.fragment:
        raise RuntimeError(f"locked dependency URL is not an exact trusted GitHub HTTPS asset: {url}")
    if target.is_file() and target.stat().st_size == expected_size and sha256(target) == expected_sha:
        return target
    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_name(target.name + ".partial")
    partial.unlink(missing_ok=True)
    request = urllib.request.Request(url, headers={"User-Agent": f"AIVCP-release-builder/{VERSION}"})
    try:
        with urllib.request.urlopen(request, timeout=120) as response, partial.open("wb") as output:
            if response.status != 200:
                raise RuntimeError(f"locked dependency download returned HTTP {response.status}: {url}")
            shutil.copyfileobj(response, output, length=1024 * 1024)
        assert_frozen(partial, expected_size, expected_sha)
        partial.replace(target)
    finally:
        partial.unlink(missing_ok=True)
    return target


def install_deno_runtime(runtime: Path, working: Path, deno_archive: Path | None = None) -> dict[str, object]:
    archive = deno_archive or download_locked_asset(
        DENO_ARCHIVE_URL,
        working / DENO_ARCHIVE_NAME,
        DENO_ARCHIVE_SIZE,
        DENO_ARCHIVE_SHA,
    )
    assert_frozen(archive, DENO_ARCHIVE_SIZE, DENO_ARCHIVE_SHA)
    with zipfile.ZipFile(archive) as bundle:
        files = [item for item in bundle.infolist() if not item.is_dir()]
        if len(files) != 1 or files[0].filename != "deno.exe":
            raise RuntimeError(f"locked Deno archive has unexpected entries: {[item.filename for item in files]}")
        payload = bundle.read(files[0])
    if len(payload) != DENO_EXE_SIZE or hashlib.sha256(payload).hexdigest() != DENO_EXE_SHA:
        raise RuntimeError("locked Deno executable size or SHA-256 mismatch")
    tools = runtime / "tools"
    tools.mkdir(parents=True, exist_ok=True)
    deno = tools / "deno.exe"
    deno.write_bytes(payload)
    license_source = ROOT / "installer" / "runtime-tool-licenses" / "deno-LICENSE.md"
    license_payload = normalized(license_source) if license_source.is_file() else b""
    if hashlib.sha256(license_payload).hexdigest() != DENO_LICENSE_SHA:
        raise RuntimeError("locked Deno license text is missing or changed")
    license_target = tools / "licenses" / "deno-LICENSE.md"
    license_target.parent.mkdir(parents=True, exist_ok=True)
    license_target.write_bytes(license_payload)
    version_output = subprocess.check_output([str(deno), "--version"], text=True, encoding="utf-8").splitlines()[0]
    if version_output != f"deno {DENO_VERSION} (stable, release, x86_64-pc-windows-msvc)":
        raise RuntimeError(f"locked Deno executable reported an unexpected version: {version_output}")
    return {
        "toolId": "deno",
        "version": DENO_VERSION,
        "relativePath": "tools/deno.exe",
        "sizeBytes": DENO_EXE_SIZE,
        "sha256": DENO_EXE_SHA,
        "source": {"url": DENO_ARCHIVE_URL, "archiveSha256": DENO_ARCHIVE_SHA},
        "license": {"expression": "MIT", "path": "tools/licenses/deno-LICENSE.md", "sha256": DENO_LICENSE_SHA},
    }


def prepare_runtime(runtime_source: Path, uv: Path, working: Path, deno_archive: Path | None = None) -> tuple[Path, list[dict[str, object]], dict[str, object], list[dict[str, object]]]:
    runtime = working / f"aivcp-python-runtime-{PYTHON_VERSION}"
    shutil.copytree(runtime_source, runtime)
    for pycache in list(runtime.rglob("__pycache__")):
        shutil.rmtree(pycache)
    for pyc in list(runtime.rglob("*.pyc")):
        pyc.unlink()
    subprocess.run(
        [str(uv), "pip", "install", "--python", str(runtime / "python.exe"), "--requirement", str(ROOT / "installer/runtime-requirements.txt"), "--reinstall", "--break-system-packages"],
        check=True,
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1", "PYTHONUTF8": "1"},
    )
    scripts = runtime / "Scripts"
    if scripts.exists():
        shutil.rmtree(scripts)
    for record in runtime.rglob("RECORD"):
        lines = record.read_text(encoding="utf-8").splitlines()
        record.write_text(
            "\n".join(line for line in lines if "Scripts/" not in line.replace("\\", "/")) + "\n",
            encoding="utf-8",
            newline="\n",
        )
    bundled_tools = [install_deno_runtime(runtime, working, deno_archive)]
    inventory_script = (
        "import importlib.metadata as m,json;"
        "print(json.dumps([{'name':d.metadata['Name'],'version':d.version,'licenseExpression':d.metadata.get('License-Expression'),"
        "'license':d.metadata.get('License'),'licenseFiles':d.metadata.get_all('License-File') or [],"
        "'homePage':d.metadata.get('Home-page')} for d in m.distributions()],sort_keys=True))"
    )
    inventory = sorted(
        json.loads(subprocess.check_output([str(runtime / "python.exe"), "-c", inventory_script], text=True, encoding="utf-8")),
        key=lambda item: (str(item.get("name", "")).lower(), str(item.get("version", ""))),
    )
    license_entries = sorted(
        path.relative_to(runtime).as_posix()
        for path in runtime.rglob("*")
        if path.is_file() and any(marker in path.name.lower() for marker in RUNTIME_LICENSE_NAME_MARKERS)
    )
    missing_declared_license = [item["name"] for item in inventory if not (item.get("licenseExpression") or item.get("license"))]
    missing_license_file = [item["name"] for item in inventory if not item.get("licenseFiles")]
    technical_license_inventory = {
        "status": "TECHNICALLY_VALIDATED_LEGAL_APPROVAL_REQUIRED",
        "packageCount": len(inventory),
        "licenseEntryCount": len(license_entries),
        "missingDeclaredLicense": missing_declared_license,
        "missingLicenseFile": missing_license_file,
        "reviewRequired": len(missing_declared_license) + len(missing_license_file),
        "legalAdviceOrSignoff": False,
    }
    package_names = {str(item.get("name", "")).lower() for item in inventory}
    if package_names != EXPECTED_RUNTIME_PACKAGE_NAMES:
        raise RuntimeError(f"Python runtime package set mismatch: {sorted(package_names)}")
    if len(license_entries) != EXPECTED_RUNTIME_LICENSE_ENTRIES or technical_license_inventory["reviewRequired"] != 0:
        raise RuntimeError(f"Python runtime technical license inventory mismatch: {technical_license_inventory}")
    yt_dlp = next(item for item in inventory if str(item.get("name", "")).lower() == "yt-dlp")
    yt_dlp_ejs = next(item for item in inventory if str(item.get("name", "")).lower() == "yt-dlp-ejs")
    if yt_dlp.get("version") != YT_DLP_VERSION:
        raise RuntimeError(f"yt-dlp version mismatch: {yt_dlp.get('version')}")
    runtime_manifest = {
        "schemaVersion": "1.1.0",
        "componentId": "python-runtime",
        "pythonVersion": PYTHON_VERSION,
        "pythonBuild": PYTHON_BUILD,
        "distribution": "python-build-standalone via uv managed runtime",
        "source": "https://github.com/astral-sh/python-build-standalone",
        "licenseFile": "LICENSE.txt",
        "technicalLicenseInventory": technical_license_inventory,
        "packages": inventory,
        "bundledTools": bundled_tools,
        "youtubeCollector": {
            "collectorId": "yt-dlp",
            "version": YT_DLP_VERSION,
            "entryPoint": ["python.exe", "-m", "yt_dlp"],
            "ejsVersion": yt_dlp_ejs.get("version"),
            "javascriptRuntime": {"toolId": "deno", "relativePath": "tools/deno.exe", "version": DENO_VERSION},
            "requiresSystemPath": False,
        },
    }
    (runtime / "RUNTIME-MANIFEST.json").write_text(json.dumps(runtime_manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    return runtime, inventory, technical_license_inventory, bundled_tools


def build_runtime(output: Path, runtime_source: Path, uv: Path, working: Path, deno_archive: Path | None = None) -> dict[str, object]:
    runtime, inventory, technical_license_inventory, bundled_tools = prepare_runtime(runtime_source, uv, working, deno_archive)
    files = []
    for path in runtime.rglob("*"):
        if path.is_file() and "__pycache__" not in path.parts and path.suffix.lower() != ".pyc":
            files.append((path.relative_to(runtime).as_posix(), normalized(path)))
    target = output / f"aivcp-python-runtime-{PYTHON_VERSION}-windows-x64.zip"
    result = deterministic_zip(target, runtime.name, files)
    return result | {"path": str(target), "fileCount": len(files), "packageInventory": inventory, "technicalLicenseInventory": technical_license_inventory, "bundledTools": bundled_tools}


def assert_frozen(path: Path, expected_size: int, expected_sha: str) -> None:
    if not path.is_file() or path.stat().st_size != expected_size or sha256(path) != expected_sha:
        raise RuntimeError(f"frozen upstream asset mismatch: {path.name}")


def publisher_machine_manifest(path: Path) -> dict[str, object]:
    if not path.is_file() or sha256(path) != PUBLISHER_COMPONENT_MANIFEST_SHA:
        raise RuntimeError(f"publisher component manifest mismatch: {path.name}")
    document = json.loads(path.read_text(encoding="utf-8"))
    expected = {
        "sourceCommit": document.get("source", {}).get("commit"),
        "assetName": document.get("release_asset", {}).get("name"),
        "assetSize": document.get("release_asset", {}).get("size_bytes"),
        "assetSha256": document.get("release_asset", {}).get("sha256"),
        "fileEntries": document.get("release_asset", {}).get("file_entries"),
        "reviewRequired": document.get("legal_inventory", {}).get("review_required"),
        "licenseTextFiles": document.get("legal_inventory", {}).get("license_text_files"),
        "constraintsSha256": document.get("external_integration_gate", {}).get("publisher_constraints_sha256"),
    }
    required = {
        "sourceCommit": PUBLISHER_SOURCE_COMMIT,
        "assetName": PUBLISHER_NAME,
        "assetSize": PUBLISHER_SIZE,
        "assetSha256": PUBLISHER_SHA,
        "fileEntries": 112,
        "reviewRequired": 0,
        "licenseTextFiles": 101,
        "constraintsSha256": PUBLISHER_CONSTRAINTS_SHA,
    }
    if expected != required:
        raise RuntimeError(f"publisher component manifest fields mismatch: {expected}")
    return document


def asset_record(asset_id: str, build: dict[str, object], **extra: object) -> dict[str, object]:
    return {"assetId": asset_id, "fileName": build["fileName"], "sizeBytes": build["sizeBytes"], "sha256": build["sha256"], **extra}


def copy_kokoro_packages(output: Path, kokoro_dir: Path) -> tuple[list[dict[str, object]], list[Path]]:
    packages: list[dict[str, object]] = []
    copied: list[Path] = []
    seen_names: set[str] = set()
    for variant in KOKORO_VARIANTS:
        base = f"Z-Manga-Studio-kokoro-runtime-{variant}"
        manifest_source = kokoro_dir / f"{base}.json"
        if not manifest_source.is_file():
            raise RuntimeError(f"Kokoro manifest is missing: {manifest_source.name}")
        document = json.loads(manifest_source.read_text(encoding="utf-8-sig"))
        archive_name = f"{base}.zip"
        if (
            document.get("schemaVersion") != "1.0"
            or document.get("variant") != variant
            or document.get("archiveName") != archive_name
            or not isinstance(document.get("runtimeVersion"), str)
            or not document["runtimeVersion"].strip()
            or not isinstance(document.get("archiveSha256"), str)
            or len(document["archiveSha256"]) != 64
            or not isinstance(document.get("parts"), list)
            or not document["parts"]
        ):
            raise RuntimeError(f"Kokoro manifest fields are invalid: {manifest_source.name}")
        archive_digest = hashlib.sha256()
        part_records: list[dict[str, object]] = []
        for index, part in enumerate(document["parts"], start=1):
            expected_name = f"{archive_name}.{index:03d}"
            if not isinstance(part, dict) or part.get("name") != expected_name:
                raise RuntimeError(f"Kokoro part order or name is invalid: {manifest_source.name}:{expected_name}")
            part_source = kokoro_dir / expected_name
            if not part_source.is_file() or part_source.stat().st_size != part.get("size") or sha256(part_source) != part.get("sha256"):
                raise RuntimeError(f"Kokoro part size or SHA-256 mismatch: {expected_name}")
            if expected_name in seen_names:
                raise RuntimeError(f"Duplicate Kokoro release attachment: {expected_name}")
            seen_names.add(expected_name)
            with part_source.open("rb") as stream:
                for block in iter(lambda: stream.read(1024 * 1024), b""):
                    archive_digest.update(block)
            target = output / expected_name
            shutil.copy2(part_source, target)
            copied.append(target)
            part_records.append({"fileName": expected_name, "sizeBytes": target.stat().st_size, "sha256": sha256(target)})
        if archive_digest.hexdigest() != document["archiveSha256"]:
            raise RuntimeError(f"Kokoro assembled archive SHA-256 mismatch: {archive_name}")
        if manifest_source.name in seen_names:
            raise RuntimeError(f"Duplicate Kokoro release attachment: {manifest_source.name}")
        seen_names.add(manifest_source.name)
        manifest_target = output / manifest_source.name
        shutil.copy2(manifest_source, manifest_target)
        copied.append(manifest_target)
        packages.append({
            "runtimeId": "kokoro-fastapi",
            "runtimeVersion": document["runtimeVersion"],
            "variant": variant,
            "manifest": {"fileName": manifest_target.name, "sizeBytes": manifest_target.stat().st_size, "sha256": sha256(manifest_target)},
            "archive": {"fileName": archive_name, "sha256": document["archiveSha256"]},
            "parts": part_records,
            "license": {
                "expression": "Apache-2.0 AND bundled-third-party-licenses",
                "source": "LICENSE-Kokoro-FastAPI.txt and THIRD_PARTY_NOTICES.txt inside the assembled runtime archive",
                "reviewStatus": "technical-inventory-validated-release-owner-approval-required",
            },
            "source": {"workshopCommit": WORKSHOP_SOURCE_COMMIT, "packager": "scripts/package-kokoro-runtime.ps1"},
        })
    return packages, copied


def reuse_kokoro_packages() -> list[dict[str, object]]:
    source_path = ROOT / "release-manifests" / KOKORO_REUSE_MANIFEST
    if not source_path.is_file() or sha256(source_path) != KOKORO_REUSE_MANIFEST_SHA:
        raise RuntimeError(f"trusted Kokoro source manifest mismatch: {source_path.name}")
    source_manifest = json.loads(source_path.read_text(encoding="utf-8"))
    packages = source_manifest.get("optionalRuntimePackages")
    if not isinstance(packages, list) or {package.get("variant") for package in packages if isinstance(package, dict)} != set(KOKORO_VARIANTS):
        raise RuntimeError("trusted Kokoro source manifest does not contain the three required variants")
    reused: list[dict[str, object]] = []
    for package in packages:
        record = json.loads(json.dumps(package))
        prior_source = record.get("source") if isinstance(record.get("source"), dict) else {}
        record["source"] = {
            **prior_source,
            "repository": "coisu772-code/AI-",
            "releaseTag": f"v{KOKORO_REUSE_VERSION}",
            "releaseManifest": {"fileName": KOKORO_REUSE_MANIFEST, "sha256": KOKORO_REUSE_MANIFEST_SHA},
            "reuseStatus": "PUBLISHED_RUNTIME_REUSED_AFTER_REMOTE_DIGEST_REVALIDATION",
        }
        reused.append(record)
    return reused


def build_all(output: Path, runtime_source: Path, uv: Path, workshop_dir: Path, publisher_dir: Path, deno_archive: Path | None = None) -> dict[str, object]:
    output.mkdir(parents=True, exist_ok=True)
    workshop_source = workshop_dir / WORKSHOP_NAME
    publisher_source = publisher_dir / PUBLISHER_NAME
    publisher_manifest_path = ROOT / "release-manifests" / PUBLISHER_COMPONENT_MANIFEST_NAME
    assert_frozen(workshop_source, WORKSHOP_SIZE, WORKSHOP_SHA)
    assert_frozen(publisher_source, PUBLISHER_SIZE, PUBLISHER_SHA)
    publisher_manifest = publisher_machine_manifest(publisher_manifest_path)
    with tempfile.TemporaryDirectory(prefix="aivcp-runtime-build-") as temp:
        working = Path(temp)
        core = build_core(output)
        bootstrap = build_bootstrap(output)
        runtime = build_runtime(output, runtime_source, uv, working, deno_archive)
    workshop_target = output / WORKSHOP_NAME
    publisher_target = output / PUBLISHER_NAME
    shutil.copy2(workshop_source, workshop_target)
    shutil.copy2(publisher_source, publisher_target)
    kokoro_packages = reuse_kokoro_packages()
    assets = [
        asset_record("unified-installer", bootstrap, version=VERSION, compatibleProductVersions=[VERSION], install=False, archiveRoot=f"AI-Video-Channel-Production-Unified-Installer-v{VERSION}", installSubpath="", license={"expression":"LicenseRef-AI-Video-Channel-Production-1.0","source":"LICENSE.md","reviewStatus":"product-license-applies"}, source={"repository":"https://github.com/coisu772-code/AI-/","commit":"LOCAL_COMMIT_TO_BE_RECORDED"}),
        asset_record("core", core, version=VERSION, compatibleProductVersions=[VERSION], install=True, archiveRoot="ai-video-channel-production-core", installSubpath="", license={"expression":"LicenseRef-AI-Video-Channel-Production-1.0","source":"LICENSE.md","reviewStatus":"product-license-applies"}, source={"repository":"https://github.com/coisu772-code/AI-/","commit":"LOCAL_COMMIT_TO_BE_RECORDED"}),
        asset_record("python-runtime", runtime, version=PYTHON_VERSION, compatibleProductVersions=[VERSION], install=True, archiveRoot=f"aivcp-python-runtime-{PYTHON_VERSION}", installSubpath="runtime/python", license={"expression":"PSF-2.0 AND bundled-third-party-licenses AND MIT","source":f"LICENSE.txt plus {EXPECTED_RUNTIME_LICENSE_ENTRIES} license entries covering {len(EXPECTED_RUNTIME_PACKAGE_NAMES)} packages and the bundled Deno runtime","reviewStatus":"technical-inventory-validated-release-owner-approval-required"}, source={"url":"https://github.com/astral-sh/python-build-standalone","build":PYTHON_BUILD,"technicalLicenseInventory":runtime["technicalLicenseInventory"],"bundledTools":runtime["bundledTools"]}),
        {"assetId":"workshop","fileName":WORKSHOP_NAME,"sizeBytes":WORKSHOP_SIZE,"sha256":WORKSHOP_SHA,"version":WORKSHOP_VERSION,"compatibleProductVersions":[VERSION],"install":True,"archiveRoot":WORKSHOP_ROOT,"installSubpath":"apps/workshop","license":{"expression":"LicenseRef-AIVCP-Workshop AND GPL-3.0-only","source":"licenses/application/LICENSE.md, licenses/ffmpeg/COPYING.GPLv3 and FFMPEG-PROVENANCE.txt inside archive","reviewStatus":"technical-inventory-validated-release-owner-approval-required"},"source":{"commit":WORKSHOP_SOURCE_COMMIT,"acceptanceStatus":"LOCAL_MERGED_ACCEPTANCE_PASS"}},
        {"assetId":"publisher-center","fileName":PUBLISHER_NAME,"sizeBytes":PUBLISHER_SIZE,"sha256":PUBLISHER_SHA,"version":PUBLISHER_VERSION,"compatibleProductVersions":[VERSION],"install":True,"archiveRoot":PUBLISHER_ROOT,"installSubpath":"apps/publisher","license":{"expression":"LicenseRef-AI-Video-Channel-Production-1.0 AND bundled-third-party-licenses","source":"LICENSE.md, THIRD-PARTY-NOTICES.json/.md and 101 third-party license texts inside archive","reviewStatus":"technical-inventory-validated-release-owner-approval-required"},"source":{"commit":PUBLISHER_SOURCE_COMMIT,"acceptanceStatus":"PUBLISHED_COMPONENT_REUSED_AFTER_HASH_REVALIDATION","componentManifest":{"fileName":PUBLISHER_COMPONENT_MANIFEST_NAME,"sha256":PUBLISHER_COMPONENT_MANIFEST_SHA},"constraintsCatalog":{"version":"2026.08.04.1","sha256":PUBLISHER_CONSTRAINTS_SHA},"fileEntries":publisher_manifest["release_asset"]["file_entries"],"licenseReviewRequired":publisher_manifest["legal_inventory"]["review_required"]}},
    ]
    manifest = {
        "schemaVersion":"2.0.0","productId":"ai-video-channel-production","productName":"AI 视频频道生产系统","productVersion":VERSION,
        "releaseStatus":"candidate","hashAlgorithm":"SHA-256","downloadBaseUrl":f"https://github.com/coisu772-code/AI-/releases/download/v{VERSION}",
        "generatedAt":"2026-08-06T00:00:00Z","assets":assets,"optionalRuntimePackages":kokoro_packages,
        "runtime":{"pythonVersion":PYTHON_VERSION,"pythonBuild":PYTHON_BUILD,"youtubeCollectorVersion":YT_DLP_VERSION,"javascriptRuntimeVersion":DENO_VERSION,"requiresPreinstalledPython":False,"requiresPreinstalledUv":False,"requiresPreinstalledYoutubeCollector":False,"requiresPreinstalledJavascriptRuntime":False},
        "logicalComponents":[{"componentId":"ffmpeg-runtime","version":"8.1.1","providedByAsset":"workshop","license":{"expression":"GPL-3.0-only","source":"apps/workshop/licenses/ffmpeg/COPYING.GPLv3 and FFMPEG-PROVENANCE.txt"},"healthCheck":{"command":"apps/workshop/tools/ffmpeg/bin/ffmpeg.exe -version","expected":"ffmpeg version 8.1.1"},"files":[
            {"relativeInstallPath":"apps/workshop/tools/ffmpeg/bin/ffmpeg.exe","sizeBytes":101457920,"sha256":"228d7a8556258de907fdb55f36850078ebc7680b84ec30d84ea02e99bec1d1eb"},
            {"relativeInstallPath":"apps/workshop/tools/ffmpeg/bin/ffprobe.exe","sizeBytes":101251072,"sha256":"0fde260f5abd35c9cafd96f594cc76365a780c1b73a90e35b6a3409ea1db1bf0"}
        ]}],
        "safetyBoundaries":{"credentialsIncluded":False,"userDataIncluded":False,"oauthExecuted":False,"realUploadExecuted":False,"longTermLearningWriteExecuted":False},
        "publicationGates":["replace-local-commit-placeholders","release-license-owner-approval","clean-windows-acceptance","github-release-approval","google-oauth-approval","private-upload-approval","studio-data-approval","long-term-learning-write-approval"]
    }
    manifest_path = output / f"unified-release-v{VERSION}.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    checksum_paths = [output / record["fileName"] for record in assets] + [manifest_path]
    checksums = output / "SHA256SUMS.txt"
    checksums.write_text("".join(f"{sha256(path)}  {path.name}\n" for path in sorted(checksum_paths, key=lambda item: item.name)), encoding="ascii", newline="\n")
    report = {
        "schemaVersion":"1.0.0","status":"BUILD_PASS","productVersion":VERSION,"assets":assets,"optionalRuntimePackages":kokoro_packages,
        "manifest":{"fileName":manifest_path.name,"sizeBytes":manifest_path.stat().st_size,"sha256":sha256(manifest_path)},
        "checksums":{"fileName":checksums.name,"sizeBytes":checksums.stat().st_size,"sha256":sha256(checksums)},
        "runtimePackageCount":len(runtime["packageInventory"]),"runtimeTechnicalLicenseInventory":runtime["technicalLicenseInventory"],
        "publisherMachineManifest":{"fileName":publisher_manifest_path.name,"sha256":sha256(publisher_manifest_path),"sourceCommit":publisher_manifest["source"]["commit"]},
        "upstreamInputsUnmodified":True,"reusedOptionalRuntimeVersion":KOKORO_REUSE_VERSION,"externalActionsExecuted":False,
    }
    report_path = output / "unified-release-build-report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--runtime-source", type=Path, required=True)
    parser.add_argument("--uv", type=Path, required=True)
    parser.add_argument("--workshop-dir", type=Path, required=True)
    parser.add_argument("--publisher-dir", type=Path, required=True)
    parser.add_argument("--deno-archive", type=Path)
    args = parser.parse_args()
    fixed_paths = tuple(path.resolve() for path in (args.output, args.runtime_source, args.uv, args.workshop_dir, args.publisher_dir))
    result = build_all(*fixed_paths, deno_archive=args.deno_archive.resolve() if args.deno_archive else None)
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
