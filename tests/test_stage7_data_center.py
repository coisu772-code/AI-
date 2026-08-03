from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MCP_ROOT = ROOT / "plugins" / "ai-video-channel-production" / "mcp"
import sys

sys.path.insert(0, str(MCP_ROOT))

from aivcp_tools.contracts import with_hash  # noqa: E402
from aivcp_tools.data_center import DataCenter  # noqa: E402
from aivcp_tools.errors import ToolError  # noqa: E402


PUBLISHED = "2026-06-01T00:00:00Z"


def fixture_hash(label: str) -> str:
    return hashlib.sha256(label.encode("utf-8")).hexdigest()


def registration(profile: str, market: str, *, video_id: str | None = None) -> dict:
    return {
        "channelProfileId": profile,
        "syntheticFixture": True,
        "syntheticRegistration": {
            "syntheticVideoId": video_id or f"synthetic-{market}-video",
            "receiptId": f"synthetic-receipt-{market}",
            "channelProfileId": profile,
            "projectId": f"project-{market}",
            "publishedAt": PUBLISHED,
            "upstreamBindings": [
                {
                    "role": role,
                    "contractType": contract_type,
                    "id": f"{role}-{market}",
                    "version": "1.0.0",
                    "schemaVersion": "1.0.0",
                    "sha256": fixture_hash(f"{role}-{market}"),
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
        },
    }


def public_source(*, profile: str = "profile-ja", video_id: str = "synthetic-ja-JP-video", views: int = 120, likes: int = 12, comments: int = 3) -> dict:
    return {
        "syntheticFixture": True,
        "factLevel": "PUBLIC_API_FACT",
        "binding": {"channelProfileId": profile, "videoId": video_id},
        "response": {
            "kind": "youtube#videoListResponse",
            "items": [
                {
                    "id": video_id,
                    "statistics": {
                        "viewCount": str(views),
                        "likeCount": str(likes),
                        "commentCount": str(comments),
                    },
                }
            ],
        },
    }


def owner_source(*, profile: str = "profile-ja", video_id: str = "synthetic-ja-JP-video", views: int = 110, retention: float = 1.25, elapsed: float = 0.5) -> dict:
    return {
        "syntheticFixture": True,
        "factLevel": "OWNER_ANALYTICS_FACT",
        "binding": {"channelProfileId": profile, "videoId": video_id},
        "records": [
            {"metricId": "youtube.analytics.views", "value": views, "unit": "count", "valueState": "PRESENT"},
            {"metricId": "youtube.reporting.impressions", "value": 1000, "unit": "count", "valueState": "PRESENT"},
            {"metricId": "youtube.reporting.impressions_ctr", "value": 0.052, "unit": "ratio", "valueState": "PRESENT"},
            {
                "metricId": "youtube.analytics.audience_watch_ratio",
                "value": retention,
                "unit": "ratio",
                "valueState": "PRESENT",
                "dimensions": {"elapsedVideoTimeRatio": elapsed},
            },
        ],
    }


def system_source(*, profile: str = "profile-ja", video_id: str = "synthetic-ja-JP-video", project_id: str = "project-ja-JP") -> dict:
    return {
        "syntheticFixture": True,
        "factLevel": "SYSTEM_FACT",
        "binding": {"channelProfileId": profile, "videoId": video_id, "projectId": project_id},
        "records": [
            {"metricId": "system.production.elapsed_seconds", "value": 321, "unit": "seconds", "valueState": "PRESENT"},
            {"metricId": "system.production.retry_count", "value": 0, "unit": "count", "valueState": "ZERO"},
        ],
        "timelineMap": {
            "durationSeconds": 600,
            "segments": [
                {
                    "startSeconds": 0,
                    "endSeconds": 300,
                    "lineIds": ["ep01-l001"],
                    "storyboardIds": ["ep01-sb001"],
                    "storyNode": "opening-promise",
                },
                {
                    "startSeconds": 300,
                    "endSeconds": 600,
                    "lineIds": ["ep01-l099"],
                    "storyboardIds": ["ep01-sb099"],
                    "storyNode": "payoff",
                },
            ],
        },
    }


def collection(
    profile: str,
    video_id: str,
    checkpoint: str,
    *,
    sources: dict,
    completeness: str | None = None,
    cutoff_suffix: str = "00:00:00Z",
) -> dict:
    dates = {
        "T+24H": ("2026-06-02T01:00:00Z", "2026-06-02T00:00:00Z", "2026-06-02T00:00:00Z"),
        "T+7D": ("2026-06-08T01:00:00Z", "2026-06-08T00:00:00Z", "2026-06-08T00:00:00Z"),
        "T+28D": ("2026-06-29T01:00:00Z", "2026-06-29T00:00:00Z", "2026-06-29T00:00:00Z"),
    }
    collected_at, window_end, cutoff = dates[checkpoint]
    if cutoff_suffix != "00:00:00Z":
        cutoff = cutoff[:11] + cutoff_suffix
    result = {
        "channelProfileId": profile,
        "videoId": video_id,
        "checkpoint": checkpoint,
        "collectedAt": collected_at,
        "windowStart": PUBLISHED,
        "windowEnd": window_end,
        "dataCutoff": cutoff,
        "timezone": "UTC",
        "sources": sources,
        "syntheticFixture": True,
    }
    if completeness:
        result["completeness"] = completeness
    return result


class Stage7DataCenterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.data_root = Path(self.temporary.name) / "data"
        self.plugin_root = ROOT / "plugins" / "ai-video-channel-production"
        self.center = DataCenter(self.data_root, plugin_root=self.plugin_root)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def assert_tool_error(self, code: str, callable_) -> None:
        with self.assertRaises(ToolError) as raised:
            callable_()
        self.assertEqual(code, raised.exception.code)

    def register(self, profile: str = "profile-ja", market: str = "ja-JP", *, video_id: str | None = None) -> str:
        args = registration(profile, market, video_id=video_id)
        result = self.center.register_video(args)
        self.assertEqual("VIDEO_REGISTERED", result["status"])
        self.assertEqual("synthetic-fixture", result["namespace"])
        return args["syntheticRegistration"]["syntheticVideoId"]

    def collect_and_report(self, profile: str, video_id: str, checkpoint: str, sources: dict, completeness: str | None = None) -> tuple[dict, dict]:
        snapshot = self.center.collect(collection(profile, video_id, checkpoint, sources=sources, completeness=completeness))
        report = self.center.generate_report(
            {"channelProfileId": profile, "videoId": video_id, "checkpoint": checkpoint, "syntheticFixture": True}
        )
        return snapshot, report

    def test_no_receipt_formal_registration_waits_without_writing(self) -> None:
        result = self.center.register_video({"channelProfileId": "formal-profile", "syntheticFixture": False})
        self.assertEqual("WAITING_FOR_PUBLICATION_RECEIPT", result["status"])
        self.assertFalse(self.data_root.exists())

    def _receipt(self, *, profile: str = "formal-profile", video_id: str = "fakeVideo01") -> dict:
        return with_hash(
            {
                "schemaVersion": "1.0.0",
                "contractType": "publication-receipt",
                "id": "receipt-formal-001",
                "version": "1.0.0",
                "createdAt": "2026-06-01T00:00:00Z",
                "hashAlgorithm": "SHA-256",
                "hashRule": "canonical-json-v1",
                "upstream": [],
                "receiptId": "receipt-formal-001",
                "publishIntentRef": {
                    "targetContractType": "publish-intent",
                    "targetId": "intent-formal-001",
                    "targetVersion": "1.0.0",
                    "targetSchemaVersion": "1.0.0",
                    "targetHash": "a" * 64,
                },
                "projectId": "project-formal",
                "channelProfileId": profile,
                "status": "RECEIPT_COMPLETE",
                "youtubeVideoId": video_id,
                "youtubeUrl": f"https://www.youtube.com/watch?v={video_id}",
                "targetChannel": {"publisherProfileId": "publisher-001", "channelSerial": "01", "youtubeChannelId": "UC1234567890"},
                "uploadedAt": PUBLISHED,
                "remoteState": {"thumbnail": "COMPLETE", "captions": "COMPLETE", "processing": "COMPLETE", "visibility": "PUBLISHED"},
            }
        )

    def test_fake_video_id_is_rejected_from_formal_namespace(self) -> None:
        receipt = Path(self.temporary.name) / "receipt.json"
        receipt.write_text(json.dumps(self._receipt()), encoding="utf-8")
        self.assert_tool_error(
            "SYNTHETIC_VIDEO_ID_FORBIDDEN",
            lambda: self.center.register_video(
                {"channelProfileId": "formal-profile", "syntheticFixture": False, "publicationReceiptPath": str(receipt)}
            ),
        )

    def test_bad_receipt_hash_and_cross_channel_are_rejected(self) -> None:
        bad = self._receipt(video_id="ValidId_01")
        bad["contentHash"] = "0" * 64
        bad_path = Path(self.temporary.name) / "bad.json"
        bad_path.write_text(json.dumps(bad), encoding="utf-8")
        self.assert_tool_error(
            "DATA_UPSTREAM_HASH_INVALID",
            lambda: self.center.register_video({"channelProfileId": "formal-profile", "syntheticFixture": False, "publicationReceiptPath": str(bad_path)}),
        )
        cross_path = Path(self.temporary.name) / "cross.json"
        cross_path.write_text(json.dumps(self._receipt(profile="other-profile", video_id="ValidId_01")), encoding="utf-8")
        self.assert_tool_error(
            "DATA_CROSS_CHANNEL_FORBIDDEN",
            lambda: self.center.register_video({"channelProfileId": "formal-profile", "syntheticFixture": False, "publicationReceiptPath": str(cross_path)}),
        )

    def test_public_only_report_keeps_owner_metrics_unknown(self) -> None:
        video_id = self.register()
        snapshot, report_result = self.collect_and_report("profile-ja", video_id, "T+24H", {"public": public_source(), "system": system_source()}, "provisional")
        self.assertEqual("provisional", snapshot["completeness"])
        report = json.loads(Path(report_result["videoReportPath"]).read_text(encoding="utf-8"))
        self.assertTrue(report["publicOnly"])
        unknown_ids = {item["metricId"] for item in report["unknown"]}
        self.assertIn("youtube.reporting.impressions_ctr", unknown_ids)
        self.assertIn("youtube.analytics.audience_watch_ratio", unknown_ids)
        unknown_dimensions = {item.get("dimensions", {}).get("requiredDimension") for item in report["unknown"]}
        self.assertIn("device_type", unknown_dimensions)
        self.assertIn("traffic_source", unknown_dimensions)
        self.assertFalse(any(item["factLevel"] == "OWNER_ANALYTICS_FACT" for item in report["facts"]))

    def test_public_source_cannot_masquerade_as_owner_or_ctr(self) -> None:
        video_id = self.register()
        owner_marked_public = public_source()
        owner_marked_public["factLevel"] = "OWNER_ANALYTICS_FACT"
        self.assert_tool_error(
            "FACT_LEVEL_SOURCE_MISMATCH",
            lambda: self.center.collect(collection("profile-ja", video_id, "T+24H", sources={"public": owner_marked_public})),
        )
        forged_ctr = public_source()
        forged_ctr["response"]["items"][0]["statistics"]["impressionsCtr"] = 0.08
        self.assert_tool_error(
            "PUBLIC_METRIC_OWNER_MASQUERADE",
            lambda: self.center.collect(collection("profile-ja", video_id, "T+24H", sources={"public": forged_ctr})),
        )

    def test_owner_fact_level_and_missing_zero_are_rejected(self) -> None:
        video_id = self.register()
        wrong_level = owner_source()
        wrong_level["factLevel"] = "PUBLIC_API_FACT"
        self.assert_tool_error(
            "FACT_LEVEL_SOURCE_MISMATCH",
            lambda: self.center.collect(collection("profile-ja", video_id, "T+24H", sources={"owner": wrong_level})),
        )
        filled_missing = owner_source()
        filled_missing["records"] = [
            {"metricId": "youtube.reporting.impressions", "value": 0, "unit": "count", "valueState": "MISSING"}
        ]
        self.assert_tool_error(
            "DATA_UNKNOWN_FILLED_WITH_VALUE",
            lambda: self.center.collect(collection("profile-ja", video_id, "T+24H", sources={"owner": filled_missing})),
        )

    def test_data_cutoff_is_required(self) -> None:
        video_id = self.register()
        args = collection("profile-ja", video_id, "T+24H", sources={"public": public_source()})
        args.pop("dataCutoff")
        self.assert_tool_error("DATA_CUTOFF_REQUIRED", lambda: self.center.collect(args))

    def test_raw_and_snapshot_imports_are_idempotent(self) -> None:
        video_id = self.register()
        args = collection("profile-ja", video_id, "T+24H", sources={"public": public_source(), "system": system_source()})
        first = self.center.collect(args)
        second = self.center.collect(args)
        self.assertFalse(first["idempotent"])
        self.assertTrue(second["idempotent"])
        root = self.data_root / "synthetic-fixtures" / "channels" / "profile-ja" / "analytics"
        self.assertEqual(1, len(list((root / "raw" / "public-data-api").glob("*.json"))))
        self.assertEqual(1, len(list((root / "raw" / "system").glob("*.json"))))
        self.assertEqual(1, len(list((root / "snapshots").rglob("manifest.json"))))

    def test_late_owner_data_creates_revised_snapshot_and_report(self) -> None:
        video_id = self.register()
        first_snapshot, first_report = self.collect_and_report(
            "profile-ja", video_id, "T+7D", {"public": public_source(views=500), "system": system_source()}, "complete"
        )
        second_args = collection(
            "profile-ja",
            video_id,
            "T+7D",
            sources={"public": public_source(views=520), "owner": owner_source(views=510), "system": system_source()},
            completeness="complete",
        )
        second_args["collectedAt"] = "2026-06-09T01:00:00Z"
        second_args["dataCutoff"] = "2026-06-09T00:00:00Z"
        second_snapshot = self.center.collect(second_args)
        second_report = self.center.generate_report(
            {"channelProfileId": "profile-ja", "videoId": video_id, "checkpoint": "T+7D", "syntheticFixture": True}
        )
        self.assertEqual("complete", first_snapshot["completeness"])
        self.assertEqual("revised", second_snapshot["completeness"])
        self.assertEqual("revised", second_report["reportStatus"])
        self.assertNotEqual(first_report["reportId"], second_report["reportId"])
        self.assertTrue(Path(first_report["videoReportPath"]).is_file())

    def test_retention_above_one_and_elapsed_ratio_are_not_clamped(self) -> None:
        video_id = self.register()
        snapshot = self.center.collect(
            collection(
                "profile-ja",
                video_id,
                "T+7D",
                sources={"public": public_source(), "owner": owner_source(retention=1.35, elapsed=1.2), "system": system_source()},
                completeness="complete",
            )
        )
        evidence = json.loads(Path(snapshot["timelineEvidencePath"]).read_text(encoding="utf-8"))
        card = evidence["cards"][0]
        self.assertEqual(1.35, card["retentionValue"])
        self.assertTrue(card["retentionValuePreservedAboveOne"])
        self.assertEqual(720.0, card["elapsedSeconds"])
        self.assertFalse(evidence["ratioClamped"])

    def test_cross_channel_baselines_never_merge(self) -> None:
        first = self.register("profile-ja", "ja-JP")
        second = self.register("profile-en", "en-US")
        _, report = self.collect_and_report("profile-ja", first, "T+28D", {"public": public_source(video_id=first), "owner": owner_source(video_id=first), "system": system_source(video_id=first)}, "complete")
        self.collect_and_report(
            "profile-en",
            second,
            "T+28D",
            {
                "public": public_source(profile="profile-en", video_id=second, views=9999),
                "owner": owner_source(profile="profile-en", video_id=second, views=9999),
                "system": system_source(profile="profile-en", video_id=second, project_id="project-en-US"),
            },
            "complete",
        )
        document = json.loads(Path(report["videoReportPath"]).read_text(encoding="utf-8"))
        self.assertEqual(0, document["baseline"]["sampleSize"])
        self.assertNotIn(second, json.dumps(document, ensure_ascii=False))

    def test_progress_is_read_only_and_restart_recovers_tasks(self) -> None:
        video_id = self.register()
        root = self.data_root / "synthetic-fixtures" / "channels" / "profile-ja" / "analytics"
        database = root / "data-center-v1.sqlite3"
        before = hashlib.sha256(database.read_bytes()).hexdigest()
        restarted = DataCenter(self.data_root, plugin_root=self.plugin_root)
        progress = restarted.progress({"channelProfileId": "profile-ja", "videoId": video_id, "syntheticFixture": True})
        after = hashlib.sha256(database.read_bytes()).hexdigest()
        self.assertEqual("OK", progress["status"])
        self.assertEqual(3, len(progress["videos"][0]["tasks"]))
        self.assertEqual(before, after)

    def test_recommendation_requires_evidence_and_long_term_write_is_blocked(self) -> None:
        video_id = self.register()
        root = self.data_root / "synthetic-fixtures" / "channels" / "profile-ja" / "analytics"
        self.assert_tool_error(
            "RECOMMENDATION_EVIDENCE_REQUIRED",
            lambda: self.center._make_recommendation(  # noqa: SLF001 - validates the safety invariant directly
                analytics_root=root,
                channel_profile_id="profile-ja",
                video_id=video_id,
                report_id="report-empty",
                report_hash="0" * 64,
                checkpoint="T+28D",
                facts=[],
                unknown=[],
                baseline={"sampleSize": 0, "confidence": "low"},
                synthetic=True,
            ),
        )
        _, report = self.collect_and_report("profile-ja", video_id, "T+28D", {"public": public_source(), "owner": owner_source(), "system": system_source()}, "complete")
        recommendations = self.center.list_recommendations({"channelProfileId": "profile-ja", "syntheticFixture": True})
        recommendation_id = recommendations["recommendations"][0]["recommendationId"]
        self.assert_tool_error(
            "LONG_TERM_LEARNING_APPROVAL_REQUIRED",
            lambda: self.center.learning_decision(
                {
                    "channelProfileId": "profile-ja",
                    "recommendationId": recommendation_id,
                    "decision": "channel_default",
                    "syntheticFixture": True,
                    "executionMode": "auto",
                }
            ),
        )
        self.assertEqual("AWAITING_LEARNING_DECISION", self.center.list_recommendations({"channelProfileId": "profile-ja", "syntheticFixture": True})["recommendations"][0]["status"])
        self.assertEqual("REPORT_READY", report["status"])

    def test_test_only_decision_stays_project_scoped(self) -> None:
        video_id = self.register()
        self.collect_and_report("profile-ja", video_id, "T+28D", {"public": public_source(), "owner": owner_source(), "system": system_source()}, "complete")
        recommendation_id = self.center.list_recommendations({"channelProfileId": "profile-ja", "syntheticFixture": True})["recommendations"][0]["recommendationId"]
        result = self.center.learning_decision(
            {
                "channelProfileId": "profile-ja",
                "recommendationId": recommendation_id,
                "decision": "test_only",
                "projectId": "project-ja-JP",
                "syntheticFixture": True,
            }
        )
        self.assertEqual("TEST_ONLY", result["status"])
        self.assertFalse(result["longTermLearningWritten"])

    def test_auth_revenue_scope_token_and_migration_guards(self) -> None:
        capabilities = self.center.capabilities()
        auth = capabilities["analyticsAuthorization"]
        self.assertEqual("AUTH_REQUIRED", auth["status"])
        self.assertFalse(auth["available"])
        self.assertFalse(auth["monetaryScope"]["enabled"])
        self.assertFalse(auth["oauthStarted"])
        self.assert_tool_error(
            "DATA_SENSITIVE_MATERIAL_FORBIDDEN",
            lambda: self.center.register_video(
                {"channelProfileId": "profile-ja", "syntheticFixture": True, "access_token": "ya29.secret", "syntheticRegistration": {}}
            ),
        )
        self.assertFalse(self.data_root.exists())
        legacy = Path(self.temporary.name) / "channel.db"
        legacy.write_bytes(b"existing-user-database")
        before = hashlib.sha256(legacy.read_bytes()).hexdigest()
        guarded = self.center.capabilities(existing_channel_database_path=str(legacy))
        after = hashlib.sha256(legacy.read_bytes()).hexdigest()
        self.assertEqual("MIGRATION_APPROVAL_REQUIRED", guarded["migration"]["status"])
        self.assertFalse(guarded["migration"]["migrationExecuted"])
        self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main()
