from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
import uuid
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


PRODUCTION_CENTER_VERSION = "1.0.0"
PRODUCTION_PACKAGE_SCHEMA_VERSION = "2.1"
PRODUCTION_TASK_SCHEMA_VERSION = "1.0.0"
PRODUCTION_RESULT_SCHEMA_VERSION = "1.0.0"
PRODUCTION_PACKAGE_FILES = {
    "project.json",
    "characters.json",
    "episodes.json",
    "script_lines.json",
    "production_config.json",
    "target_script_quality_gate.json",
    "publishing.json",
    "confirmed_thumbnail.png",
    "source_lock.json",
}
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
    ("P5", "按真实音频时长生成分镜", ("P4",)),
    ("P6", "生成并校验分镜图片提示词", ("P5",)),
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
    manuscript: dict[str, Any], catalog: dict[str, Any], catalog_version: str, catalog_hash: str
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
    speakers = {line.get("speakerId") for line in manuscript.get("targetScript", {}).get("lines", [])}
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
        f"- 制作方式：`{production_config['deliveryMode']}`",
        f"- 图片风格预设：`{production_config['imageStyle']['presetId']}`",
        f"- 图片风格提示词：{production_config['imageStyle']['prompt']}",
        f"- 剧情图片文字策略：`{production_config['storyImageTextPolicy']}`（角色图、分镜图和宫格图禁止可读文字；正式封面不受此项限制）",
        f"- 视频生成范围：`{video['selectionMode']}`",
        f"- 视频失败策略：`{video['fallbackPolicy']}`",
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
            "- `publishing.json`：目标语言标题、简介、Hashtags、频道和上传策略。",
            "- `confirmed_thumbnail.png`：唯一确认的 16:9 正式封面。",
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
            "videoSelectionModes": sorted(VIDEO_SELECTION_MODES),
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
        required_review_documents = tuple(
            dict.fromkeys(
                [item["documentId"] for item in review_view["documents"]]
                + [
            "rewrite-draft-target",
            "editorial-review",
            "revision-log",
            "final-script-target",
            "final-script-zh",
            "packaging-bilingual",
            "thumbnail-review",
                ]
            )
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
                "thumbnail-review": {
                    "sourceContractType": publishing["contractType"],
                    "sourceContractId": publishing["id"],
                    "sourceContentHash": publishing["contentHash"],
                },
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
        if thumbnail.get("mode") != "real_file" or not isinstance(thumbnail.get("asset"), dict):
            raise ToolError("PRODUCTION_THUMBNAIL_INVALID", "必须锁定真实 16:9 封面。")
        thumbnail_path = _validate_descriptor(
            publishing_root, thumbnail["asset"], code="PRODUCTION_THUMBNAIL_INVALID"
        )
        if thumbnail.get("aspectRatio") != "16:9" or not thumbnail.get("hashVerified"):
            raise ToolError("PRODUCTION_THUMBNAIL_INVALID", "封面比例或哈希确认无效。")
        if not self.voice_catalog_path or not self.voice_catalog_path.is_file():
            raise ToolError("PRODUCTION_VOICE_CATALOG_UNAVAILABLE", "没有可用的版本化音色目录。")
        catalog, catalog_version, catalog_hash = _voice_catalog_document(self.voice_catalog_path)
        voice_bindings = _validate_locked_voices(manuscript, catalog, catalog_version, catalog_hash)
        config = self._validate_production_config(production_config)
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
            for character in manuscript.get("characters", []):
                speaker_id = character.get("characterId")
                if speaker_id not in voice_bindings:
                    raise ToolError("PRODUCTION_VOICE_BINDING_MISSING", "持续角色缺少锁定音色。")
                characters.append({**deepcopy(character), "voice": deepcopy(voice_bindings[speaker_id])})
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
                "thumbnail": "confirmed_thumbnail.png",
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
        prompt_generation = deepcopy(config.get("promptGeneration", {"image": False, "video": False}))
        if (
            not isinstance(prompt_generation, dict)
            or not isinstance(prompt_generation.get("image"), bool)
            or not isinstance(prompt_generation.get("video"), bool)
        ):
            raise ToolError("PRODUCTION_PROMPT_GENERATION_INVALID", "图片提示词和视频提示词开关必须分别为明确的是／否。")
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
        concurrency = deepcopy(config.get("concurrency", {"image": 1, "video": 1, "tts": 1}))
        if any(not isinstance(value, int) or isinstance(value, bool) or value < 1 or value > 16 for value in concurrency.values()):
            raise ToolError("PRODUCTION_CONFIG_INVALID", "并发参数无效。")
        retry_limit = config.get("retryLimit", 2)
        if not isinstance(retry_limit, int) or isinstance(retry_limit, bool) or not 0 <= retry_limit <= 10:
            raise ToolError("PRODUCTION_CONFIG_INVALID", "重试次数无效。")
        return {
            "deliveryMode": delivery_mode,
            "aspectRatio": aspect_ratio,
            "width": width,
            "height": height,
            "frameRate": frame_rate,
            "imageStyle": {"presetId": image_style_id, "prompt": image_style_prompt},
            "storyImageTextPolicy": story_image_text_policy,
            "promptGeneration": {
                "image": prompt_generation["image"],
                "video": prompt_generation["video"],
            },
            "gridBatch": {
                "template": grid_template,
                "selectionSource": grid_selection_source,
            },
            "videoGeneration": video,
            "concurrency": concurrency,
            "retryLimit": retry_limit,
            "syntheticFixtureRunner": bool(config.get("syntheticFixtureRunner", False)),
        }

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
        if listed != PRODUCTION_PACKAGE_FILES or actual != PRODUCTION_PACKAGE_FILES:
            extras = sorted((listed | actual) - PRODUCTION_PACKAGE_FILES)
            missing = sorted(PRODUCTION_PACKAGE_FILES - (listed & actual))
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
        thumbnail = package_root / publishing.get("thumbnail", "")
        if thumbnail != package_root / "confirmed_thumbnail.png" or not thumbnail.is_file():
            raise ToolError("PRODUCTION_THUMBNAIL_INVALID", "发布素材没有引用包内确认封面。")
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

    def _save_task(self, task: dict[str, Any], *, event: str | None = None, details: dict[str, Any] | None = None) -> None:
        task["revision"] = int(task.get("revision", 0)) + 1
        task["updatedAt"] = utc_now()
        if event:
            task.setdefault("history", []).append(
                {"revision": task["revision"], "at": task["updatedAt"], "event": event, "details": details or {}}
            )
        _atomic_json(self._task_path(task["productionTaskId"]), task)

    def get_task(self, task_id: Any) -> dict[str, Any]:
        task = self._load_task(task_id)
        return {"task": task, "progressReadOnly": True}

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
            target = (
                target_root.resolve()
                if target_root is not None
                else self.workshop_bridge.isolation_root
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
                return {"task": existing, "idempotent": True}
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
            "deliveryMode": config["deliveryMode"],
            "synthetic": bool(manifest["synthetic"] or config.get("syntheticFixtureRunner")),
            "videoGeneration": deepcopy(config["videoGeneration"]),
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
        self._save_task(task, event="TASK_CREATED", details={"importAdapter": import_result.get("adapter")})
        return {"task": task, "idempotent": False}

    def request_pause(self, task_id: Any) -> dict[str, Any]:
        task = self._load_task(task_id)
        if task["state"] not in {"RUNNING", "RETRYING", "READY_TO_PRODUCE"}:
            raise ToolError("PRODUCTION_TASK_NOT_PAUSABLE", "当前制作状态不能请求暂停。")
        task["state"] = "PAUSE_REQUESTED" if task["state"] != "READY_TO_PRODUCE" else "PAUSED"
        self._save_task(task, event="PAUSE_REQUESTED")
        return task

    def resume_task(self, task_id: Any) -> dict[str, Any]:
        task = self._load_task(task_id)
        if task["state"] not in {"PAUSED", "NEEDS_REPAIR", "RETRYING"}:
            raise ToolError("PRODUCTION_TASK_NOT_RESUMABLE", "当前制作状态不能恢复。")
        task["state"] = "READY_TO_PRODUCE"
        task["runId"] = None
        self._save_task(task, event="TASK_RESUMED")
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
                task["state"] = "READY_TO_PRODUCE"
                task["resultPackagePath"] = None
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
                    f"sine=frequency={frequency}:sample_rate=48000:duration=0.75",
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
        for line in documents["script_lines.json"]["lines"]:
            storyboard_id = f"SB-{line['lineId']}"
            storyboards.append(
                {
                    "storyboardId": storyboard_id,
                    "episodeNumber": line["episodeNumber"],
                    "lineIds": [line["lineId"]],
                    "speakerIds": [line["speakerId"]],
                    "audioAssetIds": [f"audio-{line['lineId']}"],
                    "startSeconds": round(cursor, 3),
                    "durationSeconds": 0.75,
                }
            )
            cursor += 0.75
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
        for index, line in enumerate(lines, 1):
            start = cursor
            end = cursor + 0.75
            srt_parts.extend([str(index), f"{self._srt_timestamp(start)} --> {self._srt_timestamp(end)}", line["text"], ""])
            timeline.append(
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
        srt_path = root / "subtitles.srt"
        timeline_path = root / "timeline-map.json"
        _atomic_bytes(srt_path, ("\n".join(srt_parts).rstrip() + "\n").encode("utf-8"))
        _atomic_json(timeline_path, {"schemaVersion": "1.0.0", "language": _read_json(Path(task["packagePath"]) / "script_lines.json")["language"], "durationSeconds": round(cursor, 3), "items": timeline})
        return srt_path, timeline_path

    def _execute_p10_auto(self, task: dict[str, Any], documents: dict[str, dict[str, Any]]) -> None:
        output_root = self._task_root(task["productionTaskId"]) / "render"
        output_root.mkdir(parents=True, exist_ok=True)
        lines = documents["script_lines.json"]["lines"]
        duration = max(0.75 * len(lines), 1.0)
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
            "items": _read_json(timeline_path)["items"],
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
        if video.get("width") != expected_width or video.get("height") != expected_height or expected_width * 9 != expected_height * 16:
            raise ToolError("PRODUCTION_VIDEO_DIMENSIONS_INVALID", "最终 MP4 分辨率或画幅不符合 16:9 预设。")
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
        normalized_script = re.sub(r"\s+", "", "".join(line["text"] for line in expected_lines))
        if not normalized_script or normalized_script not in normalized_subtitles:
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
            "aspectRatio": "16:9",
            "frameRate": video.get("avg_frame_rate"),
            "videoCodec": video.get("codec_name"),
            "audioCodec": audio_streams[0].get("codec_name"),
            "durationSeconds": round(duration, 3),
            "subtitleCueCount": len(items),
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
        if isinstance(prompt_generation, dict) and bool(prompt_generation.get("image") or prompt_generation.get("video")):
            steps.append("image_prompts")
        steps.append("grid_image")
        if bool(config.get("videoGeneration", {}).get("enabled")):
            steps.append("video")
        steps.append("diagnostics")
        steps.append("export" if config.get("deliveryMode") == "jianying_refine" else "final_render")
        return steps

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
        _write_copy(Path(snapshot["subtitlePath"]), subtitle_path)
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
            for key in ("status", "sceneCount", "subtitleCount", "durationSec", "resolution", "renderHash")
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
            if self._step(task, "P0")["status"] != "COMPLETED":
                self._execute_p0(task, documents)
            request_id = f"stage5-{task['productionTaskId']}-{uuid.uuid4().hex[:12]}"
            selected_steps = self._workshop_selected_steps(documents["production_config.json"])
            start = self.workshop_bridge.start_production(
                project_path,
                selected_step_ids=selected_steps,
                request_id=request_id,
                expected_project_id=task["projectId"],
                skip_completed=True,
            )
            request_id = str(start.get("requestId") or request_id)
            task["runId"] = request_id
            task["state"] = "RUNNING"
            task["workshop"] = {
                "requestId": request_id,
                "selectedStepIds": selected_steps,
                "projectPath": str(project_path.resolve()),
                "joinedExisting": bool(start.get("joinedExisting")),
                "startConfirmed": bool(start.get("startConfirmed")),
                "launchCount": int(workshop.get("launchCount", 0)) + (0 if start.get("joinedExisting") else 1),
                "provenance": "workshop",
            }
            self._save_task(task, event="WORKSHOP_RUN_STARTED", details={"requestId": request_id, "selectedStepIds": selected_steps})
            return {"task": task, "workshopStarted": True, "idempotent": False}

        status = self.workshop_bridge.production_status(
            project_path,
            expected_project_id=task["projectId"],
            expected_request_id=request_id,
        )
        workshop["lastStatus"] = status
        normalized_status = str(status.get("status") or "").strip().lower()
        if normalized_status in {"running", "idle"} or not status.get("taskPresent"):
            task["state"] = "RUNNING"
            self._save_task(task, event="WORKSHOP_STATUS_OBSERVED", details={"status": normalized_status or "NOT_STARTED"})
            return {"task": task, "workshopRunning": True, "idempotent": True}
        if normalized_status in {"paused", "failed", "cancelled"}:
            task["state"] = "PAUSED" if normalized_status == "paused" else "FAILED"
            workshop["lastError"] = status.get("error") or status.get("message")
            self._save_task(task, event="WORKSHOP_STOPPED", details={"status": normalized_status})
            return {"task": task, "workshopNeedsAttention": True, "idempotent": True}
        if normalized_status != "completed":
            raise ToolError("WORKSHOP_STATUS_INVALID", "工坊返回了无法识别的生产状态。", details={"status": normalized_status})
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
            "thumbnailSha256": _sha256_file(Path(task["packagePath"]) / "confirmed_thumbnail.png"),
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
        if task["state"] == "VIDEO_READY":
            return {"task": task, "idempotent": True}
        if task["state"] not in {"READY_TO_PRODUCE", "RETRYING", "RUNNING"}:
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
