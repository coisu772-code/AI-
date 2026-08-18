from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
from pathlib import Path


PRODUCT_ID = "ai-video-channel-production"
REQUIRED_TOOLS = (
    "system_capabilities",
    "content_capabilities",
    "content_workspace_start",
    "content_workspace_document_reject",
    "content_workspace_narration_prepare",
    "production_capabilities",
    "data_center_capabilities",
)
CAPABILITY_TOOLS = (
    "system_capabilities",
    "content_capabilities",
    "production_capabilities",
    "data_center_capabilities",
)


def canonical(path: Path) -> str:
    return os.path.normcase(str(path.resolve()))


def invoke_cached_plugin(command: Path, arguments: list[str], cwd: Path, request: dict[str, object], environment: dict[str, str]) -> dict[str, object]:
    payload = (json.dumps(request, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")
    completed = subprocess.run(
        [
            str(command),
            *arguments,
        ],
        input=payload,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=environment,
        cwd=cwd,
        check=False,
    )
    stdout = completed.stdout.decode("utf-8-sig").strip()
    stderr = completed.stderr.decode("utf-8-sig").strip()
    if completed.returncode != 0:
        raise RuntimeError(f"Cached plugin MCP exited with {completed.returncode}: {stderr}")
    if stderr:
        raise RuntimeError(f"Cached plugin MCP wrote unexpected stderr: {stderr}")
    lines = [line for line in stdout.splitlines() if line.strip()]
    if len(lines) != 1:
        raise RuntimeError(f"Cached plugin MCP returned {len(lines)} JSON lines, expected one: {stdout}")
    response = json.loads(lines[0])
    if response.get("error") is not None:
        raise RuntimeError(f"Cached plugin MCP rejected request: {response['error']}")
    return response


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate a runtime-bound Codex-cached plugin with the installation-owned bundled Python.")
    parser.add_argument("--cached-plugin-root", required=True, type=Path)
    parser.add_argument("--local-app-data", required=True, type=Path)
    parser.add_argument("--expected-install-root", required=True, type=Path)
    parser.add_argument("--report", required=True, type=Path)
    args = parser.parse_args()

    cached_plugin = args.cached_plugin_root.resolve()
    local_app_data = args.local_app_data.resolve()
    expected_install = args.expected_install_root.resolve()
    descriptor_path = cached_plugin / ".mcp.json"
    locator_path = local_app_data / "AIVCP-Config" / "runtime-locator.json"
    if not descriptor_path.is_file():
        raise SystemExit(f"Cached plugin MCP descriptor is missing: {descriptor_path}")
    if not locator_path.is_file():
        raise SystemExit(f"Runtime locator is missing: {locator_path}")
    locator = json.loads(locator_path.read_text(encoding="utf-8-sig"))
    if locator.get("schemaVersion") != "1.0.0" or locator.get("productId") != PRODUCT_ID:
        raise SystemExit("Runtime locator identity is invalid.")
    if canonical(Path(str(locator.get("installRoot", "")))) != canonical(expected_install):
        raise SystemExit("Runtime locator does not point to the expected custom installation.")
    runtime_python = expected_install / "current" / "runtime" / "python" / "python.exe"
    if not runtime_python.is_file():
        raise SystemExit(f"Expected bundled Python is missing: {runtime_python}")
    try:
        runtime_python.relative_to(cached_plugin)
    except ValueError:
        pass
    else:
        raise SystemExit("Cached plugin unexpectedly contains the installation runtime.")

    descriptor = json.loads(descriptor_path.read_text(encoding="utf-8-sig"))
    server = descriptor.get("mcpServers", {}).get("ai-video-channel-tools", {})
    command = Path(str(server.get("command", "")))
    arguments = [str(item) for item in server.get("args", [])]
    descriptor_environment = server.get("env", {})
    data_root = Path(str(locator.get("userDataRoot", ""))).resolve()
    active_root = expected_install / "current"
    expected_environment = {
        "AIVCP_DATA_ROOT": str(data_root),
        "AIVCP_CONFIG_ROOT": str((local_app_data / "AIVCP-Config").resolve()),
        "AIVCP_INSTALL_ROOT": str(expected_install),
        "AIVCP_EXPECTED_PRODUCT_VERSION": str(locator.get("productVersion", "")),
        "AIVCP_EXPECTED_RELEASE_MANIFEST_SHA256": str(
            json.loads((expected_install / "current" / "install-state.json").read_text(encoding="utf-8-sig")).get("releaseManifestSha256", "")
        ),
        "AIVCP_WORKSHOP_EXECUTABLE": str((active_root / "apps/workshop/Z 漫剧工坊.exe").resolve()),
        # Keep the installation-owned public isolation path lexical.  It may be a
        # deliberate junction to the actual production directory; resolving the
        # junction here would incorrectly reject the descriptor written by the
        # installer even though both paths identify the same isolated storage.
        "AIVCP_WORKSHOP_ISOLATION_ROOT": str(data_root / "workshop-isolation"),
        "AIVCP_FFMPEG_PATH": str((active_root / "apps/workshop/tools/ffmpeg/bin/ffmpeg.exe").resolve()),
        "AIVCP_FFPROBE_PATH": str((active_root / "apps/workshop/tools/ffmpeg/bin/ffprobe.exe").resolve()),
        "AIVCP_PUBLISHER_CHANNEL_LIST_EXE": str((active_root / "apps/publisher/channel-list.exe").resolve()),
        "AIVCP_PUBLISHER_V2_CLI": str((active_root / "apps/publisher/publish-package-v2.exe").resolve()),
        "AIVCP_VOICE_CATALOG": str((active_root / "plugins/ai-video-channel-production/assets/voice-catalog.json").resolve()),
        "AIVCP_YT_DLP_COMMAND_JSON": json.dumps([
            str(runtime_python),
            "-m",
            "yt_dlp",
            "--js-runtimes",
            "deno:" + str((active_root / "runtime/python/tools/deno.exe").resolve()),
            "--ffmpeg-location",
            str((active_root / "apps/workshop/tools/ffmpeg/bin").resolve()),
        ], ensure_ascii=False, separators=(",", ":")),
        "AIVCP_PUBLISHER_TIMEOUT_SECONDS": "8",
        "AIVCP_NETWORK_EXECUTION": "false",
        "AIVCP_PUBLISHER_NETWORK_EXECUTION": "false",
        "PYTHONUTF8": "1",
        "PYTHONDONTWRITEBYTECODE": "1",
        "AIVCP_YT_DLP_COMMAND_JSON": json.dumps(
            [
                str(runtime_python),
                "-m",
                "yt_dlp",
                "--js-runtimes",
                f"deno:{active_root / 'runtime/python/tools/deno.exe'}",
                "--ffmpeg-location",
                str(active_root / "apps/workshop/tools/ffmpeg/bin"),
            ],
            ensure_ascii=False,
            separators=(",", ":"),
        ),
    }
    if server.get("type") != "stdio" or server.get("cwd") != ".":
        raise SystemExit("Cached plugin MCP descriptor is not locked stdio with cache-relative cwd.")
    if canonical(command) != canonical(runtime_python):
        raise SystemExit("Cached plugin MCP descriptor command is not the expected bundled Python.")
    if arguments != ["./mcp/server.py", "mcp"]:
        raise SystemExit(f"Cached plugin MCP descriptor arguments are not locked: {arguments}")
    if descriptor_environment != expected_environment:
        raise SystemExit("Cached plugin MCP descriptor environment does not exactly bind data, config and offline defaults.")

    system_root = Path(os.environ.get("SystemRoot", r"C:\Windows"))
    target_path = os.pathsep.join(
        [
            str(system_root / "System32"),
            str(system_root),
            str(system_root / "System32" / "WindowsPowerShell" / "v1.0"),
        ]
    )
    environment = os.environ.copy()
    environment["SystemRoot"] = str(system_root)
    environment["LOCALAPPDATA"] = str(local_app_data)
    environment["PATH"] = target_path
    environment["AIVCP_NETWORK_EXECUTION"] = "false"
    for name in ("AIVCP_PYTHON", "AIVCP_DATA_ROOT", "AIVCP_CONFIG_ROOT", "AIVCP_INSTALL_ROOT", "AIVCP_EXPECTED_PRODUCT_VERSION", "AIVCP_EXPECTED_RELEASE_MANIFEST_SHA256", "AIVCP_WORKSHOP_EXECUTABLE", "AIVCP_WORKSHOP_ISOLATION_ROOT", "AIVCP_FFMPEG_PATH", "AIVCP_FFPROBE_PATH", "AIVCP_PUBLISHER_CHANNEL_LIST_EXE", "AIVCP_PUBLISHER_V2_CLI", "AIVCP_VOICE_CATALOG", "AIVCP_YT_DLP_COMMAND_JSON", "AIVCP_RUNTIME_LOCATOR", "UV", "PYTHONHOME"):
        environment.pop(name, None)
    environment.update(expected_environment)
    python_visible = shutil.which("python", path=target_path)
    uv_visible = shutil.which("uv", path=target_path)
    if python_visible or uv_visible:
        raise SystemExit(f"Fresh environment unexpectedly exposes Python/uv: python={python_visible}, uv={uv_visible}")

    responses: list[dict[str, object]] = []
    list_response = invoke_cached_plugin(
        command,
        arguments,
        cached_plugin,
        {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}},
        environment,
    )
    responses.append(list_response)
    tool_definitions = {str(tool["name"]): tool for tool in list_response["result"]["tools"]}
    tool_names = set(tool_definitions)
    missing = set(REQUIRED_TOOLS) - tool_names
    if missing:
        raise SystemExit(f"Cached plugin MCP tools/list is missing: {sorted(missing)}")
    narration_schema = tool_definitions["content_workspace_narration_prepare"].get("inputSchema", {})
    narration_required = narration_schema.get("required", [])
    if "narrationTitle" not in narration_required or "narrationTitleChinese" in narration_required:
        raise SystemExit("Cached plugin narration title schema is not using the conditional Chinese-review contract.")
    publishing_tool = tool_definitions.get("content_publishing_finalize")
    if publishing_tool is None:
        raise SystemExit("Cached plugin MCP tools/list is missing content_publishing_finalize.")
    publishing_schema = publishing_tool.get("inputSchema", {})
    publishing_required = publishing_schema.get("required", [])
    publishing_properties = publishing_schema.get("properties", {})
    title_candidates_schema = publishing_properties.get("titleCandidates", {})
    title_source_schema = publishing_properties.get("titleSource", {})
    if (
        "titleCandidates" in publishing_required
        or title_candidates_schema.get("minItems") != 1
        or title_candidates_schema.get("maxItems") != 6
        or title_source_schema.get("enum") != ["confirmed_narration", "user_confirmed", "generated_candidates"]
    ):
        raise SystemExit("Cached plugin publishing title schema still forces generated title candidates.")

    capability_status: dict[str, str] = {}
    component_integration: dict[str, object] = {}
    component_integration["narrationTitleRequired"] = True
    component_integration["narrationTitleChineseConditional"] = True
    component_integration["generatedTitleCandidatesOptional"] = True
    for request_id, tool_name in enumerate(CAPABILITY_TOOLS, start=2):
        response = invoke_cached_plugin(
            command,
            arguments,
            cached_plugin,
            {
                "jsonrpc": "2.0",
                "id": request_id,
                "method": "tools/call",
                "params": {"name": tool_name, "arguments": {}},
            },
            environment,
        )
        responses.append(response)
        structured = response.get("result", {}).get("structuredContent", {})
        if structured.get("ok") is not True or structured.get("result") is None:
            raise SystemExit(f"Cached plugin capability call failed: {tool_name}")
        result = structured["result"]
        if tool_name == "system_capabilities":
            if (
                result.get("publisherInterface", {}).get("available") is not True
                or result.get("capabilities", {}).get("publisherReadOnlyInterfaceConfigured") is not True
                or result.get("capabilities", {}).get("publisherV2BridgeConfigured") is not True
                or result.get("publisherV2Bridge", {}).get("configured") is not True
                or result.get("publisherV2Bridge", {}).get("networkExecution") is not False
                or result.get("voiceCatalog", {}).get("available") is not True
                or result.get("capabilities", {}).get("preScannedVoiceCatalog") is not True
            ):
                raise SystemExit("Cached plugin did not expose the voice catalog and installed publisher bridges.")
            component_integration["publisherReadOnlyConfigured"] = True
            component_integration["publisherV2Configured"] = True
            component_integration["publisherNetworkExecution"] = False
            component_integration["voiceCatalogAvailable"] = True
        if tool_name == "content_capabilities":
            direct_draft = result.get("routes", {}).get("direct-draft", {})
            workspace_routes = result.get("creativeWorkspace", {}).get("draftingRoutes", [])
            if (
                direct_draft.get("available") is not True
                or direct_draft.get("requiresConfirmedOutline") is not False
                or direct_draft.get("firstUserReviewGate") != "D4_REWRITE_DRAFT"
                or "direct-draft" not in workspace_routes
                or "provided-outline" not in workspace_routes
            ):
                raise SystemExit("Cached plugin did not expose the direct-draft route without a forced outline gate.")
            component_integration["directDraftWithoutOutlineGate"] = True
        if tool_name == "production_capabilities":
            workshop_health = result.get("workshopHealth", {})
            workshop_capabilities = result.get("workshopCapabilities", {})
            codex_visual_plan = result.get("codexVisualPlan", {})
            voice_catalog = json.loads(Path(expected_environment["AIVCP_VOICE_CATALOG"]).read_text(encoding="utf-8-sig"))
            covered_voice_engines = {
                str(item.get("engineId"))
                for group in (voice_catalog.get("engines", []), voice_catalog.get("enginePolicies", []))
                for item in group
                if isinstance(item, dict) and item.get("engineId")
            }
            reported_voice_engines = {
                str(item.get("engine"))
                for item in workshop_capabilities.get("voiceEngines", [])
                if isinstance(item, dict) and item.get("engine")
            }
            if (
                result.get("workshopBridgeConfigured") is not True
                or result.get("ffmpegAvailable") is not True
                or result.get("ffprobeAvailable") is not True
                or workshop_health.get("success") is not True
                or workshop_health.get("ffmpegAvailable") is not True
                or workshop_health.get("ffmpegPathSet") is not True
                or workshop_health.get("ffprobePathSet") is not True
                or "2.1" not in workshop_capabilities.get("supportedPackageVersions", [])
                or workshop_capabilities.get("externalServiceProbeExecuted") is not False
                or not reported_voice_engines.issubset(covered_voice_engines)
                or codex_visual_plan.get("schemaVersion") != "1.1"
                or codex_visual_plan.get("storyVisualPlanning") is not True
                or codex_visual_plan.get("complexityAdaptivePageCount") is not True
                or codex_visual_plan.get("criticalEmotionVisualSignals") is not True
                or codex_visual_plan.get("continuityBible") is not True
                or codex_visual_plan.get("promptBudgets") != {"imageMaxChars": 600, "videoMaxChars": 500}
            ):
                raise SystemExit("Cached plugin workshop bridge or voice-engine catalog coverage is incomplete.")
            component_integration["workshopHealthCheckExecuted"] = True
            component_integration["workshopCapabilitiesNoProbeExecuted"] = True
            component_integration["productionPackage21"] = True
            component_integration["ffmpegAvailable"] = True
            component_integration["ffprobeAvailable"] = True
            component_integration["externalServiceProbeExecuted"] = False
            component_integration["workshopVoiceEnginesCovered"] = sorted(reported_voice_engines)
            component_integration["codexVisualPlanSchema"] = "1.1"
            component_integration["criticalEmotionVisualSignals"] = True
        capability_status[tool_name] = "PASS"

    report = {
        "schemaVersion": "1.0.0",
        "status": "PASS",
        "mode": "RUNTIME_BOUND_DESCRIPTOR_FRESH_PROCESS",
        "cachedPluginRoot": str(cached_plugin),
        "cachedPluginHasBundledRuntime": False,
        "locatorPath": str(locator_path),
        "locatorInstallRoot": str(expected_install),
        "bundledPython": str(runtime_python),
        "descriptorPath": str(descriptor_path),
        "descriptorCommandDirectToPython": True,
        "powershellOrCmdProxy": False,
        "freshEnvironment": {
            "preinstalledPythonVisible": False,
            "preinstalledUvVisible": False,
            "runtimeOverrideVariablesPresent": False,
            "localAppData": str(local_app_data),
        },
        "toolsList": {"status": "PASS", "required": list(REQUIRED_TOOLS), "count": len(tool_names)},
        "capabilities": capability_status,
        "componentIntegration": component_integration,
        "processesStarted": len(responses),
        "boundaries": {
            "networkExecution": False,
            "oauth": False,
            "upload": False,
            "longTermLearningWrite": False,
        },
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Runtime-bound cached plugin validation PASS: {args.report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
