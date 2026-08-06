from __future__ import annotations

import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .errors import ToolError


def resolve_contracts_root(plugin_root: Path) -> Path:
    """Resolve contracts in both a source checkout and Codex's plugin cache."""
    source_candidate = plugin_root.resolve().parents[1] / "contracts"
    if source_candidate.is_dir():
        return source_candidate
    install_root = os.environ.get("AIVCP_INSTALL_ROOT", "").strip()
    if install_root:
        installed_candidate = Path(install_root).resolve() / "current" / "contracts"
        if installed_candidate.is_dir():
            return installed_candidate
    return source_candidate


def utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def canonical_hash(document: dict[str, Any]) -> str:
    payload = dict(document)
    payload.pop("contentHash", None)
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def with_hash(document: dict[str, Any]) -> dict[str, Any]:
    result = dict(document)
    result["contentHash"] = canonical_hash(result)
    return result


def validate_defaults(defaults: Any) -> dict[str, Any]:
    if not isinstance(defaults, dict):
        raise ToolError("INVALID_DEFAULTS", "生产默认值必须是对象。")
    required = {"voice", "manuscript", "episodes", "deliveryMode", "videoGeneration", "uploadPolicy"}
    missing = sorted(required - set(defaults))
    if missing:
        raise ToolError("INVALID_DEFAULTS", "生产默认值缺少必填项。", details={"missing": missing})

    voice = defaults.get("voice")
    if not isinstance(voice, dict) or not all(isinstance(voice.get(key), str) and voice[key].strip() for key in ("engineId", "voiceId")):
        raise ToolError("INVALID_DEFAULTS", "默认配音必须包含真实目录中的 engineId 和 voiceId。")

    for key, preferred_key, minimum_key, maximum_key in (
        ("manuscript", "preferredCharacters", "minCharacters", "maxCharacters"),
        ("episodes", "preferredCount", "minCount", "maxCount"),
    ):
        value = defaults.get(key)
        if not isinstance(value, dict) or value.get("mode") != "auto_by_topic":
            raise ToolError("INVALID_DEFAULTS", f"{key} 必须使用 auto_by_topic 范围策略。")
        numbers = [value.get(minimum_key), value.get(preferred_key), value.get(maximum_key)]
        if any(not isinstance(number, int) or isinstance(number, bool) or number < 1 for number in numbers):
            raise ToolError("INVALID_DEFAULTS", f"{key} 范围必须是正整数。")
        if not numbers[0] <= numbers[1] <= numbers[2]:
            raise ToolError("INVALID_DEFAULTS", f"{key} 必须满足最小值 ≤ 偏好值 ≤ 最大值。")

    if defaults.get("deliveryMode") not in {"auto_render", "jianying_refine"}:
        raise ToolError("INVALID_DEFAULTS", "制作方式不受支持。")
    if defaults.get("uploadPolicy") not in {"DO_NOT_UPLOAD", "REQUIRE_REVIEW", "AUTO"}:
        raise ToolError("INVALID_DEFAULTS", "上传策略不受支持。")
    video = defaults.get("videoGeneration")
    if not isinstance(video, dict):
        raise ToolError("INVALID_DEFAULTS", "videoGeneration 必须是对象。")
    if not isinstance(video.get("enabled"), bool):
        raise ToolError("INVALID_DEFAULTS", "videoGeneration.enabled 必须是布尔值。")
    if video.get("selectionMode") not in {
        "none", "project_first_n_storyboards", "episode_first_n_storyboards", "all_storyboards"
    }:
        raise ToolError("INVALID_DEFAULTS", "视频分镜选择方式不受支持。")
    if video.get("fallbackPolicy") not in {"pause", "use_static_image"}:
        raise ToolError("INVALID_DEFAULTS", "视频失败策略不受支持。")
    if video.get("selectionMode") in {"project_first_n_storyboards", "episode_first_n_storyboards"}:
        if not isinstance(video.get("count"), int) or isinstance(video.get("count"), bool) or video["count"] < 1:
            raise ToolError("INVALID_DEFAULTS", "按数量选择分镜时必须提供正整数 count。")
    return json.loads(json.dumps(defaults, ensure_ascii=False))


def channel_contract(
    *,
    channel_profile_id: str,
    display_name: str,
    target_region: str,
    output_language: str,
    publisher_profile_id: str,
    channel_serial: str,
    youtube_channel_id: str,
    created_at: str,
    version: str = "1.0.0",
) -> dict[str, Any]:
    return with_hash(
        {
            "schemaVersion": "1.0.0",
            "contractType": "channel-profile",
            "id": channel_profile_id,
            "version": version,
            "createdAt": created_at,
            "hashAlgorithm": "SHA-256",
            "hashRule": "canonical-json-v1",
            "upstream": [],
            "channelProfileId": channel_profile_id,
            "displayName": display_name,
            "lifecycleStatus": "READY",
            "targetRegion": target_region,
            "outputLanguage": output_language,
            "publisherBinding": {
                "publisherProfileId": publisher_profile_id,
                "channelSerial": channel_serial,
                "youtubeChannelId": youtube_channel_id,
            },
        }
    )


def production_contract(
    *,
    preset_id: str,
    channel: dict[str, Any],
    defaults: dict[str, Any],
    created_at: str,
    preset_version: str = "1.0.0",
    execution_mode: str = "review",
    first_confirmation: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return with_hash(
        {
            "schemaVersion": "1.0.0",
            "contractType": "production-profile",
            "id": preset_id,
            "version": preset_version,
            "createdAt": created_at,
            "hashAlgorithm": "SHA-256",
            "hashRule": "canonical-json-v1",
            "upstream": [
                {
                    "targetContractType": "channel-profile",
                    "targetId": channel["id"],
                    "targetVersion": channel["version"],
                    "targetSchemaVersion": channel["schemaVersion"],
                    "targetHash": channel["contentHash"],
                }
            ],
            "presetId": preset_id,
            "channelProfileId": channel["channelProfileId"],
            "presetVersion": preset_version,
            "executionMode": execution_mode,
            "defaults": validate_defaults(defaults),
            "firstConfirmation": first_confirmation
            or {"confirmed": True, "confirmedAt": created_at, "source": "user"},
        }
    )
