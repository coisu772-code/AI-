from __future__ import annotations

import argparse
import json
import os
import subprocess
from pathlib import Path


COMPONENT_PATH_VARIABLES = (
    "AIVCP_WORKSHOP_EXECUTABLE",
    "AIVCP_WORKSHOP_ISOLATION_ROOT",
    "AIVCP_FFMPEG_PATH",
    "AIVCP_FFPROBE_PATH",
    "AIVCP_PUBLISHER_CHANNEL_LIST_EXE",
    "AIVCP_PUBLISHER_V2_CLI",
    "AIVCP_PUBLISHER_DESKTOP_EXE",
)


def invoke(command: Path, arguments: list[str], cwd: Path, environment: dict[str, str]) -> dict[str, object]:
    completed = subprocess.run(
        [str(command), *arguments],
        cwd=cwd,
        env=environment,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=30,
        check=False,
    )
    stdout = completed.stdout.decode("utf-8-sig", errors="replace").strip()
    stderr = completed.stderr.decode("utf-8-sig", errors="replace").strip()
    try:
        payload = json.loads(stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Tampered binding returned invalid JSON: exit={completed.returncode}; stdout={stdout}; stderr={stderr}") from exc
    code = payload.get("error", {}).get("code") if isinstance(payload, dict) else None
    if completed.returncode != 2 or payload.get("ok") is not False or code != "RUNTIME_BINDING_MISMATCH":
        raise RuntimeError(
            f"Tampered binding was not rejected: exit={completed.returncode}; code={code}; stdout={stdout}; stderr={stderr}"
        )
    return {"exitCode": completed.returncode, "errorCode": code}


def main() -> int:
    parser = argparse.ArgumentParser(description="Prove installed MCP component path/version tampering is rejected before service startup.")
    parser.add_argument("--cached-plugin-root", required=True, type=Path)
    parser.add_argument("--report", required=True, type=Path)
    args = parser.parse_args()

    cached_plugin = args.cached_plugin_root.resolve()
    descriptor = json.loads((cached_plugin / ".mcp.json").read_text(encoding="utf-8-sig"))
    server = descriptor["mcpServers"]["ai-video-channel-tools"]
    command = Path(server["command"]).resolve()
    arguments = ["./mcp/server.py", "capabilities"]
    baseline = os.environ.copy()
    baseline.update({str(key): str(value) for key, value in server["env"].items()})

    fixture_root = args.report.resolve().parent / "runtime-binding-tamper-fixtures"
    fixture_root.mkdir(parents=True, exist_ok=True)
    outside_file = fixture_root / "outside-component.exe"
    outside_file.write_bytes(b"not executable and must never be started")
    outside_directory = fixture_root / "outside-workshop-isolation"
    outside_directory.mkdir(exist_ok=True)

    results: dict[str, object] = {}
    for name in COMPONENT_PATH_VARIABLES:
        environment = baseline.copy()
        environment[name] = str(outside_directory if name == "AIVCP_WORKSHOP_ISOLATION_ROOT" else outside_file)
        results[name] = invoke(command, arguments, cached_plugin, environment)

    youtube_environment = baseline.copy()
    youtube_command = json.loads(youtube_environment["AIVCP_YT_DLP_COMMAND_JSON"])
    youtube_command[4] = "deno:" + str(outside_file)
    youtube_environment["AIVCP_YT_DLP_COMMAND_JSON"] = json.dumps(youtube_command, separators=(",", ":"))
    results["AIVCP_YT_DLP_COMMAND_JSON"] = invoke(command, arguments, cached_plugin, youtube_environment)

    stale_environment = baseline.copy()
    stale_environment["AIVCP_EXPECTED_PRODUCT_VERSION"] = "0.7.0-stale-binding"
    results["AIVCP_EXPECTED_PRODUCT_VERSION"] = invoke(command, arguments, cached_plugin, stale_environment)

    report = {
        "schemaVersion": "1.0.0",
        "status": "PASS",
        "mode": "RUNTIME_BINDING_COMPONENT_PATH_AND_VERSION_TAMPER_REJECTION",
        "cases": results,
        "allRejectedBeforeService": True,
        "networkExecution": False,
        "oauth": False,
        "upload": False,
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Runtime binding tamper rejection PASS: {args.report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
