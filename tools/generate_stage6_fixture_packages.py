from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PLUGIN_ROOT = ROOT / "plugins" / "ai-video-channel-production"
sys.path.insert(0, str(PLUGIN_ROOT / "mcp"))

from aivcp_tools.contracts import canonical_hash  # noqa: E402
from aivcp_tools.publish_package_v2 import assemble_publish_package_v2  # noqa: E402


CATALOG = ROOT / "contracts" / "youtube-constraints" / "catalog-2026.08.04.1.json"
POLICIES = {"ja-JP": "DO_NOT_UPLOAD", "zh-CN": "REQUIRE_REVIEW", "en-US": "AUTO"}
EXPECTED_STATES = {"ja-JP": "PACKAGE_READY", "zh-CN": "WAITING_REVIEW", "en-US": "WAITING_REVIEW"}


def _read(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"JSON root must be an object: {path}")
    return value


def _write(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _prepare_sources(stage5_root: Path, output_root: Path, language: str) -> tuple[Path, Path, dict]:
    market_root = stage5_root / language
    result_manifest_path = next((market_root / "workspace" / "data" / "production" / "results").rglob("manifest.json"))
    result_source = result_manifest_path.parent
    result_manifest = _read(result_manifest_path)
    publishing_manifest_path = next(
        path for path in (market_root / "workspace" / "data" / "channels").rglob("manifest.json")
        if "publishing-asset-package" in path.as_posix()
        and _read(path).get("projectId") == result_manifest["projectId"]
    )
    publishing_source = publishing_manifest_path.parent
    snapshots = output_root / "upstream-snapshots" / language
    result = snapshots / "production-result-v1"
    publishing = snapshots / "publishing-asset-v1"
    shutil.copytree(result_source, result)
    shutil.copytree(publishing_source, publishing)

    policy = POLICIES[language]
    publishing_manifest = _read(publishing / "manifest.json")
    publishing_manifest["uploadPolicy"] = policy
    publishing_manifest["contentHash"] = canonical_hash(publishing_manifest)
    _write(publishing / "manifest.json", publishing_manifest)
    publishing_json = _read(publishing / "publishing.json")
    publishing_json["uploadPolicy"] = policy
    _write(publishing / "publishing.json", publishing_json)

    result_manifest = _read(result / "manifest.json")
    reference = next(item for item in result_manifest["upstream"] if item["targetContractType"] == "publishing-asset-package")
    reference.update(
        {
            "targetId": publishing_manifest["id"],
            "targetVersion": publishing_manifest["version"],
            "targetHash": publishing_manifest["contentHash"],
        }
    )
    reference_path = result / "publishing-assets-reference.json"
    reference_document = _read(reference_path)
    reference_document["publishingAssetPackage"].update(reference)
    _write(reference_path, reference_document)
    file_record = next(item for item in result_manifest["files"] if item["path"] == "publishing-assets-reference.json")
    file_record.update({"sha256": _sha(reference_path), "sizeBytes": reference_path.stat().st_size})
    result_manifest["contentHash"] = canonical_hash(result_manifest)
    _write(result / "manifest.json", result_manifest)

    target = publishing_manifest["targetChannel"]
    channel_profile = {
        "channel_profile_id": publishing_manifest["channelProfileId"],
        "publisher_profile_id": target["publisherProfileId"],
        "channel_serial": target["channelSerial"],
        "expected_channel_id": target["youtubeChannelId"],
        "enabled": True,
        "authorization_status": "AUTHORIZED",
        "default_language": publishing_manifest["targetLanguage"],
        "timezone": {"ja-JP": "Asia/Tokyo", "zh-CN": "Asia/Shanghai", "en-US": "America/New_York"}[language],
        "upload_mode": policy,
    }
    _write(snapshots / "synthetic-channel-profile.json", channel_profile)
    return result, publishing, channel_profile


def generate(stage5_root: Path, output_root: Path) -> dict:
    stage5_root = stage5_root.resolve(strict=True)
    output_root = output_root.resolve()
    if output_root.exists() and any(output_root.iterdir()):
        raise RuntimeError(f"output directory is not empty: {output_root}")
    output_root.mkdir(parents=True, exist_ok=True)
    markets: dict[str, object] = {}
    for language in ("ja-JP", "zh-CN", "en-US"):
        result, publishing, channel = _prepare_sources(stage5_root, output_root, language)
        assembled = assemble_publish_package_v2(
            production_result_root=result,
            publishing_asset_root=publishing,
            inbox_root=output_root / "publish-inbox" / language,
            channel_profile=channel,
            constraints_catalog_path=CATALOG,
            created_at="2026-08-04T06:00:00Z",
            allow_synthetic_fixture=True,
        )
        package_path = Path(assembled["package_path"])
        markets[language] = {
            "synthetic_fixture": True,
            "policy": POLICIES[language],
            "expected_state": EXPECTED_STATES[language],
            "actual_state": assembled["status"],
            "blockers": assembled["blockers"],
            "publish_intent_id": assembled["publish_intent_id"],
            "package_path": package_path.relative_to(output_root).as_posix(),
            "package_hash": assembled["package_hash"],
            "manifest_sha256": _sha(package_path / "manifest.json"),
            "video_sha256": assembled["video_sha256"],
            "thumbnail_sha256": assembled["thumbnail_sha256"],
            "subtitle_sha256": assembled["subtitle_sha256"],
            "network_execution": False,
            "youtube_video_id": None,
            "publication_receipt": None,
        }
    summary = {
        "schema_version": "1.0",
        "generated_for": "stage6-publisher-integration-validation",
        "synthetic_fixture": True,
        "online_data": False,
        "real_channel_data": False,
        "oauth_executed": False,
        "upload_executed": False,
        "remote_mutation_executed": False,
        "youtube_video_ids": [],
        "publication_receipts": [],
        "constraints_catalog": {
            "version": _read(CATALOG)["catalog_version"],
            "sha256": _sha(CATALOG),
        },
        "markets": markets,
    }
    _write(output_root / "summary.json", summary)
    (output_root / "summary.sha256").write_text(_sha(output_root / "summary.json") + "  summary.json\n", encoding="utf-8")
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate three offline synthetic Stage6 publish package v2 fixtures")
    parser.add_argument("--stage5-output", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(generate(args.stage5_output, args.output), ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
