from __future__ import annotations

import json
import os
import subprocess
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from .errors import ToolError
from .security import contains_sensitive_material, redact


PUBLISHER_PROTOCOL_VERSION = "1.0.0"
PUBLISHER_CENTER_API_VERSION = "youtube-publisher-center/channel-list/v1"
MAX_PROVIDER_OUTPUT_BYTES = 1024 * 1024


class PublisherChannelProvider(Protocol):
    def capabilities(self) -> dict[str, Any]: ...
    def list_channels(self) -> list[dict[str, Any]]: ...


def _validate_channel(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise ToolError("PUBLISHER_RESPONSE_INVALID", "发布中心返回了无效频道记录。")
    if contains_sensitive_material(raw):
        raise ToolError("PUBLISHER_RESPONSE_UNSAFE", "发布中心响应包含不允许进入 Codex 的敏感字段。")
    required = ("publisherProfileId", "channelSerial", "youtubeChannelId", "displayName")
    for key in required:
        if not isinstance(raw.get(key), str) or not raw[key].strip():
            raise ToolError("PUBLISHER_RESPONSE_INVALID", f"发布中心频道记录缺少 {key}。")
    if not raw["channelSerial"].isdigit() or len(raw["channelSerial"]) < 2:
        raise ToolError("PUBLISHER_RESPONSE_INVALID", "channelSerial 格式无效。")
    allowed = {
        "publisherProfileId", "channelSerial", "youtubeChannelId", "displayName", "thumbnailUrl",
        "enabled", "authorizationStatus", "defaultLanguage", "privacyStatus", "uploadMode", "timeZone",
        "publishTime", "uploadLimit", "uploadPolicy", "interfaceVersion",
    }
    channel = {key: raw[key] for key in allowed if key in raw}
    channel.setdefault("enabled", True)
    channel.setdefault("authorizationStatus", "UNKNOWN")
    return channel


@dataclass(slots=True)
class UnconfiguredPublisherProvider:
    def capabilities(self) -> dict[str, Any]:
        return {
            "available": False,
            "protocolVersion": PUBLISHER_PROTOCOL_VERSION,
            "reasonCode": "PUBLISHER_INTERFACE_UNAVAILABLE",
        }

    def list_channels(self) -> list[dict[str, Any]]:
        raise ToolError(
            "PUBLISHER_INTERFACE_UNAVAILABLE",
            "尚未配置 YouTube 发布中心只读频道接口，请先安装或修复发布中心。",
            retryable=True,
        )


@dataclass(slots=True)
class CommandPublisherProvider:
    command: tuple[str, ...]
    timeout_seconds: float = 8.0

    def capabilities(self) -> dict[str, Any]:
        return {
            "available": True,
            "protocolVersion": PUBLISHER_PROTOCOL_VERSION,
            "transport": "subprocess-json-v1",
            "timeoutSeconds": self.timeout_seconds,
        }

    def list_channels(self) -> list[dict[str, Any]]:
        request = {
            "protocolVersion": PUBLISHER_PROTOCOL_VERSION,
            "requestId": str(uuid.uuid4()),
            "operation": "listChannels",
        }
        try:
            completed = subprocess.run(
                list(self.command),
                input=json.dumps(request, ensure_ascii=False),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=self.timeout_seconds,
                shell=False,
                check=False,
                env={**os.environ, "AIVCP_CALLER": "local-tool-service"},
            )
        except subprocess.TimeoutExpired as exc:
            raise ToolError(
                "PUBLISHER_TIMEOUT",
                "发布中心频道读取超时。",
                retryable=True,
                details={"timeoutSeconds": self.timeout_seconds},
            ) from exc
        except OSError as exc:
            raise ToolError(
                "PUBLISHER_START_FAILED",
                "无法启动发布中心只读接口。",
                retryable=True,
                details={"osError": type(exc).__name__},
            ) from exc
        if len(completed.stdout.encode("utf-8")) > MAX_PROVIDER_OUTPUT_BYTES:
            raise ToolError("PUBLISHER_RESPONSE_TOO_LARGE", "发布中心响应超过安全上限。")
        if completed.returncode != 0:
            raise ToolError(
                "PUBLISHER_CALL_FAILED",
                "发布中心只读接口调用失败。",
                retryable=True,
                details={"exitCode": completed.returncode, "diagnostic": redact(completed.stderr[-500:])},
            )
        try:
            response = json.loads(completed.stdout)
        except json.JSONDecodeError as exc:
            raise ToolError("PUBLISHER_RESPONSE_INVALID", "发布中心返回的不是有效 JSON。") from exc
        if not isinstance(response, dict) or response.get("protocolVersion") != PUBLISHER_PROTOCOL_VERSION:
            raise ToolError("PUBLISHER_PROTOCOL_MISMATCH", "发布中心接口协议版本不兼容。")
        channels = response.get("channels")
        if not isinstance(channels, list):
            raise ToolError("PUBLISHER_RESPONSE_INVALID", "发布中心响应缺少 channels 数组。")
        validated = [_validate_channel(item) for item in channels]
        ids = [item["youtubeChannelId"] for item in validated]
        if len(ids) != len(set(ids)):
            raise ToolError("PUBLISHER_IDENTITY_CONFLICT", "发布中心返回了重复的真实 YouTube 频道。")
        return validated


@dataclass(slots=True)
class PublisherCenterCliV1Provider:
    """Adapter for the frozen 03A read-only publisher-center CLI."""

    command: tuple[str, ...]
    timeout_seconds: float = 8.0

    def capabilities(self) -> dict[str, Any]:
        return {
            "available": True,
            "protocolVersion": PUBLISHER_PROTOCOL_VERSION,
            "publisherApiVersion": PUBLISHER_CENTER_API_VERSION,
            "transport": "publisher-center-cli-v1",
            "timeoutSeconds": self.timeout_seconds,
        }

    def list_channels(self) -> list[dict[str, Any]]:
        command = list(self.command)
        if "--api-version" not in command and not any(item.startswith("--api-version=") for item in command):
            command.extend(["--api-version", "v1"])
        try:
            completed = subprocess.run(
                command,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=self.timeout_seconds,
                shell=False,
                check=False,
                env={**os.environ, "AIVCP_CALLER": "local-tool-service"},
            )
        except subprocess.TimeoutExpired as exc:
            raise ToolError(
                "PUBLISHER_TIMEOUT",
                "发布中心频道读取超时。",
                retryable=True,
                details={"timeoutSeconds": self.timeout_seconds},
            ) from exc
        except OSError as exc:
            raise ToolError(
                "PUBLISHER_START_FAILED",
                "无法启动发布中心只读频道清单程序。",
                retryable=True,
                details={"osError": type(exc).__name__},
            ) from exc
        if len(completed.stdout.encode("utf-8")) > MAX_PROVIDER_OUTPUT_BYTES:
            raise ToolError("PUBLISHER_RESPONSE_TOO_LARGE", "发布中心响应超过安全上限。")
        try:
            response = json.loads(completed.stdout)
        except json.JSONDecodeError as exc:
            raise ToolError(
                "PUBLISHER_RESPONSE_INVALID",
                "发布中心只读程序没有返回有效 JSON。",
                retryable=completed.returncode in {3, 4, 5},
                details={"exitCode": completed.returncode},
            ) from exc
        if contains_sensitive_material(response):
            raise ToolError("PUBLISHER_RESPONSE_UNSAFE", "发布中心响应包含不允许进入 Codex 的敏感字段。")
        if not isinstance(response, dict) or response.get("apiVersion") != PUBLISHER_CENTER_API_VERSION:
            raise ToolError("PUBLISHER_PROTOCOL_MISMATCH", "发布中心频道清单接口版本不兼容。")
        if response.get("status") == "ERROR":
            error = response.get("error") if isinstance(response.get("error"), dict) else {}
            raise ToolError(
                str(error.get("code") or "PUBLISHER_CALL_FAILED"),
                str(error.get("message") or "发布中心只读频道清单调用失败。"),
                retryable=bool(error.get("retryable")),
                details={"publisherExitCode": completed.returncode},
            )
        if completed.returncode != 0 or response.get("status") != "OK":
            raise ToolError(
                "PUBLISHER_CALL_FAILED",
                "发布中心只读频道清单调用失败。",
                retryable=completed.returncode in {3, 4, 5},
                details={"publisherExitCode": completed.returncode},
            )
        channels = response.get("channels")
        if not isinstance(channels, list) or response.get("channelCount") != len(channels):
            raise ToolError("PUBLISHER_RESPONSE_INVALID", "发布中心 channelCount 与频道清单不一致。")
        mapped = []
        for raw in channels:
            if not isinstance(raw, dict):
                raise ToolError("PUBLISHER_RESPONSE_INVALID", "发布中心返回了无效频道记录。")
            expected = {
                "publisherProfileId", "channelSerial", "youtubeChannelId", "channelName", "enabled",
                "authorizationStatus", "defaultPrivacy", "timezone", "uploadPolicy",
            }
            if set(raw) != expected:
                raise ToolError("PUBLISHER_RESPONSE_INVALID", "发布中心频道字段与 v1 白名单不一致。")
            mapped.append(
                _validate_channel(
                    {
                        "publisherProfileId": raw["publisherProfileId"],
                        "channelSerial": raw["channelSerial"],
                        "youtubeChannelId": raw["youtubeChannelId"],
                        "displayName": raw["channelName"],
                        "enabled": raw["enabled"],
                        "authorizationStatus": raw["authorizationStatus"],
                        "privacyStatus": raw["defaultPrivacy"],
                        "timeZone": raw["timezone"],
                        "uploadPolicy": raw["uploadPolicy"],
                        "interfaceVersion": PUBLISHER_CENTER_API_VERSION,
                    }
                )
            )
        identities = [
            (item["publisherProfileId"], item["channelSerial"], item["youtubeChannelId"])
            for item in mapped
        ]
        for position in range(3):
            values = [identity[position] for identity in identities]
            if len(values) != len(set(values)):
                raise ToolError("PUBLISHER_IDENTITY_CONFLICT", "发布中心返回了重复频道身份。")
        return mapped


@dataclass(slots=True)
class FixturePublisherProvider:
    fixture_path: Path

    def capabilities(self) -> dict[str, Any]:
        return {
            "available": True,
            "protocolVersion": PUBLISHER_PROTOCOL_VERSION,
            "transport": "test-fixture",
            "testOnly": True,
        }

    def list_channels(self) -> list[dict[str, Any]]:
        try:
            document = json.loads(self.fixture_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ToolError("TEST_FIXTURE_INVALID", "测试频道夹具不可读。") from exc
        channels = document.get("channels") if isinstance(document, dict) else None
        if not isinstance(channels, list):
            raise ToolError("TEST_FIXTURE_INVALID", "测试夹具缺少 channels 数组。")
        return [_validate_channel(item) for item in channels]


def provider_from_environment(data_root: Path | None = None) -> PublisherChannelProvider:
    fixture = os.environ.get("AIVCP_TEST_PUBLISHER_FIXTURE")
    if fixture:
        if os.environ.get("AIVCP_ALLOW_TEST_FIXTURES") != "1":
            raise ToolError("TEST_FIXTURE_FORBIDDEN", "只有显式隔离测试模式可以使用频道夹具。")
        return FixturePublisherProvider(Path(fixture).resolve())
    cli_json = os.environ.get("AIVCP_PUBLISHER_CHANNEL_LIST_COMMAND_JSON")
    cli_exe = os.environ.get("AIVCP_PUBLISHER_CHANNEL_LIST_EXE")
    if not cli_json and not cli_exe:
        configured_path = os.environ.get("AIVCP_PUBLISHER_INTERFACE_CONFIG")
        config_path = Path(configured_path).resolve() if configured_path else None
        if config_path is None and data_root is not None:
            config_path = data_root.resolve().parent / "config" / "publisher-interface.json"
        if config_path and config_path.is_file():
            try:
                configured = json.loads(config_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise ToolError("PUBLISHER_CONFIG_INVALID", "发布中心接口发现文件不可读。") from exc
            if not isinstance(configured, dict) or configured.get("schemaVersion") != "1.0.0":
                raise ToolError("PUBLISHER_CONFIG_INVALID", "发布中心接口发现文件版本不受支持。")
            if configured.get("apiVersion") != PUBLISHER_CENTER_API_VERSION:
                raise ToolError("PUBLISHER_PROTOCOL_MISMATCH", "发布中心接口发现文件声明了不兼容版本。")
            command = configured.get("command")
            if not isinstance(command, list) or not command or not all(isinstance(item, str) and item for item in command):
                raise ToolError("PUBLISHER_CONFIG_INVALID", "发布中心接口发现文件缺少安全命令数组。")
            cli_json = json.dumps(command)
    if cli_json or cli_exe:
        try:
            parsed_cli = json.loads(cli_json) if cli_json else [cli_exe]
        except json.JSONDecodeError as exc:
            raise ToolError("PUBLISHER_CONFIG_INVALID", "发布中心只读命令配置不是有效 JSON。") from exc
        if not isinstance(parsed_cli, list) or not parsed_cli or not all(isinstance(item, str) and item for item in parsed_cli):
            raise ToolError("PUBLISHER_CONFIG_INVALID", "发布中心只读命令必须是非空字符串数组。")
        timeout = float(os.environ.get("AIVCP_PUBLISHER_TIMEOUT_SECONDS", "8"))
        return PublisherCenterCliV1Provider(tuple(parsed_cli), timeout_seconds=max(0.1, min(timeout, 60.0)))
    command_json = os.environ.get("AIVCP_PUBLISHER_COMMAND_JSON")
    if not command_json:
        return UnconfiguredPublisherProvider()
    try:
        parsed = json.loads(command_json)
    except json.JSONDecodeError as exc:
        raise ToolError("PUBLISHER_CONFIG_INVALID", "发布中心命令配置不是有效 JSON。") from exc
    if not isinstance(parsed, list) or not parsed or not all(isinstance(item, str) and item for item in parsed):
        raise ToolError("PUBLISHER_CONFIG_INVALID", "发布中心命令必须是非空字符串数组。")
    timeout = float(os.environ.get("AIVCP_PUBLISHER_TIMEOUT_SECONDS", "8"))
    return CommandPublisherProvider(tuple(parsed), timeout_seconds=max(0.1, min(timeout, 60.0)))
