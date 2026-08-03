from __future__ import annotations

import json
import shutil
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PLUGIN_ROOT = ROOT / "plugins" / "ai-video-channel-production"
sys.path.insert(0, str(PLUGIN_ROOT / "mcp"))
sys.path.insert(0, str(ROOT / "tests"))

from aivcp_tools.service import LocalToolService, ServiceConfig  # noqa: E402
from stage4_support import MARKETS, build_complete_pipeline, export_packages, start_topic_context  # noqa: E402


THUMBNAIL = ROOT / "contracts" / "examples" / "valid" / "fixtures" / "confirmed-thumbnail-1600x900.png"
OUTPUT = ROOT / "tests" / "fixtures" / "stage4" / "packages"


def main() -> int:
    if not THUMBNAIL.is_file():
        raise SystemExit("Synthetic 1600x900 PNG fixture is missing.")
    OUTPUT.mkdir(parents=True, exist_ok=True)
    index = {
        "schemaVersion": "1.0.0",
        "syntheticFixture": True,
        "onlineData": False,
        "userData": False,
        "generatedFor": "stage4-content-loop-validation",
        "markets": [],
    }
    with tempfile.TemporaryDirectory(prefix="aivcp-stage4-fixture-build-") as temp_name:
        build_root = Path(temp_name)
        for language in MARKETS:
            context = start_topic_context(
                build_root / language,
                language,
                plugin_root=PLUGIN_ROOT,
                local_tool_service=LocalToolService,
                service_config=ServiceConfig,
            )
            result = build_complete_pipeline(context, THUMBNAIL)
            destination = OUTPUT / language
            validation = export_packages(result, destination, language=language)

            source_detail = context.service.call(
                "source_get",
                {"channelProfileId": context.channel_id, "sourcePackageId": context.source["source_package_id"]},
            )
            source_manifest = context.service.store.channel_path(context.channel_id) / source_detail["source"]["manifest_relative_path"]
            shutil.copytree(source_manifest.parent, destination / "source-package")
            channel_context = context.service.call("channel_get", {"channelProfileId": context.channel_id})
            (destination / "channel-context.json").write_text(
                json.dumps(
                    {
                        "syntheticFixture": True,
                        "channelProfile": channel_context["channelProfile"],
                        "productionProfile": channel_context["productionProfile"],
                    },
                    ensure_ascii=False,
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )
            index["markets"].append(
                {
                    "language": language,
                    "path": language,
                    "integrity": validation["integrity"]["status"],
                    "handoffEligible": validation["handoff"]["eligible"],
                    "note": "Short synthetic fixture; never treat as online performance or user data.",
                }
            )
    (OUTPUT / "fixture-index.json").write_text(json.dumps(index, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Generated {len(index['markets'])} synthetic Stage4 package chains under {OUTPUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
