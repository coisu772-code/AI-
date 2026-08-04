from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Iterable

from .contracts import canonical_hash, utc_now, with_hash
from .errors import ToolError
from .security import contains_sensitive_material


DATA_CENTER_VERSION = "1.0.0"
ANALYTICS_SNAPSHOT_VERSION = "1.0.0"
VIDEO_REPORT_VERSION = "1.0.0"
CHANNEL_REPORT_VERSION = "1.0.0"
RECOMMENDATION_CARD_VERSION = "1.0.0"
FACT_LEVELS = {
    "SYSTEM_FACT",
    "PUBLIC_API_FACT",
    "OWNER_ANALYTICS_FACT",
    "SAMPLE_OBSERVATION",
    "INFERENCE",
    "UNKNOWN",
}
VALUE_STATES = {"PRESENT", "ZERO", "MISSING", "THRESHOLD_PROTECTED", "DELAYED"}
CHECKPOINTS = {"T+24H": timedelta(hours=24), "T+7D": timedelta(days=7), "T+28D": timedelta(days=28)}
REPORT_STATES = {"provisional", "complete", "revised", "superseded"}
SAFE_COMPONENT = re.compile(r"^[A-Za-z0-9._-]{3,160}$")
REAL_VIDEO_ID = re.compile(r"^[A-Za-z0-9_-]{6,32}$")
HEX64 = re.compile(r"^[0-9a-f]{64}$")
FAKE_MARKERS = re.compile(r"(?:synthetic|fixture|fake|dummy|sample|example|test)", re.IGNORECASE)

PUBLIC_METRICS = {
    "viewCount": ("youtube.public.view_count", "count"),
    "likeCount": ("youtube.public.like_count", "count"),
    "commentCount": ("youtube.public.comment_count", "count"),
}
OWNER_METRICS = {
    "youtube.analytics.engaged_views",
    "youtube.analytics.views",
    "youtube.analytics.estimated_minutes_watched",
    "youtube.analytics.average_view_duration_seconds",
    "youtube.analytics.average_view_percentage",
    "youtube.analytics.likes",
    "youtube.analytics.comments",
    "youtube.analytics.shares",
    "youtube.analytics.subscribers_gained",
    "youtube.analytics.subscribers_lost",
    "youtube.reporting.impressions",
    "youtube.reporting.impressions_ctr",
    "youtube.analytics.audience_watch_ratio",
    "youtube.analytics.relative_retention_performance",
}
OWNER_UNKNOWN_DEFAULTS = {
    "youtube.reporting.impressions": "count",
    "youtube.reporting.impressions_ctr": "ratio",
    "youtube.analytics.average_view_duration_seconds": "seconds",
    "youtube.analytics.average_view_percentage": "percent",
    "youtube.analytics.audience_watch_ratio": "ratio",
    "youtube.analytics.subscribers_gained": "count",
}
OWNER_UNKNOWN_DIMENSIONS = ("traffic_source", "device_type", "country", "age_group", "gender", "subscribed_status")
SYSTEM_METRICS = {
    "system.collection.collected_at",
    "system.production.elapsed_seconds",
    "system.production.retry_count",
    "system.production.model_call_count",
    "system.production.manual_repair_count",
    "system.production.optional_cost_microunits",
}
UPSTREAM_TYPES = {
    "topic": "topic-package",
    "manuscript": "manuscript-package",
    "publishing": "publishing-asset-package",
    "production": "production-result-package",
    "publishIntent": "publish-intent",
}


def _json_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _sha_value(value: Any) -> str:
    return hashlib.sha256(_json_bytes(value)).hexdigest()


def _sha_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ToolError("DATA_DOCUMENT_INVALID", "数据中心输入不是可读取的 UTF-8 JSON。", details={"path": str(path)}) from exc
    if not isinstance(value, dict):
        raise ToolError("DATA_DOCUMENT_INVALID", "数据中心输入 JSON 必须是对象。", details={"path": str(path)})
    if contains_sensitive_material(value):
        raise ToolError("DATA_SENSITIVE_MATERIAL_FORBIDDEN", "数据中心不接收 Token、密钥或凭据字段。")
    return value


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def _parse_time(value: Any, field: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise ToolError("DATA_CUTOFF_REQUIRED" if field == "dataCutoff" else "DATA_TIME_INVALID", f"{field} 必须是带时区的日期时间。")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ToolError("DATA_TIME_INVALID", f"{field} 不是有效日期时间。") from exc
    if parsed.tzinfo is None:
        raise ToolError("DATA_TIME_INVALID", f"{field} 必须包含时区。")
    return parsed.astimezone(UTC)


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _component(value: Any, name: str) -> str:
    if not isinstance(value, str) or not SAFE_COMPONENT.fullmatch(value):
        raise ToolError("DATA_IDENTIFIER_INVALID", f"{name} 不是安全标识。")
    return value


def _metric_entry(
    metric_id: str,
    *,
    value: int | float | None,
    unit: str,
    fact_level: str,
    state: str,
    source: str,
    dimensions: dict[str, Any] | None = None,
    reason: str | None = None,
) -> dict[str, Any]:
    if fact_level not in FACT_LEVELS or state not in VALUE_STATES:
        raise ToolError("DATA_FACT_LEVEL_INVALID", "指标事实等级或值状态无效。")
    if state == "ZERO" and value != 0:
        raise ToolError("DATA_ZERO_STATE_INVALID", "ZERO 状态必须明确保存数值 0。")
    if state in {"MISSING", "THRESHOLD_PROTECTED", "DELAYED"}:
        if value is not None:
            raise ToolError("DATA_UNKNOWN_FILLED_WITH_VALUE", "缺失、阈值保护或延迟值必须为 null，不能填 0 或猜测值。")
        fact_level = "UNKNOWN"
    elif value is None:
        raise ToolError("DATA_PRESENT_VALUE_REQUIRED", "PRESENT/ZERO 指标必须提供数值。")
    return {
        "metricId": metric_id,
        "value": value,
        "unit": unit,
        "factLevel": fact_level,
        "valueState": state,
        "source": source,
        "dimensions": dimensions or {},
        "reason": reason,
    }


class DataCenter:
    """Local-only, channel-isolated analytics and recommendation service."""

    def __init__(self, data_root: Path, *, plugin_root: Path | None = None) -> None:
        self.data_root = data_root.resolve()
        self.plugin_root = plugin_root.resolve() if plugin_root else None

    def capabilities(self, *, existing_channel_database_path: str | None = None) -> dict[str, Any]:
        catalog_capability: dict[str, Any]
        try:
            catalog_path = self._catalog_path()
            catalog_document = json.loads(catalog_path.read_text(encoding="utf-8"))
            catalog_capability = {
                "available": True,
                "version": catalog_document.get("catalogVersion"),
                "checkedAt": catalog_document.get("checkedAt"),
                "sha256": _sha_file(catalog_path),
            }
        except (ToolError, OSError, json.JSONDecodeError):
            catalog_capability = {"available": False, "version": None, "checkedAt": None, "sha256": None}
        result: dict[str, Any] = {
            "dataCenterVersion": DATA_CENTER_VERSION,
            "available": True,
            "metricCatalog": catalog_capability,
            "contracts": {
                "analyticsSnapshot": ANALYTICS_SNAPSHOT_VERSION,
                "videoPerformanceReport": VIDEO_REPORT_VERSION,
                "channelStrategyReport": CHANNEL_REPORT_VERSION,
                "recommendationCard": RECOMMENDATION_CARD_VERSION,
            },
            "analyticsAuthorization": {
                "status": "AUTH_REQUIRED",
                "available": False,
                "independentFromUploadAuthorization": True,
                "readOnlyScopes": ["https://www.googleapis.com/auth/yt-analytics.readonly"],
                "monetaryScope": {
                    "scope": "https://www.googleapis.com/auth/yt-analytics-monetary.readonly",
                    "enabled": False,
                    "available": False,
                },
                "oauthStarted": False,
                "credentialsVisibleToCodex": False,
            },
            "sources": {
                "public": "authorized-recorded-import-or-future-safe-read-only-adapter",
                "ownerAnalytics": "AUTH_REQUIRED",
                "ownerReporting": "AUTH_REQUIRED",
                "system": "hash-bound-local-upstream-only",
            },
            "factLevels": sorted(FACT_LEVELS),
            "checkpoints": list(CHECKPOINTS),
            "formalRegistrationRequires": ["Publication Receipt v1", "youtube_video_id", *UPSTREAM_TYPES],
            "syntheticNamespace": "data/synthetic-fixtures/channels/<profile>/analytics",
            "formalNamespace": "data/channels/<profile>/analytics",
            "networkExecution": False,
            "longTermLearningWrite": False,
        }
        if existing_channel_database_path:
            legacy = Path(existing_channel_database_path).resolve()
            result["migration"] = {
                "status": "MIGRATION_APPROVAL_REQUIRED",
                "sourcePath": str(legacy),
                "sourceExists": legacy.is_file(),
                "sourceSha256": _sha_file(legacy) if legacy.is_file() else None,
                "backupRequired": True,
                "migrationExecuted": False,
                "plan": ["create verified backup", "review schema plan", "obtain explicit approval", "run separate migration tool"],
            }
        return result

    def _analytics_root(self, channel_profile_id: str, *, synthetic: bool, create: bool = False) -> Path:
        profile = _component(channel_profile_id, "channelProfileId")
        root = self.data_root
        if synthetic:
            root = root / "synthetic-fixtures"
        result = root / "channels" / profile / "analytics"
        if create:
            for child in (
                "metric-catalog",
                "raw/public-data-api",
                "raw/analytics-query",
                "raw/reporting-bulk",
                "raw/system",
                "normalized",
                "snapshots",
                "baselines",
                "timeline-maps",
                "reports/videos",
                "reports/channel",
                "recommendations",
                "experiments",
                "sync-state",
            ):
                (result / child).mkdir(parents=True, exist_ok=True)
        return result

    def _catalog_path(self) -> Path:
        if self.plugin_root is None:
            raise ToolError("METRIC_CATALOG_UNAVAILABLE", "缺少插件根目录，无法定位 Metric Catalog v1。")
        roots = [
            self.plugin_root.parents[1] / "contracts" / "metric-catalog",
            self.plugin_root / "assets" / "metric-catalog",
        ]
        install_root_value = os.environ.get("AIVCP_INSTALL_ROOT", "").strip()
        if install_root_value:
            install_root = Path(install_root_value).expanduser().resolve()
            roots.insert(1, install_root / "current" / "contracts" / "metric-catalog")
        for catalog_root in roots:
            matches = sorted(catalog_root.glob("catalog-*.json"))
            if matches:
                return matches[-1]
        raise ToolError(
            "METRIC_CATALOG_UNAVAILABLE",
            "Metric Catalog v1 缺失。",
            details={"searched": [str(path) for path in roots]},
        )

    def _copy_catalog(self, analytics_root: Path) -> dict[str, Any]:
        source = self._catalog_path()
        try:
            catalog = json.loads(source.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ToolError("METRIC_CATALOG_UNAVAILABLE", "Metric Catalog v1 不是有效 JSON。") from exc
        if not isinstance(catalog, dict):
            raise ToolError("METRIC_CATALOG_UNAVAILABLE", "Metric Catalog v1 必须是对象。")
        destination = analytics_root / "metric-catalog" / source.name
        if not destination.exists():
            shutil.copyfile(source, destination)
        if _sha_file(destination) != _sha_file(source):
            raise ToolError("METRIC_CATALOG_HASH_MISMATCH", "频道指标目录副本哈希不一致。")
        return {"path": str(destination), "sha256": _sha_file(destination), "version": catalog.get("catalogVersion")}

    @staticmethod
    def _db_path(analytics_root: Path) -> Path:
        return analytics_root / "data-center-v1.sqlite3"

    def _connect(self, analytics_root: Path, *, create: bool) -> sqlite3.Connection | None:
        path = self._db_path(analytics_root)
        if not path.is_file() and not create:
            return None
        if create:
            analytics_root.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(path)
        connection.row_factory = sqlite3.Row
        if create:
            connection.executescript(
                """
                PRAGMA foreign_keys = ON;
                CREATE TABLE IF NOT EXISTS videos (
                    video_id TEXT PRIMARY KEY,
                    channel_profile_id TEXT NOT NULL,
                    project_id TEXT NOT NULL,
                    namespace TEXT NOT NULL,
                    receipt_id TEXT NOT NULL,
                    receipt_hash TEXT NOT NULL,
                    published_at TEXT NOT NULL,
                    registered_at TEXT NOT NULL,
                    registration_path TEXT NOT NULL,
                    metadata_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS tasks (
                    video_id TEXT NOT NULL,
                    checkpoint TEXT NOT NULL,
                    due_at TEXT NOT NULL,
                    status TEXT NOT NULL,
                    last_snapshot_id TEXT,
                    attempts INTEGER NOT NULL DEFAULT 0,
                    PRIMARY KEY(video_id, checkpoint),
                    FOREIGN KEY(video_id) REFERENCES videos(video_id)
                );
                CREATE TABLE IF NOT EXISTS snapshots (
                    snapshot_id TEXT PRIMARY KEY,
                    video_id TEXT NOT NULL,
                    checkpoint TEXT NOT NULL,
                    version_number INTEGER NOT NULL,
                    result_hash TEXT NOT NULL,
                    content_hash TEXT NOT NULL,
                    completeness TEXT NOT NULL,
                    effective_status TEXT NOT NULL,
                    path TEXT NOT NULL,
                    collected_at TEXT NOT NULL,
                    data_cutoff TEXT NOT NULL,
                    UNIQUE(video_id, checkpoint, result_hash),
                    FOREIGN KEY(video_id) REFERENCES videos(video_id)
                );
                CREATE TABLE IF NOT EXISTS reports (
                    report_id TEXT PRIMARY KEY,
                    video_id TEXT NOT NULL,
                    checkpoint TEXT NOT NULL,
                    version_number INTEGER NOT NULL,
                    snapshot_id TEXT NOT NULL,
                    source_hash TEXT NOT NULL,
                    status TEXT NOT NULL,
                    effective_status TEXT NOT NULL,
                    video_path TEXT NOT NULL,
                    channel_path TEXT NOT NULL,
                    supersedes TEXT,
                    UNIQUE(video_id, checkpoint, source_hash),
                    FOREIGN KEY(video_id) REFERENCES videos(video_id)
                );
                CREATE TABLE IF NOT EXISTS recommendations (
                    recommendation_id TEXT PRIMARY KEY,
                    video_id TEXT NOT NULL,
                    report_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    path TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(video_id) REFERENCES videos(video_id)
                );
                """
            )
            connection.commit()
        return connection

    @staticmethod
    def _validate_hashed_document(document: dict[str, Any], *, expected_type: str | None = None) -> None:
        envelope = {"schemaVersion", "contractType", "id", "version", "createdAt", "hashAlgorithm", "hashRule", "contentHash", "upstream"}
        if not envelope.issubset(document) or document.get("hashAlgorithm") != "SHA-256" or document.get("hashRule") != "canonical-json-v1":
            raise ToolError("DATA_UPSTREAM_CONTRACT_INVALID", "输入契约缺少完整 canonical-json-v1 envelope。")
        if not isinstance(document.get("id"), str) or not isinstance(document.get("version"), str) or not isinstance(document.get("upstream"), list):
            raise ToolError("DATA_UPSTREAM_CONTRACT_INVALID", "输入契约 ID、版本或上游引用无效。")
        if expected_type and document.get("contractType") != expected_type:
            raise ToolError("DATA_UPSTREAM_TYPE_MISMATCH", "上游契约类型不匹配。", details={"expected": expected_type})
        content_hash = document.get("contentHash")
        if not isinstance(content_hash, str) or not HEX64.fullmatch(content_hash) or canonical_hash(document) != content_hash:
            raise ToolError("DATA_UPSTREAM_HASH_INVALID", "输入契约的 canonical-json-v1 SHA-256 无效。")

    @staticmethod
    def _publisher_receipt_hash(receipt: dict[str, Any]) -> str:
        seed = dict(receipt)
        seed["receipt_sha256"] = ""
        body = json.dumps(seed, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(body).hexdigest()

    def _normalize_publisher_readback_receipt(
        self,
        receipt: dict[str, Any],
        *,
        channel_profile_id: str,
        documents: dict[str, dict[str, Any]],
    ) -> tuple[dict[str, Any], str, str, datetime]:
        required = {
            "schema_version",
            "receipt_id",
            "publish_intent_id",
            "project_id",
            "target_channel",
            "remote_video",
            "metadata",
            "post_processing",
            "upload",
            "source_lock",
            "evidence_mode",
            "publication_valid",
            "created_at",
            "receipt_sha256",
        }
        if not required.issubset(receipt):
            raise ToolError("PUBLICATION_RECEIPT_INVALID", "发布中心 API 回读回执缺少必填字段。")
        claimed_hash = receipt.get("receipt_sha256")
        if (
            receipt.get("schema_version") != "1.0"
            or receipt.get("evidence_mode") != "publisher-api-readback"
            or receipt.get("publication_valid") is not True
            or not isinstance(claimed_hash, str)
            or not HEX64.fullmatch(claimed_hash)
            or self._publisher_receipt_hash(receipt) != claimed_hash
        ):
            raise ToolError("PUBLICATION_RECEIPT_INVALID", "发布中心 API 回读回执版本、证据模式或完整性无效。")
        if receipt.get("syntheticFixture") is not None or receipt.get("synthetic") is not None:
            raise ToolError("SYNTHETIC_RECEIPT_FORBIDDEN", "标记为 synthetic 的回执不得进入正式命名空间。")

        target = receipt.get("target_channel")
        remote = receipt.get("remote_video")
        metadata = receipt.get("metadata")
        post = receipt.get("post_processing")
        upload = receipt.get("upload")
        if not all(isinstance(value, dict) for value in (target, remote, metadata, post, upload)):
            raise ToolError("PUBLICATION_RECEIPT_INVALID", "发布中心 API 回读回执的远端证据结构无效。")
        if target.get("channel_profile_id") != channel_profile_id:
            raise ToolError("DATA_CROSS_CHANNEL_FORBIDDEN", "发布回执属于其他频道。")
        video_id = remote.get("video_id")
        if not isinstance(video_id, str) or not REAL_VIDEO_ID.fullmatch(video_id) or FAKE_MARKERS.search(video_id):
            raise ToolError("SYNTHETIC_VIDEO_ID_FORBIDDEN", "fake/synthetic video ID 不得进入正式命名空间。")
        if remote.get("url") not in {f"https://youtu.be/{video_id}", f"https://www.youtube.com/watch?v={video_id}"}:
            raise ToolError("PUBLICATION_RECEIPT_INVALID", "发布回执 URL 与 youtube_video_id 不一致。")

        production = documents["production"]
        publishing = documents["publishing"]
        intent = documents["publishIntent"]
        project_id = receipt.get("project_id")
        if not isinstance(project_id, str) or not project_id:
            raise ToolError("PUBLICATION_RECEIPT_INVALID", "发布回执缺少 projectId。")
        if intent.get("id") != receipt.get("publish_intent_id"):
            raise ToolError("PUBLICATION_RECEIPT_HASH_BINDING_INVALID", "发布回执与所提供的 Publish Intent ID 不一致。")
        if (production.get("finalVideo") or {}).get("sha256") != metadata.get("video_sha256"):
            raise ToolError("PUBLICATION_RECEIPT_HASH_BINDING_INVALID", "发布回执没有绑定所提供制作结果的最终视频。")
        thumbnail_asset = ((publishing.get("thumbnail") or {}).get("asset") or {})
        if thumbnail_asset.get("sha256") != metadata.get("thumbnail_sha256"):
            raise ToolError("PUBLICATION_RECEIPT_HASH_BINDING_INVALID", "发布回执没有绑定所提供发布素材的封面。")
        production_ref = intent.get("productionResultRef") or {}
        publishing_ref = intent.get("publishingAssetRef") or {}
        if (
            production_ref.get("targetId") != production.get("id")
            or production_ref.get("targetVersion") != production.get("version")
            or production_ref.get("targetHash") != production.get("contentHash")
            or publishing_ref.get("targetId") != publishing.get("id")
            or publishing_ref.get("targetVersion") != publishing.get("version")
            or publishing_ref.get("targetHash") != publishing.get("contentHash")
        ):
            raise ToolError("PUBLICATION_RECEIPT_HASH_BINDING_INVALID", "Publish Intent 没有绑定所提供的制作结果与发布素材。")

        status_maps = {
            "thumbnail": {"COMPLETED": "COMPLETE", "MANUAL_REQUIRED": "MANUAL_REQUIRED", "FAILED": "FAILED"},
            "captions": {"COMPLETED": "COMPLETE", "NOT_REQUESTED": "NOT_REQUESTED", "FAILED": "FAILED"},
            "processing": {"SUCCEEDED": "COMPLETE", "PROCESSING": "PROCESSING", "FAILED": "FAILED"},
            "visibility": {
                "PRIVATE": "UPLOADED_PRIVATE",
                "UNLISTED": "UPLOADED_UNLISTED",
                "SCHEDULED": "SCHEDULED",
                "PUBLIC": "PUBLISHED",
            },
        }
        source_statuses = {
            "thumbnail": post.get("thumbnail_status"),
            "captions": post.get("caption_status"),
            "processing": post.get("processing_status"),
            "visibility": post.get("visibility_status"),
        }
        try:
            remote_state = {key: status_maps[key][str(value).upper()] for key, value in source_statuses.items()}
        except KeyError as exc:
            raise ToolError("PUBLICATION_RECEIPT_INVALID", "发布回执包含无法归一化的远端状态。") from exc
        uploaded_at = _parse_time(upload.get("completed_at"), "upload.completed_at")
        intent_ref = {
            "targetContractType": "publish-intent",
            "targetId": intent.get("id"),
            "targetVersion": intent.get("version"),
            "targetSchemaVersion": intent.get("schemaVersion"),
            "targetHash": intent.get("contentHash"),
        }
        normalized = with_hash(
            {
                "schemaVersion": "1.0.0",
                "contractType": "publication-receipt",
                "id": str(receipt.get("receipt_id")),
                "version": "1.0.0",
                "createdAt": str(receipt.get("created_at")),
                "hashAlgorithm": "SHA-256",
                "hashRule": "canonical-json-v1",
                "upstream": [intent_ref],
                "receiptId": str(receipt.get("receipt_id")),
                "publishIntentRef": intent_ref,
                "projectId": project_id,
                "channelProfileId": channel_profile_id,
                "status": "RECEIPT_COMPLETE",
                "youtubeVideoId": video_id,
                "youtubeUrl": f"https://www.youtube.com/watch?v={video_id}",
                "targetChannel": {
                    "publisherProfileId": target.get("publisher_profile_id"),
                    "channelSerial": target.get("channel_serial"),
                    "youtubeChannelId": target.get("youtube_channel_id"),
                },
                "uploadedAt": _iso(uploaded_at),
                "remoteState": remote_state,
            }
        )
        self._validate_hashed_document(normalized, expected_type="publication-receipt")
        return normalized, video_id, project_id, uploaded_at

    def _formal_registration(self, args: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]], str, str, datetime]:
        receipt_path_value = args.get("publicationReceiptPath")
        if not isinstance(receipt_path_value, str) or not receipt_path_value:
            raise ToolError("WAITING_FOR_PUBLICATION_RECEIPT", "尚无真实 Publication Receipt v1，不能注册正式视频。")
        channel_profile_id = args["channelProfileId"]
        receipt_source = _read_json(Path(receipt_path_value).resolve())
        canonical_receipt = receipt_source.get("contractType") == "publication-receipt"
        if canonical_receipt:
            self._validate_hashed_document(receipt_source, expected_type="publication-receipt")
            if receipt_source.get("syntheticFixture") is not None or receipt_source.get("synthetic") is not None:
                raise ToolError("SYNTHETIC_RECEIPT_FORBIDDEN", "标记为 synthetic 的回执不得进入正式命名空间。")
            receipt_required = {
                "receiptId",
                "publishIntentRef",
                "projectId",
                "channelProfileId",
                "status",
                "youtubeVideoId",
                "youtubeUrl",
                "targetChannel",
                "uploadedAt",
                "remoteState",
            }
            if not receipt_required.issubset(receipt_source):
                raise ToolError("PUBLICATION_RECEIPT_INVALID", "Publication Receipt v1 缺少必填字段。")
            if receipt_source.get("schemaVersion") != "1.0.0" or receipt_source.get("status") != "RECEIPT_COMPLETE":
                raise ToolError("PUBLICATION_RECEIPT_INVALID", "正式注册只接受完成且版本为 v1 的发布回执。")
            if receipt_source.get("channelProfileId") != channel_profile_id:
                raise ToolError("DATA_CROSS_CHANNEL_FORBIDDEN", "发布回执属于其他频道。")
            video_id = receipt_source.get("youtubeVideoId")
            if not isinstance(video_id, str) or not REAL_VIDEO_ID.fullmatch(video_id) or FAKE_MARKERS.search(video_id):
                raise ToolError("SYNTHETIC_VIDEO_ID_FORBIDDEN", "fake/synthetic video ID 不得进入正式命名空间。")
            if receipt_source.get("youtubeUrl") != f"https://www.youtube.com/watch?v={video_id}":
                raise ToolError("PUBLICATION_RECEIPT_INVALID", "回执 URL 与 youtube_video_id 不一致。")
            target = receipt_source.get("targetChannel")
            if not isinstance(target, dict) or not isinstance(target.get("youtubeChannelId"), str):
                raise ToolError("PUBLICATION_RECEIPT_INVALID", "回执缺少目标频道身份。")
            remote_state = receipt_source.get("remoteState")
            if not isinstance(remote_state, dict) or not {"thumbnail", "captions", "processing", "visibility"}.issubset(remote_state):
                raise ToolError("PUBLICATION_RECEIPT_INVALID", "回执缺少可核验的远端状态。")

        paths = args.get("upstreamDocuments")
        if not isinstance(paths, dict) or set(paths) != set(UPSTREAM_TYPES):
            raise ToolError("DATA_UPSTREAM_CHAIN_REQUIRED", "正式注册必须提供 Topic/Manuscript/Publishing/Production/Publish Intent 五份哈希契约。")
        upstream: list[dict[str, Any]] = []
        documents: dict[str, dict[str, Any]] = {}
        for key, contract_type in UPSTREAM_TYPES.items():
            value = paths.get(key)
            if not isinstance(value, str) or not value:
                raise ToolError("DATA_UPSTREAM_CHAIN_REQUIRED", f"缺少 {key} 契约路径。")
            document = _read_json(Path(value).resolve())
            self._validate_hashed_document(document, expected_type=contract_type)
            documents[key] = document
            upstream.append(
                {
                    "role": key,
                    "contractType": contract_type,
                    "id": document.get("id"),
                    "version": document.get("version"),
                    "schemaVersion": document.get("schemaVersion"),
                    "sha256": document.get("contentHash"),
                    "sourcePath": str(Path(value).resolve()),
                }
            )
        if canonical_receipt:
            receipt = receipt_source
            project_id = receipt.get("projectId")
            if not isinstance(project_id, str) or not project_id:
                raise ToolError("PUBLICATION_RECEIPT_INVALID", "回执缺少 projectId。")
            published_at = _parse_time(receipt.get("uploadedAt"), "uploadedAt")
        else:
            receipt, video_id, project_id, published_at = self._normalize_publisher_readback_receipt(
                receipt_source,
                channel_profile_id=channel_profile_id,
                documents=documents,
            )
        for document in documents.values():
            if document.get("projectId") not in {None, project_id}:
                raise ToolError("DATA_PROJECT_MISMATCH", "上游项目 ID 与发布回执不一致。")
            if document.get("channelProfileId") not in {None, channel_profile_id}:
                raise ToolError("DATA_CROSS_CHANNEL_FORBIDDEN", "上游契约属于其他频道。")
        intent = documents["publishIntent"]
        receipt_ref = receipt.get("publishIntentRef") or {}
        if (
            receipt_ref.get("targetId") != intent.get("id")
            or receipt_ref.get("targetVersion") != intent.get("version")
            or receipt_ref.get("targetHash") != intent.get("contentHash")
        ):
            raise ToolError("PUBLICATION_RECEIPT_HASH_BINDING_INVALID", "发布回执没有哈希绑定所提供的 Publish Intent。")
        return receipt, upstream, video_id, project_id, published_at

    def _synthetic_registration(self, args: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]], str, str, datetime]:
        fixture = args.get("syntheticRegistration")
        if not isinstance(fixture, dict):
            raise ToolError("SYNTHETIC_REGISTRATION_REQUIRED", "syntheticFixture=true 时必须提供隔离合成注册记录。")
        video_id = fixture.get("syntheticVideoId")
        if not isinstance(video_id, str) or not video_id.startswith("synthetic-") or not SAFE_COMPONENT.fullmatch(video_id):
            raise ToolError("SYNTHETIC_VIDEO_ID_INVALID", "合成 video ID 必须使用 synthetic- 前缀。")
        if fixture.get("channelProfileId") != args.get("channelProfileId"):
            raise ToolError("DATA_CROSS_CHANNEL_FORBIDDEN", "合成注册记录属于其他频道。")
        project_id = _component(fixture.get("projectId"), "projectId")
        published_at = _parse_time(fixture.get("publishedAt"), "publishedAt")
        bindings = fixture.get("upstreamBindings")
        if not isinstance(bindings, list) or {item.get("role") for item in bindings if isinstance(item, dict)} != set(UPSTREAM_TYPES):
            raise ToolError("DATA_UPSTREAM_CHAIN_REQUIRED", "合成注册也必须绑定五类上游版本和哈希。")
        for item in bindings:
            if not isinstance(item.get("sha256"), str) or not HEX64.fullmatch(item["sha256"]):
                raise ToolError("DATA_UPSTREAM_HASH_INVALID", "合成上游绑定必须使用明确 fixture SHA-256。")
        fixture_receipt = {
            "receiptId": _component(fixture.get("receiptId", f"synthetic-receipt-{_sha_value(fixture)[:12]}"), "receiptId"),
            "contentHash": _sha_value({"syntheticFixture": True, **fixture}),
            "syntheticFixture": True,
            "channelProfileId": args["channelProfileId"],
        }
        return fixture_receipt, bindings, video_id, project_id, published_at

    def register_video(self, arguments: dict[str, Any]) -> dict[str, Any]:
        if contains_sensitive_material(arguments):
            raise ToolError("DATA_SENSITIVE_MATERIAL_FORBIDDEN", "数据中心不接收 OAuth Token、密钥或凭据。")
        channel_profile_id = _component(arguments.get("channelProfileId"), "channelProfileId")
        synthetic = arguments.get("syntheticFixture") is True
        if not synthetic and not arguments.get("publicationReceiptPath"):
            return {
                "status": "WAITING_FOR_PUBLICATION_RECEIPT",
                "registered": False,
                "nextStep": "真实发布完成后提供哈希有效的 Publication Receipt v1 与五类上游契约。",
            }
        if synthetic:
            receipt, upstream, video_id, project_id, published_at = self._synthetic_registration(arguments)
        else:
            receipt, upstream, video_id, project_id, published_at = self._formal_registration(arguments)
        analytics_root = self._analytics_root(channel_profile_id, synthetic=synthetic, create=True)
        catalog = self._copy_catalog(analytics_root)
        connection = self._connect(analytics_root, create=True)
        assert connection is not None
        namespace = "synthetic-fixture" if synthetic else "formal"
        metadata = arguments.get("videoMetadata") if isinstance(arguments.get("videoMetadata"), dict) else {}
        registration = with_hash(
            {
                "schemaVersion": "1.0.0",
                "contractType": "video-registration",
                "id": f"vr_{_sha_value([namespace, channel_profile_id, video_id])[:24]}",
                "version": "1.0.0",
                "createdAt": utc_now(),
                "hashAlgorithm": "SHA-256",
                "hashRule": "canonical-json-v1",
                "upstream": [],
                "namespace": namespace,
                "syntheticFixture": synthetic,
                "channelProfileId": channel_profile_id,
                "projectId": project_id,
                "youtubeVideoId": None if synthetic else video_id,
                "syntheticVideoId": video_id if synthetic else None,
                "publicationReceipt": {
                    "receiptId": receipt.get("receiptId"),
                    "sha256": receipt.get("contentHash"),
                    "syntheticFixture": synthetic,
                },
                "publishedAt": _iso(published_at),
                "upstreamBindings": upstream,
                "metricCatalog": catalog,
                "videoMetadata": metadata,
            }
        )
        registration_path = analytics_root / "baselines" / video_id / "registration-v001.json"
        receipt_filename = "synthetic-receipt-v001.json" if synthetic else "publication-receipt-v001.json"
        normalized_receipt_path = analytics_root / "baselines" / video_id / receipt_filename
        existing = connection.execute("SELECT * FROM videos WHERE video_id = ?", (video_id,)).fetchone()
        if existing:
            if existing["receipt_hash"] != receipt.get("contentHash") or existing["project_id"] != project_id:
                connection.close()
                raise ToolError("VIDEO_REGISTRATION_CONFLICT", "同一视频 ID 已绑定不同回执或项目。")
            connection.close()
            return {
                "status": "VIDEO_REGISTERED",
                "registered": True,
                "idempotent": True,
                "videoId": video_id,
                "namespace": namespace,
                "registrationPath": existing["registration_path"],
                "publicationReceiptPath": str(normalized_receipt_path),
            }
        _write_json(normalized_receipt_path, receipt)
        _write_json(registration_path, registration)
        with connection:
            connection.execute(
                "INSERT INTO videos VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    video_id,
                    channel_profile_id,
                    project_id,
                    namespace,
                    receipt.get("receiptId"),
                    receipt.get("contentHash"),
                    _iso(published_at),
                    utc_now(),
                    str(registration_path),
                    json.dumps(metadata, ensure_ascii=False),
                ),
            )
            for checkpoint, offset in CHECKPOINTS.items():
                connection.execute(
                    "INSERT INTO tasks(video_id, checkpoint, due_at, status) VALUES (?, ?, ?, ?)",
                    (video_id, checkpoint, _iso(published_at + offset), "COLLECTION_SCHEDULED"),
                )
        connection.close()
        return {
            "status": "VIDEO_REGISTERED",
            "registered": True,
            "idempotent": False,
            "videoId": video_id,
            "namespace": namespace,
            "registrationPath": str(registration_path),
            "registrationHash": registration["contentHash"],
            "publicationReceiptPath": str(normalized_receipt_path),
            "publicationReceiptHash": receipt.get("contentHash"),
            "schedule": {checkpoint: _iso(published_at + offset) for checkpoint, offset in CHECKPOINTS.items()},
        }

    def _load_video(self, analytics_root: Path, video_id: str) -> tuple[sqlite3.Connection, sqlite3.Row]:
        connection = self._connect(analytics_root, create=False)
        if connection is None:
            raise ToolError("VIDEO_NOT_REGISTERED", "当前频道没有注册该视频。")
        row = connection.execute("SELECT * FROM videos WHERE video_id = ?", (video_id,)).fetchone()
        if row is None:
            connection.close()
            raise ToolError("VIDEO_NOT_REGISTERED", "当前频道没有注册该视频。")
        return connection, row

    @staticmethod
    def _validate_source_binding(
        payload: dict[str, Any],
        *,
        channel_profile_id: str,
        video_id: str,
        project_id: str,
        synthetic: bool,
        source_name: str,
    ) -> None:
        binding = payload.get("binding")
        if not isinstance(binding, dict):
            raise ToolError("DATA_SOURCE_BINDING_REQUIRED", f"{source_name} 数据源缺少频道／视频绑定。")
        if binding.get("channelProfileId") != channel_profile_id or binding.get("videoId") != video_id:
            raise ToolError("DATA_CROSS_CHANNEL_FORBIDDEN", f"{source_name} 数据源不属于当前频道和视频。")
        if source_name == "system" and binding.get("projectId") != project_id:
            raise ToolError("DATA_PROJECT_MISMATCH", "system 数据源不属于当前项目。")
        if payload.get("syntheticFixture") is not synthetic:
            raise ToolError("DATA_NAMESPACE_MISMATCH", f"{source_name} 数据源的 syntheticFixture 与注册命名空间不一致。")

    @staticmethod
    def _public_metrics(payload: dict[str, Any], *, video_id: str) -> list[dict[str, Any]]:
        if payload.get("factLevel") not in {None, "PUBLIC_API_FACT"}:
            raise ToolError("FACT_LEVEL_SOURCE_MISMATCH", "公开 Data API 响应只能产生 PUBLIC_API_FACT。")
        response = payload.get("response")
        if not isinstance(response, dict) or contains_sensitive_material(response):
            raise ToolError("PUBLIC_DATA_RESPONSE_INVALID", "公开数据导入必须提供安全的录制响应。")
        items = response.get("items")
        if not isinstance(items, list) or not items or not isinstance(items[0], dict):
            raise ToolError("PUBLIC_DATA_RESPONSE_INVALID", "公开视频响应缺少 items[0]。")
        if items[0].get("id") != video_id:
            raise ToolError("PUBLIC_DATA_VIDEO_MISMATCH", "公开响应的视频 ID 与注册视频不一致。")
        statistics = items[0].get("statistics")
        if not isinstance(statistics, dict):
            raise ToolError("PUBLIC_DATA_RESPONSE_INVALID", "公开视频响应缺少 statistics。")
        forbidden = {"impressions", "impressionsCtr", "audienceWatchRatio", "trafficSource", "device", "demographics"}
        if forbidden.intersection(statistics):
            raise ToolError("PUBLIC_METRIC_OWNER_MASQUERADE", "公开响应不得携带 CTR、留存、流量、设备或人口 Studio 指标。")
        result: list[dict[str, Any]] = []
        for official, (metric_id, unit) in PUBLIC_METRICS.items():
            raw = statistics.get(official)
            if raw is None:
                result.append(_metric_entry(metric_id, value=None, unit=unit, fact_level="UNKNOWN", state="MISSING", source="youtube-data-api-v3-recorded", reason="field_missing"))
                continue
            try:
                value = int(raw)
            except (TypeError, ValueError) as exc:
                raise ToolError("PUBLIC_DATA_RESPONSE_INVALID", f"{official} 不是有效非负整数。") from exc
            if value < 0:
                raise ToolError("PUBLIC_DATA_RESPONSE_INVALID", f"{official} 不能为负数。")
            result.append(_metric_entry(metric_id, value=value, unit=unit, fact_level="PUBLIC_API_FACT", state="ZERO" if value == 0 else "PRESENT", source="youtube-data-api-v3-recorded"))
        return result

    @staticmethod
    def _owner_metrics(payload: dict[str, Any], *, synthetic: bool) -> list[dict[str, Any]]:
        if not synthetic:
            raise ToolError("AUTH_REQUIRED", "频道所有者 Analytics 尚未获得独立只读授权。")
        if payload.get("syntheticFixture") is not True:
            raise ToolError("OWNER_SYNTHETIC_MARKER_REQUIRED", "合成所有者指标必须显式 syntheticFixture=true。")
        if payload.get("factLevel") not in {None, "OWNER_ANALYTICS_FACT"}:
            raise ToolError("FACT_LEVEL_SOURCE_MISMATCH", "owner analytics 响应只能产生 OWNER_ANALYTICS_FACT 或 UNKNOWN。")
        records = payload.get("records")
        if not isinstance(records, list):
            raise ToolError("OWNER_ANALYTICS_RESPONSE_INVALID", "合成 owner Analytics 必须提供 records。")
        result: list[dict[str, Any]] = []
        for record in records:
            if not isinstance(record, dict):
                raise ToolError("OWNER_ANALYTICS_RESPONSE_INVALID", "owner Analytics record 必须是对象。")
            metric_id = record.get("metricId")
            if metric_id not in OWNER_METRICS:
                raise ToolError("OWNER_METRIC_NOT_CATALOGED", "owner Analytics 指标未列入 Metric Catalog v1。", details={"metricId": metric_id})
            state = record.get("valueState", "PRESENT")
            value = record.get("value")
            if isinstance(value, bool) or (value is not None and not isinstance(value, (int, float))):
                raise ToolError("OWNER_ANALYTICS_RESPONSE_INVALID", "owner Analytics 指标值必须是数字或 null。")
            result.append(
                _metric_entry(
                    metric_id,
                    value=value,
                    unit=str(record.get("unit") or "count"),
                    fact_level="OWNER_ANALYTICS_FACT",
                    state=state,
                    source="recorded-synthetic-owner-analytics",
                    dimensions=record.get("dimensions") if isinstance(record.get("dimensions"), dict) else {},
                    reason=record.get("reason"),
                )
            )
        return result

    @staticmethod
    def _system_metrics(payload: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
        if payload.get("factLevel") not in {None, "SYSTEM_FACT"}:
            raise ToolError("FACT_LEVEL_SOURCE_MISMATCH", "本地生产数据只能产生 SYSTEM_FACT。")
        records = payload.get("records", [])
        if not isinstance(records, list):
            raise ToolError("SYSTEM_DATA_INVALID", "system records 必须是数组。")
        result: list[dict[str, Any]] = []
        for record in records:
            if not isinstance(record, dict) or record.get("metricId") not in SYSTEM_METRICS:
                raise ToolError("SYSTEM_METRIC_NOT_CATALOGED", "系统指标必须存在于 Metric Catalog v1。")
            value = record.get("value")
            state = record.get("valueState", "PRESENT")
            result.append(
                _metric_entry(
                    record["metricId"],
                    value=value,
                    unit=str(record.get("unit") or "count"),
                    fact_level="SYSTEM_FACT",
                    state=state,
                    source="hash-bound-local-system",
                    dimensions=record.get("dimensions") if isinstance(record.get("dimensions"), dict) else {},
                    reason=record.get("reason"),
                )
            )
        timeline = payload.get("timelineMap")
        if timeline is not None and not isinstance(timeline, dict):
            raise ToolError("TIMELINE_MAP_INVALID", "timelineMap 必须是对象。")
        return result, timeline

    @staticmethod
    def _timeline_evidence(timeline: dict[str, Any] | None, metrics: list[dict[str, Any]], snapshot_id: str) -> dict[str, Any] | None:
        if timeline is None:
            return None
        duration = timeline.get("durationSeconds")
        segments = timeline.get("segments")
        if not isinstance(duration, (int, float)) or duration <= 0 or not isinstance(segments, list):
            raise ToolError("TIMELINE_MAP_INVALID", "timelineMap 缺少正数 durationSeconds 或 segments。")
        cards: list[dict[str, Any]] = []
        for metric in metrics:
            if metric["metricId"] not in {"youtube.analytics.audience_watch_ratio", "youtube.analytics.relative_retention_performance"}:
                continue
            ratio = metric.get("dimensions", {}).get("elapsedVideoTimeRatio")
            if not isinstance(ratio, (int, float)):
                continue
            seconds = float(ratio) * float(duration)
            matched = None
            for segment in segments:
                if not isinstance(segment, dict):
                    continue
                if isinstance(segment.get("startSeconds"), (int, float)) and isinstance(segment.get("endSeconds"), (int, float)) and segment["startSeconds"] <= seconds <= segment["endSeconds"]:
                    matched = segment
                    break
            cards.append(
                {
                    "factLevel": metric["factLevel"],
                    "metricId": metric["metricId"],
                    "elapsedVideoTimeRatio": ratio,
                    "elapsedSeconds": seconds,
                    "retentionValue": metric["value"],
                    "retentionValuePreservedAboveOne": isinstance(metric["value"], (int, float)) and metric["value"] > 1,
                    "matchedSegment": matched,
                    "reviewOnly": True,
                    "automaticRewrite": False,
                }
            )
        return {
            "schemaVersion": "1.0.0",
            "snapshotId": snapshot_id,
            "durationSeconds": duration,
            "cards": cards,
            "ratioClamped": False,
        }

    def collect(self, arguments: dict[str, Any]) -> dict[str, Any]:
        if contains_sensitive_material(arguments):
            raise ToolError("DATA_SENSITIVE_MATERIAL_FORBIDDEN", "数据中心不接收 OAuth Token、密钥或凭据。")
        channel_profile_id = _component(arguments.get("channelProfileId"), "channelProfileId")
        video_id = _component(arguments.get("videoId"), "videoId")
        checkpoint = arguments.get("checkpoint")
        if checkpoint not in CHECKPOINTS:
            raise ToolError("DATA_CHECKPOINT_INVALID", "checkpoint 必须是 T+24H、T+7D 或 T+28D。")
        synthetic = arguments.get("syntheticFixture") is True
        analytics_root = self._analytics_root(channel_profile_id, synthetic=synthetic, create=False)
        connection, video = self._load_video(analytics_root, video_id)
        expected_namespace = "synthetic-fixture" if synthetic else "formal"
        if video["namespace"] != expected_namespace:
            connection.close()
            raise ToolError("DATA_NAMESPACE_MISMATCH", "正式与 synthetic fixture 命名空间不可混用。")
        try:
            collected_at = _parse_time(arguments.get("collectedAt"), "collectedAt")
            data_cutoff = _parse_time(arguments.get("dataCutoff"), "dataCutoff")
            window_start = _parse_time(arguments.get("windowStart"), "windowStart")
            window_end = _parse_time(arguments.get("windowEnd"), "windowEnd")
        except ToolError:
            connection.close()
            raise
        if not window_start < window_end or data_cutoff > collected_at:
            connection.close()
            raise ToolError("DATA_WINDOW_INVALID", "窗口、截止时间或采集时间顺序无效。")
        task = connection.execute("SELECT * FROM tasks WHERE video_id = ? AND checkpoint = ?", (video_id, checkpoint)).fetchone()
        if task is None:
            connection.close()
            raise ToolError("DATA_TASK_NOT_FOUND", "采集任务不存在。")
        if collected_at < _parse_time(task["due_at"], "dueAt"):
            connection.close()
            return {"status": "COLLECTION_SCHEDULED", "dueAt": task["due_at"], "readOnly": True}

        sources = arguments.get("sources")
        if not isinstance(sources, dict) or not sources:
            connection.close()
            raise ToolError("DATA_SOURCE_REQUIRED", "至少提供一个 public、owner 或 system 数据源。")
        raw_bindings: list[dict[str, Any]] = []
        metrics: list[dict[str, Any]] = []
        timeline: dict[str, Any] | None = None
        owner_present = False
        delayed = False
        try:
            for source_name in ("public", "owner", "ownerAnalytics", "ownerReporting", "system"):
                payload = sources.get(source_name)
                if payload is None:
                    continue
                if not isinstance(payload, dict):
                    raise ToolError("DATA_SOURCE_INVALID", f"{source_name} 数据源必须是对象。")
                self._validate_source_binding(
                    payload,
                    channel_profile_id=channel_profile_id,
                    video_id=video_id,
                    project_id=video["project_id"],
                    synthetic=synthetic,
                    source_name="system" if source_name == "system" else source_name,
                )
                raw_hash = _sha_value(payload)
                raw_subdir = {
                    "public": "public-data-api",
                    "owner": "analytics-query",
                    "ownerAnalytics": "analytics-query",
                    "ownerReporting": "reporting-bulk",
                    "system": "system",
                }[source_name]
                raw_path = analytics_root / "raw" / raw_subdir / f"sha256-{raw_hash}.json"
                was_existing = raw_path.exists()
                if not raw_path.exists():
                    _write_json(raw_path, {"syntheticFixture": synthetic, "source": source_name, "payload": payload})
                raw_bindings.append({"source": source_name, "path": str(raw_path), "sha256": raw_hash, "deduplicated": was_existing})
                if source_name == "public":
                    metrics.extend(self._public_metrics(payload, video_id=video_id))
                elif source_name in {"owner", "ownerAnalytics", "ownerReporting"}:
                    owner_present = True
                    metrics.extend(self._owner_metrics(payload, synthetic=synthetic))
                else:
                    system_metrics, system_timeline = self._system_metrics(payload)
                    metrics.extend(system_metrics)
                    timeline = system_timeline or timeline
        except (ToolError, OSError, TypeError, ValueError):
            connection.close()
            raise
        present_ids = {item["metricId"] for item in metrics}
        if not owner_present:
            for metric_id, unit in OWNER_UNKNOWN_DEFAULTS.items():
                if metric_id not in present_ids:
                    metrics.append(_metric_entry(metric_id, value=None, unit=unit, fact_level="UNKNOWN", state="MISSING", source="owner-analytics-not-authorized", reason="AUTH_REQUIRED"))
            for dimension in OWNER_UNKNOWN_DIMENSIONS:
                metrics.append(
                    _metric_entry(
                        "youtube.analytics.views",
                        value=None,
                        unit="count",
                        fact_level="UNKNOWN",
                        state="MISSING",
                        source="owner-analytics-not-authorized",
                        dimensions={"requiredDimension": dimension},
                        reason="AUTH_REQUIRED",
                    )
                )
        delayed = any(item["valueState"] == "DELAYED" for item in metrics)
        result_hash = _sha_value({"checkpoint": checkpoint, "metrics": metrics, "window": [_iso(window_start), _iso(window_end)], "dataCutoff": _iso(data_cutoff)})
        existing = connection.execute(
            "SELECT * FROM snapshots WHERE video_id = ? AND checkpoint = ? AND result_hash = ?",
            (video_id, checkpoint, result_hash),
        ).fetchone()
        if existing:
            connection.close()
            return {
                "status": "SNAPSHOT_READY",
                "idempotent": True,
                "snapshotId": existing["snapshot_id"],
                "snapshotPath": existing["path"],
                "contentHash": existing["content_hash"],
            }
        previous = connection.execute(
            "SELECT * FROM snapshots WHERE video_id = ? AND checkpoint = ? ORDER BY version_number DESC LIMIT 1",
            (video_id, checkpoint),
        ).fetchone()
        version_number = 1 if previous is None else int(previous["version_number"]) + 1
        requested = arguments.get("completeness", "provisional" if checkpoint == "T+24H" else "complete")
        if requested not in {"provisional", "complete"}:
            connection.close()
            raise ToolError("DATA_COMPLETENESS_INVALID", "采集输入 completeness 只能是 provisional 或 complete。")
        completeness = "revised" if previous is not None else ("provisional" if delayed else requested)
        snapshot_id = f"as_{_sha_value([channel_profile_id, video_id, checkpoint, result_hash])[:24]}"
        receipt_ref = {
            "targetContractType": "publication-receipt",
            "targetId": video["receipt_id"],
            "targetVersion": "1.0.0",
            "targetSchemaVersion": "1.0.0",
            "targetHash": video["receipt_hash"],
        }
        manifest = with_hash(
            {
                "schemaVersion": ANALYTICS_SNAPSHOT_VERSION,
                "contractType": "analytics-snapshot",
                "id": snapshot_id,
                "version": f"1.0.{version_number - 1}",
                "createdAt": _iso(collected_at),
                "hashAlgorithm": "SHA-256",
                "hashRule": "canonical-json-v1",
                "upstream": [receipt_ref],
                "snapshotId": snapshot_id,
                "publicationReceiptRef": receipt_ref,
                "channelProfileId": channel_profile_id,
                "youtubeVideoId": video_id,
                "window": {"kind": checkpoint, "start": _iso(window_start), "end": _iso(window_end), "timezone": str(arguments.get("timezone") or "UTC")},
                "collectedAt": _iso(collected_at),
                "dataCutoff": _iso(data_cutoff),
                "completeness": completeness,
                "metrics": {
                    item["metricId"] + (f"#{index}" if sum(1 for candidate in metrics if candidate["metricId"] == item["metricId"]) > 1 else ""): {
                        "value": item["value"],
                        "unit": item["unit"],
                        "factLevel": item["factLevel"],
                        "source": item["source"],
                    }
                    for index, item in enumerate(metrics)
                },
                "syntheticFixture": synthetic,
            }
        )
        snapshot_root = analytics_root / "snapshots" / video_id / checkpoint.lower().replace("+", "plus") / f"v{version_number:03d}-{snapshot_id}"
        creating = snapshot_root.with_name(snapshot_root.name + ".creating")
        if creating.exists():
            shutil.rmtree(creating)
        creating.mkdir(parents=True)
        query_plan = {
            "schemaVersion": "1.0.0",
            "checkpoint": checkpoint,
            "triggerDueAt": task["due_at"],
            "triggerIsCheckpointNotOfficialWindow": True,
            "windowStart": _iso(window_start),
            "windowEnd": _iso(window_end),
            "dataCutoff": _iso(data_cutoff),
            "timezone": str(arguments.get("timezone") or "UTC"),
            "sources": [item["source"] for item in raw_bindings],
            "analyticsAuthorization": "SYNTHETIC_FIXTURE" if owner_present and synthetic else "AUTH_REQUIRED",
            "monetaryMetricsEnabled": False,
        }
        detailed_completeness = {
            "schemaVersion": "1.0.0",
            "status": completeness,
            "dataCutoff": _iso(data_cutoff),
            "ownerAnalyticsAvailable": owner_present,
            "ownerAnalyticsAuthorization": "SYNTHETIC_FIXTURE" if owner_present and synthetic else "AUTH_REQUIRED",
            "missing": [item["metricId"] for item in metrics if item["valueState"] == "MISSING"],
            "thresholdProtected": [item["metricId"] for item in metrics if item["valueState"] == "THRESHOLD_PROTECTED"],
            "delayed": [item["metricId"] for item in metrics if item["valueState"] == "DELAYED"],
            "zero": [item["metricId"] for item in metrics if item["valueState"] == "ZERO"],
        }
        catalog = self._copy_catalog(analytics_root)
        source_lock = {
            "schemaVersion": "1.0.0",
            "snapshotId": snapshot_id,
            "rawBindings": raw_bindings,
            "metricCatalog": catalog,
            "queryResultHash": result_hash,
            "originalDataAppendOnly": True,
            "syntheticFixture": synthetic,
        }
        for name, value in (
            ("manifest.json", manifest),
            ("query-plan.json", query_plan),
            ("raw-bindings.json", {"bindings": raw_bindings}),
            ("normalized-metrics.json", {"schemaVersion": "1.0.0", "snapshotId": snapshot_id, "metrics": metrics}),
            ("completeness.json", detailed_completeness),
            ("source-lock.json", source_lock),
        ):
            _write_json(creating / name, value)
        creating.replace(snapshot_root)
        normalized_path = analytics_root / "normalized" / video_id / f"{snapshot_id}.json"
        _write_json(normalized_path, {"snapshotId": snapshot_id, "resultHash": result_hash, "metrics": metrics})
        try:
            timeline_evidence = self._timeline_evidence(timeline, metrics, snapshot_id)
        except ToolError:
            connection.close()
            raise
        timeline_path = None
        if timeline_evidence is not None:
            timeline_path = analytics_root / "timeline-maps" / video_id / f"{snapshot_id}.json"
            _write_json(timeline_path, timeline_evidence)
        with connection:
            if previous is not None:
                connection.execute("UPDATE snapshots SET effective_status = 'superseded' WHERE snapshot_id = ?", (previous["snapshot_id"],))
            connection.execute(
                "INSERT INTO snapshots VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (snapshot_id, video_id, checkpoint, version_number, result_hash, manifest["contentHash"], completeness, completeness, str(snapshot_root), _iso(collected_at), _iso(data_cutoff)),
            )
            connection.execute(
                "UPDATE tasks SET status = 'SNAPSHOT_READY', last_snapshot_id = ?, attempts = attempts + 1 WHERE video_id = ? AND checkpoint = ?",
                (snapshot_id, video_id, checkpoint),
            )
        connection.close()
        return {
            "status": "SNAPSHOT_READY",
            "idempotent": False,
            "snapshotId": snapshot_id,
            "snapshotPath": str(snapshot_root),
            "contentHash": manifest["contentHash"],
            "completeness": completeness,
            "dataCutoff": _iso(data_cutoff),
            "timelineEvidencePath": str(timeline_path) if timeline_path else None,
        }

    @staticmethod
    def _baseline(metadata: dict[str, Any], candidates: Iterable[sqlite3.Row]) -> dict[str, Any]:
        rows = list(candidates)
        priorities = ["contentForm", "language", "durationBand", "topicLane", "publishTimeBand", "primaryTrafficSource"]
        ranked: list[dict[str, Any]] = []
        for row in rows:
            other = json.loads(row["metadata_json"])
            matches = [key for key in priorities if metadata.get(key) is not None and metadata.get(key) == other.get(key)]
            ranked.append({"videoId": row["video_id"], "matchedDimensions": matches, "matchCount": len(matches)})
        ranked.sort(key=lambda item: (-item["matchCount"], item["videoId"]))
        sample = [item for item in ranked if item["matchCount"] >= 3]
        if not sample:
            sample = ranked
        return {
            "priority": ["same_channel", "same_publication_age", *priorities],
            "sampleSize": len(sample),
            "confidence": "low" if len(sample) < 3 else "medium" if len(sample) < 10 else "high",
            "fallback": "same-channel-overall" if ranked and not any(item["matchCount"] >= 3 for item in ranked) else "none" if sample else "no-baseline",
            "comparables": sample,
            "universalCtrThresholdUsed": False,
        }

    @staticmethod
    def _report_markdown(report: dict[str, Any], *, channel: bool = False) -> str:
        title = "频道策略报告" if channel else "单视频表现报告"
        lines = [f"# {title}", "", f"- 状态：{report['status']}", f"- 数据截止：{report['dataCutoff']}", f"- 频道：{report['channelProfileId']}"]
        if not channel:
            lines.append(f"- 视频：{report['videoId']}")
        lines.extend(["", "## 已确认事实", ""])
        facts = report.get("facts", [])
        if facts:
            for item in facts:
                lines.append(f"- [{item['factLevel']}] {item['metricId']} = {item['value']} {item['unit']}（{item['valueState']}）")
        else:
            lines.append("- 当前没有可确认数值。")
        lines.extend(["", "## 未知与边界", ""])
        for item in report.get("unknown", []):
            lines.append(f"- [UNKNOWN] {item['metricId']}：{item.get('reason') or item['valueState']}")
        lines.extend(["", "## 推断与替代解释", ""])
        if report.get("inferences"):
            for item in report["inferences"]:
                lines.append(f"- [INFERENCE/{item['confidence']}] {item['statement']}；替代解释：{'；'.join(item['alternativeExplanations'])}")
        else:
            lines.append("- 当前证据不足，不生成因果推断。")
        lines.extend(["", "## 不要过度解读", ""])
        for item in report.get("doNotOverinterpret", []):
            lines.append(f"- {item}")
        return "\n".join(lines) + "\n"

    def _make_recommendation(
        self,
        *,
        analytics_root: Path,
        channel_profile_id: str,
        video_id: str,
        report_id: str,
        report_hash: str,
        checkpoint: str,
        facts: list[dict[str, Any]],
        unknown: list[dict[str, Any]],
        baseline: dict[str, Any],
        synthetic: bool,
    ) -> tuple[dict[str, Any], Path]:
        evidence_candidates = [item for item in facts if item["factLevel"] in {"PUBLIC_API_FACT", "OWNER_ANALYTICS_FACT", "SYSTEM_FACT"}]
        if not evidence_candidates:
            raise ToolError("RECOMMENDATION_EVIDENCE_REQUIRED", "建议卡必须绑定至少一条可验证事实。")
        evidence = [
            {
                "factLevel": item["factLevel"],
                "metricId": item["metricId"],
                "value": item["value"],
                "unit": item["unit"],
                "reportId": report_id,
            }
            for item in evidence_candidates[:3]
        ]
        owner_unknown = any(item["metricId"] in OWNER_UNKNOWN_DEFAULTS for item in unknown)
        principle = (
            "先补充同频道所有者只读 Analytics，再测试一个可比视频；不要仅凭公开播放量改写标题、封面或文稿。"
            if owner_unknown
            else "在一个同频道、同发布年龄且形态相近的新视频上小范围复测当前内容与包装组合。"
        )
        recommendation_id = f"rec_{_sha_value([report_id, principle])[:24]}"
        card = with_hash(
            {
                "schemaVersion": RECOMMENDATION_CARD_VERSION,
                "contractType": "recommendation-card",
                "id": recommendation_id,
                "version": "1.0.0",
                "createdAt": utc_now(),
                "hashAlgorithm": "SHA-256",
                "hashRule": "canonical-json-v1",
                "upstream": [],
                "recommendationId": recommendation_id,
                "channelProfileId": channel_profile_id,
                "videoId": video_id,
                "reportId": report_id,
                "reportHash": report_hash,
                "checkpoint": checkpoint,
                "status": "AWAITING_LEARNING_DECISION",
                "evidence": evidence,
                "interpretation": "当前证据只支持继续验证，不支持确定因果或长期规则。",
                "alternativeExplanations": ["分发与发布时间差异", "题材需求或外部事件", "当前样本量不足"],
                "sampleSize": max(1, int(baseline["sampleSize"])),
                "confidence": "low" if baseline["sampleSize"] < 3 else baseline["confidence"],
                "scope": {"channelProfileId": channel_profile_id, "projectOnly": True, "crossChannel": False},
                "action": {"kind": "test", "principle": principle, "automaticRewrite": False},
                "verificationCondition": "至少新增一个同频道、同发布年龄和形态相近的视频，并取得相同口径数据。",
                "falsificationCondition": "可比样本在相同方向上不重复，或 owner Analytics 显示相反结果。",
                "longTermWriteAllowed": False,
                "syntheticFixture": synthetic,
                "evidenceMode": "recorded-synthetic-fixture" if synthetic else "formal-channel-data",
            }
        )
        path = analytics_root / "recommendations" / f"{recommendation_id}.json"
        if not path.exists():
            _write_json(path, card)
        return card, path

    def generate_report(self, arguments: dict[str, Any]) -> dict[str, Any]:
        if contains_sensitive_material(arguments):
            raise ToolError("DATA_SENSITIVE_MATERIAL_FORBIDDEN", "数据中心不接收 OAuth Token、密钥或凭据。")
        channel_profile_id = _component(arguments.get("channelProfileId"), "channelProfileId")
        video_id = _component(arguments.get("videoId"), "videoId")
        checkpoint = arguments.get("checkpoint")
        if checkpoint not in CHECKPOINTS:
            raise ToolError("DATA_CHECKPOINT_INVALID", "报告 checkpoint 无效。")
        synthetic = arguments.get("syntheticFixture") is True
        analytics_root = self._analytics_root(channel_profile_id, synthetic=synthetic, create=False)
        connection, video = self._load_video(analytics_root, video_id)
        expected_namespace = "synthetic-fixture" if synthetic else "formal"
        if video["namespace"] != expected_namespace:
            connection.close()
            raise ToolError("DATA_NAMESPACE_MISMATCH", "正式与 synthetic fixture 命名空间不可混用。")
        snapshot = connection.execute(
            "SELECT * FROM snapshots WHERE video_id = ? AND checkpoint = ? AND effective_status != 'superseded' ORDER BY version_number DESC LIMIT 1",
            (video_id, checkpoint),
        ).fetchone()
        if snapshot is None:
            connection.close()
            raise ToolError("SNAPSHOT_REQUIRED", "生成报告前必须完成当前检查点的 Analytics Snapshot v1。")
        existing = connection.execute(
            "SELECT * FROM reports WHERE video_id = ? AND checkpoint = ? AND source_hash = ?",
            (video_id, checkpoint, snapshot["content_hash"]),
        ).fetchone()
        if existing:
            connection.close()
            return {
                "status": "REPORT_READY",
                "idempotent": True,
                "reportId": existing["report_id"],
                "videoReportPath": existing["video_path"],
                "channelReportPath": existing["channel_path"],
            }
        normalized = _read_json(Path(snapshot["path"]) / "normalized-metrics.json")
        metrics = normalized.get("metrics")
        if not isinstance(metrics, list):
            connection.close()
            raise ToolError("SNAPSHOT_INVALID", "标准化指标文件无效。")
        facts = [item for item in metrics if item.get("factLevel") != "UNKNOWN"]
        unknown = [item for item in metrics if item.get("factLevel") == "UNKNOWN"]
        previous_report = connection.execute(
            "SELECT * FROM reports WHERE video_id = ? AND checkpoint = ? ORDER BY version_number DESC LIMIT 1",
            (video_id, checkpoint),
        ).fetchone()
        version_number = 1 if previous_report is None else int(previous_report["version_number"]) + 1
        status = "revised" if previous_report is not None or snapshot["completeness"] == "revised" else snapshot["completeness"]
        if status not in REPORT_STATES:
            status = "provisional"
        other_videos = connection.execute(
            "SELECT * FROM videos WHERE video_id != ? AND channel_profile_id = ?",
            (video_id, channel_profile_id),
        ).fetchall()
        metadata = json.loads(video["metadata_json"])
        baseline = self._baseline(metadata, other_videos)
        baseline_path = analytics_root / "baselines" / video_id / f"{snapshot['snapshot_id']}-comparable.json"
        _write_json(baseline_path, baseline)
        public_only = not any(item.get("factLevel") == "OWNER_ANALYTICS_FACT" for item in facts)
        inferences: list[dict[str, Any]] = []
        if facts:
            inferences.append(
                {
                    "factLevel": "INFERENCE",
                    "statement": "现有数据可用于形成下一次小范围验证假设，但不足以证明单一因果。",
                    "factRefs": [item["metricId"] for item in facts[:3]],
                    "alternativeExplanations": ["分发差异", "样本量不足", "发布时间或外部事件"],
                    "confidence": "low" if baseline["sampleSize"] < 3 else baseline["confidence"],
                    "verificationAction": "在同频道、同发布年龄和相近形态的视频上复测。",
                }
            )
        report_id = f"vpr_{_sha_value([channel_profile_id, video_id, checkpoint, snapshot['content_hash']])[:24]}"
        report = with_hash(
            {
                "schemaVersion": VIDEO_REPORT_VERSION,
                "contractType": "video-performance-report",
                "id": report_id,
                "version": f"1.0.{version_number - 1}",
                "createdAt": utc_now(),
                "hashAlgorithm": "SHA-256",
                "hashRule": "canonical-json-v1",
                "upstream": [],
                "reportId": report_id,
                "channelProfileId": channel_profile_id,
                "videoId": video_id,
                "checkpoint": checkpoint,
                "status": status,
                "supersedes": previous_report["report_id"] if previous_report else None,
                "snapshotId": snapshot["snapshot_id"],
                "snapshotHash": snapshot["content_hash"],
                "dataCutoff": snapshot["data_cutoff"],
                "publicOnly": public_only,
                "syntheticFixture": synthetic,
                "evidenceMode": "recorded-synthetic-fixture" if synthetic else "formal-channel-data",
                "facts": facts,
                "unknown": unknown,
                "inferences": inferences,
                "baseline": baseline,
                "sampleInsufficient": baseline["sampleSize"] < 3,
                "doNotOverinterpret": [
                    "T+24/T+7/T+28 是采集触发检查点，不是精确官方数据窗口。",
                    "公开播放、点赞和评论不等于 CTR、留存、流量来源、设备、人口或订阅后台事实。",
                    "相关性与一次表现不能证明标题、封面或文稿导致结果。",
                ],
            }
        )
        channel_report_id = f"csr_{_sha_value([channel_profile_id, checkpoint, snapshot['content_hash']])[:24]}"
        channel_report = with_hash(
            {
                "schemaVersion": CHANNEL_REPORT_VERSION,
                "contractType": "channel-strategy-report",
                "id": channel_report_id,
                "version": f"1.0.{version_number - 1}",
                "createdAt": utc_now(),
                "hashAlgorithm": "SHA-256",
                "hashRule": "canonical-json-v1",
                "upstream": [],
                "reportId": channel_report_id,
                "channelProfileId": channel_profile_id,
                "checkpoint": checkpoint,
                "status": status,
                "dataCutoff": snapshot["data_cutoff"],
                "videoReportIds": [report_id],
                "facts": facts,
                "unknown": unknown,
                "inferences": inferences,
                "baseline": baseline,
                "channelIsolation": {"crossChannelRead": False, "profileId": channel_profile_id},
                "syntheticFixture": synthetic,
                "evidenceMode": "recorded-synthetic-fixture" if synthetic else "formal-channel-data",
                "doNotOverinterpret": report["doNotOverinterpret"],
            }
        )
        video_base = analytics_root / "reports" / "videos" / video_id / f"{checkpoint.lower().replace('+', 'plus')}-v{version_number:03d}"
        channel_base = analytics_root / "reports" / "channel" / f"{checkpoint.lower().replace('+', 'plus')}-{video_id}-v{version_number:03d}"
        video_json = video_base.with_suffix(".json")
        video_md = video_base.with_suffix(".md")
        channel_json = channel_base.with_suffix(".json")
        channel_md = channel_base.with_suffix(".md")
        _write_json(video_json, report)
        video_md.parent.mkdir(parents=True, exist_ok=True)
        video_md.write_text(self._report_markdown(report), encoding="utf-8")
        _write_json(channel_json, channel_report)
        channel_md.parent.mkdir(parents=True, exist_ok=True)
        channel_md.write_text(self._report_markdown(channel_report, channel=True), encoding="utf-8")
        recommendation, recommendation_path = self._make_recommendation(
            analytics_root=analytics_root,
            channel_profile_id=channel_profile_id,
            video_id=video_id,
            report_id=report_id,
            report_hash=report["contentHash"],
            checkpoint=checkpoint,
            facts=facts,
            unknown=unknown,
            baseline=baseline,
            synthetic=synthetic,
        )
        with connection:
            if previous_report is not None:
                connection.execute("UPDATE reports SET effective_status = 'superseded' WHERE report_id = ?", (previous_report["report_id"],))
            connection.execute(
                "INSERT INTO reports VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (report_id, video_id, checkpoint, version_number, snapshot["snapshot_id"], snapshot["content_hash"], status, status, str(video_json), str(channel_json), previous_report["report_id"] if previous_report else None),
            )
            connection.execute(
                "INSERT OR IGNORE INTO recommendations VALUES (?, ?, ?, ?, ?, ?)",
                (recommendation["recommendationId"], video_id, report_id, "AWAITING_LEARNING_DECISION", str(recommendation_path), utc_now()),
            )
            connection.execute("UPDATE tasks SET status = 'REPORT_READY' WHERE video_id = ? AND checkpoint = ?", (video_id, checkpoint))
        connection.close()
        return {
            "status": "REPORT_READY",
            "idempotent": False,
            "reportStatus": status,
            "reportId": report_id,
            "videoReportPath": str(video_json),
            "videoReportMarkdownPath": str(video_md),
            "videoReportHash": report["contentHash"],
            "channelReportPath": str(channel_json),
            "channelReportMarkdownPath": str(channel_md),
            "channelReportHash": channel_report["contentHash"],
            "recommendationPath": str(recommendation_path),
            "recommendationHash": recommendation["contentHash"],
            "learningStatus": "AWAITING_LEARNING_DECISION",
        }

    def list_recommendations(self, arguments: dict[str, Any]) -> dict[str, Any]:
        channel_profile_id = _component(arguments.get("channelProfileId"), "channelProfileId")
        synthetic = arguments.get("syntheticFixture") is True
        analytics_root = self._analytics_root(channel_profile_id, synthetic=synthetic, create=False)
        connection = self._connect(analytics_root, create=False)
        if connection is None:
            return {"status": "WAITING_FOR_PUBLICATION_RECEIPT", "recommendations": [], "readOnly": True}
        rows = connection.execute("SELECT * FROM recommendations ORDER BY created_at, recommendation_id").fetchall()
        result = [
            {
                "recommendationId": row["recommendation_id"],
                "videoId": row["video_id"],
                "reportId": row["report_id"],
                "status": row["status"],
                "path": row["path"],
            }
            for row in rows
        ]
        connection.close()
        return {"status": "OK", "recommendations": result, "readOnly": True}

    def learning_decision(self, arguments: dict[str, Any]) -> dict[str, Any]:
        if contains_sensitive_material(arguments):
            raise ToolError("DATA_SENSITIVE_MATERIAL_FORBIDDEN", "学习决定不接收凭据。")
        channel_profile_id = _component(arguments.get("channelProfileId"), "channelProfileId")
        recommendation_id = _component(arguments.get("recommendationId"), "recommendationId")
        decision = arguments.get("decision")
        if decision not in {"test_only", "channel_default", "must_avoid", "observe", "reject"}:
            raise ToolError("LEARNING_DECISION_INVALID", "学习决定无效。")
        if decision in {"channel_default", "must_avoid"}:
            raise ToolError(
                "LONG_TERM_LEARNING_APPROVAL_REQUIRED",
                "长期频道学习必须暂停并获得用户单独确认；本阶段不会调用现有 channel_learning record。",
                details={"recommendationId": recommendation_id, "requestedScope": decision, "automaticModeCannotBypass": True},
            )
        synthetic = arguments.get("syntheticFixture") is True
        analytics_root = self._analytics_root(channel_profile_id, synthetic=synthetic, create=False)
        connection = self._connect(analytics_root, create=False)
        if connection is None:
            raise ToolError("RECOMMENDATION_NOT_FOUND", "没有找到建议卡。")
        row = connection.execute("SELECT * FROM recommendations WHERE recommendation_id = ?", (recommendation_id,)).fetchone()
        if row is None:
            connection.close()
            raise ToolError("RECOMMENDATION_NOT_FOUND", "没有找到建议卡。")
        status = {"test_only": "TEST_ONLY", "observe": "OBSERVING", "reject": "REJECTED"}[decision]
        decision_doc = with_hash(
            {
                "schemaVersion": "1.0.0",
                "contractType": "recommendation-decision",
                "id": f"rd_{_sha_value([recommendation_id, decision, arguments.get('projectId')])[:24]}",
                "version": "1.0.0",
                "createdAt": utc_now(),
                "hashAlgorithm": "SHA-256",
                "hashRule": "canonical-json-v1",
                "upstream": [],
                "recommendationId": recommendation_id,
                "channelProfileId": channel_profile_id,
                "projectId": arguments.get("projectId"),
                "decision": decision,
                "status": status,
                "longTermLearningWritten": False,
            }
        )
        decision_path = analytics_root / "experiments" / f"{decision_doc['id']}.json"
        if not decision_path.exists():
            _write_json(decision_path, decision_doc)
        with connection:
            connection.execute("UPDATE recommendations SET status = ? WHERE recommendation_id = ?", (status, recommendation_id))
        connection.close()
        return {"status": status, "decisionPath": str(decision_path), "contentHash": decision_doc["contentHash"], "longTermLearningWritten": False}

    def progress(self, arguments: dict[str, Any]) -> dict[str, Any]:
        channel_profile_id = _component(arguments.get("channelProfileId"), "channelProfileId")
        synthetic = arguments.get("syntheticFixture") is True
        analytics_root = self._analytics_root(channel_profile_id, synthetic=synthetic, create=False)
        connection = self._connect(analytics_root, create=False)
        if connection is None:
            return {"status": "WAITING_FOR_PUBLICATION_RECEIPT", "videos": [], "readOnly": True}
        video_id = arguments.get("videoId")
        if video_id is not None:
            video_id = _component(video_id, "videoId")
            videos = connection.execute("SELECT * FROM videos WHERE video_id = ?", (video_id,)).fetchall()
        else:
            videos = connection.execute("SELECT * FROM videos ORDER BY registered_at, video_id").fetchall()
        payload: list[dict[str, Any]] = []
        for video in videos:
            tasks = connection.execute("SELECT * FROM tasks WHERE video_id = ? ORDER BY due_at", (video["video_id"],)).fetchall()
            payload.append(
                {
                    "videoId": video["video_id"],
                    "projectId": video["project_id"],
                    "namespace": video["namespace"],
                    "publishedAt": video["published_at"],
                    "tasks": [
                        {
                            "checkpoint": task["checkpoint"],
                            "dueAt": task["due_at"],
                            "status": task["status"],
                            "lastSnapshotId": task["last_snapshot_id"],
                            "attempts": task["attempts"],
                        }
                        for task in tasks
                    ],
                }
            )
        connection.close()
        return {"status": "OK" if payload else "WAITING_FOR_PUBLICATION_RECEIPT", "videos": payload, "readOnly": True}
