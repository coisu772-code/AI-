from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import struct
import tempfile
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry, Resource

from .contracts import canonical_hash, resolve_contracts_root, utc_now, with_hash
from .confirmation_cards import chinese_first_confirmation_card
from .errors import ToolError
from .review_documents import (
    DOCUMENT_SPECS,
    REVIEW_DOCUMENT_SCHEMA_VERSION,
    copy_review_documents,
    review_documents_view,
    save_review_document,
    validate_review_documents,
)


CONTENT_LOOP_VERSION = "1.0.0"
PACKAGE_SCHEMA_VERSION = "1.0.0"
SCORE_KEYS = (
    "audienceFit",
    "clickPotential",
    "storySustainability",
    "visualPotential",
    "originality",
    "productionFeasibility",
    "overall",
)
SOURCE_MODES = {
    "channel-library",
    "market-original",
    "single-reference",
    "multi-reference",
    "provided-outline",
    "trend",
    "book-deconstruction",
    "imitation",
    "direct-rewrite",
    "synthesis-rewrite",
}
EXTENSION_MODES = {
    "trend",
    "single-reference",
    "multi-reference",
    "book-deconstruction",
    "imitation",
    "direct-rewrite",
    "synthesis-rewrite",
}
QUALITY_CHECKS = {
    "locked-facts",
    "story-progress",
    "character-voice",
    "target-language-naturalness",
    "regional-expression",
    "terminology-consistency",
    "tts-semantic-lines",
    "audience-reward",
}
FOREIGN_LANGUAGE_QUALITY_CHECKS = {
    "grammar-and-syntax",
    "regional-naturalness",
    "naming-and-terminology",
    "idiom-and-collocation",
    "translationese-avoidance",
    "cultural-address",
    "tts-readability",
    "chinese-review-consistency",
}
EXTENSION_CAPABILITY_NAMES = (
    "content-deconstruction",
    "direct-rewrite",
    "synthesis-rewrite",
    "title-generation",
    "description-generation",
    "thumbnail-generation",
)


def _safe_identifier(value: Any, field: str, *, maximum: int = 128) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", value):
        raise ToolError("INVALID_ARGUMENT", f"{field} 必须是安全标识符。")
    if len(value) > maximum:
        raise ToolError("INVALID_ARGUMENT", f"{field} 过长。")
    return value


def _json_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")


def _json_hash(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":"), sort_keys=True).encode("utf-8")
    ).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _atomic_bytes(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
    except Exception:
        Path(temp_name).unlink(missing_ok=True)
        raise


def _atomic_json(path: Path, value: Any) -> None:
    _atomic_bytes(path, _json_bytes(value))


def _asset(path: Path, root: Path, asset_id: str, media_type: str) -> dict[str, Any]:
    return {
        "assetId": asset_id,
        "relativePath": path.relative_to(root).as_posix(),
        "mediaType": media_type,
        "sizeBytes": path.stat().st_size,
        "sha256": _sha256_file(path),
    }


def _contract_ref(contract: dict[str, Any]) -> dict[str, Any]:
    return {
        "targetContractType": contract["contractType"],
        "targetId": contract["id"],
        "targetVersion": contract["version"],
        "targetSchemaVersion": contract["schemaVersion"],
        "targetHash": contract["contentHash"],
    }


def _approval(gate: str, confirmation: dict[str, Any], created: str) -> dict[str, Any]:
    mode = confirmation.get("mode", "review")
    result = {
        "gate": gate,
        "status": "APPROVED",
        "mode": mode,
        "source": confirmation.get("confirmedBy", "user"),
        "confirmedAt": confirmation.get("confirmedAt") or created,
    }
    if mode == "auto":
        authorization = confirmation.get("authorizationRef")
        if not isinstance(authorization, str) or len(authorization) < 3:
            raise ToolError("AUTO_CONFIRMATION_INVALID", "自动确认必须绑定已有用户授权引用。")
        result["authorizationRef"] = authorization
    return result


def _extension_capabilities() -> list[dict[str, Any]]:
    items = []
    for capability in EXTENSION_CAPABILITY_NAMES:
        packaging = capability in {"title-generation", "description-generation", "thumbnail-generation"}
        packaging_available = capability in {"title-generation", "description-generation", "thumbnail-generation"}
        item = {
            "capability": capability,
            "status": "available" if (not packaging or packaging_available) else "planned-unavailable",
            "interfaceVersion": "1.0.0",
            "inputContractTypes": ["manuscript-package"] if packaging else ["source-package"],
            "outputContractType": (
                "title-asset-v1" if capability == "title-generation"
                else "description-asset-v1" if capability == "description-generation"
                else "thumbnail-asset-v1" if capability == "thumbnail-generation"
                else "analysis-package-v1" if capability == "content-deconstruction"
                else "topic-package"
            ),
        }
        if capability == "content-deconstruction":
            item.update({"skillId": "content-deconstruct", "skillVersion": "1.0.0"})
        elif capability in {"direct-rewrite", "synthesis-rewrite"}:
            item.update({"skillId": "content-rewrite", "skillVersion": "1.0.0"})
        elif packaging_available:
            item.update(
                {
                    "skillId": "content-title-description",
                    "skillVersion": "1.0.0",
                }
            )
        else:
            raise AssertionError(f"unhandled extension capability: {capability}")
        items.append(item)
    return items


def _next_version(current: str | None) -> str:
    if not current:
        return "1.0.0"
    major, minor, patch = (int(item) for item in current.split(".")[:3])
    return f"{major}.{minor}.{patch + 1}"


def _read_contract(path: Path, expected_type: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ToolError("CONTENT_PACKAGE_INVALID", "冻结包不可读或 JSON 已损坏。", details={"path": str(path)}) from exc
    if value.get("contractType") != expected_type or canonical_hash(value) != value.get("contentHash"):
        raise ToolError("CONTENT_PACKAGE_HASH_MISMATCH", "冻结包类型或 canonical-json-v1 哈希无效。", details={"path": str(path)})
    return value


def _png_dimensions(path: Path) -> tuple[int, int]:
    with path.open("rb") as handle:
        header = handle.read(24)
    if len(header) != 24 or header[:8] != b"\x89PNG\r\n\x1a\n" or header[12:16] != b"IHDR":
        raise ToolError("THUMBNAIL_FORMAT_INVALID", "阶段4真实封面 fixture 必须是可读 PNG。")
    return struct.unpack(">II", header[16:24])


def _markdown_cell(value: Any) -> str:
    return str(value).replace("|", "\\|").replace("\r", " ").replace("\n", "<br>")


def _foreign_language_quality_contract(
    gate: Any,
    *,
    target_language: str,
    episode_count: int,
    target_script_hash: str,
) -> dict[str, Any]:
    if target_language.lower().startswith("zh"):
        if not isinstance(gate, dict) or gate.get("notApplicable") is not True:
            raise ToolError(
                "FOREIGN_LANGUAGE_QUALITY_GATE_INVALID",
                "中文母稿也必须明确记录外语质量保险门为不适用。",
            )
        reason = gate.get("reasonZh")
        if not isinstance(reason, str) or not reason.strip():
            raise ToolError("FOREIGN_LANGUAGE_QUALITY_GATE_INVALID", "外语质量门不适用原因不能为空。")
        core = {
            "version": "1.0.0",
            "targetScriptHash": target_script_hash,
            "targetLanguage": target_language,
            "status": "NOT_APPLICABLE",
            "reviewMode": "not-applicable-target-is-chinese",
            "independentFromAuthoring": False,
            "revisionRounds": 0,
            "episodeResults": [],
            "summaryZh": reason.strip(),
        }
        return {**core, "contentHash": _json_hash(core)}

    if not isinstance(gate, dict) or gate.get("passed") is not True:
        raise ToolError("FOREIGN_LANGUAGE_QUALITY_GATE_FAILED", "独立外语质量保险门未通过，不能冻结正式稿。")
    if gate.get("reviewMode") != "independent-second-pass" or gate.get("independentFromAuthoring") is not True:
        raise ToolError(
            "FOREIGN_LANGUAGE_REVIEW_NOT_INDEPENDENT",
            "外语质量保险必须在创作完成后使用独立二次审校上下文执行。",
        )
    authoring_pass_id = gate.get("authoringPassId")
    review_pass_id = gate.get("reviewPassId")
    if (
        not isinstance(authoring_pass_id, str)
        or not authoring_pass_id.strip()
        or not isinstance(review_pass_id, str)
        or not review_pass_id.strip()
        or authoring_pass_id == review_pass_id
    ):
        raise ToolError("FOREIGN_LANGUAGE_REVIEW_NOT_INDEPENDENT", "创作批次与外语审校批次必须分别标识且不能相同。")
    episodes = gate.get("episodes")
    if not isinstance(episodes, list) or len(episodes) != episode_count:
        raise ToolError("FOREIGN_LANGUAGE_QUALITY_GATE_INVALID", "每集必须有且只有一份独立外语质量审校记录。")
    normalized_episodes: list[dict[str, Any]] = []
    revision_rounds = 0
    for number, episode in enumerate(episodes, 1):
        checks = episode.get("checks") if isinstance(episode, dict) else None
        findings = episode.get("findingsZh") if isinstance(episode, dict) else None
        revision_count = episode.get("revisionCount") if isinstance(episode, dict) else None
        if (
            not isinstance(episode, dict)
            or episode.get("episode") != number
            or episode.get("passed") is not True
            or not isinstance(checks, dict)
            or set(checks) != FOREIGN_LANGUAGE_QUALITY_CHECKS
            or not all(checks.values())
            or not isinstance(findings, str)
            or not findings.strip()
            or not isinstance(revision_count, int)
            or isinstance(revision_count, bool)
            or not 0 <= revision_count <= 3
        ):
            raise ToolError(
                "FOREIGN_LANGUAGE_QUALITY_GATE_INVALID",
                "外语审校硬项、中文结论或定向修订轮数不完整。",
                details={"episode": number},
            )
        revision_rounds = max(revision_rounds, revision_count)
        normalized_episodes.append(
            {
                "episodeNumber": number,
                "status": "PASSED",
                "revisionCount": revision_count,
                "checks": {key: True for key in sorted(FOREIGN_LANGUAGE_QUALITY_CHECKS)},
                "findingsZh": findings.strip(),
            }
        )
    summary = gate.get("summaryZh")
    if not isinstance(summary, str) or not summary.strip():
        raise ToolError("FOREIGN_LANGUAGE_QUALITY_GATE_INVALID", "外语质量门必须提供中文审校总结。")
    core = {
        "version": "1.0.0",
        "targetScriptHash": target_script_hash,
        "targetLanguage": target_language,
        "status": "PASSED",
        "reviewMode": "independent-second-pass",
        "independentFromAuthoring": True,
        "authoringPassId": authoring_pass_id.strip(),
        "reviewPassId": review_pass_id.strip(),
        "revisionRounds": revision_rounds,
        "episodeResults": normalized_episodes,
        "summaryZh": summary.strip(),
    }
    return {**core, "contentHash": _json_hash(core)}


def _packaging_review_markdown(
    *,
    title_candidates: list[dict[str, Any]],
    selected_title_id: str,
    description_body: str,
    description_chinese: str,
    hashtag_translations: list[dict[str, str]],
) -> str:
    lines = [
        "# 标题、简介与 Hashtags 双语审核",
        "",
        "## 标题候选",
        "",
        "| 选择 | 目标语言标题 | 中文翻译 | 评分 | 事实依据 | 承诺兑现 | 原句复制 |",
        "|---|---|---|---:|---|---|---|",
    ]
    for item in title_candidates:
        lines.append(
            "| {selected} | {target} | {chinese} | {score} | {basis} | {promise} | {copied} |".format(
                selected="正式采用" if item["titleId"] == selected_title_id else "候选",
                target=_markdown_cell(item["text"]),
                chinese=_markdown_cell(item["zhTranslation"]),
                score=item["audienceFit"],
                basis=_markdown_cell(item["factBasis"]),
                promise="通过" if item["promiseFulfilled"] else "失败",
                copied="否" if not item["sampleWordingCopied"] else "是",
            )
        )
    lines.extend(
        [
            "",
            "## YouTube 简介（目标语言）",
            "",
            description_body.rstrip(),
            "",
            "## YouTube 简介（中文翻译，仅供审核）",
            "",
            description_chinese.rstrip(),
            "",
            "## Hashtags 双语对照",
            "",
            "| 正式 Hashtag | 中文含义 |",
            "|---|---|",
        ]
    )
    lines.extend(f"| {_markdown_cell(item['hashtag'])} | {_markdown_cell(item['chinese'])} |" for item in hashtag_translations)
    lines.extend(["", "> 中文翻译只供用户审核，不进入 YouTube 发布字段。", ""])
    return "\n".join(lines)


def _thumbnail_review_markdown(
    *,
    strategy: dict[str, Any],
    candidates: list[dict[str, Any]],
    selected_thumbnail_id: str,
    thumbnail_text_chinese: str,
    ctr_review: dict[str, Any],
) -> str:
    lines = [
        "# 封面候选与选择结果",
        "",
        f"- 目标语言封面短文案：{strategy['targetLanguageText']}",
        f"- 中文含义：{thumbnail_text_chinese}",
        f"- 核心主体：{strategy['subject']}",
        f"- 核心冲突：{strategy['conflict']}",
        f"- 正式选择：`{selected_thumbnail_id}`",
        f"- CTR 联评：{ctr_review['status']}／{ctr_review['score']}",
        f"- 选择结论：{ctr_review['conclusion']}",
        "",
        "## 五张候选",
        "",
        "| 选择 | 候选 | 差异 | 评分 | 文字 | 事实 | 移动端 |",
        "|---|---|---|---:|---|---|---|",
    ]
    for item in candidates:
        lines.append(
            "| {selected} | {candidate} | {difference} | {score} | {text} | {facts} | {mobile} |".format(
                selected="正式采用" if item["candidateId"] == selected_thumbnail_id else "候选",
                candidate=_markdown_cell(item["candidateId"]),
                difference=_markdown_cell(item["visualDifference"]),
                score=item["score"],
                text="通过" if item["textAccurate"] else "失败",
                facts="通过" if item["factsConsistent"] else "失败",
                mobile="通过" if item["mobileReadable"] else "失败",
            )
        )
    return "\n".join(lines) + "\n"


class ContentLoop:
    """Freeze AI-authored content into deterministic, traceable stage-4 packages."""

    def __init__(
        self,
        store: Any,
        sources: Any,
        *,
        plugin_root: Path | None = None,
        analyses: Any = None,
        video_analyses: Any = None,
        content_analyses: Any = None,
        style_provider: Any = None,
    ) -> None:
        self.store = store
        self.sources = sources
        self.plugin_root = plugin_root
        self.analyses = analyses
        self.video_analyses = video_analyses
        self.content_analyses = content_analyses
        self.style_provider = style_provider

    def _validate_contract_schema(self, contract: dict[str, Any], schema_name: str) -> None:
        if not self.plugin_root:
            return
        contracts_root = resolve_contracts_root(self.plugin_root)
        schema_root = contracts_root / "schemas"
        schema_path = schema_root / schema_name
        if not schema_path.is_file():
            raise ToolError("CONTENT_SCHEMA_MISSING", "安装内容缺少阶段4契约 Schema。", details={"schema": schema_name})
        try:
            resources = []
            for path in sorted(schema_root.glob("*.schema.json")):
                schema = json.loads(path.read_text(encoding="utf-8"))
                resources.append((schema["$id"], Resource.from_contents(schema)))
            selected = json.loads(schema_path.read_text(encoding="utf-8"))
            validator = Draft202012Validator(
                selected,
                registry=Registry().with_resources(resources),
                format_checker=FormatChecker(),
            )
            errors = sorted(validator.iter_errors(contract), key=lambda item: list(item.absolute_path))
        except (OSError, json.JSONDecodeError, KeyError) as exc:
            raise ToolError("CONTENT_SCHEMA_INVALID", "安装内容中的阶段4 Schema 不可读。") from exc
        if errors:
            first = errors[0]
            location = "/".join(str(item) for item in first.absolute_path) or "<root>"
            raise ToolError(
                "CONTENT_CONTRACT_SCHEMA_FAILED",
                "冻结包未通过阶段4契约 Schema。",
                details={"schema": schema_name, "location": location, "message": first.message, "errorCount": len(errors)},
            )

    def capabilities(self) -> dict[str, Any]:
        return {
            "contentLoopVersion": CONTENT_LOOP_VERSION,
            "packageSchemaVersion": PACKAGE_SCHEMA_VERSION,
            "routes": {
                "market-original": {"available": True, "label": "目标市场原创"},
                "channel-library": {"available": True, "label": "频道画像锚定"},
                "provided-outline": {"available": True, "label": "用户大纲直通"},
                "trend": {"available": False, "reason": "trend-analysis-skill-unavailable"},
                "single-reference": {"available": True, "requires": "video-copy-deconstruction Analysis Package v1"},
                "multi-reference": {"available": True, "requires": "video-copy-deconstruction Analysis Package v1"},
                "imitation": {"available": True, "requires": "original-imitation-writing Writing Style Contract v1"},
                "direct-rewrite": {"available": True, "requires": "content-deconstruct Analysis Package v1"},
                "synthesis-rewrite": {"available": True, "requires": "content-deconstruct Analysis Package v1"},
            },
            "extensionInterfaces": {
                "analysis-package-v1": {
                    "status": "available",
                    "providers": ["channel-distillation", "video-copy-deconstruction", "content-deconstruct"],
                    "consumers": ["direct-rewrite", "synthesis-rewrite", "content-review-edit"],
                },
                "writing-style-contract-v1": {
                    "status": "available",
                    "provider": "original-imitation-writing",
                    "consumers": ["imitation", "topic-center", "manuscript-center"],
                },
                "image-provider-v1": {"status": "available", "modes": ["real", "prompt_only"]},
            },
            "extensions": _extension_capabilities(),
            "sourceGate": {
                "accepted": ["CONTENT_READY"],
                "conditional": "PARTIAL requires an explicit per-source acceptance",
            },
            "userReviewDocuments": {
                "available": True,
                "schemaVersion": REVIEW_DOCUMENT_SCHEMA_VERSION,
                "directoryName": "用户审核文档",
                "documentIds": list(DOCUMENT_SPECS),
                "productionSeparationEnforced": True,
            },
            "boundaries": {
                "workshop": False,
                "publisherAuthorization": False,
                "upload": False,
                "analytics": False,
                "longTermLearningWrite": False,
            },
        }

    def _project_root(self, channel_profile_id: str, project_id: str) -> Path:
        return self.store.channel_path(channel_profile_id) / "projects" / _safe_identifier(project_id, "projectId")

    def _state_path(self, channel_profile_id: str, project_id: str) -> Path:
        return self._project_root(channel_profile_id, project_id) / "content-state.json"

    def _load_state(self, channel_profile_id: str, project_id: str) -> dict[str, Any]:
        path = self._state_path(channel_profile_id, project_id)
        if not path.is_file():
            raise ToolError("CONTENT_PROJECT_NOT_FOUND", "没有找到指定的阶段4内容项目。")
        try:
            state = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ToolError("CONTENT_STATE_INVALID", "项目状态文件损坏。") from exc
        if state.get("projectId") != project_id or state.get("channelProfileId") != channel_profile_id:
            raise ToolError("CONTENT_STATE_IDENTITY_MISMATCH", "项目状态身份不匹配。")
        return state

    def _save_state(self, state: dict[str, Any]) -> None:
        state["updatedAt"] = utc_now()
        _atomic_json(self._state_path(state["channelProfileId"], state["projectId"]), state)

    def start_project(
        self,
        *,
        task_id: Any,
        channel_profile_id: Any,
        binding_proof: Any,
        project_id: Any,
        source_mode: Any,
        source_packages: Any = None,
        analysis_packages: Any = None,
        writing_style_contracts: Any = None,
        provided_outline: Any = None,
        learning_snapshot: Any = None,
        one_time_modifications: Any = None,
        long_term_learning: Any = None,
    ) -> dict[str, Any]:
        self.store.assert_binding(
            task_id=task_id, channel_profile_id=channel_profile_id, binding_proof=binding_proof
        )
        project_id = _safe_identifier(project_id, "projectId")
        if source_mode not in SOURCE_MODES:
            raise ToolError("CONTENT_ROUTE_INVALID", "不支持该选题路线。")
        enabled_analysis_route = source_mode in {
            "single-reference",
            "multi-reference",
            "direct-rewrite",
            "synthesis-rewrite",
        } and bool(analysis_packages)
        enabled_style_route = source_mode == "imitation" and bool(writing_style_contracts)
        if source_mode in EXTENSION_MODES and not (enabled_analysis_route or enabled_style_route):
            interface = "writing-style-contract-v1" if source_mode == "imitation" else "analysis-package-v1"
            raise ToolError(
                "CONTENT_EXTENSION_UNAVAILABLE",
                "当前未安装该路线需要的拆解／趋势／仿写 Skill；不能从标题或来源元数据伪造内容。",
                details={"route": source_mode, "requiredInterface": interface},
            )
        if long_term_learning not in (None, False, {}):
            raise ToolError(
                "LONG_TERM_LEARNING_FORBIDDEN",
                "阶段4只读取频道学习快照；长期规则必须等待独立 G7 用户确认。",
            )
        if learning_snapshot is not None:
            if not isinstance(learning_snapshot, dict) or learning_snapshot.get("mode") != "read_only":
                raise ToolError("LEARNING_SNAPSHOT_INVALID", "频道学习只允许读取明确标记为 read_only 的快照。")
        if one_time_modifications is None:
            one_time_modifications = []
        if not isinstance(one_time_modifications, list) or any(not isinstance(item, str) for item in one_time_modifications):
            raise ToolError("INVALID_ARGUMENT", "oneTimeModifications 必须是字符串数组。")

        outline_hash = None
        if source_mode == "provided-outline":
            if not isinstance(provided_outline, str) or len(provided_outline.strip()) < 80:
                raise ToolError("OUTLINE_REQUIRED", "用户大纲直通需要至少 80 字的可辨认大纲。")
            outline_hash = hashlib.sha256(provided_outline.encode("utf-8")).hexdigest()
        elif provided_outline is not None:
            raise ToolError("OUTLINE_ROUTE_MISMATCH", "只有用户大纲直通路线可以冻结 providedOutline。")

        channel_summary = self.store.get_channel(channel_profile_id)
        channel = channel_summary.get("channelProfile")
        production = channel_summary.get("productionProfile")
        if not isinstance(channel, dict) or not isinstance(production, dict):
            raise ToolError("CHANNEL_CONTEXT_NOT_READY", "阶段2频道档案或生产预设尚未冻结。")
        locks: list[dict[str, Any]] = []
        for requested in source_packages or []:
            if not isinstance(requested, dict) or not isinstance(requested.get("sourcePackageId"), str):
                raise ToolError("SOURCE_REFERENCE_INVALID", "资料引用必须包含 sourcePackageId。")
            detail = self.sources.get_source(
                channel_profile_id=channel_profile_id,
                source_package_id=requested["sourcePackageId"],
            )
            manifest = detail["manifest"]
            if canonical_hash(manifest) != manifest.get("contentHash"):
                raise ToolError("SOURCE_HASH_MISMATCH", "Source Package 的 canonical 哈希无效。")
            status = manifest["status"]
            accepted_partial = bool(requested.get("acceptPartial", False))
            accepted_at = requested.get("acceptedAt")
            known_limitations = requested.get("knownLimitations")
            if status == "PARTIAL" and (
                not accepted_partial
                or not isinstance(accepted_at, str)
                or not accepted_at
                or not isinstance(known_limitations, list)
                or not known_limitations
                or any(not isinstance(item, str) or not item for item in known_limitations)
            ):
                raise ToolError(
                    "PARTIAL_SOURCE_ACCEPTANCE_REQUIRED",
                    "PARTIAL 资料只有在用户逐项明确接受并记录时间与已知限制后才能进入内容生产。",
                    details={"sourcePackageId": manifest["sourcePackageId"]},
                )
            if status not in {"CONTENT_READY", "PARTIAL"}:
                raise ToolError(
                    "SOURCE_NOT_CONTENT_READY",
                    "阶段4只接收 CONTENT_READY 或用户明确接受的 PARTIAL 资料。",
                    details={"sourcePackageId": manifest["sourcePackageId"], "status": status},
                )
            locks.append(
                {
                    "sourcePackageId": manifest["sourcePackageId"],
                    "version": manifest["version"],
                    "contentHash": manifest["contentHash"],
                    "status": status,
                    "acceptedPartial": accepted_partial,
                    "acceptedPartialAt": accepted_at if accepted_partial else None,
                    "knownLimitations": known_limitations if accepted_partial else [],
                    "provenance": manifest["provenance"],
                    "rightsBoundary": manifest["rightsBoundary"],
                }
            )
        style_locks: list[dict[str, Any]] = []
        for requested in writing_style_contracts or []:
            if not isinstance(requested, dict) or not isinstance(requested.get("imitationId"), str):
                raise ToolError("WRITING_STYLE_REFERENCE_INVALID", "仿写契约引用必须包含 imitationId。")
            if self.style_provider is None:
                raise ToolError("WRITING_STYLE_PROVIDER_UNAVAILABLE", "原创仿写契约提供器尚未接入内容中心。")
            imitation_id = requested["imitationId"]
            contract = self.style_provider.writing_contract(
                channel_profile_id=channel_profile_id,
                imitation_id=imitation_id,
            )
            if contract.get("targetChannelProfileId") != channel_profile_id:
                raise ToolError("WRITING_STYLE_CHANNEL_MISMATCH", "仿写契约不属于当前目标频道。")
            for frozen in contract.get("sourceLocks", []):
                detail = self.sources.get_source(
                    channel_profile_id=channel_profile_id,
                    source_package_id=frozen["sourcePackageId"],
                )
                manifest = detail["manifest"]
                if canonical_hash(manifest) != manifest.get("contentHash") or manifest.get("contentHash") != frozen.get("contentHash"):
                    raise ToolError("WRITING_STYLE_SOURCE_VERSION_CHANGED", "仿写契约绑定的 Source Package 已变化。")
                existing = next((item for item in locks if item["sourcePackageId"] == manifest["sourcePackageId"]), None)
                if existing is not None:
                    if existing["contentHash"] != manifest["contentHash"]:
                        raise ToolError("SOURCE_LOCK_CONFLICT", "内容项目对同一资料绑定了不同版本。")
                    continue
                locks.append(json.loads(json.dumps(frozen, ensure_ascii=False)))
            style_locks.append(
                {
                    "imitationId": imitation_id,
                    "writingStyleContract": _contract_ref(contract),
                    "selectedDirectionId": contract["selectedDirection"]["directionId"],
                    "consumers": ["topic-center", "manuscript-center"],
                }
            )
        if source_mode == "imitation":
            if len(style_locks) != 1:
                raise ToolError("WRITING_STYLE_CONTRACT_REQUIRED", "原创仿写路线必须且只能绑定一份已由用户确认的 Writing Style Contract。")
            if analysis_packages:
                raise ToolError("IMITATION_ROUTE_INPUT_CONFLICT", "原创仿写路线由 Writing Style Contract 统一封装来源，不能再并列传入分析包。")
        elif style_locks:
            raise ToolError("WRITING_STYLE_ROUTE_MISMATCH", "Writing Style Contract 只能用于 imitation 路线。")
        analysis_locks: list[dict[str, Any]] = []
        analysis_review_roots: list[Path] = []
        for requested in analysis_packages or []:
            if not isinstance(requested, dict):
                raise ToolError("ANALYSIS_REFERENCE_INVALID", "分析引用必须是对象。")
            if isinstance(requested.get("distillationId"), str):
                if self.analyses is None:
                    raise ToolError("ANALYSIS_PROVIDER_UNAVAILABLE", "频道蒸馏提供器尚未接入内容中心。")
                identifier_key = "distillationId"
                identifier = requested[identifier_key]
                contract = self.analyses.analysis_package(
                    channel_profile_id=channel_profile_id,
                    distillation_id=identifier,
                )
            elif isinstance(requested.get("deconstructionId"), str):
                provider = self.content_analyses if source_mode in {"direct-rewrite", "synthesis-rewrite"} else self.video_analyses
                if provider is None:
                    raise ToolError("ANALYSIS_PROVIDER_UNAVAILABLE", "文案拆解提供器尚未接入内容中心。")
                identifier_key = "deconstructionId"
                identifier = requested[identifier_key]
                contract = provider.analysis_package(
                    channel_profile_id=channel_profile_id,
                    deconstruction_id=identifier,
                )
                if provider is self.content_analyses:
                    detail = provider.get(
                        channel_profile_id=channel_profile_id,
                        deconstruction_id=identifier,
                    )
                    review = detail.get("outputs", {}).get("userReviewDocuments", {})
                    context_root = review.get("contextRoot") if isinstance(review, dict) else None
                    if not isinstance(context_root, str) or not context_root:
                        raise ToolError(
                            "CONTENT_REVIEW_DOCUMENTS_REQUIRED",
                            "拆解包缺少可直接查看的拆解报告和迁移方向文档。",
                        )
                    analysis_review_roots.append(Path(context_root))
            else:
                raise ToolError("ANALYSIS_REFERENCE_INVALID", "分析引用必须包含 distillationId 或 deconstructionId。")
            if contract.get("targetChannelProfileId") != channel_profile_id:
                raise ToolError("ANALYSIS_CHANNEL_MISMATCH", "分析包不属于当前目标频道。")
            analysis_locks.append(
                {
                    identifier_key: identifier,
                    "analysisPackage": _contract_ref(contract),
                    "analysisKind": contract["analysisKind"],
                    "mode": contract.get("mode"),
                    "consumers": ["topic-center", "manuscript-center"],
                }
            )
        if source_mode == "channel-library" and not locks and not analysis_locks:
            raise ToolError("CHANNEL_SOURCE_REQUIRED", "频道画像锚定路线至少需要一份合格的频道资料或冻结分析包。")
        if source_mode == "channel-library" and any(
            item["analysisKind"] != "channel-distillation" for item in analysis_locks
        ):
            raise ToolError("ANALYSIS_ROUTE_MISMATCH", "频道画像锚定路线只能消费频道蒸馏分析包。")
        if source_mode in {"single-reference", "multi-reference"}:
            if len(analysis_locks) != 1 or analysis_locks[0]["analysisKind"] != "video-copy-deconstruction":
                raise ToolError("VIDEO_ANALYSIS_PACKAGE_REQUIRED", "单／多视频参考路线必须且只能绑定一份视频文案拆解 Analysis Package。")
            expected_modes = {"single"} if source_mode == "single-reference" else {"parallel", "compare"}
            if analysis_locks[0].get("mode") not in expected_modes:
                raise ToolError("VIDEO_ANALYSIS_MODE_MISMATCH", "视频拆解模式与单／多视频参考路线不一致。")
        if source_mode in {"direct-rewrite", "synthesis-rewrite"}:
            if len(analysis_locks) != 1 or analysis_locks[0]["analysisKind"] != "content-deconstruction":
                raise ToolError("CONTENT_DECONSTRUCTION_PACKAGE_REQUIRED", "文案仿写必须绑定一份 Content Deconstruction Package v1。")
            expected_modes = {"single"} if source_mode == "direct-rewrite" else {"parallel", "compare"}
            if analysis_locks[0].get("mode") not in expected_modes:
                raise ToolError("CONTENT_DECONSTRUCTION_MODE_MISMATCH", "拆解模式与单源／融合仿写模式不一致。")

        brief = {
            "schemaVersion": CONTENT_LOOP_VERSION,
            "projectId": project_id,
            "channelProfileId": channel_profile_id,
            "sourceMode": source_mode,
            "channelContext": {
                "channelProfile": _contract_ref(channel),
                "productionProfile": _contract_ref(production),
                "targetRegion": channel["targetRegion"],
                "targetLanguage": channel["outputLanguage"],
                "productionDefaults": production["defaults"],
            },
            "sourceLocks": locks,
            "analysisLocks": analysis_locks,
            "styleLocks": style_locks,
            "providedOutlineHash": outline_hash,
            "learningSnapshot": learning_snapshot,
            "oneTimeModifications": one_time_modifications,
            "extensions": _extension_capabilities(),
        }
        request_hash = _json_hash(brief)
        state_path = self._state_path(channel_profile_id, project_id)
        if state_path.is_file():
            existing = self._load_state(channel_profile_id, project_id)
            if existing.get("requestHash") != request_hash:
                raise ToolError("CONTENT_PROJECT_EXISTS", "同一 projectId 已绑定不同内容简报；不会覆盖旧项目。")
            return {"state": existing, "idempotent": True, "confirmationCard": existing["confirmationCard"]}

        root = self._project_root(channel_profile_id, project_id)
        root.mkdir(parents=True, exist_ok=False)
        if provided_outline is not None:
            _atomic_bytes(root / "provided-outline-v001.txt", provided_outline.encode("utf-8"))
        _atomic_json(root / "content-brief-v001.json", brief)
        created = utc_now()
        state = {
            "schemaVersion": CONTENT_LOOP_VERSION,
            "projectId": project_id,
            "channelProfileId": channel_profile_id,
            "sourceMode": source_mode,
            "targetRegion": channel["targetRegion"],
            "targetLanguage": channel["outputLanguage"],
            "state": "DRAFT_BRIEF",
            "createdAt": created,
            "updatedAt": created,
            "requestHash": request_hash,
            "briefPath": "content-brief-v001.json",
            "sourceLocks": locks,
            "analysisLocks": analysis_locks,
            "styleLocks": style_locks,
            "topicCheckpoint": {"version": "1.0.0", "completedUnits": 0, "candidateIds": [], "items": []},
            "activePackages": {"topic": None, "manuscript": None, "publishing": None},
            "invalidations": [],
            "oneTimeModifications": one_time_modifications,
            "learningSnapshotMode": "read_only" if learning_snapshot else "none",
            "confirmationCard": {
                "gate": "G2",
                "targetRegion": channel["targetRegion"],
                "targetLanguage": channel["outputLanguage"],
                "sourceMode": source_mode,
                "sourceCount": len(locks),
                "styleContractCount": len(style_locks),
                "partialAcceptedCount": sum(1 for item in locks if item["status"] == "PARTIAL"),
                "next": "生成完整候选并逐项写入检查点",
            },
        }
        if source_mode in {"direct-rewrite", "synthesis-rewrite"}:
            if len(analysis_review_roots) != 1:
                raise ToolError("CONTENT_REVIEW_DOCUMENTS_REQUIRED", "仿写项目必须绑定一套拆解审核文档。")
            try:
                copy_review_documents(
                    analysis_review_roots[0],
                    root,
                    ("source-summary", "deconstruction-report", "transfer-directions"),
                    updated_at=created,
                )
            except ValueError as exc:
                raise ToolError("CONTENT_REVIEW_DOCUMENTS_REQUIRED", str(exc)) from exc
            state["userReviewDocuments"] = review_documents_view(root)
        self._save_state(state)
        return {"state": state, "idempotent": False, "confirmationCard": state["confirmationCard"]}

    def _validate_claims(self, claims: Any, source_locks: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if not isinstance(claims, list) or not claims:
            raise ToolError("EVIDENCE_REQUIRED", "候选必须保留 fact／inference／unknown 分类和来源边界。")
        source_index = {
            (item["sourcePackageId"], item["version"], item["contentHash"]): item
            for item in source_locks
        }
        seen: set[str] = set()
        normalized: list[dict[str, Any]] = []
        for claim in claims:
            if not isinstance(claim, dict) or claim.get("classification") not in {"fact", "inference", "unknown"}:
                raise ToolError("EVIDENCE_CLASSIFICATION_INVALID", "证据分类只允许 fact、inference、unknown。")
            claim_id = _safe_identifier(claim.get("claimId"), "claimId")
            if claim_id in seen or not isinstance(claim.get("statement"), str) or not claim["statement"].strip():
                raise ToolError("EVIDENCE_CLAIM_INVALID", "证据声明必须有唯一 ID 和非空内容。")
            seen.add(claim_id)
            raw_sources = claim.get("sources")
            if raw_sources is None:
                raw_sources = [
                    {
                        "sourcePackage": {
                            "targetContractType": "source-package",
                            "targetId": reference.get("sourcePackageId"),
                            "targetVersion": reference.get("version"),
                            "targetSchemaVersion": PACKAGE_SCHEMA_VERSION,
                            "targetHash": reference.get("contentHash"),
                        },
                        "locator": reference.get("locator", "frozen-source-package"),
                    }
                    for reference in claim.get("sourceRefs") or []
                ]
            clean_sources = []
            for reference in raw_sources:
                package_ref = reference.get("sourcePackage", {}) if isinstance(reference, dict) else {}
                key = (package_ref.get("targetId"), package_ref.get("targetVersion"), package_ref.get("targetHash"))
                if key not in source_index or package_ref.get("targetContractType") != "source-package":
                    raise ToolError("EVIDENCE_SOURCE_MISMATCH", "证据声明引用了未冻结或哈希不匹配的资料版本。")
                clean_sources.append(
                    {
                        "sourcePackage": {
                            "targetContractType": "source-package",
                            "targetId": key[0],
                            "targetVersion": key[1],
                            "targetSchemaVersion": PACKAGE_SCHEMA_VERSION,
                            "targetHash": key[2],
                        },
                        "locator": reference.get("locator") or source_index[key]["provenance"]["locator"],
                    }
                )
            classification = claim["classification"]
            if classification in {"fact", "inference"} and not clean_sources:
                raise ToolError("EVIDENCE_SOURCE_REQUIRED", "fact 与 inference 必须绑定冻结资料来源。")
            if classification == "unknown" and clean_sources:
                raise ToolError("UNKNOWN_SOURCE_INVALID", "unknown 必须明确无可核验来源，不能伪装成事实。")
            item = {
                "claimId": claim_id,
                "classification": classification,
                "statement": claim["statement"],
                "sources": clean_sources,
            }
            if classification in {"fact", "inference"}:
                confidence = claim.get("confidence")
                if not isinstance(confidence, (int, float)) or isinstance(confidence, bool) or not 0 <= confidence <= 1:
                    raise ToolError("EVIDENCE_CONFIDENCE_INVALID", "fact 与 inference 需要 0–1 的置信度。")
                item["confidence"] = confidence
            normalized.append(item)
        return normalized

    def _validate_candidate(self, candidate: Any, state: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(candidate, dict):
            raise ToolError("TOPIC_CANDIDATE_INVALID", "完整候选必须是对象。")
        required = {
            "candidateId",
            "audience",
            "evidenceClaims",
            "storyDriver",
            "coreSellingPoints",
            "worldRules",
            "storyFacts",
            "characters",
            "completeOutline",
            "episodePlots",
            "productionRecommendation",
            "scores",
            "strengths",
            "risks",
            "packagingBrief",
        }
        missing = sorted(required - set(candidate))
        if missing:
            raise ToolError("TOPIC_CANDIDATE_INVALID", "完整候选缺少字段。", details={"missing": missing})
        _safe_identifier(candidate["candidateId"], "candidateId")
        if state["sourceMode"] == "imitation":
            compliance = candidate.get("styleContractCompliance")
            expected_direction = state["styleLocks"][0]["selectedDirectionId"]
            required_compliance = {
                "selectedDirectionId": expected_direction,
                "unifiedCausalEngineApplied": True,
                "functionalIsomorphismApplied": True,
                "sourceRolesAndWeightsApplied": True,
                "copyBoundaryPassed": True,
            }
            if compliance != required_compliance:
                raise ToolError(
                    "WRITING_STYLE_COMPLIANCE_FAILED",
                    "仿写候选必须应用已确认方向、统一因果、功能同构、来源权重和反复制硬门。",
                )
        audience = candidate["audience"]
        audience_required = {"region", "targetLanguage", "locale", "commercialOrientation"}
        if (
            not isinstance(audience, dict)
            or set(audience) != audience_required
            or audience.get("targetLanguage") != state["targetLanguage"]
            or audience.get("region") != state["targetRegion"]
            or audience.get("commercialOrientation") not in {"male-oriented", "female-oriented", "general"}
        ):
            raise ToolError("TOPIC_LANGUAGE_MISMATCH", "候选受众语言必须与频道目标语言一致。")
        candidate["evidenceClaims"] = self._validate_claims(candidate["evidenceClaims"], state["sourceLocks"])
        for key in ("coreSellingPoints", "worldRules", "characters", "episodePlots", "strengths"):
            if not isinstance(candidate[key], list) or not candidate[key]:
                raise ToolError("TOPIC_CANDIDATE_INVALID", f"{key} 必须是非空数组。")
        if not isinstance(candidate["risks"], list):
            raise ToolError("TOPIC_CANDIDATE_INVALID", "risks 必须是数组。")
        story_facts = candidate["storyFacts"]
        fact_keys = {"lockedFacts", "worldRules", "relationships", "climax", "ending"}
        if not isinstance(story_facts, dict) or set(story_facts) != fact_keys:
            raise ToolError("STORY_FACTS_INVALID", "故事事实必须冻结事实、世界规则、关系、高潮和结局。")
        if any(not isinstance(story_facts[key], list) or not story_facts[key] for key in ("lockedFacts", "worldRules", "relationships")):
            raise ToolError("STORY_FACTS_INVALID", "故事事实数组不能为空。")
        outline = candidate["completeOutline"]
        if not isinstance(outline, dict) or set(outline) != {"opening", "development", "climax", "ending"}:
            raise ToolError("TOPIC_OUTLINE_INCOMPLETE", "候选需要有开端、发展、高潮与结局的完整大纲。")
        if sum(len(str(value)) for value in outline.values()) < 80:
            raise ToolError("TOPIC_OUTLINE_INCOMPLETE", "完整大纲信息不足。")
        recommendation = candidate["productionRecommendation"]
        if not isinstance(recommendation, dict):
            raise ToolError("PRODUCTION_RECOMMENDATION_INVALID", "生产建议必须是对象。")
        for key in ("targetCharacters", "estimatedDurationSeconds", "episodeCount"):
            value = recommendation.get(key)
            if not isinstance(value, int) or isinstance(value, bool) or value < 1:
                raise ToolError("PRODUCTION_RECOMMENDATION_INVALID", "篇幅、时长和集数必须是精确正整数。")
        if not isinstance(recommendation.get("reason"), str) or not recommendation["reason"]:
            raise ToolError("PRODUCTION_RECOMMENDATION_INVALID", "生产建议需要说明理由。")
        if len(candidate["episodePlots"]) != recommendation["episodeCount"]:
            raise ToolError("EPISODE_COUNT_MISMATCH", "逐集剧情数量必须等于精确推荐集数。")
        for number, episode in enumerate(candidate["episodePlots"], 1):
            if not isinstance(episode, dict) or set(episode) != {"episodeNumber", "startState", "progress", "audienceReward", "endState"} or episode["episodeNumber"] != number:
                raise ToolError("EPISODE_PLOT_INVALID", "逐集剧情字段或顺序无效。")
        scores = candidate["scores"]
        if not isinstance(scores, dict) or set(scores) != set(SCORE_KEYS):
            raise ToolError("TOPIC_SCORES_INVALID", "七项评分名称不完整或出现额外字段。")
        if any(not isinstance(scores[key], (int, float)) or isinstance(scores[key], bool) or not 0 <= scores[key] <= 10 for key in SCORE_KEYS):
            raise ToolError("TOPIC_SCORES_INVALID", "七项评分必须在 0–10 之间。")
        packaging = candidate["packagingBrief"]
        if not isinstance(packaging, dict) or not all(
            isinstance(packaging.get(key), str) and packaging[key].strip()
            for key in ("titleInformationDirection", "thumbnailVisualTask", "videoPresentationDirection")
        ):
            raise ToolError("PACKAGING_BRIEF_INVALID", "候选必须保存完整的后续包装任务，但不得冒充正式资产。")
        if state["sourceMode"] in {"direct-rewrite", "synthesis-rewrite"}:
            transformation_map = candidate.get("sourceTransformationMap")
            expected_source_ids = {item["sourcePackageId"] for item in state["sourceLocks"]}
            if not isinstance(transformation_map, list) or not transformation_map:
                raise ToolError("SOURCE_TRANSFORMATION_MAP_REQUIRED", "文案仿写必须记录每个来源的功能迁移与原创实现。")
            required_keys = {
                "sourcePackageId",
                "role",
                "retainedFunction",
                "newImplementation",
                "newCausalLink",
                "protectedBoundary",
            }
            actual_source_ids: list[str] = []
            for entry in transformation_map:
                if (
                    not isinstance(entry, dict)
                    or set(entry) != required_keys
                    or any(not isinstance(entry[key], str) or not entry[key].strip() for key in required_keys)
                ):
                    raise ToolError("SOURCE_TRANSFORMATION_MAP_INVALID", "来源迁移表字段必须完整且为非空文本。")
                actual_source_ids.append(entry["sourcePackageId"])
            if len(actual_source_ids) != len(set(actual_source_ids)) or set(actual_source_ids) != expected_source_ids:
                raise ToolError("SOURCE_TRANSFORMATION_MAP_INCOMPLETE", "来源迁移表必须与全部冻结来源一一对应。")
        return json.loads(json.dumps(candidate, ensure_ascii=False))

    def checkpoint_topic(
        self,
        *,
        task_id: Any,
        channel_profile_id: Any,
        binding_proof: Any,
        project_id: Any,
        candidate_number: Any,
        candidate: Any,
    ) -> dict[str, Any]:
        self.store.assert_binding(task_id=task_id, channel_profile_id=channel_profile_id, binding_proof=binding_proof)
        project_id = _safe_identifier(project_id, "projectId")
        state = self._load_state(channel_profile_id, project_id)
        checkpoint = state["topicCheckpoint"]
        expected = checkpoint["completedUnits"] + 1
        if candidate_number != expected:
            raise ToolError("TOPIC_CHECKPOINT_SEQUENCE", "每次只能追加下一个缺失候选，completedUnits 只能增加 1。", details={"expected": expected})
        single_candidate_modes = {"provided-outline", "imitation", "direct-rewrite", "synthesis-rewrite"}
        maximum = 10 if state["sourceMode"] == "channel-library" else 1 if state["sourceMode"] in single_candidate_modes else 6
        if candidate_number > maximum:
            raise ToolError("TOPIC_CANDIDATE_LIMIT", "候选数量超过当前路线允许上限。")
        candidate = self._validate_candidate(candidate, state)
        if candidate["candidateId"] in checkpoint["candidateIds"]:
            raise ToolError("TOPIC_CANDIDATE_DUPLICATE", "候选 ID 已存在。")
        topic_root = self._project_root(channel_profile_id, project_id) / "topic"
        candidate_path = topic_root / "candidates" / f"{candidate_number:02d}-{candidate['candidateId']}.json"
        _atomic_json(candidate_path, candidate)
        checkpoint["completedUnits"] = candidate_number
        checkpoint["candidateIds"].append(candidate["candidateId"])
        checkpoint["lastCandidateHash"] = _json_hash(candidate)
        checkpoint["updatedAt"] = utc_now()
        checkpoint["items"].append(
            {
                "unitNumber": candidate_number,
                "candidateId": candidate["candidateId"],
                "status": "COMPLETED",
                "contentHash": checkpoint["lastCandidateHash"],
                "completedAt": checkpoint["updatedAt"],
            }
        )
        state["state"] = "GENERATING_CANDIDATES"
        partial = {
            "schemaVersion": CONTENT_LOOP_VERSION,
            "projectId": project_id,
            "sourceMode": state["sourceMode"],
            "checkpoint": checkpoint,
            "candidateFiles": [
                path.relative_to(topic_root).as_posix()
                for path in sorted((topic_root / "candidates").glob("*.json"))
            ],
            "synthetic": False,
        }
        _atomic_json(topic_root / "topic-candidates-v001.partial.json", partial)
        self._save_state(state)
        required_total = 10 if state["sourceMode"] == "channel-library" else 1 if state["sourceMode"] in single_candidate_modes else None
        return {
            "checkpoint": checkpoint,
            "progress": f"topic {candidate_number}/{required_total or '3-6'}",
            "isComplete": candidate_number == required_total if required_total else candidate_number >= 3,
            "note": "检查点只代表已实际落盘的完整候选；不会把测试小样本宣称为频道 10 候选。",
        }

    def _load_candidates(self, state: dict[str, Any]) -> list[dict[str, Any]]:
        root = self._project_root(state["channelProfileId"], state["projectId"]) / "topic" / "candidates"
        candidates = [json.loads(path.read_text(encoding="utf-8")) for path in sorted(root.glob("*.json"))]
        if len(candidates) != state["topicCheckpoint"]["completedUnits"]:
            raise ToolError("TOPIC_CHECKPOINT_MISMATCH", "候选文件数与检查点不一致。")
        return candidates

    def finalize_topic(
        self,
        *,
        task_id: Any,
        channel_profile_id: Any,
        binding_proof: Any,
        project_id: Any,
        ranking: Any,
        selected_candidate_id: Any,
        selection_reasons: Any,
        confirmation: Any,
    ) -> dict[str, Any]:
        self.store.assert_binding(task_id=task_id, channel_profile_id=channel_profile_id, binding_proof=binding_proof)
        project_id = _safe_identifier(project_id, "projectId")
        state = self._load_state(channel_profile_id, project_id)
        candidates = self._load_candidates(state)
        single_candidate_modes = {"provided-outline", "imitation", "direct-rewrite", "synthesis-rewrite"}
        required = 10 if state["sourceMode"] == "channel-library" else 1 if state["sourceMode"] in single_candidate_modes else None
        if required is not None and len(candidates) != required:
            raise ToolError("TOPIC_CANDIDATES_INCOMPLETE", "当前路线的完整候选尚未全部落盘。", details={"required": required, "actual": len(candidates)})
        if required is None and not 3 <= len(candidates) <= 6:
            raise ToolError("TOPIC_CANDIDATES_INCOMPLETE", "普通原创路线需要 3–6 个完整且不同的候选。")
        ids = [item["candidateId"] for item in candidates]
        if not isinstance(ranking, list) or len(ranking) != len(ids) or set(ranking) != set(ids) or len(set(ranking)) != len(ranking):
            raise ToolError("TOPIC_RANKING_INVALID", "连续排名必须完整且只包含全部真实候选。")
        if selected_candidate_id not in ids or ranking[0] != selected_candidate_id:
            raise ToolError("TOPIC_SELECTION_INVALID", "唯一入选方案必须存在且与排名第一一致。")
        if not isinstance(selection_reasons, dict) or set(selection_reasons) != set(ids):
            raise ToolError("TOPIC_SELECTION_REASONS_INVALID", "必须保留每个候选的入选或未入选理由。")
        if not isinstance(confirmation, dict) or confirmation.get("confirmed") is not True:
            state["state"] = "AWAITING_SELECTION"
            self._save_state(state)
            raise ToolError("TOPIC_CONFIRMATION_REQUIRED", "G3 未确认，不能冻结 Topic Package v1。")
        selected = next(item for item in candidates if item["candidateId"] == selected_candidate_id)
        channel_summary = self.store.get_channel(channel_profile_id)
        channel = channel_summary["channelProfile"]
        production = channel_summary["productionProfile"]
        version = _next_version((state["activePackages"]["topic"] or {}).get("version"))
        topic_id = f"topic_{project_id}_v{version.replace('.', '_')}"
        evidence_by_id: dict[str, dict[str, Any]] = {}
        for candidate in candidates:
            for claim in candidate["evidenceClaims"]:
                existing_claim = evidence_by_id.get(claim["claimId"])
                if existing_claim is not None and existing_claim != claim:
                    raise ToolError("EVIDENCE_CLAIM_CONFLICT", "不同候选使用了同一 claimId 表达不同证据。")
                evidence_by_id[claim["claimId"]] = claim
        evidence = list(evidence_by_id.values())
        upstream = [_contract_ref(channel), _contract_ref(production)]
        upstream.extend(
            {
                "targetContractType": "source-package",
                "targetId": item["sourcePackageId"],
                "targetVersion": item["version"],
                "targetSchemaVersion": PACKAGE_SCHEMA_VERSION,
                "targetHash": item["contentHash"],
            }
            for item in state["sourceLocks"]
        )
        upstream.extend(item["writingStyleContract"] for item in state.get("styleLocks", []))
        created = utc_now()
        contract_candidates = [
            {
                "candidateId": item["candidateId"],
                "storyDriver": item["storyDriver"],
                "coreSellingPoints": item["coreSellingPoints"],
                "worldRules": item["worldRules"],
                "characters": item["characters"],
                "completeOutline": item["completeOutline"],
                "episodePlots": item["episodePlots"],
                "productionRecommendation": item["productionRecommendation"],
                "scores": item["scores"],
                "strengths": item["strengths"],
                "risks": item["risks"],
                "evidenceClaimIds": [claim["claimId"] for claim in item["evidenceClaims"]],
                **(
                    {"sourceTransformationMap": item["sourceTransformationMap"]}
                    if "sourceTransformationMap" in item
                    else {}
                ),
            }
            for item in candidates
        ]
        source_inputs = []
        for item in state["sourceLocks"]:
            source_input = {
                "sourcePackage": {
                    "targetContractType": "source-package",
                    "targetId": item["sourcePackageId"],
                    "targetVersion": item["version"],
                    "targetSchemaVersion": PACKAGE_SCHEMA_VERSION,
                    "targetHash": item["contentHash"],
                },
                "acceptedStatus": item["status"],
            }
            if item["status"] == "PARTIAL":
                source_input["partialAcceptance"] = {
                    "accepted": True,
                    "acceptedBy": "user",
                    "acceptedAt": item["acceptedPartialAt"],
                    "knownLimitations": item["knownLimitations"],
                }
            source_inputs.append(source_input)
        snapshot = None
        brief = json.loads((self._project_root(channel_profile_id, project_id) / state["briefPath"]).read_text(encoding="utf-8"))
        raw_snapshot = brief.get("learningSnapshot")
        if raw_snapshot and all(raw_snapshot.get(key) for key in ("profileId", "version", "contentHash")):
            snapshot = {key: raw_snapshot[key] for key in ("profileId", "version", "contentHash")}
        learning_context = {
            "accessMode": "read-only-snapshot",
            "snapshot": snapshot,
            "currentProjectChanges": [
                {"changeId": f"change-{index:03d}", "scope": "current_only", "summary": summary}
                for index, summary in enumerate(state["oneTimeModifications"], 1)
            ],
            "longTermWriteAllowed": False,
        }
        route = {
            "channel-library": "channel-profile-anchored",
            "provided-outline": "provided-outline",
            "market-original": "original",
            "single-reference": "extension",
            "multi-reference": "extension",
            "imitation": "extension",
            "direct-rewrite": "extension",
            "synthesis-rewrite": "extension",
        }[state["sourceMode"]]
        approval = _approval("G3_TOPIC", confirmation, created)
        backup_ids = ranking[1:3] if len(ranking) > 1 else []
        contract = with_hash(
            {
                "schemaVersion": PACKAGE_SCHEMA_VERSION,
                "contractType": "topic-package",
                "id": topic_id,
                "version": version,
                "createdAt": created,
                "hashAlgorithm": "SHA-256",
                "hashRule": "canonical-json-v1",
                "upstream": upstream,
                "topicPackageId": topic_id,
                "projectId": project_id,
                "channelProfileId": channel_profile_id,
                "status": "TOPIC_SELECTED",
                "route": route,
                "sourceMode": state["sourceMode"],
                "audience": selected["audience"],
                "sourceInputs": source_inputs,
                "evidence": evidence,
                "extensionCapabilities": _extension_capabilities(),
                "learningContext": learning_context,
                "candidates": contract_candidates,
                "ranking": [
                    {
                        "rank": index,
                        "candidateId": candidate_id,
                        "overallScore": next(item for item in candidates if item["candidateId"] == candidate_id)["scores"]["overall"],
                        "decision": "selected" if index == 1 else "backup" if index <= 3 else "not-selected",
                        "reason": selection_reasons[candidate_id],
                    }
                    for index, candidate_id in enumerate(ranking, 1)
                ],
                "selection": {
                    "primaryCandidateId": selected_candidate_id,
                    "backupCandidateIds": backup_ids,
                    "policy": (
                        "provided-outline-only" if state["sourceMode"] == "provided-outline"
                        else "confirmed-imitation-direction" if state["sourceMode"] == "imitation"
                        else "direct-rewrite-request" if state["sourceMode"] == "direct-rewrite"
                        else "synthesis-rewrite-request" if state["sourceMode"] == "synthesis-rewrite"
                        else "auto-best" if confirmation.get("mode") == "auto"
                        else "user-choice"
                    ),
                },
                "selectedCandidateId": selected_candidate_id,
                "selectionConfirmation": approval,
                "checkpoints": {
                    "applicable": state["sourceMode"] == "channel-library",
                    "totalUnits": required or len(candidates),
                    "completedUnits": len(candidates),
                    "items": state["topicCheckpoint"]["items"],
                },
                "storyFacts": selected["storyFacts"],
                "storyFactsHash": _json_hash(selected["storyFacts"]),
                "productionRecommendation": selected["productionRecommendation"],
                "packagingBrief": selected["packagingBrief"],
            }
        )
        self._validate_contract_schema(contract, "topic-package.schema.json")
        root = self._project_root(channel_profile_id, project_id) / "topic-package" / f"v{version}"
        _atomic_json(root / "manifest.json", contract)
        _atomic_json(
            root / "source-lock.json",
            {
                "sources": state["sourceLocks"],
                "analysisLocks": state.get("analysisLocks", []),
                "styleLocks": state.get("styleLocks", []),
                "evidenceClaims": evidence,
            },
        )
        _atomic_json(root / "topic-selection-card.json", {"ranking": contract["ranking"], "selectedCandidateId": selected_candidate_id})
        previous = state["activePackages"]["topic"]
        if previous:
            state["invalidations"].append({"at": created, "reason": "new-topic-version", "invalidated": ["manuscript", "publishing"]})
            state["activePackages"]["manuscript"] = None
            state["activePackages"]["publishing"] = None
        state["activePackages"]["topic"] = {"id": topic_id, "version": version, "hash": contract["contentHash"], "path": str(root / "manifest.json")}
        state["state"] = "TOPIC_SELECTED"
        self._save_state(state)
        return {"package": contract, "packagePath": str(root), "confirmationCard": {"gate": "G3", "confirmed": True}}

    def _validate_lines(self, lines: Any, episode_count: int, *, field: str) -> list[dict[str, Any]]:
        if not isinstance(lines, list) or not lines:
            raise ToolError("SCRIPT_LINES_INVALID", f"{field} 必须是非空行数组。")
        seen: set[str] = set()
        expected_global = 1
        per_episode: dict[int, int] = {index: 1 for index in range(1, episode_count + 1)}
        normalized: list[dict[str, Any]] = []
        for line in lines:
            if not isinstance(line, dict) or "lineId" not in line or "emotion" not in line or "text" not in line:
                raise ToolError("SCRIPT_LINES_INVALID", f"{field} 行字段不完整。")
            line_id = _safe_identifier(line["lineId"], "lineId")
            episode = line.get("episodeNumber", line.get("episode"))
            sequence = line.get("sequence", line.get("order"))
            speaker_id = line.get("speakerId", line.get("speaker"))
            line_type = line.get("lineType", line.get("type"))
            if line_id in seen or not isinstance(episode, int) or not 1 <= episode <= episode_count:
                raise ToolError("SCRIPT_LINES_INVALID", f"{field} 行 ID 重复或集号无效。")
            if sequence != per_episode[episode] or line.get("globalOrder", expected_global) != expected_global:
                raise ToolError("SCRIPT_ORDER_INVALID", f"{field} 的集内或全局顺序不连续。")
            if line_type not in {"narration", "dialogue"} or not isinstance(speaker_id, str) or not speaker_id or not all(
                isinstance(line[key], str) and line[key].strip() for key in ("emotion", "text")
            ):
                raise ToolError("SCRIPT_LINES_INVALID", f"{field} 的说话人、类型、情绪或文本无效。")
            seen.add(line_id)
            per_episode[episode] += 1
            expected_global += 1
            normalized.append(
                {
                    "lineId": line_id,
                    "episodeNumber": episode,
                    "sequence": sequence,
                    "speakerId": speaker_id,
                    "lineType": line_type,
                    "emotion": line["emotion"],
                    "text": line["text"],
                }
            )
        if set(line["episodeNumber"] for line in normalized) != set(range(1, episode_count + 1)):
            raise ToolError("SCRIPT_EPISODE_MISSING", f"{field} 没有覆盖全部分集。")
        return normalized

    def save_review_document(
        self,
        *,
        task_id: Any,
        channel_profile_id: Any,
        binding_proof: Any,
        project_id: Any,
        document_type: Any,
        content: Any,
    ) -> dict[str, Any]:
        self.store.assert_binding(task_id=task_id, channel_profile_id=channel_profile_id, binding_proof=binding_proof)
        project_id = _safe_identifier(project_id, "projectId")
        state = self._load_state(channel_profile_id, project_id)
        allowed = {
            "rewrite-draft-target": ("target", 40),
            "editorial-review": ("zh-CN", 80),
            "revision-log": ("zh-CN", 80),
        }
        if document_type not in allowed:
            raise ToolError("CONTENT_REVIEW_DOCUMENT_TYPE_INVALID", "该文档类型不允许由创作阶段直接写入。")
        if not state["activePackages"].get("topic"):
            raise ToolError("TOPIC_PACKAGE_REQUIRED", "必须先冻结 Topic Package 才能保存仿写或审核文档。")
        if state["activePackages"].get("manuscript"):
            raise ToolError("CONTENT_REVIEW_DOCUMENTS_FROZEN", "正式稿已冻结；不能回写早期初稿或审核文档。")
        existing_document_ids = {
            item["documentId"]
            for item in review_documents_view(self._project_root(channel_profile_id, project_id))["documents"]
        }
        if document_type == "rewrite-draft-target" and existing_document_ids.intersection(
            {"editorial-review", "revision-log"}
        ):
            raise ToolError("REWRITE_DRAFT_REVIEW_ALREADY_STARTED", "审核已经开始；不能再替换其来源初稿。")
        if document_type == "editorial-review" and "revision-log" in existing_document_ids:
            raise ToolError("EDITORIAL_REVIEW_REVISION_ALREADY_RECORDED", "修改对照已经生成；不能再替换其审核来源。")
        if document_type in {"editorial-review", "revision-log"}:
            draft_check = validate_review_documents(
                self._project_root(channel_profile_id, project_id),
                ("rewrite-draft-target",),
            )
            if draft_check["status"] != "PASS":
                raise ToolError("REWRITE_DRAFT_DOCUMENT_REQUIRED", "必须先保存完整仿写初稿，再记录审核或修改对照。")
        if document_type == "revision-log":
            editorial_check = validate_review_documents(
                self._project_root(channel_profile_id, project_id),
                ("editorial-review",),
            )
            if editorial_check["status"] != "PASS":
                raise ToolError("EDITORIAL_REVIEW_DOCUMENT_REQUIRED", "必须先保存完整编辑审核报告，再记录修改前后对照。")
        language_marker, minimum = allowed[document_type]
        language = state["targetLanguage"] if language_marker == "target" else language_marker
        try:
            document = save_review_document(
                self._project_root(channel_profile_id, project_id),
                document_id=document_type,
                content=content,
                language=language,
                updated_at=utc_now(),
                minimum_characters=minimum,
            )
        except ValueError as exc:
            raise ToolError("CONTENT_REVIEW_DOCUMENT_INVALID", str(exc)) from exc
        state["userReviewDocuments"] = review_documents_view(self._project_root(channel_profile_id, project_id))
        if document_type == "rewrite-draft-target":
            state["state"] = "REWRITE_DRAFT_READY"
        elif {item["documentId"] for item in state["userReviewDocuments"]["documents"]}.issuperset(
            {"editorial-review", "revision-log"}
        ):
            state["state"] = "EDIT_REVIEW_READY"
        self._save_state(state)
        return {
            "document": document,
            "userReviewDocuments": state["userReviewDocuments"],
            "next": "content-review-edit" if document_type == "rewrite-draft-target" else "content_manuscript_finalize",
        }

    def get_review_documents(self, *, channel_profile_id: Any, project_id: Any) -> dict[str, Any]:
        project_id = _safe_identifier(project_id, "projectId")
        self._load_state(channel_profile_id, project_id)
        return {
            **review_documents_view(self._project_root(channel_profile_id, project_id)),
            "progressReadOnly": True,
        }

    def finalize_manuscript(
        self,
        *,
        task_id: Any,
        channel_profile_id: Any,
        binding_proof: Any,
        project_id: Any,
        story_bible: Any,
        characters: Any,
        target_script: Any,
        chinese_audit_script: Any,
        quality_gate: Any,
        foreign_language_quality_gate: Any,
        confirmation: Any,
        authoring_mode: Any = "target-language-native",
    ) -> dict[str, Any]:
        self.store.assert_binding(task_id=task_id, channel_profile_id=channel_profile_id, binding_proof=binding_proof)
        project_id = _safe_identifier(project_id, "projectId")
        state = self._load_state(channel_profile_id, project_id)
        topic_ref = state["activePackages"]["topic"]
        if not topic_ref:
            raise ToolError("TOPIC_PACKAGE_REQUIRED", "必须先确认并冻结 Topic Package v1。")
        topic = _read_contract(Path(topic_ref["path"]), "topic-package")
        project_root = self._project_root(channel_profile_id, project_id)
        required_pre_manuscript_documents = ["rewrite-draft-target", "editorial-review", "revision-log"]
        if state["sourceMode"] in {"direct-rewrite", "synthesis-rewrite"}:
            required_pre_manuscript_documents = [
                "source-summary", "deconstruction-report", "transfer-directions", *required_pre_manuscript_documents
            ]
        pre_manuscript_documents = validate_review_documents(project_root, required_pre_manuscript_documents)
        if pre_manuscript_documents["status"] != "PASS":
            raise ToolError(
                "CONTENT_REVIEW_DOCUMENTS_REQUIRED",
                "拆解、仿写、审核或修改对照文档缺失、损坏，不能冻结正式稿。",
                details={"errors": pre_manuscript_documents["errors"]},
            )
        if authoring_mode != "target-language-native":
            raise ToolError("MANUSCRIPT_AUTHORING_MODE_INVALID", "目标语言原生稿必须是唯一生产母稿。")
        if not isinstance(story_bible, dict) or story_bible.get("sourceStoryFactsHash", story_bible.get("lockedStoryFactsHash")) != topic["storyFactsHash"]:
            raise ToolError("STORY_BIBLE_MISMATCH", "Story Bible 必须绑定已确认选题的故事事实哈希。")
        story_fields = ("lockedFacts", "worldRules", "relationships", "timeline", "foreshadowing", "climax", "ending")
        if any(key not in story_bible for key in story_fields):
            raise ToolError("STORY_BIBLE_INVALID", "Story Bible 缺少事实、时间线、伏笔、高潮或结局。")
        if not isinstance(characters, list) or not characters:
            raise ToolError("CHARACTER_PACK_INVALID", "角色包至少包含一名持续出场的主要角色。")
        contract_characters: list[dict[str, Any]] = []
        voices: list[dict[str, Any]] = []
        for character in characters:
            voice = character.get("voice") if isinstance(character, dict) else None
            if not isinstance(voice, dict) or not all(isinstance(voice.get(key), str) and voice[key] for key in ("engineId", "voiceId", "voiceName", "catalogVersion", "catalogHash")):
                raise ToolError("VOICE_LOCK_INVALID", "每个实际配音角色必须冻结真实引擎、音色 ID 和名称。")
            if not re.fullmatch(r"[0-9a-f]{64}", voice["catalogHash"]):
                raise ToolError("VOICE_LOCK_INVALID", "音色目录哈希无效。")
            required_character = {
                "characterId", "targetLanguageName", "role", "goal", "relationship",
                "speakingStyle", "visualConsistencyRequired",
            }
            if not required_character.issubset(character):
                raise ToolError("CHARACTER_PACK_INVALID", "角色缺少目标语言姓名、目标、关系或说话特征。")
            clean_character = {key: character[key] for key in required_character}
            if "aliases" in character:
                clean_character["aliases"] = character["aliases"]
            if character["visualConsistencyRequired"]:
                if not isinstance(character.get("visualAnchorPromptZh"), str) or not character["visualAnchorPromptZh"]:
                    raise ToolError("CHARACTER_VISUAL_ANCHOR_REQUIRED", "持续视觉角色必须提供中文单人锚点提示词。")
                clean_character["visualAnchorPromptZh"] = character["visualAnchorPromptZh"]
            contract_characters.append(clean_character)
            voices.append(
                {
                    "speakerId": character["characterId"],
                    "engine": voice["engineId"],
                    "voiceId": voice["voiceId"],
                    "voiceName": voice["voiceName"],
                    "bindingStatus": "BOUND",
                    "catalogVersion": voice["catalogVersion"],
                    "catalogHash": voice["catalogHash"],
                }
            )
        episode_count = topic["productionRecommendation"]["episodeCount"]
        target_lines = self._validate_lines(target_script, episode_count, field="targetScript")
        target_language = topic["audience"]["targetLanguage"]
        if target_language.startswith("zh"):
            if chinese_audit_script not in (None, target_script) and chinese_audit_script != target_script:
                raise ToolError("CHINESE_AUDIT_DUPLICATED", "中文目标稿不生成第二份回译；审核稿必须直接复用母稿。")
            audit_lines = target_lines
            audit_mode = "TARGET_IS_CHINESE"
        else:
            audit_lines = self._validate_lines(chinese_audit_script, episode_count, field="chineseAuditScript")
            if len(audit_lines) != len(target_lines):
                raise ToolError("SCRIPT_MAPPING_MISMATCH", "中文回译与目标语言母稿行数不一致。")
            mapping_keys = ("lineId", "episodeNumber", "sequence", "speakerId", "lineType", "emotion")
            for target, audit in zip(target_lines, audit_lines, strict=True):
                if any(target[key] != audit[key] for key in mapping_keys):
                    raise ToolError("SCRIPT_MAPPING_MISMATCH", "行 ID、集、顺序、说话人、类型或情绪映射错误。", details={"lineId": target["lineId"]})
            audit_mode = "LINE_BY_LINE_BACKTRANSLATION"
        target_script_hash = _json_hash(target_lines)
        foreign_quality_contract = _foreign_language_quality_contract(
            foreign_language_quality_gate,
            target_language=target_language,
            episode_count=episode_count,
            target_script_hash=target_script_hash,
        )
        if not isinstance(quality_gate, dict) or quality_gate.get("passed") is not True:
            raise ToolError("MANUSCRIPT_QUALITY_GATE_FAILED", "合并质量门未通过，不能冻结正式文稿。")
        episodes = quality_gate.get("episodes")
        if not isinstance(episodes, list) or len(episodes) != episode_count:
            raise ToolError("MANUSCRIPT_QUALITY_GATE_INVALID", "每集必须且只能有一次合并质量门记录。")
        for number, gate in enumerate(episodes, 1):
            checks = gate.get("checks") if isinstance(gate, dict) else None
            if gate.get("episode") != number or gate.get("passed") is not True or not isinstance(checks, dict):
                raise ToolError("MANUSCRIPT_QUALITY_GATE_INVALID", "分集质量门顺序或状态无效。")
            if set(checks) != QUALITY_CHECKS or not all(checks.values()) or not 0 <= gate.get("revisionCount", 0) <= 3:
                raise ToolError("MANUSCRIPT_QUALITY_GATE_INVALID", "质量门硬项不完整、未通过或定向优化超过三轮。")
        actual_characters = sum(len(line["text"]) for line in target_lines)
        target_characters = topic["productionRecommendation"]["targetCharacters"]
        tolerance = max(1, round(target_characters * 0.05))
        if abs(actual_characters - target_characters) > tolerance:
            raise ToolError(
                "MANUSCRIPT_LENGTH_OUT_OF_RANGE",
                "正式母稿篇幅不在选题锁定目标的 ±5% 容差内。",
                details={"target": target_characters, "actual": actual_characters, "tolerance": tolerance},
            )
        if not isinstance(confirmation, dict) or confirmation.get("confirmed") is not True:
            state["state"] = "AWAITING_JOINT_REVIEW"
            self._save_state(state)
            raise ToolError("MANUSCRIPT_CONFIRMATION_REQUIRED", "G4 未联合确认，不能冻结 Manuscript Package v1。")

        version = _next_version((state["activePackages"]["manuscript"] or {}).get("version"))
        manuscript_id = f"manuscript_{project_id}_v{version.replace('.', '_')}"
        root = self._project_root(channel_profile_id, project_id) / "manuscript-package" / f"v{version}"
        story_core = {key: story_bible[key] for key in story_fields}
        story_contract = {
            "version": "1.0.0",
            "contentHash": _json_hash(story_core),
            "sourceStoryFactsHash": topic["storyFactsHash"],
            **story_core,
        }
        _atomic_json(root / "story-bible.json", story_contract)
        _atomic_json(root / "narrative-character-pack.json", {"characters": contract_characters, "voices": voices})
        _atomic_json(root / "target-script.json", {"language": target_language, "lines": target_lines})
        target_txt = "\n".join(f"[{line['lineId']}] {line['speakerId']}: {line['text']}" for line in target_lines) + "\n"
        audit_txt = "\n".join(f"[{line['lineId']}] {line['speakerId']}: {line['text']}" for line in audit_lines) + "\n"
        _atomic_bytes(root / "target-script.txt", target_txt.encode("utf-8"))
        if not target_language.startswith("zh"):
            _atomic_json(root / "chinese-audit-script.json", {"language": "zh-CN", "lines": audit_lines})
            _atomic_bytes(root / "chinese-audit-script.txt", audit_txt.encode("utf-8"))
        mapping_mode = "same-as-target" if target_language.startswith("zh") else "backtranslation"
        mapping = {
            "status": "PASSED",
            "mappingMode": mapping_mode,
            "targetLineCount": len(target_lines),
            "auditLineCount": len(audit_lines),
            "checks": {
                "lineIdsMatch": True,
                "episodeNumbersMatch": True,
                "sequenceMatches": True,
                "speakersMatch": True,
                "lineTypesMatch": True,
                "emotionsMatch": True,
            },
            "items": [
                {
                    "targetLineId": target["lineId"],
                    "auditLineId": audit["lineId"],
                    "episodeNumber": target["episodeNumber"],
                    "sequence": target["sequence"],
                    "speakerId": target["speakerId"],
                    "lineType": target["lineType"],
                    "emotion": target["emotion"],
                }
                for target, audit in zip(target_lines, audit_lines, strict=True)
            ],
        }
        _atomic_json(root / "line-mapping-validation.json", mapping)
        created = utc_now()
        quality_episode_results = []
        quality_revision_rounds = 0
        quality_key_map = {
            "locked-facts": "storyFacts",
            "story-progress": "progressAndStateChange",
            "character-voice": "characterVoice",
            "target-language-naturalness": "targetLanguageNaturalness",
            "regional-expression": "regionalExpression",
            "terminology-consistency": "terminologyConsistency",
            "tts-semantic-lines": "ttsSemanticBoundaries",
            "audience-reward": "audienceRetelling",
        }
        for gate in episodes:
            quality_revision_rounds = max(quality_revision_rounds, gate.get("revisionCount", 0))
            quality_episode_results.append(
                {
                    "episodeNumber": gate["episode"],
                    "status": "PASSED",
                    "checks": {output: bool(gate["checks"][source]) for source, output in quality_key_map.items()},
                }
            )
        quality_core = {
            "version": "1.0.0",
            "targetScriptHash": target_script_hash,
            "status": "PASSED",
            "revisionRounds": quality_revision_rounds,
            "episodeResults": quality_episode_results,
        }
        quality_contract = {**quality_core, "contentHash": _json_hash(quality_core)}
        _atomic_json(root / "target-script-quality-gate.json", quality_contract)
        _atomic_json(root / "foreign-language-quality-gate.json", foreign_quality_contract)
        target_script_contract = {
            "version": "1.0.0",
            "contentHash": target_script_hash,
            "role": "target-language-production-master",
            "isSoleProductionSource": True,
            "asset": _asset(root / "target-script.json", root, "target-script", "application/json"),
            "textAsset": _asset(root / "target-script.txt", root, "target-script-text", "text/plain"),
            "lines": target_lines,
        }
        audit_script_core = {
            "version": "1.0.0",
            "language": "zh-CN",
            "mode": mapping_mode,
            "sourceTargetScriptHash": target_script_hash,
            "productionUseAllowed": False,
            "duplicateFileCreated": not target_language.startswith("zh"),
        }
        if target_language.startswith("zh"):
            audit_script_core["targetScriptReference"] = "targetScript"
            audit_content = {"mode": mapping_mode, "targetScriptHash": target_script_hash}
        else:
            audit_script_core["asset"] = _asset(root / "chinese-audit-script.json", root, "chinese-audit-script", "application/json")
            audit_script_core["textAsset"] = _asset(root / "chinese-audit-script.txt", root, "chinese-audit-script-text", "text/plain")
            audit_script_core["lines"] = audit_lines
            audit_content = audit_lines
        audit_script_contract = {**audit_script_core, "contentHash": _json_hash(audit_content)}
        contract = with_hash(
            {
                "schemaVersion": PACKAGE_SCHEMA_VERSION,
                "contractType": "manuscript-package",
                "id": manuscript_id,
                "version": version,
                "createdAt": created,
                "hashAlgorithm": "SHA-256",
                "hashRule": "canonical-json-v1",
                "upstream": [_contract_ref(topic)],
                "manuscriptPackageId": manuscript_id,
                "projectId": project_id,
                "channelProfileId": channel_profile_id,
                "status": "SCRIPT_READY",
                "targetLanguage": target_language,
                "episodeCount": episode_count,
                "lineCount": len(target_lines),
                "storyBible": story_contract,
                "characters": contract_characters,
                "voices": voices,
                "targetScript": target_script_contract,
                "auditScript": audit_script_contract,
                "lineMapping": mapping,
                "qualityGate": quality_contract,
                "qualityGateHash": quality_contract["contentHash"],
                "foreignLanguageQualityGate": foreign_quality_contract,
                "foreignLanguageQualityGateHash": foreign_quality_contract["contentHash"],
                "selectiveInvalidation": {
                    "policy": "affected-episodes-only",
                    "invalidatedEpisodeNumbers": [],
                    "upstreamStoryChangeRequiresNewTopicVersion": True,
                },
                "confirmation": _approval("G4_MANUSCRIPT", confirmation, created),
            }
        )
        self._validate_contract_schema(contract, "manuscript-package.schema.json")
        _atomic_json(root / "manifest.json", contract)
        _atomic_json(root / "source-lock.json", {"topicPackage": _contract_ref(topic), "storyFactsHash": topic["storyFactsHash"]})
        try:
            save_review_document(
                project_root,
                document_id="final-script-target",
                content=target_txt,
                language=target_language,
                updated_at=created,
            )
            save_review_document(
                project_root,
                document_id="final-script-zh",
                content=audit_txt,
                language="zh-CN",
                updated_at=created,
            )
        except ValueError as exc:
            raise ToolError("CONTENT_REVIEW_DOCUMENT_INVALID", str(exc)) from exc
        previous = state["activePackages"]["manuscript"]
        if previous:
            state["invalidations"].append({"at": created, "reason": "new-manuscript-version", "invalidated": ["publishing"]})
            state["activePackages"]["publishing"] = None
        state["activePackages"]["manuscript"] = {"id": manuscript_id, "version": version, "hash": contract["contentHash"], "path": str(root / "manifest.json")}
        state["userReviewDocuments"] = review_documents_view(project_root)
        state["state"] = "SCRIPT_READY"
        self._save_state(state)
        return {
            "package": contract,
            "packagePath": str(root),
            "userReviewDocuments": state["userReviewDocuments"],
            "confirmationCard": chinese_first_confirmation_card(
                gate="G4_MANUSCRIPT",
                target_language=target_language,
                chinese_primary={
                    "summaryZh": "正式稿、中文审核稿和外语质量保险门均已通过并冻结。",
                    "formalChineseDocument": next(
                        (
                            item["relativePath"]
                            for item in state["userReviewDocuments"]["documents"]
                            if item["documentId"] == "final-script-zh"
                        ),
                        None,
                    ),
                    "foreignLanguageQualityStatus": foreign_quality_contract["status"],
                    "foreignLanguageQualitySummaryZh": foreign_quality_contract["summaryZh"],
                    "decisionRequiredZh": "已确认，无需再次操作。",
                },
                target_language_comparison={
                    "formalTargetDocument": next(
                        (
                            item["relativePath"]
                            for item in state["userReviewDocuments"]["documents"]
                            if item["documentId"] == "final-script-target"
                        ),
                        None,
                    ),
                    "targetScriptHash": target_script_hash,
                },
                confirmed=True,
                technical={
                    "qualityGateHash": quality_contract["contentHash"],
                    "foreignLanguageQualityGateHash": foreign_quality_contract["contentHash"],
                },
            ),
        }

    def finalize_publishing(
        self,
        *,
        task_id: Any,
        channel_profile_id: Any,
        binding_proof: Any,
        project_id: Any,
        title: Any,
        title_chinese: Any,
        title_candidates: Any,
        description_body: Any,
        description_chinese: Any,
        story_summary_chinese: Any,
        hashtags: Any,
        hashtag_translations: Any,
        thumbnail_provider: Any,
        thumbnail_strategy: Any,
        thumbnail_candidates: Any,
        selected_thumbnail_id: Any,
        thumbnail: Any,
        thumbnail_text_chinese: Any,
        ctr_review: Any,
        confirmation: Any,
    ) -> dict[str, Any]:
        self.store.assert_binding(task_id=task_id, channel_profile_id=channel_profile_id, binding_proof=binding_proof)
        project_id = _safe_identifier(project_id, "projectId")
        state = self._load_state(channel_profile_id, project_id)
        manuscript_ref = state["activePackages"]["manuscript"]
        if not manuscript_ref:
            raise ToolError("MANUSCRIPT_PACKAGE_REQUIRED", "发布素材只能读取已确认 Manuscript Package v1。")
        manuscript = _read_contract(Path(manuscript_ref["path"]), "manuscript-package")
        if manuscript.get("status") != "SCRIPT_READY" or manuscript.get("confirmation", {}).get("status") != "APPROVED":
            raise ToolError("MANUSCRIPT_NOT_CONFIRMED", "正式母稿未联合确认。")
        foreign_quality = manuscript.get("foreignLanguageQualityGate")
        expected_foreign_status = "NOT_APPLICABLE" if manuscript["targetLanguage"].lower().startswith("zh") else "PASSED"
        if (
            not isinstance(foreign_quality, dict)
            or foreign_quality.get("status") != expected_foreign_status
            or foreign_quality.get("targetScriptHash") != manuscript.get("targetScript", {}).get("contentHash")
            or manuscript.get("foreignLanguageQualityGateHash") != foreign_quality.get("contentHash")
        ):
            raise ToolError("FOREIGN_LANGUAGE_QUALITY_GATE_REQUIRED", "正式稿缺少有效且绑定当前母稿的外语质量保险门。")
        for field, value, maximum in (("title", title, 100), ("descriptionBody", description_body, 5000)):
            if not isinstance(value, str) or not value.strip() or len(value) > maximum:
                raise ToolError("PUBLISHING_TEXT_INVALID", f"{field} 为空或超过长度限制。")
        if not isinstance(title_chinese, str) or not title_chinese.strip():
            raise ToolError("PUBLISHING_TEXT_INVALID", "标题必须附中文翻译供审核。")
        title_candidate_fields = {
            "titleId", "text", "zhTranslation", "audienceFit", "factBasis", "promiseFulfilled", "sampleWordingCopied"
        }
        if not isinstance(title_candidates, list) or len(title_candidates) != 6:
            raise ToolError("TITLE_CANDIDATES_REQUIRED", "必须保存六个目标语言标题候选及其中文翻译。")
        clean_title_candidates: list[dict[str, Any]] = []
        title_ids: set[str] = set()
        for item in title_candidates:
            if not isinstance(item, dict) or set(item) != title_candidate_fields:
                raise ToolError("TITLE_CANDIDATES_INVALID", "标题候选字段不完整或包含未知字段。")
            title_id = _safe_identifier(item["titleId"], "titleId")
            if title_id in title_ids:
                raise ToolError("TITLE_CANDIDATES_INVALID", "标题候选 ID 不能重复。")
            if (
                not isinstance(item["text"], str) or not item["text"].strip() or len(item["text"]) > 100
                or not isinstance(item["zhTranslation"], str) or not item["zhTranslation"].strip() or len(item["zhTranslation"]) > 200
                or not isinstance(item["audienceFit"], (int, float)) or isinstance(item["audienceFit"], bool) or not 0 <= item["audienceFit"] <= 10
                or not isinstance(item["factBasis"], str) or not item["factBasis"].strip()
                or item["promiseFulfilled"] is not True or item["sampleWordingCopied"] is not False
            ):
                raise ToolError("TITLE_CANDIDATES_INVALID", "标题候选未通过事实、翻译、评分或原创边界检查。")
            title_ids.add(title_id)
            clean_title_candidates.append(json.loads(json.dumps(item, ensure_ascii=False)))
        selected_title = next(
            (item for item in clean_title_candidates if item["text"] == title and item["zhTranslation"] == title_chinese),
            None,
        )
        if selected_title is None:
            raise ToolError("TITLE_SELECTION_INVALID", "唯一正式标题及中文翻译必须来自六个已审核候选。")
        selected_title_id = selected_title["titleId"]
        if not isinstance(description_chinese, str) or not description_chinese.strip() or len(description_chinese) > 5000:
            raise ToolError("PUBLISHING_TEXT_INVALID", "YouTube 简介必须附完整中文翻译供审核。")
        if not isinstance(story_summary_chinese, str) or len(story_summary_chinese.strip()) < 20 or len(story_summary_chinese) > 5000:
            raise ToolError("STORY_SUMMARY_CHINESE_REQUIRED", "上传前中文验收卡必须包含完整、可理解的中文故事摘要。")
        if not isinstance(hashtags, list) or not 8 <= len(hashtags) <= 12 or len(set(hashtags)) != len(hashtags):
            raise ToolError("HASHTAG_COUNT_INVALID", "Hashtags 必须是 8–12 个互不重复的目标语言标签。")
        if any(not isinstance(item, str) or not re.fullmatch(r"#[^#\s]{1,99}", item) for item in hashtags):
            raise ToolError("HASHTAG_FORMAT_INVALID", "Hashtag 必须以 # 开头且不包含空白。")
        if not isinstance(hashtag_translations, list) or len(hashtag_translations) != len(hashtags):
            raise ToolError("HASHTAG_TRANSLATIONS_REQUIRED", "每个正式 Hashtag 都必须有中文含义供审核。")
        clean_hashtag_translations: list[dict[str, str]] = []
        for expected_hashtag, item in zip(hashtags, hashtag_translations, strict=True):
            if (
                not isinstance(item, dict) or set(item) != {"hashtag", "chinese"}
                or item.get("hashtag") != expected_hashtag
                or not isinstance(item.get("chinese"), str) or not item["chinese"].strip()
            ):
                raise ToolError("HASHTAG_TRANSLATIONS_INVALID", "Hashtags 中文对照必须与正式标签逐项同序对应。")
            clean_hashtag_translations.append({"hashtag": expected_hashtag, "chinese": item["chinese"].strip()})
        if not isinstance(thumbnail_provider, dict) or not thumbnail_provider:
            raise ToolError("THUMBNAIL_PROVIDER_REQUIRED", "必须冻结图片供应商接口状态与版本。")
        if not isinstance(thumbnail_strategy, dict) or not thumbnail_strategy:
            raise ToolError("THUMBNAIL_STRATEGY_REQUIRED", "必须先冻结 16:9 封面策略。")
        if not isinstance(thumbnail_text_chinese, str) or not thumbnail_text_chinese.strip():
            raise ToolError("THUMBNAIL_TEXT_TRANSLATION_REQUIRED", "封面目标语言短文案必须附中文含义供审核。")
        if not isinstance(thumbnail_candidates, list) or len(thumbnail_candidates) != 5:
            raise ToolError("THUMBNAIL_CANDIDATES_REQUIRED", "必须保留恰好 5 个构图实质不同的封面候选与内部评分。")
        candidate_ids = [item.get("candidateId") for item in thumbnail_candidates if isinstance(item, dict)]
        if len(candidate_ids) != len(thumbnail_candidates) or len(set(candidate_ids)) != len(candidate_ids) or selected_thumbnail_id not in candidate_ids:
            raise ToolError("THUMBNAIL_SELECTION_INVALID", "封面候选 ID 或唯一正式选择无效。")
        if not isinstance(ctr_review, dict) or ctr_review.get("status") != "PASSED" or ctr_review.get("factsConsistent") is not True:
            raise ToolError("CTR_REVIEW_FAILED", "唯一标题与封面未通过事实一致性和 CTR 联评。")
        if not isinstance(confirmation, dict) or confirmation.get("confirmed") is not True:
            state["state"] = "AWAITING_PUBLISHING_CONFIRMATION"
            self._save_state(state)
            raise ToolError("PUBLISHING_CONFIRMATION_REQUIRED", "G5 未联合确认，不能冻结 Publishing Asset Package v1。")
        if not isinstance(thumbnail, dict) or thumbnail.get("mode") not in {"real", "prompt_only"}:
            raise ToolError("THUMBNAIL_INVALID", "封面必须明确标记 real 或 prompt_only。")

        project_root = self._project_root(channel_profile_id, project_id)
        required_review_documents = [
            "rewrite-draft-target", "editorial-review", "revision-log", "final-script-target", "final-script-zh"
        ]
        if state["sourceMode"] in {"direct-rewrite", "synthesis-rewrite"}:
            required_review_documents = ["source-summary", "deconstruction-report", "transfer-directions", *required_review_documents]
        review_check = validate_review_documents(project_root, required_review_documents)
        if review_check["status"] != "PASS":
            raise ToolError(
                "CONTENT_REVIEW_DOCUMENTS_REQUIRED",
                "正式稿审核文档缺失或损坏，不能生成发布素材。",
                details={"errors": review_check["errors"]},
            )

        version = _next_version((state["activePackages"]["publishing"] or {}).get("version"))
        publishing_id = f"publishing_{project_id}_v{version.replace('.', '_')}"
        root = self._project_root(channel_profile_id, project_id) / "publishing-asset-package" / f"v{version}"
        root.mkdir(parents=True, exist_ok=True)
        thumbnail_mode = thumbnail["mode"]
        thumbnail_asset = None
        thumbnail_prompt = None
        dimensions = None
        if thumbnail_mode == "real":
            source_path = thumbnail.get("sourcePath")
            if not isinstance(source_path, str) or not source_path:
                raise ToolError("THUMBNAIL_FILE_REQUIRED", "real 封面必须提供本地图片文件。")
            source = Path(source_path).resolve()
            if not source.is_file():
                raise ToolError("THUMBNAIL_FILE_MISSING", "真实封面文件不存在或不可读。")
            width, height = _png_dimensions(source)
            if width * 9 != height * 16:
                raise ToolError("THUMBNAIL_ASPECT_RATIO_INVALID", "正式封面必须是精确 16:9。", details={"width": width, "height": height})
            destination = root / "confirmed-thumbnail.png"
            shutil.copyfile(source, destination)
            dimensions = {"width": width, "height": height, "aspectRatio": "16:9"}
            thumbnail_asset = _asset(destination, root, "confirmed-thumbnail", "image/png")
        else:
            thumbnail_prompt = thumbnail.get("prompt")
            if not isinstance(thumbnail_prompt, str) or not thumbnail_prompt.strip():
                raise ToolError("THUMBNAIL_PROMPT_REQUIRED", "prompt_only 必须保存清楚的图片提示词。")
        channel = self.store.get_channel(channel_profile_id)["channelProfile"]
        production = self.store.get_channel(channel_profile_id)["productionProfile"]
        created = utc_now()
        status = "PUBLISHING_ASSETS_READY" if thumbnail_mode == "real" else "AWAITING_THUMBNAIL"
        if thumbnail_mode == "real":
            thumbnail_contract = {
                "mode": "real_file",
                "asset": thumbnail_asset,
                "widthPixels": dimensions["width"],
                "heightPixels": dimensions["height"],
                "aspectRatio": "16:9",
                "fileReadable": True,
                "hashVerified": True,
            }
        else:
            thumbnail_contract = {
                "mode": "prompt_only",
                "prompt": thumbnail_prompt,
                "providerStatus": thumbnail.get("providerStatus", "not_requested"),
            }
        contract_thumbnail_candidates = json.loads(json.dumps(thumbnail_candidates, ensure_ascii=False))
        if thumbnail_asset:
            for item in contract_thumbnail_candidates:
                if item["candidateId"] == selected_thumbnail_id:
                    item["asset"] = thumbnail_asset
                    item["renderStatus"] = "GENERATED"
        production_handoff = {
            "eligible": thumbnail_mode == "real",
            "assessedAt": created,
            "blockers": [] if thumbnail_mode == "real" else ["real-thumbnail-required"],
        }
        characters_by_id = {item["characterId"]: item for item in manuscript.get("characters", [])}
        voice_summary = [
            {
                "speakerId": item["speakerId"],
                "targetLanguageName": characters_by_id.get(item["speakerId"], {}).get("targetLanguageName", item["speakerId"]),
                "role": characters_by_id.get(item["speakerId"], {}).get("role", ""),
                "engine": item["engine"],
                "voiceId": item["voiceId"],
                "voiceName": item["voiceName"],
            }
            for item in manuscript.get("voices", [])
        ]
        chinese_review = {
            "schemaVersion": "1.0.0",
            "displayMode": "CHINESE_FIRST_WITH_TARGET_LANGUAGE",
            "uploadUseAllowed": False,
            "storySummaryZh": story_summary_chinese.strip(),
            "titleZh": title_chinese.strip(),
            "descriptionZh": description_chinese.strip(),
            "hashtagTranslations": clean_hashtag_translations,
            "thumbnailTextZh": thumbnail_text_chinese.strip(),
            "voiceSummary": voice_summary,
        }
        contract = with_hash(
            {
                "schemaVersion": PACKAGE_SCHEMA_VERSION,
                "contractType": "publishing-asset-package",
                "id": publishing_id,
                "version": version,
                "createdAt": created,
                "hashAlgorithm": "SHA-256",
                "hashRule": "canonical-json-v1",
                "upstream": [_contract_ref(manuscript)],
                "publishingAssetPackageId": publishing_id,
                "projectId": project_id,
                "channelProfileId": channel_profile_id,
                "status": status,
                "targetLanguage": manuscript["targetLanguage"],
                "manuscriptBinding": {
                    "manuscriptPackage": _contract_ref(manuscript),
                    "targetScriptHash": manuscript["targetScript"]["contentHash"],
                    "qualityGateHash": manuscript["qualityGateHash"],
                    "foreignLanguageQualityGateHash": manuscript["foreignLanguageQualityGateHash"],
                },
                "title": title,
                "titleZhTranslation": title_chinese,
                "titleSelection": {
                    "selectedTitleId": selected_title_id,
                    "factConsistencyPassed": True,
                    "similarityGatePassed": True,
                    "candidates": clean_title_candidates,
                },
                "descriptionBody": description_body,
                "hashtags": hashtags,
                "thumbnailProvider": thumbnail_provider,
                "thumbnailStrategy": thumbnail_strategy,
                "thumbnailCandidates": contract_thumbnail_candidates,
                "thumbnailSelection": {
                    "selectedCandidateId": selected_thumbnail_id,
                    "reason": ctr_review.get("conclusion", "综合评分最高且事实一致。"),
                },
                "thumbnail": thumbnail_contract,
                "ctrReview": ctr_review,
                "targetChannel": {
                    "publisherProfileId": channel["publisherBinding"]["publisherProfileId"],
                    "channelSerial": channel["publisherBinding"]["channelSerial"],
                    "youtubeChannelId": channel["publisherBinding"]["youtubeChannelId"],
                },
                "uploadPolicy": production["defaults"]["uploadPolicy"],
                "privacyStatus": "private",
                "chineseReview": chinese_review,
                "confirmation": _approval("G5_PUBLISHING_ASSETS", confirmation, created),
                "productionHandoff": production_handoff,
            }
        )
        self._validate_contract_schema(contract, "publishing-asset-package.schema.json")
        _atomic_json(root / "manifest.json", contract)
        _atomic_json(root / "publishing.json", {
            "title": title,
            "descriptionBody": description_body,
            "hashtags": hashtags,
            "thumbnail": thumbnail_asset["relativePath"] if thumbnail_asset else None,
            "thumbnailMode": thumbnail_mode,
            "targetChannel": contract["targetChannel"],
            "uploadPolicy": contract["uploadPolicy"],
            "privacyStatus": contract["privacyStatus"],
        })
        _atomic_json(root / "thumbnail-strategy.json", thumbnail_strategy)
        _atomic_json(root / "thumbnail-selection.json", {"candidates": contract_thumbnail_candidates, "selectedThumbnailId": selected_thumbnail_id})
        _atomic_json(root / "ctr-review.json", ctr_review)
        _atomic_bytes(root / "description-hashtags.txt", (description_body.rstrip() + "\n\n" + " ".join(hashtags) + "\n").encode("utf-8"))
        _atomic_json(root / "source-lock.json", {"manuscriptPackage": _contract_ref(manuscript)})
        try:
            save_review_document(
                project_root,
                document_id="packaging-bilingual",
                content=_packaging_review_markdown(
                    title_candidates=clean_title_candidates,
                    selected_title_id=selected_title_id,
                    description_body=description_body,
                    description_chinese=description_chinese,
                    hashtag_translations=clean_hashtag_translations,
                ),
                language="zh-CN",
                updated_at=created,
                minimum_characters=80,
            )
            save_review_document(
                project_root,
                document_id="thumbnail-review",
                content=_thumbnail_review_markdown(
                    strategy=thumbnail_strategy,
                    candidates=contract_thumbnail_candidates,
                    selected_thumbnail_id=selected_thumbnail_id,
                    thumbnail_text_chinese=thumbnail_text_chinese,
                    ctr_review=ctr_review,
                ),
                language="zh-CN",
                updated_at=created,
                minimum_characters=80,
            )
        except ValueError as exc:
            raise ToolError("CONTENT_REVIEW_DOCUMENT_INVALID", str(exc)) from exc
        state["activePackages"]["publishing"] = {"id": publishing_id, "version": version, "hash": contract["contentHash"], "path": str(root / "manifest.json")}
        state["userReviewDocuments"] = review_documents_view(project_root)
        state["state"] = status
        self._save_state(state)
        return {
            "package": contract,
            "packagePath": str(root),
            "confirmationCard": chinese_first_confirmation_card(
                gate="G5_PUBLISHING_ASSETS",
                target_language=manuscript["targetLanguage"],
                chinese_primary={
                    "storySummaryZh": chinese_review["storySummaryZh"],
                    "titleZh": chinese_review["titleZh"],
                    "descriptionZh": chinese_review["descriptionZh"],
                    "hashtagsZh": [item["chinese"] for item in clean_hashtag_translations],
                    "thumbnailTextZh": chinese_review["thumbnailTextZh"],
                    "decisionRequiredZh": "发布素材已确认；制作完成后仍须查看上传前最终中文验收卡。",
                },
                target_language_comparison={
                    "title": title,
                    "description": description_body,
                    "hashtags": hashtags,
                    "thumbnailText": thumbnail_strategy["targetLanguageText"],
                },
                confirmed=True,
                technical={"thumbnailMode": thumbnail_mode, "selectedThumbnailId": selected_thumbnail_id},
            ),
            "productionHandoffEligible": thumbnail_mode == "real",
            "userReviewDocuments": state["userReviewDocuments"],
        }

    def get_project(self, *, channel_profile_id: Any, project_id: Any) -> dict[str, Any]:
        project_id = _safe_identifier(project_id, "projectId")
        state = self._load_state(channel_profile_id, project_id)
        return {
            "state": state,
            "userReviewDocuments": review_documents_view(self._project_root(channel_profile_id, project_id)),
            "progressReadOnly": True,
            "boundaries": self.capabilities()["boundaries"],
        }

    def integrity_check(self, *, channel_profile_id: Any, project_id: Any) -> dict[str, Any]:
        project_id = _safe_identifier(project_id, "projectId")
        state = self._load_state(channel_profile_id, project_id)
        errors: list[dict[str, Any]] = []
        contracts: dict[str, dict[str, Any]] = {}
        for lock in state.get("styleLocks", []):
            try:
                if self.style_provider is None:
                    raise ToolError("WRITING_STYLE_PROVIDER_UNAVAILABLE", "原创仿写契约提供器尚未接入内容中心。")
                contract = self.style_provider.writing_contract(
                    channel_profile_id=channel_profile_id,
                    imitation_id=lock["imitationId"],
                )
                if (
                    contract.get("contentHash") != lock["writingStyleContract"]["targetHash"]
                    or contract.get("selectedDirection", {}).get("directionId") != lock["selectedDirectionId"]
                ):
                    errors.append({"package": "writing-style-contract", "issue": "style-upstream-hash"})
            except ToolError as exc:
                errors.append({"package": "writing-style-contract", "issue": exc.code})
        for package_name, expected_type in (("topic", "topic-package"), ("manuscript", "manuscript-package"), ("publishing", "publishing-asset-package")):
            reference = state["activePackages"].get(package_name)
            if not reference:
                continue
            try:
                contract = _read_contract(Path(reference["path"]), expected_type)
                contracts[package_name] = contract
                if contract["contentHash"] != reference["hash"]:
                    errors.append({"package": package_name, "issue": "active-reference-hash"})
                root = Path(reference["path"]).parent
                descriptors: list[tuple[str, dict[str, Any]]] = []
                if package_name == "manuscript":
                    for group in ("targetScript", "auditScript"):
                        for key in ("asset", "textAsset"):
                            descriptor = contract.get(group, {}).get(key)
                            if descriptor:
                                descriptors.append((f"{group}.{key}", descriptor))
                elif package_name == "publishing":
                    descriptor = contract.get("thumbnail", {}).get("asset")
                    if descriptor:
                        descriptors.append(("thumbnail.asset", descriptor))
                for key, descriptor in descriptors:
                    asset_path = root / descriptor["relativePath"]
                    if not asset_path.is_file() or asset_path.stat().st_size != descriptor["sizeBytes"] or _sha256_file(asset_path) != descriptor["sha256"]:
                        errors.append({"package": package_name, "issue": "asset-hash", "asset": key})
            except ToolError as exc:
                errors.append({"package": package_name, "issue": exc.code})
        if "topic" in contracts and "manuscript" in contracts:
            upstream = contracts["manuscript"]["upstream"][0]
            if upstream["targetHash"] != contracts["topic"]["contentHash"]:
                errors.append({"package": "manuscript", "issue": "topic-upstream-hash"})
        if "manuscript" in contracts and "publishing" in contracts:
            upstream = contracts["publishing"]["upstream"][0]
            if upstream["targetHash"] != contracts["manuscript"]["contentHash"]:
                errors.append({"package": "publishing", "issue": "manuscript-upstream-hash"})
            if contracts["publishing"].get("thumbnail", {}).get("mode") == "real_file":
                root = Path(state["activePackages"]["publishing"]["path"]).parent
                try:
                    width, height = _png_dimensions(root / contracts["publishing"]["thumbnail"]["asset"]["relativePath"])
                    if width * 9 != height * 16:
                        errors.append({"package": "publishing", "issue": "thumbnail-aspect-ratio"})
                except ToolError as exc:
                    errors.append({"package": "publishing", "issue": exc.code})
        required_review_documents: list[str] = []
        if state.get("sourceMode") in {"direct-rewrite", "synthesis-rewrite"} and state["activePackages"].get("topic"):
            required_review_documents.extend(("source-summary", "deconstruction-report", "transfer-directions"))
        if state["activePackages"].get("manuscript"):
            required_review_documents.extend(
                ("rewrite-draft-target", "editorial-review", "revision-log", "final-script-target", "final-script-zh")
            )
        if state["activePackages"].get("publishing"):
            required_review_documents.extend(("packaging-bilingual", "thumbnail-review"))
        review_check = None
        if required_review_documents:
            review_check = validate_review_documents(
                self._project_root(channel_profile_id, project_id),
                required_review_documents,
            )
            errors.extend(
                {"package": "user-review-documents", "issue": item.get("issue"), "documentId": item.get("documentId")}
                for item in review_check["errors"]
            )
        return {
            "status": "PASS" if not errors else "FAIL",
            "projectId": project_id,
            "checkedPackages": sorted(contracts),
            "userReviewDocuments": review_check,
            "errors": errors,
            "boundaries": self.capabilities()["boundaries"],
        }

    def handoff_check(self, *, channel_profile_id: Any, project_id: Any) -> dict[str, Any]:
        project_id = _safe_identifier(project_id, "projectId")
        state = self._load_state(channel_profile_id, project_id)
        integrity = self.integrity_check(channel_profile_id=channel_profile_id, project_id=project_id)
        missing = [name for name in ("topic", "manuscript", "publishing") if not state["activePackages"].get(name)]
        if missing:
            raise ToolError("CONTENT_CONFIRMATION_CHAIN_INCOMPLETE", "未确认的内容链不得移交制作。", details={"missing": missing})
        publishing = _read_contract(Path(state["activePackages"]["publishing"]["path"]), "publishing-asset-package")
        if integrity["status"] != "PASS" or publishing.get("status") != "PUBLISHING_ASSETS_READY" or publishing.get("thumbnail", {}).get("mode") != "real_file":
            raise ToolError(
                "CONTENT_HANDOFF_BLOCKED",
                "内容包完整性、联合确认或真实 16:9 封面未满足；不会进入制作中心。",
                details={"integrity": integrity["status"], "publishingStatus": publishing.get("status")},
            )
        return {
            "eligible": True,
            "projectId": project_id,
            "nextCenter": "production",
            "packageHashes": {name: value["hash"] for name, value in state["activePackages"].items()},
            "notExecuted": ["production-package", "workshop", "publisher-authorization", "upload", "analytics", "long-term-learning-write"],
        }
