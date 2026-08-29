from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
import time
import uuid
from collections import Counter
from copy import deepcopy
from pathlib import Path
from typing import Any

from .contracts import canonical_hash, utc_now, with_hash
from .errors import ToolError
from .review_documents import (
    render_script_text,
    review_documents_view,
    save_review_document,
    validate_review_document_bindings,
    validate_review_documents,
)
from .security import contains_sensitive_material


PRODUCTION_CENTER_VERSION = "1.2.0"
PRODUCTION_PACKAGE_SCHEMA_VERSION = "2.1"
PRODUCTION_TASK_SCHEMA_VERSION = "1.0.0"
PRODUCTION_RESULT_SCHEMA_VERSION = "1.0.0"
PRODUCTION_TASK_RECENT_HISTORY_LIMIT = 100
PRODUCTION_TASK_DEFAULT_HISTORY_LIMIT = 50
PRODUCTION_TASK_MAX_HISTORY_PAGE = 1000
COALESCED_WORKSHOP_EVENTS = {
    "WORKSHOP_QUEUED",
    "WORKSHOP_STATUS_OBSERVED",
    "WORKSHOP_START_CONFIRMATION_PENDING",
}
PRODUCTION_PACKAGE_REQUIRED_FILES = {
    "project.json",
    "characters.json",
    "episodes.json",
    "script_lines.json",
    "production_config.json",
    "target_script_quality_gate.json",
    "publishing.json",
    "source_lock.json",
}
PRODUCTION_PACKAGE_OPTIONAL_FILES = {"confirmed_thumbnail.png"}
PRODUCTION_PACKAGE_FILES = PRODUCTION_PACKAGE_REQUIRED_FILES | PRODUCTION_PACKAGE_OPTIONAL_FILES
ACTIVE_TASK_STATES = {
    "PREFLIGHT",
    "READY_TO_PRODUCE",
    "IMPORTING",
    "RUNNING",
    "ASSET_DIAGNOSTICS",
    "AUTO_RENDERING",
    "JIANYING_DRAFT_READY",
    "AWAITING_JIANYING_EXPORT",
    "INGESTING_EXPORT",
    "RESULT_VALIDATING",
    "PAUSE_REQUESTED",
    "PAUSED",
    "QUEUED_WAITING_WORKSHOP",
    "NEEDS_CONFIGURATION",
    "NEEDS_REPAIR",
    "RETRYING",
}
TERMINAL_TASK_STATES = {"VIDEO_READY", "FAILED", "CANCELLED", "ARCHIVED"}
STEP_DEFINITIONS = (
    ("P0", "生产环境与输入包预检", ()),
    ("P1", "主要角色图生成", ("P0",)),
    ("P2", "角色资产质量门", ("P1",)),
    ("P3", "配音行与音色绑定校验", ("P2",)),
    ("P4", "逐句配音", ("P3",)),
    ("P5", "按锁定语义画面组生成分镜时间线", ("P4",)),
    ("P6", "按生产模式载入或生成分镜提示词", ("P5",)),
    ("P7", "宫格生图、切割与分镜回填", ("P6",)),
    ("P8", "可选分镜视频生成", ("P7",)),
    ("P9", "全片素材诊断", ("P8",)),
    ("P10", "自动成片或剪映完整包导出", ("P9",)),
    ("P11", "成片技术验收", ("P10",)),
)
VIDEO_SELECTION_MODES = {
    "none",
    "project_first_n_storyboards",
    "episode_first_n_storyboards",
    "all_storyboards",
}
PRODUCTION_MODE_IDS = {"fast_auto", "balanced", "director"}
PRODUCTION_MODE_LABELS = {
    "fast_auto": "极速自动模式",
    "balanced": "平衡模式",
    "director": "精品导演模式",
}
SCENE_IMAGE_CADENCE_MODES = {"semantic_auto", "seconds_range", "line_level", "custom"}
QUEUE_SCHEMA_VERSION = "2.0"

MAX_PRODUCTION_CONCURRENCY = 20
WORKSHOP_MISSING_TASK_GRACE_OBSERVATIONS = 2
WORKSHOP_MISSING_TASK_GRACE_SECONDS = 60.0

CODEX_VISUAL_PLAN_SCHEMA_VERSION = "1.5"
CODEX_VISUAL_PLAN_AUTHOR = "codex"
CODEX_REFERENCE_USAGE = "identity_only"
CODEX_REFERENCE_POLICIES = {"required", "optional", "none"}
CODEX_VISUAL_DIRECTION = {
    "mode": "manga_impact",
    "panelMode": "single_panel",
    "singleFocalPoint": True,
    "expressionMode": "exaggerated_story_driven",
    "backgroundSimplification": "impact_adaptive",
    "compositionMode": "story_driven",
    "mangaDeviceLimit": 3,
}
CODEX_REFERENCE_FLEXIBLE_FEATURES = (
    "expression",
    "gaze",
    "headPose",
    "bodyPose",
    "handGesture",
    "framing",
    "lighting",
    "background",
)
CODEX_PERFORMANCE_FIELDS = (
    "internalEmotion",
    "visibleEmotion",
    "intensity",
    "gaze",
    "eyes",
    "brows",
    "mouth",
    "headPose",
    "bodyPose",
    "handGesture",
    "interactionTarget",
    "changeFromPrevious",
)


def _character_appearance_contract(character: dict[str, Any]) -> dict[str, str]:
    character_id = _non_empty_text(character.get("characterId"), "character.characterId", maximum=128)
    policy = str(character.get("referencePolicy") or "").strip()
    if policy not in CODEX_REFERENCE_POLICIES:
        policy = "required" if character.get("visualConsistencyRequired") is True else "none"
    return {
        "personId": str(character.get("personId") or character_id).strip(),
        "appearanceId": str(character.get("appearanceId") or character_id).strip(),
        "lifePhase": str(character.get("lifePhase") or "current_life").strip(),
        "ageStage": str(character.get("ageStage") or "unspecified").strip(),
        "referencePolicy": policy,
    }


def _sound_effect_duration_profile(prompt: str) -> dict[str, float | str]:
    text = str(prompt or "").strip().lower()
    has = lambda *values: any(value in text for value in values)
    if has("音乐", "音樂", "旋律", "八音盒", "music", "melody", "song", "オルゴール", "音楽", "メロディ"):
        return {"category": "musical", "min": 3.0, "max": 4.8, "recommended": 3.8}
    if has("欢呼", "歡呼", "喝彩", "人群", "群众", "群眾", "笑声", "笑聲", "crowd", "cheer", "applause", "laughter", "歓声", "拍手", "群衆", "笑い声"):
        return {"category": "crowd", "min": 2.5, "max": 4.2, "recommended": 3.2}
    if has("风声", "風聲", "雨声", "雨聲", "火焰声", "篝火声", "海浪声", "河流声", "树林环境", "森林环境", "环境声", "環境音", "wind", "rain", "fire ambience", "waves", "river ambience", "forest ambience", "風音", "雨音", "波音"):
        return {"category": "ambience", "min": 3.0, "max": 4.8, "recommended": 3.8}
    if has("鼓", "钟", "鐘", "铃", "鈴", "锣", "鑼", "号角", "回响", "回響", "drum", "bell", "gong", "horn", "resonance", "太鼓", "角笛", "残響"):
        return {"category": "resonant", "min": 1.8, "max": 3.2, "recommended": 2.4}
    if has("转场", "轉場", "过渡", "過渡", "提示音", "系统音", "系統音", "transition", "whoosh", "swoosh", "通知音", "転換"):
        return {"category": "transition", "min": 1.6, "max": 3.0, "recommended": 2.2}
    return {"category": "transient", "min": 0.8, "max": 1.6, "recommended": 1.2}


def _classify_workshop_error(message: Any) -> dict[str, Any]:
    text = str(message or "").strip()
    normalized = text.lower()
    category = "unknown"
    recoverable = False
    action = "inspect_workshop_logs"
    patterns = (
        ("prompt_retry_exhausted", False, "repair_listed_storyboards", (
            "prompt_retry_exhausted", "提示词已达到", "提示词修复批次已达到", "有限重试上限",
        )),
        ("partial_prompt_generation", True, "retry_missing_prompt_items", (
            "仍缺少", "只补齐缺失", "只补齐剩余", "缺少图片提示词", "缺少视频提示词",
        )),
        ("provider_task_pending", True, "resume_original_provider_task", (
            "尚未完成", "待取回", "仍在处理", "polling pending", "task pending", "processing",
        )),
        ("quota_exhausted", True, "wait_or_change_provider_quota", (
            "resource has been exhausted", "quota", "rate limit", "too many requests", "配额", "限流",
        )),
        ("authentication", True, "repair_provider_authentication", (
            "auth_unavailable", "unauthorized", "authentication", "invalid api key", "http 401", "http 403", "鉴权", "认证",
        )),
        ("timeout", True, "resume_from_checkpoint", (
            "timeout", "timed out", "deadline exceeded", "超时",
        )),
        ("content_policy", False, "revise_failed_prompt_only", (
            "content policy", "safety", "moderation", "内容政策", "安全审核",
        )),
        ("cancelled", True, "resume_from_checkpoint", (
            "cancelled", "canceled", "已取消", "已停止", "中断",
        )),
    )
    for candidate, candidate_recoverable, candidate_action, markers in patterns:
        if any(marker in normalized for marker in markers):
            category = candidate
            recoverable = candidate_recoverable
            action = candidate_action
            break
    return {
        "category": category,
        "recoverable": recoverable,
        "recommendedAction": action,
        "message": text,
    }


def _coalesced_event_signature(event: str, details: dict[str, Any]) -> str:
    stable_keys = (
        "status",
        "taskPresent",
        "requestId",
        "ownerProjectId",
        "ownerRequestId",
    )
    stable = {key: details.get(key) for key in stable_keys if key in details}
    return canonical_hash({"event": event, "details": stable})


def _character_reference_prompt_risk(prompt: str) -> str | None:
    value = prompt.strip().lower()
    multi_view_terms = (
        "三视图", "四视图", "六视图", "多视图", "多视角", "多角度", "三分之二侧面",
        "正侧背", "转面设定", "turnaround", "model sheet", "character sheet", "reference sheet",
        "拼图", "分栏", "宫格", "多画面", "重复人物",
    )
    for term in multi_view_terms:
        if term in value:
            return f"包含多视角或多画面指令：{term}"
    front_requested = "正面" in value or "front view" in value
    side_or_back_requested = any(term in value for term in ("侧面", "背面", "side view", "back view"))
    if front_requested and side_or_back_requested:
        return "同时要求正面与侧面/背面"
    multi_outfit_terms = (
        "两套服装", "两种服装", "多套服装", "多种服装", "多款服装", "不同服装", "服装对比", "换装",
        "alternate outfit", "multiple outfit", "outfit variant",
    )
    for term in multi_outfit_terms:
        if term in value:
            return f"包含多套服装指令：{term}"
    return None
CODEX_NARRATIVE_FUNCTIONS = {
    "hook",
    "relationship",
    "conflict",
    "setup",
    "emotion_peak",
    "reversal",
    "payoff",
    "transition",
}
CODEX_SHOT_SCALES = {"extreme_wide", "wide", "medium", "close_up", "extreme_close_up"}
CODEX_CAMERA_ANGLES = {"eye_level", "high_angle", "low_angle", "dutch_angle"}
CODEX_CAMERA_VIEWS = {"front", "three_quarter", "profile", "back_view", "over_the_shoulder"}
CODEX_DIALOGUE_STAGING = {
    "action",
    "blocking_change",
    "reaction",
    "evidence_insert",
    "environment",
    "half_body_dialogue",
}
CODEX_SHOT_ROLES = {
    "establishing",
    "action",
    "reaction",
    "emotion_closeup",
    "evidence_insert",
    "consequence",
    "transition",
    "climax",
    "aftermath",
}
CODEX_CRITICAL_EMOTIONS = {
    "none",
    "shock",
    "anger",
    "fear",
    "heartbreak",
    "betrayal",
    "awakening",
    "revenge",
    "face_slap",
    "truth_reveal",
    "life_death_separation",
    "sweet_confirmation",
    "final_reconciliation",
}
CODEX_EMOTION_SIGNALS = {
    "gaze_change",
    "pupil_constriction",
    "mouth_micro_change",
    "tears",
    "clenched_hand",
    "trembling_fingertips",
    "step_back",
    "blocking_or_protective_action",
    "interpersonal_distance",
    "light_color_shift",
}
CODEX_PHYSICAL_EMOTION_SIGNALS = CODEX_EMOTION_SIGNALS - {"light_color_shift"}
CODEX_PROMPT_COMPONENT_FIELDS = (
    "subjectActionZh",
    "visualStoryZh",
    "performanceZh",
    "cameraCompositionZh",
    "continuityEnvironmentZh",
    "lightingColorZh",
    "keyObjectZh",
)
CODEX_MANGA_COMPOSITION_TEXT_FIELDS = (
    "coreMomentZh",
    "singleVisualFocusZh",
    "primaryActionZh",
    "interactionZh",
    "shotDesignZh",
    "backgroundTreatmentZh",
    "continuityEssentialsZh",
    "clutterControlZh",
)
CODEX_FACIAL_ACTING_FIELDS = (
    "eyeShapeZh",
    "pupilZh",
    "browZh",
    "mouthJawZh",
    "faceTensionZh",
    "exaggerationTechniqueZh",
)
CODEX_BODY_ACTING_FIELDS = (
    "lineOfActionZh",
    "centerOfGravityZh",
    "shoulderSpineZh",
    "handTensionZh",
    "secondaryMotionZh",
)
CODEX_MANGA_DEVICES = {
    "speed_lines",
    "impact_burst",
    "extreme_foreshortening",
    "dutch_angle",
    "frame_breaking",
    "heavy_shadow",
    "high_contrast_silhouette",
    "abstract_background",
    "foreground_occlusion",
}
CODEX_BACKGROUND_MODES = {"detailed_context", "selective_detail", "simplified", "abstract_impact"}
CODEX_IMAGE_PROMPT_MAXIMUM = 600
CODEX_IMAGE_PROMPT_SOFT_MINIMUM = 280
CODEX_IMAGE_PROMPT_SOFT_MAXIMUM = 450
CODEX_VIDEO_PROMPT_MAXIMUM = 500
CODEX_IMAGE_PROMPT_MINIMUM_UNIQUE_RATIO = 0.90
CODEX_SEMANTIC_GROUP_DOMINANCE_LIMIT = 0.70
CODEX_SCENE_ROLE_DOMINANCE_LIMIT = 0.65
CODEX_COMPLEXITY_LEVELS = {1, 2, 3, 4, 5}
CODEX_SERIES_PLANNING_MODE = "full_series_then_sequence_then_shot"
CODEX_FAILURE_REPAIR_SCOPE = "failed_scene_only"
CODEX_SEMANTIC_GROUPING_MODE = "semantic_visual_beat_v2"
CODEX_SEMANTIC_GROUP_DECISIONS = {"merged", "intentional_single"}
CODEX_SEMANTIC_GROUP_REASONS = {
    "same_visual_moment",
    "same_action_phase",
    "environmental_support",
    "continuous_dialogue_reaction",
    "short_context_continuation",
    "intentional_single_line_impact",
}
CODEX_SCENE_BOUNDARY_REASONS = {
    "episode_start",
    "important_action_phase_change",
    "focal_subject_change",
    "spatial_change",
    "gaze_emotion_change",
    "key_object_change",
    "causal_result_change",
    "intentional_single_line_impact",
}
CODEX_COMBAT_PHASES = {
    "anticipation",
    "charge",
    "release",
    "contact",
    "impact",
    "defense",
    "reaction",
    "aftermath",
}
CODEX_COMBAT_DIRECTION_FIELDS = (
    "frozenMomentZh",
    "effectSourceZh",
    "trajectoryZh",
    "impactPointZh",
    "effectShapeColorZh",
    "scaleLayeringZh",
    "particlesDebrisZh",
    "environmentalResponseZh",
    "lightingInteractionZh",
    "attackerKineticsZh",
    "defenderResponseZh",
    "safetyBoundaryZh",
)
SOUND_EFFECT_MAX_DURATION_SECONDS = 5.0


def _json_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _subtitles_cover_spoken_lines_in_order(
    normalized_subtitles: str,
    spoken_lines: list[dict[str, Any]],
) -> bool:
    """Require every spoken line in order while allowing interleaved SFX cues."""

    cursor = 0
    found_spoken_text = False
    for line in spoken_lines:
        normalized_line = re.sub(r"\s+", "", str(line.get("text") or ""))
        if not normalized_line:
            continue
        found_spoken_text = True
        position = normalized_subtitles.find(normalized_line, cursor)
        if position < 0:
            return False
        cursor = position + len(normalized_line)
    return found_spoken_text


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _atomic_bytes(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except Exception:
        Path(temporary).unlink(missing_ok=True)
        raise


def _atomic_json(path: Path, value: Any) -> None:
    _atomic_bytes(path, _json_bytes(value))


def _non_empty_text(value: Any, field: str, *, maximum: int = 2000) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ToolError("PRODUCTION_CODEX_VISUAL_PLAN_INVALID", f"{field} 不能为空。")
    normalized = value.strip()
    if len(normalized) > maximum:
        raise ToolError("PRODUCTION_CODEX_VISUAL_PLAN_INVALID", f"{field} 过长。")
    if not re.search(r"(?:^|\.)(?:characterId|groupId|sequenceId|sceneId|beatId|entryStateId|exitStateId)$", field):
        placeholder_risk = _visual_placeholder_risk(normalized)
        if placeholder_risk:
            raise ToolError(
                "PRODUCTION_CODEX_VISUAL_PLAN_INVALID",
                f"{field} 含有占位内容“{placeholder_risk}”，必须填写与本项目剧情直接相关的具体信息。",
            )
    return normalized


def _visual_placeholder_risk(value: str) -> str | None:
    normalized = re.sub(r"[\s`'\"“”‘’。，、；;：:（）()\[\]【】/|_-]+", "", value).lower()
    if normalized in {"x", "y", "z", "xy", "xyz", "tbd", "todo", "na", "null", "none", "待补", "待定", "占位"}:
        return value.strip()
    for token in ("placeholder", "占位符", "待补充", "待填写", "稍后补充", "todo:", "tbd:"):
        if token in value.lower():
            return token
    if normalized and set(normalized) <= {"x", "y", "z"}:
        return value.strip()
    return None


def _image_prompt_temporal_sequence_risk(prompt: str) -> str | None:
    value = re.sub(r"\s+", "", prompt)
    for term in ("随后", "接着", "然后", "之后又", "紧接着"):
        if term in value:
            return f"包含时间序列连接词“{term}”"
    if re.search(r"先.{0,48}(?:再|然后|接着)", value):
        return "同时描述了动作起点、过程或结果"
    return None


def _generic_scene_language_risk(*values: str) -> str | None:
    combined = "\n".join(values)
    for phrase in (
        "身体重心稳定并与动作一致",
        "视线落在互动对象或关键物件",
        "改变景别以避免重复",
        "当前人物或物件",
        "当前人物或关键物件",
        "当前剧情对应",
        "与当前正式稿对应",
        "眼神、眉形、嘴形和手势明确",
        "背景适度简化",
    ):
        if phrase in combined:
            return phrase
    return None


def _validate_sound_effect_scene_bindings(
    target_lines: list[dict[str, Any]],
    scene_id_by_line_id: dict[str, str],
) -> None:
    lines_by_episode: dict[int, list[dict[str, Any]]] = {}
    for line in target_lines:
        episode_number = line.get("episodeNumber")
        if isinstance(episode_number, int) and not isinstance(episode_number, bool):
            lines_by_episode.setdefault(episode_number, []).append(line)
    for episode_number, episode_lines in lines_by_episode.items():
        for index, line in enumerate(episode_lines):
            if line.get("lineType") != "sound_effect":
                continue
            trigger_index = index - 1 if index > 0 else 1
            if trigger_index >= len(episode_lines):
                raise ToolError(
                    "PRODUCTION_CODEX_VISUAL_PLAN_INVALID",
                    "音效行必须和触发它的旁白或对白共用同一分镜。",
                    details={"episodeNumber": episode_number, "lineId": line.get("lineId")},
                )
            line_id = str(line.get("lineId") or "")
            trigger_line_id = str(episode_lines[trigger_index].get("lineId") or "")
            if (
                not scene_id_by_line_id.get(line_id)
                or scene_id_by_line_id.get(line_id) != scene_id_by_line_id.get(trigger_line_id)
            ):
                raise ToolError(
                    "PRODUCTION_CODEX_VISUAL_PLAN_INVALID",
                    "音效行必须和触发它的旁白或对白共用同一分镜，禁止音画错位。",
                    details={
                        "episodeNumber": episode_number,
                        "lineId": line_id,
                        "triggerLineId": trigger_line_id,
                        "soundSceneId": scene_id_by_line_id.get(line_id),
                        "triggerSceneId": scene_id_by_line_id.get(trigger_line_id),
                    },
                )


def _normalize_codex_visual_plan(
    value: Any,
    *,
    manuscript: dict[str, Any],
    production_config: dict[str, Any],
    synthetic: bool,
) -> dict[str, Any] | None:
    prompt_generation = production_config["promptGeneration"]
    production_mode = production_config.get("productionMode", {})
    production_mode_id = str(production_mode.get("id") or "director")
    requires_scene_plan = production_mode_id == "director" and bool(prompt_generation["image"] or prompt_generation["video"])
    if value is None:
        if requires_scene_plan and not synthetic:
            raise ToolError(
                "PRODUCTION_CODEX_VISUAL_PLAN_REQUIRED",
                "已选择由 Codex 生成图片或视频提示词，但生产配置缺少 Codex 视觉方案。",
            )
        return None
    if production_mode_id != "director" and not synthetic:
        raise ToolError(
            "PRODUCTION_MODE_VISUAL_PLAN_CONFLICT",
            "极速自动模式和平衡模式禁止生成完整 Codex 视觉方案；只有精品导演模式使用 codexVisualPlan。",
            details={"productionMode": production_mode_id},
        )
    if not isinstance(value, dict):
        raise ToolError("PRODUCTION_CODEX_VISUAL_PLAN_INVALID", "codexVisualPlan 必须是对象。")
    if value.get("schemaVersion") != CODEX_VISUAL_PLAN_SCHEMA_VERSION or value.get("author") != CODEX_VISUAL_PLAN_AUTHOR:
        raise ToolError(
            "PRODUCTION_CODEX_VISUAL_PLAN_INVALID",
            f"codexVisualPlan 必须声明 schemaVersion={CODEX_VISUAL_PLAN_SCHEMA_VERSION}、author=codex。",
        )
    visual_direction = value.get("visualDirection")
    if not isinstance(visual_direction, dict) or any(
        visual_direction.get(field) != expected
        for field, expected in CODEX_VISUAL_DIRECTION.items()
    ):
        raise ToolError(
            "PRODUCTION_CODEX_VISUAL_PLAN_INVALID",
            "visualDirection 必须使用单幅、单焦点、剧情驱动的 manga_impact 导演合同。",
        )

    characters = manuscript.get("characters", [])
    character_by_id = {
        item.get("characterId"): item
        for item in characters
        if isinstance(item, dict) and isinstance(item.get("characterId"), str)
    }
    appearance_by_character_id = {
        character_id: _character_appearance_contract(item)
        for character_id, item in character_by_id.items()
    }
    appearance_owners: dict[str, str] = {}
    for character_id, appearance in appearance_by_character_id.items():
        appearance_id = appearance["appearanceId"]
        if not all(appearance.values()) or appearance_id in appearance_owners:
            raise ToolError(
                "PRODUCTION_CODEX_VISUAL_PLAN_INVALID",
                "每个角色外观阶段必须有非空 personId、appearanceId、lifePhase、ageStage、referencePolicy，且 appearanceId 全局唯一。",
                details={"characterId": character_id, "appearanceId": appearance_id, "owner": appearance_owners.get(appearance_id)},
            )
        appearance_owners[appearance_id] = character_id
        visual_required = character_by_id[character_id].get("visualConsistencyRequired") is True
        if (appearance["referencePolicy"] == "required") != visual_required or (appearance["referencePolicy"] == "none" and visual_required):
            raise ToolError(
                "PRODUCTION_CODEX_VISUAL_PLAN_INVALID",
                "referencePolicy 与 visualConsistencyRequired 冲突；required 必须生成阶段专用参考图，none 必须直接按文字生图。",
                details={"characterId": character_id, "referencePolicy": appearance["referencePolicy"]},
            )
    required_visual_ids = {
        character_id
        for character_id, item in character_by_id.items()
        if item.get("visualConsistencyRequired") is True
    }
    normalized_designs: list[dict[str, Any]] = []
    seen_design_ids: set[str] = set()
    for index, item in enumerate(value.get("characterDesigns", []), start=1):
        if not isinstance(item, dict):
            raise ToolError("PRODUCTION_CODEX_VISUAL_PLAN_INVALID", f"characterDesigns[{index}] 必须是对象。")
        character_id = item.get("characterId")
        if character_id not in character_by_id or character_id in seen_design_ids:
            raise ToolError("PRODUCTION_CODEX_VISUAL_PLAN_INVALID", f"characterDesigns[{index}].characterId 无效或重复。")
        seen_design_ids.add(character_id)
        appearance = appearance_by_character_id[character_id]
        for field in ("personId", "appearanceId", "lifePhase", "ageStage", "referencePolicy"):
            if str(item.get(field) or "").strip() != appearance[field]:
                raise ToolError(
                    "PRODUCTION_CODEX_VISUAL_PLAN_INVALID",
                    f"characterDesigns[{index}].{field} 与角色外观阶段不一致。",
                    details={"characterId": character_id, "expected": appearance[field]},
                )
        fixed_features = item.get("fixedFeatures")
        if not isinstance(fixed_features, list) or not 3 <= len(fixed_features) <= 12:
            raise ToolError(
                "PRODUCTION_CODEX_VISUAL_PLAN_INVALID",
                f"characterDesigns[{index}].fixedFeatures 必须包含 3–12 个身份固定特征。",
            )
        fixed_features = [_non_empty_text(entry, f"characterDesigns[{index}].fixedFeatures", maximum=180) for entry in fixed_features]
        reference_sheet_prompt = str(item.get("referenceSheetPromptZh") or "").strip()
        if appearance["referencePolicy"] != "none":
            reference_sheet_prompt = _non_empty_text(reference_sheet_prompt, f"characterDesigns[{index}].referenceSheetPromptZh")
            reference_risk = _character_reference_prompt_risk(reference_sheet_prompt)
            if reference_risk:
                raise ToolError(
                    "PRODUCTION_CODEX_VISUAL_PLAN_INVALID",
                    f"characterDesigns[{index}].referenceSheetPromptZh 必须是单画布、单角色、单视角、单套主服装：{reference_risk}。",
                    details={"characterId": character_id, "risk": reference_risk},
                )
        elif reference_sheet_prompt:
            raise ToolError(
                "PRODUCTION_CODEX_VISUAL_PLAN_INVALID",
                f"characterDesigns[{index}] 的 referencePolicy=none，不得生成或绑定角色参考图提示词。",
            )
        normalized_designs.append(
            {
                "characterId": character_id,
                **appearance,
                "designIntentZh": _non_empty_text(item.get("designIntentZh"), f"characterDesigns[{index}].designIntentZh"),
                "identityAnchorPromptZh": _non_empty_text(item.get("identityAnchorPromptZh"), f"characterDesigns[{index}].identityAnchorPromptZh"),
                "referenceSheetPromptZh": reference_sheet_prompt,
                "storyboardIdentityPromptZh": _non_empty_text(item.get("storyboardIdentityPromptZh"), f"characterDesigns[{index}].storyboardIdentityPromptZh"),
                "fixedFeatures": fixed_features,
                "referenceUsage": CODEX_REFERENCE_USAGE if appearance["referencePolicy"] != "none" else "none",
                "flexibleFeatures": list(CODEX_REFERENCE_FLEXIBLE_FEATURES),
            }
        )
    if required_visual_ids - seen_design_ids:
        raise ToolError(
            "PRODUCTION_CODEX_VISUAL_PLAN_INVALID",
            "Codex 角色设计没有覆盖全部需要视觉一致性的角色。",
            details={"missingCharacterIds": sorted(required_visual_ids - seen_design_ids)},
        )

    continuity_bible = value.get("continuityBible")
    if not isinstance(continuity_bible, dict):
        raise ToolError("PRODUCTION_CODEX_VISUAL_PLAN_INVALID", "continuityBible 缺失。")

    def normalize_continuity_entries(field: str, id_field: str, *, required: bool = False) -> tuple[list[dict[str, Any]], set[str]]:
        entries = continuity_bible.get(field)
        if not isinstance(entries, list) or (required and not entries):
            raise ToolError("PRODUCTION_CODEX_VISUAL_PLAN_INVALID", f"continuityBible.{field} 必须是非空数组。")
        normalized_entries: list[dict[str, Any]] = []
        seen_ids: set[str] = set()
        for entry_index, entry in enumerate(entries, start=1):
            if not isinstance(entry, dict):
                raise ToolError("PRODUCTION_CODEX_VISUAL_PLAN_INVALID", f"continuityBible.{field}[{entry_index}] 必须是对象。")
            entry_id = _non_empty_text(entry.get(id_field), f"continuityBible.{field}[{entry_index}].{id_field}", maximum=120)
            if entry_id in seen_ids:
                raise ToolError("PRODUCTION_CODEX_VISUAL_PLAN_INVALID", f"continuityBible.{field}.{id_field} 重复。")
            seen_ids.add(entry_id)
            fixed_features = entry.get("fixedFeatures")
            if not isinstance(fixed_features, list) or not fixed_features:
                raise ToolError("PRODUCTION_CODEX_VISUAL_PLAN_INVALID", f"continuityBible.{field}[{entry_index}].fixedFeatures 不能为空。")
            normalized_entry = {
                id_field: entry_id,
                "nameZh": _non_empty_text(entry.get("nameZh"), f"continuityBible.{field}[{entry_index}].nameZh", maximum=120),
                "fixedFeatures": [
                    _non_empty_text(feature, f"continuityBible.{field}[{entry_index}].fixedFeatures", maximum=180)
                    for feature in fixed_features
                ],
            }
            if field == "costumes":
                character_id = entry.get("characterId")
                if character_id not in character_by_id:
                    raise ToolError("PRODUCTION_CODEX_VISUAL_PLAN_INVALID", f"continuityBible.costumes[{entry_index}].characterId 无效。")
                normalized_entry["characterId"] = character_id
            normalized_entries.append(normalized_entry)
        return normalized_entries, seen_ids

    locations, location_ids = normalize_continuity_entries("locations", "locationId", required=True)
    costumes, costume_ids = normalize_continuity_entries("costumes", "costumeId")
    props, prop_ids = normalize_continuity_entries("props", "propId")
    costume_character_by_id = {entry["costumeId"]: entry["characterId"] for entry in costumes}
    costume_features_by_id = {entry["costumeId"]: entry["fixedFeatures"] for entry in costumes}

    target_lines = manuscript.get("targetScript", {}).get("lines", [])
    line_by_id = {
        item.get("lineId"): item
        for item in target_lines
        if isinstance(item, dict) and isinstance(item.get("lineId"), str)
    }
    expected_line_ids = [item.get("lineId") for item in target_lines]
    expected_episode_numbers = list(dict.fromkeys(
        item.get("episodeNumber")
        for item in target_lines
        if isinstance(item.get("episodeNumber"), int) and not isinstance(item.get("episodeNumber"), bool)
    ))
    series_visual_plan = value.get("seriesVisualPlan")
    if not isinstance(series_visual_plan, dict):
        raise ToolError("PRODUCTION_CODEX_VISUAL_PLAN_INVALID", "seriesVisualPlan 缺失，必须先读取全剧再规划连续场景。")
    series_episode_numbers = series_visual_plan.get("episodeNumbers")
    if (
        series_visual_plan.get("planningMode") != CODEX_SERIES_PLANNING_MODE
        or series_visual_plan.get("allEpisodesRead") is not True
        or series_episode_numbers != expected_episode_numbers
    ):
        raise ToolError(
            "PRODUCTION_CODEX_VISUAL_PLAN_INVALID",
            "seriesVisualPlan 必须按全剧→连续场景→单镜顺序规划，并完整声明全部正式稿集数。",
        )
    normalized_series_visual_plan = {
        "planningMode": CODEX_SERIES_PLANNING_MODE,
        "allEpisodesRead": True,
        "episodeNumbers": expected_episode_numbers,
        "timelineSummaryZh": _non_empty_text(series_visual_plan.get("timelineSummaryZh"), "seriesVisualPlan.timelineSummaryZh", maximum=800),
        "crossEpisodeContinuityZh": _non_empty_text(series_visual_plan.get("crossEpisodeContinuityZh"), "seriesVisualPlan.crossEpisodeContinuityZh", maximum=800),
    }
    story_visual_plan = value.get("storyVisualPlan")
    if not isinstance(story_visual_plan, dict):
        raise ToolError("PRODUCTION_CODEX_VISUAL_PLAN_INVALID", "storyVisualPlan 缺失。")
    semantic_grouping = story_visual_plan.get("semanticGrouping")
    if (
        not isinstance(semantic_grouping, dict)
        or semantic_grouping.get("mode") != CODEX_SEMANTIC_GROUPING_MODE
        or semantic_grouping.get("ttsLineBreakCreatesScene") is not False
        or semantic_grouping.get("durationCreatesScene") is not False
        or semantic_grouping.get("mergeBeforeContinuityPlanning") is not True
        or semantic_grouping.get("lineCountHardCap") is not False
        or semantic_grouping.get("actionPhaseChangeCreatesScene") is not False
        or semantic_grouping.get("splitOnlyForImportantVisibleChange") is not True
    ):
        raise ToolError(
            "PRODUCTION_CODEX_VISUAL_PLAN_INVALID",
            "storyVisualPlan.semanticGrouping 必须先按视觉时刻合并相邻短行，再做连续性与分镜；拆行、时长和行数上限均不得直接制造画面。",
        )
    combat_selection_policy = story_visual_plan.get("combatSelectionPolicy")
    if (
        not isinstance(combat_selection_policy, dict)
        or combat_selection_policy.get("mode") != "key_moments_only"
        or combat_selection_policy.get("allPhasesRequired") is not False
        or combat_selection_policy.get("phaseChangeCreatesScene") is not False
        or combat_selection_policy.get("intermediatePhasesMayBeOmitted") is not True
    ):
        raise ToolError(
            "PRODUCTION_CODEX_VISUAL_PLAN_INVALID",
            "storyVisualPlan.combatSelectionPolicy 必须只选择承担剧情重点的战斗瞬间，不得为覆盖全部动作阶段而加镜。",
        )
    semantic_beat_groups = story_visual_plan.get("semanticBeatGroups")
    if not isinstance(semantic_beat_groups, list) or not semantic_beat_groups:
        raise ToolError("PRODUCTION_CODEX_VISUAL_PLAN_INVALID", "storyVisualPlan.semanticBeatGroups 不能为空。")
    normalized_semantic_groups: list[dict[str, Any]] = []
    semantic_group_by_id: dict[str, dict[str, Any]] = {}
    semantic_group_line_ids: list[str] = []
    previous_episode_number: int | None = None
    for group_index, group in enumerate(semantic_beat_groups, start=1):
        if not isinstance(group, dict):
            raise ToolError("PRODUCTION_CODEX_VISUAL_PLAN_INVALID", f"semanticBeatGroups[{group_index}] 必须是对象。")
        group_id = _non_empty_text(group.get("groupId"), f"semanticBeatGroups[{group_index}].groupId", maximum=160)
        if group_id in semantic_group_by_id:
            raise ToolError("PRODUCTION_CODEX_VISUAL_PLAN_INVALID", f"semanticBeatGroups[{group_index}].groupId 重复。")
        group_line_ids = group.get("sourceLineIds")
        if (
            not isinstance(group_line_ids, list)
            or not group_line_ids
            or any(line_id not in line_by_id for line_id in group_line_ids)
            or len(set(group_line_ids)) != len(group_line_ids)
        ):
            raise ToolError("PRODUCTION_CODEX_VISUAL_PLAN_INVALID", f"semanticBeatGroups[{group_index}].sourceLineIds 无效。")
        episode_numbers = {line_by_id[line_id].get("episodeNumber") for line_id in group_line_ids}
        episode_number = group.get("episodeNumber")
        if episode_numbers != {episode_number}:
            raise ToolError("PRODUCTION_CODEX_VISUAL_PLAN_INVALID", f"semanticBeatGroups[{group_index}] 不能跨集或错绑集数。")
        decision = group.get("decision")
        expected_decision = "merged" if len(group_line_ids) > 1 else "intentional_single"
        if decision not in CODEX_SEMANTIC_GROUP_DECISIONS or decision != expected_decision:
            raise ToolError(
                "PRODUCTION_CODEX_VISUAL_PLAN_INVALID",
                f"semanticBeatGroups[{group_index}].decision 必须反映实际合并结果。",
            )
        reason = group.get("reason")
        if reason not in CODEX_SEMANTIC_GROUP_REASONS:
            raise ToolError("PRODUCTION_CODEX_VISUAL_PLAN_INVALID", f"semanticBeatGroups[{group_index}].reason 无效。")
        if decision == "intentional_single" and reason != "intentional_single_line_impact":
            raise ToolError(
                "PRODUCTION_CODEX_VISUAL_PLAN_INVALID",
                f"semanticBeatGroups[{group_index}] 单行独立成镜必须说明它本身就是不可合并的决定性画面。",
            )
        if decision == "merged" and reason == "intentional_single_line_impact":
            raise ToolError("PRODUCTION_CODEX_VISUAL_PLAN_INVALID", f"semanticBeatGroups[{group_index}] 合并组不能使用单行理由。")
        boundary_reason = group.get("boundaryFromPrevious")
        is_episode_start = episode_number != previous_episode_number
        if boundary_reason not in CODEX_SCENE_BOUNDARY_REASONS or (boundary_reason == "episode_start") != is_episode_start:
            raise ToolError(
                "PRODUCTION_CODEX_VISUAL_PLAN_INVALID",
                f"semanticBeatGroups[{group_index}].boundaryFromPrevious 必须对应真实的可见边界，不能由换行制造。",
            )
        normalized_group = {
            "groupId": group_id,
            "episodeNumber": episode_number,
            "sourceLineIds": list(group_line_ids),
            "visualMomentZh": _non_empty_text(group.get("visualMomentZh"), f"semanticBeatGroups[{group_index}].visualMomentZh", maximum=360),
            "decision": decision,
            "reason": reason,
            "decisionReasonZh": _non_empty_text(group.get("decisionReasonZh"), f"semanticBeatGroups[{group_index}].decisionReasonZh", maximum=360),
            "boundaryFromPrevious": boundary_reason,
        }
        normalized_semantic_groups.append(normalized_group)
        semantic_group_by_id[group_id] = normalized_group
        semantic_group_line_ids.extend(group_line_ids)
        previous_episode_number = episode_number
    if semantic_group_line_ids != expected_line_ids:
        raise ToolError(
            "PRODUCTION_CODEX_VISUAL_PLAN_INVALID",
            "semanticBeatGroups 必须按正式稿顺序完整且仅覆盖每一行一次。",
            details={"expectedLineIds": expected_line_ids, "actualLineIds": semantic_group_line_ids},
        )
    normalized_scenes: list[dict[str, Any]] = []
    covered_line_ids: list[str] = []
    seen_scene_ids: set[str] = set()
    used_semantic_group_ids: list[str] = []
    scene_by_id: dict[str, dict[str, Any]] = {}
    for index, item in enumerate(value.get("scenePlans", []), start=1):
        if not isinstance(item, dict):
            raise ToolError("PRODUCTION_CODEX_VISUAL_PLAN_INVALID", f"scenePlans[{index}] 必须是对象。")
        scene_id = _non_empty_text(item.get("sceneId"), f"scenePlans[{index}].sceneId", maximum=160)
        if scene_id in seen_scene_ids:
            raise ToolError("PRODUCTION_CODEX_VISUAL_PLAN_INVALID", f"scenePlans[{index}].sceneId 重复。")
        seen_scene_ids.add(scene_id)
        line_ids = item.get("scriptLineIds")
        if not isinstance(line_ids, list) or not line_ids:
            raise ToolError("PRODUCTION_CODEX_VISUAL_PLAN_INVALID", f"scenePlans[{index}].scriptLineIds 必须包含至少一行。")
        if any(line_id not in line_by_id for line_id in line_ids) or len(set(line_ids)) != len(line_ids):
            raise ToolError("PRODUCTION_CODEX_VISUAL_PLAN_INVALID", f"scenePlans[{index}] 引用了无效或重复的正式稿行。")
        if not any(line_by_id[line_id].get("lineType") in {"narration", "dialogue"} for line_id in line_ids):
            raise ToolError(
                "PRODUCTION_CODEX_VISUAL_PLAN_INVALID",
                f"scenePlans[{index}] 不能由纯音效单独形成画面，必须与相邻旁白或对白共用分镜。",
            )
        episode_numbers = {line_by_id[line_id].get("episodeNumber") for line_id in line_ids}
        if episode_numbers != {item.get("episodeNumber")}:
            raise ToolError("PRODUCTION_CODEX_VISUAL_PLAN_INVALID", f"scenePlans[{index}] 不能跨集或错绑集数。")
        semantic_group_id = _non_empty_text(item.get("semanticGroupId"), f"scenePlans[{index}].semanticGroupId", maximum=160)
        semantic_group = semantic_group_by_id.get(semantic_group_id)
        if semantic_group is None or semantic_group_id in used_semantic_group_ids:
            raise ToolError("PRODUCTION_CODEX_VISUAL_PLAN_INVALID", f"scenePlans[{index}].semanticGroupId 无效或重复。")
        if semantic_group["sourceLineIds"] != line_ids or semantic_group["episodeNumber"] != item.get("episodeNumber"):
            raise ToolError("PRODUCTION_CODEX_VISUAL_PLAN_INVALID", f"scenePlans[{index}] 与语义画面组绑定不一致。")
        used_semantic_group_ids.append(semantic_group_id)
        sequence_id = _non_empty_text(item.get("sequenceId"), f"scenePlans[{index}].sequenceId", maximum=160)
        shot_role = item.get("shotRole")
        if shot_role not in CODEX_SHOT_ROLES:
            raise ToolError("PRODUCTION_CODEX_VISUAL_PLAN_INVALID", f"scenePlans[{index}].shotRole 无效。")
        visible_ids = item.get("visibleCharacterIds", [])
        if not isinstance(visible_ids, list) or any(character_id not in character_by_id for character_id in visible_ids):
            raise ToolError("PRODUCTION_CODEX_VISUAL_PLAN_INVALID", f"scenePlans[{index}].visibleCharacterIds 无效。")
        visible_ids = list(dict.fromkeys(visible_ids))
        if any(character_id not in seen_design_ids for character_id in visible_ids):
            raise ToolError(
                "PRODUCTION_CODEX_VISUAL_PLAN_INVALID",
                f"scenePlans[{index}] 的每个出镜外观阶段都必须有 characterDesign；referencePolicy=none 也要有文字身份锚点。",
            )
        raw_appearance_bindings = item.get("appearanceBindings")
        if not isinstance(raw_appearance_bindings, list) or len(raw_appearance_bindings) != len(visible_ids):
            raise ToolError("PRODUCTION_CODEX_VISUAL_PLAN_INVALID", f"scenePlans[{index}].appearanceBindings 必须与出镜角色逐一对应。")
        normalized_appearance_bindings: list[dict[str, str]] = []
        bound_character_ids: set[str] = set()
        for binding_index, binding in enumerate(raw_appearance_bindings, start=1):
            if not isinstance(binding, dict):
                raise ToolError("PRODUCTION_CODEX_VISUAL_PLAN_INVALID", f"scenePlans[{index}].appearanceBindings[{binding_index}] 必须是对象。")
            character_id = str(binding.get("characterId") or "").strip()
            expected = appearance_by_character_id.get(character_id)
            if character_id not in visible_ids or character_id in bound_character_ids or expected is None:
                raise ToolError("PRODUCTION_CODEX_VISUAL_PLAN_INVALID", f"scenePlans[{index}].appearanceBindings[{binding_index}] 角色无效或重复。")
            if any(str(binding.get(field) or "").strip() != expected[field] for field in ("personId", "appearanceId", "lifePhase", "ageStage", "referencePolicy")):
                raise ToolError(
                    "PRODUCTION_CODEX_VISUAL_PLAN_INVALID",
                    f"scenePlans[{index}] 外观阶段绑定与角色合同不一致，禁止跨年龄或跨人生阶段复用参考图。",
                    details={"characterId": character_id, "expected": expected},
                )
            normalized_appearance_bindings.append({"characterId": character_id, **expected})
            bound_character_ids.add(character_id)
        if visible_ids and item.get("primaryCharacterId") not in visible_ids:
            raise ToolError(
                "PRODUCTION_CODEX_VISUAL_PLAN_INVALID",
                f"scenePlans[{index}].primaryCharacterId 必须指定本镜唯一主要角色。",
            )
        performance = item.get("performance")
        if not isinstance(performance, dict):
            raise ToolError("PRODUCTION_CODEX_VISUAL_PLAN_INVALID", f"scenePlans[{index}].performance 缺失。")
        normalized_performance: dict[str, Any] = {}
        for field in CODEX_PERFORMANCE_FIELDS:
            if field == "intensity":
                intensity = performance.get(field)
                if not isinstance(intensity, int) or isinstance(intensity, bool) or not 1 <= intensity <= 5:
                    raise ToolError("PRODUCTION_CODEX_VISUAL_PLAN_INVALID", f"scenePlans[{index}].performance.intensity 必须为 1–5。")
                normalized_performance[field] = intensity
            else:
                normalized_performance[field] = _non_empty_text(
                    performance.get(field), f"scenePlans[{index}].performance.{field}", maximum=260
                )
        generic_performance_risk = _generic_scene_language_risk(
            *[str(normalized_performance[field]) for field in CODEX_PERFORMANCE_FIELDS if field != "intensity"]
        )
        if generic_performance_risk:
            raise ToolError(
                "PRODUCTION_CODEX_VISUAL_PLAN_INVALID",
                f"scenePlans[{index}].performance 使用了不可复用的通用套话：{generic_performance_risk}。",
            )

        impact_level = item.get("impactLevel")
        if not isinstance(impact_level, int) or isinstance(impact_level, bool) or not 1 <= impact_level <= 5:
            raise ToolError("PRODUCTION_CODEX_VISUAL_PLAN_INVALID", f"scenePlans[{index}].impactLevel 必须为 1–5。")
        expression_exaggeration = item.get("expressionExaggeration")
        if not isinstance(expression_exaggeration, int) or isinstance(expression_exaggeration, bool) or not 1 <= expression_exaggeration <= 5:
            raise ToolError("PRODUCTION_CODEX_VISUAL_PLAN_INVALID", f"scenePlans[{index}].expressionExaggeration 必须为 1–5。")

        manga_composition = item.get("mangaComposition")
        if not isinstance(manga_composition, dict):
            raise ToolError("PRODUCTION_CODEX_VISUAL_PLAN_INVALID", f"scenePlans[{index}].mangaComposition 缺失。")
        normalized_manga_composition = {
            field: _non_empty_text(
                manga_composition.get(field), f"scenePlans[{index}].mangaComposition.{field}", maximum=260
            )
            for field in CODEX_MANGA_COMPOSITION_TEXT_FIELDS
        }
        background_mode = manga_composition.get("backgroundMode")
        if background_mode not in CODEX_BACKGROUND_MODES:
            raise ToolError("PRODUCTION_CODEX_VISUAL_PLAN_INVALID", f"scenePlans[{index}].mangaComposition.backgroundMode 无效。")
        manga_devices = manga_composition.get("mangaDevices")
        if (
            not isinstance(manga_devices, list)
            or len(manga_devices) > CODEX_VISUAL_DIRECTION["mangaDeviceLimit"]
            or any(device not in CODEX_MANGA_DEVICES for device in manga_devices)
        ):
            raise ToolError(
                "PRODUCTION_CODEX_VISUAL_PLAN_INVALID",
                f"scenePlans[{index}].mangaComposition.mangaDevices 最多使用三个受支持的漫画冲击手法。",
            )
        normalized_manga_composition["backgroundMode"] = background_mode
        normalized_manga_composition["mangaDevices"] = list(dict.fromkeys(manga_devices))

        facial_acting = item.get("facialActing")
        body_acting = item.get("bodyActing")
        if visible_ids:
            if not isinstance(facial_acting, dict) or not isinstance(body_acting, dict):
                raise ToolError(
                    "PRODUCTION_CODEX_VISUAL_PLAN_INVALID",
                    f"scenePlans[{index}] 有角色出镜时必须提供 facialActing 与 bodyActing。",
                )
            normalized_facial_acting = {
                field: _non_empty_text(facial_acting.get(field), f"scenePlans[{index}].facialActing.{field}", maximum=220)
                for field in CODEX_FACIAL_ACTING_FIELDS
            }
            normalized_body_acting = {
                field: _non_empty_text(body_acting.get(field), f"scenePlans[{index}].bodyActing.{field}", maximum=220)
                for field in CODEX_BODY_ACTING_FIELDS
            }
        else:
            if expression_exaggeration != 1:
                raise ToolError(
                    "PRODUCTION_CODEX_VISUAL_PLAN_INVALID",
                    f"scenePlans[{index}] 无人镜头的 expressionExaggeration 必须为 1。",
                )
            normalized_facial_acting = {}
            normalized_body_acting = {}

        complexity_score = item.get("complexityScore")
        if not isinstance(complexity_score, int) or isinstance(complexity_score, bool) or not 1 <= complexity_score <= 5:
            raise ToolError("PRODUCTION_CODEX_VISUAL_PLAN_INVALID", f"scenePlans[{index}].complexityScore 必须为 1–5。")
        narrative_function = item.get("narrativeFunction")
        if narrative_function not in CODEX_NARRATIVE_FUNCTIONS:
            raise ToolError("PRODUCTION_CODEX_VISUAL_PLAN_INVALID", f"scenePlans[{index}].narrativeFunction 无效。")
        beat_ids = item.get("storyBeatIds")
        if not isinstance(beat_ids, list) or not beat_ids or any(not isinstance(beat_id, str) or not beat_id.strip() for beat_id in beat_ids):
            raise ToolError("PRODUCTION_CODEX_VISUAL_PLAN_INVALID", f"scenePlans[{index}].storyBeatIds 不能为空。")

        shot = item.get("shot")
        if not isinstance(shot, dict) or shot.get("scale") not in CODEX_SHOT_SCALES or shot.get("angle") not in CODEX_CAMERA_ANGLES or shot.get("view") not in CODEX_CAMERA_VIEWS or shot.get("dialogueStaging") not in CODEX_DIALOGUE_STAGING:
            raise ToolError("PRODUCTION_CODEX_VISUAL_PLAN_INVALID", f"scenePlans[{index}].shot 镜头字段无效。")
        breaking_composition = shot.get("breakingComposition") is True
        normalized_shot = {
            "scale": shot["scale"],
            "angle": shot["angle"],
            "view": shot["view"],
            "dialogueStaging": shot["dialogueStaging"],
            "breakingComposition": breaking_composition,
            "breakingCompositionZh": _non_empty_text(shot.get("breakingCompositionZh"), f"scenePlans[{index}].shot.breakingCompositionZh", maximum=220),
            "focalPointZh": _non_empty_text(shot.get("focalPointZh"), f"scenePlans[{index}].shot.focalPointZh", maximum=180),
            "depthCompositionZh": _non_empty_text(shot.get("depthCompositionZh"), f"scenePlans[{index}].shot.depthCompositionZh", maximum=220),
            "posterCompositionZh": _non_empty_text(shot.get("posterCompositionZh"), f"scenePlans[{index}].shot.posterCompositionZh", maximum=220),
        }
        if impact_level >= 4:
            if shot["scale"] not in {"close_up", "extreme_close_up"} and not breaking_composition:
                raise ToolError(
                    "PRODUCTION_CODEX_VISUAL_PLAN_INVALID",
                    f"scenePlans[{index}] 高冲击镜头必须使用近景／极近特写或破格构图。",
                )
            if not normalized_manga_composition["mangaDevices"]:
                raise ToolError(
                    "PRODUCTION_CODEX_VISUAL_PLAN_INVALID",
                    f"scenePlans[{index}] 高冲击镜头至少需要一种漫画冲击手法。",
                )
            if normalized_manga_composition["backgroundMode"] not in {"simplified", "abstract_impact"}:
                raise ToolError(
                    "PRODUCTION_CODEX_VISUAL_PLAN_INVALID",
                    f"scenePlans[{index}] 高冲击镜头必须简化或抽象化背景。",
                )
            if visible_ids and expression_exaggeration < 4:
                raise ToolError(
                    "PRODUCTION_CODEX_VISUAL_PLAN_INVALID",
                    f"scenePlans[{index}] 高冲击人物镜头的表情夸张度不得低于 4。",
                )

        readability = item.get("visualReadability")
        if not isinstance(readability, dict) or readability.get("withoutDialogueReadable") is not True:
            raise ToolError("PRODUCTION_CODEX_VISUAL_PLAN_INVALID", f"scenePlans[{index}].visualReadability 必须保证脱离文字仍可理解。")
        normalized_readability = {
            "storyInformationZh": _non_empty_text(readability.get("storyInformationZh"), f"scenePlans[{index}].visualReadability.storyInformationZh", maximum=240),
            "relationshipCueZh": _non_empty_text(readability.get("relationshipCueZh"), f"scenePlans[{index}].visualReadability.relationshipCueZh", maximum=240),
            "conflictOrCauseEffectCueZh": _non_empty_text(readability.get("conflictOrCauseEffectCueZh"), f"scenePlans[{index}].visualReadability.conflictOrCauseEffectCueZh", maximum=240),
            "withoutDialogueReadable": True,
        }

        continuity = item.get("continuity")
        if not isinstance(continuity, dict) or continuity.get("locationId") not in location_ids:
            raise ToolError("PRODUCTION_CODEX_VISUAL_PLAN_INVALID", f"scenePlans[{index}].continuity.locationId 无效。")
        costume_bindings = continuity.get("costumeIdsByCharacter")
        if not isinstance(costume_bindings, dict):
            raise ToolError("PRODUCTION_CODEX_VISUAL_PLAN_INVALID", f"scenePlans[{index}].continuity.costumeIdsByCharacter 必须是对象。")
        for character_id in visible_ids:
            costume_id = costume_bindings.get(character_id)
            if costume_id not in costume_ids or costume_character_by_id.get(costume_id) != character_id:
                raise ToolError("PRODUCTION_CODEX_VISUAL_PLAN_INVALID", f"scenePlans[{index}] 未给出镜角色绑定正确服装。")
        scene_prop_ids = continuity.get("propIds", [])
        if not isinstance(scene_prop_ids, list) or any(prop_id not in prop_ids for prop_id in scene_prop_ids):
            raise ToolError("PRODUCTION_CODEX_VISUAL_PLAN_INVALID", f"scenePlans[{index}].continuity.propIds 无效。")
        normalized_continuity = {
            "locationId": continuity["locationId"],
            "costumeIdsByCharacter": {character_id: costume_bindings[character_id] for character_id in visible_ids},
            "propIds": list(dict.fromkeys(scene_prop_ids)),
            "changeJustificationZh": _non_empty_text(continuity.get("changeJustificationZh"), f"scenePlans[{index}].continuity.changeJustificationZh", maximum=240),
        }
        continuity_state = item.get("continuityState")
        if not isinstance(continuity_state, dict):
            raise ToolError("PRODUCTION_CODEX_VISUAL_PLAN_INVALID", f"scenePlans[{index}].continuityState 缺失。")
        carry_over_from_scene_id = continuity_state.get("carryOverFromSceneId", "")
        if not isinstance(carry_over_from_scene_id, str):
            raise ToolError("PRODUCTION_CODEX_VISUAL_PLAN_INVALID", f"scenePlans[{index}].continuityState.carryOverFromSceneId 必须是字符串。")
        normalized_continuity_state = {
            "entryStateId": _non_empty_text(continuity_state.get("entryStateId"), f"scenePlans[{index}].continuityState.entryStateId", maximum=160),
            "entryStateZh": _non_empty_text(continuity_state.get("entryStateZh"), f"scenePlans[{index}].continuityState.entryStateZh", maximum=420),
            "exitStateId": _non_empty_text(continuity_state.get("exitStateId"), f"scenePlans[{index}].continuityState.exitStateId", maximum=160),
            "exitStateZh": _non_empty_text(continuity_state.get("exitStateZh"), f"scenePlans[{index}].continuityState.exitStateZh", maximum=420),
            "characterBlockingZh": _non_empty_text(continuity_state.get("characterBlockingZh"), f"scenePlans[{index}].continuityState.characterBlockingZh", maximum=320),
            "screenDirectionZh": _non_empty_text(continuity_state.get("screenDirectionZh"), f"scenePlans[{index}].continuityState.screenDirectionZh", maximum=260),
            "eyelineZh": _non_empty_text(continuity_state.get("eyelineZh"), f"scenePlans[{index}].continuityState.eyelineZh", maximum=260),
            "propStateZh": _non_empty_text(continuity_state.get("propStateZh"), f"scenePlans[{index}].continuityState.propStateZh", maximum=260),
            "lightingStateZh": _non_empty_text(continuity_state.get("lightingStateZh"), f"scenePlans[{index}].continuityState.lightingStateZh", maximum=260),
            "carryOverFromSceneId": carry_over_from_scene_id.strip(),
        }

        emotional_beat = item.get("emotionalBeat")
        if not isinstance(emotional_beat, dict) or emotional_beat.get("category") not in CODEX_CRITICAL_EMOTIONS:
            raise ToolError("PRODUCTION_CODEX_VISUAL_PLAN_INVALID", f"scenePlans[{index}].emotionalBeat.category 无效。")
        emotion_category = emotional_beat["category"]
        visual_signals = emotional_beat.get("visualSignals", [])
        if not isinstance(visual_signals, list) or any(signal not in CODEX_EMOTION_SIGNALS for signal in visual_signals):
            raise ToolError("PRODUCTION_CODEX_VISUAL_PLAN_INVALID", f"scenePlans[{index}].emotionalBeat.visualSignals 无效。")
        visual_signals = list(dict.fromkeys(visual_signals))
        if emotion_category != "none":
            if shot["scale"] not in {"close_up", "extreme_close_up"} and not breaking_composition:
                raise ToolError("PRODUCTION_CODEX_VISUAL_PLAN_INVALID", f"scenePlans[{index}] 情绪爆点必须使用特写／极近特写或破格构图。")
            if len(visual_signals) < 2 or not CODEX_PHYSICAL_EMOTION_SIGNALS.intersection(visual_signals):
                raise ToolError("PRODUCTION_CODEX_VISUAL_PLAN_INVALID", f"scenePlans[{index}] 情绪爆点至少需要两个可见信号，且不能只靠明暗或色彩。")
            if visible_ids and expression_exaggeration < 3:
                raise ToolError("PRODUCTION_CODEX_VISUAL_PLAN_INVALID", f"scenePlans[{index}] 情绪爆点的表情夸张度不得低于 3。")

        prompt_components = item.get("promptComponents")
        if not isinstance(prompt_components, dict):
            raise ToolError("PRODUCTION_CODEX_VISUAL_PLAN_INVALID", f"scenePlans[{index}].promptComponents 缺失。")
        normalized_components = {
            field: _non_empty_text(prompt_components.get(field), f"scenePlans[{index}].promptComponents.{field}", maximum=260)
            for field in CODEX_PROMPT_COMPONENT_FIELDS
        }
        generic_component_risk = _generic_scene_language_risk(*normalized_components.values())
        if generic_component_risk:
            raise ToolError(
                "PRODUCTION_CODEX_VISUAL_PLAN_INVALID",
                f"scenePlans[{index}].promptComponents 使用了不可跨项目复用的模板语句：{generic_component_risk}。",
            )
        for character_id in visible_ids:
            costume_id = costume_bindings[character_id]
            costume_features = costume_features_by_id[costume_id]
            if not any(feature in normalized_components["continuityEnvironmentZh"] for feature in costume_features):
                raise ToolError(
                    "PRODUCTION_CODEX_VISUAL_PLAN_INVALID",
                    f"scenePlans[{index}] 没有把当前剧情服装写入 continuityEnvironmentZh，角色参考图可能覆盖实际剧情服装。",
                    details={"characterId": character_id, "costumeId": costume_id, "requiredFeatures": costume_features},
                )
        battle_effects = str(prompt_components.get("battleEffectsZh") or "").strip()
        combat_direction = item.get("combatDirection")
        if not isinstance(combat_direction, dict) or not isinstance(combat_direction.get("active"), bool):
            raise ToolError("PRODUCTION_CODEX_VISUAL_PLAN_INVALID", f"scenePlans[{index}].combatDirection.active 必须明确为 true 或 false。")
        if combat_direction["active"]:
            combat_phase = combat_direction.get("phase")
            if combat_phase not in CODEX_COMBAT_PHASES:
                raise ToolError("PRODUCTION_CODEX_VISUAL_PLAN_INVALID", f"scenePlans[{index}].combatDirection.phase 无效。")
            normalized_combat_direction = {
                "active": True,
                "phase": combat_phase,
                **{
                    field: _non_empty_text(
                        combat_direction.get(field), f"scenePlans[{index}].combatDirection.{field}", maximum=300
                    )
                    for field in CODEX_COMBAT_DIRECTION_FIELDS
                },
            }
            battle_effects = _non_empty_text(
                battle_effects, f"scenePlans[{index}].promptComponents.battleEffectsZh", maximum=320
            )
            for field, text in (
                ("combatDirection.frozenMomentZh", normalized_combat_direction["frozenMomentZh"]),
                ("promptComponents.battleEffectsZh", battle_effects),
            ):
                temporal_risk = _image_prompt_temporal_sequence_risk(text)
                if temporal_risk:
                    raise ToolError(
                        "PRODUCTION_CODEX_VISUAL_PLAN_INVALID",
                        f"scenePlans[{index}].{field} 必须只描述战斗的一个动作阶段：{temporal_risk}。",
                    )
        else:
            if combat_direction.get("phase") != "none" or battle_effects:
                raise ToolError(
                    "PRODUCTION_CODEX_VISUAL_PLAN_INVALID",
                    f"scenePlans[{index}] 非战斗镜头必须使用 phase=none 且 battleEffectsZh 为空。",
                )
            normalized_combat_direction = {"active": False, "phase": "none"}
        normalized_components["battleEffectsZh"] = battle_effects
        image_prompt = str(item.get("imagePromptZh") or "").strip()
        video_prompt = str(item.get("videoPromptZh") or "").strip()
        if prompt_generation["image"]:
            image_prompt = _non_empty_text(image_prompt, f"scenePlans[{index}].imagePromptZh", maximum=CODEX_IMAGE_PROMPT_MAXIMUM)
            if len(image_prompt) < CODEX_IMAGE_PROMPT_SOFT_MINIMUM:
                raise ToolError(
                    "PRODUCTION_CODEX_VISUAL_PLAN_INVALID",
                    f"scenePlans[{index}].imagePromptZh 只有 {len(image_prompt)} 字符，低于 {CODEX_IMAGE_PROMPT_SOFT_MINIMUM} 字符质量下限。",
                )
            temporal_risk = _image_prompt_temporal_sequence_risk(image_prompt)
            if temporal_risk:
                raise ToolError(
                    "PRODUCTION_CODEX_VISUAL_PLAN_INVALID",
                    f"scenePlans[{index}].imagePromptZh 必须只描述一个静态决定性瞬间：{temporal_risk}。",
                )
            if normalized_combat_direction["active"] and battle_effects not in image_prompt:
                raise ToolError(
                    "PRODUCTION_CODEX_VISUAL_PLAN_INVALID",
                    f"scenePlans[{index}].imagePromptZh 必须编入已锁定的战斗特效组件。",
                )
            grounded_components = sum(
                component in image_prompt
                for component in normalized_components.values()
                if component
            )
            if grounded_components < 3:
                raise ToolError(
                    "PRODUCTION_CODEX_VISUAL_PLAN_INVALID",
                    f"scenePlans[{index}].imagePromptZh 未直接编入足够的剧情动作、表演、构图或连续性组件。",
                )
            if normalized_components["continuityEnvironmentZh"] not in image_prompt:
                raise ToolError(
                    "PRODUCTION_CODEX_VISUAL_PLAN_INVALID",
                    f"scenePlans[{index}].imagePromptZh 必须直接编入地点与当前服装连续性，禁止参考图服装覆盖剧情。",
                )
            compact_prompt = re.sub(r"\s+", "", image_prompt).lower()
            if "文字" not in compact_prompt and "文本" not in compact_prompt and "readabletext" not in compact_prompt:
                raise ToolError(
                    "PRODUCTION_CODEX_VISUAL_PLAN_INVALID",
                    f"scenePlans[{index}].imagePromptZh 必须明确禁止可读文字。",
                )
        elif len(image_prompt) > CODEX_IMAGE_PROMPT_MAXIMUM:
            raise ToolError("PRODUCTION_CODEX_VISUAL_PLAN_INVALID", f"scenePlans[{index}].imagePromptZh 过长。")
        if prompt_generation["video"]:
            video_prompt = _non_empty_text(video_prompt, f"scenePlans[{index}].videoPromptZh", maximum=CODEX_VIDEO_PROMPT_MAXIMUM)
            if normalized_combat_direction["active"] and battle_effects not in video_prompt:
                raise ToolError(
                    "PRODUCTION_CODEX_VISUAL_PLAN_INVALID",
                    f"scenePlans[{index}].videoPromptZh 必须编入已锁定的战斗特效组件。",
                )
        elif len(video_prompt) > CODEX_VIDEO_PROMPT_MAXIMUM:
            raise ToolError("PRODUCTION_CODEX_VISUAL_PLAN_INVALID", f"scenePlans[{index}].videoPromptZh 过长。")

        normalized_scene = {
            "sceneId": scene_id,
            "episodeNumber": item.get("episodeNumber"),
            "sequence": index,
            "sequenceId": sequence_id,
            "shotRole": shot_role,
            "semanticGroupId": semantic_group_id,
            "scriptLineIds": line_ids,
            "visibleCharacterIds": visible_ids,
            "appearanceBindings": normalized_appearance_bindings,
            "primaryCharacterId": item.get("primaryCharacterId") if visible_ids else "",
            "noCharacter": len(visible_ids) == 0,
            "complexityScore": complexity_score,
            "impactLevel": impact_level,
            "expressionExaggeration": expression_exaggeration,
            "narrativeFunction": narrative_function,
            "storyBeatIds": list(dict.fromkeys(beat_ids)),
            "shot": normalized_shot,
            "visualReadability": normalized_readability,
            "continuity": normalized_continuity,
            "continuityState": normalized_continuity_state,
            "emotionalBeat": {"category": emotion_category, "visualSignals": visual_signals},
            "mangaComposition": normalized_manga_composition,
            "facialActing": normalized_facial_acting,
            "bodyActing": normalized_body_acting,
            "combatDirection": normalized_combat_direction,
            "promptComponents": normalized_components,
            "imagePromptZh": image_prompt,
            "videoPromptZh": video_prompt,
            "performance": normalized_performance,
        }
        normalized_scenes.append(normalized_scene)
        scene_by_id[scene_id] = normalized_scene
        covered_line_ids.extend(line_ids)
    if requires_scene_plan and covered_line_ids != expected_line_ids:
        raise ToolError(
            "PRODUCTION_CODEX_VISUAL_PLAN_INVALID",
            "Codex 分镜方案必须按正式稿顺序完整且仅覆盖每一行一次。",
            details={"expectedLineIds": expected_line_ids, "actualLineIds": covered_line_ids},
        )
    _validate_sound_effect_scene_bindings(
        target_lines,
        {
            line_id: scene["sceneId"]
            for scene in normalized_scenes
            for line_id in scene["scriptLineIds"]
        },
    )
    if used_semantic_group_ids != [group["groupId"] for group in normalized_semantic_groups]:
        raise ToolError(
            "PRODUCTION_CODEX_VISUAL_PLAN_INVALID",
            "每个语义画面组必须按顺序且仅绑定一个分镜。",
        )

    if prompt_generation["image"] and len(normalized_scenes) >= 20:
        prompt_signatures = [re.sub(r"[\s，。；、,:：;]+", "", scene["imagePromptZh"]).lower() for scene in normalized_scenes]
        unique_prompt_ratio = len(set(prompt_signatures)) / len(prompt_signatures)
        prompt_counts = Counter(prompt_signatures)
        most_repeated_prompt = prompt_counts.most_common(1)[0][1]
        if unique_prompt_ratio < CODEX_IMAGE_PROMPT_MINIMUM_UNIQUE_RATIO or most_repeated_prompt > 2:
            raise ToolError(
                "PRODUCTION_CODEX_VISUAL_PLAN_INVALID",
                "整套图片提示词重复度过高，必须让每镜直接体现本镜独有的场景、动作、表演、构图和连续性。",
                details={
                    "sceneCount": len(normalized_scenes),
                    "uniquePromptCount": len(set(prompt_signatures)),
                    "uniquePromptRatio": round(unique_prompt_ratio, 4),
                    "maximumExactRepeat": most_repeated_prompt,
                    "requiredUniqueRatio": CODEX_IMAGE_PROMPT_MINIMUM_UNIQUE_RATIO,
                },
            )

    if len(normalized_semantic_groups) >= 40:
        group_size_counts = Counter(len(group["sourceLineIds"]) for group in normalized_semantic_groups)
        dominant_group_size, dominant_group_count = group_size_counts.most_common(1)[0]
        dominant_group_ratio = dominant_group_count / len(normalized_semantic_groups)
        decision_reason_ratio = len({group["decisionReasonZh"] for group in normalized_semantic_groups}) / len(normalized_semantic_groups)
        visual_moment_ratio = len({group["visualMomentZh"] for group in normalized_semantic_groups}) / len(normalized_semantic_groups)
        if (
            dominant_group_size > 1
            and dominant_group_ratio > CODEX_SEMANTIC_GROUP_DOMINANCE_LIMIT
            and (decision_reason_ratio < 0.60 or visual_moment_ratio < 0.60)
        ):
            raise ToolError(
                "PRODUCTION_CODEX_VISUAL_PLAN_INVALID",
                "语义画面组呈现固定行数机械切分特征，必须重新按剧情中的可见变化与决定性瞬间分组。",
                details={
                    "dominantLineCount": dominant_group_size,
                    "dominantGroupRatio": round(dominant_group_ratio, 4),
                    "decisionReasonUniqueRatio": round(decision_reason_ratio, 4),
                    "visualMomentUniqueRatio": round(visual_moment_ratio, 4),
                },
            )

    scenes_by_episode: dict[int, list[dict[str, Any]]] = {}
    for scene in normalized_scenes:
        scenes_by_episode.setdefault(scene["episodeNumber"], []).append(scene)
    for episode_scenes in scenes_by_episode.values():
        if len(episode_scenes) >= 12:
            role_counts = Counter(scene["shotRole"] for scene in episode_scenes)
            dominant_role, dominant_role_count = role_counts.most_common(1)[0]
            if dominant_role_count / len(episode_scenes) > CODEX_SCENE_ROLE_DOMINANCE_LIMIT:
                raise ToolError(
                    "PRODUCTION_CODEX_VISUAL_PLAN_INVALID",
                    "单集镜头功能过度集中，必须补齐建立、行动、反应、情绪、结果与高潮所需的剧情镜头。",
                    details={"dominantRole": dominant_role, "dominantRoleRatio": round(dominant_role_count / len(episode_scenes), 4)},
                )
            episode_roles = set(role_counts)
            if "climax" not in episode_roles or not episode_roles.intersection({"emotion_closeup", "consequence", "aftermath"}):
                raise ToolError(
                    "PRODUCTION_CODEX_VISUAL_PLAN_INVALID",
                    "单集缺少高潮或情绪／结果回报镜头，不能把故事全部降级为普通反应镜头。",
                    details={"episodeNumber": episode_scenes[0]["episodeNumber"], "shotRoles": sorted(episode_roles)},
                )
            impact_levels = [scene["impactLevel"] for scene in episode_scenes]
            if min(impact_levels) > 2 or max(impact_levels) < 4:
                raise ToolError(
                    "PRODUCTION_CODEX_VISUAL_PLAN_INVALID",
                    "单集缺少视觉蓄力与爆发的冲击曲线，impactLevel 必须同时包含低强度铺垫和 4–5 级关键画面。",
                    details={"episodeNumber": episode_scenes[0]["episodeNumber"], "minimum": min(impact_levels), "maximum": max(impact_levels)},
                )
        previous_emotion = "none"
        repeated_dialogue = 0
        repeated_shot = 0
        repeated_high_impact = 0
        previous_signature: tuple[str, str, str] | None = None
        previous_scene_id = ""
        for scene in episode_scenes:
            if scene["continuityState"]["carryOverFromSceneId"] != previous_scene_id:
                raise ToolError(
                    "PRODUCTION_CODEX_VISUAL_PLAN_INVALID",
                    f"分镜 {scene['sceneId']} 的进入状态没有承接上一镜；carryOverFromSceneId 应为“{previous_scene_id}”。",
                )
            previous_scene_id = scene["sceneId"]
            emotion = scene["emotionalBeat"]["category"]
            if emotion != "none" and emotion == previous_emotion:
                raise ToolError("PRODUCTION_CODEX_VISUAL_PLAN_INVALID", "相邻分镜不得连续重复同一种情绪爆点。")
            previous_emotion = emotion
            repeated_dialogue = repeated_dialogue + 1 if scene["shot"]["dialogueStaging"] == "half_body_dialogue" else 0
            if repeated_dialogue >= 3:
                raise ToolError("PRODUCTION_CODEX_VISUAL_PLAN_INVALID", "不得连续三镜使用人物半身对话构图。")
            signature = (scene["shot"]["scale"], scene["shot"]["angle"], scene["shot"]["view"])
            repeated_shot = repeated_shot + 1 if signature == previous_signature else 1
            if repeated_shot >= 3:
                raise ToolError("PRODUCTION_CODEX_VISUAL_PLAN_INVALID", "不得连续三镜使用完全相同的景别、角度和视向。")
            previous_signature = signature
            repeated_high_impact = repeated_high_impact + 1 if scene["impactLevel"] >= 4 else 0
            if repeated_high_impact >= 3:
                raise ToolError("PRODUCTION_CODEX_VISUAL_PLAN_INVALID", "不得连续三镜都使用高冲击构图，必须保留视觉蓄力与爆发对比。")

    complexity_level = story_visual_plan.get("complexityLevel")
    if not isinstance(complexity_level, int) or isinstance(complexity_level, bool) or complexity_level not in CODEX_COMPLEXITY_LEVELS:
        raise ToolError("PRODUCTION_CODEX_VISUAL_PLAN_INVALID", "storyVisualPlan.complexityLevel 必须为 1–5。")
    planned_page_count = story_visual_plan.get("plannedPageCount")
    if story_visual_plan.get("pageCountMode") != "complexity_adaptive" or planned_page_count != len(normalized_scenes):
        raise ToolError("PRODUCTION_CODEX_VISUAL_PLAN_INVALID", "分镜页数必须按剧情语义自适应，并与实际分镜数一致；不得按语音时长强制拆画面。")
    opening_hook_scene_id = story_visual_plan.get("openingHookSceneId")
    if not normalized_scenes or opening_hook_scene_id != normalized_scenes[0]["sceneId"] or normalized_scenes[0]["narrativeFunction"] != "hook":
        raise ToolError("PRODUCTION_CODEX_VISUAL_PLAN_INVALID", "第一镜必须是已绑定正式稿的开篇钩子。")
    relationship_conflict_scene_ids = story_visual_plan.get("relationshipConflictSceneIds")
    if not isinstance(relationship_conflict_scene_ids, list) or not relationship_conflict_scene_ids or any(scene_id not in scene_by_id for scene_id in relationship_conflict_scene_ids):
        raise ToolError("PRODUCTION_CODEX_VISUAL_PLAN_INVALID", "storyVisualPlan.relationshipConflictSceneIds 无效。")

    story_beats = story_visual_plan.get("storyBeats")
    if not isinstance(story_beats, list) or not story_beats:
        raise ToolError("PRODUCTION_CODEX_VISUAL_PLAN_INVALID", "storyVisualPlan.storyBeats 不能为空。")
    normalized_beats: list[dict[str, Any]] = []
    beat_ids: set[str] = set()
    beat_types: set[str] = set()
    for beat_index, beat in enumerate(story_beats, start=1):
        if not isinstance(beat, dict) or beat.get("type") not in CODEX_NARRATIVE_FUNCTIONS:
            raise ToolError("PRODUCTION_CODEX_VISUAL_PLAN_INVALID", f"storyBeats[{beat_index}] 无效。")
        beat_id = _non_empty_text(beat.get("beatId"), f"storyBeats[{beat_index}].beatId", maximum=120)
        if beat_id in beat_ids:
            raise ToolError("PRODUCTION_CODEX_VISUAL_PLAN_INVALID", f"storyBeats[{beat_index}].beatId 重复。")
        source_line_ids = beat.get("sourceLineIds")
        beat_scene_ids = beat.get("sceneIds")
        if not isinstance(source_line_ids, list) or not source_line_ids or any(line_id not in line_by_id for line_id in source_line_ids):
            raise ToolError("PRODUCTION_CODEX_VISUAL_PLAN_INVALID", f"storyBeats[{beat_index}].sourceLineIds 无效。")
        if not isinstance(beat_scene_ids, list) or not beat_scene_ids or any(scene_id not in scene_by_id for scene_id in beat_scene_ids):
            raise ToolError("PRODUCTION_CODEX_VISUAL_PLAN_INVALID", f"storyBeats[{beat_index}].sceneIds 无效。")
        if any(beat_id not in scene_by_id[scene_id]["storyBeatIds"] for scene_id in beat_scene_ids):
            raise ToolError("PRODUCTION_CODEX_VISUAL_PLAN_INVALID", f"storyBeats[{beat_index}] 与分镜绑定不一致。")
        bound_line_ids = {
            line_id
            for scene_id in beat_scene_ids
            for line_id in scene_by_id[scene_id]["scriptLineIds"]
        }
        if not set(source_line_ids).issubset(bound_line_ids):
            raise ToolError("PRODUCTION_CODEX_VISUAL_PLAN_INVALID", f"storyBeats[{beat_index}] 的来源正式稿行与承载分镜不一致。")
        beat_ids.add(beat_id)
        beat_types.add(beat["type"])
        normalized_beats.append({
            "beatId": beat_id,
            "type": beat["type"],
            "summaryZh": _non_empty_text(beat.get("summaryZh"), f"storyBeats[{beat_index}].summaryZh", maximum=320),
            "sourceLineIds": list(dict.fromkeys(source_line_ids)),
            "sceneIds": list(dict.fromkeys(beat_scene_ids)),
        })
    if not {"hook", "relationship", "conflict"}.issubset(beat_types):
        raise ToolError("PRODUCTION_CODEX_VISUAL_PLAN_INVALID", "storyBeats 必须覆盖开篇钩子、人物关系和核心矛盾。")
    required_relation_beat_ids = {beat["beatId"] for beat in normalized_beats if beat["type"] == "relationship"}
    required_conflict_beat_ids = {beat["beatId"] for beat in normalized_beats if beat["type"] == "conflict"}
    relationship_conflict_bindings = {
        beat_id
        for scene_id in relationship_conflict_scene_ids
        for beat_id in scene_by_id[scene_id]["storyBeatIds"]
    }
    if not relationship_conflict_bindings.intersection(required_relation_beat_ids) or not relationship_conflict_bindings.intersection(required_conflict_beat_ids):
        raise ToolError("PRODUCTION_CODEX_VISUAL_PLAN_INVALID", "关系／核心矛盾分镜必须分别绑定 relationship 与 conflict 节拍。")
    if any(beat_id not in beat_ids for scene in normalized_scenes for beat_id in scene["storyBeatIds"]):
        raise ToolError("PRODUCTION_CODEX_VISUAL_PLAN_INVALID", "分镜引用了不存在的 storyBeatId。")

    visual_sequences = story_visual_plan.get("visualSequences")
    if not isinstance(visual_sequences, list) or not visual_sequences:
        raise ToolError("PRODUCTION_CODEX_VISUAL_PLAN_INVALID", "storyVisualPlan.visualSequences 不能为空。")
    normalized_sequences: list[dict[str, Any]] = []
    seen_sequence_ids: set[str] = set()
    ordered_sequence_scene_ids: list[str] = []
    previous_sequence_by_episode: dict[int, dict[str, Any]] = {}
    for sequence_index, sequence in enumerate(visual_sequences, start=1):
        if not isinstance(sequence, dict):
            raise ToolError("PRODUCTION_CODEX_VISUAL_PLAN_INVALID", f"visualSequences[{sequence_index}] 必须是对象。")
        sequence_id = _non_empty_text(sequence.get("sequenceId"), f"visualSequences[{sequence_index}].sequenceId", maximum=160)
        if sequence_id in seen_sequence_ids:
            raise ToolError("PRODUCTION_CODEX_VISUAL_PLAN_INVALID", f"visualSequences[{sequence_index}].sequenceId 重复。")
        seen_sequence_ids.add(sequence_id)
        sequence_scene_ids = sequence.get("sceneIds")
        if not isinstance(sequence_scene_ids, list) or not sequence_scene_ids or any(scene_id not in scene_by_id for scene_id in sequence_scene_ids):
            raise ToolError("PRODUCTION_CODEX_VISUAL_PLAN_INVALID", f"visualSequences[{sequence_index}].sceneIds 无效。")
        sequence_episode_number = sequence.get("episodeNumber")
        sequence_scenes = [scene_by_id[scene_id] for scene_id in sequence_scene_ids]
        if any(scene["episodeNumber"] != sequence_episode_number or scene["sequenceId"] != sequence_id for scene in sequence_scenes):
            raise ToolError("PRODUCTION_CODEX_VISUAL_PLAN_INVALID", f"visualSequences[{sequence_index}] 与分镜集数或 sequenceId 绑定不一致。")
        sequence_location_id = sequence.get("locationId")
        if sequence_location_id not in location_ids or any(scene["continuity"]["locationId"] != sequence_location_id for scene in sequence_scenes):
            raise ToolError("PRODUCTION_CODEX_VISUAL_PLAN_INVALID", f"visualSequences[{sequence_index}] 必须在同一冻结地点内连续调度。")
        shot_ladder = sequence.get("shotLadder")
        impact_arc = sequence.get("impactArc")
        if shot_ladder != [scene["shotRole"] for scene in sequence_scenes]:
            raise ToolError("PRODUCTION_CODEX_VISUAL_PLAN_INVALID", f"visualSequences[{sequence_index}].shotLadder 必须与实际镜头功能顺序一致。")
        if impact_arc != [scene["impactLevel"] for scene in sequence_scenes]:
            raise ToolError("PRODUCTION_CODEX_VISUAL_PLAN_INVALID", f"visualSequences[{sequence_index}].impactArc 必须与实际镜头冲击等级一致。")
        opening_state_id = _non_empty_text(sequence.get("openingStateId"), f"visualSequences[{sequence_index}].openingStateId", maximum=160)
        closing_state_id = _non_empty_text(sequence.get("closingStateId"), f"visualSequences[{sequence_index}].closingStateId", maximum=160)
        if opening_state_id != sequence_scenes[0]["continuityState"]["entryStateId"] or closing_state_id != sequence_scenes[-1]["continuityState"]["exitStateId"]:
            raise ToolError("PRODUCTION_CODEX_VISUAL_PLAN_INVALID", f"visualSequences[{sequence_index}] 的首尾状态与分镜不一致。")
        for local_index, scene in enumerate(sequence_scenes[1:], start=1):
            previous_scene = sequence_scenes[local_index - 1]
            if scene["continuityState"]["entryStateId"] != previous_scene["continuityState"]["exitStateId"]:
                raise ToolError(
                    "PRODUCTION_CODEX_VISUAL_PLAN_INVALID",
                    f"visualSequences[{sequence_index}] 内分镜 {scene['sceneId']} 的进入状态没有继承上一镜离开状态。",
                )
        previous_sequence = previous_sequence_by_episode.get(sequence_episode_number)
        if previous_sequence and previous_sequence["locationId"] != sequence_location_id and sequence_scenes[0]["shotRole"] not in {"establishing", "transition"}:
            raise ToolError(
                "PRODUCTION_CODEX_VISUAL_PLAN_INVALID",
                f"visualSequences[{sequence_index}] 更换地点后必须以环境建立或转场镜头开始。",
            )
        normalized_sequence = {
            "sequenceId": sequence_id,
            "episodeNumber": sequence_episode_number,
            "sceneIds": list(sequence_scene_ids),
            "locationId": sequence_location_id,
            "timeLightingZh": _non_empty_text(sequence.get("timeLightingZh"), f"visualSequences[{sequence_index}].timeLightingZh", maximum=320),
            "paletteContrastZh": _non_empty_text(sequence.get("paletteContrastZh"), f"visualSequences[{sequence_index}].paletteContrastZh", maximum=320),
            "spatialAxisZh": _non_empty_text(sequence.get("spatialAxisZh"), f"visualSequences[{sequence_index}].spatialAxisZh", maximum=320),
            "openingStateId": opening_state_id,
            "closingStateId": closing_state_id,
            "continuityFromPreviousZh": _non_empty_text(sequence.get("continuityFromPreviousZh"), f"visualSequences[{sequence_index}].continuityFromPreviousZh", maximum=420),
            "shotLadder": list(shot_ladder),
            "impactArc": list(impact_arc),
        }
        normalized_sequences.append(normalized_sequence)
        previous_sequence_by_episode[sequence_episode_number] = normalized_sequence
        ordered_sequence_scene_ids.extend(sequence_scene_ids)
    if ordered_sequence_scene_ids != [scene["sceneId"] for scene in normalized_scenes]:
        raise ToolError(
            "PRODUCTION_CODEX_VISUAL_PLAN_INVALID",
            "visualSequences 必须按正式分镜顺序完整且仅覆盖每一镜一次。",
        )

    prompt_compiler = story_visual_plan.get("promptCompiler")
    if (
        not isinstance(prompt_compiler, dict)
        or prompt_compiler.get("mode") != "manga_structured_budgeted_merge"
        or prompt_compiler.get("imagePromptMaxChars") != CODEX_IMAGE_PROMPT_MAXIMUM
        or prompt_compiler.get("imagePromptSoftMinChars") != CODEX_IMAGE_PROMPT_SOFT_MINIMUM
        or prompt_compiler.get("imagePromptSoftMaxChars") != CODEX_IMAGE_PROMPT_SOFT_MAXIMUM
        or prompt_compiler.get("videoPromptMaxChars") != CODEX_VIDEO_PROMPT_MAXIMUM
        or prompt_compiler.get("globalStyleRepeatedPerScene") is not False
        or prompt_compiler.get("identityFullProfileRepeatedPerScene") is not False
        or prompt_compiler.get("singlePanelDirectiveRequired") is not True
        or prompt_compiler.get("singleFocalPointRequired") is not True
        or prompt_compiler.get("clutterControlRequired") is not True
        or prompt_compiler.get("fullSeriesContextRequired") is not True
        or prompt_compiler.get("sequencePlanRequired") is not True
        or prompt_compiler.get("continuityStateRequired") is not True
        or prompt_compiler.get("temporalSequenceForbidden") is not True
        or prompt_compiler.get("shotRoleRequired") is not True
        or prompt_compiler.get("semanticBeatGroupingRequired") is not True
        or prompt_compiler.get("lineBreakSplitForbidden") is not True
        or prompt_compiler.get("lineCountHardCapDisabled") is not True
        or prompt_compiler.get("combatEffectsContractRequired") is not True
        or prompt_compiler.get("combatKeyMomentSelectionRequired") is not True
        or prompt_compiler.get("failureRepairScope") != CODEX_FAILURE_REPAIR_SCOPE
    ):
        raise ToolError(
            "PRODUCTION_CODEX_VISUAL_PLAN_INVALID",
            "promptCompiler 必须使用漫画单幅、单焦点、画面减法和预算内合并合同，且不得逐镜重复全局画风和完整角色设定。",
        )

    style_prompt = production_config["imageStyle"]["prompt"]
    normalized = {
        "schemaVersion": CODEX_VISUAL_PLAN_SCHEMA_VERSION,
        "author": CODEX_VISUAL_PLAN_AUTHOR,
        "projectId": manuscript.get("projectId"),
        "stylePresetId": production_config["imageStyle"]["presetId"],
        "stylePromptSha256": _sha256_bytes(style_prompt.encode("utf-8")),
        "referenceUsage": CODEX_REFERENCE_USAGE,
        "visualDirection": dict(CODEX_VISUAL_DIRECTION),
        "seriesVisualPlan": normalized_series_visual_plan,
        "characterDesigns": normalized_designs,
        "continuityBible": {"locations": locations, "costumes": costumes, "props": props},
        "storyVisualPlan": {
            "openingHookSceneId": opening_hook_scene_id,
            "relationshipConflictSceneIds": list(dict.fromkeys(relationship_conflict_scene_ids)),
            "complexityLevel": complexity_level,
            "pageCountMode": "complexity_adaptive",
            "plannedPageCount": planned_page_count,
            "pageCountRationaleZh": _non_empty_text(story_visual_plan.get("pageCountRationaleZh"), "storyVisualPlan.pageCountRationaleZh", maximum=420),
            "semanticGrouping": {
                "mode": CODEX_SEMANTIC_GROUPING_MODE,
                "ttsLineBreakCreatesScene": False,
                "durationCreatesScene": False,
                "mergeBeforeContinuityPlanning": True,
                "lineCountHardCap": False,
                "actionPhaseChangeCreatesScene": False,
                "splitOnlyForImportantVisibleChange": True,
            },
            "combatSelectionPolicy": {
                "mode": "key_moments_only",
                "allPhasesRequired": False,
                "phaseChangeCreatesScene": False,
                "intermediatePhasesMayBeOmitted": True,
            },
            "semanticBeatGroups": normalized_semantic_groups,
            "storyBeats": normalized_beats,
            "visualSequences": normalized_sequences,
            "promptCompiler": {
                "mode": "manga_structured_budgeted_merge",
                "imagePromptMaxChars": CODEX_IMAGE_PROMPT_MAXIMUM,
                "imagePromptSoftMinChars": CODEX_IMAGE_PROMPT_SOFT_MINIMUM,
                "imagePromptSoftMaxChars": CODEX_IMAGE_PROMPT_SOFT_MAXIMUM,
                "videoPromptMaxChars": CODEX_VIDEO_PROMPT_MAXIMUM,
                "globalStyleRepeatedPerScene": False,
                "identityFullProfileRepeatedPerScene": False,
                "singlePanelDirectiveRequired": True,
                "singleFocalPointRequired": True,
                "clutterControlRequired": True,
                "fullSeriesContextRequired": True,
                "sequencePlanRequired": True,
                "continuityStateRequired": True,
                "temporalSequenceForbidden": True,
                "shotRoleRequired": True,
                "semanticBeatGroupingRequired": True,
                "lineBreakSplitForbidden": True,
                "lineCountHardCapDisabled": True,
                "combatEffectsContractRequired": True,
                "combatKeyMomentSelectionRequired": True,
                "failureRepairScope": CODEX_FAILURE_REPAIR_SCOPE,
            },
        },
        "scenePlans": normalized_scenes,
        "storyImageTextPolicy": "forbid_visible_text",
        "locks": {
            "identity": ["face", "eyes", "hair", "bodyProportion", "outfitSilhouette", "palette", "fixedAccessories"],
            "performanceIsSceneSpecific": True,
            "workshopMayRewritePrompts": False,
            "criticalEmotionRequiresCloseOrBreakingComposition": True,
            "adjacentSameCriticalEmotionForbidden": True,
            "continuityBindingsRequired": True,
            "singlePanelMangaRequired": True,
            "singleVisualFocusRequired": True,
            "exaggeratedStoryDrivenExpressionRequired": True,
            "adaptiveBackgroundSimplificationRequired": True,
            "clutterControlRequired": True,
            "fullSeriesContextRequired": True,
            "sequenceContinuityRequired": True,
            "temporalSequenceInSingleImageForbidden": True,
            "semanticBeatGroupingRequired": True,
            "lineBreakSplitForbidden": True,
            "lineCountHardCapDisabled": True,
            "combatEffectsContractRequired": True,
            "combatKeyMomentSelectionRequired": True,
            "failedPromptRepairScope": CODEX_FAILURE_REPAIR_SCOPE,
            "atomicImageReplacementRequired": True,
        },
    }
    normalized["contentHash"] = _sha256_bytes(_canonical_bytes(normalized))
    return normalized


def _safe_identifier(value: Any, field: str, *, maximum: int = 160) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", value):
        raise ToolError("PRODUCTION_IDENTIFIER_INVALID", f"{field} 必须是安全标识符。")
    if len(value) > maximum:
        raise ToolError("PRODUCTION_IDENTIFIER_INVALID", f"{field} 过长。")
    return value


def _safe_relative(value: Any, field: str) -> Path:
    if not isinstance(value, str) or not value or "\\" in value:
        raise ToolError("PRODUCTION_PATH_INVALID", f"{field} 必须使用包内 POSIX 相对路径。")
    path = Path(value)
    if path.is_absolute() or path.drive or any(part in {"", ".", ".."} for part in path.parts):
        raise ToolError("PRODUCTION_PATH_INVALID", f"{field} 不能引用包外路径。")
    return path


def _ensure_within(root: Path, candidate: Path, field: str) -> Path:
    resolved_root = root.resolve()
    resolved = candidate.resolve()
    if resolved != resolved_root and resolved_root not in resolved.parents:
        raise ToolError("PRODUCTION_PATH_OUTSIDE_ROOT", f"{field} 超出隔离根目录。")
    return resolved


def _read_json(path: Path, code: str = "PRODUCTION_JSON_INVALID") -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ToolError(code, "生产文件不可读或 JSON 已损坏。", details={"file": path.name}) from exc
    if not isinstance(value, dict):
        raise ToolError(code, "生产 JSON 顶层必须是对象。", details={"file": path.name})
    return value


def _write_copy(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.{uuid.uuid4().hex}.tmp")
    try:
        # Production, result and publish staging folders normally live on the
        # same NTFS volume.  A hard link keeps the package contract while the
        # video bytes remain stored only once.  Cross-volume and unsupported
        # filesystems safely fall back to a real copy.
        os.link(source, temporary)
    except OSError:
        shutil.copyfile(source, temporary)
    os.replace(temporary, destination)


def _asset(path: Path, root: Path, asset_id: str, media_type: str, **extra: Any) -> dict[str, Any]:
    result = {
        "assetId": asset_id,
        "relativePath": path.relative_to(root).as_posix(),
        "mediaType": media_type,
        "sizeBytes": path.stat().st_size,
        "sha256": _sha256_file(path),
    }
    result.update(extra)
    return result


def _contract_ref(contract: dict[str, Any]) -> dict[str, Any]:
    return {
        "targetContractType": contract["contractType"],
        "targetId": contract["id"],
        "targetVersion": contract["version"],
        "targetSchemaVersion": contract["schemaVersion"],
        "targetHash": contract["contentHash"],
    }


def _source_ref(value: dict[str, Any], *, field: str, expected_contract_type: str | None = None) -> dict[str, Any]:
    """Normalize either a full canonical contract or an existing source ref.

    Production Package 2.1 stores references, not complete contracts.  Passing
    a complete Production Profile through unchanged used to make the Workshop
    decoder drop ``contentHash`` (it expects ``targetHash``), which then caused
    ``PRODUCTION_PACKAGE_V21_SOURCE_LOCK_INVALID: productionPreset``.
    """

    if not isinstance(value, dict):
        raise ToolError("PRODUCTION_SOURCE_LOCK_INVALID", f"{field} 必须是版本化合同或来源引用。")
    if all(key in value for key in ("contractType", "id", "version", "schemaVersion", "contentHash")):
        if expected_contract_type and value.get("contractType") != expected_contract_type:
            raise ToolError(
                "PRODUCTION_SOURCE_LOCK_INVALID",
                f"{field} 合同类型不正确。",
                details={"expected": expected_contract_type},
            )
        if canonical_hash(value) != value.get("contentHash"):
            raise ToolError("PRODUCTION_SOURCE_LOCK_INVALID", f"{field} canonical-json-v1 哈希无效。")
        return _contract_ref(value)

    identifier = value.get("targetId") or value.get("id")
    version = value.get("targetVersion") or value.get("version")
    source_hash = value.get("targetHash") or value.get("hash")
    if (
        not isinstance(identifier, str)
        or not identifier.strip()
        or not isinstance(version, str)
        or not version.strip()
        or not isinstance(source_hash, str)
        or re.fullmatch(r"[0-9a-fA-F]{64}", source_hash.strip()) is None
    ):
        raise ToolError("PRODUCTION_SOURCE_LOCK_INVALID", f"{field} 缺少有效 ID、版本或 SHA-256。")
    contract_type = value.get("targetContractType")
    schema_version = value.get("targetSchemaVersion")
    if expected_contract_type and contract_type not in {None, "", expected_contract_type}:
        raise ToolError(
            "PRODUCTION_SOURCE_LOCK_INVALID",
            f"{field} 引用类型不正确。",
            details={"expected": expected_contract_type},
        )
    result = {
        "targetId": identifier.strip(),
        "targetVersion": version.strip(),
        "targetHash": source_hash.strip().lower(),
    }
    if isinstance(contract_type, str) and contract_type.strip():
        result["targetContractType"] = contract_type.strip()
    if isinstance(schema_version, str) and schema_version.strip():
        result["targetSchemaVersion"] = schema_version.strip()
    return result


def _read_contract(path: Path, expected_type: str) -> tuple[dict[str, Any], Path]:
    manifest_path = path / "manifest.json" if path.is_dir() else path
    contract = _read_json(manifest_path, "PRODUCTION_UPSTREAM_INVALID")
    if contract.get("contractType") != expected_type:
        raise ToolError("PRODUCTION_UPSTREAM_TYPE_INVALID", "上游包类型不正确。", details={"expected": expected_type})
    if canonical_hash(contract) != contract.get("contentHash"):
        raise ToolError("PRODUCTION_UPSTREAM_HASH_MISMATCH", "上游包 canonical-json-v1 哈希无效。")
    return contract, manifest_path.parent


def _assert_confirmation(contract: dict[str, Any], expected_status: str, gate: str) -> None:
    confirmation = contract.get("confirmation")
    if contract.get("status") != expected_status or not isinstance(confirmation, dict):
        raise ToolError("PRODUCTION_UPSTREAM_NOT_CONFIRMED", "上游包尚未达到确认状态。")
    if confirmation.get("status") != "APPROVED" or confirmation.get("gate") != gate:
        raise ToolError("PRODUCTION_UPSTREAM_NOT_CONFIRMED", "上游包确认门无效。")


def _validate_descriptor(root: Path, descriptor: dict[str, Any], *, code: str) -> Path:
    relative = _safe_relative(descriptor.get("relativePath"), "relativePath")
    path = _ensure_within(root, root / relative, "asset")
    if not path.is_file():
        raise ToolError(code, "上游资产不存在。", details={"path": relative.as_posix()})
    if path.stat().st_size != descriptor.get("sizeBytes") or _sha256_file(path) != descriptor.get("sha256"):
        raise ToolError(code, "上游资产大小或 SHA-256 不匹配。", details={"path": relative.as_posix()})
    return path


def _voice_catalog_document(path: Path) -> tuple[dict[str, Any], str, str]:
    document = _read_json(path, "PRODUCTION_VOICE_CATALOG_INVALID")
    if document.get("schemaVersion") != "1.0.0" or not isinstance(document.get("engines"), list):
        raise ToolError("PRODUCTION_VOICE_CATALOG_INVALID", "音色目录版本或结构不受支持。")
    if contains_sensitive_material(document):
        raise ToolError("PRODUCTION_VOICE_CATALOG_UNSAFE", "音色目录包含敏感字段。")
    declared = document.get("contentHash")
    computed = canonical_hash(document) if isinstance(declared, str) else _sha256_file(path)
    if declared is not None and declared != computed:
        raise ToolError("PRODUCTION_VOICE_CATALOG_HASH_MISMATCH", "音色目录内容哈希无效。")
    version = document.get("version") or document["schemaVersion"]
    return document, version, computed


def _validate_locked_voices(
    manuscript: dict[str, Any],
    catalog: dict[str, Any],
    catalog_version: str,
    catalog_hash: str,
    *,
    selected_engine_id: str,
) -> dict[str, dict[str, Any]]:
    available: set[tuple[str, str]] = set()
    for engine in catalog["engines"]:
        if not isinstance(engine, dict) or not engine.get("installed", True):
            continue
        for voice in engine.get("voices", []):
            if isinstance(voice, dict):
                available.add((str(engine.get("engineId")), str(voice.get("voiceId"))))
    bindings: dict[str, dict[str, Any]] = {}
    for voice in manuscript.get("voices", []):
        engine = voice.get("engine") or voice.get("engineId")
        voice_id = voice.get("voiceId")
        if engine != selected_engine_id:
            raise ToolError(
                "PRODUCTION_VOICE_ENGINE_MISMATCH",
                "人物旁白与对白只能使用本次用户确认的配音引擎，不能跨引擎推荐或锁定音色。",
                details={
                    "speakerId": voice.get("speakerId"),
                    "selectedEngineId": selected_engine_id,
                    "actualEngineId": engine,
                },
            )
        if (engine, voice_id) not in available:
            raise ToolError(
                "PRODUCTION_VOICE_UNKNOWN",
                "锁定音色不在当前版本化目录中。",
                details={"speakerId": voice.get("speakerId"), "engineId": engine, "voiceId": voice_id},
            )
        if voice.get("catalogVersion") != catalog_version or voice.get("catalogHash") != catalog_hash:
            raise ToolError("PRODUCTION_VOICE_CATALOG_MISMATCH", "锁定音色与当前目录版本或哈希不一致。")
        bindings[str(voice.get("speakerId"))] = {
            "engineId": engine,
            "voiceId": voice_id,
            "voiceName": voice.get("voiceName", voice_id),
            "catalogVersion": catalog_version,
            "catalogHash": catalog_hash,
        }
    speakers = {
        line.get("speakerId")
        for line in manuscript.get("targetScript", {}).get("lines", [])
        if line.get("lineType") in {"narration", "dialogue"}
    }
    missing = sorted(str(value) for value in speakers if value not in bindings)
    if missing:
        raise ToolError("PRODUCTION_VOICE_BINDING_MISSING", "部分正式文稿说话人没有锁定音色。", details={"speakers": missing})
    return bindings


def _package_hash_input(manifest: dict[str, Any]) -> dict[str, Any]:
    return {
        key: manifest[key]
        for key in (
            "schemaVersion",
            "packageType",
            "packageVersion",
            "productionPackageId",
            "projectId",
            "status",
            "synthetic",
            "files",
            "manifestSelfExcluded",
        )
    }


def production_package_hash(manifest: dict[str, Any]) -> str:
    return _sha256_bytes(_canonical_bytes(_package_hash_input(manifest)))


def _production_overview_markdown(
    *,
    manuscript: dict[str, Any],
    publishing: dict[str, Any],
    production_config: dict[str, Any],
    production_preset: dict[str, Any],
    package_path: Path,
    package_hash: str,
    review_documents: dict[str, Any],
) -> str:
    def cell(value: Any) -> str:
        return str(value).replace("|", "\\|").replace("\r", " ").replace("\n", "<br>")

    video = production_config["videoGeneration"]
    review_by_id = {item["documentId"]: item for item in review_documents.get("documents", [])}
    target_review = review_by_id["final-script-target"]
    chinese_review = review_by_id["final-script-zh"]
    machine_script_path = package_path / "script_lines.json"
    machine_script_hash = _sha256_file(machine_script_path) if machine_script_path.is_file() else "尚未生成"
    lines = [
        "# 完整生产资料总览",
        "",
        f"- 项目：`{manuscript['projectId']}`",
        f"- 目标语言：`{manuscript['targetLanguage']}`",
        f"- 分集：{manuscript['episodeCount']}",
        f"- 配音行数：{manuscript['lineCount']}",
        f"- 正式标题：{publishing['title']}",
        f"- 中文标题：{publishing['titleZhTranslation']}",
        f"- 生产模式：`{production_config['productionMode']['id']}`（{PRODUCTION_MODE_LABELS.get(production_config['productionMode']['id'], '兼容模式')}）",
        f"- 制作方式：`{production_config['deliveryMode']}`",
        f"- 人物配音引擎：`{production_config['voiceTtsProfile']['engineId']}`（只从该引擎推荐并锁定当前项目音色）",
        (
            f"- 纯音效：`开启`；固定 `seed_audio`；每条显式时长且不超过 {production_config['soundEffects']['maxDurationSeconds']:.0f} 秒"
            if production_config["soundEffects"]["enabled"]
            else "- 纯音效：`关闭`（用户本次选择）；不加载 Seed Audio，正式稿不含 sound_effect 行。"
        ),
        f"- 图片风格预设：`{production_config['imageStyle']['presetId']}`",
        f"- 图片风格提示词：{production_config['imageStyle']['prompt']}",
        f"- 剧情图片文字策略：`{production_config['storyImageTextPolicy']}`（角色图、分镜图和宫格图禁止可读文字；正式封面不受此项限制）",
        f"- 视频生成范围：`{video['selectionMode']}`",
        f"- 视频失败策略：`{video['fallbackPolicy']}`",
        f"- 图片覆盖节奏：`{production_config['sceneImageCadence']['mode']}`（本次用户选择并冻结）",
        f"- Production Package：`{package_path}`",
        f"- Package SHA-256：`{package_hash}`",
        "",
        "## 正式口播稿与中文审核稿",
        "",
        f"- **唯一用于配音、字幕和分镜的正式口播稿**：`{target_review['absolutePath']}`",
        f"- 正式口播稿 SHA-256：`{target_review['sha256']}`",
        f"- 正式口播稿内容绑定：`{manuscript['targetScript']['contentHash']}`",
        f"- 工坊机器输入：`{machine_script_path}`",
        f"- 工坊机器输入 SHA-256：`{machine_script_hash}`",
        f"- 中文审核稿（禁止生产）：`{chinese_review['absolutePath']}`",
        f"- 中文审核稿 SHA-256：`{chinese_review['sha256']}`",
        "- 绑定状态：`PASSED`；07 正式稿与 `script_lines.json` 来自同一组目标语言结构化行。",
        "",
        "## 配音与角色",
        "",
        "| 角色 | 目标语言姓名 | 功能 | 音色引擎 | 音色 | 角色形象提示词 |",
        "|---|---|---|---|---|---|",
    ]
    voices = {item["speakerId"]: item for item in manuscript.get("voices", [])}
    for character in manuscript.get("characters", []):
        voice = voices.get(character["characterId"], {})
        lines.append(
            "| {id} | {name} | {role} | {engine} | {voice} | {visual} |".format(
                id=cell(character["characterId"]),
                name=cell(character["targetLanguageName"]),
                role=cell(character["role"]),
                engine=cell(voice.get("engine", "未绑定")),
                voice=cell(voice.get("voiceName", "未绑定")),
                visual=cell(character.get("visualAnchorPromptZh", "不要求持续视觉一致性")),
            )
        )
    lines.extend(
        [
            "",
            "## 工坊正式输入",
            "",
            "- `script_lines.json`：唯一目标语言配音与字幕文本，包含 lineId、说话人、类型和情绪。",
            "- `characters.json`：角色身份、关系、形象锚点和锁定音色。",
            "- `episodes.json`：分集与正式文稿行映射。",
            "- `production_config.json`：画幅、分辨率、并发、视频范围和失败策略。",
            "- 人物语音不设固定行时长上限，也不会因配音时长自动拆分分镜；同一视觉时刻的多行可共用一幅画面。",
            (
                "- 纯音效已开启：不生成独立画面，使用 Seed Audio 后与相邻旁白或对白混合；背景音乐不属于音效。"
                if production_config["soundEffects"]["enabled"]
                else "- 纯音效已关闭：只处理旁白与对白，不创建或混合音效资产。"
            ),
            "- `publishing.json`：目标语言标题、简介、Hashtags、频道和上传策略。",
            (
                "- `confirmed_thumbnail.png`：用户明确要求并确认的 16:9 自定义封面。"
                if publishing.get("thumbnail", {}).get("mode") == "real_file"
                else "- 自定义封面：未请求；生产包不生成封面，上传时使用 YouTube 自动缩略图。"
            ),
            "",
            "## 发布信息",
            "",
            publishing["descriptionBody"].rstrip(),
            "",
            " ".join(publishing["hashtags"]),
            "",
            f"- 发布频道序号：`{publishing.get('targetChannel', {}).get('channelSerial', '未设置')}`",
            f"- 上传策略：`{publishing.get('uploadPolicy', production_preset.get('uploadPolicy', 'REQUIRE_REVIEW'))}`",
            "",
            "> 中文审核稿只供用户检查，不进入工坊配音、字幕或分镜生产。",
            "",
        ]
    )
    return "\n".join(lines)


def _codex_visual_plan_markdown(plan: dict[str, Any], characters: list[dict[str, Any]]) -> str:
    character_names = {item.get("characterId"): item.get("targetLanguageName", item.get("characterId", "")) for item in characters}
    lines = [
        "# Codex 角色设计与分镜提示词方案",
        "",
        f"- 方案版本：`{plan['schemaVersion']}`",
        f"- 图片风格：`{plan['stylePresetId']}`",
        f"- 风格提示词 SHA-256：`{plan['stylePromptSha256']}`",
        f"- 角色参考图用途：`{plan['referenceUsage']}`（只锁身份，不锁表情、视线、姿势、构图与背景）",
        "- 视觉导演：单幅漫画、单一视觉焦点、剧情驱动夸张表演、冲击等级自适应背景减法。",
        f"- 方案 SHA-256：`{plan['contentHash']}`",
        "",
        "## 漫画角色设计",
        "",
    ]
    for item in plan.get("characterDesigns", []):
        character_id = item["characterId"]
        lines.extend(
            [
                f"### {character_names.get(character_id, character_id)}（`{character_id}`）",
                "",
                f"- 人物／外观阶段：`{item['personId']}` → `{item['appearanceId']}`；人生阶段 `{item['lifePhase']}`；年龄阶段 `{item['ageStage']}`。",
                f"- 参考图策略：`{item['referencePolicy']}`；实际用途 `{item['referenceUsage']}`。",
                f"- 设计意图：{item['designIntentZh']}",
                f"- 身份锚点：{item['identityAnchorPromptZh']}",
                f"- 角色参考图提示词：{item['referenceSheetPromptZh'] or '无（本阶段直接按文字生图）'}",
                f"- 分镜身份短锚点：{item['storyboardIdentityPromptZh']}",
                f"- 固定特征：{'、'.join(item['fixedFeatures'])}",
                f"- 分镜可变项：{'、'.join(item['flexibleFeatures'])}",
                "",
            ]
        )
    series_plan = plan["seriesVisualPlan"]
    story_plan = plan["storyVisualPlan"]
    lines.extend(
        [
            "## 故事画面规划",
            "",
            f"- 规划顺序：`{series_plan['planningMode']}`；已读取全部集数：{series_plan['episodeNumbers']}。",
            f"- 全剧时间线：{series_plan['timelineSummaryZh']}",
            f"- 跨集连续性：{series_plan['crossEpisodeContinuityZh']}",
            f"- 开篇钩子分镜：`{story_plan['openingHookSceneId']}`",
            f"- 关系／核心矛盾分镜：`{'`、`'.join(story_plan['relationshipConflictSceneIds'])}`",
            f"- 剧情复杂度：{story_plan['complexityLevel']}/5",
            f"- 自适应页数：{story_plan['plannedPageCount']}；{story_plan['pageCountRationaleZh']}",
            f"- 提示词预算：图片建议 {story_plan['promptCompiler']['imagePromptSoftMinChars']}–{story_plan['promptCompiler']['imagePromptSoftMaxChars']} 字符，硬上限 {story_plan['promptCompiler']['imagePromptMaxChars']}；视频 ≤ {story_plan['promptCompiler']['videoPromptMaxChars']} 字符",
            "",
            "| 节拍 | 类型 | 来源正式稿 | 承载分镜 | 说明 |",
            "|---|---|---|---|---|",
        ]
    )
    for beat in story_plan["storyBeats"]:
        lines.append(
            f"| `{beat['beatId']}` | `{beat['type']}` | {', '.join(beat['sourceLineIds'])} | {', '.join(beat['sceneIds'])} | {beat['summaryZh']} |"
        )
    lines.extend(["", "## 配音行到语义画面组", "", "| 画面组 | 正式稿行 | 决策 | 与上一组边界 | 唯一视觉时刻 |", "|---|---|---|---|---|"])
    for group in story_plan["semanticBeatGroups"]:
        lines.append(
            f"| `{group['groupId']}` | {', '.join(group['sourceLineIds'])} | `{group['decision']}`／`{group['reason']}` | `{group['boundaryFromPrevious']}` | {group['visualMomentZh']}（{group['decisionReasonZh']}） |"
        )
    lines.extend(["", "## 连续场景段", ""])
    for sequence in story_plan["visualSequences"]:
        lines.extend(
            [
                f"### 第 {sequence['episodeNumber']} 集 · `{sequence['sequenceId']}`",
                "",
                f"- 地点／分镜：`{sequence['locationId']}`；{'、'.join(sequence['sceneIds'])}",
                f"- 时间与光线：{sequence['timeLightingZh']}",
                f"- 色彩与反差：{sequence['paletteContrastZh']}",
                f"- 空间轴线：{sequence['spatialAxisZh']}",
                f"- 首尾状态：`{sequence['openingStateId']}` → `{sequence['closingStateId']}`；{sequence['continuityFromPreviousZh']}",
                f"- 镜头梯度：{' → '.join(sequence['shotLadder'])}",
                f"- 冲击曲线：{' → '.join(str(level) for level in sequence['impactArc'])}",
                "",
            ]
        )
    lines.extend(["", "## 连续性圣经", ""])
    for label, field, id_field in (("地点", "locations", "locationId"), ("服装", "costumes", "costumeId"), ("道具", "props", "propId")):
        entries = plan["continuityBible"][field]
        lines.append(f"- {label}：" + ("；".join(f"`{entry[id_field]}` {entry['nameZh']}（{'、'.join(entry['fixedFeatures'])}）" for entry in entries) or "无"))
    lines.append("")
    lines.extend(["## 分镜图片／视频提示词", ""])
    for item in plan.get("scenePlans", []):
        performance = item["performance"]
        manga_composition = item["mangaComposition"]
        continuity_state = item["continuityState"]
        facial_acting = item.get("facialActing", {})
        body_acting = item.get("bodyActing", {})
        combat_direction = item.get("combatDirection", {"active": False, "phase": "none"})
        visible_names = [character_names.get(character_id, character_id) for character_id in item.get("visibleCharacterIds", [])]
        lines.extend(
            [
                f"### 第 {item['episodeNumber']} 集 · 分镜 {item['sequence']}（`{item['sceneId']}`）",
                "",
                f"- 正式稿行：`{'`, `'.join(item['scriptLineIds'])}`",
                f"- 语义画面组：`{item['semanticGroupId']}`（先合并相邻短行，再应用连续性和单镜合同）",
                f"- 连续场景／镜头功能：`{item['sequenceId']}`／`{item['shotRole']}`",
                f"- 出镜角色：{'、'.join(visible_names) if visible_names else '无人出镜'}",
                f"- 剧情功能／复杂度：`{item['narrativeFunction']}`；{item['complexityScore']}/5",
                f"- 漫画冲击等级：{item['impactLevel']}/5；表情夸张度：{item['expressionExaggeration']}/5。",
                f"- 镜头：`{item['shot']['scale']}`／`{item['shot']['angle']}`／`{item['shot']['view']}`；调度 `{item['shot']['dialogueStaging']}`；焦点 {item['shot']['focalPointZh']}；层次 {item['shot']['depthCompositionZh']}；海报构图 {item['shot']['posterCompositionZh']}。",
                f"- 单幅漫画导演：核心瞬间 {manga_composition['coreMomentZh']}；唯一焦点 {manga_composition['singleVisualFocusZh']}；主动作 {manga_composition['primaryActionZh']}；互动 {manga_composition['interactionZh']}；构图 {manga_composition['shotDesignZh']}。",
                f"- 冲击与减法：手法 {'、'.join(manga_composition['mangaDevices']) or '无'}；背景 `{manga_composition['backgroundMode']}`，{manga_composition['backgroundTreatmentZh']}；连续性 {manga_composition['continuityEssentialsZh']}；杂乱控制 {manga_composition['clutterControlZh']}。",
                f"- 脱离文字可读：{item['visualReadability']['storyInformationZh']}；关系 {item['visualReadability']['relationshipCueZh']}；因果／矛盾 {item['visualReadability']['conflictOrCauseEffectCueZh']}。",
                f"- 情绪爆点：`{item['emotionalBeat']['category']}`；可见信号：{'、'.join(item['emotionalBeat']['visualSignals']) or '无'}。",
                f"- 连续性：地点 `{item['continuity']['locationId']}`；服装 {item['continuity']['costumeIdsByCharacter']}；道具 {item['continuity']['propIds']}；{item['continuity']['changeJustificationZh']}。",
                f"- 状态链：`{continuity_state['entryStateId']}` → `{continuity_state['exitStateId']}`；进入 {continuity_state['entryStateZh']}；离开 {continuity_state['exitStateZh']}。",
                f"- 空间承接：站位 {continuity_state['characterBlockingZh']}；运动方向 {continuity_state['screenDirectionZh']}；视线 {continuity_state['eyelineZh']}；道具 {continuity_state['propStateZh']}；光线 {continuity_state['lightingStateZh']}；承接上一镜 `{continuity_state['carryOverFromSceneId'] or '无（本集首镜）'}`。",
                f"- 表演：内在情绪“{performance['internalEmotion']}”，外显“{performance['visibleEmotion']}”，强度 {performance['intensity']}/5；视线 {performance['gaze']}；眼睛 {performance['eyes']}；眉形 {performance['brows']}；嘴形 {performance['mouth']}；头部 {performance['headPose']}；身体 {performance['bodyPose']}；手势 {performance['handGesture']}；互动对象 {performance['interactionTarget']}；相对上一镜 {performance['changeFromPrevious']}。",
                (
                    f"- 漫画面部表演：眼形 {facial_acting['eyeShapeZh']}；瞳孔 {facial_acting['pupilZh']}；眉形 {facial_acting['browZh']}；口部与下颌 {facial_acting['mouthJawZh']}；面部张力 {facial_acting['faceTensionZh']}；夸张手法 {facial_acting['exaggerationTechniqueZh']}。"
                    if facial_acting else "- 漫画面部表演：无人镜头，不适用。"
                ),
                (
                    f"- 漫画肢体表演：动作线 {body_acting['lineOfActionZh']}；重心 {body_acting['centerOfGravityZh']}；肩背 {body_acting['shoulderSpineZh']}；手部张力 {body_acting['handTensionZh']}；次级运动 {body_acting['secondaryMotionZh']}。"
                    if body_acting else "- 漫画肢体表演：无人镜头，不适用。"
                ),
                (
                    f"- 战斗特效：阶段 `{combat_direction['phase']}`；冻结瞬间 {combat_direction['frozenMomentZh']}；来源 {combat_direction['effectSourceZh']}；轨迹 {combat_direction['trajectoryZh']}；接触点 {combat_direction['impactPointZh']}；形态与色彩 {combat_direction['effectShapeColorZh']}；尺度分层 {combat_direction['scaleLayeringZh']}；粒子与碎屑 {combat_direction['particlesDebrisZh']}；环境反馈 {combat_direction['environmentalResponseZh']}；光影交互 {combat_direction['lightingInteractionZh']}；攻方动力 {combat_direction['attackerKineticsZh']}；守方反应 {combat_direction['defenderResponseZh']}；安全边界 {combat_direction['safetyBoundaryZh']}。"
                    if combat_direction.get("active") else "- 战斗特效：本镜不适用。"
                ),
                f"- 编译后的战斗特效组件：{item['promptComponents']['battleEffectsZh'] or '本镜不适用'}",
                f"- 图片提示词：{item['imagePromptZh'] or '本次未启用'}",
                f"- 视频提示词：{item['videoPromptZh'] or '本次未启用'}",
                "",
            ]
        )
    lines.append("> 本文档用于用户查看与工坊执行对照；角色参考图只锁身份，不把参考图里的中性表情复制到剧情分镜。")
    lines.append("")
    return "\n".join(lines)


class ProductionCenter:
    """Authoritative Stage-5 package, task, media validation, and result boundary."""

    def __init__(
        self,
        data_root: Path,
        *,
        plugin_root: Path | None = None,
        voice_catalog_path: Path | None = None,
        ffmpeg_path: Path | str | None = None,
        ffprobe_path: Path | str | None = None,
        workshop_bridge: Any | None = None,
    ) -> None:
        self.data_root = data_root.resolve()
        self.root = self.data_root / "production"
        self.plugin_root = plugin_root.resolve() if plugin_root else None
        self.voice_catalog_path = voice_catalog_path.resolve() if voice_catalog_path else None
        self.ffmpeg_path = str(ffmpeg_path or os.environ.get("AIVCP_FFMPEG_PATH") or shutil.which("ffmpeg") or "")
        self.ffprobe_path = str(ffprobe_path or os.environ.get("AIVCP_FFPROBE_PATH") or shutil.which("ffprobe") or "")
        self.workshop_bridge = workshop_bridge

    def capabilities(self) -> dict[str, Any]:
        return {
            "version": PRODUCTION_CENTER_VERSION,
            "contracts": {
                "productionPackage": PRODUCTION_PACKAGE_SCHEMA_VERSION,
                "productionTask": PRODUCTION_TASK_SCHEMA_VERSION,
                "productionResultPackage": PRODUCTION_RESULT_SCHEMA_VERSION,
                "jianyingDraftPackage": "1.0.0",
            },
            "steps": [step_id for step_id, _, _ in STEP_DEFINITIONS],
            "deliveryModes": ["auto_render", "jianying_refine"],
            "productionModes": {
                "selectionRequiredEveryNewProduction": True,
                "inheritedDefault": None,
                "recommended": "balanced",
                "modeOnlySelectsPromptAuthorAndRecommendedDefaults": True,
                "deliveryModeAlwaysUserSelectable": True,
                "shotVideoAlwaysUserSelectable": True,
                "sceneImageCadenceAlwaysUserSelectable": True,
                "items": [
                    {
                        "id": "fast_auto",
                        "displayNameZh": PRODUCTION_MODE_LABELS["fast_auto"],
                        "codexVisualPlan": False,
                        "workshopImagePromptAnalysis": False,
                        "shotVideo": "explicit_scope_only",
                        "deliveryModes": ["auto_render", "jianying_refine"],
                    },
                    {
                        "id": "balanced",
                        "displayNameZh": PRODUCTION_MODE_LABELS["balanced"],
                        "codexVisualPlan": False,
                        "workshopImagePromptAnalysis": True,
                        "shotVideo": "explicit_scope_only",
                        "deliveryModes": ["auto_render", "jianying_refine"],
                    },
                    {
                        "id": "director",
                        "displayNameZh": PRODUCTION_MODE_LABELS["director"],
                        "codexVisualPlan": True,
                        "workshopImagePromptAnalysis": False,
                        "shotVideo": "explicit_scope_only",
                        "deliveryModes": ["auto_render", "jianying_refine"],
                    },
                ],
            },
            "videoSelectionModes": sorted(VIDEO_SELECTION_MODES),
            "sceneImageCadenceModes": sorted(SCENE_IMAGE_CADENCE_MODES),
            "productionConcurrency": {"minimum": 1, "maximum": MAX_PRODUCTION_CONCURRENCY, "recommendedImage": 20},
            "gridBatch": {"globalTemplate": True, "episodeTemplateOverrides": True},
            "workshopScheduling": {
                "singleton": True,
                "machineWideOwner": True,
                "crossProjectParallelism": False,
                "busyBehavior": "queued_waiting_workshop",
                "sameRequestJoin": True,
            },
            "localProductionQueue": {
                "schemaVersion": QUEUE_SCHEMA_VERSION,
                "appliesTo": "new_non_synthetic_tasks_only",
                "dispatchMode": "persistent_local_event",
                "wakeSources": ["task_enqueued", "task_resumed", "task_retry_requested", "workshop_filesystem_change"],
                "crashRecoveryWatchdogSeconds": 60,
                "codexHeartbeatDrivesProduction": False,
                "scheduledRetryDrivesProduction": False,
                "oldTasksMigrated": False,
            },
            "audioRouting": {
                "humanVoiceEngineSelectedByUser": True,
                "recommendVoicesFromSelectedEngineOnly": True,
                "speakerBindingScope": "current_project",
                "soundEffectsSelectedByUserEveryProduction": True,
                "soundEffectsMayBeDisabled": True,
                "soundEffectEngineLoadedOnlyWhenEnabled": True,
                "pureSpeechFirstLineAllowedWhenDisabled": True,
                "soundEffectEngine": "seed_audio",
                "soundEffectExplicitDurationRequired": True,
                "soundEffectMaxDurationSeconds": SOUND_EFFECT_MAX_DURATION_SECONDS,
                "soundEffectCategoryDurationWindows": True,
                "soundEffectActiveAudioGate": True,
                "soundEffectIncompleteAutoRetry": True,
                "backgroundMusicTreatedAsSoundEffect": False,
            },
            "codexVisualPlan": {
                "schemaVersion": CODEX_VISUAL_PLAN_SCHEMA_VERSION,
                "characterDesign": True,
                "logicalPersonAppearanceStages": True,
                "sceneAppearanceBindingRequired": True,
                "textOnlyChildAppearanceAllowed": True,
                "crossLifeReferenceReuseForbidden": True,
                "sceneImagePrompts": True,
                "sceneVideoPrompts": True,
                "scenePerformance": True,
                "storyVisualPlanning": True,
                "complexityAdaptivePageCount": True,
                "semanticSceneGrouping": True,
                "semanticGroupingMode": CODEX_SEMANTIC_GROUPING_MODE,
                "semanticGroupingBeforeContinuity": True,
                "ttsLineBreakCreatesScene": False,
                "lineCountHardCap": False,
                "speechDurationMaySplitStoryboard": False,
                "soundEffectStandaloneStoryboard": False,
                "cameraCompositionContract": True,
                "criticalEmotionVisualSignals": True,
                "continuityBible": True,
                "mangaImpactDirection": True,
                "singlePanel": True,
                "singleVisualFocus": True,
                "exaggeratedFacialActing": True,
                "bodyLineOfAction": True,
                "adaptiveBackgroundSimplification": True,
                "clutterControl": True,
                "fullSeriesContext": True,
                "visualSequencePlanning": True,
                "continuityStateChain": True,
                "temporalSequenceInSingleImageForbidden": True,
                "combatEffectsContract": True,
                "combatSinglePhasePerStill": True,
                "combatKeyMomentsOnly": True,
                "combatAllPhasesRequired": False,
                "combatPhaseChangeMayForceStoryboard": False,
                "combatIntermediatePhasesMayBeOmitted": True,
                "nonGraphicCombatEffectsPreserved": True,
                "failedPromptRepairScope": CODEX_FAILURE_REPAIR_SCOPE,
                "atomicImageReplacement": True,
                "mangaDeviceLimit": CODEX_VISUAL_DIRECTION["mangaDeviceLimit"],
                "placeholderContentRejected": True,
                "imagePromptSoftMinimumEnforced": True,
                "imagePromptMinimumUniqueRatio": CODEX_IMAGE_PROMPT_MINIMUM_UNIQUE_RATIO,
                "mechanicalLineGroupingRejected": True,
                "shotRoleBalanceGate": True,
                "impactArcGate": True,
                "promptComponentGroundingRequired": True,
                "sceneCostumeGroundingRequired": True,
                "storyPromptPrecedesReferenceMaterial": True,
                "costumeOverrideSuppressesFullBodyReference": True,
                "promptBudgets": {
                    "imageSoftMinChars": CODEX_IMAGE_PROMPT_SOFT_MINIMUM,
                    "imageSoftMaxChars": CODEX_IMAGE_PROMPT_SOFT_MAXIMUM,
                    "imageMaxChars": CODEX_IMAGE_PROMPT_MAXIMUM,
                    "videoMaxChars": CODEX_VIDEO_PROMPT_MAXIMUM,
                },
                "referenceUsage": CODEX_REFERENCE_USAGE,
                "workshopMayRewriteLockedPrompts": False,
                "postGenerationVisualAudit": False,
                "autoRenderMotion": {
                    "minimumFamiliesForTwelveStills": 5,
                    "adjacentFamilyRepeatForbidden": True,
                    "zoomAmplitude": {"low": 1.10, "medium": 1.16, "high": 1.22},
                    "speedMultiplier": {"low": 1.40, "medium": 1.62, "high": 1.85},
                },
            },
            "ffmpegAvailable": bool(self.ffmpeg_path and Path(self.ffmpeg_path).is_file()),
            "ffprobeAvailable": bool(self.ffprobe_path and Path(self.ffprobe_path).is_file()),
            "workshopBridgeConfigured": self.workshop_bridge is not None,
            "boundaries": {
                "publishingPackage": False,
                "readyPackage": False,
                "publisherCenter": False,
                "oauth": False,
                "upload": False,
                "analytics": False,
                "longTermLearningWrite": False,
            },
        }

    def _package_index_path(self, project_id: str) -> Path:
        return self.root / "packages" / project_id / "package-index.json"

    def _package_file_descriptors(self, root: Path) -> list[dict[str, Any]]:
        media_types = {
            ".json": "application/json",
            ".png": "image/png",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".webp": "image/webp",
        }
        descriptors = []
        for path in sorted((item for item in root.rglob("*") if item.is_file() and item.name != "manifest.json"), key=lambda item: item.relative_to(root).as_posix()):
            descriptors.append(
                {
                    "path": path.relative_to(root).as_posix(),
                    "sizeBytes": path.stat().st_size,
                    "sha256": _sha256_file(path),
                    "mediaType": media_types.get(path.suffix.lower(), "application/octet-stream"),
                }
            )
        return descriptors

    def _next_package_version(self, project_id: str, identity_hash: str) -> tuple[str, Path | None]:
        index_path = self._package_index_path(project_id)
        if not index_path.is_file():
            return "1.0.0", None
        index = _read_json(index_path)
        for item in index.get("packages", []):
            if item.get("identityHash") == identity_hash:
                existing = Path(item["path"])
                if existing.is_dir():
                    return item["packageVersion"], existing
        versions = [item.get("packageVersion", "1.0.0") for item in index.get("packages", [])]
        patches = [int(version.split(".")[2]) for version in versions if re.fullmatch(r"1\.0\.\d+", version)]
        return f"1.0.{max(patches, default=-1) + 1}", None

    def assemble_package(
        self,
        *,
        manuscript_path: Path,
        publishing_path: Path,
        production_config: dict[str, Any],
        production_preset: dict[str, Any],
        workshop_compatibility: dict[str, Any],
        synthetic: bool = False,
    ) -> dict[str, Any]:
        if not isinstance(production_preset, dict) or not isinstance(workshop_compatibility, dict):
            raise ToolError("PRODUCTION_CONFIG_INVALID", "生产预设和工坊兼容声明必须是对象。")
        production_preset_ref = _source_ref(
            production_preset,
            field="productionPreset",
            expected_contract_type="production-profile",
        )
        if workshop_compatibility.get("interfaceVersion") != "2.1":
            raise ToolError("PRODUCTION_WORKSHOP_VERSION_UNSUPPORTED", "工坊兼容接口必须声明 2.1。")
        manuscript, manuscript_root = _read_contract(manuscript_path, "manuscript-package")
        publishing, publishing_root = _read_contract(publishing_path, "publishing-asset-package")
        user_project_root = manuscript_root.parents[1]
        _assert_confirmation(manuscript, "SCRIPT_READY", "G4_MANUSCRIPT")
        _assert_confirmation(publishing, "PUBLISHING_ASSETS_READY", "G5_PUBLISHING_ASSETS")
        if manuscript.get("projectId") != publishing.get("projectId"):
            raise ToolError("PRODUCTION_UPSTREAM_PROJECT_MISMATCH", "文稿包和发布素材包项目 ID 不一致。")
        if manuscript.get("channelProfileId") != publishing.get("channelProfileId"):
            raise ToolError("PRODUCTION_UPSTREAM_CHANNEL_MISMATCH", "文稿包和发布素材包频道 ID 不一致。")
        if manuscript.get("targetLanguage") != publishing.get("targetLanguage"):
            raise ToolError("PRODUCTION_UPSTREAM_LANGUAGE_MISMATCH", "文稿包和发布素材包目标语言不一致。")
        binding = publishing.get("manuscriptBinding", {}).get("manuscriptPackage", {})
        if binding.get("targetId") != manuscript.get("id") or binding.get("targetHash") != manuscript.get("contentHash"):
            raise ToolError("PRODUCTION_UPSTREAM_BINDING_MISMATCH", "发布素材包没有绑定当前文稿版本与哈希。")
        upstream = publishing.get("upstream", [])
        if not upstream or upstream[0].get("targetHash") != manuscript.get("contentHash"):
            raise ToolError("PRODUCTION_UPSTREAM_BINDING_MISMATCH", "发布素材包上游哈希无效。")
        target_script = manuscript.get("targetScript", {})
        quality_gate = manuscript.get("qualityGate", {})
        foreign_quality_gate = manuscript.get("foreignLanguageQualityGate", {})
        if not target_script.get("isSoleProductionSource") or target_script.get("role") != "target-language-production-master":
            raise ToolError("PRODUCTION_TARGET_SCRIPT_NOT_SOLE_SOURCE", "目标语言正式母稿不是唯一生产源。")
        if quality_gate.get("status") != "PASSED" or quality_gate.get("targetScriptHash") != target_script.get("contentHash"):
            raise ToolError("PRODUCTION_QUALITY_GATE_INVALID", "质量门未通过或未绑定当前正式母稿。")
        if publishing.get("manuscriptBinding", {}).get("qualityGateHash") != manuscript.get("qualityGateHash"):
            raise ToolError("PRODUCTION_QUALITY_GATE_INVALID", "发布素材包绑定了不同质量门。")
        expected_foreign_status = "NOT_APPLICABLE" if manuscript.get("targetLanguage", "").lower().startswith("zh") else "PASSED"
        if (
            foreign_quality_gate.get("status") != expected_foreign_status
            or foreign_quality_gate.get("targetScriptHash") != target_script.get("contentHash")
            or manuscript.get("foreignLanguageQualityGateHash") != foreign_quality_gate.get("contentHash")
            or publishing.get("manuscriptBinding", {}).get("foreignLanguageQualityGateHash")
            != manuscript.get("foreignLanguageQualityGateHash")
            or (
                expected_foreign_status == "PASSED"
                and (
                    foreign_quality_gate.get("reviewMode") != "independent-second-pass"
                    or foreign_quality_gate.get("independentFromAuthoring") is not True
                )
            )
        ):
            raise ToolError("PRODUCTION_FOREIGN_LANGUAGE_QUALITY_GATE_INVALID", "外语质量保险门缺失、未通过或没有绑定当前正式母稿。")
        target_lines = target_script.get("lines", [])
        audit_lines = (
            target_lines
            if manuscript.get("targetLanguage", "").lower().startswith("zh")
            else manuscript.get("auditScript", {}).get("lines", [])
        )
        try:
            expected_target_text = render_script_text(target_lines)
            expected_audit_text = render_script_text(audit_lines)
        except ValueError as exc:
            raise ToolError("PRODUCTION_TARGET_SCRIPT_INVALID", str(exc)) from exc
        review_view = review_documents_view(user_project_root)
        required_ids = [
            "rewrite-draft-target",
            "editorial-review",
            "revision-log",
            "final-script-target",
            "final-script-zh",
            "packaging-bilingual",
        ]
        if publishing.get("thumbnail", {}).get("mode") != "youtube_auto":
            required_ids.append("thumbnail-review")
        required_review_documents = tuple(
            dict.fromkeys([item["documentId"] for item in review_view["documents"]] + required_ids)
        )
        review_validation = validate_review_documents(user_project_root, required_review_documents)
        if review_validation["status"] != "PASS":
            raise ToolError(
                "PRODUCTION_REVIEW_DOCUMENTS_REQUIRED",
                "用户审核文档缺失、损坏或用途标记错误，不能组装生产包。",
                details={"errors": review_validation["errors"]},
            )
        topic_ref = manuscript.get("upstream", [{}])[0]
        review_binding_expectations = {
                "rewrite-draft-target": {
                    "sourceContractType": topic_ref.get("targetContractType"),
                    "sourceContractId": topic_ref.get("targetId"),
                    "sourceContentHash": topic_ref.get("targetHash"),
                },
                "editorial-review": {
                    "sourceContractType": topic_ref.get("targetContractType"),
                    "sourceContractId": topic_ref.get("targetId"),
                    "sourceContentHash": topic_ref.get("targetHash"),
                },
                "revision-log": {
                    "sourceContractType": topic_ref.get("targetContractType"),
                    "sourceContractId": topic_ref.get("targetId"),
                    "sourceContentHash": topic_ref.get("targetHash"),
                },
                "final-script-target": {
                    "content": expected_target_text,
                    "language": manuscript["targetLanguage"],
                    "productionUseAllowed": True,
                    "sourceContractType": manuscript["contractType"],
                    "sourceContractId": manuscript["id"],
                    "sourceContentHash": manuscript["contentHash"],
                },
                "final-script-zh": {
                    "content": expected_audit_text,
                    "language": "zh-CN",
                    "productionUseAllowed": False,
                    "sourceContractType": manuscript["contractType"],
                    "sourceContractId": manuscript["id"],
                    "sourceContentHash": manuscript["contentHash"],
                },
                "packaging-bilingual": {
                    "sourceContractType": publishing["contractType"],
                    "sourceContractId": publishing["id"],
                    "sourceContentHash": publishing["contentHash"],
                },
            }
        if publishing.get("thumbnail", {}).get("mode") != "youtube_auto":
            review_binding_expectations["thumbnail-review"] = {
                "sourceContractType": publishing["contractType"],
                "sourceContractId": publishing["id"],
                "sourceContentHash": publishing["contentHash"],
            }
        review_binding = validate_review_document_bindings(user_project_root, review_binding_expectations)
        if review_binding["status"] != "PASS":
            raise ToolError(
                "PRODUCTION_REVIEW_DOCUMENT_MISMATCH",
                "用户看到的正式口播稿或中文审核稿与机器文稿包不一致。",
                details={"errors": review_binding["errors"]},
            )
        target_asset = target_script.get("asset")
        if isinstance(target_asset, dict):
            target_asset_path = _validate_descriptor(manuscript_root, target_asset, code="PRODUCTION_TARGET_SCRIPT_ASSET_INVALID")
            target_asset_document = _read_json(target_asset_path)
            if target_asset_document.get("language") != manuscript.get("targetLanguage") or target_asset_document.get("lines") != target_lines:
                raise ToolError("PRODUCTION_TARGET_SCRIPT_ASSET_INVALID", "目标语言机器稿与文稿合同不一致。")
        else:
            raise ToolError("PRODUCTION_TARGET_SCRIPT_ASSET_INVALID", "目标语言机器稿缺少结构化资产。")
        target_text_asset = target_script.get("textAsset")
        if not isinstance(target_text_asset, dict):
            raise ToolError("PRODUCTION_TARGET_SCRIPT_ASSET_INVALID", "目标语言机器稿缺少可读文本资产。")
        target_text_path = _validate_descriptor(manuscript_root, target_text_asset, code="PRODUCTION_TARGET_SCRIPT_ASSET_INVALID")
        if target_text_path.read_text(encoding="utf-8-sig") != expected_target_text:
            raise ToolError("PRODUCTION_TARGET_SCRIPT_ASSET_INVALID", "目标语言机器文本与结构化正式稿不一致。")
        if not manuscript.get("targetLanguage", "").lower().startswith("zh"):
            audit_script = manuscript.get("auditScript", {})
            audit_text_asset = audit_script.get("textAsset")
            audit_asset = audit_script.get("asset")
            if not isinstance(audit_text_asset, dict) or not isinstance(audit_asset, dict):
                raise ToolError("PRODUCTION_CHINESE_AUDIT_ASSET_INVALID", "非中文正式稿缺少中文审核资产。")
            audit_text_path = _validate_descriptor(manuscript_root, audit_text_asset, code="PRODUCTION_CHINESE_AUDIT_ASSET_INVALID")
            audit_asset_path = _validate_descriptor(manuscript_root, audit_asset, code="PRODUCTION_CHINESE_AUDIT_ASSET_INVALID")
            audit_asset_document = _read_json(audit_asset_path)
            if audit_text_path.read_text(encoding="utf-8-sig") != expected_audit_text or audit_asset_document.get("lines") != audit_lines:
                raise ToolError("PRODUCTION_CHINESE_AUDIT_ASSET_INVALID", "中文审核机器资产与逐行映射不一致。")
        review_by_id = {item["documentId"]: item for item in review_view["documents"]}
        thumbnail = publishing.get("thumbnail", {})
        thumbnail_mode = thumbnail.get("mode")
        thumbnail_path: Path | None = None
        if thumbnail_mode == "real_file":
            if not isinstance(thumbnail.get("asset"), dict):
                raise ToolError("PRODUCTION_THUMBNAIL_INVALID", "自定义封面缺少真实文件资产。")
            thumbnail_path = _validate_descriptor(
                publishing_root, thumbnail["asset"], code="PRODUCTION_THUMBNAIL_INVALID"
            )
            if thumbnail.get("aspectRatio") != "16:9" or not thumbnail.get("hashVerified"):
                raise ToolError("PRODUCTION_THUMBNAIL_INVALID", "自定义封面比例或哈希确认无效。")
        elif thumbnail_mode != "youtube_auto":
            raise ToolError("PRODUCTION_THUMBNAIL_INVALID", "用户要求的自定义封面尚未完成。")
        if not self.voice_catalog_path or not self.voice_catalog_path.is_file():
            raise ToolError("PRODUCTION_VOICE_CATALOG_UNAVAILABLE", "没有可用的版本化音色目录。")
        catalog, catalog_version, catalog_hash = _voice_catalog_document(self.voice_catalog_path)
        config = self._validate_production_config(production_config)
        voice_bindings = _validate_locked_voices(
            manuscript,
            catalog,
            catalog_version,
            catalog_hash,
            selected_engine_id=config["voiceTtsProfile"]["engineId"],
        )
        sound_effect_lines = [line for line in target_lines if line.get("lineType") == "sound_effect"]
        if sound_effect_lines and not config["soundEffects"]["enabled"]:
            raise ToolError("PRODUCTION_SOUND_EFFECT_DISABLED", "正式配音稿含纯音效行，但本次制作设置没有开启音效生成。")
        if config["soundEffects"]["enabled"] and not sound_effect_lines:
            raise ToolError("PRODUCTION_SOUND_EFFECT_LINES_REQUIRED", "本次制作设置已开启纯音效，但正式配音稿没有任何纯音效行。")
        manuscript_sound_effects = manuscript.get("soundEffects")
        if (
            isinstance(manuscript_sound_effects, dict)
            and isinstance(manuscript_sound_effects.get("enabled"), bool)
            and manuscript_sound_effects["enabled"] != config["soundEffects"]["enabled"]
        ):
            raise ToolError(
                "PRODUCTION_SOUND_EFFECT_SELECTION_MISMATCH",
                "正式配音稿与本次制作设置的纯音效选择不一致，必须按用户本次选择重新冻结正式稿。",
            )
        for line in sound_effect_lines:
            if (
                line.get("speakerId") != "sfx"
                or line.get("audioEngine") != "seed_audio"
                or line.get("visualGenerationAllowed") is not False
                or not isinstance(line.get("durationSeconds"), (int, float))
                or isinstance(line.get("durationSeconds"), bool)
                or not 0 < float(line["durationSeconds"]) <= SOUND_EFFECT_MAX_DURATION_SECONDS
                or not str(line.get("soundPrompt") or "").strip()
            ):
                raise ToolError(
                    "PRODUCTION_SOUND_EFFECT_LINE_INVALID",
                    "纯音效行必须使用 sfx、Seed Audio、显式0–5秒时长，并禁止独立生成画面。",
                    details={"lineId": line.get("lineId")},
                )
            duration_profile = _sound_effect_duration_profile(str(line.get("soundPrompt") or ""))
            duration_seconds = float(line["durationSeconds"])
            if not float(duration_profile["min"]) <= duration_seconds <= float(duration_profile["max"]):
                raise ToolError(
                    "PRODUCTION_SOUND_EFFECT_DURATION_INVALID",
                    "纯音效时长必须落在当前声音类型的可辨认区间，不能把欢呼、环境声或鼓声压成突兀的一秒。",
                    details={
                        "lineId": line.get("lineId"),
                        "category": duration_profile["category"],
                        "minimumSeconds": duration_profile["min"],
                        "maximumSeconds": duration_profile["max"],
                        "recommendedSeconds": duration_profile["recommended"],
                        "actualSeconds": duration_seconds,
                    },
                )
        config["codexVisualPlan"] = _normalize_codex_visual_plan(
            config.get("codexVisualPlan"),
            manuscript=manuscript,
            production_config=config,
            synthetic=synthetic,
        )
        if config["codexVisualPlan"] is None:
            config.pop("codexVisualPlan")
        visual_characters = [
            character
            for character in manuscript.get("characters", [])
            if isinstance(character, dict)
            and character.get("visualConsistencyRequired") is True
            and str(character.get("characterId") or "").strip().lower() not in {"narrator", "sfx"}
        ]
        if not visual_characters:
            raise ToolError(
                "PRODUCTION_CHARACTER_VISUAL_PACK_REQUIRED",
                "叙事类正式稿必须在正文阶段同时冻结主要角色识别和中文单人形象锚点，不能用只有旁白的角色表启动工坊。",
            )
        self._validate_environment(config)
        project_id = _safe_identifier(manuscript["projectId"], "projectId")
        identity = {
            "manuscriptHash": manuscript["contentHash"],
            "publishingHash": publishing["contentHash"],
            "productionConfig": config,
            "productionPreset": production_preset,
            "workshopCompatibility": workshop_compatibility,
            "voiceCatalogHash": catalog_hash,
        }
        identity_hash = _sha256_bytes(_canonical_bytes(identity))
        package_version, existing = self._next_package_version(project_id, identity_hash)
        if existing:
            manifest = self.validate_package(existing)
            try:
                save_review_document(
                    user_project_root,
                    document_id="production-overview",
                    content=_production_overview_markdown(
                        manuscript=manuscript,
                        publishing=publishing,
                        production_config=config,
                        production_preset=production_preset,
                        package_path=existing,
                        package_hash=manifest["packageHash"],
                        review_documents=review_view,
                    ),
                    language="zh-CN",
                    updated_at=manifest["createdAt"],
                    minimum_characters=120,
                    source_binding={
                        "contractType": manifest["packageType"],
                        "contractId": manifest["productionPackageId"],
                        "contentHash": manifest["packageHash"],
                    },
                )
                if config.get("codexVisualPlan"):
                    save_review_document(
                        user_project_root,
                        document_id="codex-visual-plan",
                        content=_codex_visual_plan_markdown(config["codexVisualPlan"], manuscript.get("characters", [])),
                        language="zh-CN",
                        updated_at=manifest["createdAt"],
                        minimum_characters=120,
                        source_binding={
                            "contractType": manifest["packageType"],
                            "contractId": manifest["productionPackageId"],
                            "contentHash": config["codexVisualPlan"]["contentHash"],
                        },
                    )
            except ValueError as exc:
                raise ToolError("PRODUCTION_REVIEW_DOCUMENT_INVALID", str(exc)) from exc
            return {
                "packagePath": str(existing),
                "manifest": manifest,
                "idempotent": True,
                "userReviewDocuments": review_documents_view(user_project_root),
            }
        production_package_id = f"production_{project_id}_v{package_version.replace('.', '_')}"
        package_root = self.root / "packages" / project_id / f"v{package_version}"
        if package_root.exists():
            raise ToolError("PRODUCTION_PACKAGE_PATH_CONFLICT", "生产包版本目录已存在但不在索引中。")
        package_root.mkdir(parents=True)
        package_committed = False
        try:
            lines = deepcopy(target_script.get("lines", []))
            if not lines or len(lines) != manuscript.get("lineCount"):
                raise ToolError("PRODUCTION_TARGET_SCRIPT_INVALID", "正式母稿行数量无效。")
            characters = []
            design_by_character_id = {
                item["characterId"]: item
                for item in config.get("codexVisualPlan", {}).get("characterDesigns", [])
            }
            for character in manuscript.get("characters", []):
                speaker_id = character.get("characterId")
                if speaker_id not in voice_bindings:
                    raise ToolError("PRODUCTION_VOICE_BINDING_MISSING", "持续角色缺少锁定音色。")
                design = design_by_character_id.get(speaker_id, {})
                appearance = _character_appearance_contract(character) if config.get("codexVisualPlan") else {}
                packaged_character = {
                    **deepcopy(character),
                    **appearance,
                    **deepcopy(design),
                    "voice": deepcopy(voice_bindings[speaker_id]),
                }
                if design.get("identityAnchorPromptZh"):
                    packaged_character["visualAnchorPromptZh"] = design["identityAnchorPromptZh"]
                characters.append(packaged_character)
            episodes = []
            for episode_number in range(1, manuscript.get("episodeCount", 0) + 1):
                line_ids = [line["lineId"] for line in lines if line.get("episodeNumber") == episode_number]
                if not line_ids:
                    raise ToolError("PRODUCTION_EPISODE_INVALID", "分集没有正式母稿行。")
                episodes.append({"episodeId": f"E{episode_number:02d}", "episodeNumber": episode_number, "lineIds": line_ids})
            project = {
                "schemaVersion": "2.1",
                "projectId": project_id,
                "channelProfileId": manuscript["channelProfileId"],
                "targetRegion": production_preset.get("targetRegion", "unknown"),
                "targetLanguage": manuscript["targetLanguage"],
                "title": publishing["title"],
                "titleZhTranslation": publishing.get("titleZhTranslation", ""),
                "episodeCount": manuscript["episodeCount"],
                "lineCount": manuscript["lineCount"],
                "packageVersion": package_version,
            }
            package_characters = {"schemaVersion": "2.1", "characters": characters}
            package_episodes = {"schemaVersion": "2.1", "episodes": episodes}
            script_lines = {
                "schemaVersion": "2.1",
                "language": manuscript["targetLanguage"],
                "role": "target-language-production-master",
                "isSoleProductionSource": True,
                "lines": lines,
            }
            config_document = {"schemaVersion": "2.1", **config}
            quality_document = {
                "schemaVersion": "2.1",
                "sourceHash": manuscript["qualityGateHash"],
                **deepcopy(quality_gate),
            }
            publishing_document = {
                "schemaVersion": "2.1",
                "title": publishing["title"],
                "titleZhTranslation": publishing.get("titleZhTranslation", ""),
                "descriptionBody": publishing["descriptionBody"],
                "hashtags": publishing["hashtags"],
                "thumbnail": "confirmed_thumbnail.png" if thumbnail_path else "",
                "thumbnailMode": "custom" if thumbnail_path else "youtube_auto",
                "targetChannel": publishing.get("targetChannel", {}),
                "uploadPolicy": publishing.get("uploadPolicy", "REQUIRE_REVIEW"),
            }
            source_lock = {
                "schemaVersion": "2.1",
                "manuscriptPackage": _contract_ref(manuscript),
                "publishingAssetPackage": _contract_ref(publishing),
                "productionPreset": production_preset_ref,
                "workshopCompatibility": deepcopy(workshop_compatibility),
                "voiceCatalog": {
                    "id": catalog.get("catalogId", "voice-catalog"),
                    "version": catalog_version,
                    "hash": catalog_hash,
                },
                "targetScriptBinding": {
                    "targetScriptContentHash": target_script["contentHash"],
                    "userReviewDocumentId": "final-script-target",
                    "userReviewDocumentSha256": review_by_id["final-script-target"]["sha256"],
                    "productionUseAllowed": True,
                    "productionFile": "script_lines.json",
                },
            }
            for name, document in (
                ("project.json", project),
                ("characters.json", package_characters),
                ("episodes.json", package_episodes),
                ("script_lines.json", script_lines),
                ("production_config.json", config_document),
                ("target_script_quality_gate.json", quality_document),
                ("publishing.json", publishing_document),
                ("source_lock.json", source_lock),
            ):
                if contains_sensitive_material(document):
                    raise ToolError("PRODUCTION_PACKAGE_SENSITIVE", "标准生产包包含敏感字段。")
                _atomic_json(package_root / name, document)
            if thumbnail_path is not None:
                _write_copy(thumbnail_path, package_root / "confirmed_thumbnail.png")
            manifest = {
                "schemaVersion": "2.1",
                "packageType": "production-package-v2",
                "packageVersion": package_version,
                "productionPackageId": production_package_id,
                "projectId": project_id,
                "status": "READY_TO_PRODUCE",
                "synthetic": bool(synthetic),
                "createdAt": utc_now(),
                "files": self._package_file_descriptors(package_root),
                "manifestSelfExcluded": True,
            }
            manifest["packageHash"] = production_package_hash(manifest)
            _atomic_json(package_root / "manifest.json", manifest)
            self.validate_package(package_root)
            index_path = self._package_index_path(project_id)
            index = _read_json(index_path) if index_path.is_file() else {"schemaVersion": "1.0.0", "projectId": project_id, "packages": []}
            index["packages"].append(
                {
                    "productionPackageId": production_package_id,
                    "packageVersion": package_version,
                    "packageHash": manifest["packageHash"],
                    "identityHash": identity_hash,
                    "path": str(package_root),
                }
            )
            _atomic_json(index_path, index)
            package_committed = True
            try:
                save_review_document(
                    user_project_root,
                    document_id="production-overview",
                    content=_production_overview_markdown(
                        manuscript=manuscript,
                        publishing=publishing,
                        production_config=config,
                        production_preset=production_preset,
                        package_path=package_root,
                        package_hash=manifest["packageHash"],
                        review_documents=review_view,
                    ),
                    language="zh-CN",
                    updated_at=manifest["createdAt"],
                    minimum_characters=120,
                    source_binding={
                        "contractType": manifest["packageType"],
                        "contractId": manifest["productionPackageId"],
                        "contentHash": manifest["packageHash"],
                    },
                )
                if config.get("codexVisualPlan"):
                    save_review_document(
                        user_project_root,
                        document_id="codex-visual-plan",
                        content=_codex_visual_plan_markdown(config["codexVisualPlan"], manuscript.get("characters", [])),
                        language="zh-CN",
                        updated_at=manifest["createdAt"],
                        minimum_characters=120,
                        source_binding={
                            "contractType": manifest["packageType"],
                            "contractId": manifest["productionPackageId"],
                            "contentHash": config["codexVisualPlan"]["contentHash"],
                        },
                    )
            except ValueError as exc:
                raise ToolError("PRODUCTION_REVIEW_DOCUMENT_INVALID", str(exc)) from exc
            return {
                "packagePath": str(package_root),
                "manifest": manifest,
                "idempotent": False,
                "userReviewDocuments": review_documents_view(user_project_root),
            }
        except Exception:
            if not package_committed and package_root.exists():
                shutil.rmtree(package_root)
            raise

    def _validate_production_config(self, config: Any) -> dict[str, Any]:
        if not isinstance(config, dict):
            raise ToolError("PRODUCTION_CONFIG_INVALID", "生产配置必须是对象。")
        settings_contract_version = str(config.get("settingsContractVersion") or "legacy").strip()
        delivery_mode = config.get("deliveryMode")
        if delivery_mode not in {"auto_render", "jianying_refine"}:
            raise ToolError("PRODUCTION_CONFIG_INVALID", "制作方式不受支持。")
        aspect_ratio = config.get("aspectRatio", "16:9")
        width = config.get("width", 640)
        height = config.get("height", 360)
        frame_rate = config.get("frameRate", 24)
        if aspect_ratio != "16:9" or any(not isinstance(value, int) or value <= 0 for value in (width, height, frame_rate)):
            raise ToolError("PRODUCTION_CONFIG_INVALID", "画幅、分辨率或帧率无效。")
        if width * 9 != height * 16:
            raise ToolError("PRODUCTION_CONFIG_INVALID", "分辨率不是 16:9。")
        image_style = deepcopy(config.get("imageStyle"))
        if not isinstance(image_style, dict):
            raise ToolError("PRODUCTION_IMAGE_STYLE_REQUIRED", "开始制作前必须选择图片风格预设或确认自定义图片风格提示词。")
        image_style_id = str(image_style.get("presetId") or "").strip()
        image_style_prompt = str(image_style.get("prompt") or "").strip()
        current_style_ids = {f"visual_{index:02d}" for index in range(1, 37)} | {"custom"}
        if image_style_id not in current_style_ids:
            raise ToolError(
                "PRODUCTION_IMAGE_STYLE_RETIRED",
                "新生产包只接受 visual_01–visual_36 或 custom；旧画风预设已退役。",
            )
        if not image_style_prompt:
            raise ToolError("PRODUCTION_IMAGE_STYLE_REQUIRED", "图片风格提示词不能为空；每个新任务都必须明确确认一次。")
        if len(image_style_prompt) > 2000:
            raise ToolError("PRODUCTION_IMAGE_STYLE_INVALID", "图片风格提示词过长。")
        story_image_text_policy = str(config.get("storyImageTextPolicy") or "").strip()
        if story_image_text_policy != "forbid_visible_text":
            raise ToolError(
                "PRODUCTION_STORY_IMAGE_TEXT_POLICY_INVALID",
                "角色图、分镜图和宫格图必须使用 forbid_visible_text；正式封面文字由封面流程单独管理。",
            )
        voice_tts_profile = deepcopy(config.get("voiceTtsProfile"))
        if not isinstance(voice_tts_profile, dict):
            raise ToolError("PRODUCTION_VOICE_ENGINE_REQUIRED", "开始制作前必须由用户明确选择人物旁白与对白配音引擎。")
        voice_selection_source = str(voice_tts_profile.get("selectionSource") or "").strip()
        voice_engine_id = str(voice_tts_profile.get("engineId") or "").strip()
        if voice_selection_source != "user" or not voice_engine_id or voice_engine_id == "seed_audio":
            raise ToolError(
                "PRODUCTION_VOICE_ENGINE_INVALID",
                "人物旁白与对白引擎必须来自本次用户选择，且不得使用仅供纯音效的 Seed Audio。",
            )
        if voice_tts_profile.get("recommendVoicesFromSelectedEngineOnly") is not True:
            raise ToolError("PRODUCTION_VOICE_RECOMMENDATION_SCOPE_INVALID", "角色音色只能从用户所选配音引擎中推荐。")
        if voice_tts_profile.get("lockScope") != "current_project":
            raise ToolError("PRODUCTION_VOICE_LOCK_SCOPE_INVALID", "角色 speaker_id 与音色绑定必须锁定在当前项目范围。")
        sound_effects = deepcopy(config.get("soundEffects"))
        if not isinstance(sound_effects, dict) or not isinstance(sound_effects.get("enabled"), bool):
            raise ToolError("PRODUCTION_SOUND_EFFECT_CONFIG_REQUIRED", "必须明确确认本项目是否生成纯音效。")
        if settings_contract_version == "2.0" and (
            sound_effects.get("selectionSource") != "user" or sound_effects.get("confirmed") is not True
        ):
            raise ToolError(
                "PRODUCTION_SOUND_EFFECT_SELECTION_REQUIRED",
                "新任务必须由用户本次明确选择是否启用纯音效；不得从频道预设、旧项目或历史学习继承。",
            )
        if sound_effects["enabled"]:
            if (
                sound_effects.get("engineId") != "seed_audio"
                or not str(sound_effects.get("modelId") or "").strip()
                or sound_effects.get("requireExplicitDuration") is not True
                or sound_effects.get("maxDurationSeconds") != SOUND_EFFECT_MAX_DURATION_SECONDS
                or sound_effects.get("standaloneStoryboard") is not False
                or sound_effects.get("mixWithAdjacentSpeech") is not True
                or sound_effects.get("backgroundMusicEnabled") is not False
            ):
                raise ToolError(
                    "PRODUCTION_SOUND_EFFECT_CONFIG_INVALID",
                    "开启纯音效时必须独立使用 Seed Audio、显式短时长（最长5秒）、贴邻人声混合且不得单独生成画面或充当背景音乐。",
                )
            normalized_sound_effects = {
                "enabled": True,
                "engineId": "seed_audio",
                "modelId": str(sound_effects["modelId"]).strip(),
                "requireExplicitDuration": True,
                "maxDurationSeconds": SOUND_EFFECT_MAX_DURATION_SECONDS,
                "standaloneStoryboard": False,
                "mixWithAdjacentSpeech": True,
                "backgroundMusicEnabled": False,
            }
        else:
            if sound_effects.get("backgroundMusicEnabled", False) is not False:
                raise ToolError("PRODUCTION_SOUND_EFFECT_CONFIG_INVALID", "关闭纯音效不能借此开启背景音乐。")
            normalized_sound_effects = {
                "enabled": False,
                "engineId": None,
                "modelId": None,
                "requireExplicitDuration": False,
                "maxDurationSeconds": 0.0,
                "standaloneStoryboard": False,
                "mixWithAdjacentSpeech": False,
                "backgroundMusicEnabled": False,
            }
        if settings_contract_version == "2.0":
            normalized_sound_effects.update({"selectionSource": "user", "confirmed": True})
        prompt_generation = deepcopy(config.get("promptGeneration", {"image": False, "video": False}))
        if (
            not isinstance(prompt_generation, dict)
            or not isinstance(prompt_generation.get("image"), bool)
            or not isinstance(prompt_generation.get("video"), bool)
        ):
            raise ToolError("PRODUCTION_PROMPT_GENERATION_INVALID", "图片提示词和视频提示词开关必须分别为明确的是／否。")
        raw_production_mode = deepcopy(config.get("productionMode"))
        production_mode_explicit = raw_production_mode is not None
        if raw_production_mode is None:
            # 旧生产包继续按原来的 Codex 导演路线读取；新任务会在自由创作工作区
            # 绑定生产前强制取得本次用户选择，因此不会静默继承这个兼容值。
            production_mode = {
                "id": "director",
                "selectionSource": "legacy",
                "confirmed": True,
            }
        else:
            if not isinstance(raw_production_mode, dict):
                raise ToolError("PRODUCTION_MODE_INVALID", "生产模式必须是对象。")
            production_mode_id = str(raw_production_mode.get("id") or "").strip()
            production_mode_source = str(raw_production_mode.get("selectionSource") or "").strip()
            if (
                production_mode_id == "director"
                and production_mode_source == "legacy"
                and raw_production_mode.get("confirmed") is True
            ):
                # 已归一化的旧包在二次校验时继续保持兼容身份；新工作区无法
                # 通过 bind_for_production 写出 legacy 来源。
                production_mode_explicit = False
                production_mode = {
                    "id": "director",
                    "selectionSource": "legacy",
                    "confirmed": True,
                }
            elif (
                production_mode_id not in PRODUCTION_MODE_IDS
                or production_mode_source != "user"
                or raw_production_mode.get("confirmed") is not True
            ):
                raise ToolError(
                    "PRODUCTION_MODE_CONFIRMATION_REQUIRED",
                    "每次开始制作都必须由用户本次明确选择极速自动、平衡或精品导演模式。",
                )
            else:
                production_mode = {
                    "id": production_mode_id,
                    "selectionSource": "user",
                    "confirmed": True,
                }
        codex_visual_plan = deepcopy(config.get("codexVisualPlan"))
        if codex_visual_plan is not None and not isinstance(codex_visual_plan, dict):
            raise ToolError("PRODUCTION_CODEX_VISUAL_PLAN_INVALID", "codexVisualPlan 必须是对象。")
        grid_batch = deepcopy(config.get("gridBatch", {"template": "wide_16_9_4", "selectionSource": "default"}))
        if not isinstance(grid_batch, dict):
            raise ToolError("PRODUCTION_GRID_BATCH_INVALID", "宫格批次必须是对象。")
        grid_template = str(grid_batch.get("template") or "").strip()
        valid_grid_templates = {
            "wide_16_9_1", "wide_16_9_4", "wide_16_9_9", "wide_16_9_16",
            "wide_4_3_4", "wide_4_3_9", "wide_4_3_16",
            "portrait_9_16_1", "portrait_9_16_4", "portrait_9_16_9", "portrait_9_16_16",
            "square_1_1_1", "square_1_1_4", "square_1_1_9", "square_1_1_16",
        }
        if grid_template not in valid_grid_templates:
            raise ToolError("PRODUCTION_GRID_BATCH_INVALID", "宫格批次预设无效。")
        grid_selection_source = str(grid_batch.get("selectionSource") or "default").strip()
        if grid_selection_source not in {"user", "default", "production_profile"}:
            raise ToolError("PRODUCTION_GRID_BATCH_INVALID", "宫格批次选择来源无效。")
        episode_templates = deepcopy(grid_batch.get("episodeTemplates", {}))
        if not isinstance(episode_templates, dict):
            raise ToolError("PRODUCTION_GRID_BATCH_INVALID", "分集宫格批次必须是 episodeId 到宫格预设的对象映射。")
        normalized_episode_templates: dict[str, str] = {}
        for raw_episode_id, raw_template in episode_templates.items():
            episode_id = str(raw_episode_id or "").strip()
            episode_template = str(raw_template or "").strip()
            if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", episode_id) or episode_template not in valid_grid_templates:
                raise ToolError(
                    "PRODUCTION_GRID_BATCH_INVALID",
                    "分集宫格批次包含无效的 episodeId 或宫格预设。",
                    details={"episodeId": episode_id, "template": episode_template},
                )
            normalized_episode_templates[episode_id] = episode_template
        video = deepcopy(config.get("videoGeneration", {}))
        if not isinstance(video.get("enabled"), bool) or video.get("selectionMode") not in VIDEO_SELECTION_MODES:
            raise ToolError("PRODUCTION_VIDEO_SCOPE_INVALID", "视频生成范围无效。")
        if video.get("fallbackPolicy") not in {"pause", "use_static_image"}:
            raise ToolError("PRODUCTION_VIDEO_FALLBACK_INVALID", "视频失败回退策略无效。")
        if video["selectionMode"] in {"project_first_n_storyboards", "episode_first_n_storyboards"}:
            if not isinstance(video.get("count"), int) or isinstance(video.get("count"), bool) or video["count"] < 1:
                raise ToolError("PRODUCTION_VIDEO_SCOPE_INVALID", "按数量选择视频时必须提供正整数 count。")
        if not video["enabled"] and video["selectionMode"] != "none":
            raise ToolError("PRODUCTION_VIDEO_SCOPE_INVALID", "禁用视频生成时 selectionMode 必须为 none。")
        frame_input_mode = str(video.get("frameInputMode") or "first_frame").strip()
        raw_end_frame_source = video.get("endFrameSource")
        end_frame_source = "dedicated_generated" if raw_end_frame_source is None else str(raw_end_frame_source).strip()
        if frame_input_mode not in {"first_frame", "first_last_frame"}:
            raise ToolError("PRODUCTION_VIDEO_FRAME_INPUT_INVALID", "视频输入模式只能选择仅首帧或首尾帧。")
        if frame_input_mode == "first_last_frame":
            if not video["enabled"]:
                raise ToolError("PRODUCTION_VIDEO_FRAME_INPUT_INVALID", "首尾帧模式只能用于本次已明确开启的视频生成范围。")
            if end_frame_source != "dedicated_generated":
                raise ToolError("PRODUCTION_VIDEO_END_FRAME_INVALID", "首尾帧模式当前只接受同镜头独立尾帧。")
        video["frameInputMode"] = frame_input_mode
        video["endFrameSource"] = end_frame_source
        video["selectedStoryboardIds"] = []
        scene_image_cadence = deepcopy(
            config.get(
                "sceneImageCadence",
                {
                    "mode": "semantic_auto",
                    "selectionSource": "legacy",
                    "confirmed": True,
                },
            )
        )
        if not isinstance(scene_image_cadence, dict):
            raise ToolError("PRODUCTION_SCENE_CADENCE_INVALID", "图片覆盖节奏必须是对象。")
        cadence_mode = str(scene_image_cadence.get("mode") or "").strip()
        if cadence_mode not in SCENE_IMAGE_CADENCE_MODES:
            raise ToolError("PRODUCTION_SCENE_CADENCE_INVALID", "图片覆盖节奏模式无效。")
        normalized_cadence: dict[str, Any] = {
            "mode": cadence_mode,
            "selectionSource": str(scene_image_cadence.get("selectionSource") or "legacy").strip(),
            "confirmed": scene_image_cadence.get("confirmed") is True,
        }
        if cadence_mode == "seconds_range":
            minimum_seconds = scene_image_cadence.get("minimumSeconds")
            maximum_seconds = scene_image_cadence.get("maximumSeconds")
            if (
                not isinstance(minimum_seconds, (int, float))
                or isinstance(minimum_seconds, bool)
                or not isinstance(maximum_seconds, (int, float))
                or isinstance(maximum_seconds, bool)
                or minimum_seconds <= 0
                or maximum_seconds < minimum_seconds
                or maximum_seconds > 120
            ):
                raise ToolError("PRODUCTION_SCENE_CADENCE_INVALID", "按秒覆盖图片时必须提供有效的最短和最长秒数。")
            normalized_cadence["minimumSeconds"] = float(minimum_seconds)
            normalized_cadence["maximumSeconds"] = float(maximum_seconds)
        if cadence_mode == "custom":
            instructions = str(scene_image_cadence.get("instructions") or "").strip()
            if not instructions or len(instructions) > 1000:
                raise ToolError("PRODUCTION_SCENE_CADENCE_INVALID", "自定义图片覆盖节奏必须提供有效说明。")
            normalized_cadence["instructions"] = instructions
        if settings_contract_version == "2.0":
            if (
                normalized_cadence["selectionSource"] != "user"
                or normalized_cadence["confirmed"] is not True
                or str(config.get("deliveryModeSelectionSource") or "") != "user"
                or video.get("selectionSource") != "user"
                or video.get("confirmed") is not True
                or prompt_generation.get("selectionSource") != "user"
                or prompt_generation.get("confirmed") is not True
            ):
                raise ToolError(
                    "PRODUCTION_USER_SETTINGS_NOT_FROZEN",
                    "新任务的成片方式、提示词、镜头视频和图片覆盖节奏必须来自本次用户选择并冻结。",
                )
        workshop_prompt_generation = {"image": False, "video": False}
        if production_mode_explicit:
            production_mode_id = production_mode["id"]
            if production_mode_id in {"fast_auto", "balanced"}:
                if codex_visual_plan is not None:
                    raise ToolError(
                        "PRODUCTION_MODE_VISUAL_PLAN_CONFLICT",
                        "极速自动模式和平衡模式不得携带 codexVisualPlan。",
                        details={"productionMode": production_mode_id},
                    )
                workshop_prompt_generation["image"] = production_mode_id == "balanced" or bool(prompt_generation["image"])
                workshop_prompt_generation["video"] = bool(prompt_generation["video"])
            elif production_mode_id == "director":
                if prompt_generation["image"] is not True:
                    raise ToolError(
                        "PRODUCTION_MODE_PROMPT_CONFLICT",
                        "精品导演模式必须开启 Codex 图片提示词与完整逐镜视觉方案。",
                    )
        if production_mode_explicit and video["enabled"] and prompt_generation["video"] is not True:
            raise ToolError(
                "PRODUCTION_MODE_VIDEO_PROMPT_REQUIRED",
                "开启镜头视频时必须同时开启视频提示词；提示词作者由生产模式决定。",
            )
        concurrency = deepcopy(config.get("concurrency", {"image": 20, "video": 1, "tts": 1}))
        if not isinstance(concurrency, dict) or any(
            not isinstance(value, int) or isinstance(value, bool) or value < 1 or value > MAX_PRODUCTION_CONCURRENCY
            for value in concurrency.values()
        ):
            raise ToolError("PRODUCTION_CONFIG_INVALID", "并发参数无效。")
        retry_limit = config.get("retryLimit", 2)
        if not isinstance(retry_limit, int) or isinstance(retry_limit, bool) or not 0 <= retry_limit <= 10:
            raise ToolError("PRODUCTION_CONFIG_INVALID", "重试次数无效。")
        normalized_config = {
            "settingsContractVersion": settings_contract_version,
            "productionMode": production_mode,
            "deliveryMode": delivery_mode,
            "deliveryModeSelectionSource": str(config.get("deliveryModeSelectionSource") or "legacy").strip(),
            "aspectRatio": aspect_ratio,
            "width": width,
            "height": height,
            "frameRate": frame_rate,
            "imageStyle": {"presetId": image_style_id, "prompt": image_style_prompt},
            "storyImageTextPolicy": story_image_text_policy,
            "voiceTtsProfile": {
                "selectionSource": "user",
                "engineId": voice_engine_id,
                "recommendVoicesFromSelectedEngineOnly": True,
                "lockScope": "current_project",
            },
            "soundEffects": normalized_sound_effects,
            "promptGeneration": {
                "image": prompt_generation["image"],
                "video": prompt_generation["video"],
                **(
                    {
                        "selectionSource": str(prompt_generation.get("selectionSource") or "").strip(),
                        "confirmed": prompt_generation.get("confirmed") is True,
                    }
                    if settings_contract_version == "2.0"
                    else {}
                ),
            },
            "workshopPromptGeneration": workshop_prompt_generation,
            "gridBatch": {
                "template": grid_template,
                "selectionSource": grid_selection_source,
                "episodeTemplates": normalized_episode_templates,
            },
            "videoGeneration": video,
            "sceneImageCadence": normalized_cadence,
            "concurrency": concurrency,
            "retryLimit": retry_limit,
            "syntheticFixtureRunner": bool(config.get("syntheticFixtureRunner", False)),
        }
        if codex_visual_plan is not None:
            normalized_config["codexVisualPlan"] = codex_visual_plan
        return normalized_config

    def _validate_environment(self, config: dict[str, Any]) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        usage = shutil.disk_usage(self.root)
        minimum = 16 * 1024 * 1024
        if usage.free < minimum:
            raise ToolError("PRODUCTION_DISK_INSUFFICIENT", "隔离生产目录磁盘空间不足。")
        if not self.ffmpeg_path or not Path(self.ffmpeg_path).is_file():
            raise ToolError("PRODUCTION_FFMPEG_UNAVAILABLE", "FFmpeg 不可用。")
        if not self.ffprobe_path or not Path(self.ffprobe_path).is_file():
            raise ToolError("PRODUCTION_FFPROBE_UNAVAILABLE", "ffprobe 不可用。")
        if config["deliveryMode"] == "jianying_refine" and os.environ.get("AIVCP_DISABLE_JIANYING_DRAFT") == "1":
            raise ToolError("PRODUCTION_JIANYING_UNAVAILABLE", "当前安装禁用了剪映草稿导出。")

    def validate_package(self, package_root: Path) -> dict[str, Any]:
        package_root = package_root.resolve()
        manifest = _read_json(package_root / "manifest.json", "PRODUCTION_PACKAGE_INVALID")
        if manifest.get("schemaVersion") != "2.1" or manifest.get("packageType") != "production-package-v2":
            raise ToolError("PRODUCTION_PACKAGE_VERSION_UNSUPPORTED", "标准生产包必须为 schemaVersion 2.1。")
        if manifest.get("status") != "READY_TO_PRODUCE" or manifest.get("manifestSelfExcluded") is not True:
            raise ToolError("PRODUCTION_PACKAGE_INVALID", "生产包状态或 manifest 自身哈希规则无效。")
        _safe_identifier(manifest.get("projectId"), "projectId")
        _safe_identifier(manifest.get("productionPackageId"), "productionPackageId")
        if not re.fullmatch(r"\d+\.\d+\.\d+", str(manifest.get("packageVersion", ""))):
            raise ToolError("PRODUCTION_PACKAGE_INVALID", "packageVersion 必须是三段版本号。")
        files = manifest.get("files")
        if not isinstance(files, list):
            raise ToolError("PRODUCTION_PACKAGE_INVALID", "manifest.files 无效。")
        declared_paths = [item.get("path") for item in files if isinstance(item, dict)]
        if declared_paths != sorted(declared_paths):
            raise ToolError("PRODUCTION_PACKAGE_INVALID", "manifest.files must be sorted by relative path.")
        listed: set[str] = set()
        for descriptor in files:
            if not isinstance(descriptor, dict):
                raise ToolError("PRODUCTION_PACKAGE_INVALID", "文件描述符无效。")
            relative = _safe_relative(descriptor.get("path"), "manifest.files.path")
            normalized = relative.as_posix()
            if normalized in listed:
                raise ToolError("PRODUCTION_PACKAGE_INVALID", "manifest 包含重复文件路径。")
            listed.add(normalized)
            path = _ensure_within(package_root, package_root / relative, "manifest file")
            if not path.is_file() or path.stat().st_size != descriptor.get("sizeBytes") or _sha256_file(path) != descriptor.get("sha256"):
                raise ToolError("PRODUCTION_PACKAGE_FILE_HASH_MISMATCH", "生产包文件缺失、大小或哈希不一致。", details={"path": normalized})
        actual = {path.relative_to(package_root).as_posix() for path in package_root.rglob("*") if path.is_file() and path.name != "manifest.json"}
        allowed_files = PRODUCTION_PACKAGE_FILES
        if (
            listed != actual
            or not PRODUCTION_PACKAGE_REQUIRED_FILES.issubset(listed)
            or not listed.issubset(allowed_files)
        ):
            extras = sorted((listed | actual) - PRODUCTION_PACKAGE_FILES)
            missing = sorted(PRODUCTION_PACKAGE_REQUIRED_FILES - (listed & actual))
            code = "PRODUCTION_AUDIT_SCRIPT_FORBIDDEN" if any("chinese-audit" in value for value in extras) else "PRODUCTION_PACKAGE_FILE_SET_INVALID"
            raise ToolError(code, "生产包只能包含冻结的 2.1 文件集合。", details={"extra": extras, "missing": missing})
        if production_package_hash(manifest) != manifest.get("packageHash"):
            raise ToolError("PRODUCTION_PACKAGE_HASH_MISMATCH", "生产包 packageHash 无效。")
        project = _read_json(package_root / "project.json")
        publishing = _read_json(package_root / "publishing.json")
        script_lines = _read_json(package_root / "script_lines.json")
        characters = _read_json(package_root / "characters.json")
        episodes = _read_json(package_root / "episodes.json")
        config = _read_json(package_root / "production_config.json")
        quality = _read_json(package_root / "target_script_quality_gate.json")
        source_lock = _read_json(package_root / "source_lock.json")
        for document in (project, publishing, script_lines, characters, episodes, config, quality, source_lock):
            if document.get("schemaVersion") != "2.1":
                raise ToolError("PRODUCTION_PACKAGE_VERSION_UNSUPPORTED", "包内 JSON schemaVersion 必须全部为 2.1。")
            if contains_sensitive_material(document):
                raise ToolError("PRODUCTION_PACKAGE_SENSITIVE", "生产包包含密钥、Token 或其他敏感字段。")
        if project.get("projectId") != manifest["projectId"] or project.get("packageVersion") != manifest["packageVersion"]:
            raise ToolError("PRODUCTION_PACKAGE_IDENTITY_MISMATCH", "manifest 与 project 身份不一致。")
        if project.get("title") != publishing.get("title"):
            raise ToolError("PRODUCTION_TITLE_MISMATCH", "正式标题必须来自 Publishing Asset 且两处一致。")
        if script_lines.get("role") != "target-language-production-master" or script_lines.get("isSoleProductionSource") is not True:
            raise ToolError("PRODUCTION_TARGET_SCRIPT_NOT_SOLE_SOURCE", "script_lines 不是唯一目标语言正式母稿。")
        lines = script_lines.get("lines")
        if not isinstance(lines, list) or len(lines) != project.get("lineCount"):
            raise ToolError("PRODUCTION_SCRIPT_MAPPING_INVALID", "正式文稿行数量不一致。")
        expected_ids: list[str] = []
        for episode in episodes.get("episodes", []):
            expected_ids.extend(episode.get("lineIds", []))
        if expected_ids != [line.get("lineId") for line in lines]:
            raise ToolError("PRODUCTION_SCRIPT_MAPPING_INVALID", "分集行顺序与正式母稿不一致。")
        if (
            quality.get("status") != "PASSED"
            or not re.fullmatch(r"[0-9a-f]{64}", str(quality.get("sourceHash", "")))
            or not re.fullmatch(r"[0-9a-f]{64}", str(quality.get("targetScriptHash", "")))
        ):
            raise ToolError("PRODUCTION_QUALITY_GATE_INVALID", "生产包质量门无效。")
        self._validate_production_config({key: value for key, value in config.items() if key != "schemaVersion"})
        thumbnail_mode = publishing.get("thumbnailMode")
        thumbnail_name = publishing.get("thumbnail", "")
        if thumbnail_mode == "custom":
            thumbnail = package_root / thumbnail_name
            if thumbnail != package_root / "confirmed_thumbnail.png" or not thumbnail.is_file():
                raise ToolError("PRODUCTION_THUMBNAIL_INVALID", "自定义封面模式没有引用包内确认封面。")
        elif thumbnail_mode == "youtube_auto":
            if thumbnail_name or (package_root / "confirmed_thumbnail.png").exists():
                raise ToolError("PRODUCTION_THUMBNAIL_INVALID", "YouTube 自动缩略图模式不得夹带自定义封面。")
        else:
            raise ToolError("PRODUCTION_THUMBNAIL_INVALID", "publishing.json 缺少有效 thumbnailMode。")
        return manifest

    def _task_path(self, task_id: str) -> Path:
        return self.root / "tasks" / task_id / "production-task.json"

    def _task_root(self, task_id: str) -> Path:
        return self.root / "tasks" / task_id

    def _load_task(self, task_id: Any) -> dict[str, Any]:
        task_id = _safe_identifier(task_id, "productionTaskId")
        path = self._task_path(task_id)
        if not path.is_file():
            raise ToolError("PRODUCTION_TASK_NOT_FOUND", "没有找到指定制作任务。")
        return _read_json(path, "PRODUCTION_TASK_INVALID")

    def _archive_task_history(self, task: dict[str, Any]) -> None:
        history = task.get("history") if isinstance(task.get("history"), list) else []
        if len(history) <= PRODUCTION_TASK_RECENT_HISTORY_LIMIT:
            return
        archive_path = self._task_root(str(task["productionTaskId"])) / "history.ndjson"
        archived: dict[int, dict[str, Any]] = {}
        if archive_path.is_file():
            try:
                for line in archive_path.read_text(encoding="utf-8-sig").splitlines():
                    item = json.loads(line)
                    if isinstance(item, dict) and isinstance(item.get("revision"), int):
                        archived[item["revision"]] = item
            except (OSError, UnicodeError, json.JSONDecodeError):
                archived = {}
        for item in history[:-PRODUCTION_TASK_RECENT_HISTORY_LIMIT]:
            if isinstance(item, dict) and isinstance(item.get("revision"), int):
                archived[item["revision"]] = item
        ordered = [archived[key] for key in sorted(archived)]
        payload = "".join(json.dumps(item, ensure_ascii=False, separators=(",", ":")) + "\n" for item in ordered)
        _atomic_bytes(archive_path, payload.encode("utf-8"))
        task["history"] = history[-PRODUCTION_TASK_RECENT_HISTORY_LIMIT:]
        task["historyArchive"] = {
            "relativePath": archive_path.name,
            "eventCount": len(ordered),
            "throughRevision": max(archived) if archived else 0,
        }

    def _history_page(self, task: dict[str, Any], *, limit: int, cursor_revision: int | None) -> dict[str, Any]:
        events: dict[int, dict[str, Any]] = {}
        archive_path = self._task_root(str(task["productionTaskId"])) / "history.ndjson"
        if archive_path.is_file():
            try:
                for line in archive_path.read_text(encoding="utf-8-sig").splitlines():
                    item = json.loads(line)
                    if isinstance(item, dict) and isinstance(item.get("revision"), int):
                        events[item["revision"]] = item
            except (OSError, UnicodeError, json.JSONDecodeError):
                pass
        for item in task.get("history") or []:
            if isinstance(item, dict) and isinstance(item.get("revision"), int):
                events[item["revision"]] = item
        revisions = sorted(
            (revision for revision in events if cursor_revision is None or revision < cursor_revision),
            reverse=True,
        )
        selected_revisions = revisions[:limit]
        selected = [events[revision] for revision in reversed(selected_revisions)]
        next_cursor = min(selected_revisions) if len(revisions) > len(selected_revisions) and selected_revisions else None
        return {
            "events": selected,
            "limit": limit,
            "nextCursorRevision": next_cursor,
            "hasMore": next_cursor is not None,
            "totalAvailable": len(events),
        }

    def _save_task(self, task: dict[str, Any], *, event: str | None = None, details: dict[str, Any] | None = None) -> None:
        queue = task.get("queue") if isinstance(task.get("queue"), dict) else None
        if queue and queue.get("schemaVersion") == QUEUE_SCHEMA_VERSION:
            state = str(task.get("state") or "")
            queue["status"] = (
                "COMPLETED" if state == "VIDEO_READY"
                else "WAITING_WORKSHOP" if state == "QUEUED_WAITING_WORKSHOP"
                else "RUNNING" if state == "RUNNING"
                else "AWAITING_MANUAL_EXPORT" if state == "AWAITING_JIANYING_EXPORT"
                else "PAUSED" if state in {"PAUSED", "NEEDS_CONFIGURATION", "NEEDS_REPAIR"}
                else "FAILED" if state in {"FAILED", "CANCELLED", "ARCHIVED"}
                else "QUEUED"
            )
        now = utc_now()
        details = details or {}
        suppress_event = False
        if event in COALESCED_WORKSHOP_EVENTS:
            signature = _coalesced_event_signature(event, details)
            coalescing = task.setdefault("eventCoalescing", {})
            previous = coalescing.get(event) if isinstance(coalescing.get(event), dict) else {}
            if previous.get("signature") == signature:
                suppress_event = True
                previous["occurrences"] = int(previous.get("occurrences", 1)) + 1
                previous["lastSeenAt"] = now
                summary = task.setdefault("historySummary", {})
                suppressed = summary.setdefault("suppressedDuplicateEvents", {})
                suppressed[event] = int(suppressed.get(event, 0)) + 1
            else:
                coalescing[event] = {
                    "signature": signature,
                    "occurrences": 1,
                    "firstSeenAt": now,
                    "lastSeenAt": now,
                }
        if not suppress_event:
            task["revision"] = int(task.get("revision", 0)) + 1
        task["updatedAt"] = now
        if event and not suppress_event:
            task.setdefault("history", []).append(
                {"revision": task["revision"], "at": task["updatedAt"], "event": event, "details": details}
            )
            summary = task.setdefault("historySummary", {})
            counts = summary.setdefault("eventCounts", {})
            counts[event] = int(counts.get(event, 0)) + 1
            summary["lastEvent"] = event
            summary["lastEventAt"] = now
        self._archive_task_history(task)
        _atomic_json(self._task_path(task["productionTaskId"]), task)

    def _queue_dispatcher_settings(self) -> dict[str, Path] | None:
        if self.workshop_bridge is None or self.plugin_root is None:
            return None
        executable = getattr(self.workshop_bridge, "executable", None)
        isolation_root = getattr(self.workshop_bridge, "isolation_root", None)
        if not isinstance(executable, Path) or not isinstance(isolation_root, Path):
            return None
        return {
            "data_root": self.data_root,
            "plugin_root": self.plugin_root,
            "workshop_executable": executable,
            "workshop_isolation_root": isolation_root,
        }

    def _wake_queue_dispatcher(self, *, start_if_missing: bool = True) -> dict[str, Any] | None:
        settings = self._queue_dispatcher_settings()
        if settings is None:
            return None
        from .production_queue_worker import ensure_dispatcher, signal_dispatcher

        if start_if_missing:
            return ensure_dispatcher(**settings)
        signal_dispatcher(self.data_root)
        return {"started": False, "signaled": True}

    def get_task(
        self,
        task_id: Any,
        *,
        include_history: bool = False,
        history_limit: int = PRODUCTION_TASK_DEFAULT_HISTORY_LIMIT,
        history_cursor_revision: int | None = None,
    ) -> dict[str, Any]:
        stored_task = self._load_task(task_id)
        task = deepcopy(stored_task)
        limit = min(PRODUCTION_TASK_MAX_HISTORY_PAGE, max(1, int(history_limit or PRODUCTION_TASK_DEFAULT_HISTORY_LIMIT)))
        history_page = self._history_page(stored_task, limit=limit, cursor_revision=history_cursor_revision) if include_history else None
        task.pop("history", None)
        task["historyAvailable"] = int((stored_task.get("historyArchive") or {}).get("eventCount") or 0) + len(stored_task.get("history") or [])
        result = {"task": task, "progressReadOnly": True, "historyIncluded": include_history}
        if history_page is not None:
            result["historyPage"] = history_page
        queue = task.get("queue") if isinstance(task.get("queue"), dict) else {}
        if queue.get("schemaVersion") == QUEUE_SCHEMA_VERSION:
            from .production_queue_worker import queue_position

            result["queue"] = queue_position(self.data_root, str(task["productionTaskId"]))
        return result

    def _find_active_task(self, project_id: str, package_version: str) -> dict[str, Any] | None:
        tasks_root = self.root / "tasks"
        if not tasks_root.is_dir():
            return None
        for path in tasks_root.glob("*/production-task.json"):
            task = _read_json(path, "PRODUCTION_TASK_INVALID")
            if (
                task.get("projectId") == project_id
                and task.get("packageVersion") == package_version
                and task.get("state") in ACTIVE_TASK_STATES
            ):
                return task
        return None

    def _strict_roundtrip(self, package_root: Path, import_root: Path) -> dict[str, Any]:
        manifest = self.validate_package(package_root)
        key = f"{manifest['projectId']}--{manifest['packageVersion']}--{manifest['packageHash']}"
        record_path = self.root / "imports" / f"{_sha256_bytes(key.encode('utf-8'))}.json"
        if record_path.is_file():
            record = _read_json(record_path)
            snapshot_path = Path(record["snapshotPath"])
            if not snapshot_path.is_file() or _sha256_file(snapshot_path) != record.get("snapshotSha256"):
                raise ToolError("PRODUCTION_PACKAGE_DUPLICATE_INVALID", "既有导入快照已损坏，不能伪装幂等复用。")
            return {**record, "duplicate": True}
        source = {
            name: _read_json(package_root / name)
            for name in (
                "project.json",
                "characters.json",
                "episodes.json",
                "script_lines.json",
                "production_config.json",
                "publishing.json",
            )
        }
        snapshot = {
            "schemaVersion": "1.0.0",
            "source": "production_package",
            "projectId": manifest["projectId"],
            "packageVersion": manifest["packageVersion"],
            "packageHash": manifest["packageHash"],
            "contentLocked": True,
            "roundTripValidated": True,
            "lockedProductionInput": source,
        }
        import_root.mkdir(parents=True, exist_ok=True)
        snapshot_path = import_root / "workshop-import-roundtrip.json"
        _atomic_json(snapshot_path, snapshot)
        persisted = _read_json(snapshot_path)
        if persisted["lockedProductionInput"] != source:
            raise ToolError("PRODUCTION_WORKSHOP_ROUNDTRIP_MISMATCH", "工坊导入往返字段不一致。")
        record = {
            "schemaVersion": "1.0.0",
            "projectId": manifest["projectId"],
            "packageVersion": manifest["packageVersion"],
            "packageHash": manifest["packageHash"],
            "snapshotPath": str(snapshot_path),
            "snapshotSha256": _sha256_file(snapshot_path),
            "roundTripValidated": True,
            "contentLocked": True,
            "adapter": "contract-adapter",
            "publishingTriggered": False,
        }
        _atomic_json(record_path, record)
        return {**record, "duplicate": False}

    def import_package(self, package_root: Path, *, target_root: Path | None = None) -> dict[str, Any]:
        package_root = package_root.resolve()
        manifest = self.validate_package(package_root)
        if self.workshop_bridge is not None:
            bridge_isolation_root = getattr(self.workshop_bridge, "isolation_root", self.root)
            target = (
                target_root.resolve()
                if target_root is not None
                else bridge_isolation_root
                / "workshop-projects"
                / manifest["projectId"]
                / manifest["packageVersion"]
            )
            result = self.workshop_bridge.import_package(
                package_root,
                target,
                expected_project_id=manifest["projectId"],
            )
            if not result.get("roundTripValidated") or result.get("publishingTriggered"):
                raise ToolError("PRODUCTION_WORKSHOP_ROUNDTRIP_MISMATCH", "工坊没有返回锁定内容往返证明。")
            return {**result, "adapter": "actual-workshop-cli"}
        target = target_root or (self.root / "workshop-projects" / manifest["projectId"] / manifest["packageVersion"])
        target = _ensure_within(self.root, target, "workshop import target")
        return self._strict_roundtrip(package_root, target)

    def start_task(
        self,
        *,
        production_task_id: Any,
        package_root: Path,
    ) -> dict[str, Any]:
        task_id = _safe_identifier(production_task_id, "productionTaskId")
        manifest = self.validate_package(package_root)
        existing_path = self._task_path(task_id)
        if existing_path.is_file():
            existing = self._load_task(task_id)
            if (
                existing.get("packageHash") == manifest["packageHash"]
                and existing.get("projectId") == manifest["projectId"]
            ):
                dispatcher = self._wake_queue_dispatcher() if existing.get("queue") else None
                return {"task": existing, "idempotent": True, "dispatcher": dispatcher}
            raise ToolError("PRODUCTION_TASK_ID_CONFLICT", "制作任务 ID 已绑定其他生产包。")
        active = self._find_active_task(manifest["projectId"], manifest["packageVersion"])
        if active:
            raise ToolError(
                "PRODUCTION_ACTIVE_TASK_EXISTS",
                "同一项目和生产包版本已经存在活动任务。",
                details={"productionTaskId": active["productionTaskId"]},
            )
        package_root = package_root.resolve()
        config = _read_json(package_root / "production_config.json")
        if bool(config.get("syntheticFixtureRunner")) != bool(manifest.get("synthetic")):
            raise ToolError(
                "PRODUCTION_SYNTHETIC_MARKER_MISMATCH",
                "syntheticFixtureRunner must match manifest.synthetic.",
            )
        if not manifest.get("synthetic") and self.workshop_bridge is None:
            raise ToolError(
                "PRODUCTION_WORKSHOP_UNAVAILABLE",
                "Non-synthetic production requires the actual Workshop 2.1 bridge.",
            )
        self._validate_environment({key: value for key, value in config.items() if key != "schemaVersion"})
        import_result = self.import_package(package_root)
        now = utc_now()
        task = {
            "schemaVersion": PRODUCTION_TASK_SCHEMA_VERSION,
            "contractType": "production-task",
            "productionTaskId": task_id,
            "projectId": manifest["projectId"],
            "productionPackageId": manifest["productionPackageId"],
            "packageVersion": manifest["packageVersion"],
            "packageHash": manifest["packageHash"],
            "packagePath": str(package_root),
            "state": "READY_TO_PRODUCE",
            "authority": "production-task-v1",
            "queueChannel": "workshop-single",
            "runId": None,
            "revision": 0,
            "createdAt": now,
            "updatedAt": now,
            "productionMode": deepcopy(config["productionMode"]),
            "deliveryMode": config["deliveryMode"],
            "synthetic": bool(manifest["synthetic"] or config.get("syntheticFixtureRunner")),
            "videoGeneration": deepcopy(config["videoGeneration"]),
            "sceneImageCadence": deepcopy(config.get("sceneImageCadence", {})),
            "settingsContractVersion": config.get("settingsContractVersion", "legacy"),
            "selectedStoryboardIds": [],
            "steps": [
                {
                    "stepId": step_id,
                    "name": name,
                    "dependencies": list(dependencies),
                    "status": "PENDING",
                    "attempts": 0,
                    "assetIds": [],
                }
                for step_id, name, dependencies in STEP_DEFINITIONS
            ],
            "assets": [],
            "fallbacks": [],
            "progress": {"completedSteps": 0, "totalSteps": len(STEP_DEFINITIONS), "completedAssets": 0, "failedAssets": 0},
            "import": import_result,
            "resultPackagePath": None,
            "jianyingDraftPackagePath": None,
            "lastIngestedExport": None,
            "history": [],
            "boundaries": {
                "readyPackageCreated": False,
                "publisherCenterCalled": False,
                "oauthExecuted": False,
                "uploadExecuted": False,
                "longTermLearningWrite": False,
            },
        }
        if config.get("settingsContractVersion") == "2.0" and not task["synthetic"]:
            task["queue"] = {
                "schemaVersion": QUEUE_SCHEMA_VERSION,
                "status": "QUEUED",
                "dispatchMode": "persistent_local_event",
                "enqueuedAt": now,
                "idempotencyKey": f"{task_id}:{manifest['packageHash']}",
                "codexHeartbeatDrivesProduction": False,
            }
        self._save_task(task, event="TASK_CREATED", details={"importAdapter": import_result.get("adapter")})
        dispatcher = self._wake_queue_dispatcher() if task.get("queue") else None
        return {"task": task, "idempotent": False, "dispatcher": dispatcher}

    def request_pause(self, task_id: Any) -> dict[str, Any]:
        task = self._load_task(task_id)
        if task["state"] not in {"RUNNING", "RETRYING", "READY_TO_PRODUCE", "QUEUED_WAITING_WORKSHOP"}:
            raise ToolError("PRODUCTION_TASK_NOT_PAUSABLE", "当前制作状态不能请求暂停。")
        task["state"] = (
            "PAUSE_REQUESTED"
            if task["state"] in {"RUNNING", "RETRYING"}
            else "PAUSED"
        )
        self._save_task(task, event="PAUSE_REQUESTED")
        return task

    def resume_task(self, task_id: Any) -> dict[str, Any]:
        task = self._load_task(task_id)
        if task["state"] == "PAUSE_REQUESTED":
            details: dict[str, Any] = {"fromState": "PAUSE_REQUESTED"}
            workshop = task.get("workshop")
            if not task.get("synthetic") and isinstance(workshop, dict) and self.workshop_bridge is not None:
                project_path_text = str(task.get("import", {}).get("projectPath") or "").strip()
                request_id = str(workshop.get("requestId") or "").strip()
                if project_path_text and request_id:
                    status = self.workshop_bridge.production_status(
                        Path(project_path_text),
                        expected_project_id=task["projectId"],
                        expected_request_id=request_id,
                    )
                    workshop["lastStatus"] = status
                    normalized_status = str(status.get("status") or "").strip().lower()
                    task_present = bool(status.get("taskPresent"))
                    details.update({"workshopStatus": normalized_status or "NOT_STARTED", "taskPresent": task_present})
                    if task_present and normalized_status in {"running", "idle", "completed"}:
                        task["state"] = "RUNNING"
                        task["runId"] = request_id
                        self._save_task(task, event="TASK_RESUMED", details=details)
                        if task.get("queue"):
                            self._wake_queue_dispatcher()
                        return task
                previous_request_id = str(workshop.get("requestId") or "").strip()
                if previous_request_id:
                    workshop["previousRequestId"] = previous_request_id
                workshop.pop("requestId", None)
                workshop.pop("lastStatus", None)
            task["state"] = "READY_TO_PRODUCE"
            task["runId"] = None
            self._save_task(task, event="TASK_RESUMED", details=details)
            if task.get("queue"):
                self._wake_queue_dispatcher()
            return task
        if task["state"] not in {"PAUSED", "NEEDS_REPAIR", "RETRYING"}:
            raise ToolError("PRODUCTION_TASK_NOT_RESUMABLE", "当前制作状态不能恢复。")
        task["state"] = "READY_TO_PRODUCE"
        task["runId"] = None
        self._save_task(task, event="TASK_RESUMED")
        if task.get("queue"):
            self._wake_queue_dispatcher()
        return task

    def retry_failed(self, task_id: Any) -> dict[str, Any]:
        task = self._load_task(task_id)
        if not task.get("synthetic") and isinstance(task.get("workshop"), dict):
            if task.get("state") not in {"FAILED", "PAUSED", "NEEDS_REPAIR", "RETRYING"}:
                raise ToolError("PRODUCTION_TASK_NOT_RETRYABLE", "真实工坊任务当前不处于失败或暂停状态。")
            previous_request_id = task["workshop"].get("requestId")
            task["workshop"]["previousRequestId"] = previous_request_id
            task["workshop"].pop("requestId", None)
            task["workshop"].pop("lastStatus", None)
            task["state"] = "RETRYING"
            task["runId"] = None
            self._save_task(
                task,
                event="WORKSHOP_RETRY_SCHEDULED",
                details={"previousRequestId": previous_request_id, "skipCompleted": True},
            )
            if task.get("queue"):
                self._wake_queue_dispatcher()
            return task
        failed_assets = [asset for asset in task["assets"] if asset.get("status") == "FAILED"]
        if not failed_assets:
            raise ToolError("PRODUCTION_NO_FAILED_ASSETS", "没有可重试的失败资产。")
        failed_steps = {asset["stepId"] for asset in failed_assets}
        for asset in failed_assets:
            asset["status"] = "PENDING"
            asset.pop("error", None)
        for step in task["steps"]:
            if step["stepId"] in failed_steps:
                step["status"] = "PENDING"
        task["state"] = "RETRYING"
        self._update_progress(task)
        self._save_task(task, event="FAILED_ASSETS_RETRY_SCHEDULED", details={"assetIds": [item["assetId"] for item in failed_assets]})
        if task.get("queue"):
            self._wake_queue_dispatcher()
        return task

    def invalidate(self, task_id: Any, *, changes: list[str]) -> dict[str, Any]:
        task = self._load_task(task_id)
        if not isinstance(changes, list) or not changes:
            raise ToolError("PRODUCTION_INVALIDATION_INVALID", "必须提供至少一个变更类型。")
        publishing_only = {"title", "description", "hashtags", "thumbnail", "publishing.title", "publishing.description", "publishing.hashtags", "publishing.thumbnail"}
        rules = {
            "script_line": {"voice-line", "audio", "storyboard", "image-prompt", "storyboard-image", "storyboard-video", "subtitles", "final-video"},
            "voice": {"audio", "storyboard", "storyboard-video", "subtitles", "final-video"},
            "visual_anchor": {"character-image", "storyboard-image", "storyboard-video", "final-video"},
            "image_style": {"storyboard-image", "storyboard-video", "final-video"},
            "video_scope": {"storyboard-video", "final-video"},
            "delivery_mode": {"final-video", "jianying-draft"},
            "render_engine": {"final-video"},
        }
        invalidated: set[str] = set()
        if all(change in publishing_only for change in changes):
            for asset in task["assets"]:
                if asset.get("assetType") == "publishing-reference":
                    asset["status"] = "INVALIDATED"
                    invalidated.add(asset["assetId"])
        else:
            affected_types: set[str] = set()
            for change in changes:
                affected_types.update(rules.get(change, set()))
            for asset in task["assets"]:
                if asset.get("assetType") in affected_types:
                    asset["status"] = "INVALIDATED"
                    invalidated.add(asset["assetId"])
            for step in task["steps"]:
                if any(asset_id in invalidated for asset_id in step["assetIds"]):
                    step["status"] = "PENDING"
            if invalidated:
                task["resultPackagePath"] = None
                workshop = task.get("workshop")
                if not task.get("synthetic") and isinstance(workshop, dict):
                    previous_request_id = str(workshop.pop("requestId", "") or "").strip()
                    if previous_request_id:
                        workshop["previousRequestId"] = previous_request_id
                    workshop.pop("lastStatus", None)
                    workshop.pop("artifactSnapshot", None)
                    task["state"] = "RETRYING"
                    task["runId"] = None
                else:
                    task["state"] = "READY_TO_PRODUCE"
        self._update_progress(task)
        self._save_task(task, event="SELECTIVE_INVALIDATION", details={"changes": changes, "assetIds": sorted(invalidated)})
        return {"task": task, "invalidatedAssetIds": sorted(invalidated), "mediaPreserved": all(change in publishing_only for change in changes)}

    def _step(self, task: dict[str, Any], step_id: str) -> dict[str, Any]:
        return next(step for step in task["steps"] if step["stepId"] == step_id)

    def _update_progress(self, task: dict[str, Any]) -> None:
        task["progress"] = {
            "completedSteps": sum(step["status"] in {"COMPLETED", "SKIPPED"} for step in task["steps"]),
            "totalSteps": len(task["steps"]),
            "completedAssets": sum(asset.get("status") == "COMPLETED" for asset in task["assets"]),
            "failedAssets": sum(asset.get("status") == "FAILED" for asset in task["assets"]),
        }

    def _existing_asset(self, task: dict[str, Any], asset_id: str) -> dict[str, Any] | None:
        return next((asset for asset in task["assets"] if asset["assetId"] == asset_id), None)

    def _register_asset(
        self,
        task: dict[str, Any],
        *,
        step_id: str,
        asset_id: str,
        asset_type: str,
        path: Path | None,
        status: str = "COMPLETED",
        input_value: Any = None,
        source: str | None = None,
        error: str | None = None,
        upstream_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        existing = self._existing_asset(task, asset_id)
        record = existing or {"assetId": asset_id, "attempts": 0}
        record.update(
            {
                "stepId": step_id,
                "assetType": asset_type,
                "status": status,
                "attempts": int(record.get("attempts", 0)) + 1,
                "source": source or ("deterministic-fixture-runner" if task["synthetic"] else "workshop"),
                "synthetic": bool(task["synthetic"]),
                "inputFingerprint": _sha256_bytes(_canonical_bytes(input_value if input_value is not None else {"assetId": asset_id})),
                "upstreamAssetIds": upstream_ids or [],
            }
        )
        if path is not None and path.is_file():
            record.update(
                {
                    "relativePath": path.relative_to(self._task_root(task["productionTaskId"])).as_posix(),
                    "sizeBytes": path.stat().st_size,
                    "sha256": _sha256_file(path),
                }
            )
        if error:
            record["error"] = error
        else:
            record.pop("error", None)
        if not existing:
            task["assets"].append(record)
        step = self._step(task, step_id)
        if asset_id not in step["assetIds"]:
            step["assetIds"].append(asset_id)
        return record

    def _run_command(self, arguments: list[str], *, code: str, timeout: int = 120) -> subprocess.CompletedProcess[str]:
        try:
            result = subprocess.run(arguments, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout, check=False)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise ToolError(code, "本地媒体工具未能完成。", retryable=True) from exc
        if result.returncode != 0:
            raise ToolError(code, "本地媒体工具返回失败。", details={"exitCode": result.returncode}, retryable=True)
        return result

    def _task_documents(self, task: dict[str, Any]) -> dict[str, dict[str, Any]]:
        root = Path(task["packagePath"])
        return {
            name: _read_json(root / name)
            for name in (
                "project.json",
                "characters.json",
                "episodes.json",
                "script_lines.json",
                "production_config.json",
                "publishing.json",
                "source_lock.json",
            )
        }

    def _complete_step(self, task: dict[str, Any], step_id: str, *, status: str = "COMPLETED") -> None:
        step = self._step(task, step_id)
        step["status"] = status
        step["attempts"] = int(step.get("attempts", 0)) + 1
        self._update_progress(task)
        self._save_task(task, event="STEP_COMPLETED", details={"stepId": step_id, "status": status})

    def _execute_p0(self, task: dict[str, Any], documents: dict[str, dict[str, Any]]) -> None:
        self.validate_package(Path(task["packagePath"]))
        self._validate_environment({key: value for key, value in documents["production_config.json"].items() if key != "schemaVersion"})
        report = {
            "status": "PASSED",
            "packageHash": task["packageHash"],
            "ffmpegAvailable": True,
            "ffprobeAvailable": True,
            "outputDirectoryWritable": True,
            "synthetic": task["synthetic"],
            "externalServiceCalls": [],
        }
        path = self._task_root(task["productionTaskId"]) / "reports" / "p0-preflight.json"
        _atomic_json(path, report)
        self._register_asset(task, step_id="P0", asset_id="preflight-report", asset_type="preflight-report", path=path, input_value=report)
        publishing_reference_path = self._task_root(task["productionTaskId"]) / "assets" / "publishing-reference.json"
        _atomic_json(publishing_reference_path, documents["publishing.json"])
        self._register_asset(
            task,
            step_id="P0",
            asset_id="publishing-reference",
            asset_type="publishing-reference",
            path=publishing_reference_path,
            input_value=documents["publishing.json"],
        )
        self._complete_step(task, "P0")

    def _execute_p1(self, task: dict[str, Any], documents: dict[str, dict[str, Any]]) -> None:
        package_root = Path(task["packagePath"])
        source = package_root / "confirmed_thumbnail.png"
        for character in documents["characters.json"]["characters"]:
            if not character.get("visualConsistencyRequired"):
                continue
            character_id = character["characterId"]
            path = self._task_root(task["productionTaskId"]) / "assets" / "characters" / f"{character_id}.png"
            _write_copy(source, path)
            self._register_asset(
                task,
                step_id="P1",
                asset_id=f"character-image-{character_id}",
                asset_type="character-image",
                path=path,
                input_value={"visualAnchor": character.get("visualAnchorPromptZh"), "syntheticPlaceholder": task["synthetic"]},
            )
        self._complete_step(task, "P1")

    def _execute_p2(self, task: dict[str, Any], documents: dict[str, dict[str, Any]]) -> None:
        required = [character for character in documents["characters.json"]["characters"] if character.get("visualConsistencyRequired")]
        issues = []
        for character in required:
            asset = self._existing_asset(task, f"character-image-{character['characterId']}")
            if not asset or asset.get("status") != "COMPLETED":
                issues.append(character["characterId"])
        report = {"status": "PASSED" if not issues else "FAILED", "missingCharacterIds": issues, "synthetic": task["synthetic"]}
        path = self._task_root(task["productionTaskId"]) / "reports" / "p2-character-quality.json"
        _atomic_json(path, report)
        self._register_asset(task, step_id="P2", asset_id="character-quality-report", asset_type="quality-report", path=path, input_value=report)
        if issues:
            raise ToolError("PRODUCTION_CHARACTER_ASSET_INVALID", "主要角色资产质量门失败。")
        self._complete_step(task, "P2")

    def _execute_p3(self, task: dict[str, Any], documents: dict[str, dict[str, Any]]) -> None:
        characters = {item["characterId"]: item for item in documents["characters.json"]["characters"]}
        rows = []
        for line in documents["script_lines.json"]["lines"]:
            if line.get("lineType") == "sound_effect":
                rows.append(
                    {
                        **deepcopy(line),
                        "voice": {
                            "engineId": "seed_audio",
                            "modelId": documents["production_config.json"]["soundEffects"]["modelId"],
                            "bindingStatus": "SOUND_EFFECT_ENGINE_BOUND",
                        },
                    }
                )
                continue
            speaker = characters.get(line["speakerId"])
            if not speaker or not isinstance(speaker.get("voice"), dict):
                raise ToolError("PRODUCTION_VOICE_BINDING_MISSING", "正式文稿行说话人没有锁定音色。")
            rows.append({**deepcopy(line), "voice": deepcopy(speaker["voice"])})
        document = {"schemaVersion": "1.0.0", "mode": "validate-and-bind-only", "contentLocked": True, "lines": rows}
        path = self._task_root(task["productionTaskId"]) / "assets" / "voice-lines.json"
        _atomic_json(path, document)
        self._register_asset(task, step_id="P3", asset_id="voice-lines", asset_type="voice-line", path=path, input_value=document)
        self._complete_step(task, "P3")

    def _execute_p4(self, task: dict[str, Any], documents: dict[str, dict[str, Any]]) -> None:
        audio_root = self._task_root(task["productionTaskId"]) / "assets" / "audio"
        audio_root.mkdir(parents=True, exist_ok=True)
        for index, line in enumerate(documents["script_lines.json"]["lines"], 1):
            asset_id = f"audio-{line['lineId']}"
            existing = self._existing_asset(task, asset_id)
            if existing and existing.get("status") == "COMPLETED":
                continue
            path = audio_root / f"{line['lineId']}.wav"
            frequency = 360 + index * 20
            duration_seconds = float(line.get("durationSeconds", 0.75)) if line.get("lineType") == "sound_effect" else 0.75
            self._run_command(
                [
                    self.ffmpeg_path,
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-y",
                    "-f",
                    "lavfi",
                    "-i",
                    f"sine=frequency={frequency}:sample_rate=48000:duration={duration_seconds:.3f}",
                    "-c:a",
                    "pcm_s16le",
                    str(path),
                ],
                code="PRODUCTION_SYNTHETIC_AUDIO_FAILED",
            )
            self._register_asset(task, step_id="P4", asset_id=asset_id, asset_type="audio", path=path, input_value=line)
        self._complete_step(task, "P4")

    def _execute_p5(self, task: dict[str, Any], documents: dict[str, dict[str, Any]]) -> None:
        storyboards = []
        cursor = 0.0
        lines = documents["script_lines.json"]["lines"]
        line_by_id = {line["lineId"]: line for line in lines}
        scene_plans = documents["production_config.json"].get("codexVisualPlan", {}).get("scenePlans", [])
        grouped_lines: list[tuple[str, list[dict[str, Any]]]] = []
        if scene_plans:
            for scene in scene_plans:
                grouped_lines.append((scene["sceneId"], [line_by_id[line_id] for line_id in scene["scriptLineIds"]]))
        else:
            pending_effects: list[dict[str, Any]] = []
            for line in lines:
                if line.get("lineType") == "sound_effect":
                    pending_effects.append(line)
                    continue
                grouped_lines.append((f"SB-{line['lineId']}", [*pending_effects, line]))
                pending_effects = []
            if pending_effects and grouped_lines:
                grouped_lines[-1][1].extend(pending_effects)
        for storyboard_id, group in grouped_lines:
            duration_seconds = sum(
                float(line.get("durationSeconds", 0.75)) if line.get("lineType") == "sound_effect" else 0.75
                for line in group
            )
            storyboards.append(
                {
                    "storyboardId": storyboard_id,
                    "episodeNumber": group[0]["episodeNumber"],
                    "lineIds": [line["lineId"] for line in group],
                    "speakerIds": [line["speakerId"] for line in group if line.get("lineType") != "sound_effect"],
                    "audioAssetIds": [f"audio-{line['lineId']}" for line in group],
                    "startSeconds": round(cursor, 3),
                    "durationSeconds": round(duration_seconds, 3),
                }
            )
            cursor += duration_seconds
        document = {"schemaVersion": "1.0.0", "storyboards": storyboards, "durationSeconds": round(cursor, 3)}
        path = self._task_root(task["productionTaskId"]) / "assets" / "storyboards.json"
        _atomic_json(path, document)
        self._register_asset(task, step_id="P5", asset_id="storyboards", asset_type="storyboard", path=path, input_value=document, upstream_ids=[asset["assetId"] for asset in task["assets"] if asset["assetType"] == "audio"])
        self._complete_step(task, "P5")

    def _execute_p6(self, task: dict[str, Any], documents: dict[str, dict[str, Any]]) -> None:
        storyboards = _read_json(self._task_root(task["productionTaskId"]) / "assets" / "storyboards.json")["storyboards"]
        prompts = []
        for storyboard in storyboards:
            prompts.append(
                {
                    "storyboardId": storyboard["storyboardId"],
                    "promptZh": "合成验收画面，16:9，清晰主体，保持角色视觉锚点；不代表真实模型调用。",
                    "factsLocked": True,
                    "synthetic": task["synthetic"],
                }
            )
        document = {"schemaVersion": "1.0.0", "status": "PASSED", "prompts": prompts}
        path = self._task_root(task["productionTaskId"]) / "assets" / "image-prompts.json"
        _atomic_json(path, document)
        self._register_asset(task, step_id="P6", asset_id="image-prompts", asset_type="image-prompt", path=path, input_value=document, upstream_ids=["storyboards"])
        self._complete_step(task, "P6")

    def _execute_p7(self, task: dict[str, Any], documents: dict[str, dict[str, Any]]) -> None:
        storyboards = _read_json(self._task_root(task["productionTaskId"]) / "assets" / "storyboards.json")["storyboards"]
        source = Path(task["packagePath"]) / "confirmed_thumbnail.png"
        for storyboard in storyboards:
            storyboard_id = storyboard["storyboardId"]
            path = self._task_root(task["productionTaskId"]) / "assets" / "storyboard-images" / f"{storyboard_id}.png"
            if not path.is_file():
                _write_copy(source, path)
            self._register_asset(task, step_id="P7", asset_id=f"storyboard-image-{storyboard_id}", asset_type="storyboard-image", path=path, input_value={"storyboard": storyboard, "synthetic": task["synthetic"]}, upstream_ids=["image-prompts"])
        self._complete_step(task, "P7")

    def _selected_storyboards(self, storyboards: list[dict[str, Any]], video: dict[str, Any]) -> list[str]:
        if not video["enabled"] or video["selectionMode"] == "none":
            return []
        if video["selectionMode"] == "all_storyboards":
            return [item["storyboardId"] for item in storyboards]
        count = video["count"]
        if video["selectionMode"] == "project_first_n_storyboards":
            return [item["storyboardId"] for item in storyboards[:count]]
        selected: list[str] = []
        episodes = sorted({item["episodeNumber"] for item in storyboards})
        for episode in episodes:
            selected.extend(item["storyboardId"] for item in [value for value in storyboards if value["episodeNumber"] == episode][:count])
        return selected

    def _execute_p8(
        self,
        task: dict[str, Any],
        documents: dict[str, dict[str, Any]],
        *,
        fail_storyboard_ids: set[str],
    ) -> bool:
        storyboards = _read_json(self._task_root(task["productionTaskId"]) / "assets" / "storyboards.json")["storyboards"]
        video_config = documents["production_config.json"]["videoGeneration"]
        selected = self._selected_storyboards(storyboards, video_config)
        task["selectedStoryboardIds"] = selected
        task["videoGeneration"]["selectedStoryboardIds"] = selected
        failed = False
        for storyboard_id in selected:
            asset_id = f"storyboard-video-{storyboard_id}"
            existing = self._existing_asset(task, asset_id)
            if existing and existing.get("status") == "COMPLETED":
                continue
            image_path = self._task_root(task["productionTaskId"]) / "assets" / "storyboard-images" / f"{storyboard_id}.png"
            video_path = self._task_root(task["productionTaskId"]) / "assets" / "storyboard-videos" / f"{storyboard_id}.mp4"
            upstream_ids = [f"storyboard-image-{storyboard_id}"]
            if video_config.get("frameInputMode") == "first_last_frame":
                end_frame_path = self._task_root(task["productionTaskId"]) / "assets" / "storyboard-end-frames" / f"{storyboard_id}.png"
                if not end_frame_path.is_file():
                    _write_copy(image_path, end_frame_path)
                end_frame_asset_id = f"storyboard-end-frame-{storyboard_id}"
                self._register_asset(
                    task,
                    step_id="P8",
                    asset_id=end_frame_asset_id,
                    asset_type="storyboard-end-frame",
                    path=end_frame_path,
                    input_value={"storyboardId": storyboard_id, "source": "dedicated_generated", "synthetic": task["synthetic"]},
                    upstream_ids=[f"storyboard-image-{storyboard_id}"],
                )
                upstream_ids.append(end_frame_asset_id)
            if storyboard_id in fail_storyboard_ids:
                if video_config["fallbackPolicy"] == "use_static_image":
                    task["fallbacks"].append({"storyboardId": storyboard_id, "mode": "use_static_image", "reason": "synthetic injected video failure"})
                    self._register_asset(task, step_id="P8", asset_id=asset_id, asset_type="storyboard-video", path=None, status="COMPLETED", input_value={"storyboardId": storyboard_id}, source="authorized-static-fallback")
                    continue
                self._register_asset(task, step_id="P8", asset_id=asset_id, asset_type="storyboard-video", path=None, status="FAILED", input_value={"storyboardId": storyboard_id}, error="VIDEO_GENERATION_FAILED_AND_FALLBACK_NOT_AUTHORIZED")
                failed = True
                continue
            self._render_media(image_path, video_path, duration_seconds=0.75, width=documents["production_config.json"]["width"], height=documents["production_config.json"]["height"], frame_rate=documents["production_config.json"]["frameRate"])
            self._register_asset(task, step_id="P8", asset_id=asset_id, asset_type="storyboard-video", path=video_path, input_value={"storyboardId": storyboard_id, "videoConfig": video_config}, upstream_ids=upstream_ids)
        if failed:
            step = self._step(task, "P8")
            step["status"] = "FAILED"
            step["attempts"] += 1
            task["state"] = "PAUSED"
            self._update_progress(task)
            self._save_task(task, event="VIDEO_FAILURE_PAUSED", details={"failedStoryboardIds": sorted(fail_storyboard_ids & set(selected))})
            return False
        self._complete_step(task, "P8", status="SKIPPED" if not selected else "COMPLETED")
        return True

    def _execute_p9(self, task: dict[str, Any], documents: dict[str, dict[str, Any]]) -> None:
        failed = [asset["assetId"] for asset in task["assets"] if asset.get("status") == "FAILED"]
        report = {
            "schemaVersion": "1.0.0",
            "status": "PASSED" if not failed else "FAILED",
            "failedAssetIds": failed,
            "selectedStoryboardIds": task["selectedStoryboardIds"],
            "frameInputMode": documents["production_config.json"]["videoGeneration"].get("frameInputMode", "first_frame"),
            "fallbacks": task["fallbacks"],
            "synthetic": task["synthetic"],
        }
        path = self._task_root(task["productionTaskId"]) / "reports" / "p9-asset-diagnostics.json"
        _atomic_json(path, report)
        self._register_asset(task, step_id="P9", asset_id="asset-diagnostics", asset_type="quality-report", path=path, input_value=report)
        if failed:
            raise ToolError("PRODUCTION_ASSET_DIAGNOSTICS_FAILED", "素材诊断发现失败资产。")
        self._complete_step(task, "P9")

    def _render_media(self, image_path: Path, output_path: Path, *, duration_seconds: float, width: int, height: int, frame_rate: int) -> None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        self._run_command(
            [
                self.ffmpeg_path,
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-loop",
                "1",
                "-i",
                str(image_path),
                "-f",
                "lavfi",
                "-i",
                f"sine=frequency=440:sample_rate=48000:duration={duration_seconds:.3f}",
                "-t",
                f"{duration_seconds:.3f}",
                "-vf",
                f"scale={width}:{height}:force_original_aspect_ratio=decrease,pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,format=yuv420p",
                "-r",
                str(frame_rate),
                "-c:v",
                "libx264",
                "-preset",
                "ultrafast",
                "-c:a",
                "aac",
                "-map_metadata",
                "-1",
                "-shortest",
                str(output_path),
            ],
            code="PRODUCTION_RENDER_FAILED",
        )

    @staticmethod
    def _srt_timestamp(seconds: float) -> str:
        milliseconds = round(seconds * 1000)
        hours, remainder = divmod(milliseconds, 3_600_000)
        minutes, remainder = divmod(remainder, 60_000)
        secs, millis = divmod(remainder, 1000)
        return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"

    def _write_subtitles(self, task: dict[str, Any], lines: list[dict[str, Any]], root: Path) -> tuple[Path, Path]:
        srt_parts: list[str] = []
        timeline = []
        cursor = 0.0
        cue = 0
        for index, line in enumerate(lines, 1):
            start = cursor
            duration_seconds = float(line.get("durationSeconds", 0.75)) if line.get("lineType") == "sound_effect" else 0.75
            end = cursor + duration_seconds
            subtitle_cue: int | None = None
            if line.get("lineType") != "sound_effect":
                cue += 1
                subtitle_cue = cue
                srt_parts.extend([str(cue), f"{self._srt_timestamp(start)} --> {self._srt_timestamp(end)}", line["text"], ""])
            timeline.append(
                {
                    "cue": subtitle_cue,
                    "lineId": line["lineId"],
                    "episodeNumber": line["episodeNumber"],
                    "speakerId": line["speakerId"],
                    "lineType": line.get("lineType"),
                    "startSeconds": round(start, 3),
                    "endSeconds": round(end, 3),
                    "textHash": _sha256_bytes(line["text"].encode("utf-8")),
                }
            )
            cursor = end
        srt_path = root / "subtitles.srt"
        timeline_path = root / "timeline-map.json"
        _atomic_bytes(srt_path, (("\n".join(srt_parts).rstrip() + "\n") if srt_parts else "").encode("utf-8"))
        _atomic_json(timeline_path, {"schemaVersion": "1.0.0", "language": _read_json(Path(task["packagePath"]) / "script_lines.json")["language"], "durationSeconds": round(cursor, 3), "items": timeline})
        return srt_path, timeline_path

    def _execute_p10_auto(self, task: dict[str, Any], documents: dict[str, dict[str, Any]]) -> None:
        output_root = self._task_root(task["productionTaskId"]) / "render"
        output_root.mkdir(parents=True, exist_ok=True)
        lines = documents["script_lines.json"]["lines"]
        duration = max(
            sum(
                float(line.get("durationSeconds", 0.75)) if line.get("lineType") == "sound_effect" else 0.75
                for line in lines
            ),
            1.0,
        )
        video_path = output_root / "final-video.mp4"
        self._render_media(
            Path(task["packagePath"]) / "confirmed_thumbnail.png",
            video_path,
            duration_seconds=duration,
            width=documents["production_config.json"]["width"],
            height=documents["production_config.json"]["height"],
            frame_rate=documents["production_config.json"]["frameRate"],
        )
        srt_path, timeline_path = self._write_subtitles(task, lines, output_root)
        self._register_asset(task, step_id="P10", asset_id="final-video", asset_type="final-video", path=video_path, input_value={"packageHash": task["packageHash"], "deliveryMode": "auto_render"}, upstream_ids=[asset["assetId"] for asset in task["assets"] if asset["assetType"] in {"audio", "storyboard-image", "storyboard-video"}])
        self._register_asset(task, step_id="P10", asset_id="subtitles", asset_type="subtitles", path=srt_path, input_value=lines)
        self._register_asset(task, step_id="P10", asset_id="timeline-map", asset_type="timeline-map", path=timeline_path, input_value=lines)
        task["state"] = "AUTO_RENDERING"
        self._complete_step(task, "P10")

    def _create_jianying_draft(self, task: dict[str, Any], documents: dict[str, dict[str, Any]]) -> Path:
        draft_root = self._task_root(task["productionTaskId"]) / "jianying-draft-package"
        media_root = draft_root / "media"
        media_root.mkdir(parents=True, exist_ok=True)
        lines = documents["script_lines.json"]["lines"]
        srt_path, timeline_path = self._write_subtitles(task, lines, draft_root)
        _write_copy(Path(task["packagePath"]) / "confirmed_thumbnail.png", media_root / "confirmed_thumbnail.png")
        for audio_asset in [asset for asset in task["assets"] if asset["assetType"] == "audio" and asset.get("status") == "COMPLETED"]:
            source = self._task_root(task["productionTaskId"]) / audio_asset["relativePath"]
            _write_copy(source, media_root / "audio" / source.name)
        native_track = {
            "schemaVersion": "1.0.0",
            "trackType": "jianying-native-subtitle-track",
            "language": documents["script_lines.json"]["language"],
            "sourceSrt": "subtitles.srt",
            "items": [item for item in _read_json(timeline_path)["items"] if item.get("cue") is not None],
            "ordinaryTextTrack": False,
        }
        _atomic_json(draft_root / "native-subtitle-track.json", native_track)
        draft_meta = {
            "schemaVersion": "1.0.0",
            "packageType": "jianying-draft-package-v1",
            "projectId": task["projectId"],
            "productionTaskId": task["productionTaskId"],
            "packageVersion": task["packageVersion"],
            "packageHash": task["packageHash"],
            "contentLocked": True,
            "selfContained": True,
            "launchJianying": False,
            "synthetic": task["synthetic"],
        }
        _atomic_json(draft_root / "draft-meta.json", draft_meta)
        _atomic_json(
            draft_root / "export-request.json",
            {
                "projectId": task["projectId"],
                "productionTaskId": task["productionTaskId"],
                "packageHash": task["packageHash"],
                "requiredSidecarName": "export-identity.json",
            },
        )
        files = []
        for path in sorted((item for item in draft_root.rglob("*") if item.is_file() and item.name != "manifest.json"), key=lambda item: item.relative_to(draft_root).as_posix()):
            files.append(
                {
                    "path": path.relative_to(draft_root).as_posix(),
                    "sizeBytes": path.stat().st_size,
                    "sha256": _sha256_file(path),
                }
            )
        manifest = {"schemaVersion": "1.0.0", "packageType": "jianying-draft-package-v1", "projectId": task["projectId"], "productionTaskId": task["productionTaskId"], "packageHash": task["packageHash"], "status": "AWAITING_JIANYING_EXPORT", "files": files, "synthetic": task["synthetic"]}
        manifest["contentHash"] = _sha256_bytes(_canonical_bytes({key: value for key, value in manifest.items() if key != "contentHash"}))
        _atomic_json(draft_root / "manifest.json", manifest)
        return draft_root

    def _execute_p10_jianying(self, task: dict[str, Any], documents: dict[str, dict[str, Any]]) -> None:
        draft_root = self._create_jianying_draft(task, documents)
        manifest = _read_json(draft_root / "manifest.json")
        self._register_asset(task, step_id="P10", asset_id="jianying-draft", asset_type="jianying-draft", path=draft_root / "manifest.json", input_value=manifest)
        self._register_asset(task, step_id="P10", asset_id="subtitles", asset_type="subtitles", path=draft_root / "subtitles.srt", input_value=documents["script_lines.json"]["lines"])
        self._register_asset(task, step_id="P10", asset_id="timeline-map", asset_type="timeline-map", path=draft_root / "timeline-map.json", input_value=documents["script_lines.json"]["lines"])
        task["jianyingDraftPackagePath"] = str(draft_root)
        task["state"] = "AWAITING_JIANYING_EXPORT"
        self._complete_step(task, "P10")

    def validate_video(
        self,
        *,
        video_path: Path,
        subtitles_path: Path,
        timeline_path: Path,
        expected_lines: list[dict[str, Any]],
        expected_width: int,
        expected_height: int,
    ) -> dict[str, Any]:
        if not video_path.is_file() or video_path.stat().st_size == 0:
            raise ToolError("PRODUCTION_VIDEO_INVALID", "最终 MP4 不存在或为空。")
        probe = self._run_command(
            [self.ffprobe_path, "-v", "error", "-show_streams", "-show_format", "-of", "json", str(video_path)],
            code="PRODUCTION_VIDEO_DECODE_FAILED",
        )
        try:
            document = json.loads(probe.stdout)
        except json.JSONDecodeError as exc:
            raise ToolError("PRODUCTION_VIDEO_DECODE_FAILED", "ffprobe 返回无效 JSON。") from exc
        streams = document.get("streams", [])
        video_streams = [stream for stream in streams if stream.get("codec_type") == "video"]
        audio_streams = [stream for stream in streams if stream.get("codec_type") == "audio"]
        if not video_streams or not audio_streams:
            raise ToolError("PRODUCTION_VIDEO_STREAMS_INVALID", "最终 MP4 必须同时包含视频流和音频流。")
        video = video_streams[0]
        actual_width = int(video.get("width") or 0)
        actual_height = int(video.get("height") or 0)
        if (
            expected_width * 9 != expected_height * 16
            or actual_width * 9 != actual_height * 16
            or actual_width < expected_width
            or actual_height < expected_height
        ):
            raise ToolError("PRODUCTION_VIDEO_DIMENSIONS_INVALID", "最终 MP4 分辨率低于预设或画幅不符合 16:9。")
        try:
            duration = float(document.get("format", {}).get("duration") or video.get("duration") or 0)
        except (TypeError, ValueError):
            duration = 0
        if duration <= 0:
            raise ToolError("PRODUCTION_VIDEO_DURATION_INVALID", "最终 MP4 时长无效。")
        if not subtitles_path.is_file() or not timeline_path.is_file():
            raise ToolError("PRODUCTION_SUBTITLES_INVALID", "目标语言字幕或时间轴映射不存在。")
        timeline = _read_json(timeline_path, "PRODUCTION_SUBTITLES_INVALID")
        items = timeline.get("items")
        if not isinstance(items, list) or [item.get("lineId") for item in items] != [line.get("lineId") for line in expected_lines]:
            raise ToolError("PRODUCTION_SUBTITLE_MAPPING_MISMATCH", "字幕行 ID 映射与正式母稿不一致。")
        if [item.get("speakerId") for item in items] != [line.get("speakerId") for line in expected_lines]:
            raise ToolError("PRODUCTION_SUBTITLE_MAPPING_MISMATCH", "字幕说话人映射与正式母稿不一致。")
        for item, line in zip(items, expected_lines, strict=True):
            if item.get("textHash") != _sha256_bytes(line["text"].encode("utf-8")) or item.get("endSeconds", 0) <= item.get("startSeconds", 0):
                raise ToolError("PRODUCTION_SUBTITLE_MAPPING_MISMATCH", "字幕文本或时间轴映射无效。")
        srt_text = subtitles_path.read_text(encoding="utf-8-sig")
        subtitle_text_parts: list[str] = []
        for block in re.split(r"\r?\n\s*\r?\n", srt_text.strip()):
            rows = block.splitlines()
            time_index = next((index for index, row in enumerate(rows) if "-->" in row), None)
            if time_index is not None:
                subtitle_text_parts.extend(rows[time_index + 1 :])
        normalized_subtitles = re.sub(r"\s+", "", "".join(subtitle_text_parts))
        spoken_lines = [line for line in expected_lines if line.get("lineType") != "sound_effect"]
        if not _subtitles_cover_spoken_lines_in_order(normalized_subtitles, spoken_lines):
            raise ToolError("PRODUCTION_SUBTITLE_MAPPING_MISMATCH", "SRT 没有按原顺序完整包含目标语言正式母稿。")
        expected_duration = float(timeline.get("durationSeconds", 0))
        if abs(duration - expected_duration) > max(1.0, expected_duration * 0.2):
            raise ToolError("PRODUCTION_TIMELINE_DURATION_MISMATCH", "成片时长与字幕时间轴超出允许误差。")
        return {
            "schemaVersion": "1.0.0",
            "status": "PASSED",
            "decodePassed": True,
            "videoStreamCount": len(video_streams),
            "audioStreamCount": len(audio_streams),
            "width": video["width"],
            "height": video["height"],
            "configuredMinimumWidth": expected_width,
            "configuredMinimumHeight": expected_height,
            "resolutionUpgradeApplied": actual_width > expected_width or actual_height > expected_height,
            "aspectRatio": "16:9",
            "frameRate": video.get("avg_frame_rate"),
            "videoCodec": video.get("codec_name"),
            "audioCodec": audio_streams[0].get("codec_name"),
            "durationSeconds": round(duration, 3),
            "subtitleCueCount": len(spoken_lines),
            "timelineMapped": True,
            "videoSha256": _sha256_file(video_path),
            "subtitlesSha256": _sha256_file(subtitles_path),
            "timelineMapSha256": _sha256_file(timeline_path),
        }

    @staticmethod
    def _workshop_selected_steps(config: dict[str, Any]) -> list[str]:
        steps = [
            "character_images",
            "voice_matching",
            "character_assets_gate",
            "audio",
            "storyboard",
        ]
        prompt_generation = config.get("promptGeneration")
        workshop_prompt_generation = config.get("workshopPromptGeneration")
        if (
            isinstance(prompt_generation, dict)
            and bool(prompt_generation.get("image") or prompt_generation.get("video"))
        ) or (
            isinstance(workshop_prompt_generation, dict)
            and bool(workshop_prompt_generation.get("image") or workshop_prompt_generation.get("video"))
        ):
            steps.append("image_prompts")
        steps.append("grid_image")
        if bool(config.get("videoGeneration", {}).get("enabled")):
            steps.append("video")
        steps.append("diagnostics")
        steps.append("export" if config.get("deliveryMode") == "jianying_refine" else "final_render")
        return steps

    @staticmethod
    def _workshop_selective_rework_scope(task: dict[str, Any], project_path: Path) -> dict[str, Any] | None:
        """Load a one-project selective retry contract without broadening its scope."""

        if str(task.get("state") or "").strip().upper() not in {"RETRYING", "READY_TO_PRODUCE"}:
            return None
        scope_path = project_path.parent / "selective-rework-scope.json"
        if not scope_path.is_file():
            return None
        try:
            scope = json.loads(scope_path.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ToolError(
                "PRODUCTION_SELECTIVE_REWORK_SCOPE_INVALID",
                "选择性恢复清单无法读取，已阻止回退为全流程重跑。",
                details={"scopePath": str(scope_path)},
            ) from exc
        if not isinstance(scope, dict):
            raise ToolError(
                "PRODUCTION_SELECTIVE_REWORK_SCOPE_INVALID",
                "选择性恢复清单格式无效，已阻止回退为全流程重跑。",
                details={"scopePath": str(scope_path)},
            )

        project_id = str(task.get("projectId") or "").strip()
        command = scope.get("command") if isinstance(scope.get("command"), dict) else {}
        steps = [str(item).strip() for item in command.get("steps", [])]
        episodes = [str(item).strip() for item in command.get("episodes", [])]
        hard_exclusions = {str(item).strip() for item in scope.get("hardExclusions", [])}
        allowed_steps = {
            "character_images",
            "voice_matching",
            "character_assets_gate",
            "audio",
            "storyboard",
            "image_prompts",
            "grid_image",
            "video",
            "diagnostics",
            "export",
            "final_render",
        }
        authorization = str(scope.get("automaticRemainingWorkflowAuthorization") or "").strip()
        invalid = (
            str(scope.get("projectId") or "").strip() != project_id
            or str(scope.get("authorizationBoundToProjectId") or "").strip() != project_id
            or not authorization.endswith(":auto-remaining-workflow")
            or bool(scope.get("uploadAuthorized"))
            or not bool(command.get("skipCompleted"))
            or not steps
            or any(step not in allowed_steps for step in steps)
            or any(step in hard_exclusions for step in steps)
            or not episodes
        )
        if invalid:
            raise ToolError(
                "PRODUCTION_SELECTIVE_REWORK_SCOPE_INVALID",
                "选择性恢复清单与当前项目或授权不匹配，已阻止扩大重试范围。",
                details={"scopePath": str(scope_path), "projectId": project_id},
            )
        return {
            "path": str(scope_path.resolve()),
            "sha256": _sha256_file(scope_path),
            "selectedStepIds": steps,
            "selectedEpisodeIds": episodes,
            "skipCompleted": True,
            "authorization": authorization,
        }

    @staticmethod
    def _srt_end_seconds(path: Path) -> float:
        text = path.read_text(encoding="utf-8-sig")
        matches = re.findall(r"-->\s*(\d{2}):(\d{2}):(\d{2})[,.](\d{3})", text)
        if not matches:
            raise ToolError("PRODUCTION_SUBTITLES_INVALID", "工坊 SRT 不包含可解析的时间轴。")
        hour, minute, second, millisecond = matches[-1]
        return int(hour) * 3600 + int(minute) * 60 + int(second) + int(millisecond) / 1000

    def _write_workshop_timeline(
        self,
        task: dict[str, Any],
        documents: dict[str, dict[str, Any]],
        workshop_snapshot: dict[str, Any],
        subtitle_path: Path,
        destination: Path,
    ) -> Path:
        lines = documents["script_lines.json"]["lines"]
        workshop_lines = {
            item.get("lineId"): item
            for item in workshop_snapshot.get("scriptLines", [])
            if isinstance(item, dict) and item.get("lineId")
        }
        duration_total = self._srt_end_seconds(subtitle_path)
        weights = []
        for line in lines:
            item = workshop_lines.get(line["lineId"], {})
            try:
                duration = float(item.get("durationSeconds") or 0)
            except (TypeError, ValueError):
                duration = 0
            weights.append(max(duration, 0.01))
        weight_total = sum(weights)
        cursor = 0.0
        timeline_items = []
        for index, (line, weight) in enumerate(zip(lines, weights, strict=True), 1):
            start = cursor
            end = duration_total if index == len(lines) else cursor + duration_total * weight / weight_total
            timeline_items.append(
                {
                    "cue": index,
                    "lineId": line["lineId"],
                    "episodeNumber": line["episodeNumber"],
                    "speakerId": line["speakerId"],
                    "startSeconds": round(start, 3),
                    "endSeconds": round(end, 3),
                    "textHash": _sha256_bytes(line["text"].encode("utf-8")),
                }
            )
            cursor = end
        _atomic_json(
            destination,
            {
                "schemaVersion": "1.0.0",
                "language": documents["script_lines.json"]["language"],
                "durationSeconds": round(duration_total, 3),
                "items": timeline_items,
                "source": "workshop-script-line-durations-scaled-to-final-srt",
            },
        )
        return destination

    def _write_workshop_validation_subtitles(
        self,
        documents: dict[str, dict[str, Any]],
        workshop_snapshot: dict[str, Any],
        destination: Path,
    ) -> Path:
        """Build an audit-only SRT when the final video intentionally has no subtitles.

        The sidecar is used only by the Stage 5 line-order and duration checks;
        it is never burned into the completed MP4.
        """

        lines = documents["script_lines.json"]["lines"]
        workshop_lines = {
            str(item.get("lineId") or ""): item
            for item in workshop_snapshot.get("scriptLines", [])
            if isinstance(item, dict) and str(item.get("lineId") or "").strip()
        }
        try:
            duration_total = float((workshop_snapshot.get("uploadReport") or {}).get("durationSec") or 0)
        except (TypeError, ValueError):
            duration_total = 0
        if duration_total <= 0:
            raise ToolError("PRODUCTION_VIDEO_DURATION_INVALID", "无字幕工坊报告缺少有效成片时长。")

        weights: list[float] = []
        for line in lines:
            item = workshop_lines.get(str(line.get("lineId") or ""), {})
            try:
                duration = float(item.get("durationSeconds") or 0)
            except (TypeError, ValueError):
                duration = 0
            weights.append(max(duration, 0.01))
        weight_total = sum(weights)
        cursor = 0.0
        cue = 0
        parts: list[str] = []
        for index, (line, weight) in enumerate(zip(lines, weights, strict=True), 1):
            start = cursor
            end = duration_total if index == len(lines) else cursor + duration_total * weight / weight_total
            if line.get("lineType") != "sound_effect":
                cue += 1
                parts.extend(
                    [
                        str(cue),
                        f"{self._srt_timestamp(start)} --> {self._srt_timestamp(end)}",
                        str(line.get("text") or ""),
                        "",
                    ]
                )
            cursor = end
        if cue == 0:
            raise ToolError("PRODUCTION_SUBTITLES_INVALID", "正式母稿没有可用于技术验收的人声文本。")
        _atomic_bytes(destination, ("\n".join(parts).rstrip() + "\n").encode("utf-8"))
        return destination

    def _sample_video_frames(self, task: dict[str, Any], video_path: Path, duration_seconds: float) -> dict[str, Any]:
        sample_root = self._task_root(task["productionTaskId"]) / "reports" / "frame-samples"
        sample_root.mkdir(parents=True, exist_ok=True)
        hashes: list[str] = []
        for index, ratio in enumerate((0.1, 0.3, 0.5, 0.7, 0.9), 1):
            output = sample_root / f"frame-{index:02d}.png"
            self._run_command(
                [
                    self.ffmpeg_path,
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-y",
                    "-ss",
                    f"{max(0.0, duration_seconds * ratio):.3f}",
                    "-i",
                    str(video_path),
                    "-frames:v",
                    "1",
                    "-vf",
                    "scale=320:-2",
                    str(output),
                ],
                code="PRODUCTION_FRAME_SAMPLE_FAILED",
            )
            if not output.is_file() or output.stat().st_size == 0:
                raise ToolError("PRODUCTION_FRAME_SAMPLE_FAILED", "无法从正式成片抽取技术验收帧。")
            hashes.append(_sha256_file(output))
        return {
            "sampleCount": len(hashes),
            "uniqueFrameCount": len(set(hashes)),
            "frameHashes": hashes,
        }

    def _workshop_media_integrity(
        self,
        task: dict[str, Any],
        workshop_snapshot: dict[str, Any],
        *,
        video_path: Path,
        duration_seconds: float,
    ) -> dict[str, Any]:
        images = workshop_snapshot.get("storyboardImages", [])
        image_hashes = [str(item.get("sha256") or "") for item in images if isinstance(item, dict)]
        total = len(image_hashes)
        unique = len(set(image_hashes))
        duplicates = total - unique
        duplicate_ratio = duplicates / total if total else 1.0
        if total == 0 or (total > 1 and (unique < 2 or duplicate_ratio > 0.5)):
            raise ToolError(
                "PRODUCTION_STORYBOARD_IMAGE_INTEGRITY_FAILED",
                "分镜图片缺失或大面积精确重复，已阻止把占位画面当作正式成片。",
                details={
                    "totalStoryboardImages": total,
                    "uniqueImageCount": unique,
                    "exactDuplicateRatio": round(duplicate_ratio, 6),
                },
            )
        frame_samples = self._sample_video_frames(task, video_path, duration_seconds)
        if total > 1 and frame_samples["uniqueFrameCount"] < 2:
            raise ToolError(
                "PRODUCTION_FINAL_VIDEO_VISUAL_CHANGE_FAILED",
                "最终视频抽样画面没有任何变化，已阻止静态占位成片进入发布中心。",
            )
        return {
            "status": "PASSED",
            "provenance": "workshop",
            "placeholderRunnerUsed": False,
            "totalStoryboardImages": total,
            "uniqueImageCount": unique,
            "exactDuplicateCount": duplicates,
            "exactDuplicateRatio": round(duplicate_ratio, 6),
            **frame_samples,
        }

    def _ingest_workshop_completion(
        self,
        task: dict[str, Any],
        documents: dict[str, dict[str, Any]],
        snapshot: dict[str, Any],
    ) -> dict[str, Any]:
        render_root = self._task_root(task["productionTaskId"]) / "render"
        render_root.mkdir(parents=True, exist_ok=True)
        video_path = render_root / "final-video.mp4"
        subtitle_path = render_root / "subtitles.srt"
        _write_copy(Path(snapshot["finalVideoPath"]), video_path)
        workshop_subtitle_path = str(snapshot.get("subtitlePath") or "").strip()
        subtitle_source = "workshop"
        if workshop_subtitle_path:
            _write_copy(Path(workshop_subtitle_path), subtitle_path)
        else:
            subtitle_source = "validation_sidecar_only"
            self._write_workshop_validation_subtitles(documents, snapshot, subtitle_path)
        timeline_path = self._write_workshop_timeline(
            task,
            documents,
            snapshot,
            subtitle_path,
            render_root / "timeline-map.json",
        )
        validation = self.validate_video(
            video_path=video_path,
            subtitles_path=subtitle_path,
            timeline_path=timeline_path,
            expected_lines=documents["script_lines.json"]["lines"],
            expected_width=documents["production_config.json"]["width"],
            expected_height=documents["production_config.json"]["height"],
        )
        validation["synthetic"] = False
        validation["provenance"] = "workshop"
        validation["placeholderRunnerUsed"] = False
        validation["mediaIntegrity"] = self._workshop_media_integrity(
            task,
            snapshot,
            video_path=video_path,
            duration_seconds=validation["durationSeconds"],
        )
        validation["workshopUploadReport"] = {
            key: snapshot.get("uploadReport", {}).get(key)
            for key in ("status", "sceneCount", "subtitleCount", "subtitleMode", "durationSec", "resolution", "renderHash")
        }
        validation_path = self._task_root(task["productionTaskId"]) / "reports" / "p11-validation.json"
        _atomic_json(validation_path, validation)
        task["selectedStoryboardIds"] = [str(item.get("sceneId")) for item in snapshot["storyboardImages"]]
        task["workshop"]["artifactSnapshot"] = {
            "provenance": "workshop",
            "storyboardImageCount": len(snapshot["storyboardImages"]),
            "uploadReportSha256": _sha256_file(Path(snapshot["uploadReportPath"])),
            "finalVideoSha256": _sha256_file(video_path),
            "subtitlesSha256": _sha256_file(subtitle_path),
            "subtitleSource": subtitle_source,
        }
        self._register_asset(task, step_id="P10", asset_id="final-video", asset_type="final-video", path=video_path, source="workshop")
        self._register_asset(task, step_id="P10", asset_id="subtitles", asset_type="subtitles", path=subtitle_path, source="workshop")
        self._register_asset(task, step_id="P10", asset_id="timeline-map", asset_type="timeline-map", path=timeline_path, source="workshop")
        self._register_asset(task, step_id="P11", asset_id="technical-validation", asset_type="quality-report", path=validation_path, source="workshop")
        for step in task["steps"]:
            step["status"] = "SKIPPED" if step["stepId"] == "P8" and not task["videoGeneration"].get("enabled") else "COMPLETED"
            step["attempts"] = max(1, int(step.get("attempts", 0)))
        self._update_progress(task)
        task["state"] = "VIDEO_READY"
        result_root = self._build_result_package(task, documents, validation_path)
        task["resultPackagePath"] = str(result_root)
        self._save_task(task, event="VIDEO_READY", details={"resultPackagePath": str(result_root), "provenance": "workshop"})
        return {"task": task, "idempotent": False, "workshopCompleted": True}

    def _run_workshop_task(self, task: dict[str, Any]) -> dict[str, Any]:
        if self.workshop_bridge is None:
            raise ToolError("PRODUCTION_WORKSHOP_UNAVAILABLE", "正式制作必须使用真实工坊桥。")
        project_path_text = str(task.get("import", {}).get("projectPath") or "").strip()
        if not project_path_text:
            raise ToolError("PRODUCTION_WORKSHOP_IMPORT_INVALID", "正式制作任务缺少隔离工坊项目路径。")
        project_path = Path(project_path_text)
        documents = self._task_documents(task)
        workshop = task.setdefault("workshop", {})
        request_id = str(workshop.get("requestId") or "")
        if not request_id:
            production_config = documents.get("production_config.json", {})
            prompt_generation = production_config.get("promptGeneration", {})
            production_mode_id = str(production_config.get("productionMode", {}).get("id") or "director")
            if production_mode_id == "director" and bool(prompt_generation.get("image") or prompt_generation.get("video")):
                visual_plan = production_config.get("codexVisualPlan")
                if not isinstance(visual_plan, dict) or visual_plan.get("schemaVersion") != CODEX_VISUAL_PLAN_SCHEMA_VERSION:
                    raise ToolError(
                        "PRODUCTION_CODEX_VISUAL_PLAN_LEGACY",
                        "旧视觉方案不能启动新的工坊请求；请用当前 1.5 语义分镜合同重新组装生产包。",
                        details={
                            "requiredSchemaVersion": CODEX_VISUAL_PLAN_SCHEMA_VERSION,
                            "actualSchemaVersion": visual_plan.get("schemaVersion") if isinstance(visual_plan, dict) else None,
                        },
                    )
            if self._step(task, "P0")["status"] != "COMPLETED":
                self._execute_p0(task, documents)
            request_id = str(workshop.get("pendingRequestId") or "").strip()
            newly_reserved = not request_id
            if not request_id:
                request_id = f"stage5-{task['productionTaskId']}-{uuid.uuid4().hex[:12]}"
                workshop["pendingRequestId"] = request_id
                workshop["requestReservedAt"] = utc_now()
            selected_steps = self._workshop_selected_steps(documents["production_config.json"])
            selected_episode_ids: list[str] = []
            skip_completed = True
            selective_scope = self._workshop_selective_rework_scope(task, project_path)
            if selective_scope is not None:
                selected_steps = selective_scope["selectedStepIds"]
                selected_episode_ids = selective_scope["selectedEpisodeIds"]
                skip_completed = selective_scope["skipCompleted"]
            if newly_reserved:
                self._save_task(
                    task,
                    event="WORKSHOP_REQUEST_RESERVED",
                    details={"requestId": request_id, "projectId": task["projectId"]},
                )
            try:
                start = self.workshop_bridge.start_production(
                    project_path,
                    selected_step_ids=selected_steps,
                    selected_episode_ids=selected_episode_ids,
                    request_id=request_id,
                    expected_project_id=task["projectId"],
                    skip_completed=skip_completed,
                )
            except ToolError as exc:
                if exc.code != "WORKSHOP_BUSY":
                    raise
                queue = task.setdefault("workshopQueue", {})
                if not queue.get("queuedAt"):
                    queue["queuedAt"] = utc_now()
                queue.update(
                    {
                        "status": "WAITING_WORKSHOP",
                        "requestId": request_id,
                        "ownerProjectId": str(exc.details.get("ownerProjectId") or ""),
                        "ownerRequestId": str(exc.details.get("ownerRequestId") or ""),
                        "message": "工坊正在处理其他项目；本任务保留原请求号并等待。",
                    }
                )
                task["state"] = "QUEUED_WAITING_WORKSHOP"
                task["runId"] = request_id
                self._save_task(
                    task,
                    event="WORKSHOP_QUEUED",
                    details={
                        "requestId": request_id,
                        "ownerProjectId": queue["ownerProjectId"],
                        "ownerRequestId": queue["ownerRequestId"],
                    },
                )
                return {
                    "task": task,
                    "workshopQueued": True,
                    "waitingForWorkshop": True,
                    "idempotent": True,
                }
            request_id = str(start.get("requestId") or request_id)
            task["runId"] = request_id
            task["state"] = "RUNNING"
            task.pop("workshopQueue", None)
            task["workshop"] = {
                "requestId": request_id,
                "selectedStepIds": selected_steps,
                "selectedEpisodeIds": selected_episode_ids,
                "skipCompleted": skip_completed,
                "projectPath": str(project_path.resolve()),
                "joinedExisting": bool(start.get("joinedExisting")),
                "startConfirmed": bool(start.get("startConfirmed")),
                "launchCount": int(workshop.get("launchCount", 0)) + (0 if start.get("joinedExisting") else 1),
                "provenance": "workshop",
                "startupConfirmationStartedAtEpoch": time.time(),
            }
            if selective_scope is not None:
                task["workshop"]["selectiveReworkScope"] = {
                    "path": selective_scope["path"],
                    "sha256": selective_scope["sha256"],
                    "authorization": selective_scope["authorization"],
                }
            self._save_task(
                task,
                event="WORKSHOP_RUN_STARTED",
                details={
                    "requestId": request_id,
                    "selectedStepIds": selected_steps,
                    "selectedEpisodeIds": selected_episode_ids,
                    "skipCompleted": skip_completed,
                    "selectiveReworkScope": selective_scope is not None,
                },
            )
            return {"task": task, "workshopStarted": True, "idempotent": False}

        status = self.workshop_bridge.production_status(
            project_path,
            expected_project_id=task["projectId"],
            expected_request_id=request_id,
        )
        workshop["lastStatus"] = status
        normalized_status = str(status.get("status") or "").strip().lower()
        task_present = bool(status.get("taskPresent"))
        if task_present and normalized_status in {"running", "idle"}:
            workshop["missingTaskObservations"] = 0
            task["state"] = "RUNNING"
            self._save_task(
                task,
                event="WORKSHOP_STATUS_OBSERVED",
                details={"status": normalized_status or "NOT_STARTED", "taskPresent": True, "requestId": request_id},
            )
            return {"task": task, "workshopRunning": True, "idempotent": True}
        if normalized_status in {"paused", "failed", "cancelled"}:
            error_message = status.get("error") or status.get("message") or normalized_status
            error_detail = _classify_workshop_error(error_message)
            if error_detail["category"] == "authentication":
                task["state"] = "NEEDS_CONFIGURATION"
            elif error_detail["category"] == "prompt_retry_exhausted":
                task["state"] = "NEEDS_REPAIR"
            elif normalized_status == "paused" or error_detail["recoverable"]:
                task["state"] = "PAUSED"
            else:
                task["state"] = "FAILED"
            workshop["lastError"] = error_detail["message"]
            workshop["lastErrorDetail"] = error_detail
            workshop["missingTaskObservations"] = 0
            self._save_task(
                task,
                event="WORKSHOP_STOPPED",
                details={
                    "status": normalized_status,
                    "taskPresent": task_present,
                    "requestId": request_id,
                    "error": error_detail,
                },
            )
            return {"task": task, "workshopNeedsAttention": True, "idempotent": True}
        if not task_present:
            missing_count = int(workshop.get("missingTaskObservations", 0)) + 1
            workshop["missingTaskObservations"] = missing_count
            startup_started_at = workshop.get("startupConfirmationStartedAtEpoch")
            try:
                startup_started_at_epoch = float(startup_started_at)
            except (TypeError, ValueError):
                startup_started_at_epoch = time.time()
                workshop["startupConfirmationStartedAtEpoch"] = startup_started_at_epoch
            startup_elapsed_seconds = max(0.0, time.time() - startup_started_at_epoch)
            details = {
                "status": normalized_status or "NOT_STARTED",
                "taskPresent": False,
                "requestId": request_id,
                "missingTaskObservations": missing_count,
                "startupElapsedSeconds": round(startup_elapsed_seconds, 3),
            }
            if (
                missing_count <= WORKSHOP_MISSING_TASK_GRACE_OBSERVATIONS
                or startup_elapsed_seconds < WORKSHOP_MISSING_TASK_GRACE_SECONDS
            ):
                task["state"] = "RUNNING"
                workshop["startupPendingConfirmation"] = True
                self._save_task(task, event="WORKSHOP_START_CONFIRMATION_PENDING", details=details)
                return {
                    "task": task,
                    "workshopRunning": True,
                    "workshopStartConfirmationPending": True,
                    "idempotent": True,
                }
            error_detail = {
                "category": "workshop_task_missing",
                "recoverable": True,
                "recommendedAction": "inspect_original_request_before_retry",
                "message": "工坊连续查询不到原生产任务，已停止把缺失任务误报为运行中。",
            }
            task["state"] = "NEEDS_REPAIR"
            workshop["startupPendingConfirmation"] = False
            workshop["lastError"] = error_detail["message"]
            workshop["lastErrorDetail"] = error_detail
            self._save_task(task, event="WORKSHOP_TASK_MISSING", details={**details, "error": error_detail})
            return {"task": task, "workshopNeedsAttention": True, "idempotent": True}
        if normalized_status != "completed":
            raise ToolError(
                "WORKSHOP_STATUS_INVALID",
                "工坊返回了无法识别的生产状态。",
                details={"status": normalized_status, "taskPresent": task_present, "requestId": request_id},
            )
        workshop["missingTaskObservations"] = 0
        workshop["startupPendingConfirmation"] = False
        snapshot = self.workshop_bridge.production_artifacts(
            project_path,
            expected_project_id=task["projectId"],
            expected_request_id=request_id,
        )
        return self._ingest_workshop_completion(task, documents, snapshot)

    def _execute_p11(self, task: dict[str, Any], documents: dict[str, dict[str, Any]]) -> None:
        render_root = self._task_root(task["productionTaskId"]) / "render"
        validation = self.validate_video(
            video_path=render_root / "final-video.mp4",
            subtitles_path=render_root / "subtitles.srt",
            timeline_path=render_root / "timeline-map.json",
            expected_lines=documents["script_lines.json"]["lines"],
            expected_width=documents["production_config.json"]["width"],
            expected_height=documents["production_config.json"]["height"],
        )
        validation["synthetic"] = task["synthetic"]
        validation["externalMediaServicesCalled"] = False if task["synthetic"] else None
        validation["provenance"] = "deterministic-fixture-runner" if task["synthetic"] else "workshop"
        validation["placeholderRunnerUsed"] = bool(task["synthetic"])
        if task["synthetic"]:
            validation["mediaIntegrity"] = {
                "status": "SYNTHETIC_FIXTURE_ONLY",
                "provenance": "deterministic-fixture-runner",
                "placeholderRunnerUsed": True,
            }
        validation_path = self._task_root(task["productionTaskId"]) / "reports" / "p11-validation.json"
        _atomic_json(validation_path, validation)
        self._register_asset(task, step_id="P11", asset_id="technical-validation", asset_type="quality-report", path=validation_path, input_value=validation)
        self._complete_step(task, "P11")
        task["state"] = "VIDEO_READY"
        result_root = self._build_result_package(task, documents, validation_path)
        task["resultPackagePath"] = str(result_root)
        self._save_task(task, event="VIDEO_READY", details={"resultPackagePath": str(result_root)})

    def _build_result_package(
        self,
        task: dict[str, Any],
        documents: dict[str, dict[str, Any]],
        validation_path: Path,
    ) -> Path:
        validation = _read_json(validation_path, "PRODUCTION_RESULT_INVALID")
        result_root = self.root / "results" / task["projectId"] / task["productionTaskId"]
        if result_root.exists():
            shutil.rmtree(result_root)
        result_root.mkdir(parents=True)
        render_root = self._task_root(task["productionTaskId"]) / "render"
        _write_copy(render_root / "final-video.mp4", result_root / "final-video.mp4")
        _write_copy(render_root / "subtitles.srt", result_root / "subtitles.srt")
        _write_copy(validation_path, result_root / "validation-report.json")
        timeline_source = render_root / "timeline-map.json"
        timeline = _read_json(timeline_source)
        production_report = {
            "schemaVersion": "1.0.0",
            "productionTaskId": task["productionTaskId"],
            "projectId": task["projectId"],
            "status": "VIDEO_READY",
            "deliveryMode": task["deliveryMode"],
            "sceneImageCadence": task.get("sceneImageCadence"),
            "selectedStoryboardIds": task["selectedStoryboardIds"],
            "fallbacks": task["fallbacks"],
            "synthetic": task["synthetic"],
            "provenance": validation.get("provenance"),
            "placeholderRunnerUsed": validation.get("placeholderRunnerUsed"),
            "mediaIntegrity": validation.get("mediaIntegrity"),
            "externalServiceCalls": [],
            "publishingTriggered": False,
        }
        _atomic_json(result_root / "production-report.json", production_report)
        task_copy = deepcopy(task)
        task_copy["state"] = "VIDEO_READY"
        task_copy["packagePath"] = "source-lock.json#productionPackage"
        task_copy["resultPackagePath"] = "."
        if task_copy.get("jianyingDraftPackagePath"):
            task_copy["jianyingDraftPackagePath"] = "production-report.json#jianyingDraft"
        if task_copy.get("lastIngestedExport"):
            task_copy["lastIngestedExport"] = {
                key: value for key, value in task_copy["lastIngestedExport"].items() if key != "sourcePath"
            }
        if isinstance(task_copy.get("import"), dict):
            task_copy["import"] = {
                key: value
                for key, value in task_copy["import"].items()
                if key not in {"snapshotPath", "projectPath"}
            }
        _atomic_json(result_root / "production-task.json", task_copy)
        publishing_reference = {
            "schemaVersion": "1.0.0",
            "title": documents["publishing.json"]["title"],
            "thumbnailMode": documents["publishing.json"].get("thumbnailMode", "custom"),
            "thumbnailSha256": (
                _sha256_file(Path(task["packagePath"]) / "confirmed_thumbnail.png")
                if (Path(task["packagePath"]) / "confirmed_thumbnail.png").is_file()
                else None
            ),
            "publishingAssetPackage": documents["source_lock.json"]["publishingAssetPackage"],
            "publishPackageCreated": False,
        }
        _atomic_json(result_root / "publishing-assets-reference.json", publishing_reference)
        source_lock = {
            "schemaVersion": "1.0.0",
            "productionPackage": {
                "productionPackageId": task["productionPackageId"],
                "packageVersion": task["packageVersion"],
                "packageHash": task["packageHash"],
            },
            "manuscriptPackage": documents["source_lock.json"]["manuscriptPackage"],
            "publishingAssetPackage": documents["source_lock.json"]["publishingAssetPackage"],
        }
        _atomic_json(result_root / "source-lock.json", source_lock)
        artifacts = []
        for path in sorted((item for item in result_root.iterdir() if item.is_file() and item.name not in {"manifest.json", "artifact-index.json"}), key=lambda item: item.name):
            media_type = "video/mp4" if path.suffix == ".mp4" else "application/x-subrip" if path.suffix == ".srt" else "application/json"
            artifacts.append(_asset(path, result_root, path.stem.replace("_", "-"), media_type, synthetic=task["synthetic"]))
        _atomic_json(result_root / "artifact-index.json", {"schemaVersion": "1.0.0", "artifacts": artifacts, "timeline": timeline})
        artifact_index_asset = _asset(result_root / "artifact-index.json", result_root, "artifact-index", "application/json")
        final_video = _asset(result_root / "final-video.mp4", result_root, "final-video", "video/mp4")
        subtitles = _asset(result_root / "subtitles.srt", result_root, "subtitles", "application/x-subrip")
        files = []
        for path in sorted((item for item in result_root.iterdir() if item.is_file() and item.name != "manifest.json"), key=lambda item: item.name):
            files.append({"path": path.name, "sizeBytes": path.stat().st_size, "sha256": _sha256_file(path)})
        created = utc_now()
        manifest = with_hash(
            {
                "schemaVersion": "1.0.0",
                "contractType": "production-result-package",
                "id": f"result_{task['productionTaskId']}",
                "version": "1.0.0",
                "createdAt": created,
                "hashAlgorithm": "SHA-256",
                "hashRule": "canonical-json-v1",
                "upstream": [documents["source_lock.json"]["manuscriptPackage"], documents["source_lock.json"]["publishingAssetPackage"]],
                "productionResultPackageId": f"result_{task['productionTaskId']}",
                "projectId": task["projectId"],
                "channelProfileId": documents["project.json"]["channelProfileId"],
                "productionTaskId": task["productionTaskId"],
                "productionPackageVersion": task["packageVersion"],
                "productionPackageHash": task["packageHash"],
                "status": "VIDEO_READY",
                "workshopVersion": documents["source_lock.json"]["workshopCompatibility"].get("workshopVersion", "0.0.0"),
                "finalVideo": final_video,
                "subtitles": subtitles,
                "artifactIndex": artifact_index_asset,
                "validationReportHash": _sha256_file(result_root / "validation-report.json"),
                "timelineMapHash": _sha256_file(timeline_source),
                "fallbacks": task["fallbacks"],
                "synthetic": task["synthetic"],
                "provenance": validation.get("provenance"),
                "placeholderRunnerUsed": validation.get("placeholderRunnerUsed"),
                "mediaIntegrity": validation.get("mediaIntegrity"),
                "files": files,
                "publishingTriggered": False,
            }
        )
        _atomic_json(result_root / "manifest.json", manifest)
        self.validate_result_package(result_root)
        return result_root

    def validate_result_package(self, result_root: Path) -> dict[str, Any]:
        root = result_root.resolve()
        manifest = _read_json(root / "manifest.json", "PRODUCTION_RESULT_INVALID")
        if manifest.get("contractType") != "production-result-package" or manifest.get("status") != "VIDEO_READY":
            raise ToolError("PRODUCTION_RESULT_INVALID", "结果包类型或状态无效。")
        if canonical_hash(manifest) != manifest.get("contentHash"):
            raise ToolError("PRODUCTION_RESULT_HASH_MISMATCH", "结果包 canonical-json-v1 哈希无效。")
        expected = {
            "production-task.json",
            "production-report.json",
            "artifact-index.json",
            "validation-report.json",
            "final-video.mp4",
            "subtitles.srt",
            "publishing-assets-reference.json",
            "source-lock.json",
        }
        listed = set()
        for item in manifest.get("files", []):
            relative = _safe_relative(item.get("path"), "result.files.path")
            listed.add(relative.as_posix())
            path = _ensure_within(root, root / relative, "result file")
            if not path.is_file() or path.stat().st_size != item.get("sizeBytes") or _sha256_file(path) != item.get("sha256"):
                raise ToolError("PRODUCTION_RESULT_FILE_HASH_MISMATCH", "结果包文件哈希无效。")
        if listed != expected:
            raise ToolError("PRODUCTION_RESULT_FILE_SET_INVALID", "结果包文件集合不完整。")
        if any(path.suffix == ".ready" or path.name.endswith(".ready") for path in root.rglob("*")):
            raise ToolError("PRODUCTION_PUBLISH_BOUNDARY_VIOLATION", "制作中心不得创建 .ready 发布包。")
        actual = {
            path.relative_to(root).as_posix()
            for path in root.rglob("*")
            if path.is_file() and path.name != "manifest.json"
        }
        if actual != expected:
            raise ToolError("PRODUCTION_RESULT_FILE_SET_INVALID", "Result package contains undeclared or missing files.")
        if manifest.get("publishingTriggered") is not False:
            raise ToolError("PRODUCTION_PUBLISH_BOUNDARY_VIOLATION", "制作结果错误标记为已触发发布。")
        if manifest.get("synthetic") is not True:
            media_integrity = manifest.get("mediaIntegrity")
            if (
                manifest.get("provenance") != "workshop"
                or manifest.get("placeholderRunnerUsed") is not False
                or not isinstance(media_integrity, dict)
                or media_integrity.get("status") != "PASSED"
                or media_integrity.get("provenance") != "workshop"
            ):
                raise ToolError(
                    "PRODUCTION_REAL_MEDIA_PROVENANCE_INVALID",
                    "正式结果包缺少真实工坊来源或分镜／成片完整性证明。",
                )
        return {"status": "PASS", "manifest": manifest}

    def run_task(
        self,
        task_id: Any,
        *,
        pause_after_step: str | None = None,
        fail_storyboard_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        task = self._load_task(task_id)
        queue = task.get("queue") if isinstance(task.get("queue"), dict) else {}
        if queue.get("schemaVersion") == QUEUE_SCHEMA_VERSION and os.environ.get("AIVCP_QUEUE_WORKER") != "1":
            dispatcher = self._wake_queue_dispatcher()
            return {
                "task": task,
                "queuedByDispatcher": True,
                "dispatcher": dispatcher,
                "productionTaskRunRequiredAgain": False,
            }
        if task["state"] == "VIDEO_READY":
            return {"task": task, "idempotent": True}
        runnable_states = {"READY_TO_PRODUCE", "RETRYING", "RUNNING", "QUEUED_WAITING_WORKSHOP"}
        # A formal workshop request that temporarily disappeared must keep the
        # same request id.  Allow monitoring to resume from NEEDS_REPAIR without
        # launching a second paid request.  Synthetic fixtures still use the
        # explicit repair/retry path.
        if not task["synthetic"]:
            runnable_states.add("NEEDS_REPAIR")
        if task["state"] not in runnable_states:
            raise ToolError("PRODUCTION_TASK_NOT_RUNNABLE", "当前制作任务不能运行。")
        if not task["synthetic"]:
            return self._run_workshop_task(task)
        task["state"] = "RUNNING"
        task["runId"] = f"run_{uuid.uuid4().hex}"
        self._save_task(task, event="RUN_STARTED", details={"runId": task["runId"]})
        documents = self._task_documents(task)
        failed = set(fail_storyboard_ids or [])
        executors = {
            "P0": lambda: self._execute_p0(task, documents),
            "P1": lambda: self._execute_p1(task, documents),
            "P2": lambda: self._execute_p2(task, documents),
            "P3": lambda: self._execute_p3(task, documents),
            "P4": lambda: self._execute_p4(task, documents),
            "P5": lambda: self._execute_p5(task, documents),
            "P6": lambda: self._execute_p6(task, documents),
            "P7": lambda: self._execute_p7(task, documents),
            "P8": lambda: self._execute_p8(task, documents, fail_storyboard_ids=failed),
            "P9": lambda: self._execute_p9(task, documents),
        }
        for step_id, _, dependencies in STEP_DEFINITIONS:
            step = self._step(task, step_id)
            if step["status"] in {"COMPLETED", "SKIPPED"}:
                continue
            if any(self._step(task, dependency)["status"] not in {"COMPLETED", "SKIPPED"} for dependency in dependencies):
                raise ToolError("PRODUCTION_STEP_DEPENDENCY_INVALID", "步骤依赖尚未完成。", details={"stepId": step_id})
            try:
                if step_id == "P10":
                    if task["deliveryMode"] == "auto_render":
                        self._execute_p10_auto(task, documents)
                    else:
                        self._execute_p10_jianying(task, documents)
                        return {"task": task, "awaitingJianyingExport": True}
                elif step_id == "P11":
                    task["state"] = "RESULT_VALIDATING"
                    self._save_task(task, event="RESULT_VALIDATION_STARTED")
                    self._execute_p11(task, documents)
                else:
                    if step_id == "P0":
                        task["state"] = "PREFLIGHT"
                    elif step_id == "P9":
                        task["state"] = "ASSET_DIAGNOSTICS"
                    completed = executors[step_id]()
                    if step_id == "P8" and completed is False:
                        return {"task": task, "pausedForRepair": True}
            except ToolError as exc:
                if step["status"] != "FAILED":
                    step["status"] = "FAILED"
                    step["attempts"] = int(step.get("attempts", 0)) + 1
                task["state"] = "PAUSED"
                self._update_progress(task)
                self._save_task(task, event="STEP_FAILURE_PAUSED", details={"stepId": step_id, "errorCode": exc.code})
                raise
            if pause_after_step == step_id and task["state"] not in {"VIDEO_READY", "AWAITING_JIANYING_EXPORT"}:
                task["state"] = "PAUSED"
                self._save_task(task, event="PAUSED_AT_CHECKPOINT", details={"stepId": step_id})
                return {"task": task, "paused": True}
        return {"task": task, "idempotent": False}

    def ingest_jianying_export(
        self,
        task_id: Any,
        *,
        export_path: Path,
        identity_path: Path,
    ) -> dict[str, Any]:
        task = self._load_task(task_id)
        if task["deliveryMode"] != "jianying_refine":
            raise ToolError("PRODUCTION_JIANYING_NOT_AWAITING", "任务没有等待剪映导出。")
        export_path = export_path.resolve()
        identity_path = identity_path.resolve()
        if not export_path.is_file() or not identity_path.is_file():
            raise ToolError("PRODUCTION_JIANYING_EXPORT_MISSING", "剪映导出 MP4 或身份旁车文件不存在。")
        identity = _read_json(identity_path, "PRODUCTION_JIANYING_IDENTITY_INVALID")
        expected = {
            "projectId": task["projectId"],
            "productionTaskId": task["productionTaskId"],
            "packageHash": task["packageHash"],
        }
        if any(identity.get(key) != value for key, value in expected.items()):
            raise ToolError("PRODUCTION_JIANYING_EXPORT_IDENTITY_MISMATCH", "剪映导出不属于当前项目或任务。")
        export_hash = _sha256_file(export_path)
        if identity.get("videoSha256") != export_hash:
            raise ToolError("PRODUCTION_JIANYING_EXPORT_HASH_MISMATCH", "剪映导出 SHA-256 与身份旁车不一致。")
        if task.get("lastIngestedExport"):
            if task["lastIngestedExport"].get("videoSha256") == export_hash:
                return {"task": task, "idempotent": True}
            raise ToolError("PRODUCTION_JIANYING_EXPORT_DUPLICATE_CONFLICT", "任务已经回收了另一份成片。")
        if task["state"] not in {"AWAITING_JIANYING_EXPORT", "INGESTING_EXPORT"}:
            raise ToolError("PRODUCTION_JIANYING_NOT_AWAITING", "任务没有等待剪映导出。")
        task["state"] = "INGESTING_EXPORT"
        self._save_task(task, event="JIANYING_EXPORT_INGEST_STARTED")
        render_root = self._task_root(task["productionTaskId"]) / "render"
        render_root.mkdir(parents=True, exist_ok=True)
        _write_copy(export_path, render_root / "final-video.mp4")
        draft_root = Path(task["jianyingDraftPackagePath"])
        _write_copy(draft_root / "subtitles.srt", render_root / "subtitles.srt")
        _write_copy(draft_root / "timeline-map.json", render_root / "timeline-map.json")
        self._register_asset(task, step_id="P10", asset_id="final-video", asset_type="final-video", path=render_root / "final-video.mp4", input_value=identity, source="user-jianying-export")
        task["lastIngestedExport"] = {**expected, "videoSha256": export_hash, "sourcePath": str(export_path)}
        task["state"] = "RESULT_VALIDATING"
        self._save_task(task, event="JIANYING_EXPORT_INGESTED", details={"videoSha256": export_hash})
        documents = self._task_documents(task)
        self._execute_p11(task, documents)
        return {"task": task, "idempotent": False}
