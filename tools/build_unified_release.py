from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import stat
import subprocess
import tempfile
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
VERSION = "0.8.0-rc.2"
PYTHON_VERSION = "3.12.13"
PYTHON_BUILD = "20260610"
FIXED_TIME = (2026, 8, 4, 0, 0, 0)
TEXT_SUFFIXES = {".cmd", ".json", ".md", ".ps1", ".py", ".txt", ".yaml", ".yml"}
CORE_ITEMS = (".agents", "plugins", "contracts", "installer", "release-manifests", "docs", "README.md", "CHANGELOG.md", "LICENSE.md")
BOOTSTRAP_FILES = (
    "installer/Common.ps1",
    "installer/CodexCli.ps1",
    "installer/Install-AIVideoChannelProduction.ps1",
    "installer/install.cmd",
)
WORKSHOP_NAME = "Z-Manga-Workshop-2.1.0-stage5-for-AIVCP-0.8.0-rc.1-windows-x64-portable.zip"
WORKSHOP_SHA = "7a9cb4562e3c82606436ad76d1620a1fa1d59a652deb9f46be01cccad5085167"
WORKSHOP_SIZE = 82990897
WORKSHOP_ROOT = "Z-Manga-Workshop-2.1.0-stage5-for-AIVCP-0.8.0-rc.1-windows-x64-portable"
PUBLISHER_NAME = "youtube-publisher-center-v0.8.0-rc.2-windows-amd64.zip"
PUBLISHER_SHA = "4f51f1a4ba4808261f24599da86f710330c76132a64793c70f111278440239d3"
PUBLISHER_SIZE = 32435182
PUBLISHER_ROOT = "youtube-publisher-center-v0.8.0-rc.2-windows-amd64"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def normalized(path: Path) -> bytes:
    data = path.read_bytes()
    if path.suffix.lower() in TEXT_SUFFIXES:
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
        or relative == "release-manifests/unified-release-v0.8.0-rc.2.json"
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
        "The entry retrieves the manifest only from the version-specific v0.8.0-rc.2 Release URL, then verifies every missing asset.\n"
        "Offline: keep unified-release-v0.8.0-rc.2.json and all four component ZIP files beside install.cmd.\n"
        "No Token, API key, OAuth or upload is performed.\n"
    ).encode("utf-8")
    files.append(("README-INSTALL.txt", readme))
    target = output / f"AI-Video-Channel-Production-Unified-Installer-v{VERSION}.zip"
    result = deterministic_zip(target, f"AI-Video-Channel-Production-Unified-Installer-v{VERSION}", files)
    return result | {"path": str(target), "fileCount": len(files)}


def prepare_runtime(runtime_source: Path, uv: Path, working: Path) -> tuple[Path, list[dict[str, object]]]:
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
    inventory_script = (
        "import importlib.metadata as m,json;"
        "print(json.dumps([{'name':d.metadata['Name'],'version':d.version,'licenseExpression':d.metadata.get('License-Expression'),"
        "'license':d.metadata.get('License'),'homePage':d.metadata.get('Home-page')} for d in m.distributions()],sort_keys=True))"
    )
    inventory = sorted(
        json.loads(subprocess.check_output([str(runtime / "python.exe"), "-c", inventory_script], text=True, encoding="utf-8")),
        key=lambda item: (str(item.get("name", "")).lower(), str(item.get("version", ""))),
    )
    runtime_manifest = {
        "schemaVersion": "1.0.0",
        "componentId": "python-runtime",
        "pythonVersion": PYTHON_VERSION,
        "pythonBuild": PYTHON_BUILD,
        "distribution": "python-build-standalone via uv managed runtime",
        "source": "https://github.com/astral-sh/python-build-standalone",
        "licenseFile": "LICENSE.txt",
        "packages": inventory,
    }
    (runtime / "RUNTIME-MANIFEST.json").write_text(json.dumps(runtime_manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    return runtime, inventory


def build_runtime(output: Path, runtime_source: Path, uv: Path, working: Path) -> dict[str, object]:
    runtime, inventory = prepare_runtime(runtime_source, uv, working)
    files = []
    for path in runtime.rglob("*"):
        if path.is_file() and "__pycache__" not in path.parts and path.suffix.lower() != ".pyc":
            files.append((path.relative_to(runtime).as_posix(), normalized(path)))
    target = output / f"aivcp-python-runtime-{PYTHON_VERSION}-windows-x64.zip"
    result = deterministic_zip(target, runtime.name, files)
    return result | {"path": str(target), "fileCount": len(files), "packageInventory": inventory}


def assert_frozen(path: Path, expected_size: int, expected_sha: str) -> None:
    if not path.is_file() or path.stat().st_size != expected_size or sha256(path) != expected_sha:
        raise RuntimeError(f"frozen upstream asset mismatch: {path.name}")


def asset_record(asset_id: str, build: dict[str, object], **extra: object) -> dict[str, object]:
    return {"assetId": asset_id, "fileName": build["fileName"], "sizeBytes": build["sizeBytes"], "sha256": build["sha256"], **extra}


def build_all(output: Path, runtime_source: Path, uv: Path, workshop_dir: Path, publisher_dir: Path) -> dict[str, object]:
    output.mkdir(parents=True, exist_ok=True)
    workshop_source = workshop_dir / WORKSHOP_NAME
    publisher_source = publisher_dir / PUBLISHER_NAME
    assert_frozen(workshop_source, WORKSHOP_SIZE, WORKSHOP_SHA)
    assert_frozen(publisher_source, PUBLISHER_SIZE, PUBLISHER_SHA)
    with tempfile.TemporaryDirectory(prefix="aivcp-runtime-build-") as temp:
        working = Path(temp)
        core = build_core(output)
        bootstrap = build_bootstrap(output)
        runtime = build_runtime(output, runtime_source, uv, working)
    workshop_target = output / WORKSHOP_NAME
    publisher_target = output / PUBLISHER_NAME
    shutil.copy2(workshop_source, workshop_target)
    shutil.copy2(publisher_source, publisher_target)
    assets = [
        asset_record("unified-installer", bootstrap, version=VERSION, compatibleProductVersions=[VERSION], install=False, archiveRoot=f"AI-Video-Channel-Production-Unified-Installer-v{VERSION}", installSubpath="", license={"expression":"LicenseRef-AI-Video-Channel-Production-1.0","source":"LICENSE.md","reviewStatus":"product-license-applies"}, source={"repository":"https://github.com/coisu772-code/AI-/","commit":"LOCAL_COMMIT_TO_BE_RECORDED"}),
        asset_record("core", core, version=VERSION, compatibleProductVersions=[VERSION], install=True, archiveRoot="ai-video-channel-production-core", installSubpath="", license={"expression":"LicenseRef-AI-Video-Channel-Production-1.0","source":"LICENSE.md","reviewStatus":"product-license-applies"}, source={"repository":"https://github.com/coisu772-code/AI-/","commit":"LOCAL_COMMIT_TO_BE_RECORDED"}),
        asset_record("python-runtime", runtime, version=PYTHON_VERSION, compatibleProductVersions=[VERSION], install=True, archiveRoot=f"aivcp-python-runtime-{PYTHON_VERSION}", installSubpath="runtime/python", license={"expression":"PSF-2.0 AND bundled-third-party-licenses","source":"LICENSE.txt and package dist-info license files","reviewStatus":"inventory-generated-review-required"}, source={"url":"https://github.com/astral-sh/python-build-standalone","build":PYTHON_BUILD}),
        {"assetId":"workshop","fileName":WORKSHOP_NAME,"sizeBytes":WORKSHOP_SIZE,"sha256":WORKSHOP_SHA,"version":"2.1.0-stage5","compatibleProductVersions":["0.8.0-rc.1",VERSION],"install":True,"archiveRoot":WORKSHOP_ROOT,"installSubpath":"apps/workshop","license":{"expression":"LicenseRef-AIVCP-Workshop AND GPL-3.0-only","source":"licenses/ application license, FFmpeg GPL text and Gyan README inside archive","reviewStatus":"upstream-machine-validated"},"source":{"commit":"224e11ecdaec2eae2833ac9f63893f9d72ac5c84","upstreamReport":"validation-summary-v2.1.0-stage5.json"}},
        {"assetId":"publisher-center","fileName":PUBLISHER_NAME,"sizeBytes":PUBLISHER_SIZE,"sha256":PUBLISHER_SHA,"version":VERSION,"compatibleProductVersions":[VERSION],"install":True,"archiveRoot":PUBLISHER_ROOT,"installSubpath":"apps/publisher","license":{"expression":"LicenseRef-AI-Video-Channel-Production-1.0","source":"product LICENSE.md (archive has no standalone LICENSE or THIRD-PARTY-NOTICES)","reviewStatus":"manual-third-party-notice-review-required"},"source":{"commit":"62453a0c06cf7a678beff22f650c8277e87e3613","acceptanceStatus":"CANDIDATE_READY_FOR_CONTROLLED_REAL_ACCEPTANCE"}},
    ]
    manifest = {
        "schemaVersion":"2.0.0","productId":"ai-video-channel-production","productName":"AI 视频频道生产系统","productVersion":VERSION,
        "releaseStatus":"candidate","hashAlgorithm":"SHA-256","downloadBaseUrl":f"https://github.com/coisu772-code/AI-/releases/download/v{VERSION}",
        "generatedAt":"2026-08-04T00:00:00Z","assets":assets,
        "runtime":{"pythonVersion":PYTHON_VERSION,"pythonBuild":PYTHON_BUILD,"requiresPreinstalledPython":False,"requiresPreinstalledUv":False},
        "logicalComponents":[{"componentId":"ffmpeg-runtime","version":"8.1.2","providedByAsset":"workshop","license":{"expression":"GPL-3.0-only","source":"apps/workshop/licenses/ffmpeg/COPYING.GPLv3 and GYAN-BUILD-README.txt"},"healthCheck":{"command":"apps/workshop/tools/ffmpeg/bin/ffmpeg.exe -version","expected":"ffmpeg version 8.1.2"},"files":[
            {"relativeInstallPath":"apps/workshop/tools/ffmpeg/bin/ffmpeg.exe","sizeBytes":101897728,"sha256":"1326dde4c84ff1f96fe6b8916c5bed29e163e9b5dccf995f6f3db069d143ec5e"},
            {"relativeInstallPath":"apps/workshop/tools/ffmpeg/bin/ffprobe.exe","sizeBytes":101692928,"sha256":"b49ccc7c6547b141ad5a2f6ec69cc04323d7133d7704d70b331b904c63eecb07"}
        ]}],
        "safetyBoundaries":{"credentialsIncluded":False,"userDataIncluded":False,"oauthExecuted":False,"realUploadExecuted":False,"longTermLearningWriteExecuted":False},
        "publicationGates":["replace-local-commit-placeholders","publisher-third-party-notice-review","clean-windows-acceptance","github-release-approval","google-oauth-approval","private-upload-approval","studio-data-approval","long-term-learning-write-approval"]
    }
    manifest_path = output / f"unified-release-v{VERSION}.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    checksum_paths = [output / record["fileName"] for record in assets] + [manifest_path]
    checksums = output / "SHA256SUMS.txt"
    checksums.write_text("".join(f"{sha256(path)}  {path.name}\n" for path in sorted(checksum_paths, key=lambda item: item.name)), encoding="ascii", newline="\n")
    report = {
        "schemaVersion":"1.0.0","status":"BUILD_PASS","productVersion":VERSION,"assets":assets,
        "manifest":{"path":str(manifest_path),"sizeBytes":manifest_path.stat().st_size,"sha256":sha256(manifest_path)},
        "checksums":{"path":str(checksums),"sizeBytes":checksums.stat().st_size,"sha256":sha256(checksums)},
        "runtimePackageCount":len(runtime["packageInventory"]),"upstreamInputsUnmodified":True,"externalActionsExecuted":False,
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
    args = parser.parse_args()
    result = build_all(*(path.resolve() for path in (args.output, args.runtime_source, args.uv, args.workshop_dir, args.publisher_dir)))
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
