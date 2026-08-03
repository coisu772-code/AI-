from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
PLUGIN_ROOT = ROOT / "plugins" / "ai-video-channel-production"
sys.path.insert(0, str(PLUGIN_ROOT / "mcp"))

from aivcp_tools.production import ProductionCenter  # noqa: E402
from aivcp_tools.errors import ToolError  # noqa: E402


EXPECTED_MARKETS = {"ja-JP", "zh-CN", "en-US"}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def validate(output_root: Path) -> list[str]:
    errors: list[str] = []
    root = output_root.resolve()
    summary_path = root / "summary.json"
    if not summary_path.is_file():
        return ["summary.json is missing"]
    try:
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return ["summary.json is invalid"]
    if set(summary.get("markets", {})) != EXPECTED_MARKETS:
        errors.append("summary must contain ja-JP, zh-CN, and en-US")
    for boundary in (
        "publisherCenterCalled",
        "oauthExecuted",
        "uploadExecuted",
        "readyPackageCreated",
        "longTermLearningWrite",
    ):
        if summary.get(boundary) is not False:
            errors.append(f"boundary must remain false: {boundary}")
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        errors.append("ffprobe is unavailable")
        return errors
    center = ProductionCenter(root, ffmpeg_path=shutil.which("ffmpeg"), ffprobe_path=ffprobe)
    for market, record in summary.get("markets", {}).items():
        try:
            package_root = (root / record["productionPackagePath"]).resolve()
            result_root = (root / record["resultPath"]).resolve()
            if root not in package_root.parents or root not in result_root.parents:
                raise ValueError("path escapes output root")
            package_manifest = center.validate_package(package_root)
            result = center.validate_result_package(result_root)["manifest"]
            if package_manifest["packageHash"] != record.get("packageHash"):
                errors.append(f"{market}: production package hash mismatch")
            video_path = result_root / result["finalVideo"]["relativePath"]
            if _sha256(video_path) != record.get("videoSha256"):
                errors.append(f"{market}: final video hash mismatch")
            probe = subprocess.run(
                [ffprobe, "-v", "error", "-show_entries", "stream=codec_type,width,height", "-of", "json", str(video_path)],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=False,
            )
            if probe.returncode != 0:
                errors.append(f"{market}: ffprobe failed")
            else:
                streams = json.loads(probe.stdout).get("streams", [])
                if {stream.get("codec_type") for stream in streams} != {"video", "audio"}:
                    errors.append(f"{market}: audio/video streams missing")
            if any(path.name.endswith(".ready") for path in result_root.rglob("*")):
                errors.append(f"{market}: forbidden .ready package found")
        except (KeyError, OSError, ValueError, json.JSONDecodeError, ToolError) as exc:
            errors.append(f"{market}: {type(exc).__name__}: {exc}")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate Stage5 synthetic production outputs")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    errors = validate(args.output)
    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        print(f"Stage5 output validation failed with {len(errors)} error(s).")
        return 1
    print("Stage5 output validation passed for 3 market(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
