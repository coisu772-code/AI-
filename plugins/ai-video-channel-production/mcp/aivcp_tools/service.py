from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .content import CONTENT_LOOP_VERSION, SOURCE_MODES, ContentLoop
from .data_center import DATA_CENTER_VERSION, DataCenter
from .errors import ToolError
from .publisher import PUBLISHER_PROTOCOL_VERSION, PublisherChannelProvider, provider_from_environment
from .production import PRODUCTION_CENTER_VERSION, ProductionCenter
from .publish_package_v2 import (
    PublishPackageError,
    assemble_publish_package_v2,
    validate_publish_package_v2,
)
from .publisher_v2_bridge import PublisherV2Bridge
from .security import redact
from .source_library import SOURCE_LIBRARY_VERSION, SourceLibrary
from .store import ARCHIVE_FORMAT_VERSION, CHANNEL_SCHEMA_VERSION, SYSTEM_SCHEMA_VERSION, ChannelStore
from .voices import VoiceCatalog
from .workshop_bridge import WorkshopBridge


LOCAL_TOOL_PROTOCOL_VERSION = "1.0.0"
SERVICE_VERSION = "0.8.0-rc.1"


def default_data_root(plugin_root: Path | None = None) -> Path:
    configured = os.environ.get("AIVCP_DATA_ROOT")
    if configured:
        return Path(configured).expanduser().resolve()
    if plugin_root:
        resolved = plugin_root.resolve()
        current = resolved.parents[1] if len(resolved.parents) > 1 else None
        if current and current.name == "current" and (current / "install-state.json").is_file():
            try:
                state = json.loads((current / "install-state.json").read_text(encoding="utf-8-sig"))
            except (OSError, json.JSONDecodeError):
                state = {}
            configured_root = state.get("userDataRoot") if isinstance(state, dict) else None
            if isinstance(configured_root, str) and configured_root.strip():
                return Path(configured_root).expanduser().resolve()
            return current.parent / "data"
    local = os.environ.get("LOCALAPPDATA")
    if local:
        return Path(local) / "AI Video Channel Production" / "data"
    return Path.home() / ".ai-video-channel-production" / "data"


@dataclass(slots=True)
class ServiceConfig:
    data_root: Path
    plugin_root: Path | None = None
    voice_catalog_path: Path | None = None
    workshop_executable: Path | None = None
    workshop_isolation_root: Path | None = None

    @classmethod
    def from_environment(cls, plugin_root: Path | None = None) -> "ServiceConfig":
        configured_catalog = os.environ.get("AIVCP_VOICE_CATALOG")
        catalog_path = Path(configured_catalog).resolve() if configured_catalog else None
        if catalog_path is None and plugin_root:
            candidate = plugin_root / "assets" / "voice-catalog.json"
            catalog_path = candidate if candidate.is_file() else None
        workshop_executable = os.environ.get("AIVCP_WORKSHOP_EXECUTABLE")
        isolation_root = os.environ.get("AIVCP_WORKSHOP_ISOLATION_ROOT")
        return cls(
            data_root=default_data_root(plugin_root),
            plugin_root=plugin_root,
            voice_catalog_path=catalog_path,
            workshop_executable=Path(workshop_executable).resolve() if workshop_executable else None,
            workshop_isolation_root=Path(isolation_root).resolve() if isolation_root else None,
        )


class LocalToolService:
    def __init__(
        self,
        config: ServiceConfig,
        *,
        publisher_provider: PublisherChannelProvider | None = None,
    ) -> None:
        self.config = config
        self.publisher = publisher_provider or provider_from_environment(config.data_root)
        self.voices = VoiceCatalog(config.voice_catalog_path)
        self.store = ChannelStore(config.data_root)
        self.sources = SourceLibrary(self.store)
        self.content = ContentLoop(self.store, self.sources, plugin_root=config.plugin_root)
        bridge = None
        if config.workshop_executable and config.workshop_isolation_root:
            bridge = WorkshopBridge(config.workshop_executable, config.workshop_isolation_root)
        self.production = ProductionCenter(
            config.data_root,
            plugin_root=config.plugin_root,
            voice_catalog_path=config.voice_catalog_path,
            workshop_bridge=bridge,
        )
        self.data_center = DataCenter(config.data_root, plugin_root=config.plugin_root)

    def capabilities(self) -> dict[str, Any]:
        return {
            "service": "ai-video-channel-local-tools",
            "serviceVersion": SERVICE_VERSION,
            "protocolVersion": LOCAL_TOOL_PROTOCOL_VERSION,
            "publisherInterface": self.publisher.capabilities(),
            "voiceCatalog": self.voices.capabilities(),
            "schemas": {
                "systemDatabase": SYSTEM_SCHEMA_VERSION,
                "channelDatabase": CHANNEL_SCHEMA_VERSION,
                "archiveFormat": ARCHIVE_FORMAT_VERSION,
                "sourceLibrary": SOURCE_LIBRARY_VERSION,
                "contentLoop": CONTENT_LOOP_VERSION,
                "productionCenter": PRODUCTION_CENTER_VERSION,
                "channelProfileContract": "1.0.0",
                "productionProfileContract": "1.0.0",
                "topicPackageContract": "1.0.0",
                "manuscriptPackageContract": "1.0.0",
                "publishingAssetPackageContract": "1.0.0",
                "productionPackageContract": "2.1",
                "productionTaskContract": "1.0.0",
                "productionResultPackageContract": "1.0.0",
                "publishPackageProtocol": "2.0.0",
                "publisherLocalToolProtocol": "1.0.0",
                "dataCenter": DATA_CENTER_VERSION,
                "analyticsSnapshotContract": "1.0.0",
                "videoPerformanceReport": "1.0.0",
                "channelStrategyReport": "1.0.0",
                "recommendationCard": "1.0.0",
            },
            "capabilities": {
                "publisherChannelList": self.publisher.capabilities().get("available", False),
                "preScannedVoiceCatalog": self.voices.capabilities().get("available", False),
                "channelOnboarding": True,
                "taskBinding": True,
                "oneTimeOverrides": True,
                "channelDefaultVersioning": True,
                "backupRestore": True,
                "channelMigrationPackage": True,
                "sourceCollection": True,
                "sourceDeduplication": True,
                "sourceIncrementalUpdate": True,
                "sourceTaskRecovery": True,
                "contentProduction": True,
                "contentPackageHandoffCheck": True,
                "productionPackage": True,
                "productionTask": True,
                "productionResultPackage": True,
                "publishPackageAssembly": True,
                "publishPackageValidation": True,
                "publisherIsolatedImport": True,
                "workshop": self.production.workshop_bridge is not None,
                "upload": False,
                "analytics": False,
                "analyticsOwnerAuthorizationAvailable": False,
                "dataCenter": True,
                "dataCenterPublicRecordedImport": True,
                "dataCenterSyntheticFixtureIsolation": True,
            },
            "security": {
                "privateMaterialAccepted": False,
                "publisherPrivateMaterialVisible": False,
                "providerResponseAllowlist": True,
                "taskBindingProofRequiredForWrites": True,
                "analyticsCredentialsVisible": False,
                "longTermLearningAutomaticWrite": False,
            },
        }

    def _publisher_channels(self) -> list[dict[str, Any]]:
        return self.publisher.list_channels()

    def _find_publisher_channel(self, arguments: dict[str, Any]) -> dict[str, Any]:
        publisher_profile_id = arguments.get("publisherProfileId")
        channel_serial = arguments.get("channelSerial")
        youtube_channel_id = arguments.get("youtubeChannelId")
        provided = [value is not None for value in (publisher_profile_id, channel_serial, youtube_channel_id)]
        if sum(provided) != 1:
            raise ToolError(
                "PUBLISHER_CHANNEL_SELECTOR_INVALID",
                "必须且只能提供 publisherProfileId、channelSerial 或 youtubeChannelId 之一。",
            )
        channels = self._publisher_channels()
        key, value = (
            ("publisherProfileId", publisher_profile_id)
            if publisher_profile_id is not None
            else ("channelSerial", channel_serial)
            if channel_serial is not None
            else ("youtubeChannelId", youtube_channel_id)
        )
        matches = [channel for channel in channels if channel.get(key) == value]
        if not matches:
            raise ToolError("PUBLISHER_CHANNEL_NOT_FOUND", "发布中心没有找到指定的真实频道。")
        channel = matches[0]
        return channel

    def call(self, name: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
        args = arguments or {}
        if not isinstance(args, dict):
            raise ToolError("INVALID_ARGUMENT", "工具参数必须是对象。")
        if name == "system_capabilities":
            result = self.capabilities()
        elif name == "publisher_list_channels":
            result = {
                "protocolVersion": PUBLISHER_PROTOCOL_VERSION,
                "channels": self._publisher_channels(),
            }
        elif name == "system_voice_catalog":
            result = self.voices.read()
        elif name == "channel_onboarding_start":
            task_id = args.get("taskId")
            if not isinstance(task_id, str) or not task_id:
                raise ToolError("INVALID_ARGUMENT", "taskId 是必填项。")
            existing_binding = self.store.get_task_binding(task_id)
            selected = self._find_publisher_channel(args)
            if existing_binding:
                existing_channel = self.store.get_channel(existing_binding["channelProfileId"])
                if existing_channel["publisherBinding"]["youtubeChannelId"] != selected["youtubeChannelId"]:
                    raise ToolError(
                        "TASK_ALREADY_BOUND",
                        "当前任务已经绑定另一个目标频道；切换频道必须新建任务。",
                        details={"boundChannelProfileId": existing_binding["channelProfileId"]},
                    )
            channel, idempotent = self.store.create_pending_channel(
                publisher_channel=selected,
                target_region=args.get("targetRegion"),
                output_language=args.get("outputLanguage"),
            )
            binding = self.store.bind_task(task_id=task_id, channel_profile_id=channel["channelProfileId"])
            result = {
                "phase": "LIBRARY_DEFAULTS_PENDING",
                "channel": channel,
                "taskBinding": binding,
                "idempotentChannel": idempotent,
                "requiredNext": ["defaultVoice", "manuscriptRange", "episodeRange", "deliveryMode"],
            }
        elif name == "channel_onboarding_complete":
            channel = self.store.get_channel(args.get("channelProfileId"))
            selected = self._find_publisher_channel(
                {"youtubeChannelId": channel["publisherBinding"]["youtubeChannelId"]}
            )
            binding = channel["publisherBinding"]
            if (
                selected["publisherProfileId"] != binding["publisherProfileId"]
                or selected["channelSerial"] != binding["channelSerial"]
            ):
                raise ToolError("PUBLISHER_BINDING_CHANGED", "发布中心身份映射已变化，禁止完成建库。")
            requested_defaults = args.get("defaults")
            voice = requested_defaults.get("voice") if isinstance(requested_defaults, dict) else {}
            self.voices.validate_selection(voice.get("engineId"), voice.get("voiceId"))
            if requested_defaults.get("uploadPolicy") == "AUTO":
                raise ToolError(
                    "AUTO_UPLOAD_NOT_AVAILABLE_STAGE2",
                    "首次建库不能自动授权真实上传；阶段2只允许 DO_NOT_UPLOAD 或 REQUIRE_REVIEW。",
                )
            result = self.store.complete_library(
                task_id=args.get("taskId"),
                channel_profile_id=args.get("channelProfileId"),
                binding_proof=args.get("bindingProof"),
                defaults=requested_defaults,
                execution_mode=args.get("executionMode", "review"),
            )
        elif name == "channel_list":
            result = {"channels": self.store.list_channels()}
        elif name == "channel_get":
            result = self.store.get_channel(args.get("channelProfileId"))
        elif name == "channel_bind_task":
            result = self.store.bind_task(
                task_id=args.get("taskId"), channel_profile_id=args.get("channelProfileId")
            )
        elif name == "channel_resolve_production":
            result = self.store.resolve_production(
                task_id=args.get("taskId"),
                channel_profile_id=args.get("channelProfileId"),
                binding_proof=args.get("bindingProof"),
                overrides=args.get("overrides"),
            )
        elif name == "channel_update_defaults":
            requested_defaults = args.get("defaults")
            if isinstance(requested_defaults, dict) and requested_defaults.get("uploadPolicy") == "AUTO":
                raise ToolError(
                    "AUTO_UPLOAD_NOT_AVAILABLE_STAGE2",
                    "阶段2不能把频道默认值改为自动上传；必须等待真实上传授权链。",
                )
            result = self.store.update_defaults(
                task_id=args.get("taskId"),
                channel_profile_id=args.get("channelProfileId"),
                binding_proof=args.get("bindingProof"),
                defaults=requested_defaults,
                confirmation=args.get("confirmation"),
            )
        elif name == "channel_integrity_check":
            result = self.store.integrity_check(args.get("channelProfileId"))
        elif name == "channel_backup":
            self.store.assert_binding(
                task_id=args.get("taskId"),
                channel_profile_id=args.get("channelProfileId"),
                binding_proof=args.get("bindingProof"),
            )
            result = self.store.backup_channel(args.get("channelProfileId"), kind=args.get("kind", "quick"))
        elif name == "channel_export":
            self.store.assert_binding(
                task_id=args.get("taskId"),
                channel_profile_id=args.get("channelProfileId"),
                binding_proof=args.get("bindingProof"),
            )
            result = self.store.export_channel(args.get("channelProfileId"))
        elif name == "channel_import":
            verified = self.store.verify_archive(args.get("archivePath"))
            imported_binding = verified["channelProfile"]["publisherBinding"]
            task_id = args.get("taskId")
            if not isinstance(task_id, str) or not task_id:
                raise ToolError("INVALID_ARGUMENT", "迁移导入必须提供当前 taskId。")
            existing_task = self.store.get_task_binding(task_id)
            if existing_task and existing_task["channelProfileId"] != verified["manifest"]["channelProfileId"]:
                raise ToolError(
                    "TASK_ALREADY_BOUND",
                    "当前任务已绑定其他频道，不能导入另一个目标频道。",
                    details={"boundChannelProfileId": existing_task["channelProfileId"]},
                )
            selected = self._find_publisher_channel(
                {"youtubeChannelId": imported_binding["youtubeChannelId"]}
            )
            if (
                selected["publisherProfileId"] != imported_binding["publisherProfileId"]
                or selected["channelSerial"] != imported_binding["channelSerial"]
            ):
                raise ToolError(
                    "IMPORT_PUBLISHER_BINDING_MISMATCH",
                    "迁移包频道身份与当前发布中心真实频道映射不一致，禁止导入。",
                )
            result = self.store.import_channel(
                args.get("archivePath"), conflict_mode=args.get("conflictMode", "reject")
            )
            result["taskBinding"] = self.store.bind_task(
                task_id=task_id, channel_profile_id=result["channelProfileId"]
            )
        elif name == "channel_restore":
            if args.get("mode", "verify_only") == "replace":
                channel_profile_id = self.store.verify_archive(args.get("archivePath"))["manifest"]["channelProfileId"]
                self.store.assert_binding(
                    task_id=args.get("taskId"),
                    channel_profile_id=channel_profile_id,
                    binding_proof=args.get("bindingProof"),
                )
            result = self.store.restore_channel(
                args.get("archivePath"),
                mode=args.get("mode", "verify_only"),
                confirmation=args.get("confirmation"),
            )
        elif name == "source_library_capabilities":
            result = self.sources.capabilities()
            try:
                from .source_sites import SiteAdapterRegistry

                registry = SiteAdapterRegistry.from_environment() if hasattr(SiteAdapterRegistry, "from_environment") else SiteAdapterRegistry()
                capability_reader = getattr(registry, "capabilities", None) or getattr(registry, "list_capabilities", None)
                if capability_reader:
                    result["siteCapabilities"] = capability_reader()
            except (ImportError, OSError, ToolError, TypeError, ValueError):
                result["siteCapabilities"] = {"available": False, "reason": "site-adapter-not-ready"}
        elif name == "source_add_prepare":
            result = self.sources.prepare_add(
                task_id=args.get("taskId"),
                channel_profile_id=args.get("channelProfileId"),
                binding_proof=args.get("bindingProof"),
                inputs=args.get("inputs"),
                options=args.get("options"),
            )
        elif name == "source_add_confirm":
            result = self.sources.confirm_add(
                task_id=args.get("taskId"),
                channel_profile_id=args.get("channelProfileId"),
                binding_proof=args.get("bindingProof"),
                acquisition_job_id=args.get("acquisitionJobId"),
                plan_hash=args.get("planHash"),
                confirmation=args.get("confirmation"),
            )
        elif name == "source_job_get":
            result = self.sources.get_job(
                channel_profile_id=args.get("channelProfileId"),
                acquisition_job_id=args.get("acquisitionJobId"),
            )
        elif name == "source_job_cancel":
            result = self.sources.cancel_job(
                task_id=args.get("taskId"),
                channel_profile_id=args.get("channelProfileId"),
                binding_proof=args.get("bindingProof"),
                acquisition_job_id=args.get("acquisitionJobId"),
            )
        elif name == "source_job_resume":
            result = self.sources.resume_job(
                task_id=args.get("taskId"),
                channel_profile_id=args.get("channelProfileId"),
                binding_proof=args.get("bindingProof"),
                acquisition_job_id=args.get("acquisitionJobId"),
                supplements=args.get("supplements"),
            )
        elif name == "source_search":
            result = self.sources.search(
                channel_profile_id=args.get("channelProfileId"),
                query=args.get("query"),
                source_type=args.get("sourceType"),
                status=args.get("status"),
                language=args.get("language"),
                limit=args.get("limit", 50),
            )
        elif name == "source_get":
            result = self.sources.get_source(
                channel_profile_id=args.get("channelProfileId"),
                source_package_id=args.get("sourcePackageId"),
            )
        elif name == "source_update_prepare":
            result = self.sources.update_source(
                task_id=args.get("taskId"),
                channel_profile_id=args.get("channelProfileId"),
                binding_proof=args.get("bindingProof"),
                source_package_id=args.get("sourcePackageId"),
                options=args.get("options"),
            )
        elif name == "source_integrity_check":
            result = self.sources.integrity_check(channel_profile_id=args.get("channelProfileId"))
        elif name == "content_capabilities":
            result = self.content.capabilities()
        elif name == "content_project_start":
            result = self.content.start_project(
                task_id=args.get("taskId"),
                channel_profile_id=args.get("channelProfileId"),
                binding_proof=args.get("bindingProof"),
                project_id=args.get("projectId"),
                source_mode=args.get("sourceMode"),
                source_packages=args.get("sourcePackages"),
                provided_outline=args.get("providedOutline"),
                learning_snapshot=args.get("learningSnapshot"),
                one_time_modifications=args.get("oneTimeModifications"),
                long_term_learning=args.get("longTermLearning"),
            )
        elif name == "content_topic_checkpoint":
            result = self.content.checkpoint_topic(
                task_id=args.get("taskId"),
                channel_profile_id=args.get("channelProfileId"),
                binding_proof=args.get("bindingProof"),
                project_id=args.get("projectId"),
                candidate_number=args.get("candidateNumber"),
                candidate=args.get("candidate"),
            )
        elif name == "content_topic_finalize":
            result = self.content.finalize_topic(
                task_id=args.get("taskId"),
                channel_profile_id=args.get("channelProfileId"),
                binding_proof=args.get("bindingProof"),
                project_id=args.get("projectId"),
                ranking=args.get("ranking"),
                selected_candidate_id=args.get("selectedCandidateId"),
                selection_reasons=args.get("selectionReasons"),
                confirmation=args.get("confirmation"),
            )
        elif name == "content_manuscript_finalize":
            result = self.content.finalize_manuscript(
                task_id=args.get("taskId"),
                channel_profile_id=args.get("channelProfileId"),
                binding_proof=args.get("bindingProof"),
                project_id=args.get("projectId"),
                story_bible=args.get("storyBible"),
                characters=args.get("characters"),
                target_script=args.get("targetScript"),
                chinese_audit_script=args.get("chineseAuditScript"),
                quality_gate=args.get("qualityGate"),
                confirmation=args.get("confirmation"),
                authoring_mode=args.get("authoringMode", "target-language-native"),
            )
        elif name == "content_publishing_finalize":
            result = self.content.finalize_publishing(
                task_id=args.get("taskId"),
                channel_profile_id=args.get("channelProfileId"),
                binding_proof=args.get("bindingProof"),
                project_id=args.get("projectId"),
                title=args.get("title"),
                title_chinese=args.get("titleChinese"),
                description_body=args.get("descriptionBody"),
                hashtags=args.get("hashtags"),
                thumbnail_provider=args.get("thumbnailProvider"),
                thumbnail_strategy=args.get("thumbnailStrategy"),
                thumbnail_candidates=args.get("thumbnailCandidates"),
                selected_thumbnail_id=args.get("selectedThumbnailId"),
                thumbnail=args.get("thumbnail"),
                ctr_review=args.get("ctrReview"),
                confirmation=args.get("confirmation"),
            )
        elif name == "content_project_get":
            result = self.content.get_project(
                channel_profile_id=args.get("channelProfileId"),
                project_id=args.get("projectId"),
            )
        elif name == "content_integrity_check":
            result = self.content.integrity_check(
                channel_profile_id=args.get("channelProfileId"),
                project_id=args.get("projectId"),
            )
        elif name == "content_handoff_check":
            result = self.content.handoff_check(
                channel_profile_id=args.get("channelProfileId"),
                project_id=args.get("projectId"),
            )
        elif name == "production_capabilities":
            result = self.production.capabilities()
            if self.production.workshop_bridge is not None:
                result["workshopHealth"] = self.production.workshop_bridge.health_check()
                result["workshopCapabilities"] = self.production.workshop_bridge.capabilities()
        elif name == "production_package_assemble":
            self.store.assert_binding(
                task_id=args.get("taskId"),
                channel_profile_id=args.get("channelProfileId"),
                binding_proof=args.get("bindingProof"),
            )
            state = self.content.get_project(
                channel_profile_id=args.get("channelProfileId"),
                project_id=args.get("projectId"),
            )["state"]
            manuscript_ref = state.get("activePackages", {}).get("manuscript")
            publishing_ref = state.get("activePackages", {}).get("publishing")
            if not manuscript_ref or not publishing_ref:
                raise ToolError("PRODUCTION_UPSTREAM_NOT_CONFIRMED", "缺少已确认文稿包或发布素材包。")
            result = self.production.assemble_package(
                manuscript_path=Path(manuscript_ref["path"]),
                publishing_path=Path(publishing_ref["path"]),
                production_config=args.get("productionConfig"),
                production_preset=args.get("productionPreset"),
                workshop_compatibility=args.get("workshopCompatibility"),
                synthetic=bool(args.get("synthetic", False)),
            )
        elif name == "production_task_start":
            self.store.assert_binding(
                task_id=args.get("taskId"),
                channel_profile_id=args.get("channelProfileId"),
                binding_proof=args.get("bindingProof"),
            )
            result = self.production.start_task(
                production_task_id=args.get("productionTaskId"),
                package_root=Path(args.get("productionPackagePath", "")),
            )
        elif name == "production_task_get":
            result = self.production.get_task(args.get("productionTaskId"))
        elif name in {
            "production_task_run",
            "production_task_pause",
            "production_task_resume",
            "production_task_retry",
            "production_task_invalidate",
            "production_jianying_export_ingest",
        }:
            self.store.assert_binding(
                task_id=args.get("taskId"),
                channel_profile_id=args.get("channelProfileId"),
                binding_proof=args.get("bindingProof"),
            )
            if name == "production_task_run":
                result = self.production.run_task(
                    args.get("productionTaskId"),
                    pause_after_step=args.get("pauseAfterStep"),
                    fail_storyboard_ids=args.get("failStoryboardIds"),
                )
            elif name == "production_task_pause":
                result = self.production.request_pause(args.get("productionTaskId"))
            elif name == "production_task_resume":
                result = self.production.resume_task(args.get("productionTaskId"))
            elif name == "production_task_retry":
                result = self.production.retry_failed(args.get("productionTaskId"))
            elif name == "production_task_invalidate":
                result = self.production.invalidate(args.get("productionTaskId"), changes=args.get("changes"))
            else:
                result = self.production.ingest_jianying_export(
                    args.get("productionTaskId"),
                    export_path=Path(args.get("exportPath", "")),
                    identity_path=Path(args.get("identityPath", "")),
                )
        elif name == "production_result_validate":
            result = self.production.validate_result_package(Path(args.get("resultPackagePath", "")))
        elif name == "assemble_publish_package_v2":
            if args.get("networkExecution") is not False:
                raise ToolError("PUBLISHER_NETWORK_EXECUTION_FORBIDDEN", "Stage6 必须显式传入 networkExecution=false。")
            publisher_channel = args.get("publisherChannel")
            if not isinstance(publisher_channel, dict):
                raise ToolError("INVALID_ARGUMENT", "publisherChannel 必须是只读频道档案对象。")
            channel_profile = {
                "channel_profile_id": args.get("channelProfileId"),
                "publisher_profile_id": publisher_channel.get("publisherProfileId"),
                "channel_serial": publisher_channel.get("channelSerial"),
                "expected_channel_id": publisher_channel.get("youtubeChannelId"),
                "enabled": publisher_channel.get("enabled"),
                "authorization_status": publisher_channel.get("authorizationStatus"),
                "default_language": publisher_channel.get("defaultLanguage", ""),
                "timezone": publisher_channel.get("timeZone"),
                "upload_mode": publisher_channel.get("uploadPolicy"),
            }
            authorization = args.get("authorization")
            if isinstance(authorization, dict):
                authorization = {
                    key: {
                        "granted": bool(value.get("granted", False)),
                        "version": value.get("version", ""),
                        "confirmed_at": value.get("confirmedAt", ""),
                    }
                    for key, value in authorization.items()
                    if key in {"workspace", "channel", "intent"} and isinstance(value, dict)
                }
            try:
                result = assemble_publish_package_v2(
                    production_result_root=Path(args.get("productionResultPath", "")),
                    publishing_asset_root=Path(args.get("publishingAssetPath", "")),
                    inbox_root=Path(args.get("inboxPath", "")),
                    channel_profile=channel_profile,
                    constraints_catalog_path=self._publisher_constraints_catalog(),
                    authorization=authorization,
                    limits=args.get("limits"),
                    scheduled_at=args.get("scheduledAt"),
                    schedule_conflict=bool(args.get("scheduleConflict", False)),
                    timezone=args.get("timeZone"),
                    ffprobe_path=args.get("ffprobePath"),
                )
            except PublishPackageError as exc:
                raise ToolError(exc.code, str(exc), details=exc.details) from exc
        elif name == "validate_publish_package_v2":
            if args.get("networkExecution") is not False:
                raise ToolError("PUBLISHER_NETWORK_EXECUTION_FORBIDDEN", "Stage6 必须显式传入 networkExecution=false。")
            try:
                result = validate_publish_package_v2(
                    Path(args.get("packagePath", "")),
                    constraints_catalog_path=self._publisher_constraints_catalog(),
                    ffprobe_path=args.get("ffprobePath"),
                )
            except PublishPackageError as exc:
                raise ToolError(exc.code, str(exc), details=exc.details) from exc
        elif name == "import_publish_package_v2":
            result = PublisherV2Bridge.from_arguments(args).import_package(args)
        elif name == "get_publication_status":
            result = PublisherV2Bridge.from_arguments(args).read_status(args, receipt=False)
        elif name == "get_publication_receipt":
            result = PublisherV2Bridge.from_arguments(args).read_status(args, receipt=True)
        elif name == "data_center_capabilities":
            result = self.data_center.capabilities(
                existing_channel_database_path=args.get("existingChannelDatabasePath")
            )
        elif name == "data_video_register":
            result = self.data_center.register_video(args)
        elif name == "data_collection_run":
            result = self.data_center.collect(args)
        elif name == "data_report_generate":
            result = self.data_center.generate_report(args)
        elif name == "data_recommendations_list":
            result = self.data_center.list_recommendations(args)
        elif name == "data_learning_decide":
            result = self.data_center.learning_decision(args)
        elif name == "data_progress_get":
            result = self.data_center.progress(args)
        else:
            raise ToolError("TOOL_NOT_FOUND", "本地工具服务没有该工具。", details={"tool": name})
        return redact(result)

    def _publisher_constraints_catalog(self) -> Path:
        if self.config.plugin_root is None:
            raise ToolError("PUBLISHER_CONSTRAINTS_UNAVAILABLE", "缺少插件根目录，无法定位版本化 YouTube 规则目录。")
        candidate = self.config.plugin_root.resolve().parents[1] / "contracts" / "youtube-constraints" / "catalog-2026.08.04.1.json"
        if not candidate.is_file():
            raise ToolError("PUBLISHER_CONSTRAINTS_UNAVAILABLE", "版本化 YouTube 规则目录缺失。")
        return candidate


def tool_definitions() -> list[dict[str, Any]]:
    object_schema: dict[str, Any] = {"type": "object", "additionalProperties": False}
    binding_properties = {
        "taskId": {"type": "string", "minLength": 1, "maxLength": 160},
        "channelProfileId": {"type": "string", "minLength": 3, "maxLength": 160},
        "bindingProof": {"type": "string", "minLength": 20, "maxLength": 256},
    }
    definitions = [
        ("system_capabilities", "读取本地工具、协议、Schema、安全和阶段能力状态。", {}, []),
        ("system_voice_catalog", "只读列出已安装的预扫描真实音色目录，不启动工坊扫描。", {}, []),
        ("publisher_list_channels", "从 YouTube 发布中心只读列出真实频道，不返回凭据。", {}, []),
        (
            "channel_onboarding_start",
            "确认真实发布频道、目标地区和输出语言，建立阶段 A 身份绑定。",
            {
                "taskId": {"type": "string"},
                "publisherProfileId": {"type": "string"},
                "channelSerial": {"type": "string"},
                "youtubeChannelId": {"type": "string"},
                "targetRegion": {"type": "string"},
                "outputLanguage": {"type": "string"},
            },
            ["taskId", "targetRegion", "outputLanguage"],
        ),
        (
            "channel_onboarding_complete",
            "确认阶段 B 四项生产默认值并原子创建独立频道资料库。",
            {
                **binding_properties,
                "defaults": {"type": "object"},
                "executionMode": {"type": "string", "enum": ["review", "auto"]},
            },
            ["taskId", "channelProfileId", "bindingProof", "defaults"],
        ),
        ("channel_list", "列出本机频道资料库摘要。", {}, []),
        (
            "channel_get",
            "读取指定频道档案和活动生产预设。",
            {"channelProfileId": {"type": "string"}},
            ["channelProfileId"],
        ),
        (
            "channel_bind_task",
            "将新 Codex 任务绑定到一个已有频道，并轮换写入校验值。",
            {"taskId": {"type": "string"}, "channelProfileId": {"type": "string"}},
            ["taskId", "channelProfileId"],
        ),
        (
            "channel_resolve_production",
            "读取长期默认并合并仅本次覆盖；不修改频道默认值。",
            {**binding_properties, "overrides": {"type": "object"}},
            ["taskId", "channelProfileId", "bindingProof"],
        ),
        (
            "channel_update_defaults",
            "在明确频道级确认后生成新的生产预设版本，不改旧项目快照。",
            {**binding_properties, "defaults": {"type": "object"}, "confirmation": {"type": "object"}},
            ["taskId", "channelProfileId", "bindingProof", "defaults", "confirmation"],
        ),
        (
            "channel_integrity_check",
            "只读检查系统注册库或指定频道资料库完整性。",
            {"channelProfileId": {"type": "string"}},
            [],
        ),
        (
            "channel_backup",
            "在本地隔离备份目录生成带文件哈希的 .avchannel 包。",
            {**binding_properties, "kind": {"type": "string", "enum": ["quick", "full"]}},
            ["taskId", "channelProfileId", "bindingProof"],
        ),
        (
            "channel_export",
            "导出可迁移且经过完整性校验的 .avchannel 包。",
            binding_properties,
            ["taskId", "channelProfileId", "bindingProof"],
        ),
        (
            "channel_import",
            "导入迁移包；身份冲突时拒绝覆盖或复用完全相同频道。",
            {
                "archivePath": {"type": "string"},
                "conflictMode": {"type": "string", "enum": ["reject", "reuse_existing"]},
                "taskId": {"type": "string"},
            },
            ["archivePath", "taskId"],
        ),
        (
            "channel_restore",
            "默认只校验备份；替换恢复需要外部确认并自动建立恢复前备份。",
            {
                "archivePath": {"type": "string"},
                "mode": {"type": "string", "enum": ["verify_only", "replace"]},
                "confirmation": {"type": "string"},
                "taskId": {"type": "string"},
                "bindingProof": {"type": "string"},
            },
            ["archivePath"],
        ),
        ("source_library_capabilities", "读取资料库、去重、恢复、格式与三市场站点能力；不执行内容分析。", {}, []),
        (
            "source_add_prepare",
            "识别链接、文件或粘贴文字并生成唯一入库确认卡；尚不采集或分析。",
            {**binding_properties, "inputs": {"type": "array", "minItems": 1, "maxItems": 500}, "options": {"type": "object"}},
            ["taskId", "channelProfileId", "bindingProof", "inputs"],
        ),
        (
            "source_add_confirm",
            "确认入库卡后执行采集、标准化、三层去重、版本写入与完成卡。",
            {
                **binding_properties,
                "acquisitionJobId": {"type": "string"},
                "planHash": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
                "confirmation": {"type": "object"},
            },
            ["taskId", "channelProfileId", "bindingProof", "acquisitionJobId", "planHash", "confirmation"],
        ),
        (
            "source_job_get",
            "只读查看当前频道资料任务进度、失败项、补充路径与完成卡。",
            {"channelProfileId": {"type": "string"}, "acquisitionJobId": {"type": "string"}},
            ["channelProfileId", "acquisitionJobId"],
        ),
        (
            "source_job_cancel",
            "取消资料任务；保留已经完整入库的资料。",
            {**binding_properties, "acquisitionJobId": {"type": "string"}},
            ["taskId", "channelProfileId", "bindingProof", "acquisitionJobId"],
        ),
        (
            "source_job_resume",
            "从检查点恢复失败或等待补充的资料项，可附加用户提供的文件或文字。",
            {**binding_properties, "acquisitionJobId": {"type": "string"}, "supplements": {"type": "array"}},
            ["taskId", "channelProfileId", "bindingProof", "acquisitionJobId"],
        ),
        (
            "source_search",
            "按关键词、来源类型、状态和语言检索当前频道资料索引。",
            {
                "channelProfileId": {"type": "string"}, "query": {"type": "string"},
                "sourceType": {"type": "string"}, "status": {"type": "string"},
                "language": {"type": "string"}, "limit": {"type": "integer", "minimum": 1, "maximum": 200},
            },
            ["channelProfileId"],
        ),
        (
            "source_get",
            "读取一个 Source Package v1 当前版本、历史版本、别名和来源边界。",
            {"channelProfileId": {"type": "string"}, "sourcePackageId": {"type": "string"}},
            ["channelProfileId", "sourcePackageId"],
        ),
        (
            "source_update_prepare",
            "为已有频道、视频或连载小说生成只下载增量的更新确认卡。",
            {**binding_properties, "sourcePackageId": {"type": "string"}, "options": {"type": "object"}},
            ["taskId", "channelProfileId", "bindingProof", "sourcePackageId"],
        ),
        (
            "source_integrity_check",
            "校验 Source Package manifest、canonical-json-v1 哈希和全部正式资产 SHA-256。",
            {"channelProfileId": {"type": "string"}},
            ["channelProfileId"],
        ),
        (
            "content_capabilities",
            "只读列出阶段4内容路线、可插拔接口、资料门和禁止触发的下游边界。",
            {},
            [],
        ),
        (
            "content_project_start",
            "冻结阶段2频道上下文与阶段3资料版本，建立阶段4内容项目和 G2 确认卡。",
            {
                **binding_properties,
                "projectId": {"type": "string"},
                "sourceMode": {"type": "string", "enum": sorted(SOURCE_MODES)},
                "sourcePackages": {"type": "array"},
                "providedOutline": {"type": "string"},
                "learningSnapshot": {"type": "object"},
                "oneTimeModifications": {"type": "array", "items": {"type": "string"}},
                "longTermLearning": {},
            },
            ["taskId", "channelProfileId", "bindingProof", "projectId", "sourceMode"],
        ),
        (
            "content_topic_checkpoint",
            "逐个保存一个真实完整候选；频道路线按 1/10 到 10/10 严格递增，不伪造检查点。",
            {**binding_properties, "projectId": {"type": "string"}, "candidateNumber": {"type": "integer", "minimum": 1, "maximum": 10}, "candidate": {"type": "object"}},
            ["taskId", "channelProfileId", "bindingProof", "projectId", "candidateNumber", "candidate"],
        ),
        (
            "content_topic_finalize",
            "校验完整候选、七项评分、排名与 G3 确认后冻结 Topic Package v1。",
            {**binding_properties, "projectId": {"type": "string"}, "ranking": {"type": "array"}, "selectedCandidateId": {"type": "string"}, "selectionReasons": {"type": "object"}, "confirmation": {"type": "object"}},
            ["taskId", "channelProfileId", "bindingProof", "projectId", "ranking", "selectedCandidateId", "selectionReasons", "confirmation"],
        ),
        (
            "content_manuscript_finalize",
            "校验目标语言原生母稿、逐行中文审核映射、角色音色和合并质量门后冻结 Manuscript Package v1。",
            {**binding_properties, "projectId": {"type": "string"}, "storyBible": {"type": "object"}, "characters": {"type": "array"}, "targetScript": {"type": "array"}, "chineseAuditScript": {"type": ["array", "null"]}, "qualityGate": {"type": "object"}, "confirmation": {"type": "object"}, "authoringMode": {"type": "string"}},
            ["taskId", "channelProfileId", "bindingProof", "projectId", "storyBible", "characters", "targetScript", "qualityGate", "confirmation"],
        ),
        (
            "content_publishing_finalize",
            "只读取确认母稿，校验唯一标题、简介、8–12 个 Hashtags、封面与 CTR 联评后冻结 Publishing Asset Package v1。",
            {**binding_properties, "projectId": {"type": "string"}, "title": {"type": "string"}, "titleChinese": {"type": "string"}, "descriptionBody": {"type": "string"}, "hashtags": {"type": "array"}, "thumbnailProvider": {"type": "object"}, "thumbnailStrategy": {"type": "object"}, "thumbnailCandidates": {"type": "array", "minItems": 5, "maxItems": 5}, "selectedThumbnailId": {"type": "string"}, "thumbnail": {"type": "object"}, "ctrReview": {"type": "object"}, "confirmation": {"type": "object"}},
            ["taskId", "channelProfileId", "bindingProof", "projectId", "title", "titleChinese", "descriptionBody", "hashtags", "thumbnailProvider", "thumbnailStrategy", "thumbnailCandidates", "selectedThumbnailId", "thumbnail", "ctrReview", "confirmation"],
        ),
        (
            "content_project_get",
            "只读查看阶段4项目状态、冻结包版本、失效记录和边界。",
            {"channelProfileId": {"type": "string"}, "projectId": {"type": "string"}},
            ["channelProfileId", "projectId"],
        ),
        (
            "content_integrity_check",
            "只读校验三个冻结包、上游哈希、逐行资产及真实封面文件。",
            {"channelProfileId": {"type": "string"}, "projectId": {"type": "string"}},
            ["channelProfileId", "projectId"],
        ),
        (
            "content_handoff_check",
            "只读判断全部确认门与真实封面是否满足；不生成生产包、不启动工坊。",
            {"channelProfileId": {"type": "string"}, "projectId": {"type": "string"}},
            ["channelProfileId", "projectId"],
        ),
        (
            "production_capabilities",
            "只读检查标准生产包、制作任务、FFmpeg、工坊桥和发布隔离边界。",
            {},
            [],
        ),
        (
            "production_package_assemble",
            "从已确认的 Manuscript 与 Publishing Asset 组装并硬门校验 Production Package v2.1。",
            {
                **binding_properties,
                "projectId": {"type": "string"},
                "productionConfig": {"type": "object"},
                "productionPreset": {"type": "object"},
                "workshopCompatibility": {"type": "object"},
                "synthetic": {"type": "boolean"},
            },
            ["taskId", "channelProfileId", "bindingProof", "projectId", "productionConfig", "productionPreset", "workshopCompatibility"],
        ),
        (
            "production_task_start",
            "严格导入 Production Package v2.1，并创建唯一权威 Production Task v1。",
            {
                **binding_properties,
                "productionTaskId": {"type": "string"},
                "productionPackagePath": {"type": "string"},
            },
            ["taskId", "channelProfileId", "bindingProof", "productionTaskId", "productionPackagePath"],
        ),
        (
            "production_task_get",
            "只读查看权威制作任务的步骤、资产、失败和 VIDEO_READY 状态，不修改任务。",
            {"productionTaskId": {"type": "string"}},
            ["productionTaskId"],
        ),
        (
            "production_task_run",
            "按 P0–P11 依赖运行或恢复任务；合成验收必须显式 synthetic 标记。",
            {
                **binding_properties,
                "productionTaskId": {"type": "string"},
                "pauseAfterStep": {"type": "string", "enum": [f"P{value}" for value in range(12)]},
                "failStoryboardIds": {"type": "array", "items": {"type": "string"}},
            },
            ["taskId", "channelProfileId", "bindingProof", "productionTaskId"],
        ),
        (
            "production_task_pause",
            "请求安全暂停当前制作任务，保留全部已完成资产。",
            {**binding_properties, "productionTaskId": {"type": "string"}},
            ["taskId", "channelProfileId", "bindingProof", "productionTaskId"],
        ),
        (
            "production_task_resume",
            "从权威任务检查点恢复，不重做已通过且指纹有效的资产。",
            {**binding_properties, "productionTaskId": {"type": "string"}},
            ["taskId", "channelProfileId", "bindingProof", "productionTaskId"],
        ),
        (
            "production_task_retry",
            "只把失败资产及其步骤排入重试，不清空其他已完成资产。",
            {**binding_properties, "productionTaskId": {"type": "string"}},
            ["taskId", "channelProfileId", "bindingProof", "productionTaskId"],
        ),
        (
            "production_task_invalidate",
            "按输入指纹和依赖表选择性失效；发布文字或封面变化不得失效正片。",
            {**binding_properties, "productionTaskId": {"type": "string"}, "changes": {"type": "array", "minItems": 1, "items": {"type": "string"}}},
            ["taskId", "channelProfileId", "bindingProof", "productionTaskId", "changes"],
        ),
        (
            "production_jianying_export_ingest",
            "隔离回收带项目、任务和包指纹的剪映导出 MP4，并执行统一技术验收。",
            {**binding_properties, "productionTaskId": {"type": "string"}, "exportPath": {"type": "string"}, "identityPath": {"type": "string"}},
            ["taskId", "channelProfileId", "bindingProof", "productionTaskId", "exportPath", "identityPath"],
        ),
        (
            "production_result_validate",
            "只读校验 VIDEO_READY Production Result Package v1 及发布越权边界。",
            {"resultPackagePath": {"type": "string"}},
            ["resultPackagePath"],
        ),
        (
            "assemble_publish_package_v2",
            "离线组装发布包 v2；只在全部校验成功后把 .creating 原子提升为 .ready。",
            {
                "productionResultPath": {"type": "string"},
                "publishingAssetPath": {"type": "string"},
                "inboxPath": {"type": "string"},
                "channelProfileId": {"type": "string"},
                "publisherChannel": {"type": "object"},
                "authorization": {"type": "object"},
                "limits": {"type": "object"},
                "scheduledAt": {"type": ["string", "null"]},
                "scheduleConflict": {"type": "boolean"},
                "timeZone": {"type": "string"},
                "ffprobePath": {"type": "string"},
                "networkExecution": {"const": False},
            },
            ["productionResultPath", "publishingAssetPath", "inboxPath", "channelProfileId", "publisherChannel", "networkExecution"],
        ),
        (
            "validate_publish_package_v2",
            "只读独立重验完整 .ready 发布包 v2；拒绝半包、路径、哈希、媒体和状态伪造。",
            {
                "packagePath": {"type": "string"},
                "ffprobePath": {"type": "string"},
                "networkExecution": {"const": False},
            },
            ["packagePath", "networkExecution"],
        ),
        (
            "import_publish_package_v2",
            "通过隔离发布中心 CLI 导入 .ready 包；强制 networkExecution=false，不触碰正式数据库。",
            {
                "publisherCliPath": {"type": "string"},
                "packagePath": {"type": "string"},
                "inboxPath": {"type": "string"},
                "databasePath": {"type": "string"},
                "isolationRoot": {"type": "string"},
                "channelCliPath": {"type": "string"},
                "channelDatabasePath": {"type": "string"},
                "syntheticChannelProfilePath": {"type": "string"},
                "ffprobePath": {"type": "string"},
                "networkExecution": {"const": False},
            },
            ["publisherCliPath", "packagePath", "inboxPath", "databasePath", "isolationRoot", "networkExecution"],
        ),
        (
            "get_publication_status",
            "从隔离发布中心 SQLite 只读查询本地或真实状态，不推进任务。",
            {
                "publisherCliPath": {"type": "string"},
                "databasePath": {"type": "string"},
                "isolationRoot": {"type": "string"},
                "publishIntentId": {"type": "string"},
                "networkExecution": {"const": False},
            },
            ["publisherCliPath", "databasePath", "isolationRoot", "publishIntentId", "networkExecution"],
        ),
        (
            "get_publication_receipt",
            "只读获取真实发布回执；没有真实 YouTube video ID 时明确返回 not_available。",
            {
                "publisherCliPath": {"type": "string"},
                "databasePath": {"type": "string"},
                "isolationRoot": {"type": "string"},
                "publishIntentId": {"type": "string"},
                "networkExecution": {"const": False},
            },
            ["publisherCliPath", "databasePath", "isolationRoot", "publishIntentId", "networkExecution"],
        ),
        (
            "data_center_capabilities",
            "只读检查数据中心、Metric Catalog、独立 Analytics 授权占位、迁移审批门和安全边界。",
            {"existingChannelDatabasePath": {"type": "string"}},
            [],
        ),
        (
            "data_video_register",
            "用真实 Publication Receipt v1 和五类上游哈希注册正式视频；synthetic fixture 只能进入隔离命名空间。",
            {
                "channelProfileId": {"type": "string"},
                "publicationReceiptPath": {"type": "string"},
                "upstreamDocuments": {"type": "object"},
                "videoMetadata": {"type": "object"},
                "syntheticFixture": {"type": "boolean"},
                "syntheticRegistration": {"type": "object"},
            },
            ["channelProfileId", "syntheticFixture"],
        ),
        (
            "data_collection_run",
            "在 T+24/T+7/T+28 触发检查点导入公开、owner fixture 或本地系统事实并生成不可变 Analytics Snapshot v1。",
            {
                "channelProfileId": {"type": "string"},
                "videoId": {"type": "string"},
                "checkpoint": {"type": "string", "enum": ["T+24H", "T+7D", "T+28D"]},
                "collectedAt": {"type": "string"},
                "windowStart": {"type": "string"},
                "windowEnd": {"type": "string"},
                "dataCutoff": {"type": "string"},
                "timezone": {"type": "string"},
                "completeness": {"type": "string", "enum": ["provisional", "complete"]},
                "sources": {"type": "object"},
                "syntheticFixture": {"type": "boolean"},
            },
            ["channelProfileId", "videoId", "checkpoint", "collectedAt", "windowStart", "windowEnd", "dataCutoff", "timezone", "sources", "syntheticFixture"],
        ),
        (
            "data_report_generate",
            "从当前频道有效快照同时生成 JSON/Markdown 视频报告、频道报告和等待学习决定的建议卡。",
            {
                "channelProfileId": {"type": "string"},
                "videoId": {"type": "string"},
                "checkpoint": {"type": "string", "enum": ["T+24H", "T+7D", "T+28D"]},
                "syntheticFixture": {"type": "boolean"},
            },
            ["channelProfileId", "videoId", "checkpoint", "syntheticFixture"],
        ),
        (
            "data_recommendations_list",
            "只读列出当前频道建议卡及其学习决定状态，不读取其他频道。",
            {"channelProfileId": {"type": "string"}, "syntheticFixture": {"type": "boolean"}},
            ["channelProfileId", "syntheticFixture"],
        ),
        (
            "data_learning_decide",
            "记录仅本次实验、继续观察或拒绝；任何长期学习请求一律停在单独审批门。",
            {
                "channelProfileId": {"type": "string"},
                "recommendationId": {"type": "string"},
                "decision": {"type": "string", "enum": ["test_only", "channel_default", "must_avoid", "observe", "reject"]},
                "projectId": {"type": "string"},
                "syntheticFixture": {"type": "boolean"},
            },
            ["channelProfileId", "recommendationId", "decision", "syntheticFixture"],
        ),
        (
            "data_progress_get",
            "只读查看视频注册与 T+24/T+7/T+28 采集/报告进度，不推进或改写任务。",
            {"channelProfileId": {"type": "string"}, "videoId": {"type": "string"}, "syntheticFixture": {"type": "boolean"}},
            ["channelProfileId", "syntheticFixture"],
        ),
    ]
    return [
        {
            "name": name,
            "description": description,
            "inputSchema": {**object_schema, "properties": properties, "required": required},
        }
        for name, description, properties, required in definitions
    ]
