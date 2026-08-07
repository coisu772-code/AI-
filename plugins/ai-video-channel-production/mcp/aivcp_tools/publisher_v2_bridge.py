from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any

from .errors import ToolError


MAX_OUTPUT_BYTES = 2 * 1024 * 1024


def _path(value: Any, *, field: str, must_exist: bool = True, file: bool | None = None) -> Path:
    if not isinstance(value, str) or not value.strip():
        raise ToolError("PUBLISHER_ARGUMENT_INVALID", f"{field} 是必填路径。")
    raw = Path(value).expanduser()
    if raw.is_symlink():
        raise ToolError("PUBLISHER_SYMLINK_FORBIDDEN", f"{field} 不得是符号链接。")
    try:
        resolved = raw.resolve(strict=must_exist)
    except OSError as exc:
        raise ToolError("PUBLISHER_PATH_INVALID", f"{field} 路径无效。") from exc
    if must_exist and file is True and not resolved.is_file():
        raise ToolError("PUBLISHER_PATH_INVALID", f"{field} 必须是文件。")
    if must_exist and file is False and not resolved.is_dir():
        raise ToolError("PUBLISHER_PATH_INVALID", f"{field} 必须是目录。")
    return resolved


def _within(root: Path, target: Path, *, field: str) -> None:
    try:
        target.relative_to(root)
    except ValueError as exc:
        raise ToolError("PUBLISHER_ISOLATION_BOUNDARY", f"{field} 必须位于明确隔离根目录内。") from exc


class PublisherV2Bridge:
    """Thin offline-only adapter for the isolated Go publisher v2 CLI."""

    def __init__(self, executable: Path):
        self.executable = executable

    @classmethod
    def from_arguments(cls, arguments: dict[str, Any]) -> "PublisherV2Bridge":
        configured = arguments.get("publisherCliPath") or os.environ.get("AIVCP_PUBLISHER_V2_CLI")
        executable = _path(configured, field="publisherCliPath", file=True)
        if executable.name.lower() != "publish-package-v2.exe":
            raise ToolError("PUBLISHER_CLI_IDENTITY_INVALID", "只允许使用隔离构建 publish-package-v2.exe。")
        return cls(executable)

    @staticmethod
    def assert_offline(arguments: dict[str, Any]) -> None:
        if arguments.get("networkExecution") is not False:
            raise ToolError("PUBLISHER_NETWORK_EXECUTION_FORBIDDEN", "Stage6 工具必须显式传入 networkExecution=false。")

    def _run(self, operation: str, arguments: list[str], *, timeout: int) -> dict[str, Any]:
        env = os.environ.copy()
        env["AIVCP_NETWORK_EXECUTION"] = "false"
        env["AIVCP_PUBLISHER_NETWORK_EXECUTION"] = "false"
        completed = subprocess.run(
            [str(self.executable), operation, *arguments],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env,
            timeout=timeout,
            check=False,
            shell=False,
        )
        if len(completed.stdout.encode("utf-8")) > MAX_OUTPUT_BYTES or len(completed.stderr.encode("utf-8")) > MAX_OUTPUT_BYTES:
            raise ToolError("PUBLISHER_CLI_OUTPUT_TOO_LARGE", "发布中心 CLI 输出超过安全上限。")
        try:
            payload = json.loads(completed.stdout)
        except json.JSONDecodeError as exc:
            raise ToolError(
                "PUBLISHER_CLI_PROTOCOL_INVALID",
                "发布中心 CLI 没有返回合法 JSON。",
                details={"exitCode": completed.returncode},
            ) from exc
        if not isinstance(payload, dict) or payload.get("network_execution") is not False:
            raise ToolError("PUBLISHER_CLI_PROTOCOL_INVALID", "发布中心 CLI 未证明 network_execution=false。")
        if completed.returncode != 0:
            code = str(payload.get("code") or "PUBLISHER_CLI_FAILED")
            if operation in {"receipt", "receipt-live"} and code == "PUBLICATION_RECEIPT_NOT_AVAILABLE":
                return {
                    "status": "not_available",
                    "code": code,
                    "publishIntentId": payload.get("result", {}).get("publish_intent_id"),
                    "publicationReceipt": None,
                    "youtubeVideoId": None,
                    "networkExecution": False,
                }
            raise ToolError(
                code,
                str(payload.get("message") or "发布中心隔离 CLI 操作失败。"),
                details={"operation": operation, "exitCode": completed.returncode},
            )
        return payload

    def capabilities(self) -> dict[str, Any]:
        payload = self._run("capabilities", [], timeout=15)
        result = payload.get("result") if isinstance(payload.get("result"), dict) else {}
        commands = result.get("commands") if isinstance(result.get("commands"), list) else []
        return {
            "configured": True,
            "formalHandoff": "handoff" in commands,
            "liveStatus": "status-live" in commands,
            "liveReceipt": "receipt-live" in commands,
            "uploadExecutionOwner": result.get("upload_execution_owner"),
            "networkExecution": False,
        }

    def import_package(self, arguments: dict[str, Any]) -> dict[str, Any]:
        self.assert_offline(arguments)
        mode = arguments.get("handoffMode")
        if mode is None:
            mode = "isolated" if arguments.get("syntheticChannelProfilePath") else "formal"
        if mode == "formal":
            package = _path(arguments.get("packagePath"), field="packagePath", file=False)
            if not package.name.endswith(".ready"):
                raise ToolError("PUBLISHER_PACKAGE_LIFECYCLE_INVALID", "只允许移交 .ready 发布包。")
            command = ["--package", str(package)]
            data_dir = arguments.get("publisherDataDir")
            if data_dir:
                command.extend(["--data-dir", str(_path(data_dir, field="publisherDataDir", file=False))])
            payload = self._run("handoff", command, timeout=180)
            return {
                "publisher": payload,
                "handoffMode": "formal",
                "networkExecution": False,
                "uploadExecutionOwner": "youtube-publisher-center-desktop",
            }
        if mode != "isolated":
            raise ToolError("PUBLISHER_HANDOFF_MODE_INVALID", "handoffMode 只允许 formal 或 isolated。")
        isolation = _path(arguments.get("isolationRoot"), field="isolationRoot", file=False)
        inbox = _path(arguments.get("inboxPath"), field="inboxPath", file=False)
        database = _path(arguments.get("databasePath"), field="databasePath", must_exist=False)
        _within(isolation, inbox, field="inboxPath")
        _within(isolation, database, field="databasePath")
        package_value = arguments.get("packagePath")
        if package_value is not None:
            package = _path(package_value, field="packagePath", file=False)
            _within(inbox, package, field="packagePath")
            if not package.name.endswith(".ready"):
                raise ToolError("PUBLISHER_PACKAGE_LIFECYCLE_INVALID", "只允许导入 .ready 发布包。")
        command = ["--inbox", str(inbox), "--database", str(database), "--isolation-root", str(isolation)]
        self._append_channel_source(command, arguments)
        ffprobe = arguments.get("ffprobePath")
        if ffprobe:
            command.extend(["--ffprobe", str(_path(ffprobe, field="ffprobePath", file=True))])
        payload = self._run("import", command, timeout=120)
        return {"publisher": payload, "handoffMode": "isolated", "networkExecution": False}

    def read_status(self, arguments: dict[str, Any], *, receipt: bool) -> dict[str, Any]:
        self.assert_offline(arguments)
        mode = arguments.get("handoffMode", "formal")
        intent = arguments.get("publishIntentId")
        if not isinstance(intent, str) or not intent:
            raise ToolError("PUBLISHER_ARGUMENT_INVALID", "publishIntentId 是必填项。")
        if mode == "formal":
            command = ["--publish-intent-id", intent]
            data_dir = arguments.get("publisherDataDir")
            if data_dir:
                command.extend(["--data-dir", str(_path(data_dir, field="publisherDataDir", file=False))])
            payload = self._run("receipt-live" if receipt else "status-live", command, timeout=30)
            return {"publisher": payload, "handoffMode": "formal", "networkExecution": False}
        if mode != "isolated":
            raise ToolError("PUBLISHER_HANDOFF_MODE_INVALID", "handoffMode 只允许 formal 或 isolated。")
        isolation = _path(arguments.get("isolationRoot"), field="isolationRoot", file=False)
        database = _path(arguments.get("databasePath"), field="databasePath", file=True)
        _within(isolation, database, field="databasePath")
        payload = self._run(
            "receipt" if receipt else "status",
            ["--database", str(database), "--isolation-root", str(isolation), "--publish-intent-id", intent],
            timeout=30,
        )
        return {"publisher": payload, "handoffMode": "isolated", "networkExecution": False}

    @staticmethod
    def _append_channel_source(command: list[str], arguments: dict[str, Any]) -> None:
        synthetic = arguments.get("syntheticChannelProfilePath")
        channel_cli = arguments.get("channelCliPath")
        channel_database = arguments.get("channelDatabasePath")
        if synthetic and (channel_cli or channel_database):
            raise ToolError("PUBLISHER_CHANNEL_SOURCE_INVALID", "合成档案和真实只读频道 CLI 不能同时使用。")
        if synthetic:
            command.extend(["--synthetic-channel-profile", str(_path(synthetic, field="syntheticChannelProfilePath", file=True))])
            return
        if not channel_cli:
            raise ToolError("PUBLISHER_CHANNEL_SOURCE_INVALID", "必须提供真实只读 channelCliPath 或明确合成频道档案。")
        command.extend(["--channel-cli", str(_path(channel_cli, field="channelCliPath", file=True))])
        if channel_database:
            command.extend(["--channel-database", str(_path(channel_database, field="channelDatabasePath", file=True))])
