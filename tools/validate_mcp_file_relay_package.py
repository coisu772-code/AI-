from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import tempfile
import zipfile
from pathlib import Path, PurePosixPath


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def extract_safe(archive_path: Path, destination: Path) -> None:
    with zipfile.ZipFile(archive_path) as archive:
        for info in archive.infolist():
            normalized = info.filename.replace("\\", "/")
            member = PurePosixPath(normalized)
            if member.is_absolute() or ".." in member.parts:
                raise RuntimeError(f"unsafe archive member: {archive_path.name}:{info.filename}")
            target = destination.joinpath(*member.parts)
            if info.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(info) as source, target.open("wb") as output:
                shutil.copyfileobj(source, output)


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate packaged MCP with WinPS no-BOM JSONL file relay")
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--asset-root", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    manifest = json.loads(args.manifest.resolve(strict=True).read_text(encoding="utf-8"))
    assets = {item["assetId"]: item for item in manifest["assets"]}
    asset_root = args.asset_root.resolve(strict=True)
    selected = {asset_id: asset_root / assets[asset_id]["fileName"] for asset_id in ("core", "python-runtime")}
    for asset_id, path in selected.items():
        record = assets[asset_id]
        if path.stat().st_size != record["sizeBytes"] or sha256(path) != record["sha256"]:
            raise RuntimeError(f"locked {asset_id} asset mismatch")
    powershell = shutil.which("powershell")
    if not powershell:
        raise RuntimeError("Windows PowerShell is unavailable")
    with tempfile.TemporaryDirectory(prefix="aivcp-packaged-mcp-file-relay-") as temporary_name:
        temporary = Path(temporary_name)
        extract_safe(selected["core"], temporary)
        extract_safe(selected["python-runtime"], temporary)
        python_executable = temporary / assets["python-runtime"]["archiveRoot"] / "python.exe"
        server_script = temporary / assets["core"]["archiveRoot"] / "plugins/ai-video-channel-production/mcp/server.py"
        command = [
            powershell,
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(root / "tools/Test-McpFileRelay.ps1"),
            "-PythonExecutable",
            str(python_executable),
            "-ServerScript",
            str(server_script),
            "-AsJson",
        ]
        completed = subprocess.run(command, check=True, capture_output=True, text=True, encoding="utf-8")
        if completed.stderr.strip():
            raise RuntimeError(f"packaged MCP validation wrote stderr: {completed.stderr}")
        powershell_report = json.loads(completed.stdout.lstrip("\ufeff"))
    if powershell_report.get("status") != "PASS":
        raise RuntimeError("packaged MCP file-relay validation failed")
    transport = powershell_report.get("transport", {})
    if (
        transport.get("mode") != "NO_BOM_JSONL_FILE_PYTHON_RELAY"
        or any(transport.get("requestPreambleBytes", [-1]))
        or transport.get("powershellInputRedirection")
        or transport.get("powershellInputObjectAccess")
    ):
        raise RuntimeError("packaged MCP did not use the no-BOM JSONL file relay")
    if powershell_report.get("fileRelay", {}).get("exitCode") != 0:
        raise RuntimeError("packaged MCP file relay did not exit successfully")
    if not powershell_report.get("powershell", {}).get("desktop51"):
        raise RuntimeError("packaged MCP validation did not run under Windows PowerShell 5.1")
    root_cause = powershell_report.get("controlledRootCauseEvidence", {})
    if root_cause.get("rawStdinProbeHex") != "efbbbf580a" or root_cause.get("fileRelay", {}).get("exitCode") != 0:
        raise RuntimeError("attempt-7 root-cause evidence was not preserved")
    report = {
        "schemaVersion": "1.0.0",
        "status": "PASS",
        "assets": {
            asset_id: {"fileName": path.name, "sizeBytes": path.stat().st_size, "sha256": sha256(path)}
            for asset_id, path in selected.items()
        },
        "powershellIntegration": powershell_report,
        "sandboxAttempt7": "FAIL_FIXED_LOCALLY_WAITING_FOR_CONTROLLED_RERUN",
        "externalActionsExecuted": False,
    }
    args.report.resolve().write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
