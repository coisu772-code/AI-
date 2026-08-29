from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import time
from pathlib import Path


REQUIRED_TOOLS = (
    "system_capabilities",
    "content_capabilities",
    "production_capabilities",
    "data_center_capabilities",
)


def toml_literal(value: Path | str) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def terminate_process_tree(process: subprocess.Popen[str]) -> str:
    if process.poll() is not None:
        return "PARENT_ALREADY_EXITED"
    if os.name == "nt":
        completed = subprocess.run(
            ["taskkill", "/PID", str(process.pid), "/T", "/F"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=20,
            check=False,
        )
        return f"TASKKILL_TREE_EXIT_{completed.returncode}"
    os.killpg(process.pid, signal.SIGKILL)
    return "POSIX_PROCESS_GROUP_KILLED"


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a bounded real Codex CLI MCP smoke test without changing plugin registration.")
    parser.add_argument("--codex-exe", required=True, type=Path)
    parser.add_argument("--cached-plugin-root", required=True, type=Path)
    parser.add_argument("--local-app-data", required=True, type=Path)
    parser.add_argument("--expected-install-root", required=True, type=Path)
    parser.add_argument("--model", default="gpt-5.4")
    parser.add_argument("--timeout-seconds", type=int, default=90)
    parser.add_argument("--report", required=True, type=Path)
    parser.add_argument("--events", required=True, type=Path)
    parser.add_argument("--last-message", required=True, type=Path)
    args = parser.parse_args()

    if args.timeout_seconds < 15 or args.timeout_seconds > 180:
        raise SystemExit("timeout-seconds must be between 15 and 180")
    codex = args.codex_exe.resolve()
    cached_plugin = args.cached_plugin_root.resolve()
    local_app_data = args.local_app_data.resolve()
    install_root = args.expected_install_root.resolve()
    runtime_python = install_root / "current" / "runtime" / "python" / "python.exe"
    for required in (codex, cached_plugin / "mcp" / "server.py", cached_plugin / ".mcp.json", runtime_python):
        if not required.exists():
            raise SystemExit(f"Required real-Codex smoke input is missing: {required}")

    descriptor = json.loads((cached_plugin / ".mcp.json").read_text(encoding="utf-8-sig"))
    server = descriptor["mcpServers"]["ai-video-channel-tools"]
    if Path(server["command"]).resolve() != runtime_python:
        raise SystemExit("Runtime-bound descriptor does not point to the expected bundled Python.")
    if server.get("args") != ["./mcp/server.py", "mcp"] or server.get("cwd") != ".":
        raise SystemExit("Runtime-bound descriptor command arguments or cwd are not locked.")
    environment = server.get("env", {})
    expected_config = local_app_data / "AIVCP-Config"
    if Path(environment.get("AIVCP_CONFIG_ROOT", "")).resolve() != expected_config:
        raise SystemExit("Runtime-bound descriptor configuration root is not locked to the isolated test root.")
    if environment.get("AIVCP_NETWORK_EXECUTION") != "false":
        raise SystemExit("Runtime-bound descriptor is not offline by default.")
    required_component_bindings = (
        "AIVCP_WORKSHOP_EXECUTABLE",
        "AIVCP_WORKSHOP_ISOLATION_ROOT",
        "AIVCP_FFMPEG_PATH",
        "AIVCP_FFPROBE_PATH",
        "AIVCP_PUBLISHER_CHANNEL_LIST_EXE",
        "AIVCP_PUBLISHER_V2_CLI",
        "AIVCP_PUBLISHER_DESKTOP_EXE",
        "AIVCP_VOICE_CATALOG",
        "AIVCP_YT_DLP_COMMAND_JSON",
    )
    if any(not environment.get(name) for name in required_component_bindings):
        raise SystemExit("Runtime-bound descriptor is missing installed component paths.")

    prompt = (
        "Use only the MCP server aivcpfresh. Call system_capabilities, content_capabilities, "
        "production_capabilities, and data_center_capabilities exactly once each. Confirm from the "
        "results that the workshop bridge, FFmpeg, ffprobe, Production Package 2.1, publisher read-only "
        "interface, publisher v2 bridge and pre-scanned voice catalog are configured, externalServiceProbeExecuted is false, and "
        "publisherV2Bridge.networkExecution is false. Do not call shell or any other tool. "
        "Do not perform network operations, OAuth, uploads, or writes. Return only one compact "
        "JSON object with keys toolsLoaded, system, content, production, data, workshop, ffmpeg, ffprobe, "
        "package21, publisherReadOnly, publisherV2, voiceCatalog, externalProbeFalse, networkFalse, all true only if verified."
    )
    env_toml = "{" + ",".join(f"{key}={toml_literal(str(value))}" for key, value in environment.items()) + "}"
    command = [
        str(codex),
        "exec",
        "--ephemeral",
        "--ignore-user-config",
        "--ignore-rules",
        "--skip-git-repo-check",
        "--dangerously-bypass-approvals-and-sandbox",
        "--color",
        "never",
        "--json",
        "-m",
        args.model,
        "-o",
        str(args.last_message.resolve()),
        "-C",
        str(cached_plugin),
        "-c",
        f"mcp_servers.aivcpfresh.command={toml_literal(runtime_python)}",
        "-c",
        "mcp_servers.aivcpfresh.args=['./mcp/server.py','mcp']",
        "-c",
        f"mcp_servers.aivcpfresh.cwd={toml_literal(cached_plugin)}",
        "-c",
        f"mcp_servers.aivcpfresh.env={env_toml}",
        prompt,
    ]
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.events.parent.mkdir(parents=True, exist_ok=True)
    args.last_message.parent.mkdir(parents=True, exist_ok=True)
    creation_flags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
    started = time.monotonic()
    process = subprocess.Popen(
        command,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=creation_flags,
        start_new_session=os.name != "nt",
    )
    cleanup = "NORMAL_CODEX_EXIT"
    timed_out = False
    try:
        stdout, stderr = process.communicate(timeout=args.timeout_seconds)
    except subprocess.TimeoutExpired:
        timed_out = True
        cleanup = terminate_process_tree(process)
        stdout, stderr = process.communicate(timeout=20)
    elapsed = round(time.monotonic() - started, 3)
    args.events.write_text(stdout + ("\n" if stdout and not stdout.endswith("\n") else ""), encoding="utf-8")

    events = []
    for line in stdout.splitlines():
        if line.startswith("{"):
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    calls: dict[str, str] = {}
    forbidden_events: list[str] = []
    for event in events:
        item = event.get("item", {})
        item_type = item.get("type")
        if item_type in {"command_execution", "web_search", "file_change"}:
            forbidden_events.append(str(item_type))
        if item_type == "mcp_tool_call" and item.get("server") == "aivcpfresh" and item.get("tool") in REQUIRED_TOOLS:
            if item.get("status") == "completed" and item.get("error") is None:
                calls[str(item["tool"])] = "PASS"
            elif item.get("status") == "failed":
                calls[str(item["tool"])] = f"FAIL: {item.get('error')}"

    last_message = args.last_message.read_text(encoding="utf-8-sig").strip() if args.last_message.is_file() else ""
    try:
        final_value = json.loads(last_message)
    except json.JSONDecodeError:
        final_value = {}
    final_keys = (
        "toolsLoaded", "system", "content", "production", "data", "workshop", "ffmpeg", "ffprobe",
        "package21", "publisherReadOnly", "publisherV2", "externalProbeFalse", "networkFalse",
        "voiceCatalog",
    )
    final_pass = all(final_value.get(key) is True for key in final_keys)
    success = (
        not timed_out
        and process.returncode == 0
        and not forbidden_events
        and all(calls.get(name) == "PASS" for name in REQUIRED_TOOLS)
        and final_pass
    )
    report = {
        "schemaVersion": "1.0.0",
        "status": "PASS" if success else "FAIL",
        "mode": "ACTUAL_CODEX_CLI_RUNTIME_BOUND_MCP",
        "codexExe": str(codex),
        "codexExitCode": process.returncode,
        "model": args.model,
        "timeoutSeconds": args.timeout_seconds,
        "timedOut": timed_out,
        "elapsedSeconds": elapsed,
        "processCleanup": cleanup,
        "mcpStartOrHandshakeFailed": not calls and not timed_out,
        "codexWaitTimedOut": timed_out,
        "testHarnessFailure": process.returncode not in (0, None) and not calls,
        "toolsListObservedByCodex": final_value.get("toolsLoaded") is True,
        "capabilityCalls": calls,
        "forbiddenEvents": forbidden_events,
        "lastMessage": final_value,
        "componentIntegrationObserved": {
            "workshopReadOnlyHealthAndCapabilities": final_value.get("workshop") is True,
            "ffmpeg": final_value.get("ffmpeg") is True,
            "ffprobe": final_value.get("ffprobe") is True,
            "productionPackage21": final_value.get("package21") is True,
            "publisherReadOnly": final_value.get("publisherReadOnly") is True,
            "publisherV2": final_value.get("publisherV2") is True,
            "voiceCatalog": final_value.get("voiceCatalog") is True,
            "externalServiceProbeExecuted": False if final_value.get("externalProbeFalse") is True else None,
            "networkExecution": False if final_value.get("networkFalse") is True else None,
        },
        "stderrTail": stderr.splitlines()[-20:],
        "boundaries": {
            "pluginRegistrationChanged": False,
            "networkExecutionByMcp": False,
            "oauth": False,
            "upload": False,
            "longTermLearningWrite": False,
        },
    }
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if not success:
        raise SystemExit(f"Actual Codex CLI MCP smoke failed; see {args.report}")
    print(f"Actual Codex CLI runtime-bound MCP validation PASS: {args.report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
