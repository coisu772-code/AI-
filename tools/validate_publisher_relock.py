from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import tempfile
import zipfile
from pathlib import Path


PUBLISHER_NAME = "youtube-publisher-center-v0.9.0-rc.3-windows-amd64.zip"
PUBLISHER_SIZE = 32691503
PUBLISHER_SHA256 = "0cbc58dd7d2cee6b8e8f4bbba84d3d626bbdf17ba50e10dbf47f20b33b412d37"
PUBLISHER_ROOT = "youtube-publisher-center-v0.9.0-rc.3-windows-amd64"
PUBLISHER_VALIDATOR_SIZE = 17501696
PUBLISHER_VALIDATOR_SHA256 = "6a83a0d03b38070d0004b936c2a82c65720a448848d9e6f93726f707e2233988"
CATALOG_VERSION = "2026.08.04.1"
CATALOG_SHA256 = "28788480458f37ba86584b4c63e0ef998081ac521ecd9fd0b1724c2a6074b99a"
STALE_CATALOG_SHA256 = "a57cf04014db7512b420771fe9f412e47a3bd69048b0d34fc9c4765085ad5e13"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def run_cli(executable: Path, arguments: list[str]) -> tuple[int, dict[str, object]]:
    completed = subprocess.run(
        [str(executable), *arguments],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    try:
        document = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"publisher CLI returned non-JSON output: {completed.stdout!r} {completed.stderr!r}") from exc
    if document.get("network_execution") is not False:
        raise RuntimeError("publisher CLI crossed the offline network boundary")
    return completed.returncode, document


def validate(publisher_zip: Path, stage8_output: Path) -> dict[str, object]:
    publisher_zip = publisher_zip.resolve(strict=True)
    if publisher_zip.name != PUBLISHER_NAME or publisher_zip.stat().st_size != PUBLISHER_SIZE or sha256(publisher_zip) != PUBLISHER_SHA256:
        raise RuntimeError("publisher ZIP is not the final locked candidate")
    stage8_output = stage8_output.resolve(strict=True)
    stage6_root = stage8_output / "publish" if (stage8_output / "publish" / "summary.json").is_file() else stage8_output
    summary = json.loads((stage6_root / "summary.json").read_text(encoding="utf-8"))
    with tempfile.TemporaryDirectory(prefix="aivcp-publisher-relock-") as temporary:
        executable = Path(temporary) / "publish-package-v2.exe"
        entry_name = f"{PUBLISHER_ROOT}/publish-package-v2.exe"
        with zipfile.ZipFile(publisher_zip) as archive:
            info = archive.getinfo(entry_name)
            if info.is_dir() or info.file_size != PUBLISHER_VALIDATOR_SIZE:
                raise RuntimeError("publisher validation CLI entry is invalid")
            executable.write_bytes(archive.read(info))
        if sha256(executable) != PUBLISHER_VALIDATOR_SHA256:
            raise RuntimeError("publisher validation CLI hash is not the locked final binary")

        code, capabilities = run_cli(executable, ["capabilities"])
        result = capabilities.get("result", {})
        if code != 0 or capabilities.get("status") != "OK":
            raise RuntimeError(f"publisher capabilities failed: {capabilities}")
        if result.get("constraints_catalog_version") != CATALOG_VERSION or result.get("constraints_catalog_sha256") != CATALOG_SHA256:
            raise RuntimeError(f"publisher constraints identity mismatch: {result}")
        if result.get("network_execution_default") is not False:
            raise RuntimeError("publisher capabilities did not preserve the offline default")
        if result.get("component_version") != "0.9.0-rc.3" or result.get("formal_publisher_handoff") is not True:
            raise RuntimeError("publisher formal handoff capability is missing")

        exact_results: dict[str, object] = {}
        first_package: Path | None = None
        first_profile: Path | None = None
        for market in ("ja-JP", "zh-CN", "en-US"):
            item = summary["markets"][market]
            package = stage6_root / item["package_path"]
            profile = stage6_root / "upstream-snapshots" / market / "synthetic-channel-profile.json"
            code, response = run_cli(
                executable,
                ["validate", "--package", str(package), "--synthetic-channel-profile", str(profile)],
            )
            validation = response.get("result", {})
            if code != 0 or response.get("status") != "OK" or validation.get("valid") is not True:
                raise RuntimeError(f"{market}: exact catalog package was rejected: {response}")
            if validation.get("network_execution") is not False:
                raise RuntimeError(f"{market}: validation crossed the network boundary")
            exact_results[market] = {
                "status": response["status"],
                "valid": validation["valid"],
                "publishIntentId": validation["publish_intent_id"],
            }
            first_package = first_package or package
            first_profile = first_profile or profile

        assert first_package is not None and first_profile is not None
        stale_package = Path(temporary) / "stale-catalog.ready"
        shutil.copytree(first_package, stale_package)
        stale_manifest_path = stale_package / "manifest.json"
        stale_manifest = json.loads(stale_manifest_path.read_text(encoding="utf-8"))
        if stale_manifest["constraints_catalog"] != {"version": CATALOG_VERSION, "sha256": CATALOG_SHA256}:
            raise RuntimeError("generated package is not bound to the new exact catalog")
        stale_manifest["constraints_catalog"]["sha256"] = STALE_CATALOG_SHA256
        stale_manifest_path.write_text(json.dumps(stale_manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
        stale_code, stale_response = run_cli(
            executable,
            ["validate", "--package", str(stale_package), "--synthetic-channel-profile", str(first_profile)],
        )
        issues = stale_response.get("result", {}).get("issues", [])
        issue_codes = [item.get("code") for item in issues]
        if stale_code == 0 or "CONSTRAINTS_CATALOG_MISMATCH" not in issue_codes:
            raise RuntimeError(f"stale catalog was not rejected by the exact safety contract: {stale_response}")

    return {
        "schemaVersion": "1.0.0",
        "status": "PASS",
        "publisherZip": {"sizeBytes": PUBLISHER_SIZE, "sha256": PUBLISHER_SHA256},
        "publisherValidationCli": {"sizeBytes": PUBLISHER_VALIDATOR_SIZE, "sha256": PUBLISHER_VALIDATOR_SHA256},
        "constraintsCatalog": {"version": CATALOG_VERSION, "sha256": CATALOG_SHA256},
        "exactCatalogPackages": exact_results,
        "staleCatalog": {"sha256": STALE_CATALOG_SHA256, "rejected": True, "failureCode": "CONSTRAINTS_CATALOG_MISMATCH"},
        "networkExecution": False,
        "oauthExecuted": False,
        "youtubeApiCalled": False,
        "uploadExecuted": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate the Stage6 fixture re-lock against the final publisher binary")
    parser.add_argument("--publisher-zip", type=Path, required=True)
    parser.add_argument("--stage8-output", type=Path, required=True)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    report = validate(args.publisher_zip, args.stage8_output)
    rendered = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.report:
        args.report.resolve().write_text(rendered, encoding="utf-8", newline="\n")
    print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
