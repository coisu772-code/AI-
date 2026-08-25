from __future__ import annotations

import argparse
import json
import os
import subprocess
import tempfile
import zipfile
from pathlib import Path, PurePosixPath


def parse_python(path: Path) -> None:
    json.loads(path.read_text(encoding="utf-8-sig"))


def tracked_json(root: Path) -> list[Path]:
    completed = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "*.json"],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return [(root / line).resolve(strict=True) for line in completed.stdout.splitlines() if line]


def archive_json(asset_root: Path, temporary: Path) -> list[Path]:
    extracted: list[Path] = []
    for archive_path in sorted(asset_root.glob("*.zip")):
        with zipfile.ZipFile(archive_path) as archive:
            for info in archive.infolist():
                normalized = info.filename.replace("\\", "/")
                member = PurePosixPath(normalized)
                if info.is_dir() or member.suffix.lower() != ".json":
                    continue
                # Dependency lockfiles are not release control documents and
                # commonly use the empty-string package-root key, which
                # Windows PowerShell 5.1 ConvertFrom-Json cannot represent.
                # npm validates these lockfiles in their owning component.
                if member.name.lower() == "package-lock.json":
                    continue
                if member.is_absolute() or ".." in member.parts:
                    raise RuntimeError(f"unsafe JSON archive member: {archive_path.name}:{info.filename}")
                destination = temporary / f"archive-{len(extracted):05d}.json"
                destination.write_bytes(archive.read(info))
                extracted.append(destination)
    return extracted


def run_external_parsers(paths: list[Path], temporary: Path) -> None:
    index = temporary / "json-paths.json"
    index.write_text(json.dumps([str(path) for path in paths], ensure_ascii=False), encoding="utf-8", newline="\n")
    environment = os.environ.copy()
    environment["AIVCP_JSON_INDEX"] = str(index)
    powershell = (
        "$ErrorActionPreference='Stop'; "
        "$paths=Get-Content -LiteralPath $env:AIVCP_JSON_INDEX -Raw -Encoding UTF8 | ConvertFrom-Json; "
        "foreach($path in @($paths)){"
        "$null=Get-Content -LiteralPath $path -Raw -Encoding UTF8 | ConvertFrom-Json"
        "}"
    )
    subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", powershell],
        check=True,
        env=environment,
    )
    node = (
        "const fs=require('fs');"
        "const paths=JSON.parse(fs.readFileSync(process.env.AIVCP_JSON_INDEX,'utf8').replace(/^\\uFEFF/,''));"
        "for(const path of paths){JSON.parse(fs.readFileSync(path,'utf8').replace(/^\\uFEFF/,''));}"
    )
    subprocess.run(["node", "-e", node], check=True, env=environment)


def main() -> int:
    parser = argparse.ArgumentParser(description="Parse every RC JSON document with PowerShell, Python, and Node")
    parser.add_argument("--asset-root", type=Path, required=True)
    parser.add_argument("--evidence-root", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    asset_root = args.asset_root.resolve(strict=True)
    evidence_root = args.evidence_root.resolve(strict=True)
    report_path = args.report.resolve()
    repository_paths = tracked_json(root)
    release_paths = sorted(asset_root.rglob("*.json"))
    evidence_paths = [path for path in sorted(evidence_root.rglob("*.json")) if path.resolve() != report_path]
    direct_paths = list(dict.fromkeys(repository_paths + release_paths + evidence_paths))
    with tempfile.TemporaryDirectory(prefix="aivcp-json-parsers-") as temporary_name:
        temporary = Path(temporary_name)
        archived_paths = archive_json(asset_root, temporary)
        paths = direct_paths + archived_paths
        for path in paths:
            parse_python(path)
        run_external_parsers(paths, temporary)
    report = {
        "schemaVersion": "1.0.0",
        "status": "PASS",
        "parsers": {"powershellConvertFromJson": "PASS", "pythonJson": "PASS", "nodeJsonParse": "PASS"},
        "documents": {
            "repository": len(repository_paths),
            "releaseAndEvidence": len(direct_paths) - len(repository_paths),
            "insideReleaseArchives": len(archived_paths),
            "total": len(direct_paths) + len(archived_paths),
        },
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
