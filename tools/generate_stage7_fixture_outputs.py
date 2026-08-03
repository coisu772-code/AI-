from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
MCP_ROOT = ROOT / "plugins" / "ai-video-channel-production" / "mcp"
sys.path.insert(0, str(MCP_ROOT))

from aivcp_tools.data_center import DataCenter  # noqa: E402


PUBLISHED = "2026-06-01T00:00:00Z"
MARKETS = (
    ("ja-JP", "stage7-ja-profile"),
    ("zh-CN", "stage7-zh-profile"),
    ("en-US", "stage7-en-profile"),
)


def sha_label(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def file_hash(path: str | Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def public_payload(market: str, profile: str, video_id: str, views: int) -> dict[str, Any]:
    return {
        "syntheticFixture": True,
        "factLevel": "PUBLIC_API_FACT",
        "binding": {"channelProfileId": profile, "videoId": video_id},
        "response": {
            "kind": "youtube#videoListResponse",
            "fixtureNotice": "recorded synthetic response; not live channel performance",
            "items": [
                {
                    "id": video_id,
                    "statistics": {
                        "viewCount": str(views),
                        "likeCount": str(max(1, views // 12)),
                        "commentCount": str(max(0, views // 50)),
                    },
                }
            ],
        },
    }


def owner_payload(market: str, profile: str, video_id: str, views: int, *, retention: float = 1.08) -> dict[str, Any]:
    return {
        "syntheticFixture": True,
        "factLevel": "OWNER_ANALYTICS_FACT",
        "binding": {"channelProfileId": profile, "videoId": video_id},
        "fixtureNotice": "synthetic owner analytics; not YouTube Studio data",
        "records": [
            {"metricId": "youtube.analytics.views", "value": views, "unit": "count", "valueState": "PRESENT"},
            {"metricId": "youtube.analytics.estimated_minutes_watched", "value": views * 4.2, "unit": "minutes", "valueState": "PRESENT"},
            {"metricId": "youtube.analytics.average_view_duration_seconds", "value": 252, "unit": "seconds", "valueState": "PRESENT"},
            {"metricId": "youtube.reporting.impressions", "value": views * 7, "unit": "count", "valueState": "PRESENT"},
            {"metricId": "youtube.reporting.impressions_ctr", "value": 0.051, "unit": "ratio", "valueState": "PRESENT"},
            {"metricId": "youtube.analytics.subscribers_gained", "value": max(1, views // 100), "unit": "count", "valueState": "PRESENT"},
            {
                "metricId": "youtube.analytics.audience_watch_ratio",
                "value": retention,
                "unit": "ratio",
                "valueState": "PRESENT",
                "dimensions": {"elapsedVideoTimeRatio": 0.5},
            },
            {
                "metricId": "youtube.analytics.relative_retention_performance",
                "value": 0.54,
                "unit": "ratio",
                "valueState": "PRESENT",
                "dimensions": {"elapsedVideoTimeRatio": 0.9},
            },
        ],
    }


def system_payload(market: str, profile: str, video_id: str) -> dict[str, Any]:
    return {
        "syntheticFixture": True,
        "factLevel": "SYSTEM_FACT",
        "binding": {"channelProfileId": profile, "videoId": video_id, "projectId": f"stage7-project-{market}"},
        "fixtureNotice": "hash-bound synthetic Stage5/6 system facts",
        "records": [
            {"metricId": "system.production.elapsed_seconds", "value": 5400, "unit": "seconds", "valueState": "PRESENT"},
            {"metricId": "system.production.retry_count", "value": 1, "unit": "count", "valueState": "PRESENT"},
            {"metricId": "system.production.optional_cost_microunits", "value": 2500000, "unit": "currency_microunits", "valueState": "PRESENT"},
        ],
        "timelineMap": {
            "durationSeconds": 600,
            "market": market,
            "segments": [
                {"startSeconds": 0, "endSeconds": 120, "lineIds": ["ep01-l001"], "storyboardIds": ["ep01-sb001"], "storyNode": "promise"},
                {"startSeconds": 120, "endSeconds": 420, "lineIds": ["ep01-l020"], "storyboardIds": ["ep01-sb020"], "storyNode": "progress"},
                {"startSeconds": 420, "endSeconds": 600, "lineIds": ["ep01-l080"], "storyboardIds": ["ep01-sb080"], "storyNode": "payoff"},
            ],
        },
    }


def registration(market: str, profile: str) -> dict[str, Any]:
    return {
        "channelProfileId": profile,
        "syntheticFixture": True,
        "syntheticRegistration": {
            "syntheticVideoId": f"synthetic-{market}-stage7",
            "receiptId": f"synthetic-receipt-{market}",
            "channelProfileId": profile,
            "projectId": f"stage7-project-{market}",
            "publishedAt": PUBLISHED,
            "upstreamBindings": [
                {
                    "role": role,
                    "contractType": contract_type,
                    "id": f"stage7-{role}-{market}",
                    "version": "1.0.0",
                    "schemaVersion": "1.0.0",
                    "sha256": sha_label(f"recorded-stage7-{role}-{market}"),
                }
                for role, contract_type in (
                    ("topic", "topic-package"),
                    ("manuscript", "manuscript-package"),
                    ("publishing", "publishing-asset-package"),
                    ("production", "production-result-package"),
                    ("publishIntent", "publish-intent"),
                )
            ],
        },
        "videoMetadata": {
            "language": market,
            "contentForm": "long-form-novel-manga",
            "durationBand": "8-12m",
            "topicLane": "family-reversal",
            "publishTimeBand": "evening",
            "fixtureNotice": "synthetic only",
        },
    }


def collect_args(profile: str, video_id: str, checkpoint: str, sources: dict[str, Any], *, completeness: str, revision: bool = False) -> dict[str, Any]:
    dates = {
        "T+24H": ("2026-06-02T01:00:00Z", "2026-06-02T00:00:00Z"),
        "T+7D": ("2026-06-08T01:00:00Z", "2026-06-08T00:00:00Z"),
        "T+28D": ("2026-06-29T01:00:00Z", "2026-06-29T00:00:00Z"),
    }
    collected, cutoff = dates[checkpoint]
    if revision:
        collected = collected.replace("T01", "T02")
        cutoff = cutoff.replace("T00", "T01")
    return {
        "channelProfileId": profile,
        "videoId": video_id,
        "checkpoint": checkpoint,
        "collectedAt": collected,
        "windowStart": PUBLISHED,
        "windowEnd": dates[checkpoint][1],
        "dataCutoff": cutoff,
        "timezone": "UTC",
        "completeness": completeness,
        "sources": sources,
        "syntheticFixture": True,
    }


def build(output: Path) -> dict[str, Any]:
    if output.exists():
        shutil.rmtree(output)
    output.mkdir(parents=True)
    data_root = output / "data"
    center = DataCenter(data_root, plugin_root=ROOT / "plugins" / "ai-video-channel-production")
    markets: list[dict[str, Any]] = []
    for index, (market, profile) in enumerate(MARKETS, start=1):
        registered = center.register_video(registration(market, profile))
        video_id = registered["videoId"]
        market_record: dict[str, Any] = {
            "market": market,
            "channelProfileId": profile,
            "videoId": video_id,
            "syntheticFixture": True,
            "registrationPath": registered["registrationPath"],
            "registrationHash": registered["registrationHash"],
            "checkpoints": [],
        }
        t24_sources = {"public": public_payload(market, profile, video_id, 100 * index), "system": system_payload(market, profile, video_id)}
        t24_snapshot = center.collect(collect_args(profile, video_id, "T+24H", t24_sources, completeness="provisional"))
        t24_report = center.generate_report({"channelProfileId": profile, "videoId": video_id, "checkpoint": "T+24H", "syntheticFixture": True})
        market_record["checkpoints"].append({"checkpoint": "T+24H", "snapshot": t24_snapshot, "report": t24_report, "publicOnly": True})

        t7_sources = {"public": public_payload(market, profile, video_id, 500 * index), "system": system_payload(market, profile, video_id)}
        t7_snapshot = center.collect(collect_args(profile, video_id, "T+7D", t7_sources, completeness="complete"))
        t7_report = center.generate_report({"channelProfileId": profile, "videoId": video_id, "checkpoint": "T+7D", "syntheticFixture": True})
        t7_revision_sources = {
            "public": public_payload(market, profile, video_id, 520 * index),
            "owner": owner_payload(market, profile, video_id, 510 * index, retention=1.1 + index / 100),
            "system": system_payload(market, profile, video_id),
        }
        t7_revised_snapshot = center.collect(collect_args(profile, video_id, "T+7D", t7_revision_sources, completeness="complete", revision=True))
        t7_revised_report = center.generate_report({"channelProfileId": profile, "videoId": video_id, "checkpoint": "T+7D", "syntheticFixture": True})
        market_record["checkpoints"].append(
            {
                "checkpoint": "T+7D",
                "initialSnapshot": t7_snapshot,
                "initialReport": t7_report,
                "snapshot": t7_revised_snapshot,
                "report": t7_revised_report,
                "lateRevision": True,
            }
        )

        t28_sources = {
            "public": public_payload(market, profile, video_id, 900 * index),
            "owner": owner_payload(market, profile, video_id, 880 * index, retention=1.15),
            "system": system_payload(market, profile, video_id),
        }
        t28_snapshot = center.collect(collect_args(profile, video_id, "T+28D", t28_sources, completeness="complete"))
        t28_report = center.generate_report({"channelProfileId": profile, "videoId": video_id, "checkpoint": "T+28D", "syntheticFixture": True})
        market_record["checkpoints"].append({"checkpoint": "T+28D", "snapshot": t28_snapshot, "report": t28_report, "recommendation": True})
        market_record["progress"] = center.progress({"channelProfileId": profile, "videoId": video_id, "syntheticFixture": True})
        market_record["recommendations"] = center.list_recommendations({"channelProfileId": profile, "syntheticFixture": True})
        markets.append(market_record)

    summary: dict[str, Any] = {
        "schemaVersion": "1.0.0",
        "generatedAt": "2026-08-04T00:00:00Z",
        "fixtureType": "recorded-synthetic-stage7",
        "syntheticFixture": True,
        "formalRegistrationExecuted": False,
        "oauthExecuted": False,
        "youtubeApiNetworkCalled": False,
        "studioDataUsed": False,
        "longTermLearningWritten": False,
        "markets": markets,
    }
    summary_path = output / "summary.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    summary["summaryPath"] = str(summary_path)
    summary["summarySha256"] = file_hash(summary_path)
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate the Stage7 three-market recorded synthetic data center chain.")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = build(args.output.resolve())
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
