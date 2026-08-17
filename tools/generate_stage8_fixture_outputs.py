from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
PLUGIN_ROOT = ROOT / "plugins" / "ai-video-channel-production"
sys.path.insert(0, str(PLUGIN_ROOT / "mcp"))
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "tools"))

from aivcp_tools.contracts import canonical_hash  # noqa: E402
from aivcp_tools.data_center import DataCenter  # noqa: E402
from aivcp_tools.errors import ToolError  # noqa: E402
from aivcp_tools.publish_package_v2 import assemble_publish_package_v2  # noqa: E402
from aivcp_tools.service import LocalToolService, ServiceConfig  # noqa: E402
from generate_stage5_fixture_outputs import generate as generate_stage5  # noqa: E402
from generate_stage6_fixture_packages import CATALOG, generate as generate_stage6  # noqa: E402
from generate_stage7_fixture_outputs import collect_args, owner_payload, public_payload, system_payload  # noqa: E402
from stage4_support import MARKETS, StaticPublisherProvider  # noqa: E402
from validate_stage5_outputs import validate as validate_stage5  # noqa: E402
from validate_stage6_outputs import validate as validate_stage6  # noqa: E402


LANGUAGES = ("ja-JP", "zh-CN", "en-US")


def read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"expected JSON object: {path}")
    return value


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def contract(root: Path, contract_type: str, project_id: str | None = None) -> tuple[Path, dict[str, Any]]:
    for path in root.rglob("manifest.json"):
        try:
            document = read(path)
        except (OSError, json.JSONDecodeError):
            continue
        if document.get("contractType") == contract_type and (project_id is None or document.get("projectId") in {None, project_id}):
            return path, document
    raise RuntimeError(f"missing {contract_type} under {root}")


def has_ref(document: dict[str, Any], target_type: str, target_hash: str) -> bool:
    return any(
        isinstance(item, dict) and item.get("targetContractType") == target_type and item.get("targetHash") == target_hash
        for item in document.get("upstream", [])
    )


def rel(path: Path, root: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def generate(output_root: Path) -> dict[str, Any]:
    output_root = output_root.resolve()
    if output_root.exists() and any(output_root.iterdir()):
        raise RuntimeError(f"output directory is not empty: {output_root}")
    output_root.mkdir(parents=True, exist_ok=True)
    stage5_root = output_root / "production"
    stage6_root = output_root / "publish"
    generate_stage5(stage5_root)
    stage5_errors = validate_stage5(stage5_root)
    if stage5_errors:
        raise RuntimeError("stage5 validation failed: " + "; ".join(stage5_errors))
    generate_stage6(stage5_root, stage6_root)
    stage6_validation = validate_stage6(stage6_root)
    data_root = output_root / "a"
    center = DataCenter(data_root, plugin_root=PLUGIN_ROOT)
    stage5_summary = read(stage5_root / "summary.json")
    stage6_summary = read(stage6_root / "summary.json")
    markets: dict[str, Any] = {}

    for index, language in enumerate(LANGUAGES, start=1):
        key = MARKETS[language]["key"]
        workspace = stage5_root / language / "workspace"
        workspace_data = workspace / "data"
        original_result_path = stage5_root / stage5_summary["markets"][language]["resultPath"]
        result_path = stage6_root / "upstream-snapshots" / language / "production-result-v1"
        result_manifest = read(result_path / "manifest.json")
        project_id = result_manifest["projectId"]
        source_path, source = contract(workspace_data, "source-package")
        topic_path, topic = contract(workspace_data, "topic-package", project_id)
        manuscript_path, manuscript = contract(workspace_data, "manuscript-package", project_id)
        publishing_snapshot = stage6_root / "upstream-snapshots" / language / "publishing-asset-v1"
        publishing_path = publishing_snapshot / "manifest.json"
        publishing = read(publishing_path)
        production_package_path = stage5_root / stage5_summary["markets"][language]["productionPackagePath"]
        production_package = read(production_package_path / "manifest.json")
        publish_package_path = stage6_root / stage6_summary["markets"][language]["package_path"]
        publish_manifest = read(publish_package_path / "manifest.json")

        documents = (source, topic, manuscript, publishing, result_manifest)
        if any(canonical_hash(document) != document.get("contentHash") for document in documents):
            raise RuntimeError(f"{language}: canonical content hash chain is invalid")
        chain_ok = (
            has_ref(topic, "source-package", source["contentHash"])
            and has_ref(manuscript, "topic-package", topic["contentHash"])
            and has_ref(publishing, "manuscript-package", manuscript["contentHash"])
            and has_ref(result_manifest, "publishing-asset-package", publishing["contentHash"])
            and result_manifest["productionPackageHash"] == production_package["packageHash"]
            and stage6_summary["markets"][language]["package_hash"] == publish_manifest["content_hash"]
        )
        if not chain_ok:
            raise RuntimeError(f"{language}: cross-center reference chain is invalid")

        voice_catalog = workspace / "voice-catalog.json"
        restarted_service = LocalToolService(
            ServiceConfig(data_root=workspace_data, plugin_root=PLUGIN_ROOT, voice_catalog_path=voice_catalog),
            publisher_provider=StaticPublisherProvider(language, key),
        )
        production_task_id = f"task-stage5-{key}"
        task_before = restarted_service.call("production_task_get", {"productionTaskId": production_task_id})["task"]
        task_binding = restarted_service.call(
            "channel_bind_task",
            {"taskId": f"task-stage4-{key}", "channelProfileId": publishing["channelProfileId"]},
        )
        result_count_before = len(list((workspace_data / "production" / "results").glob("*")))
        rerun = restarted_service.call(
            "production_task_run",
            {
                "taskId": f"task-stage4-{key}",
                "channelProfileId": publishing["channelProfileId"],
                "bindingProof": task_binding["bindingProof"],
                "productionTaskId": production_task_id,
            },
        )["task"]
        result_count_after = len(list((workspace_data / "production" / "results").glob("*")))
        production_idempotent = (
            task_before["state"] == rerun["state"] == "VIDEO_READY"
            and task_before["resultPackagePath"] == rerun["resultPackagePath"]
            and Path(task_before["resultPackagePath"]).resolve() == original_result_path.resolve()
            and result_count_before == result_count_after
        )

        snapshots = stage6_root / "upstream-snapshots" / language
        channel_profile = read(snapshots / "synthetic-channel-profile.json")
        publish_again = assemble_publish_package_v2(
            production_result_root=snapshots / "production-result-v1",
            publishing_asset_root=snapshots / "publishing-asset-v1",
            inbox_root=stage6_root / "publish-inbox" / language,
            channel_profile=channel_profile,
            constraints_catalog_path=CATALOG,
            created_at="2026-08-04T06:00:00Z",
            allow_synthetic_fixture=True,
        )
        publish_idempotent = (
            publish_again["package_hash"] == stage6_summary["markets"][language]["package_hash"]
            and len(list((stage6_root / "publish-inbox" / language).glob("*.ready"))) == 1
            and publish_again.get("youtube_video_id") is None
        )

        bindings = [
            {"role": "topic", "contractType": "topic-package", "id": topic["id"], "version": topic["version"], "schemaVersion": topic["schemaVersion"], "sha256": topic["contentHash"]},
            {"role": "manuscript", "contractType": "manuscript-package", "id": manuscript["id"], "version": manuscript["version"], "schemaVersion": manuscript["schemaVersion"], "sha256": manuscript["contentHash"]},
            {"role": "publishing", "contractType": "publishing-asset-package", "id": publishing["id"], "version": publishing["version"], "schemaVersion": publishing["schemaVersion"], "sha256": publishing["contentHash"]},
            {"role": "production", "contractType": "production-result-package", "id": result_manifest["id"], "version": result_manifest["version"], "schemaVersion": result_manifest["schemaVersion"], "sha256": result_manifest["contentHash"]},
            {"role": "publishIntent", "contractType": "publish-intent", "id": publish_manifest["publish_intent_id"], "version": publish_manifest["package_version"], "schemaVersion": publish_manifest["schema_version"], "sha256": publish_manifest["content_hash"]},
        ]
        profile = publishing["channelProfileId"]
        registration_args = {
            "channelProfileId": profile,
            "syntheticFixture": True,
            "syntheticRegistration": {
                "syntheticVideoId": f"synthetic-{language}-stage8",
                "receiptId": f"synthetic-stage8-receipt-{key}",
                "channelProfileId": profile,
                "projectId": project_id,
                "publishedAt": "2026-06-01T00:00:00Z",
                "upstreamBindings": bindings,
            },
            "videoMetadata": {"language": language, "contentForm": "long-form-novel-manga", "durationBand": "fixture", "topicLane": "recorded-stage8", "publishTimeBand": "fixture"},
        }
        registered = center.register_video(registration_args)
        registered_again = center.register_video(registration_args)
        video_id = registered["videoId"]
        restarted_center = DataCenter(data_root, plugin_root=PLUGIN_ROOT)
        sources = {
            "public": public_payload(language, profile, video_id, 700 * index),
            "owner": owner_payload(language, profile, video_id, 680 * index),
            "system": system_payload(language, profile, video_id),
        }
        sources["system"]["binding"]["projectId"] = project_id
        collection_args = collect_args(profile, video_id, "T+28D", sources, completeness="complete")
        snapshot = restarted_center.collect(collection_args)
        snapshot_again = restarted_center.collect(collection_args)
        report = restarted_center.generate_report({"channelProfileId": profile, "videoId": video_id, "checkpoint": "T+28D", "syntheticFixture": True})
        report_again = restarted_center.generate_report({"channelProfileId": profile, "videoId": video_id, "checkpoint": "T+28D", "syntheticFixture": True})
        recommendations = restarted_center.list_recommendations({"channelProfileId": profile, "syntheticFixture": True})
        recommendation_id = recommendations["recommendations"][0]["recommendationId"]
        learning_gate = None
        try:
            restarted_center.learning_decision(
                {"channelProfileId": profile, "recommendationId": recommendation_id, "decision": "channel_default", "syntheticFixture": True, "executionMode": "auto"}
            )
        except ToolError as exc:
            learning_gate = exc.code
        if learning_gate != "LONG_TERM_LEARNING_APPROVAL_REQUIRED":
            raise RuntimeError(f"{language}: long-term learning gate was bypassed")

        markets[language] = {
            "status": "GO_RECORDED_SYNTHETIC",
            "syntheticFixture": True,
            "channelProfileId": profile,
            "projectId": project_id,
            "chain": {
                "source": {"path": rel(source_path, output_root), "sha256": source["contentHash"]},
                "topic": {"path": rel(topic_path, output_root), "sha256": topic["contentHash"]},
                "manuscript": {"path": rel(manuscript_path, output_root), "sha256": manuscript["contentHash"]},
                "publishing": {"path": rel(publishing_path, output_root), "sha256": publishing["contentHash"]},
                "productionPackage": {"path": rel(production_package_path, output_root), "sha256": production_package["packageHash"]},
                "productionResult": {"path": rel(result_path, output_root), "sha256": result_manifest["contentHash"], "videoSha256": result_manifest["finalVideo"]["sha256"]},
                "publishPackage": {"path": rel(publish_package_path, output_root), "sha256": publish_manifest["content_hash"], "localStatus": stage6_summary["markets"][language]["actual_state"]},
                "analyticsRegistration": {"path": rel(Path(registered["registrationPath"]), output_root), "sha256": registered["registrationHash"]},
                "analyticsSnapshot": {"path": rel(Path(snapshot["snapshotPath"]), output_root), "sha256": snapshot["contentHash"]},
                "report": {"path": rel(Path(report["videoReportPath"]), output_root), "sha256": sha(Path(report["videoReportPath"]))},
                "recommendation": {"path": rel(Path(report["recommendationPath"]), output_root), "sha256": sha(Path(report["recommendationPath"]))},
            },
            "restartRecovery": task_before["state"] == "VIDEO_READY" and snapshot["status"] == "SNAPSHOT_READY",
            "productionIdempotent": production_idempotent,
            "publishIdempotent": publish_idempotent,
            "analyticsIdempotent": bool(registered_again.get("idempotent")) and bool(snapshot_again.get("idempotent")) and bool(report_again.get("idempotent")),
            "learningGate": learning_gate,
            "realUploadExecuted": False,
            "publicationReceiptCreated": False,
            "studioDataUsed": False,
        }
        if not all((chain_ok, production_idempotent, publish_idempotent, markets[language]["restartRecovery"], markets[language]["analyticsIdempotent"])):
            raise RuntimeError(f"{language}: Stage8 lifecycle invariant failed")

    profile_ids = {record["channelProfileId"] for record in markets.values()}
    summary = {
        "schemaVersion": "1.0.0",
        "productVersion": "0.8.0-rc.2",
        "fixtureType": "recorded-synthetic-stage8-e2e",
        "syntheticFixture": True,
        "markets": markets,
        "marketCount": len(markets),
        "channelIsolation": len(profile_ids) == 3,
        "stage5Validation": "PASS",
        "stage6Validation": "PASS" if stage6_validation.get("valid") else "FAIL",
        "networkExecution": False,
        "oauthExecuted": False,
        "realUploadExecuted": False,
        "publicationReceiptCreated": False,
        "studioDataUsed": False,
        "longTermLearningWritten": False,
    }
    summary_path = output_root / "summary.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (output_root / "summary.sha256").write_text(f"{sha(summary_path)}  summary.json\n", encoding="ascii")
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate the Stage8 three-market recorded synthetic end-to-end chain.")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(generate(args.output), ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
