from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from stage4_support import (
    MARKETS,
    PipelineContext,
    StaticPublisherProvider,
    build_complete_pipeline,
    finalize_manuscript,
    finalize_topic,
    start_topic_context,
)


@dataclass
class Stage5Context:
    content: PipelineContext
    package: dict[str, Any]
    production_task_id: str
    production_config: dict[str, Any]


def production_config(
    *,
    delivery_mode: str = "auto_render",
    selection_mode: str = "none",
    count: int | None = None,
    fallback_policy: str = "pause",
) -> dict[str, Any]:
    video = {
        "enabled": selection_mode != "none",
        "selectionMode": selection_mode,
        "fallbackPolicy": fallback_policy,
    }
    if count is not None:
        video["count"] = count
    return {
        "deliveryMode": delivery_mode,
        "aspectRatio": "16:9",
        "width": 640,
        "height": 360,
        "frameRate": 24,
        "imageStyle": {
            "presetId": "visual_01",
            "prompt": "现代二维电视动画正片风格，干净轮廓线，克制赛璐璐上色，统一人物比例与色彩。",
        },
        "storyImageTextPolicy": "forbid_visible_text",
        "voiceTtsProfile": {
            "selectionSource": "user",
            "engineId": "fixture-tts",
            "recommendVoicesFromSelectedEngineOnly": True,
            "lockScope": "current_project",
        },
        "soundEffects": {
            "enabled": False,
            "engineId": "seed_audio",
            "modelId": "seed-audio-1.0",
            "requireExplicitDuration": True,
            "maxDurationSeconds": 5.0,
            "standaloneStoryboard": False,
            "mixWithAdjacentSpeech": True,
            "backgroundMusicEnabled": False,
        },
        "videoGeneration": video,
        "concurrency": {"image": 1, "video": 1, "tts": 1},
        "retryLimit": 2,
        "syntheticFixtureRunner": True,
    }


def build_stage5_context(
    root: Path,
    language: str,
    *,
    plugin_root: Path,
    local_tool_service: Any,
    service_config: Any,
    thumbnail_path: Path,
    delivery_mode: str = "auto_render",
    selection_mode: str = "none",
    count: int | None = None,
    fallback_policy: str = "pause",
    omit_optional_publishing_assets: bool = False,
) -> Stage5Context:
    content = start_topic_context(
        root,
        language,
        plugin_root=plugin_root,
        local_tool_service=local_tool_service,
        service_config=service_config,
    )
    if omit_optional_publishing_assets:
        finalize_topic(content)
        finalize_manuscript(content)
        content.service.call(
            "content_publishing_finalize",
            {
                "taskId": content.task_id,
                "channelProfileId": content.channel_id,
                "bindingProof": content.proof,
                "projectId": content.project_id,
                "title": content.market["title"],
                "titleChinese": content.market["titleZh"],
                "titleSource": "confirmed_narration",
                "storySummaryChinese": "社区共同空间面临关闭，主角寻找记录并联合居民核验证据，最终让场所重新开放。",
                "confirmation": {
                    "confirmed": True,
                    "mode": "review",
                    "confirmedBy": "synthetic-fixture-user",
                    "confirmedAt": "2026-08-04T03:00:00Z",
                },
            },
        )
    else:
        build_complete_pipeline(content, thumbnail_path)
    config = production_config(
        delivery_mode=delivery_mode,
        selection_mode=selection_mode,
        count=count,
        fallback_policy=fallback_policy,
    )
    assembled = content.service.call(
        "production_package_assemble",
        {
            "taskId": content.task_id,
            "channelProfileId": content.channel_id,
            "bindingProof": content.proof,
            "projectId": content.project_id,
            "productionConfig": config,
            "productionPreset": {
                "id": f"synthetic-{MARKETS[language]['key']}-production",
                "version": "1.0.0",
                "hash": "1" * 64,
                "targetRegion": MARKETS[language]["region"],
                "synthetic": True,
            },
            "workshopCompatibility": {
                "interfaceVersion": "2.1",
                "workshopVersion": "0.5.0-stage5",
                "adapter": "novel-manga-workshop-cli",
            },
            "synthetic": True,
        },
    )
    production_task_id = f"task-stage5-{MARKETS[language]['key']}"
    content.service.call(
        "production_task_start",
        {
            "taskId": content.task_id,
            "channelProfileId": content.channel_id,
            "bindingProof": content.proof,
            "productionTaskId": production_task_id,
            "productionPackagePath": assembled["packagePath"],
        },
    )
    return Stage5Context(content, assembled, production_task_id, config)


def mutation_arguments(context: Stage5Context) -> dict[str, Any]:
    return {
        "taskId": context.content.task_id,
        "channelProfileId": context.content.channel_id,
        "bindingProof": context.content.proof,
        "productionTaskId": context.production_task_id,
    }


def export_identity(context: Stage5Context, video_path: Path, *, project_id: str | None = None) -> dict[str, Any]:
    import hashlib

    return {
        "projectId": project_id or context.content.project_id,
        "productionTaskId": context.production_task_id,
        "packageHash": context.package["manifest"]["packageHash"],
        "videoSha256": hashlib.sha256(video_path.read_bytes()).hexdigest(),
    }


def summarize_result(result_root: Path) -> dict[str, Any]:
    manifest = json.loads((result_root / "manifest.json").read_text(encoding="utf-8"))
    validation = json.loads((result_root / "validation-report.json").read_text(encoding="utf-8"))
    return {
        "resultPath": str(result_root),
        "productionResultPackageId": manifest["productionResultPackageId"],
        "packageHash": manifest["productionPackageHash"],
        "videoSha256": manifest["finalVideo"]["sha256"],
        "videoSizeBytes": manifest["finalVideo"]["sizeBytes"],
        "subtitlesSha256": manifest["subtitles"]["sha256"],
        "width": validation["width"],
        "height": validation["height"],
        "durationSeconds": validation["durationSeconds"],
        "videoCodec": validation["videoCodec"],
        "audioCodec": validation["audioCodec"],
        "synthetic": manifest["synthetic"],
    }
