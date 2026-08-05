from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any

from aivcp_tools import LocalToolService, ServiceConfig, ToolError
from aivcp_tools.security import redact
from aivcp_tools.service import LOCAL_TOOL_PROTOCOL_VERSION, SERVICE_VERSION, tool_definitions


MCP_PROTOCOL_VERSION = "2025-06-18"
MAX_MESSAGE_BYTES = 2 * 1024 * 1024
PLUGIN_ROOT = Path(__file__).resolve().parents[1]


def _same_path(left: Path, right: Path) -> bool:
    return os.path.normcase(str(left.resolve())) == os.path.normcase(str(right.resolve()))


def _runtime_binding_error(message: str) -> ToolError:
    return ToolError("RUNTIME_BINDING_MISMATCH", message)


def _validate_runtime_binding() -> None:
    binding_names = (
        "AIVCP_INSTALL_ROOT",
        "AIVCP_EXPECTED_PRODUCT_VERSION",
        "AIVCP_EXPECTED_RELEASE_MANIFEST_SHA256",
        "AIVCP_WORKSHOP_EXECUTABLE",
        "AIVCP_WORKSHOP_ISOLATION_ROOT",
        "AIVCP_FFMPEG_PATH",
        "AIVCP_FFPROBE_PATH",
        "AIVCP_PUBLISHER_CHANNEL_LIST_EXE",
        "AIVCP_PUBLISHER_V2_CLI",
        "AIVCP_VOICE_CATALOG",
    )
    values = {name: os.environ.get(name, "").strip() for name in binding_names}
    if not any(values.values()):
        return
    if not all(values.values()):
        raise _runtime_binding_error("The installed MCP runtime binding is incomplete. Run installer repair.")
    expected_version = values["AIVCP_EXPECTED_PRODUCT_VERSION"]
    expected_release = values["AIVCP_EXPECTED_RELEASE_MANIFEST_SHA256"].lower()
    if len(expected_release) != 64 or any(character not in "0123456789abcdef" for character in expected_release):
        raise _runtime_binding_error("The installed MCP release binding is invalid. Run installer repair.")
    install_root = Path(values["AIVCP_INSTALL_ROOT"])
    data_value = os.environ.get("AIVCP_DATA_ROOT", "").strip()
    config_value = os.environ.get("AIVCP_CONFIG_ROOT", "").strip()
    if not install_root.is_absolute() or not data_value or not config_value:
        raise _runtime_binding_error("The installed MCP path binding is incomplete. Run installer repair.")
    data_root = Path(data_value)
    config_root = Path(config_value)
    if not data_root.is_absolute() or not config_root.is_absolute():
        raise _runtime_binding_error("The installed MCP paths must be absolute. Run installer repair.")
    paths = {
        "plugin": PLUGIN_ROOT / ".codex-plugin" / "plugin.json",
        "marker": install_root / "installation.json",
        "state": install_root / "current" / "install-state.json",
        "manifest": install_root / "current" / "unified-release-manifest.json",
        "locator": config_root / "runtime-locator.json",
    }
    if any(not path.is_file() for path in paths.values()):
        raise _runtime_binding_error("The installed MCP binding records are incomplete. Run installer repair.")
    try:
        plugin = json.loads(paths["plugin"].read_text(encoding="utf-8-sig"))
        marker = json.loads(paths["marker"].read_text(encoding="utf-8-sig"))
        state = json.loads(paths["state"].read_text(encoding="utf-8-sig"))
        manifest_bytes = paths["manifest"].read_bytes()
        manifest = json.loads(manifest_bytes.decode("utf-8-sig"))
        locator = json.loads(paths["locator"].read_text(encoding="utf-8-sig"))
        youtube_runtime_contract = json.loads((PLUGIN_ROOT / "assets" / "portable-youtube-runtime.json").read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise _runtime_binding_error("The installed MCP binding records are unreadable. Run installer repair.") from exc
    try:
        marker_data = Path(str(marker["userDataRoot"]))
        state_data = Path(str(state["userDataRoot"]))
        locator_data = Path(str(locator["userDataRoot"]))
        locator_install = Path(str(locator["installRoot"]))
    except (KeyError, TypeError, ValueError) as exc:
        raise _runtime_binding_error("The installed MCP binding records are incomplete. Run installer repair.") from exc
    runtime = state.get("runtime", {})
    installed_assets = {
        item.get("assetId"): item
        for item in state.get("installedAssets", [])
        if isinstance(item, dict) and isinstance(item.get("assetId"), str)
    }
    manifest_assets = {
        item.get("assetId"): item
        for item in manifest.get("assets", [])
        if isinstance(item, dict) and isinstance(item.get("assetId"), str) and item.get("install") is True
    }
    required_assets = {"core", "python-runtime", "workshop", "publisher-center"}
    asset_bindings_match = set(installed_assets) == required_assets and set(manifest_assets) == required_assets
    if asset_bindings_match:
        for asset_id in required_assets:
            installed = installed_assets[asset_id]
            declared = manifest_assets[asset_id]
            if any(installed.get(field) != declared.get(field) for field in ("fileName", "sha256", "sizeBytes")):
                asset_bindings_match = False
                break
    identity_matches = (
        plugin.get("name") == "ai-video-channel-production"
        and plugin.get("version") == expected_version
        and marker.get("schemaVersion") == "2.0.0"
        and marker.get("productId") == "ai-video-channel-production"
        and marker.get("activeVersion") == expected_version
        and marker.get("activeRoot") == "current"
        and str(marker.get("releaseManifestSha256", "")).lower() == expected_release
        and state.get("schemaVersion") == "2.0.0"
        and state.get("productId") == "ai-video-channel-production"
        and state.get("productVersion") == expected_version
        and str(state.get("releaseManifestSha256", "")).lower() == expected_release
        and runtime.get("bundled") is True
        and runtime.get("python") == "runtime/python/python.exe"
        and runtime.get("youtubeCollectorModule") == "runtime/python/Lib/site-packages/yt_dlp/__init__.py"
        and runtime.get("youtubeJavascriptRuntime") == "runtime/python/tools/deno.exe"
        and manifest.get("schemaVersion") == "2.0.0"
        and manifest.get("productId") == "ai-video-channel-production"
        and manifest.get("productVersion") == expected_version
        and manifest.get("releaseStatus") == "candidate"
        and hashlib.sha256(manifest_bytes).hexdigest() == expected_release
        and asset_bindings_match
        and locator.get("schemaVersion") == "1.0.0"
        and locator.get("productId") == "ai-video-channel-production"
        and locator.get("productVersion") == expected_version
        and locator.get("activeRoot") == "current"
        and locator.get("pythonRelativePath") == "runtime/python/python.exe"
    )
    expected_python = install_root / "current" / "runtime" / "python" / "python.exe"
    expected_deno = install_root / "current" / "runtime" / "python" / "tools" / "deno.exe"
    expected_youtube_module = install_root / "current" / "runtime" / "python" / "Lib" / "site-packages" / "yt_dlp" / "__init__.py"
    expected_ejs_module = install_root / "current" / "runtime" / "python" / "Lib" / "site-packages" / "yt_dlp_ejs" / "__init__.py"
    expected_ffmpeg = install_root / "current" / "apps" / "workshop" / "tools" / "ffmpeg" / "bin" / "ffmpeg.exe"
    try:
        youtube_command = json.loads(os.environ.get("AIVCP_YT_DLP_COMMAND_JSON", ""))
    except json.JSONDecodeError as exc:
        raise _runtime_binding_error("The installed YouTube collector binding is invalid. Run installer repair.") from exc
    expected_youtube_command = [
        str(expected_python),
        "-m",
        "yt_dlp",
        "--js-runtimes",
        f"deno:{expected_deno}",
        "--ffmpeg-location",
        str(expected_ffmpeg.parent),
    ]
    youtube_runtime_matches = (
        youtube_runtime_contract.get("schemaVersion") == "1.1.0"
        and youtube_runtime_contract.get("collector", {}).get("id") == "yt-dlp"
        and youtube_runtime_contract.get("collector", {}).get("version") == "2026.7.4"
        and youtube_runtime_contract.get("collector", {}).get("commandVersion") == "2026.07.04"
        and youtube_runtime_contract.get("javascriptRuntime", {}).get("id") == "deno"
        and youtube_runtime_contract.get("javascriptRuntime", {}).get("version") == "2.9.4"
        and youtube_runtime_contract.get("requiresSystemPath") is False
        and youtube_command == expected_youtube_command
        and all(path.is_file() and not path.is_symlink() for path in (expected_deno, expected_youtube_module, expected_ejs_module))
    )
    managed_paths = {
        "AIVCP_WORKSHOP_EXECUTABLE": install_root / "current" / "apps" / "workshop" / "Z 漫剧工坊.exe",
        "AIVCP_FFMPEG_PATH": expected_ffmpeg,
        "AIVCP_FFPROBE_PATH": install_root / "current" / "apps" / "workshop" / "tools" / "ffmpeg" / "bin" / "ffprobe.exe",
        "AIVCP_PUBLISHER_CHANNEL_LIST_EXE": install_root / "current" / "apps" / "publisher" / "channel-list.exe",
        "AIVCP_PUBLISHER_V2_CLI": install_root / "current" / "apps" / "publisher" / "publish-package-v2.exe",
    }
    expected_isolation = data_root / "workshop-isolation"
    component_paths_match = all(
        Path(values[name]).is_absolute()
        and _same_path(Path(values[name]), expected_path)
        and expected_path.is_file()
        and not expected_path.is_symlink()
        for name, expected_path in managed_paths.items()
    )
    if (
        not identity_matches
        or not _same_path(locator_install, install_root)
        or not _same_path(marker_data, data_root)
        or not _same_path(state_data, data_root)
        or not _same_path(locator_data, data_root)
        or not _same_path(Path(sys.executable), expected_python)
        or not component_paths_match
        or not youtube_runtime_matches
        or not _same_path(Path(values["AIVCP_WORKSHOP_ISOLATION_ROOT"]), expected_isolation)
        or not expected_isolation.is_dir()
        or os.environ.get("AIVCP_NETWORK_EXECUTION") != "false"
        or os.environ.get("AIVCP_PUBLISHER_NETWORK_EXECUTION") != "false"
    ):
        raise _runtime_binding_error("The cached plugin, active runtime, locator, state, or data root no longer match. Reinstall or repair the plugin and restart Codex.")


def _tool_result(payload: dict[str, Any], *, is_error: bool = False) -> dict[str, Any]:
    safe = redact(payload)
    return {
        "content": [{"type": "text", "text": json.dumps(safe, ensure_ascii=False)}],
        "structuredContent": safe,
        "isError": is_error,
    }


class McpServer:
    def __init__(self, service: LocalToolService):
        self.service = service

    def handle(self, request: dict[str, Any]) -> dict[str, Any] | None:
        request_id = request.get("id")
        method = request.get("method")
        if method == "notifications/initialized":
            return None
        if method == "initialize":
            result = {
                "protocolVersion": MCP_PROTOCOL_VERSION,
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": "ai-video-channel-local-tools", "version": SERVICE_VERSION},
                "instructions": "处理频道身份、资料、内容冻结、制作到 VIDEO_READY、阶段6本地发布准备，以及阶段7按频道隔离的数据快照、报告和建议；不接受凭据，不发起 OAuth、YouTube 上传、私有 Analytics 网络调用、远端修改或长期学习。",
            }
        elif method == "ping":
            result = {}
        elif method == "tools/list":
            result = {"tools": tool_definitions()}
        elif method == "tools/call":
            params = request.get("params") or {}
            try:
                payload = {
                    "ok": True,
                    "protocolVersion": LOCAL_TOOL_PROTOCOL_VERSION,
                    "result": self.service.call(params.get("name"), params.get("arguments")),
                }
                result = _tool_result(payload)
            except ToolError as exc:
                result = _tool_result(
                    {"ok": False, "protocolVersion": LOCAL_TOOL_PROTOCOL_VERSION, "error": exc.as_dict()},
                    is_error=True,
                )
        else:
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "error": {"code": -32601, "message": "Method not found"},
            }
        return {"jsonrpc": "2.0", "id": request_id, "result": result}


def run_stdio(service: LocalToolService) -> int:
    server = McpServer(service)
    for raw_line in sys.stdin.buffer:
        if len(raw_line) > MAX_MESSAGE_BYTES:
            response = {"jsonrpc": "2.0", "id": None, "error": {"code": -32600, "message": "Message too large"}}
        else:
            try:
                request = json.loads(raw_line.decode("utf-8"))
                if not isinstance(request, dict) or request.get("jsonrpc") != "2.0":
                    raise ValueError("invalid JSON-RPC request")
                response = server.handle(request)
            except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
                response = {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Parse error"}}
            except ToolError as exc:
                response = {"jsonrpc": "2.0", "id": None, "error": {"code": -32000, "message": exc.code}}
            except Exception as exc:  # never expose stack traces or provider output to stdout
                response = {"jsonrpc": "2.0", "id": None, "error": {"code": -32603, "message": type(exc).__name__}}
        if response is not None:
            sys.stdout.write(json.dumps(redact(response), ensure_ascii=False, separators=(",", ":")) + "\n")
            sys.stdout.flush()
    return 0


def main(argv: list[str] | None = None) -> int:
    # MCP stdio is UTF-8 regardless of the Windows console code page.  The
    # catalog contains real Japanese and multilingual display names that are
    # not representable in legacy GBK/ANSI process defaults.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="strict", newline="\n")
    parser = argparse.ArgumentParser(description="AI Video Channel Production local tool service")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("mcp", help="run the MCP stdio server")
    subparsers.add_parser("capabilities", help="print sanitized service capabilities")
    call_parser = subparsers.add_parser("call", help="call one deterministic tool")
    call_parser.add_argument("tool")
    call_parser.add_argument("--arguments", default="{}")
    args = parser.parse_args(argv)

    try:
        _validate_runtime_binding()
        service = LocalToolService(ServiceConfig.from_environment(PLUGIN_ROOT))
        if args.command == "mcp":
            return run_stdio(service)
        if args.command == "capabilities":
            payload = {"ok": True, "result": service.capabilities()}
        else:
            payload = {"ok": True, "result": service.call(args.tool, json.loads(args.arguments))}
    except (ToolError, json.JSONDecodeError) as exc:
        error = exc if isinstance(exc, ToolError) else ToolError("INVALID_JSON", "--arguments 不是有效 JSON。")
        payload = {"ok": False, "error": error.as_dict()}
    sys.stdout.write(json.dumps(redact(payload), ensure_ascii=False, indent=2) + "\n")
    return 0 if payload["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
