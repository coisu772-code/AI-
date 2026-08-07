#!/usr/bin/env python3
"""Read-only Stage6 publisher Skill and local tool installation health check."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any


SKILL_NAME = "publish-video"
REQUIRED_TOOLS = (
    "assemble_publish_package_v2",
    "validate_publish_package_v2",
    "import_publish_package_v2",
    "get_publication_status",
    "get_publication_receipt",
)
REQUIRED_SKILL_FILES = (
    "SKILL.md",
    "agents/openai.yaml",
    "references/tool-protocol.md",
    "scripts/check_publisher_install.py",
)


class HealthError(RuntimeError):
    pass


def _plugin_root_from_script() -> Path:
    return Path(__file__).resolve().parents[3]


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeError) as exc:
        raise HealthError(f"cannot read required file: {path.name}") from exc


def _read_json(path: Path, *, label: str) -> dict[str, Any]:
    try:
        value = json.loads(_read_text(path).lstrip("\ufeff"))
    except json.JSONDecodeError as exc:
        raise HealthError(f"{label} is invalid JSON") from exc
    if not isinstance(value, dict):
        raise HealthError(f"{label} must contain a JSON object")
    return value


def _check_static(plugin_root: Path) -> dict[str, Any]:
    manifest_path = plugin_root / ".codex-plugin" / "plugin.json"
    if not manifest_path.is_file():
        raise HealthError("plugin manifest is missing")
    manifest = _read_json(manifest_path, label="plugin manifest")
    if manifest.get("name") != "ai-video-channel-production":
        raise HealthError("unexpected plugin identity")

    install_state_checked = False
    current_root = plugin_root.parents[1]
    install_state_path = current_root / "install-state.json"
    if current_root.name == "current":
        if not install_state_path.is_file():
            raise HealthError("installed plugin is missing install-state.json")
        install_state = _read_json(install_state_path, label="install-state.json")
        if str(install_state.get("productVersion", "")) != str(manifest.get("version", "")):
            raise HealthError("install state and plugin versions differ")
        install_state_checked = True

    skill_root = plugin_root / "skills" / SKILL_NAME
    missing = [item for item in REQUIRED_SKILL_FILES if not (skill_root / item).is_file()]
    if missing:
        raise HealthError("missing Skill files: " + ", ".join(missing))

    skill_text = _read_text(skill_root / "SKILL.md")
    protocol_text = _read_text(skill_root / "references" / "tool-protocol.md")
    for tool_name in REQUIRED_TOOLS:
        if tool_name not in skill_text or tool_name not in protocol_text:
            raise HealthError(f"Skill protocol does not declare {tool_name}")
    for boundary in (
        "networkExecution=false",
        "FINAL_CHINESE_REVIEW_CONFIRMATION_REQUIRED",
        "PACKAGE_READY",
        "WAITING_REVIEW",
        "READY_TO_UPLOAD",
        "youtubeVideoId",
    ):
        if boundary not in skill_text and boundary not in protocol_text:
            raise HealthError(f"Skill protocol is missing safety boundary: {boundary}")
    return {
        "plugin": manifest["name"],
        "pluginVersion": str(manifest.get("version", "")),
        "installStateChecked": install_state_checked,
        "skill": SKILL_NAME,
        "skillFiles": len(REQUIRED_SKILL_FILES),
        "requiredTools": list(REQUIRED_TOOLS),
    }


def _list_tools_isolated(plugin_root: Path) -> dict[str, dict[str, Any]]:
    server = plugin_root / "mcp" / "server.py"
    if not server.is_file():
        raise HealthError("local tool server is missing")
    request = json.dumps(
        {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}},
        separators=(",", ":"),
    ) + "\n"
    with tempfile.TemporaryDirectory(prefix="aivcp-stage6-health-") as temp_root:
        env = os.environ.copy()
        for name in tuple(env):
            if name.startswith("AIVCP_PUBLISHER_") or name.startswith("AIVCP_WORKSHOP_"):
                env.pop(name, None)
        env.update(
            {
                "AIVCP_DATA_ROOT": str(Path(temp_root) / "data"),
                "AIVCP_NETWORK_EXECUTION": "false",
                "AIVCP_PUBLISHER_NETWORK_EXECUTION": "false",
                "PYTHONDONTWRITEBYTECODE": "1",
            }
        )
        try:
            completed = subprocess.run(
                [sys.executable, str(server), "mcp"],
                input=request,
                text=True,
                capture_output=True,
                cwd=plugin_root,
                env=env,
                timeout=30,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise HealthError("isolated local tool service timed out") from exc
        except OSError as exc:
            raise HealthError("isolated local tool service could not start") from exc
    if completed.returncode != 0:
        raise HealthError("isolated local tool service failed")
    if len(completed.stdout.encode("utf-8")) > 2 * 1024 * 1024:
        raise HealthError("local tool list response is too large")
    lines = [line for line in completed.stdout.splitlines() if line.strip()]
    if len(lines) != 1:
        raise HealthError("local tool service returned an unexpected response count")
    try:
        response = json.loads(lines[0])
        tools = response["result"]["tools"]
        definitions = {str(item["name"]): item for item in tools}
    except (KeyError, TypeError, json.JSONDecodeError) as exc:
        raise HealthError("local tool list response is invalid") from exc
    if len(definitions) != len(tools):
        raise HealthError("local tool list contains duplicate names")
    return definitions


def check(plugin_root: Path, *, static_only: bool) -> dict[str, Any]:
    root = plugin_root.expanduser().resolve()
    result = _check_static(root)
    if static_only:
        result.update({"status": "PASS", "serviceChecked": False, "networkExecution": False})
        return result
    definitions = _list_tools_isolated(root)
    missing = [name for name in REQUIRED_TOOLS if name not in definitions]
    if missing:
        raise HealthError("local tool service is missing: " + ", ".join(missing))
    for name in REQUIRED_TOOLS:
        schema = definitions[name].get("inputSchema")
        properties = schema.get("properties") if isinstance(schema, dict) else None
        gate = properties.get("networkExecution") if isinstance(properties, dict) else None
        required = schema.get("required") if isinstance(schema, dict) else None
        if not isinstance(gate, dict) or gate.get("const") is not False:
            raise HealthError(f"local tool does not force networkExecution=false: {name}")
        if not isinstance(required, list) or "networkExecution" not in required:
            raise HealthError(f"local tool does not require the network safety gate: {name}")
    result.update(
        {
            "status": "PASS",
            "serviceChecked": True,
            "toolCount": len(REQUIRED_TOOLS),
            "networkExecution": False,
            "networkGateChecked": True,
            "boundaries": {
                "productionData": "not_touched",
                "publisherDatabase": "not_touched",
                "publisherInbox": "not_touched",
                "oauth": "not_called",
                "youtubeUpload": "not_called",
                "remoteMutation": "not_called",
            },
        }
    )
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plugin-root", type=Path, default=_plugin_root_from_script())
    parser.add_argument("--static-only", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    try:
        result = check(args.plugin_root, static_only=args.static_only)
    except HealthError as exc:
        result = {
            "status": "FAIL",
            "error": str(exc),
            "networkExecution": False,
            "oauth": "not_called",
            "youtubeUpload": "not_called",
        }
        print(json.dumps(result, ensure_ascii=False, indent=2) if args.json else f"Health FAIL: {exc}")
        return 2
    print(
        json.dumps(result, ensure_ascii=False, indent=2)
        if args.json
        else f"Health PASS: {result['skill']}; serviceChecked={result['serviceChecked']}; networkExecution=false."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
