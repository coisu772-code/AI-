from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any


def load(path: str | Path) -> dict[str, Any]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def canonical_hash(document: dict[str, Any]) -> str:
    payload = dict(document)
    payload.pop("contentHash", None)
    encoded = json.dumps(payload, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def validate(output: Path) -> list[str]:
    errors: list[str] = []
    summary_path = output / "summary.json"
    if not summary_path.is_file():
        return ["summary.json is missing"]
    summary = load(summary_path)
    if summary.get("fixtureType") != "recorded-synthetic-stage7" or summary.get("syntheticFixture") is not True:
        errors.append("summary is not explicitly recorded synthetic")
    for forbidden in ("formalRegistrationExecuted", "oauthExecuted", "youtubeApiNetworkCalled", "studioDataUsed", "longTermLearningWritten"):
        if summary.get(forbidden) is not False:
            errors.append(f"unsafe boundary changed: {forbidden}")
    markets = summary.get("markets")
    if not isinstance(markets, list) or len(markets) != 3:
        return errors + ["expected exactly three markets"]
    expected_markets = {"ja-JP", "zh-CN", "en-US"}
    if {market.get("market") for market in markets} != expected_markets:
        errors.append("market set mismatch")
    profiles: set[str] = set()
    coverage: set[tuple[str, str]] = set()
    for market in markets:
        profile = market.get("channelProfileId")
        if profile in profiles:
            errors.append("channel profiles are not isolated")
        profiles.add(profile)
        if market.get("syntheticFixture") is not True or not str(market.get("videoId", "")).startswith("synthetic-"):
            errors.append(f"{profile}: synthetic identity marker missing")
        registration = load(market["registrationPath"])
        if registration.get("namespace") != "synthetic-fixture" or registration.get("contentHash") != market.get("registrationHash"):
            errors.append(f"{profile}: registration namespace/hash invalid")
        checkpoints = market.get("checkpoints") or []
        if len(checkpoints) != 3:
            errors.append(f"{profile}: expected three checkpoints")
        for checkpoint in checkpoints:
            name = checkpoint.get("checkpoint")
            snapshot_result = checkpoint.get("snapshot") or {}
            report_result = checkpoint.get("report") or {}
            snapshot_path = Path(snapshot_result.get("snapshotPath", ""))
            report_path = Path(report_result.get("videoReportPath", ""))
            channel_path = Path(report_result.get("channelReportPath", ""))
            recommendation_path = Path(report_result.get("recommendationPath", ""))
            for required in (snapshot_path / "manifest.json", snapshot_path / "query-plan.json", snapshot_path / "raw-bindings.json", snapshot_path / "normalized-metrics.json", snapshot_path / "completeness.json", snapshot_path / "source-lock.json", report_path, channel_path, recommendation_path):
                if not required.is_file():
                    errors.append(f"{profile}/{name}: missing {required.name}")
            if (snapshot_path / "manifest.json").is_file():
                manifest = load(snapshot_path / "manifest.json")
                if canonical_hash(manifest) != manifest.get("contentHash"):
                    errors.append(f"{profile}/{name}: snapshot hash invalid")
                coverage.add((name, manifest.get("completeness")))
            if report_path.is_file():
                report = load(report_path)
                if canonical_hash(report) != report.get("contentHash"):
                    errors.append(f"{profile}/{name}: video report hash invalid")
                if name == "T+24H":
                    if not report.get("publicOnly"):
                        errors.append(f"{profile}: T+24 should prove public-only path")
                    owner_ids = {item.get("metricId") for item in report.get("unknown", [])}
                    for owner_id in ("youtube.reporting.impressions_ctr", "youtube.analytics.audience_watch_ratio"):
                        if owner_id not in owner_ids:
                            errors.append(f"{profile}: public-only report omitted UNKNOWN {owner_id}")
                    unknown_dimensions = {item.get("dimensions", {}).get("requiredDimension") for item in report.get("unknown", [])}
                    for dimension in ("traffic_source", "device_type", "country", "age_group", "gender"):
                        if dimension not in unknown_dimensions:
                            errors.append(f"{profile}: public-only report omitted UNKNOWN dimension {dimension}")
            if channel_path.is_file():
                channel_report = load(channel_path)
                if channel_report.get("channelIsolation", {}).get("crossChannelRead") is not False:
                    errors.append(f"{profile}/{name}: channel isolation marker invalid")
            if recommendation_path.is_file():
                recommendation = load(recommendation_path)
                if recommendation.get("status") != "AWAITING_LEARNING_DECISION" or not recommendation.get("evidence"):
                    errors.append(f"{profile}/{name}: recommendation gate/evidence invalid")
        progress = market.get("progress", {})
        if progress.get("readOnly") is not True:
            errors.append(f"{profile}: progress is not read-only")
        for recommendation in market.get("recommendations", {}).get("recommendations", []):
            if recommendation.get("status") != "AWAITING_LEARNING_DECISION":
                errors.append(f"{profile}: learning decision was applied")
    required_coverage = {("T+24H", "provisional"), ("T+7D", "revised"), ("T+28D", "complete")}
    if not required_coverage.issubset(coverage):
        errors.append(f"checkpoint/status coverage missing: {sorted(required_coverage - coverage)}")
    formal_root = output / "data" / "channels"
    if formal_root.exists() and any(formal_root.iterdir()):
        errors.append("synthetic validation wrote into formal channel namespace")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate Stage7 recorded synthetic data center outputs.")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    errors = validate(args.output.resolve())
    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        print(f"Stage7 validation failed with {len(errors)} error(s).")
        return 1
    print("Stage7 three-market snapshots, reports, recommendations, isolation, revisions, and fact boundaries passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
