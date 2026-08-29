from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PLUGIN_ROOT = ROOT / "plugins" / "ai-video-channel-production"
sys.path.insert(0, str(PLUGIN_ROOT / "mcp"))
sys.path.insert(0, str(ROOT / "tests"))

from aivcp_tools.service import LocalToolService, ServiceConfig  # noqa: E402
from stage5_support import build_stage5_context, export_identity, mutation_arguments, summarize_result  # noqa: E402


THUMBNAIL = ROOT / "contracts" / "examples" / "valid" / "fixtures" / "confirmed-thumbnail-1600x900.png"


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _relative(path: Path, root: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def generate(output_root: Path) -> dict[str, object]:
    output_root = output_root.resolve()
    if output_root.exists() and any(output_root.iterdir()):
        raise RuntimeError(f"output directory is not empty: {output_root}")
    output_root.mkdir(parents=True, exist_ok=True)
    markets: dict[str, object] = {}

    ja = build_stage5_context(
        output_root / "ja-JP" / "workspace",
        "ja-JP",
        plugin_root=PLUGIN_ROOT,
        local_tool_service=LocalToolService,
        service_config=ServiceConfig,
        thumbnail_path=THUMBNAIL,
        delivery_mode="auto_render",
        selection_mode="none",
    )
    ja_args = mutation_arguments(ja)
    ja.content.service.call("production_task_run", {**ja_args, "pauseAfterStep": "P4"})
    ja.content.service.call("production_task_resume", ja_args)
    ja_task = ja.content.service.call("production_task_run", ja_args)["task"]
    markets["ja-JP"] = {
        **summarize_result(Path(ja_task["resultPackagePath"])),
        "productionPackagePath": _relative(Path(ja.package["packagePath"]), output_root),
        "resultPath": _relative(Path(ja_task["resultPackagePath"]), output_root),
        "flowEvidence": ["pause-after-P4", "service-resume", "auto-render", "ffprobe-validation"],
        "selectedStoryboardIds": ja_task["selectedStoryboardIds"],
        "fallbacks": ja_task["fallbacks"],
    }

    zh = build_stage5_context(
        output_root / "zh-CN" / "workspace",
        "zh-CN",
        plugin_root=PLUGIN_ROOT,
        local_tool_service=LocalToolService,
        service_config=ServiceConfig,
        thumbnail_path=THUMBNAIL,
        delivery_mode="auto_render",
        selection_mode="project_first_n_storyboards",
        count=1,
        fallback_policy="use_static_image",
    )
    zh_args = mutation_arguments(zh)
    zh_task = zh.content.service.call(
        "production_task_run", {**zh_args, "failStoryboardIds": ["SB-E01-L001"]}
    )["task"]
    markets["zh-CN"] = {
        **summarize_result(Path(zh_task["resultPackagePath"])),
        "productionPackagePath": _relative(Path(zh.package["packagePath"]), output_root),
        "resultPath": _relative(Path(zh_task["resultPackagePath"]), output_root),
        "flowEvidence": ["project-first-n-video", "authorized-static-fallback", "auto-render", "ffprobe-validation"],
        "selectedStoryboardIds": zh_task["selectedStoryboardIds"],
        "fallbacks": zh_task["fallbacks"],
    }

    en = build_stage5_context(
        output_root / "en-US" / "workspace",
        "en-US",
        plugin_root=PLUGIN_ROOT,
        local_tool_service=LocalToolService,
        service_config=ServiceConfig,
        thumbnail_path=THUMBNAIL,
        delivery_mode="jianying_refine",
        selection_mode="all_storyboards",
        fallback_policy="pause",
    )
    en_args = mutation_arguments(en)
    en.content.service.call("production_task_run", {**en_args, "failStoryboardIds": ["SB-E01-L001"]})
    en.content.service.call("production_task_retry", en_args)
    en.content.service.call("production_task_resume", en_args)
    waiting = en.content.service.call("production_task_run", en_args)["task"]
    export_root = output_root / "en-US" / "jianying-user-export"
    export_path = export_root / "export.mp4"
    draft_timeline = json.loads(
        (Path(waiting["jianyingDraftPackagePath"]) / "timeline-map.json").read_text(encoding="utf-8")
    )
    expected_export_duration = float(draft_timeline["durationSeconds"])
    en.content.service.production._render_media(
        Path(en.package["packagePath"]) / "confirmed_thumbnail.png",
        export_path,
        duration_seconds=expected_export_duration,
        width=640,
        height=360,
        frame_rate=24,
    )
    identity_path = export_root / "export-identity.json"
    _write_json(identity_path, export_identity(en, export_path))
    en_task = en.content.service.call(
        "production_jianying_export_ingest",
        {**en_args, "exportPath": str(export_path), "identityPath": str(identity_path)},
    )["task"]
    markets["en-US"] = {
        **summarize_result(Path(en_task["resultPackagePath"])),
        "productionPackagePath": _relative(Path(en.package["packagePath"]), output_root),
        "jianyingDraftPackagePath": _relative(Path(waiting["jianyingDraftPackagePath"]), output_root),
        "jianyingExportPath": _relative(export_path, output_root),
        "resultPath": _relative(Path(en_task["resultPackagePath"]), output_root),
        "flowEvidence": [
            "unauthorized-fallback-paused",
            "failed-asset-only-retry",
            "jianying-draft-v1",
            "identity-checked-export-ingest",
            "ffprobe-validation",
        ],
        "selectedStoryboardIds": en_task["selectedStoryboardIds"],
        "fallbacks": en_task["fallbacks"],
    }

    summary: dict[str, object] = {
        "schemaVersion": "1.0.0",
        "generatedFor": "stage5-production-handoff-validation",
        "syntheticFixture": True,
        "onlineData": False,
        "userData": False,
        "externalImageServiceCalled": False,
        "externalVideoServiceCalled": False,
        "externalTtsServiceCalled": False,
        "publisherCenterCalled": False,
        "oauthExecuted": False,
        "uploadExecuted": False,
        "readyPackageCreated": False,
        "longTermLearningWrite": False,
        "markets": markets,
    }
    summary_bytes = (json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")
    (output_root / "summary.json").write_bytes(summary_bytes)
    (output_root / "summary.sha256").write_text(hashlib.sha256(summary_bytes).hexdigest() + "  summary.json\n", encoding="utf-8")
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate deterministic Stage5 synthetic production outputs")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    summary = generate(args.output)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
