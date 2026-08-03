from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from aivcp_tools import LocalToolService, ServiceConfig, ToolError
from aivcp_tools.security import redact
from aivcp_tools.service import LOCAL_TOOL_PROTOCOL_VERSION, SERVICE_VERSION, tool_definitions


MCP_PROTOCOL_VERSION = "2025-06-18"
MAX_MESSAGE_BYTES = 2 * 1024 * 1024
PLUGIN_ROOT = Path(__file__).resolve().parents[1]


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
                "instructions": "处理频道身份、建库、备份迁移及阶段3资料添加、标准化、去重、检索与恢复；不接受或返回凭据，不执行内容分析或生成。",
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
    parser = argparse.ArgumentParser(description="AI Video Channel Production local tool service")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("mcp", help="run the MCP stdio server")
    subparsers.add_parser("capabilities", help="print sanitized service capabilities")
    call_parser = subparsers.add_parser("call", help="call one deterministic tool")
    call_parser.add_argument("tool")
    call_parser.add_argument("--arguments", default="{}")
    args = parser.parse_args(argv)

    try:
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
