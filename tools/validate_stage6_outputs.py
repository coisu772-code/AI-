from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PLUGIN_ROOT = ROOT / "plugins" / "ai-video-channel-production"
sys.path.insert(0, str(PLUGIN_ROOT / "mcp"))

from aivcp_tools.publish_package_v2 import validate_publish_package_v2  # noqa: E402


CATALOG = ROOT / "contracts" / "youtube-constraints" / "catalog-2026.08.04.1.json"
EXPECTED = {
    "ja-JP": ("DO_NOT_UPLOAD", "PACKAGE_READY"),
    "zh-CN": ("REQUIRE_REVIEW", "WAITING_REVIEW"),
    "en-US": ("AUTO", "WAITING_REVIEW"),
}


def _read(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"JSON root must be an object: {path}")
    return value


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def validate(output_root: Path) -> dict:
    output_root = output_root.resolve(strict=True)
    summary_path = output_root / "summary.json"
    summary = _read(summary_path)
    expected_hash = (output_root / "summary.sha256").read_text(encoding="utf-8").split()[0]
    if _sha(summary_path) != expected_hash:
        raise RuntimeError("summary SHA-256 mismatch")
    if any(
        (
            summary.get("online_data"), summary.get("real_channel_data"), summary.get("oauth_executed"),
            summary.get("upload_executed"), summary.get("remote_mutation_executed"),
            summary.get("youtube_video_ids"), summary.get("publication_receipts"),
        )
    ):
        raise RuntimeError("Stage6 fixture summary crosses the offline safety boundary")
    validated: dict[str, object] = {}
    for language, (policy, state) in EXPECTED.items():
        item = summary["markets"][language]
        if item["policy"] != policy or item["expected_state"] != state or item["actual_state"] != state:
            raise RuntimeError(f"{language}: policy/state matrix mismatch")
        package = output_root / item["package_path"]
        result = validate_publish_package_v2(package, constraints_catalog_path=CATALOG)
        if result["status"] != state or result["package_hash"] != item["package_hash"]:
            raise RuntimeError(f"{language}: package validation mismatch")
        if result["youtube_video_id"] is not None or result["publication_receipt"] is not None:
            raise RuntimeError(f"{language}: forged remote upload evidence")
        validated[language] = result
    return {"valid": True, "market_count": len(validated), "markets": validated, "network_execution": False}


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate three offline synthetic Stage6 fixture packages")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(validate(args.output), ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
