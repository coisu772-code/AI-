from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PLUGIN_ROOT = ROOT / "plugins" / "ai-video-channel-production"
sys.path.insert(0, str(PLUGIN_ROOT / "mcp"))

from aivcp_tools.publish_package_v2 import (  # noqa: E402
    PublishPackageError,
    assemble_publish_package_v2,
    validate_publish_package_v2,
)


DEFAULT_CATALOG = ROOT / "contracts" / "youtube-constraints" / "catalog-2026.08.04.1.json"


def _load_json(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("JSON root must be an object")
    return value


def main() -> int:
    parser = argparse.ArgumentParser(description="Offline-only YouTube publish package v2 assembler and validator")
    subcommands = parser.add_subparsers(dest="command", required=True)

    assemble = subcommands.add_parser("assemble", help="Assemble .creating and atomically promote it to .ready")
    assemble.add_argument("--production-result", type=Path, required=True)
    assemble.add_argument("--publishing-asset", type=Path, required=True)
    assemble.add_argument("--inbox", type=Path, required=True)
    assemble.add_argument("--channel-profile", type=Path, required=True)
    assemble.add_argument("--authorization", type=Path)
    assemble.add_argument("--limits", type=Path)
    assemble.add_argument("--scheduled-at")
    assemble.add_argument("--schedule-conflict", action="store_true")
    assemble.add_argument("--timezone")
    assemble.add_argument("--created-at")
    assemble.add_argument("--ffprobe")
    assemble.add_argument("--constraints-catalog", type=Path, default=DEFAULT_CATALOG)

    validate = subcommands.add_parser("validate", help="Validate a complete .ready package; .creating is always rejected")
    validate.add_argument("--package", type=Path, required=True)
    validate.add_argument("--ffprobe")
    validate.add_argument("--constraints-catalog", type=Path, default=DEFAULT_CATALOG)

    args = parser.parse_args()
    try:
        if args.command == "assemble":
            result = assemble_publish_package_v2(
                production_result_root=args.production_result,
                publishing_asset_root=args.publishing_asset,
                inbox_root=args.inbox,
                channel_profile=_load_json(args.channel_profile),
                constraints_catalog_path=args.constraints_catalog,
                authorization=_load_json(args.authorization) if args.authorization else None,
                limits=_load_json(args.limits) if args.limits else None,
                scheduled_at=args.scheduled_at,
                schedule_conflict=args.schedule_conflict,
                timezone=args.timezone,
                created_at=args.created_at,
                ffprobe_path=args.ffprobe,
            )
        else:
            result = validate_publish_package_v2(
                args.package,
                constraints_catalog_path=args.constraints_catalog,
                ffprobe_path=args.ffprobe,
            )
    except (PublishPackageError, ValueError, OSError) as exc:
        error = {
            "ok": False,
            "error": getattr(exc, "code", "PUBLISH_COMMAND_FAILED"),
            "message": str(exc),
            "details": getattr(exc, "details", {}),
            "network_execution": False,
        }
        print(json.dumps(error, ensure_ascii=False, indent=2, sort_keys=True))
        return 2
    print(json.dumps({"ok": True, **result}, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
