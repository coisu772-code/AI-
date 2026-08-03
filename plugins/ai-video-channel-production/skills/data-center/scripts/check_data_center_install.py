#!/usr/bin/env python3
"""Read-only Stage7 data-center Skill and local tool installation health check."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any


SKILL_NAME = "data-center"
REQUIRED_TOOLS = (
    "data_center_capabilities",
    "data_video_register",
    "data_collection_run",
    "data_report_generate",
    "data_recommendations_list",
    "data_learning_decide",
    "data_progress_get",
)
REQUIRED_SKILL_FILES = (
    "SKILL.md",
    "agents/openai.yaml",
    "references/tool-protocol.md",
    "scripts/check_data_center_install.py",
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
        "WAITING_FOR_PUBLICATION_RECEIPT",
        "AUTH_REQUIRED",
        "available=false",
        "syntheticFixture=true",
        "LONG_TERM_LEARNING_APPROVAL_REQUIRED",
        "AWAITING_LEARNING_DECISION",
        "UNKNOWN",
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


def _run_isolated_service(plugin_root: Path) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    server = plugin_root / "mcp" / "server.py"
    if not server.is_file():
        raise HealthError("local tool server is missing")
    requests = (
        json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}, separators=(",", ":"))
        + "\n"
        + json.dumps(
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {"name": "data_center_capabilities", "arguments": {}},
            },
            separators=(",", ":"),
        )
        + "\n"
    )
    with tempfile.TemporaryDirectory(prefix="aivcp-stage7-health-") as temp_root:
        env = os.environ.copy()
        for name in tuple(env):
            upper = name.upper()
            if (
                upper.startswith(("AIVCP_ANALYTICS_", "AIVCP_PUBLISHER_", "AIVCP_WORKSHOP_", "GOOGLE_", "YOUTUBE_"))
                or "OAUTH" in upper
                or "TOKEN" in upper
            ):
                env.pop(name, None)
        env.update(
            {
                "AIVCP_DATA_ROOT": str(Path(temp_root) / "data"),
                "AIVCP_NETWORK_EXECUTION": "false",
                "AIVCP_ANALYTICS_AVAILABLE": "false",
                "AIVCP_ANALYTICS_REVENUE_SCOPE": "false",
                "PYTHONDONTWRITEBYTECODE": "1",
            }
        )
        try:
            completed = subprocess.run(
                [sys.executable, str(server), "mcp"],
                input=requests,
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
        raise HealthError("local tool response is too large")
    lines = [line for line in completed.stdout.splitlines() if line.strip()]
    if len(lines) != 2:
        raise HealthError("local tool service returned an unexpected response count")
    try:
        responses = {item["id"]: item for item in (json.loads(line) for line in lines)}
        tools = responses[1]["result"]["tools"]
        definitions = {str(item["name"]): item for item in tools}
        payload = responses[2]["result"]["structuredContent"]
        capability = payload["result"]
    except (KeyError, TypeError, json.JSONDecodeError) as exc:
        raise HealthError("local tool response is invalid") from exc
    if len(definitions) != len(tools):
        raise HealthError("local tool list contains duplicate names")
    if not isinstance(capability, dict):
        raise HealthError("data-center capabilities result is invalid")
    return definitions, capability


def check(plugin_root: Path, *, static_only: bool) -> dict[str, Any]:
    root = plugin_root.expanduser().resolve()
    result = _check_static(root)
    if static_only:
        result.update({"status": "PASS", "serviceChecked": False})
        return result
    definitions, capability = _run_isolated_service(root)
    missing = [name for name in REQUIRED_TOOLS if name not in definitions]
    if missing:
        raise HealthError("local tool service is missing: " + ", ".join(missing))
    authorization = capability.get("analyticsAuthorization")
    if not isinstance(authorization, dict):
        raise HealthError("data-center capabilities are missing analyticsAuthorization")
    if authorization.get("status") != "AUTH_REQUIRED" or authorization.get("available") is not False:
        raise HealthError("Analytics authorization must default to AUTH_REQUIRED and available=false")
    monetary = authorization.get("monetaryScope")
    if not isinstance(monetary, dict) or monetary.get("enabled") is not False or monetary.get("available") is not False:
        raise HealthError("Analytics monetary scope must default to disabled and unavailable")
    if authorization.get("oauthStarted") is not False:
        raise HealthError("data-center health check must not start OAuth")
    metric_catalog = capability.get("metricCatalog")
    if (
        not isinstance(metric_catalog, dict)
        or metric_catalog.get("available") is not True
        or metric_catalog.get("version") != "2026.08.04.1"
        or not isinstance(metric_catalog.get("sha256"), str)
        or len(metric_catalog["sha256"]) != 64
    ):
        raise HealthError("Metric Catalog v1 is missing or invalid")
    serialized = json.dumps(capability, ensure_ascii=False).lower()
    if any(secret_marker in serialized for secret_marker in ("access_token", "refresh_token", "client_secret")):
        raise HealthError("data-center capabilities exposed credential material")
    result.update(
        {
            "status": "PASS",
            "serviceChecked": True,
            "toolCount": len(REQUIRED_TOOLS),
            "analyticsAuthorization": "AUTH_REQUIRED",
            "analyticsAvailable": False,
            "revenueScopeEnabled": False,
            "metricCatalogVersion": metric_catalog["version"],
            "metricCatalogSha256": metric_catalog["sha256"],
            "boundaries": {
                "productionData": "not_touched",
                "existingChannelDatabase": "not_touched",
                "oauth": "not_called",
                "token": "not_read",
                "analyticsPrivateApi": "not_called",
                "longTermLearningWrite": "not_called",
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
            "analyticsAvailable": False,
            "oauth": "not_called",
            "token": "not_read",
            "longTermLearningWrite": "not_called",
        }
        print(json.dumps(result, ensure_ascii=False, indent=2) if args.json else f"Health FAIL: {exc}")
        return 2
    print(
        json.dumps(result, ensure_ascii=False, indent=2)
        if args.json
        else f"Health PASS: {result['skill']}; serviceChecked={result['serviceChecked']}; Analytics=AUTH_REQUIRED."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
