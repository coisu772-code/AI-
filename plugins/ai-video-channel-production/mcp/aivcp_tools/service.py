from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .content import CONTENT_LOOP_VERSION, SOURCE_MODES, ContentLoop
from .content_analysis import CONTENT_ANALYSIS_VERSION, ChannelDistillation
from .creative_workspace import CREATIVE_WORKSPACE_VERSION, DOCUMENT_STAGES, PROMPT_STAGES, CreativeWorkspace
from .data_center import DATA_CENTER_VERSION, DataCenter
from .errors import ToolError
from .original_imitation import ORIGINAL_IMITATION_VERSION, OriginalImitationWriting
from .publisher import PUBLISHER_PROTOCOL_VERSION, PublisherChannelProvider, provider_from_environment
from .production import PRODUCTION_CENTER_VERSION, ProductionCenter
from .publish_package_v2 import (
    PublishPackageError,
    assemble_publish_package_v2,
    validate_publish_package_v2,
)
from .publisher_v2_bridge import PublisherV2Bridge
from .review_documents import REVIEW_DOCUMENT_SCHEMA_VERSION
from .confirmation_cards import normalize_confirmation_cards
from .security import redact
from .source_library import SOURCE_LIBRARY_VERSION, SourceLibrary
from .store import ARCHIVE_FORMAT_VERSION, CHANNEL_SCHEMA_VERSION, SYSTEM_SCHEMA_VERSION, ChannelStore
from .task_prompts import TASK_PROMPT_CONTRACT_VERSION, TASK_PROMPT_STAGES, TaskPromptRegistry
from .video_deconstruction import VIDEO_DECONSTRUCTION_VERSION, VideoCopyDeconstruction
from .voices import VoiceCatalog
from .workshop_bridge import WorkshopBridge


RETIRED_CONTENT_TOOL_PREFIXES = (
    "video_deconstruction_",
    "content_deconstruction_",
    "original_imitation_",
)


LOCAL_TOOL_PROTOCOL_VERSION = "1.0.0"
SERVICE_VERSION = "0.12.0-rc.4"


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
        return Path(local) / "AI Video Channel Production Data"
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
        self.creative_workspace = CreativeWorkspace(self.store)
        self.task_prompts = TaskPromptRegistry(self.store)
        self.sources = SourceLibrary(self.store)
        self.analysis = ChannelDistillation(self.store, self.sources, plugin_root=config.plugin_root)
        self.video_analysis = VideoCopyDeconstruction(
            self.store,
            self.sources,
            channel_distillations=self.analysis,
            plugin_root=config.plugin_root,
        )
        self.content_deconstruction = VideoCopyDeconstruction(
            self.store,
            self.sources,
            plugin_root=config.plugin_root,
            analysis_kind="content-deconstruction",
            root_folder="content-deconstructions",
            accepted_source_types={"youtube-video", "local-file", "pasted-text", "novel-web"},
        )
        self.original_imitation = OriginalImitationWriting(
            self.store,
            self.sources,
            video_analyses=self.video_analysis,
            channel_distillations=self.analysis,
            plugin_root=config.plugin_root,
        )
        self.content = ContentLoop(
            self.store,
            self.sources,
            plugin_root=config.plugin_root,
            analyses=self.analysis,
            video_analyses=self.video_analysis,
            content_analyses=self.content_deconstruction,
            style_provider=self.original_imitation,
            task_prompt_registry=self.task_prompts,
        )
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
        publisher_v2_value = os.environ.get("AIVCP_PUBLISHER_V2_CLI", "").strip()
        publisher_v2_path = Path(publisher_v2_value).resolve() if publisher_v2_value else None
        publisher_v2_configured = bool(
            publisher_v2_path
            and publisher_v2_path.is_file()
            and publisher_v2_path.name.lower() == "publish-package-v2.exe"
        )
        publisher_capabilities = self.publisher.capabilities()
        publisher_v2_capabilities: dict[str, Any] = {
            "configured": publisher_v2_configured,
            "formalHandoff": False,
            "liveStatus": False,
            "liveReceipt": False,
            "networkExecution": False,
        }
        if publisher_v2_configured and publisher_v2_path is not None:
            try:
                publisher_v2_capabilities = PublisherV2Bridge(publisher_v2_path).capabilities()
            except ToolError as exc:
                publisher_v2_capabilities["reasonCode"] = exc.code
        publisher_upload_available = bool(
            publisher_capabilities.get("available", False)
            and publisher_v2_capabilities.get("formalHandoff", False)
        )
        configured_workshop_root = (self.config.workshop_isolation_root or (self.config.data_root / "workshop-isolation")).resolve()
        resolved_data_root = self.config.data_root.resolve()
        large_assets_under_data_root = (
            configured_workshop_root == resolved_data_root or resolved_data_root in configured_workshop_root.parents
        )
        return {
            "service": "ai-video-channel-local-tools",
            "serviceVersion": SERVICE_VERSION,
            "protocolVersion": LOCAL_TOOL_PROTOCOL_VERSION,
            "publisherInterface": publisher_capabilities,
            "publisherV2Bridge": publisher_v2_capabilities,
            "voiceCatalog": self.voices.capabilities(),
            "schemas": {
                "systemDatabase": SYSTEM_SCHEMA_VERSION,
                "channelDatabase": CHANNEL_SCHEMA_VERSION,
                "archiveFormat": ARCHIVE_FORMAT_VERSION,
                "sourceLibrary": SOURCE_LIBRARY_VERSION,
                "contentLoop": CONTENT_LOOP_VERSION,
                "contentAnalysis": CONTENT_ANALYSIS_VERSION,
                "videoCopyDeconstruction": VIDEO_DECONSTRUCTION_VERSION,
                "contentDeconstruction": VIDEO_DECONSTRUCTION_VERSION,
                "originalImitationWriting": ORIGINAL_IMITATION_VERSION,
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
                "userReviewDocumentIndex": REVIEW_DOCUMENT_SCHEMA_VERSION,
                "taskPromptContract": TASK_PROMPT_CONTRACT_VERSION,
                "creativeWorkspace": CREATIVE_WORKSPACE_VERSION,
            },
            "storage": {
                "userDataRoot": str(self.config.data_root),
                "channelsRoot": str(self.config.data_root / "channels"),
                "contentWorkspacesRoot": str(self.config.data_root / "content-workspaces"),
                "productionRoot": str(self.config.data_root / "production"),
                "workshopIsolationRoot": str(configured_workshop_root),
                "backupsRoot": str(self.config.data_root / "backups"),
                "largeAssetsStoredUnderUserDataRoot": large_assets_under_data_root,
                "programUpdatesPreserveUserDataRoot": True,
            },
            "capabilities": {
                "publisherChannelList": publisher_capabilities.get("available", False),
                "publisherReadOnlyInterfaceConfigured": publisher_capabilities.get("available", False),
                "publisherV2BridgeConfigured": publisher_v2_configured,
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
                "channelFreeCreativeWorkspace": True,
                "productionBindingOnlyAfterExplicitStart": True,
                "projectScopedAutoUploadAuthorization": True,
                "channelDistillation": True,
                "videoCopyDeconstruction": False,
                "contentDeconstruction": False,
                "directRewrite": False,
                "synthesisRewrite": False,
                "originalImitationWriting": False,
                "canonicalContentAnalysis": True,
                "contentPackageHandoffCheck": True,
                "userReadableReviewDocuments": True,
                "productionPackage": True,
                "productionTask": True,
                "productionResultPackage": True,
                "publishPackageAssembly": True,
                "publishPackageValidation": True,
                "publisherIsolatedImport": True,
                "publisherFormalHandoff": publisher_v2_capabilities.get("formalHandoff", False),
                "publisherLiveStatus": publisher_v2_capabilities.get("liveStatus", False),
                "workshop": self.production.workshop_bridge is not None,
                "upload": publisher_upload_available,
                "directUploadFromCodex": False,
                "directNetworkUpload": False,
                "formalPublisherHandoff": publisher_v2_capabilities.get("formalHandoff", False),
                "publisherLiveReceipt": publisher_v2_capabilities.get("liveReceipt", False),
                "publisherManagedUpload": publisher_v2_capabilities.get("formalHandoff", False),
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

    @staticmethod
    def _assert_persistent_video_generation_disabled(defaults: Any) -> None:
        video = defaults.get("videoGeneration") if isinstance(defaults, dict) else None
        if isinstance(video, dict) and (video.get("enabled") is True or video.get("selectionMode") != "none"):
            raise ToolError(
                "PERSISTENT_VIDEO_GENERATION_NOT_ALLOWED",
                "镜头视频生成不能保存为频道默认值；新项目固定为 enabled=false、selectionMode=none，只有当前任务明确指定镜头后才能临时开启。",
            )

    @staticmethod
    def _assert_current_image_style_selected(defaults: Any) -> None:
        image_style = defaults.get("imageStyle") if isinstance(defaults, dict) else None
        if not isinstance(image_style, dict):
            raise ToolError("IMAGE_STYLE_SELECTION_REQUIRED", "新频道必须明确选择当前图片风格预设或自定义画风。")
        preset_id = image_style.get("presetId")
        prompt = image_style.get("prompt")
        current_builtin = preset_id in {f"visual_{index:02d}" for index in range(1, 37)}
        custom = preset_id == "custom"
        if not (current_builtin or custom) or not isinstance(prompt, str) or not prompt.strip():
            raise ToolError("IMAGE_STYLE_SELECTION_REQUIRED", "图片风格必须使用 visual_01–visual_36 或非空自定义画风。")

    @staticmethod
    def _validate_task_video_generation_authorization(*, task_id: Any, overrides: Any, authorization: Any) -> None:
        video = overrides.get("videoGeneration") if isinstance(overrides, dict) else None
        if not isinstance(video, dict) or video.get("enabled") is not True:
            return
        expected = {"confirmed": True, "scope": "current_task", "taskId": task_id}
        if not isinstance(authorization, dict) or any(authorization.get(key) != value for key, value in expected.items()):
            raise ToolError(
                "VIDEO_GENERATION_AUTHORIZATION_REQUIRED",
                "只有用户在当前任务明确指定生成视频的镜头或范围后，才能临时开启视频生成。",
            )
        confirmation_ref = authorization.get("confirmationRef")
        if not isinstance(confirmation_ref, str) or not confirmation_ref.startswith(f"task:{task_id}:"):
            raise ToolError("VIDEO_GENERATION_AUTHORIZATION_REF_INVALID", "视频生成授权必须绑定当前任务。")

    def call(self, name: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
        args = arguments or {}
        if not isinstance(args, dict):
            raise ToolError("INVALID_ARGUMENT", "工具参数必须是对象。")
        if name.startswith(RETIRED_CONTENT_TOOL_PREFIXES):
            raise ToolError(
                "RETIRED_CONTENT_SKILL",
                "旧拆解与旧仿写方向能力已经移除；新任务不会执行或恢复这些工具。",
                details={"tool": name},
            )
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
            self._assert_persistent_video_generation_disabled(requested_defaults)
            self._assert_current_image_style_selected(requested_defaults)
            voice = requested_defaults.get("voice") if isinstance(requested_defaults, dict) else {}
            self.voices.validate_selection(voice.get("engineId"), voice.get("voiceId"))
            if requested_defaults.get("uploadPolicy") == "AUTO":
                raise ToolError(
                    "AUTO_UPLOAD_NOT_AVAILABLE_STAGE2",
                    "频道预设不能持久化自动上传；自动上传授权只允许绑定当前任务和当前项目。",
                )
            if args.get("executionMode", "review") != "review":
                raise ToolError(
                    "PERSISTENT_AUTO_MODE_NOT_ALLOWED",
                    "频道预设固定为审核模式；自动完成授权只能由用户在当前任务明确授予，不能持久化到频道。",
                )
            result = self.store.complete_library(
                task_id=args.get("taskId"),
                channel_profile_id=args.get("channelProfileId"),
                binding_proof=args.get("bindingProof"),
                defaults=requested_defaults,
                execution_mode="review",
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
            overrides = args.get("overrides")
            if overrides is None:
                overrides = {}
            if not isinstance(overrides, dict):
                raise ToolError("INVALID_OVERRIDE", "本次覆盖必须是对象。")
            self._validate_task_video_generation_authorization(
                task_id=args.get("taskId"),
                overrides=overrides,
                authorization=args.get("videoGenerationAuthorization"),
            )
            if not (
                isinstance(overrides.get("videoGeneration"), dict)
                and overrides["videoGeneration"].get("enabled") is True
            ):
                overrides = {
                    **overrides,
                    "videoGeneration": {
                        "enabled": False,
                        "selectionMode": "none",
                        "fallbackPolicy": "pause",
                    },
                }
            result = self.store.resolve_production(
                task_id=args.get("taskId"),
                channel_profile_id=args.get("channelProfileId"),
                binding_proof=args.get("bindingProof"),
                overrides=overrides,
            )
        elif name == "channel_update_defaults":
            requested_defaults = args.get("defaults")
            self._assert_persistent_video_generation_disabled(requested_defaults)
            self._assert_current_image_style_selected(requested_defaults)
            if isinstance(requested_defaults, dict) and requested_defaults.get("uploadPolicy") == "AUTO":
                raise ToolError(
                    "AUTO_UPLOAD_NOT_AVAILABLE_STAGE2",
                    "频道预设不能持久化自动上传；自动上传授权只允许绑定当前任务和当前项目。",
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
        elif name == "channel_distillation_capabilities":
            result = self.analysis.capabilities()
        elif name == "channel_distillation_prepare":
            result = self.analysis.prepare(
                task_id=args.get("taskId"),
                channel_profile_id=args.get("channelProfileId"),
                binding_proof=args.get("bindingProof"),
                distillation_id=args.get("distillationId"),
                mode=args.get("mode"),
                references=args.get("references"),
                previous_distillation_id=args.get("previousDistillationId"),
            )
        elif name == "channel_distillation_checkpoint":
            result = self.analysis.checkpoint(
                task_id=args.get("taskId"),
                channel_profile_id=args.get("channelProfileId"),
                binding_proof=args.get("bindingProof"),
                distillation_id=args.get("distillationId"),
                source_package_id=args.get("sourcePackageId"),
                status=args.get("status"),
                analysis=args.get("analysis"),
                failure=args.get("failure"),
            )
        elif name == "channel_distillation_finalize":
            result = self.analysis.finalize(
                task_id=args.get("taskId"),
                channel_profile_id=args.get("channelProfileId"),
                binding_proof=args.get("bindingProof"),
                distillation_id=args.get("distillationId"),
                profiles=args.get("profiles"),
                account_requirements=args.get("accountRequirements"),
                quality_gate=args.get("qualityGate"),
                fusion_profile=args.get("fusionProfile"),
            )
        elif name == "channel_distillation_get":
            result = self.analysis.get(
                channel_profile_id=args.get("channelProfileId"),
                distillation_id=args.get("distillationId"),
            )
        elif name == "channel_distillation_integrity_check":
            result = self.analysis.integrity_check(
                channel_profile_id=args.get("channelProfileId"),
                distillation_id=args.get("distillationId"),
            )
        elif name == "video_deconstruction_capabilities":
            result = self.video_analysis.capabilities()
        elif name == "video_deconstruction_prepare":
            result = self.video_analysis.prepare(
                task_id=args.get("taskId"),
                channel_profile_id=args.get("channelProfileId"),
                binding_proof=args.get("bindingProof"),
                deconstruction_id=args.get("deconstructionId"),
                mode=args.get("mode"),
                videos=args.get("videos"),
                distillation_id=args.get("distillationId"),
            )
        elif name == "video_deconstruction_read_source":
            result = self.video_analysis.read_source(
                task_id=args.get("taskId"),
                channel_profile_id=args.get("channelProfileId"),
                binding_proof=args.get("bindingProof"),
                deconstruction_id=args.get("deconstructionId"),
                source_package_id=args.get("sourcePackageId"),
                start_paragraph=args.get("startParagraph", 1),
                max_paragraphs=args.get("maxParagraphs", 60),
            )
        elif name == "video_deconstruction_checkpoint":
            result = self.video_analysis.checkpoint(
                task_id=args.get("taskId"),
                channel_profile_id=args.get("channelProfileId"),
                binding_proof=args.get("bindingProof"),
                deconstruction_id=args.get("deconstructionId"),
                source_package_id=args.get("sourcePackageId"),
                status=args.get("status"),
                analysis=args.get("analysis"),
                failure=args.get("failure"),
            )
        elif name == "video_deconstruction_finalize":
            result = self.video_analysis.finalize(
                task_id=args.get("taskId"),
                channel_profile_id=args.get("channelProfileId"),
                binding_proof=args.get("bindingProof"),
                deconstruction_id=args.get("deconstructionId"),
                quality_gate=args.get("qualityGate"),
                comparison=args.get("comparison"),
            )
        elif name == "video_deconstruction_get":
            result = self.video_analysis.get(
                channel_profile_id=args.get("channelProfileId"),
                deconstruction_id=args.get("deconstructionId"),
            )
        elif name == "video_deconstruction_integrity_check":
            result = self.video_analysis.integrity_check(
                channel_profile_id=args.get("channelProfileId"),
                deconstruction_id=args.get("deconstructionId"),
            )
        elif name == "content_deconstruction_capabilities":
            result = self.content_deconstruction.capabilities()
        elif name == "content_deconstruction_prepare":
            result = self.content_deconstruction.prepare(
                task_id=args.get("taskId"),
                channel_profile_id=args.get("channelProfileId"),
                binding_proof=args.get("bindingProof"),
                deconstruction_id=args.get("deconstructionId"),
                mode=args.get("mode"),
                videos=args.get("sources"),
            )
        elif name == "content_deconstruction_read_source":
            result = self.content_deconstruction.read_source(
                task_id=args.get("taskId"),
                channel_profile_id=args.get("channelProfileId"),
                binding_proof=args.get("bindingProof"),
                deconstruction_id=args.get("deconstructionId"),
                source_package_id=args.get("sourcePackageId"),
                start_paragraph=args.get("startParagraph", 1),
                max_paragraphs=args.get("maxParagraphs", 60),
            )
        elif name == "content_deconstruction_checkpoint":
            result = self.content_deconstruction.checkpoint(
                task_id=args.get("taskId"),
                channel_profile_id=args.get("channelProfileId"),
                binding_proof=args.get("bindingProof"),
                deconstruction_id=args.get("deconstructionId"),
                source_package_id=args.get("sourcePackageId"),
                status=args.get("status"),
                analysis=args.get("analysis"),
                failure=args.get("failure"),
            )
        elif name == "content_deconstruction_finalize":
            result = self.content_deconstruction.finalize(
                task_id=args.get("taskId"),
                channel_profile_id=args.get("channelProfileId"),
                binding_proof=args.get("bindingProof"),
                deconstruction_id=args.get("deconstructionId"),
                quality_gate=args.get("qualityGate"),
                comparison=args.get("comparison"),
                deconstruction_report=args.get("deconstructionReportMarkdown"),
                transfer_directions=args.get("transferDirectionsMarkdown"),
                direction_package=args.get("directionPackage"),
            )
        elif name == "content_deconstruction_get":
            result = self.content_deconstruction.get(
                channel_profile_id=args.get("channelProfileId"),
                deconstruction_id=args.get("deconstructionId"),
            )
        elif name == "content_deconstruction_integrity_check":
            result = self.content_deconstruction.integrity_check(
                channel_profile_id=args.get("channelProfileId"),
                deconstruction_id=args.get("deconstructionId"),
            )
        elif name == "original_imitation_capabilities":
            result = self.original_imitation.capabilities()
        elif name == "original_imitation_prepare":
            result = self.original_imitation.prepare(
                task_id=args.get("taskId"),
                channel_profile_id=args.get("channelProfileId"),
                binding_proof=args.get("bindingProof"),
                imitation_id=args.get("imitationId"),
                references=args.get("references"),
                distillation_id=args.get("distillationId"),
            )
        elif name == "original_imitation_read_source":
            result = self.original_imitation.read_source(
                task_id=args.get("taskId"),
                channel_profile_id=args.get("channelProfileId"),
                binding_proof=args.get("bindingProof"),
                imitation_id=args.get("imitationId"),
                source_package_id=args.get("sourcePackageId"),
                start_paragraph=args.get("startParagraph", 1),
                max_paragraphs=args.get("maxParagraphs", 60),
            )
        elif name == "original_imitation_source_checkpoint":
            result = self.original_imitation.source_checkpoint(
                task_id=args.get("taskId"),
                channel_profile_id=args.get("channelProfileId"),
                binding_proof=args.get("bindingProof"),
                imitation_id=args.get("imitationId"),
                source_package_id=args.get("sourcePackageId"),
                analysis=args.get("analysis"),
            )
        elif name == "original_imitation_direction_checkpoint":
            result = self.original_imitation.direction_checkpoint(
                task_id=args.get("taskId"),
                channel_profile_id=args.get("channelProfileId"),
                binding_proof=args.get("bindingProof"),
                imitation_id=args.get("imitationId"),
                direction_number=args.get("directionNumber"),
                direction=args.get("direction"),
            )
        elif name == "original_imitation_directions_finalize":
            result = self.original_imitation.directions_finalize(
                task_id=args.get("taskId"),
                channel_profile_id=args.get("channelProfileId"),
                binding_proof=args.get("bindingProof"),
                imitation_id=args.get("imitationId"),
                pairwise_distinctness=args.get("pairwiseDistinctness"),
                quality_gate=args.get("qualityGate"),
            )
        elif name == "original_imitation_confirm":
            result = self.original_imitation.confirm(
                task_id=args.get("taskId"),
                channel_profile_id=args.get("channelProfileId"),
                binding_proof=args.get("bindingProof"),
                imitation_id=args.get("imitationId"),
                direction_id=args.get("directionId"),
                confirmation=args.get("confirmation"),
            )
        elif name == "original_imitation_get":
            result = self.original_imitation.get(
                channel_profile_id=args.get("channelProfileId"),
                imitation_id=args.get("imitationId"),
            )
        elif name == "original_imitation_integrity_check":
            result = self.original_imitation.integrity_check(
                channel_profile_id=args.get("channelProfileId"),
                imitation_id=args.get("imitationId"),
            )
        elif name == "content_capabilities":
            result = self.content.capabilities()
            result["creativeWorkspace"] = {
                "version": CREATIVE_WORKSPACE_VERSION,
                "defaultBeforeProduction": True,
                "channelRequired": False,
                "channelListLookupAllowed": False,
                "productionBindingTrigger": "explicit-user-start-production",
                "draftingRoutes": ["direct-draft", "provided-outline"],
            }
        elif name == "content_workspace_start":
            result = self.creative_workspace.start(
                task_id=args.get("taskId"),
                project_id=args.get("projectId"),
                workspace_id=args.get("workspaceId"),
            )
        elif name == "content_workspace_prompt_register":
            result = self.creative_workspace.register_prompt(
                task_id=args.get("taskId"),
                workspace_id=args.get("workspaceId"),
                binding_proof=args.get("workspaceBindingProof"),
                prompt_id=args.get("promptId"),
                prompt_path=args.get("promptPath"),
                stage=args.get("stage"),
                purpose=args.get("purpose"),
                execution_order=args.get("executionOrder"),
                field_mappings=args.get("fieldMappings"),
                input_bindings=args.get("inputBindings"),
            )
        elif name == "content_workspace_document_save":
            result = self.creative_workspace.save_document(
                task_id=args.get("taskId"),
                workspace_id=args.get("workspaceId"),
                binding_proof=args.get("workspaceBindingProof"),
                document_id=args.get("documentId"),
                title=args.get("title"),
                stage=args.get("stage"),
                purpose=args.get("purpose"),
                language=args.get("language"),
                content=args.get("content"),
                media_type=args.get("mediaType", "text/markdown"),
                source_refs=args.get("sourceRefs"),
            )
        elif name == "content_workspace_document_confirm":
            result = self.creative_workspace.confirm_document(
                task_id=args.get("taskId"),
                workspace_id=args.get("workspaceId"),
                binding_proof=args.get("workspaceBindingProof"),
                document_id=args.get("documentId"),
                confirmation=args.get("confirmation"),
            )
        elif name == "content_workspace_document_reject":
            result = self.creative_workspace.reject_document(
                task_id=args.get("taskId"),
                workspace_id=args.get("workspaceId"),
                binding_proof=args.get("workspaceBindingProof"),
                document_id=args.get("documentId"),
                rejection=args.get("rejection"),
            )
        elif name == "content_workspace_auto_upload_authorize":
            result = self.creative_workspace.authorize_auto_upload(
                task_id=args.get("taskId"),
                workspace_id=args.get("workspaceId"),
                binding_proof=args.get("workspaceBindingProof"),
                authorization=args.get("authorization"),
            )
        elif name == "content_workspace_bind_production":
            result = self.creative_workspace.bind_for_production(
                task_id=args.get("taskId"),
                workspace_id=args.get("workspaceId"),
                binding_proof=args.get("workspaceBindingProof"),
                channel_profile_id=args.get("channelProfileId"),
                channel_binding_proof=args.get("channelBindingProof"),
                production_source_document_id=args.get("productionSourceDocumentId"),
                production_config=args.get("productionConfig"),
                confirmation=args.get("confirmation"),
            )
        elif name == "content_workspace_narration_prepare":
            result = self.creative_workspace.prepare_narration(
                task_id=args.get("taskId"),
                workspace_id=args.get("workspaceId"),
                binding_proof=args.get("workspaceBindingProof"),
                source_document_id=args.get("sourceDocumentId"),
                language=args.get("language"),
                narration_title=args.get("narrationTitle"),
                narration_title_chinese=args.get("narrationTitleChinese"),
                narration_content=args.get("narrationContent"),
                spoken_section_headings=args.get("spokenSectionHeadings", False),
                cleanup_report=args.get("cleanupReport"),
            )
        elif name == "content_workspace_get":
            result = self.creative_workspace.get(workspace_id=args.get("workspaceId"))
        elif name == "content_task_prompt_register":
            result = self.task_prompts.register(
                task_id=args.get("taskId"),
                channel_profile_id=args.get("channelProfileId"),
                binding_proof=args.get("bindingProof"),
                project_id=args.get("projectId"),
                prompt_id=args.get("promptId"),
                prompt_path=args.get("promptPath"),
                stage=args.get("stage"),
                purpose=args.get("purpose"),
                execution_order=args.get("executionOrder"),
                field_mappings=args.get("fieldMappings"),
                input_bindings=args.get("inputBindings"),
            )
        elif name == "content_task_prompts_get":
            self.store.assert_binding(
                task_id=args.get("taskId"),
                channel_profile_id=args.get("channelProfileId"),
                binding_proof=args.get("bindingProof"),
            )
            contracts = self.task_prompts.get_many(
                task_id=args.get("taskId"),
                channel_profile_id=args.get("channelProfileId"),
                project_id=args.get("projectId"),
                prompt_ids=args.get("promptIds"),
            )
            result = {
                "contracts": contracts,
                "promptReadPaths": [item["promptFile"]["absolutePath"] for item in contracts],
                "scope": "current_task_only",
                "skillInstalled": False,
            }
        elif name == "content_project_start":
            self.creative_workspace.assert_legacy_project_start_allowed(
                task_id=args.get("taskId"),
                channel_profile_id=args.get("channelProfileId"),
                production_handoff_path=args.get("creativeWorkspaceProductionHandoffPath"),
            )
            result = self.content.start_project(
                task_id=args.get("taskId"),
                channel_profile_id=args.get("channelProfileId"),
                binding_proof=args.get("bindingProof"),
                project_id=args.get("projectId"),
                source_mode=args.get("sourceMode"),
                source_packages=args.get("sourcePackages"),
                analysis_packages=args.get("analysisPackages"),
                writing_style_contracts=args.get("writingStyleContracts"),
                provided_outline=args.get("providedOutline"),
                learning_snapshot=args.get("learningSnapshot"),
                one_time_modifications=args.get("oneTimeModifications"),
                long_term_learning=args.get("longTermLearning"),
                task_prompt_contract_ids=args.get("taskPromptContractIds"),
                resume_existing_project=args.get("resumeExistingProject", False),
                resume_confirmation_ref=args.get("resumeConfirmationRef"),
            )
        elif name == "content_topic_checkpoint":
            result = self.content.checkpoint_topic(
                task_id=args.get("taskId"),
                channel_profile_id=args.get("channelProfileId"),
                binding_proof=args.get("bindingProof"),
                project_id=args.get("projectId"),
                candidate_number=args.get("candidateNumber"),
                candidate=args.get("candidate"),
                planning_confirmation=args.get("planningConfirmation"),
            )
        elif name == "content_planning_document_save":
            result = self.content.save_planning_document(
                task_id=args.get("taskId"),
                channel_profile_id=args.get("channelProfileId"),
                binding_proof=args.get("bindingProof"),
                project_id=args.get("projectId"),
                document_type=args.get("documentType"),
                content=args.get("content"),
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
        elif name == "content_review_document_save":
            result = self.content.save_review_document(
                task_id=args.get("taskId"),
                channel_profile_id=args.get("channelProfileId"),
                binding_proof=args.get("bindingProof"),
                project_id=args.get("projectId"),
                document_type=args.get("documentType"),
                content=args.get("content"),
            )
        elif name == "content_revision_begin":
            result = self.content.begin_revision(
                task_id=args.get("taskId"),
                channel_profile_id=args.get("channelProfileId"),
                binding_proof=args.get("bindingProof"),
                project_id=args.get("projectId"),
                scope=args.get("scope"),
                reason=args.get("reason"),
                requested_changes=args.get("requestedChanges"),
                confirmation=args.get("confirmation"),
            )
        elif name == "content_review_documents_get":
            result = self.content.get_review_documents(
                channel_profile_id=args.get("channelProfileId"),
                project_id=args.get("projectId"),
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
                foreign_language_quality_gate=args.get("foreignLanguageQualityGate"),
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
                title_source=args.get("titleSource"),
                title_candidates=args.get("titleCandidates"),
                description_body=args.get("descriptionBody"),
                description_chinese=args.get("descriptionChinese"),
                story_summary_chinese=args.get("storySummaryChinese"),
                hashtags=args.get("hashtags"),
                hashtag_translations=args.get("hashtagTranslations"),
                thumbnail_provider=args.get("thumbnailProvider"),
                thumbnail_strategy=args.get("thumbnailStrategy"),
                thumbnail_candidates=args.get("thumbnailCandidates"),
                selected_thumbnail_id=args.get("selectedThumbnailId"),
                thumbnail=args.get("thumbnail"),
                thumbnail_text_chinese=args.get("thumbnailTextChinese"),
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
            production_config = args.get("productionConfig")
            if not bool(args.get("synthetic", False)):
                self._validate_task_video_generation_authorization(
                    task_id=args.get("taskId"),
                    overrides={
                        "videoGeneration": production_config.get("videoGeneration")
                        if isinstance(production_config, dict)
                        else None
                    },
                    authorization=args.get("videoGenerationAuthorization"),
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
                production_config=production_config,
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
                normalized_authorization: dict[str, dict[str, Any]] = {}
                for key, value in authorization.items():
                    if key not in {"workspace", "channel", "intent", "project"} or not isinstance(value, dict):
                        continue
                    normalized = {
                        "granted": bool(value.get("granted", value.get("authorized", False))),
                        "version": value.get("version", ""),
                        "confirmed_at": value.get("confirmedAt", value.get("confirmed_at", "")),
                    }
                    if key == "project":
                        normalized.update(
                            {
                                "source": value.get("source"),
                                "scope": value.get("scope"),
                                "project_id": value.get("projectId", value.get("project_id")),
                                "upload_policy": value.get("uploadPolicy", value.get("upload_policy")),
                                "channel_serial": value.get("channelSerial", value.get("channel_serial")),
                                "privacy_status": value.get("privacyStatus", value.get("privacy_status")),
                                "confirmation_ref": value.get("confirmationRef", value.get("confirmation_ref")),
                                "revoked": value.get("revoked", False),
                            }
                        )
                    normalized_authorization[key] = normalized
                authorization = normalized_authorization
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
        elif name == "handoff_publish_package_v2":
            result = PublisherV2Bridge.from_arguments(args).handoff_package(args)
        elif name == "get_publication_status":
            result = PublisherV2Bridge.from_arguments(args).read_status(args, receipt=False)
        elif name == "get_publication_receipt":
            result = PublisherV2Bridge.from_arguments(args).read_status(args, receipt=True)
        elif name == "get_live_publication_status":
            result = PublisherV2Bridge.from_arguments(args).read_live_status(args, receipt=False)
        elif name == "get_live_publication_receipt":
            result = PublisherV2Bridge.from_arguments(args).read_live_status(args, receipt=True)
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
        return redact(normalize_confirmation_cards(result))

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
    workspace_binding_properties = {
        "taskId": {"type": "string", "minLength": 1, "maxLength": 160},
        "workspaceId": {"type": "string", "minLength": 3, "maxLength": 160},
        "workspaceBindingProof": {"type": "string", "minLength": 20, "maxLength": 256},
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
            "确认阶段 B 四项生产默认值并以固定审核模式原子创建独立频道资料库。",
            {
                **binding_properties,
                "defaults": {"type": "object"},
                "executionMode": {"type": "string", "enum": ["review"]},
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
            "读取长期默认并合并仅本次覆盖；镜头视频默认关闭，只有当前任务明确授权并指定范围后才临时开启。",
            {
                **binding_properties,
                "overrides": {"type": "object"},
                "videoGenerationAuthorization": {"type": "object"},
            },
            ["taskId", "channelProfileId", "bindingProof"],
        ),
        (
            "channel_update_defaults",
            "在明确频道级确认后生成新的生产预设版本，不改旧项目快照。",
            {
                **binding_properties,
                "defaults": {"type": "object"},
                "confirmation": {"type": "object"},
            },
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
            "channel_distillation_capabilities",
            "只读列出频道蒸馏平台、七阶段、契约、证据边界和下游接口。",
            {},
            [],
        ),
        (
            "channel_distillation_prepare",
            "冻结目标频道、参考频道身份、独立视频资料版本、模式、角色、权重与深拆样本计划。",
            {
                **binding_properties,
                "distillationId": {"type": "string"},
                "mode": {"type": "string", "enum": sorted(["single", "parallel", "compare", "fusion"])},
                "references": {"type": "array", "minItems": 1, "maxItems": 8},
                "previousDistillationId": {"type": "string"},
            },
            ["taskId", "channelProfileId", "bindingProof", "distillationId", "mode", "references"],
        ),
        (
            "channel_distillation_checkpoint",
            "逐视频独立保存深拆结果或失败；成功结果强制分开五类证据并覆盖完整频道分析维度。",
            {
                **binding_properties,
                "distillationId": {"type": "string"},
                "sourcePackageId": {"type": "string"},
                "status": {"type": "string", "enum": ["SUCCEEDED", "FAILED", "SKIPPED"]},
                "analysis": {"type": "object"},
                "failure": {"type": "object"},
            },
            ["taskId", "channelProfileId", "bindingProof", "distillationId", "sourcePackageId", "status"],
        ),
        (
            "channel_distillation_finalize",
            "聚合多条热门证据，分别冻结各参考频道画像、精简运行画像、账号专属拆解／仿写要求和下游 Analysis Package。",
            {
                **binding_properties,
                "distillationId": {"type": "string"},
                "profiles": {"type": "array", "minItems": 1, "maxItems": 8},
                "accountRequirements": {"type": "object"},
                "qualityGate": {"type": "object"},
                "fusionProfile": {"type": "object"},
            },
            ["taskId", "channelProfileId", "bindingProof", "distillationId", "profiles", "accountRequirements", "qualityGate"],
        ),
        (
            "channel_distillation_get",
            "只读查看频道蒸馏 7/7 进度、冻结输出与下游引用，不改变任何活动步骤。",
            {"channelProfileId": {"type": "string"}, "distillationId": {"type": "string"}},
            ["channelProfileId", "distillationId"],
        ),
        (
            "channel_distillation_integrity_check",
            "只读校验频道蒸馏状态、样本、画像、运行要求和契约哈希。",
            {"channelProfileId": {"type": "string"}, "distillationId": {"type": "string"}},
            ["channelProfileId", "distillationId"],
        ),
        (
            "video_deconstruction_capabilities",
            "只读列出视频文案拆解的模式、维度、契约、下游消费者和反复制边界。",
            {},
            [],
        ),
        (
            "video_deconstruction_prepare",
            "冻结目标频道、独立视频 Source Package、可选频道专属拆解要求和逐视频计划。",
            {
                **binding_properties,
                "deconstructionId": {"type": "string"},
                "mode": {"type": "string", "enum": sorted(["single", "parallel", "compare"])},
                "videos": {"type": "array", "minItems": 1, "maxItems": 8},
                "distillationId": {"type": "string"},
            },
            ["taskId", "channelProfileId", "bindingProof", "deconstructionId", "mode", "videos"],
        ),
        (
            "video_deconstruction_read_source",
            "按段落读取本次计划中已验收的 content.txt 与可选时间映射；不会读取或返回字幕文件。",
            {
                **binding_properties,
                "deconstructionId": {"type": "string"},
                "sourcePackageId": {"type": "string"},
                "startParagraph": {"type": "integer", "minimum": 1},
                "maxParagraphs": {"type": "integer", "minimum": 1, "maximum": 100},
            },
            ["taskId", "channelProfileId", "bindingProof", "deconstructionId", "sourcePackageId"],
        ),
        (
            "video_deconstruction_checkpoint",
            "逐视频独立冻结五类证据、功能区段、完整拆解维度、账号专属覆盖和质量门。",
            {
                **binding_properties,
                "deconstructionId": {"type": "string"},
                "sourcePackageId": {"type": "string"},
                "status": {"type": "string", "enum": ["SUCCEEDED", "FAILED", "SKIPPED"]},
                "analysis": {"type": "object"},
                "failure": {"type": "object"},
            },
            ["taskId", "channelProfileId", "bindingProof", "deconstructionId", "sourcePackageId", "status"],
        ),
        (
            "video_deconstruction_finalize",
            "冻结可交给选题中心与文稿中心的 Analysis Package v1；多视频保持独立，不求平均、不拼段。",
            {
                **binding_properties,
                "deconstructionId": {"type": "string"},
                "qualityGate": {"type": "object"},
                "comparison": {"type": "object"},
            },
            ["taskId", "channelProfileId", "bindingProof", "deconstructionId", "qualityGate"],
        ),
        (
            "video_deconstruction_get",
            "只读查看视频文案拆解进度和冻结输出，不改变任何视频状态。",
            {"channelProfileId": {"type": "string"}, "deconstructionId": {"type": "string"}},
            ["channelProfileId", "deconstructionId"],
        ),
        (
            "video_deconstruction_integrity_check",
            "只读校验视频资料锁、账号专属要求、逐视频拆解和 Analysis Package 哈希。",
            {"channelProfileId": {"type": "string"}, "deconstructionId": {"type": "string"}},
            ["channelProfileId", "deconstructionId"],
        ),
        (
            "content_deconstruction_capabilities",
            "只读列出统一文案拆解支持的视频字幕、用户文本、小说正文、拆解维度和下游边界。",
            {},
            [],
        ),
        (
            "content_deconstruction_prepare",
            "冻结一个或多个视频／文本 Source Package，建立单源、并列或比较拆解计划。",
            {
                **binding_properties,
                "deconstructionId": {"type": "string"},
                "mode": {"type": "string", "enum": sorted(["single", "parallel", "compare"])},
                "sources": {"type": "array", "minItems": 1, "maxItems": 8},
            },
            ["taskId", "channelProfileId", "bindingProof", "deconstructionId", "mode", "sources"],
        ),
        (
            "content_deconstruction_read_source",
            "按段读取本次计划中的唯一规范 content.txt 与可选时间映射，不读取原始字幕副本。",
            {
                **binding_properties,
                "deconstructionId": {"type": "string"},
                "sourcePackageId": {"type": "string"},
                "startParagraph": {"type": "integer", "minimum": 1},
                "maxParagraphs": {"type": "integer", "minimum": 1, "maximum": 100},
            },
            ["taskId", "channelProfileId", "bindingProof", "deconstructionId", "sourcePackageId"],
        ),
        (
            "content_deconstruction_checkpoint",
            "逐来源冻结五类证据、全文功能区段、结构节奏表达、原创边界和质量门。",
            {
                **binding_properties,
                "deconstructionId": {"type": "string"},
                "sourcePackageId": {"type": "string"},
                "status": {"type": "string", "enum": ["SUCCEEDED", "FAILED", "SKIPPED"]},
                "analysis": {"type": "object"},
                "failure": {"type": "object"},
            },
            ["taskId", "channelProfileId", "bindingProof", "deconstructionId", "sourcePackageId", "status"],
        ),
        (
            "content_deconstruction_finalize",
            "冻结来源证据驱动的 Content Deconstruction Package v1；必须含完整拆解文档、三档各5个方向和等待用户选择状态。",
            {
                **binding_properties,
                "deconstructionId": {"type": "string"},
                "qualityGate": {"type": "object"},
                "comparison": {"type": "object"},
                "deconstructionReportMarkdown": {"type": "string", "minLength": 200},
                "transferDirectionsMarkdown": {"type": "string", "minLength": 120},
                "directionPackage": {"type": "object"},
            },
            [
                "taskId", "channelProfileId", "bindingProof", "deconstructionId", "qualityGate",
                "deconstructionReportMarkdown", "transferDirectionsMarkdown", "directionPackage",
            ],
        ),
        (
            "content_deconstruction_get",
            "只读查看统一文案拆解进度和冻结输出，不改变任何来源状态。",
            {"channelProfileId": {"type": "string"}, "deconstructionId": {"type": "string"}},
            ["channelProfileId", "deconstructionId"],
        ),
        (
            "content_deconstruction_integrity_check",
            "只读校验来源锁、逐来源拆解、全文覆盖和 Content Deconstruction Package 哈希。",
            {"channelProfileId": {"type": "string"}, "deconstructionId": {"type": "string"}},
            ["channelProfileId", "deconstructionId"],
        ),
        (
            "original_imitation_capabilities",
            "只读列出原创仿写输入、8 方向、13 项评分、可信度、原创性与下游契约边界。",
            {},
            [],
        ),
        (
            "original_imitation_prepare",
            "冻结视频拆解包与规范化小说资料的角色、权重、版本和目标频道专属仿写要求。",
            {
                **binding_properties,
                "imitationId": {"type": "string"},
                "references": {"type": "array", "minItems": 1, "maxItems": 8},
                "distillationId": {"type": "string"},
            },
            ["taskId", "channelProfileId", "bindingProof", "imitationId", "references"],
        ),
        (
            "original_imitation_read_source",
            "按段落读取计划中的规范化小说 content.txt；YouTube 只消费已冻结视频拆解包。",
            {
                **binding_properties,
                "imitationId": {"type": "string"},
                "sourcePackageId": {"type": "string"},
                "startParagraph": {"type": "integer", "minimum": 1},
                "maxParagraphs": {"type": "integer", "minimum": 1, "maximum": 100},
            },
            ["taskId", "channelProfileId", "bindingProof", "imitationId", "sourcePackageId"],
        ),
        (
            "original_imitation_source_checkpoint",
            "逐个冻结直接小说／文本来源的五类证据、可迁移功能与原创边界。",
            {
                **binding_properties,
                "imitationId": {"type": "string"},
                "sourcePackageId": {"type": "string"},
                "analysis": {"type": "object"},
            },
            ["taskId", "channelProfileId", "bindingProof", "imitationId", "sourcePackageId", "analysis"],
        ),
        (
            "original_imitation_direction_checkpoint",
            "依次保存 8 个原创方向；逐项执行统一因果、10 问可信度、13 项评分与反复制硬门。",
            {
                **binding_properties,
                "imitationId": {"type": "string"},
                "directionNumber": {"type": "integer", "minimum": 1, "maximum": 8},
                "direction": {"type": "object"},
            },
            ["taskId", "channelProfileId", "bindingProof", "imitationId", "directionNumber", "direction"],
        ),
        (
            "original_imitation_directions_finalize",
            "校验 28 组实质差异，展示全部 8 个方向及评分并生成 TOP3，停在人工选择门。",
            {
                **binding_properties,
                "imitationId": {"type": "string"},
                "pairwiseDistinctness": {"type": "array", "minItems": 28, "maxItems": 28},
                "qualityGate": {"type": "object"},
            },
            ["taskId", "channelProfileId", "bindingProof", "imitationId", "pairwiseDistinctness", "qualityGate"],
        ),
        (
            "original_imitation_confirm",
            "仅在用户明确确认一个合格方向后冻结 Writing Style Contract v1，供选题与文稿中心继续使用。",
            {
                **binding_properties,
                "imitationId": {"type": "string"},
                "directionId": {"type": "string"},
                "confirmation": {"type": "object"},
            },
            ["taskId", "channelProfileId", "bindingProof", "imitationId", "directionId", "confirmation"],
        ),
        (
            "original_imitation_get",
            "只读查看原创仿写进度、8 方向评选或冻结契约，不改变确认状态。",
            {"channelProfileId": {"type": "string"}, "imitationId": {"type": "string"}},
            ["channelProfileId", "imitationId"],
        ),
        (
            "original_imitation_integrity_check",
            "只读校验来源锁、账号专属要求、方向文件和 Writing Style Contract 哈希。",
            {"channelProfileId": {"type": "string"}, "imitationId": {"type": "string"}},
            ["channelProfileId", "imitationId"],
        ),
        (
            "content_task_prompt_register",
            "仅供已进入生产绑定的兼容项目登记外部提示词；自由创作阶段改用 content_workspace_prompt_register，避免提前绑定频道。",
            {
                **binding_properties,
                "projectId": {"type": "string"},
                "promptId": {"type": "string"},
                "promptPath": {"type": "string"},
                "stage": {"type": "string", "enum": sorted(TASK_PROMPT_STAGES)},
                "purpose": {"type": "string", "minLength": 1, "maxLength": 240},
                "executionOrder": {"type": "integer", "minimum": 1, "maximum": 1000},
                "fieldMappings": {"type": "object", "additionalProperties": {"type": "string"}},
                "inputBindings": {"type": "array", "items": {"type": "string"}},
            },
            ["taskId", "channelProfileId", "bindingProof", "projectId", "promptId", "promptPath", "stage", "purpose", "executionOrder"],
        ),
        (
            "content_task_prompts_get",
            "按当前任务和项目读取临时提示词执行顺序、字段映射与原始文件路径；不返回其他任务合同，也不安装 Skill。",
            {
                **binding_properties,
                "projectId": {"type": "string"},
                "promptIds": {"type": "array", "items": {"type": "string"}},
            },
            ["taskId", "channelProfileId", "bindingProof", "projectId"],
        ),
        (
            "content_capabilities",
            "只读列出无频道自由创作、制作入口、阶段4内容路线及下游边界。",
            {},
            [],
        ),
        (
            "content_workspace_start",
            "为当前任务新建不绑定频道的自由创作工作区；不得读取频道列表、旧项目、旧频道学习或旧发布素材。",
            {
                "taskId": {"type": "string", "minLength": 1, "maxLength": 160},
                "projectId": {"type": "string", "minLength": 1, "maxLength": 160},
                "workspaceId": {"type": "string", "minLength": 3, "maxLength": 160},
            },
            ["taskId", "projectId"],
        ),
        (
            "content_workspace_prompt_register",
            "在无频道工作区登记用户本次临时提示词的路径、SHA-256、用途、顺序和映射；不复制正文、不安装 Skill。",
            {
                **workspace_binding_properties,
                "promptId": {"type": "string", "minLength": 1, "maxLength": 128},
                "promptPath": {"type": "string", "minLength": 1},
                "stage": {"type": "string", "enum": sorted(PROMPT_STAGES)},
                "purpose": {"type": "string", "minLength": 1, "maxLength": 240},
                "executionOrder": {"type": "integer", "minimum": 1, "maximum": 1000},
                "fieldMappings": {"type": "object", "additionalProperties": {"type": "string"}},
                "inputBindings": {"type": "array", "items": {"type": "string"}},
            },
            ["taskId", "workspaceId", "workspaceBindingProof", "promptId", "promptPath", "stage", "purpose", "executionOrder"],
        ),
        (
            "content_workspace_document_save",
            "按用户任意创作顺序保存版本化可查看文档；新版本默认未确认，不自动进入下一阶段或制作。",
            {
                **workspace_binding_properties,
                "documentId": {"type": "string", "minLength": 1, "maxLength": 128},
                "title": {"type": "string", "minLength": 1, "maxLength": 240},
                "stage": {"type": "string", "enum": sorted(DOCUMENT_STAGES)},
                "purpose": {"type": "string", "minLength": 1, "maxLength": 500},
                "language": {"type": "string", "minLength": 1, "maxLength": 32},
                "content": {"type": "string", "minLength": 1},
                "mediaType": {"type": "string", "enum": ["text/plain", "text/markdown", "application/json"]},
                "sourceRefs": {"type": "array", "items": {"type": "string"}},
            },
            ["taskId", "workspaceId", "workspaceBindingProof", "documentId", "title", "stage", "purpose", "language", "content"],
        ),
        (
            "content_workspace_document_confirm",
            "只确认当前工作区某一文档的当前版本与 SHA-256；不会自动开始制作。",
            {
                **workspace_binding_properties,
                "documentId": {"type": "string", "minLength": 1, "maxLength": 128},
                "confirmation": {"type": "object"},
            },
            ["taskId", "workspaceId", "workspaceBindingProof", "documentId", "confirmation"],
        ),
        (
            "content_workspace_document_reject",
            "把用户在当前任务明确否决的当前文档版本永久标记为不可复用；新写作必须保存真正的新版本。",
            {
                **workspace_binding_properties,
                "documentId": {"type": "string", "minLength": 1, "maxLength": 128},
                "rejection": {"type": "object"},
            },
            ["taskId", "workspaceId", "workspaceBindingProof", "documentId", "rejection"],
        ),
        (
            "content_workspace_auto_upload_authorize",
            "记录用户在当前任务对当前项目明确说出的自动上传授权；最终中文验收卡仍展示，但不重复等待确认。",
            {**workspace_binding_properties, "authorization": {"type": "object"}},
            ["taskId", "workspaceId", "workspaceBindingProof", "authorization"],
        ),
        (
            "content_workspace_bind_production",
            "仅在用户明确开始制作并确认频道号、正式文稿和生产配置后，将无频道工作区一次性绑定到目标频道并生成生产交接清单。",
            {
                **workspace_binding_properties,
                "channelProfileId": {"type": "string", "minLength": 3, "maxLength": 160},
                "channelBindingProof": {"type": "string", "minLength": 20, "maxLength": 256},
                "productionSourceDocumentId": {"type": "string", "minLength": 1, "maxLength": 128},
                "productionConfig": {"type": "object"},
                "confirmation": {"type": "object"},
            },
            ["taskId", "workspaceId", "workspaceBindingProof", "channelProfileId", "channelBindingProof", "productionSourceDocumentId", "productionConfig", "confirmation"],
        ),
        (
            "content_workspace_narration_prepare",
            "制作绑定完成后，把用户确认的正式稿整理为可直接配音的版本，并冻结一个默认直接用于发布的口播稿标题；不自动生成另一套标题。章节标题是否朗读必须使用本次制作设置，不能从旧项目继承。",
            {
                **workspace_binding_properties,
                "sourceDocumentId": {"type": "string", "minLength": 1, "maxLength": 128},
                "language": {"type": "string", "minLength": 1, "maxLength": 32},
                "narrationTitle": {"type": "string", "minLength": 1, "maxLength": 100},
                "narrationTitleChinese": {"type": "string", "minLength": 1, "maxLength": 200},
                "narrationContent": {"type": "string", "minLength": 1},
                "spokenSectionHeadings": {"type": "boolean"},
                "cleanupReport": {"type": "object"},
            },
            ["taskId", "workspaceId", "workspaceBindingProof", "sourceDocumentId", "language", "narrationTitle", "narrationContent"],
        ),
        (
            "content_workspace_get",
            "只读查看无频道自由创作工作区、已确认文档、自动上传授权和制作绑定状态。",
            {"workspaceId": {"type": "string", "minLength": 3, "maxLength": 160}},
            ["workspaceId"],
        ),
        (
            "content_project_start",
            "生产阶段兼容入口：只能在无频道工作区完成制作绑定后，用已确认内容建立频道内机器生产项目；自由创作阶段不得调用。",
            {
                **binding_properties,
                "projectId": {"type": "string"},
                "sourceMode": {"type": "string", "enum": sorted(SOURCE_MODES)},
                "sourcePackages": {"type": "array"},
                "analysisPackages": {"type": "array"},
                "writingStyleContracts": {"type": "array"},
                "taskPromptContractIds": {"type": "array", "items": {"type": "string"}},
                "providedOutline": {"type": "string"},
                "learningSnapshot": {"type": "object"},
                "oneTimeModifications": {"type": "array", "items": {"type": "string"}},
                "longTermLearning": {},
                "resumeExistingProject": {"type": "boolean"},
                "resumeConfirmationRef": {"type": "string"},
                "creativeWorkspaceProductionHandoffPath": {"type": "string"},
            },
            ["taskId", "channelProfileId", "bindingProof", "projectId", "sourceMode"],
        ),
        (
            "content_planning_document_save",
            "在 Topic Package 冻结前保存 01B 内容分析或 02 创作方案；任务级提示词正文仍留在用户文件中，不进入 Skill。",
            {
                **binding_properties,
                "projectId": {"type": "string"},
                "documentType": {"type": "string", "enum": ["source-analysis", "creative-plan"]},
                "content": {"type": "string", "minLength": 80},
            },
            ["taskId", "channelProfileId", "bindingProof", "projectId", "documentType", "content"],
        ),
        (
            "content_topic_checkpoint",
            "逐个保存一个真实完整候选；频道路线按 1/10 到 10/10 严格递增，不伪造检查点。",
            {**binding_properties, "projectId": {"type": "string"}, "candidateNumber": {"type": "integer", "minimum": 1, "maximum": 10}, "candidate": {"type": "object"}, "planningConfirmation": {"type": "object"}},
            ["taskId", "channelProfileId", "bindingProof", "projectId", "candidateNumber", "candidate"],
        ),
        (
            "content_topic_finalize",
            "校验完整候选、七项评分、排名与 G3 确认后冻结 Topic Package v1。",
            {**binding_properties, "projectId": {"type": "string"}, "ranking": {"type": "array"}, "selectedCandidateId": {"type": "string"}, "selectionReasons": {"type": "object"}, "confirmation": {"type": "object"}},
            ["taskId", "channelProfileId", "bindingProof", "projectId", "ranking", "selectedCandidateId", "selectionReasons", "confirmation"],
        ),
        (
            "content_revision_begin",
            "仅在当前任务获得针对本项目和修改范围的明确确认后开启增量修订；保留旧版本供追溯，并使受影响的下游包失效。",
            {
                **binding_properties,
                "projectId": {"type": "string"},
                "scope": {"type": "string", "enum": ["creative-plan", "topic", "manuscript", "publishing"]},
                "reason": {"type": "string", "minLength": 1},
                "requestedChanges": {"type": "array", "minItems": 1, "items": {"type": "string", "minLength": 1}},
                "confirmation": {"type": "object"},
            },
            ["taskId", "channelProfileId", "bindingProof", "projectId", "scope", "reason", "requestedChanges", "confirmation"],
        ),
        (
            "content_review_document_save",
            "把完整仿写初稿、编辑审核报告或修改前后对照立即保存为用户可直接查看的版本化文档。",
            {
                **binding_properties,
                "projectId": {"type": "string"},
                "documentType": {
                    "type": "string",
                    "enum": ["rewrite-draft-target", "rewrite-draft-zh", "editorial-review", "revision-log"],
                },
                "content": {"type": "string", "minLength": 40},
            },
            ["taskId", "channelProfileId", "bindingProof", "projectId", "documentType", "content"],
        ),
        (
            "content_review_documents_get",
            "只读列出项目的用户审核文档、当前版本、可点击绝对路径、SHA-256、用途边界和来源合同绑定；自动模式也必须向用户展示新增文档。",
            {"channelProfileId": {"type": "string"}, "projectId": {"type": "string"}},
            ["channelProfileId", "projectId"],
        ),
        (
            "content_manuscript_finalize",
            "校验目标语言原生母稿、逐行中文审核映射、角色音色、合并质量门和独立外语质量保险门后冻结 Manuscript Package v1，并生成绑定该包的 07 正式口播稿与 08 中文审核稿。",
            {**binding_properties, "projectId": {"type": "string"}, "storyBible": {"type": "object"}, "characters": {"type": "array"}, "targetScript": {"type": "array"}, "chineseAuditScript": {"type": ["array", "null"]}, "qualityGate": {"type": "object"}, "foreignLanguageQualityGate": {"type": "object"}, "confirmation": {"type": "object"}, "authoringMode": {"type": "string"}},
            ["taskId", "channelProfileId", "bindingProof", "projectId", "storyBible", "characters", "targetScript", "qualityGate", "foreignLanguageQualityGate", "confirmation"],
        ),
        (
            "content_publishing_finalize",
            "只读取确认母稿并默认继承口播稿标题。简介、Hashtags 和自定义封面全部可选：只有用户明确提供或要求生成时才接收；未要求自定义封面时冻结 youtube_auto，不调用封面生成或 thumbnails.set。",
            {**binding_properties, "projectId": {"type": "string"}, "title": {"type": "string"}, "titleChinese": {"type": "string"}, "titleSource": {"type": "string", "enum": ["confirmed_narration", "user_confirmed", "generated_candidates"]}, "titleCandidates": {"type": "array", "minItems": 1, "maxItems": 6}, "descriptionBody": {"type": "string"}, "descriptionChinese": {"type": "string"}, "storySummaryChinese": {"type": "string"}, "hashtags": {"type": "array"}, "hashtagTranslations": {"type": "array"}, "thumbnailProvider": {"type": "object"}, "thumbnailStrategy": {"type": "object"}, "thumbnailCandidates": {"type": "array", "minItems": 5, "maxItems": 5}, "selectedThumbnailId": {"type": "string"}, "thumbnail": {"type": "object"}, "thumbnailTextChinese": {"type": "string"}, "ctrReview": {"type": "object"}, "confirmation": {"type": "object"}},
            ["taskId", "channelProfileId", "bindingProof", "projectId", "title", "titleChinese", "storySummaryChinese", "confirmation"],
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
            "从已确认的 Manuscript 与 Publishing Asset 组装 Production Package v2.1；开启图片或视频提示词时，必须由 Codex 在 productionConfig.codexVisualPlan 中提交漫画角色设计、故事画面规划、复杂度自适应页数、镜头构图、情绪爆点可见信号、连续性绑定、预算内图片提示词和可选视频提示词，工坊锁定执行且不得重写。硬门同时校验 07 正式口播稿与机器生产脚本逐字一致、08 中文稿仅供审核，并生成生产包总览与可查看视觉方案文档。",
            {
                **binding_properties,
                "projectId": {"type": "string"},
                "productionConfig": {"type": "object"},
                "productionPreset": {"type": "object"},
                "workshopCompatibility": {"type": "object"},
                "videoGenerationAuthorization": {"type": "object"},
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
            "把真实 .ready 包本地移交正式发布中心，或在显式测试模式导入隔离数据库；本调用不执行网络上传。",
            {
                "publisherCliPath": {"type": "string"},
                "packagePath": {"type": "string"},
                "handoffMode": {"type": "string", "enum": ["formal", "isolated"]},
                "publisherDataDir": {"type": "string"},
                "inboxPath": {"type": "string"},
                "databasePath": {"type": "string"},
                "isolationRoot": {"type": "string"},
                "channelCliPath": {"type": "string"},
                "channelDatabasePath": {"type": "string"},
                "syntheticChannelProfilePath": {"type": "string"},
                "ffprobePath": {"type": "string"},
                "networkExecution": {"const": False},
            },
            ["publisherCliPath", "packagePath", "networkExecution"],
        ),
        (
            "handoff_publish_package_v2",
            "在当前任务完成 G6 最终中文验收后，把 AUTO 发布包正式交接给发布中心；本工具只写本地 READY 状态，不直接执行网络上传。",
            {
                "publisherCliPath": {"type": "string"},
                "publisherDataPath": {"type": "string"},
                "packagePath": {"type": "string"},
                "finalReviewApproval": {"type": "object"},
                "networkExecution": {"const": False},
            },
            ["publisherCliPath", "packagePath", "finalReviewApproval", "networkExecution"],
        ),
        (
            "get_publication_status",
            "从隔离发布中心 SQLite 只读查询本地或真实状态，不推进任务。",
            {
                "publisherCliPath": {"type": "string"},
                "handoffMode": {"type": "string", "enum": ["formal", "isolated"]},
                "publisherDataDir": {"type": "string"},
                "databasePath": {"type": "string"},
                "isolationRoot": {"type": "string"},
                "publishIntentId": {"type": "string"},
                "networkExecution": {"const": False},
            },
            ["publisherCliPath", "publishIntentId", "networkExecution"],
        ),
        (
            "get_live_publication_status",
            "从正式发布中心只读查询真实任务状态，不推进任务。",
            {
                "publisherCliPath": {"type": "string"},
                "publisherDataPath": {"type": "string"},
                "publishIntentId": {"type": "string"},
                "networkExecution": {"const": False},
            },
            ["publisherCliPath", "publishIntentId", "networkExecution"],
        ),
        (
            "get_live_publication_receipt",
            "从正式发布中心只读获取真实 YouTube 回执；没有 video ID 时返回 not_available。",
            {
                "publisherCliPath": {"type": "string"},
                "publisherDataPath": {"type": "string"},
                "publishIntentId": {"type": "string"},
                "networkExecution": {"const": False},
            },
            ["publisherCliPath", "publishIntentId", "networkExecution"],
        ),
        (
            "get_publication_receipt",
            "只读获取真实发布回执；没有真实 YouTube video ID 时明确返回 not_available。",
            {
                "publisherCliPath": {"type": "string"},
                "handoffMode": {"type": "string", "enum": ["formal", "isolated"]},
                "publisherDataDir": {"type": "string"},
                "databasePath": {"type": "string"},
                "isolationRoot": {"type": "string"},
                "publishIntentId": {"type": "string"},
                "networkExecution": {"const": False},
            },
            ["publisherCliPath", "publishIntentId", "networkExecution"],
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
        if not name.startswith(RETIRED_CONTENT_TOOL_PREFIXES)
    ]
