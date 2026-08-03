from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .errors import ToolError
from .publisher import PUBLISHER_PROTOCOL_VERSION, PublisherChannelProvider, provider_from_environment
from .security import redact
from .store import ARCHIVE_FORMAT_VERSION, CHANNEL_SCHEMA_VERSION, SYSTEM_SCHEMA_VERSION, ChannelStore
from .voices import VoiceCatalog


LOCAL_TOOL_PROTOCOL_VERSION = "1.0.0"
SERVICE_VERSION = "0.2.0-dev.1"


def default_data_root(plugin_root: Path | None = None) -> Path:
    configured = os.environ.get("AIVCP_DATA_ROOT")
    if configured:
        return Path(configured).expanduser().resolve()
    if plugin_root:
        resolved = plugin_root.resolve()
        current = resolved.parents[1] if len(resolved.parents) > 1 else None
        if current and current.name == "current" and (current / "install-state.json").is_file():
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

    @classmethod
    def from_environment(cls, plugin_root: Path | None = None) -> "ServiceConfig":
        configured_catalog = os.environ.get("AIVCP_VOICE_CATALOG")
        catalog_path = Path(configured_catalog).resolve() if configured_catalog else None
        if catalog_path is None and plugin_root:
            candidate = plugin_root / "assets" / "voice-catalog.json"
            catalog_path = candidate if candidate.is_file() else None
        return cls(data_root=default_data_root(plugin_root), plugin_root=plugin_root, voice_catalog_path=catalog_path)


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
                "channelProfileContract": "1.0.0",
                "productionProfileContract": "1.0.0",
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
                "sourceCollection": False,
                "contentProduction": False,
                "workshop": False,
                "upload": False,
                "analytics": False,
            },
            "security": {
                "privateMaterialAccepted": False,
                "publisherPrivateMaterialVisible": False,
                "providerResponseAllowlist": True,
                "taskBindingProofRequiredForWrites": True,
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
        else:
            raise ToolError("TOOL_NOT_FOUND", "本地工具服务没有该工具。", details={"tool": name})
        return redact(result)


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
    ]
    return [
        {
            "name": name,
            "description": description,
            "inputSchema": {**object_schema, "properties": properties, "required": required},
        }
        for name, description, properties, required in definitions
    ]
