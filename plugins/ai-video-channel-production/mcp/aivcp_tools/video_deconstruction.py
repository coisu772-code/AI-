from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry, Resource

from .content_analysis import (
    BUCKET_KEYS,
    CONTENT_ANALYSIS_VERSION,
    _atomic_json,
    _contract_ref,
    _derived_id,
    _json_hash,
    _safe_identifier,
    _source_ref,
    _validate_analysis_buckets,
    _validate_dimensions,
)
from .contracts import canonical_hash, resolve_contracts_root, utc_now, with_hash
from .errors import ToolError


VIDEO_DECONSTRUCTION_VERSION = "1.0.0"
VIDEO_DECONSTRUCTION_MODES = {"single", "parallel", "compare"}
VIDEO_DECONSTRUCTION_DIMENSIONS = {
    "positioning",
    "oneSentenceCore",
    "paragraphOverview",
    "functionalStructure",
    "emotionalCurve",
    "audienceRewards",
    "payoffAndReversals",
    "characterFunctionsAndRelations",
    "narrativeVoiceAndStyle",
    "paragraphBreath",
    "expressionTechniques",
    "youtubeTiming",
    "retentionMechanics",
    "titlePromiseFulfillment",
    "crossAssetAlignment",
    "credibilityAndConstraints",
    "originalityBoundaries",
}
CHECKPOINT_QUALITY_KEYS = {
    "fiveBucketsSeparated",
    "evidenceTraceable",
    "functionalSectionsMapped",
    "timingMappedOrUnknown",
    "accountRequirementsCovered",
    "copyBoundariesExplicit",
}
FINAL_QUALITY_KEYS = {
    "independentVideoAnalysis",
    "fiveBucketSeparation",
    "evidenceTraceability",
    "accountRequirementCoverage",
    "downstreamHandoff",
    "antiCopyBoundary",
    "timingIntegrity",
}
DOWNSTREAM_CONSUMERS = {"topic-center", "manuscript-center", "content-rewrite", "production-text"}


def _read_json(path: Path, code: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ToolError(code, "视频文案拆解状态或契约不可读。", details={"path": str(path)}) from exc
    if not isinstance(value, dict):
        raise ToolError(code, "视频文案拆解状态或契约结构无效。", details={"path": str(path)})
    return value


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _paragraph_number(value: Any, field: str) -> int:
    if not isinstance(value, str) or not re.fullmatch(r"p\d{4,}", value):
        raise ToolError("SECTION_PARAGRAPH_INVALID", f"{field} 必须使用 p0001 形式的段落 ID。")
    return int(value[1:])


class VideoCopyDeconstruction:
    """Freeze evidence-bound video-copy deconstructions for downstream content centers."""

    def __init__(
        self,
        store: Any,
        sources: Any,
        *,
        channel_distillations: Any = None,
        plugin_root: Path | None = None,
        analysis_kind: str = "video-copy-deconstruction",
        root_folder: str = "video-deconstructions",
        accepted_source_types: set[str] | None = None,
    ) -> None:
        self.store = store
        self.sources = sources
        self.channel_distillations = channel_distillations
        self.plugin_root = plugin_root
        self.analysis_kind = analysis_kind
        self.root_folder = root_folder
        self.accepted_source_types = accepted_source_types or {"youtube-video"}

    def _validate_contract_schema(self, contract: dict[str, Any], schema_name: str) -> None:
        if self.plugin_root is None:
            return
        schema_root = resolve_contracts_root(self.plugin_root) / "schemas"
        schema_path = schema_root / schema_name
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
        except (OSError, UnicodeError, json.JSONDecodeError, KeyError) as exc:
            raise ToolError("VIDEO_DECONSTRUCTION_SCHEMA_INVALID", "视频文案拆解契约 Schema 不可读。") from exc
        if errors:
            first = errors[0]
            location = "/".join(str(item) for item in first.absolute_path) or "<root>"
            raise ToolError(
                "VIDEO_DECONSTRUCTION_CONTRACT_SCHEMA_FAILED",
                "视频文案拆解契约未通过 Schema。",
                details={"schema": schema_name, "location": location, "message": first.message},
            )

    def capabilities(self) -> dict[str, Any]:
        generic = self.analysis_kind == "content-deconstruction"
        interfaces = (
            {
                "content-deconstruction": "available",
                "video-analysis": "available",
                "analysis-package-v1": "available",
                "direct-rewrite": "available-via-content-rewrite",
                "synthesis-rewrite": "available-via-content-rewrite",
            }
            if generic
            else {
                "content-deconstruction": "unavailable",
                "video-analysis": "available",
                "analysis-package-v1": "available",
                "style-imitation": "available-via-original-imitation-writing",
                "writing-style-contract-v1": "available-via-original-imitation-writing",
            }
        )
        return {
            "available": True,
            "version": VIDEO_DECONSTRUCTION_VERSION,
            "platforms": ["youtube", "local-file", "pasted-text", "novel-web"] if generic else ["youtube"],
            "modes": sorted(VIDEO_DECONSTRUCTION_MODES),
            "interfaces": interfaces,
            "dimensions": sorted(VIDEO_DECONSTRUCTION_DIMENSIONS),
            "outputs": [
                "content-deconstruction-analysis-v1" if generic else "video-deconstruction-analysis-v1",
                "analysis-package-v1",
            ],
            "consumers": ["content-rewrite", "production-text"] if generic else ["topic-center", "manuscript-center"],
            "boundaries": {
                "requiresCanonicalContentTxt": True,
                "readsRawSubtitleFiles": False,
                "storesRawSubtitleFiles": False,
                "eachVideoRemainsIndependent": True,
                "averagingUsed": False,
                "segmentSplicingUsed": False,
                "generatesOriginalDirections": False,
                "writesOutlineOrManuscript": False,
            },
        }

    def _root(self, channel_profile_id: str, deconstruction_id: str) -> Path:
        return (
            self.store.channel_path(channel_profile_id)
            / "content-analysis"
            / self.root_folder
            / _safe_identifier(deconstruction_id, "deconstructionId")
        )

    def _state_path(self, channel_profile_id: str, deconstruction_id: str) -> Path:
        return self._root(channel_profile_id, deconstruction_id) / "state.json"

    def _load_state(self, channel_profile_id: str, deconstruction_id: str) -> dict[str, Any]:
        state = _read_json(
            self._state_path(channel_profile_id, deconstruction_id),
            "VIDEO_DECONSTRUCTION_NOT_FOUND",
        )
        if (
            state.get("channelProfileId") != channel_profile_id
            or state.get("deconstructionId") != deconstruction_id
        ):
            raise ToolError("VIDEO_DECONSTRUCTION_IDENTITY_MISMATCH", "视频文案拆解状态身份不匹配。")
        return state

    def _save_state(self, state: dict[str, Any]) -> None:
        state["updatedAt"] = utc_now()
        _atomic_json(
            self._state_path(state["channelProfileId"], state["deconstructionId"]),
            state,
        )

    @staticmethod
    def _asset(manifest: dict[str, Any], filename: str) -> dict[str, Any] | None:
        return next(
            (
                item
                for item in manifest.get("assets", [])
                if isinstance(item, dict)
                and str(item.get("relativePath", "")).endswith(f"/{filename}")
                and "/normalized/" in f"/{str(item.get('relativePath', ''))}"
            ),
            None,
        )

    def _source_detail(self, channel_profile_id: str, source_package_id: Any) -> dict[str, Any]:
        source_package_id = _safe_identifier(source_package_id, "sourcePackageId")
        detail = self.sources.get_source(
            channel_profile_id=channel_profile_id,
            source_package_id=source_package_id,
        )
        manifest = detail["manifest"]
        if canonical_hash(manifest) != manifest.get("contentHash"):
            raise ToolError("SOURCE_HASH_MISMATCH", "Source Package 的 canonical-json-v1 哈希无效。")
        if manifest.get("sourceType") not in self.accepted_source_types:
            raise ToolError(
                "CONTENT_SOURCE_TYPE_UNSUPPORTED",
                "当前文案拆解不支持该 Source Package 类型。",
                details={"sourceType": manifest.get("sourceType"), "accepted": sorted(self.accepted_source_types)},
            )
        content_asset = self._asset(manifest, "content.txt")
        if manifest.get("status") != "CONTENT_READY" or content_asset is None:
            raise ToolError("CANONICAL_VIDEO_TEXT_REQUIRED", "视频必须先形成已验收的统一 content.txt。")
        return {
            "detail": detail,
            "manifest": manifest,
            "contentAsset": content_asset,
            "timingAsset": self._asset(manifest, "timing-map.json"),
        }

    def _asset_path(
        self,
        channel_profile_id: str,
        detail: dict[str, Any],
        asset: dict[str, Any],
    ) -> Path:
        manifest_relative = detail.get("source", {}).get("manifest_relative_path")
        if not isinstance(manifest_relative, str):
            raise ToolError("SOURCE_ASSET_PATH_INVALID", "Source Package 缺少正式 manifest 路径。")
        channel_root = self.store.channel_path(channel_profile_id).resolve()
        package_root = (channel_root / manifest_relative).resolve().parent
        target = (package_root / str(asset.get("relativePath", ""))).resolve()
        if target != package_root and package_root not in target.parents:
            raise ToolError("SOURCE_ASSET_PATH_INVALID", "资料资产路径越出 Source Package。")
        if not target.is_file() or _sha256_file(target) != asset.get("sha256"):
            raise ToolError("SOURCE_ASSET_HASH_MISMATCH", "统一正文或时间映射文件缺失或哈希无效。")
        return target

    def prepare(
        self,
        *,
        task_id: Any,
        channel_profile_id: Any,
        binding_proof: Any,
        deconstruction_id: Any,
        mode: Any,
        videos: Any,
        distillation_id: Any = None,
    ) -> dict[str, Any]:
        self.store.assert_binding(
            task_id=task_id,
            channel_profile_id=channel_profile_id,
            binding_proof=binding_proof,
        )
        channel_profile_id = _safe_identifier(channel_profile_id, "channelProfileId", maximum=160)
        deconstruction_id = _safe_identifier(deconstruction_id, "deconstructionId")
        if mode not in VIDEO_DECONSTRUCTION_MODES:
            raise ToolError("VIDEO_DECONSTRUCTION_MODE_INVALID", "视频文案拆解模式不受支持。")
        if not isinstance(videos, list) or not videos or len(videos) > 8:
            raise ToolError("VIDEO_DECONSTRUCTION_INPUT_INVALID", "videos 必须包含 1–8 个视频。")
        if mode == "single" and len(videos) != 1:
            raise ToolError("VIDEO_DECONSTRUCTION_COUNT_INVALID", "单视频模式必须且只能提供一个视频。")
        if mode != "single" and len(videos) < 2:
            raise ToolError("VIDEO_DECONSTRUCTION_COUNT_INVALID", "并行或对比模式至少需要两个视频。")

        planned_videos: list[dict[str, Any]] = []
        identifiers: set[str] = set()
        for item in videos:
            if not isinstance(item, dict):
                raise ToolError("VIDEO_DECONSTRUCTION_INPUT_INVALID", "每个视频输入必须是对象。")
            source = self._source_detail(channel_profile_id, item.get("sourcePackageId"))
            manifest = source["manifest"]
            source_package_id = manifest["sourcePackageId"]
            if source_package_id in identifiers:
                raise ToolError("VIDEO_DECONSTRUCTION_DUPLICATE", "同一视频不能在一次拆解中重复出现。")
            identifiers.add(source_package_id)
            role = item.get("role") or "reference"
            if not isinstance(role, str) or not role.strip():
                raise ToolError("VIDEO_DECONSTRUCTION_ROLE_INVALID", "每个视频必须有明确角色。")
            row = source["detail"].get("source", {})
            planned_videos.append(
                {
                    "sourcePackage": _source_ref(manifest),
                    "sourcePackageId": source_package_id,
                    "role": role.strip(),
                    "title": row.get("title"),
                    "platformId": row.get("platform_id"),
                    "canonicalUrl": row.get("canonical_url"),
                    "language": row.get("language"),
                    "canonicalTextAsset": source["contentAsset"],
                    "timingMapAsset": source["timingAsset"],
                }
            )

        requirement_ref = None
        required_sections: list[str] = []
        locked_distillation_id = None
        if distillation_id is not None:
            if self.channel_distillations is None:
                raise ToolError("CHANNEL_REQUIREMENT_PROVIDER_UNAVAILABLE", "频道蒸馏要求提供器尚未接入。")
            locked_distillation_id = _safe_identifier(distillation_id, "distillationId")
            requirement = self.channel_distillations.account_requirement(
                channel_profile_id=channel_profile_id,
                distillation_id=locked_distillation_id,
                kind="decomposition",
            )
            required_sections = requirement.get("requirements", {}).get("requiredSections")
            if not isinstance(required_sections, list) or not required_sections or any(
                not isinstance(item, str) or not item.strip() for item in required_sections
            ):
                raise ToolError("ACCOUNT_DECOMPOSITION_REQUIREMENTS_INVALID", "账号专属拆解要求缺少有效必拆区块。")
            required_sections = [item.strip() for item in required_sections]
            requirement_ref = _contract_ref(requirement)

        plan = {
            "schemaVersion": VIDEO_DECONSTRUCTION_VERSION,
            "deconstructionId": deconstruction_id,
            "analysisKind": self.analysis_kind,
            "channelProfileId": channel_profile_id,
            "targetChannel": _contract_ref(self.store.get_channel(channel_profile_id)["channelProfile"]),
            "mode": mode,
            "videos": planned_videos,
            "distillationId": locked_distillation_id,
            "accountRequirement": requirement_ref,
            "requiredSections": required_sections,
            "requiredDimensions": sorted(VIDEO_DECONSTRUCTION_DIMENSIONS),
            "boundaries": self.capabilities()["boundaries"],
        }
        request_hash = _json_hash(plan)
        root = self._root(channel_profile_id, deconstruction_id)
        if self._state_path(channel_profile_id, deconstruction_id).is_file():
            state = self._load_state(channel_profile_id, deconstruction_id)
            if state.get("requestHash") != request_hash:
                raise ToolError("VIDEO_DECONSTRUCTION_ID_CONFLICT", "同一 deconstructionId 已绑定不同请求。")
            return {"state": state, "plan": plan, "idempotent": True}
        root.mkdir(parents=True, exist_ok=False)
        _atomic_json(root / "plan.json", plan)
        created = utc_now()
        state = {
            "schemaVersion": VIDEO_DECONSTRUCTION_VERSION,
            "deconstructionId": deconstruction_id,
            "analysisKind": self.analysis_kind,
            "channelProfileId": channel_profile_id,
            "mode": mode,
            "state": "ANALYSIS_READY",
            "createdAt": created,
            "updatedAt": created,
            "requestHash": request_hash,
            "planPath": "plan.json",
            "videos": {},
            "progress": {"recorded": 0, "succeeded": 0, "total": len(planned_videos)},
            "outputs": {},
        }
        self._save_state(state)
        return {
            "state": state,
            "plan": plan,
            "idempotent": False,
            "confirmationCard": {
                "mode": mode,
                "videos": len(planned_videos),
                "accountSpecificRequirements": bool(requirement_ref),
                "requiredSections": required_sections,
                "canonicalInput": "content.txt",
                "rawSubtitleWillBeReadOrStored": False,
                "next": "read canonical paragraphs and checkpoint every video independently",
            },
        }

    def read_source(
        self,
        *,
        task_id: Any,
        channel_profile_id: Any,
        binding_proof: Any,
        deconstruction_id: Any,
        source_package_id: Any,
        start_paragraph: Any = 1,
        max_paragraphs: Any = 60,
    ) -> dict[str, Any]:
        self.store.assert_binding(
            task_id=task_id,
            channel_profile_id=channel_profile_id,
            binding_proof=binding_proof,
        )
        channel_profile_id = _safe_identifier(channel_profile_id, "channelProfileId", maximum=160)
        deconstruction_id = _safe_identifier(deconstruction_id, "deconstructionId")
        source_package_id = _safe_identifier(source_package_id, "sourcePackageId")
        self._load_state(channel_profile_id, deconstruction_id)
        plan = _read_json(self._root(channel_profile_id, deconstruction_id) / "plan.json", "VIDEO_DECONSTRUCTION_PLAN_INVALID")
        planned = next(
            (item for item in plan["videos"] if item["sourcePackageId"] == source_package_id),
            None,
        )
        if planned is None:
            raise ToolError("VIDEO_NOT_PLANNED", "该视频不属于本次拆解计划。")
        if not isinstance(start_paragraph, int) or isinstance(start_paragraph, bool) or start_paragraph < 1:
            raise ToolError("PARAGRAPH_RANGE_INVALID", "startParagraph 必须是从 1 开始的整数。")
        if not isinstance(max_paragraphs, int) or isinstance(max_paragraphs, bool) or not 1 <= max_paragraphs <= 100:
            raise ToolError("PARAGRAPH_RANGE_INVALID", "maxParagraphs 必须在 1–100 之间。")
        source = self._source_detail(channel_profile_id, source_package_id)
        if source["manifest"]["contentHash"] != planned["sourcePackage"]["targetHash"]:
            raise ToolError("VIDEO_SOURCE_VERSION_CHANGED", "视频资料版本已变化，必须重新准备拆解任务。")
        content_path = self._asset_path(channel_profile_id, source["detail"], source["contentAsset"])
        text = content_path.read_text(encoding="utf-8")
        paragraphs = [item.strip() for item in re.split(r"\r?\n\s*\r?\n", text) if item.strip()]
        timing_by_id: dict[str, dict[str, Any]] = {}
        if source["timingAsset"] is not None:
            timing_path = self._asset_path(channel_profile_id, source["detail"], source["timingAsset"])
            timing = _read_json(timing_path, "VIDEO_TIMING_MAP_INVALID")
            timing_by_id = {
                str(item.get("paragraphId")): item
                for item in timing.get("entries", [])
                if isinstance(item, dict) and isinstance(item.get("paragraphId"), str)
            }
        start_index = start_paragraph - 1
        selected = paragraphs[start_index : start_index + max_paragraphs]
        rows = []
        for offset, paragraph in enumerate(selected, start=start_paragraph):
            paragraph_id = f"p{offset:04d}"
            rows.append(
                {
                    "paragraphId": paragraph_id,
                    "text": paragraph,
                    "timing": timing_by_id.get(paragraph_id),
                }
            )
        next_paragraph = start_paragraph + len(rows)
        return {
            "deconstructionId": deconstruction_id,
            "sourcePackageId": source_package_id,
            "sourcePackageHash": planned["sourcePackage"]["targetHash"],
            "canonicalAsset": "content.txt",
            "paragraphs": rows,
            "totalParagraphs": len(paragraphs),
            "nextParagraph": next_paragraph if next_paragraph <= len(paragraphs) else None,
            "complete": next_paragraph > len(paragraphs),
            "timingMapAvailable": source["timingAsset"] is not None,
            "rawSubtitleReadOrStored": False,
        }

    @staticmethod
    def _validate_section_map(
        value: Any,
        *,
        fact_ids: set[str],
        timing_available: bool,
        paragraph_count: int,
    ) -> list[dict[str, Any]]:
        minimum_sections = 1 if paragraph_count == 1 else 2
        if not isinstance(value, list) or len(value) < minimum_sections:
            raise ToolError("FUNCTIONAL_SECTION_MAP_REQUIRED", "多段正文至少需要两个有证据的功能区段；单段正文仍须提交一个完整区段。")
        result: list[dict[str, Any]] = []
        section_ids: set[str] = set()
        previous_end = 0
        for item in value:
            if not isinstance(item, dict):
                raise ToolError("FUNCTIONAL_SECTION_INVALID", "功能区段必须是对象。")
            section_id = item.get("sectionId")
            if not isinstance(section_id, str) or not section_id.strip() or section_id in section_ids:
                raise ToolError("FUNCTIONAL_SECTION_INVALID", "功能区段 ID 缺失或重复。")
            section_ids.add(section_id)
            start = _paragraph_number(item.get("startParagraphId"), "startParagraphId")
            end = _paragraph_number(item.get("endParagraphId"), "endParagraphId")
            if start > end or start != previous_end + 1:
                raise ToolError("FUNCTIONAL_SECTION_ORDER_INVALID", "功能区段必须从 p0001 起连续覆盖正文且不能重叠或留空。")
            if end > paragraph_count:
                raise ToolError("FUNCTIONAL_SECTION_PARAGRAPH_OUT_OF_RANGE", "功能区段引用了统一正文中不存在的段落。")
            previous_end = end
            for field in (
                "functions",
                "audienceExpectation",
                "progress",
                "audienceReward",
                "emotionBefore",
                "emotionAfter",
            ):
                if item.get(field) in (None, "", [], {}):
                    raise ToolError("FUNCTIONAL_SECTION_INCOMPLETE", f"功能区段缺少 {field}。")
            if not isinstance(item["functions"], list) or any(not isinstance(x, str) or not x for x in item["functions"]):
                raise ToolError("FUNCTIONAL_SECTION_INCOMPLETE", "functions 必须是非空字符串数组。")
            evidence = item.get("evidenceFactIds")
            if not isinstance(evidence, list) or not evidence or not set(evidence).issubset(fact_ids):
                raise ToolError("FUNCTIONAL_SECTION_EVIDENCE_INVALID", "功能区段必须引用本视频已有事实。")
            if timing_available:
                start_seconds = item.get("startSeconds")
                end_seconds = item.get("endSeconds")
                if (
                    not isinstance(start_seconds, (int, float))
                    or isinstance(start_seconds, bool)
                    or not isinstance(end_seconds, (int, float))
                    or isinstance(end_seconds, bool)
                    or start_seconds < 0
                    or end_seconds <= start_seconds
                ):
                    raise ToolError("FUNCTIONAL_SECTION_TIMING_INVALID", "存在时间映射时，每个区段必须提供有效起止秒数。")
            result.append(json.loads(json.dumps(item, ensure_ascii=False)))
        if previous_end != paragraph_count:
            raise ToolError("FUNCTIONAL_SECTION_COVERAGE_INCOMPLETE", "功能区段必须覆盖统一正文的全部段落。")
        return result

    @staticmethod
    def _validate_requirement_coverage(
        value: Any,
        required_sections: list[str],
        source_package_id: str,
    ) -> list[dict[str, Any]]:
        if not required_sections:
            if value not in (None, []):
                raise ToolError("ACCOUNT_REQUIREMENT_COVERAGE_INVALID", "未绑定频道专属要求时不得伪造专属覆盖记录。")
            return []
        if not isinstance(value, list) or len(value) != len(required_sections):
            raise ToolError("ACCOUNT_REQUIREMENT_COVERAGE_REQUIRED", "必须逐项覆盖账号专属拆解区块。")
        rows: dict[str, dict[str, Any]] = {}
        for item in value:
            if not isinstance(item, dict) or item.get("requirement") in rows:
                raise ToolError("ACCOUNT_REQUIREMENT_COVERAGE_INVALID", "账号专属拆解覆盖项无效或重复。")
            requirement = item.get("requirement")
            if not isinstance(requirement, str):
                raise ToolError("ACCOUNT_REQUIREMENT_COVERAGE_INVALID", "账号专属拆解覆盖项缺少 requirement。")
            if item.get("status") != "COVERED" or not isinstance(item.get("evidenceRefs"), list) or not item["evidenceRefs"]:
                raise ToolError("ACCOUNT_REQUIREMENT_NOT_COVERED", "每个账号专属区块都必须标为 COVERED 并绑定证据。")
            if any(
                not isinstance(reference, dict)
                or reference.get("sourcePackageId") != source_package_id
                or not isinstance(reference.get("locator"), str)
                or not reference["locator"].strip()
                for reference in item["evidenceRefs"]
            ):
                raise ToolError("ACCOUNT_REQUIREMENT_EVIDENCE_INVALID", "账号专属区块只能引用当前视频的有效证据定位。")
            if not isinstance(item.get("observation"), str) or not item["observation"].strip():
                raise ToolError("ACCOUNT_REQUIREMENT_COVERAGE_INVALID", "账号专属区块必须记录观察结果；不存在也要明确说明。")
            rows[requirement] = json.loads(json.dumps(item, ensure_ascii=False))
        if set(rows) != set(required_sections):
            raise ToolError("ACCOUNT_REQUIREMENT_COVERAGE_INVALID", "账号专属拆解区块必须与冻结要求逐字对应。")
        return [rows[item] for item in required_sections]

    @staticmethod
    def _validate_quality_checks(value: Any) -> dict[str, Any]:
        if not isinstance(value, dict) or value.get("passed") is not True:
            raise ToolError("VIDEO_DECONSTRUCTION_QUALITY_FAILED", "单视频拆解质量门必须通过。")
        missing = sorted(CHECKPOINT_QUALITY_KEYS - set(value))
        if missing or any(value.get(key) is not True for key in CHECKPOINT_QUALITY_KEYS):
            raise ToolError("VIDEO_DECONSTRUCTION_QUALITY_FAILED", "单视频拆解质量硬项未全部通过。", details={"missing": missing})
        if value.get("hardFailures") not in (None, []):
            raise ToolError("VIDEO_DECONSTRUCTION_QUALITY_FAILED", "存在硬失败时不能保存成功拆解。")
        return json.loads(json.dumps(value, ensure_ascii=False))

    def checkpoint(
        self,
        *,
        task_id: Any,
        channel_profile_id: Any,
        binding_proof: Any,
        deconstruction_id: Any,
        source_package_id: Any,
        status: Any,
        analysis: Any = None,
        failure: Any = None,
    ) -> dict[str, Any]:
        self.store.assert_binding(
            task_id=task_id,
            channel_profile_id=channel_profile_id,
            binding_proof=binding_proof,
        )
        channel_profile_id = _safe_identifier(channel_profile_id, "channelProfileId", maximum=160)
        deconstruction_id = _safe_identifier(deconstruction_id, "deconstructionId")
        source_package_id = _safe_identifier(source_package_id, "sourcePackageId")
        state = self._load_state(channel_profile_id, deconstruction_id)
        if state.get("state") == "FROZEN":
            raise ToolError("VIDEO_DECONSTRUCTION_FROZEN", "已冻结的视频文案拆解不能改写。")
        plan = _read_json(self._root(channel_profile_id, deconstruction_id) / "plan.json", "VIDEO_DECONSTRUCTION_PLAN_INVALID")
        planned = next((item for item in plan["videos"] if item["sourcePackageId"] == source_package_id), None)
        if planned is None:
            raise ToolError("VIDEO_NOT_PLANNED", "该视频不属于本次拆解计划。")
        if status not in {"SUCCEEDED", "FAILED", "SKIPPED"}:
            raise ToolError("VIDEO_DECONSTRUCTION_STATUS_INVALID", "视频拆解状态不受支持。")
        checkpoint_input_hash = _json_hash({"status": status, "analysis": analysis, "failure": failure})
        root = self._root(channel_profile_id, deconstruction_id)
        path = root / "videos" / f"{source_package_id}.json"
        if path.is_file():
            existing = _read_json(path, "VIDEO_DECONSTRUCTION_CHECKPOINT_INVALID")
            if existing.get("checkpointInputHash") == checkpoint_input_hash:
                return {"analysis": existing, "state": state, "idempotent": True}
            raise ToolError("VIDEO_DECONSTRUCTION_CHECKPOINT_CONFLICT", "同一视频已保存不同拆解，不会静默覆盖。")

        now = utc_now()
        if status == "SUCCEEDED":
            if not isinstance(analysis, dict):
                raise ToolError("VIDEO_DECONSTRUCTION_ANALYSIS_REQUIRED", "成功视频必须提交完整拆解。")
            buckets = _validate_analysis_buckets(analysis.get("analysisBuckets"), source_package_id=source_package_id)
            for method in buckets["transferableMethods"]:
                consumers = method.get("downstreamConsumers")
                if not isinstance(consumers, list) or not consumers or not set(consumers).issubset(DOWNSTREAM_CONSUMERS):
                    raise ToolError("DOWNSTREAM_CONSUMERS_REQUIRED", "每条可迁移方法必须标明选题中心、文稿中心或两者。")
            dimensions = _validate_dimensions(
                analysis.get("dimensions"),
                VIDEO_DECONSTRUCTION_DIMENSIONS,
                "VIDEO_DECONSTRUCTION_DIMENSIONS_INCOMPLETE",
            )
            current_source = self._source_detail(channel_profile_id, source_package_id)
            if current_source["manifest"]["contentHash"] != planned["sourcePackage"]["targetHash"]:
                raise ToolError("VIDEO_SOURCE_VERSION_CHANGED", "视频资料版本已变化，必须重新准备拆解任务。")
            content_path = self._asset_path(
                channel_profile_id,
                current_source["detail"],
                current_source["contentAsset"],
            )
            paragraph_count = len(
                [
                    item
                    for item in re.split(r"\r?\n\s*\r?\n", content_path.read_text(encoding="utf-8"))
                    if item.strip()
                ]
            )
            fact_ids = {item["factId"] for item in buckets["originalFacts"]}
            section_map = self._validate_section_map(
                analysis.get("sectionMap"),
                fact_ids=fact_ids,
                timing_available=planned.get("timingMapAsset") is not None,
                paragraph_count=paragraph_count,
            )
            requirement_coverage = self._validate_requirement_coverage(
                analysis.get("requirementCoverage"),
                plan.get("requiredSections", []),
                source_package_id,
            )
            quality_checks = self._validate_quality_checks(analysis.get("qualityChecks"))
            generic = self.analysis_kind == "content-deconstruction"
            item_contract_type = "content-deconstruction-analysis-v1" if generic else "video-deconstruction-analysis-v1"
            item_schema = "content-deconstruction-analysis-v1.schema.json" if generic else "video-deconstruction-analysis-v1.schema.json"
            contract = with_hash(
                {
                    "schemaVersion": CONTENT_ANALYSIS_VERSION,
                    "contractType": item_contract_type,
                    "id": _derived_id("content_deconstruction" if generic else "video_deconstruction", deconstruction_id, source_package_id),
                    "version": "1.0.0",
                    "createdAt": now,
                    "hashAlgorithm": "SHA-256",
                    "hashRule": "canonical-json-v1",
                    "upstream": [
                        planned["sourcePackage"],
                        *([plan["accountRequirement"]] if plan.get("accountRequirement") else []),
                    ],
                    "deconstructionId": deconstruction_id,
                    "targetChannelProfileId": channel_profile_id,
                    "sourcePackageId": source_package_id,
                    "sourcePackageHash": planned["sourcePackage"]["targetHash"],
                    "role": planned["role"],
                    "checkpointInputHash": checkpoint_input_hash,
                    "analysisBuckets": buckets,
                    "dimensions": dimensions,
                    "sectionMap": section_map,
                    "requirementCoverage": requirement_coverage,
                    "qualityGate": quality_checks,
                    "status": "FROZEN",
                }
            )
            self._validate_contract_schema(contract, item_schema)
        else:
            if not isinstance(failure, dict) or not isinstance(failure.get("reason"), str) or not failure["reason"].strip():
                raise ToolError("VIDEO_DECONSTRUCTION_FAILURE_REQUIRED", "失败或跳过视频必须记录原因。")
            generic = self.analysis_kind == "content-deconstruction"
            item_contract_type = "content-deconstruction-analysis-v1" if generic else "video-deconstruction-analysis-v1"
            item_schema = "content-deconstruction-analysis-v1.schema.json" if generic else "video-deconstruction-analysis-v1.schema.json"
            contract = with_hash(
                {
                    "schemaVersion": CONTENT_ANALYSIS_VERSION,
                    "contractType": item_contract_type,
                    "id": _derived_id("content_deconstruction" if generic else "video_deconstruction", deconstruction_id, source_package_id),
                    "version": "1.0.0",
                    "createdAt": now,
                    "hashAlgorithm": "SHA-256",
                    "hashRule": "canonical-json-v1",
                    "upstream": [planned["sourcePackage"]],
                    "deconstructionId": deconstruction_id,
                    "targetChannelProfileId": channel_profile_id,
                    "sourcePackageId": source_package_id,
                    "sourcePackageHash": planned["sourcePackage"]["targetHash"],
                    "role": planned["role"],
                    "checkpointInputHash": checkpoint_input_hash,
                    "failure": failure,
                    "status": status,
                }
            )
            self._validate_contract_schema(contract, item_schema)
        _atomic_json(path, contract)
        state["videos"][source_package_id] = {
            "status": status,
            "sourceHash": planned["sourcePackage"]["targetHash"],
            "contentHash": contract["contentHash"],
            "path": path.relative_to(root).as_posix(),
        }
        succeeded = sum(item["status"] == "SUCCEEDED" for item in state["videos"].values())
        state["progress"] = {
            "recorded": len(state["videos"]),
            "succeeded": succeeded,
            "total": len(plan["videos"]),
        }
        if len(state["videos"]) == len(plan["videos"]):
            state["state"] = "FINALIZE_READY"
        self._save_state(state)
        return {"analysis": contract, "state": state, "idempotent": False}

    @staticmethod
    def _validate_comparison(
        value: Any,
        mode: str,
        successful_source_ids: set[str],
    ) -> dict[str, Any] | None:
        if mode != "compare":
            if value not in (None, {}):
                raise ToolError("VIDEO_COMPARISON_MODE_MISMATCH", "只有 compare 模式可以冻结跨视频比较。")
            return None
        if len(successful_source_ids) < 2:
            raise ToolError("VIDEO_COMPARISON_INSUFFICIENT", "compare 模式至少需要两条成功拆解。")
        if not isinstance(value, dict):
            raise ToolError("VIDEO_COMPARISON_REQUIRED", "compare 模式必须提交保留差异的比较结果。")
        for key in ("sharedFunctions", "videoDifferences", "nonTransferableDifferences"):
            if not isinstance(value.get(key), list) or not value[key]:
                raise ToolError("VIDEO_COMPARISON_INCOMPLETE", f"比较结果缺少 {key}。")
        if value.get("eachVideoKeptIndependent") is not True:
            raise ToolError("VIDEO_COMPARISON_INDEPENDENCE_REQUIRED", "比较必须保留每条视频独立结论。")
        if value.get("averagingUsed") is not False or value.get("segmentSplicingUsed") is not False:
            raise ToolError("VIDEO_COMPARISON_MERGE_FORBIDDEN", "比较不得求平均或按片段拼接。")
        for shared in value["sharedFunctions"]:
            if (
                not isinstance(shared, dict)
                or not isinstance(shared.get("statement"), str)
                or not shared["statement"].strip()
                or not isinstance(shared.get("evidenceSourcePackageIds"), list)
                or len(set(shared["evidenceSourcePackageIds"])) < 2
                or not set(shared["evidenceSourcePackageIds"]).issubset(successful_source_ids)
            ):
                raise ToolError("VIDEO_COMPARISON_EVIDENCE_INVALID", "共享功能必须由至少两条成功视频的独立拆解支持。")
        difference_ids = {
            item.get("sourcePackageId")
            for item in value["videoDifferences"]
            if isinstance(item, dict)
            and isinstance(item.get("difference"), str)
            and item["difference"].strip()
        }
        if difference_ids != successful_source_ids:
            raise ToolError("VIDEO_COMPARISON_DIFFERENCES_INCOMPLETE", "比较必须逐条记录每个成功视频的差异。")
        return json.loads(json.dumps(value, ensure_ascii=False))

    @staticmethod
    def _validate_final_quality(value: Any) -> dict[str, Any]:
        if not isinstance(value, dict) or value.get("passed") is not True:
            raise ToolError("VIDEO_DECONSTRUCTION_FINAL_QUALITY_FAILED", "视频文案拆解最终质量门必须通过。")
        missing = sorted(FINAL_QUALITY_KEYS - set(value))
        if missing or any(value.get(key) is not True for key in FINAL_QUALITY_KEYS):
            raise ToolError("VIDEO_DECONSTRUCTION_FINAL_QUALITY_FAILED", "最终质量硬项未全部通过。", details={"missing": missing})
        if value.get("hardFailures") not in (None, []):
            raise ToolError("VIDEO_DECONSTRUCTION_FINAL_QUALITY_FAILED", "存在硬失败时不能冻结分析包。")
        return json.loads(json.dumps(value, ensure_ascii=False))

    @staticmethod
    def _downstream_views(analyses: list[dict[str, Any]]) -> dict[str, Any]:
        method_ids = {consumer: [] for consumer in DOWNSTREAM_CONSUMERS}
        boundary_ids: list[dict[str, str]] = []
        unknown_ids: list[dict[str, str]] = []
        for analysis in analyses:
            source_package_id = analysis["sourcePackageId"]
            for method in analysis["analysisBuckets"]["transferableMethods"]:
                for consumer in method["downstreamConsumers"]:
                    method_ids[consumer].append(
                        {"sourcePackageId": source_package_id, "methodId": method["methodId"]}
                    )
            boundary_ids.extend(
                {"sourcePackageId": source_package_id, "boundaryId": item["boundaryId"]}
                for item in analysis["analysisBuckets"]["prohibitedCopy"]
            )
            unknown_ids.extend(
                {"sourcePackageId": source_package_id, "unknownId": item["unknownId"]}
                for item in analysis["analysisBuckets"]["unknowns"]
            )
        topic_view = {
            "transferableMethods": method_ids["topic-center"],
            "preferredDimensions": [
                "positioning",
                "oneSentenceCore",
                "functionalStructure",
                "emotionalCurve",
                "audienceRewards",
                "payoffAndReversals",
                "characterFunctionsAndRelations",
                "credibilityAndConstraints",
            ],
            "prohibitedCopy": boundary_ids,
            "unknowns": unknown_ids,
        }
        manuscript_view = {
            "transferableMethods": method_ids["manuscript-center"],
            "preferredDimensions": [
                "functionalStructure",
                "narrativeVoiceAndStyle",
                "paragraphBreath",
                "expressionTechniques",
                "youtubeTiming",
                "retentionMechanics",
                "titlePromiseFulfillment",
            ],
            "prohibitedCopy": boundary_ids,
            "unknowns": unknown_ids,
        }
        return {
            "topicCenter": topic_view,
            "manuscriptCenter": manuscript_view,
            "rewrite": {**topic_view, "transferableMethods": method_ids["content-rewrite"] or topic_view["transferableMethods"]},
            "productionText": {**manuscript_view, "transferableMethods": method_ids["production-text"] or manuscript_view["transferableMethods"]},
        }

    def finalize(
        self,
        *,
        task_id: Any,
        channel_profile_id: Any,
        binding_proof: Any,
        deconstruction_id: Any,
        quality_gate: Any,
        comparison: Any = None,
    ) -> dict[str, Any]:
        self.store.assert_binding(
            task_id=task_id,
            channel_profile_id=channel_profile_id,
            binding_proof=binding_proof,
        )
        channel_profile_id = _safe_identifier(channel_profile_id, "channelProfileId", maximum=160)
        deconstruction_id = _safe_identifier(deconstruction_id, "deconstructionId")
        state = self._load_state(channel_profile_id, deconstruction_id)
        if state.get("state") == "FROZEN":
            return self.get(channel_profile_id=channel_profile_id, deconstruction_id=deconstruction_id)
        plan = _read_json(self._root(channel_profile_id, deconstruction_id) / "plan.json", "VIDEO_DECONSTRUCTION_PLAN_INVALID")
        if len(state.get("videos", {})) != len(plan["videos"]):
            raise ToolError("VIDEO_DECONSTRUCTION_INCOMPLETE", "必须先逐条记录所有计划视频的成功、失败或跳过状态。")
        root = self._root(channel_profile_id, deconstruction_id)
        analyses: list[dict[str, Any]] = []
        failures: list[dict[str, Any]] = []
        for planned in plan["videos"]:
            record = state["videos"][planned["sourcePackageId"]]
            contract = _read_json(root / record["path"], "VIDEO_DECONSTRUCTION_ANALYSIS_INVALID")
            if canonical_hash(contract) != contract.get("contentHash"):
                raise ToolError("VIDEO_DECONSTRUCTION_ANALYSIS_HASH_MISMATCH", "单视频拆解哈希无效。")
            if record["status"] == "SUCCEEDED":
                analyses.append(contract)
            else:
                failures.append(
                    {
                        "sourcePackageId": planned["sourcePackageId"],
                        "status": record["status"],
                        "failure": contract.get("failure"),
                    }
                )
        if not analyses:
            raise ToolError("VIDEO_DECONSTRUCTION_NO_SUCCESS", "没有成功视频可冻结为 Analysis Package。")
        if plan["mode"] == "single" and len(analyses) != 1:
            raise ToolError("VIDEO_DECONSTRUCTION_SINGLE_FAILED", "单视频拆解没有成功完成。")
        comparison = self._validate_comparison(
            comparison,
            plan["mode"],
            {analysis["sourcePackageId"] for analysis in analyses},
        )
        quality_gate = self._validate_final_quality(quality_gate)
        merged_buckets = {
            key: [
                {**item, "sourcePackageId": analysis["sourcePackageId"]}
                for analysis in analyses
                for item in analysis["analysisBuckets"][key]
            ]
            for key in BUCKET_KEYS
        }
        created = utc_now()
        downstream_views = self._downstream_views(analyses)
        generic = self.analysis_kind == "content-deconstruction"
        package_payload = {
                "schemaVersion": CONTENT_ANALYSIS_VERSION,
                "contractType": "analysis-package-v1",
                "id": _derived_id("analysis", deconstruction_id),
                "version": "1.0.0",
                "createdAt": created,
                "hashAlgorithm": "SHA-256",
                "hashRule": "canonical-json-v1",
                "upstream": [
                    item["sourcePackage"] for item in plan["videos"]
                ] + ([plan["accountRequirement"]] if plan.get("accountRequirement") else []),
                "analysisKind": self.analysis_kind,
                "deconstructionId": deconstruction_id,
                "distillationId": plan.get("distillationId"),
                "targetChannelProfileId": channel_profile_id,
                "mode": plan["mode"],
                "analysisBuckets": merged_buckets,
                "comparison": comparison,
                "downstreamViews": downstream_views,
                "qualityGate": quality_gate,
                "status": "FROZEN",
            }
        if generic:
            package_payload["sourceAnalyses"] = analyses
            package_payload["failedSources"] = failures
        else:
            package_payload["videoAnalyses"] = analyses
            package_payload["failedVideos"] = failures
        package = with_hash(package_payload)
        package_path = root / "analysis-package-v1.json"
        self._validate_contract_schema(package, "analysis-package-v1.schema.json")
        _atomic_json(package_path, package)
        outputs = {
            "analysisPackage": {
                **_contract_ref(package),
                "path": package_path.relative_to(root).as_posix(),
            },
            "sourceAnalyses" if generic else "videoAnalyses": [
                {
                    **_contract_ref(analysis),
                    "sourcePackageId": analysis["sourcePackageId"],
                    "path": state["videos"][analysis["sourcePackageId"]]["path"],
                }
                for analysis in analyses
            ],
            "downstreamConsumers": ["topic-center", "manuscript-center"],
        }
        _atomic_json(root / "outputs.json", outputs)
        state["outputs"] = outputs
        state["state"] = "FROZEN"
        self._save_state(state)
        return {
            "state": state,
            "outputs": outputs,
            "completionCard": {
                "contentDeconstruction" if generic else "videoDeconstruction": f"{len(analyses)}/{len(plan['videos'])} succeeded",
                "failedOrSkipped": len(failures),
                "accountRequirementsApplied": bool(plan.get("accountRequirement")),
                "fiveEvidenceBuckets": list(BUCKET_KEYS),
                "handoffReady": ["content-rewrite", "production-text"] if generic else ["topic-center", "manuscript-center"],
                "next": "continue to content-rewrite" if generic else "legacy analysis package frozen",
            },
        }

    def get(self, *, channel_profile_id: Any, deconstruction_id: Any) -> dict[str, Any]:
        channel_profile_id = _safe_identifier(channel_profile_id, "channelProfileId", maximum=160)
        deconstruction_id = _safe_identifier(deconstruction_id, "deconstructionId")
        state = self._load_state(channel_profile_id, deconstruction_id)
        root = self._root(channel_profile_id, deconstruction_id)
        return {
            "state": state,
            "plan": _read_json(root / "plan.json", "VIDEO_DECONSTRUCTION_PLAN_INVALID"),
            "outputs": state.get("outputs", {}),
            "progressReadOnly": True,
        }

    def analysis_package(self, *, channel_profile_id: Any, deconstruction_id: Any) -> dict[str, Any]:
        state = self._load_state(channel_profile_id, deconstruction_id)
        if state.get("state") != "FROZEN":
            raise ToolError("VIDEO_DECONSTRUCTION_NOT_FROZEN", "视频文案拆解尚未冻结，不能交给下游。")
        path = self._root(channel_profile_id, deconstruction_id) / state["outputs"]["analysisPackage"]["path"]
        contract = _read_json(path, "VIDEO_DECONSTRUCTION_ANALYSIS_PACKAGE_INVALID")
        if canonical_hash(contract) != contract.get("contentHash"):
            raise ToolError("VIDEO_DECONSTRUCTION_ANALYSIS_PACKAGE_HASH_MISMATCH", "Analysis Package 哈希无效。")
        return contract

    def integrity_check(self, *, channel_profile_id: Any, deconstruction_id: Any) -> dict[str, Any]:
        channel_profile_id = _safe_identifier(channel_profile_id, "channelProfileId", maximum=160)
        deconstruction_id = _safe_identifier(deconstruction_id, "deconstructionId")
        state = self._load_state(channel_profile_id, deconstruction_id)
        root = self._root(channel_profile_id, deconstruction_id)
        errors: list[dict[str, Any]] = []
        plan = _read_json(root / "plan.json", "VIDEO_DECONSTRUCTION_PLAN_INVALID")
        for planned in plan["videos"]:
            try:
                source = self._source_detail(channel_profile_id, planned["sourcePackageId"])
                if source["manifest"]["contentHash"] != planned["sourcePackage"]["targetHash"]:
                    errors.append({"sourcePackageId": planned["sourcePackageId"], "issue": "source-version"})
            except ToolError as exc:
                errors.append({"sourcePackageId": planned["sourcePackageId"], "issue": exc.code})
        for record in state.get("videos", {}).values():
            path = root / record["path"]
            if not path.is_file():
                errors.append({"path": record["path"], "issue": "missing"})
                continue
            contract = _read_json(path, "VIDEO_DECONSTRUCTION_ANALYSIS_INVALID")
            if canonical_hash(contract) != contract.get("contentHash"):
                errors.append({"path": record["path"], "issue": "content-hash"})
        output = state.get("outputs", {}).get("analysisPackage")
        if isinstance(output, dict) and isinstance(output.get("path"), str):
            path = root / output["path"]
            if not path.is_file():
                errors.append({"path": output["path"], "issue": "missing"})
            else:
                package = _read_json(path, "VIDEO_DECONSTRUCTION_ANALYSIS_PACKAGE_INVALID")
                if canonical_hash(package) != package.get("contentHash"):
                    errors.append({"path": output["path"], "issue": "content-hash"})
        if plan.get("accountRequirement"):
            try:
                requirement = self.channel_distillations.account_requirement(
                    channel_profile_id=channel_profile_id,
                    distillation_id=plan["distillationId"],
                    kind="decomposition",
                )
                if requirement["contentHash"] != plan["accountRequirement"]["targetHash"]:
                    errors.append({"distillationId": plan["distillationId"], "issue": "account-requirement-version"})
            except (AttributeError, ToolError) as exc:
                errors.append({"distillationId": plan.get("distillationId"), "issue": getattr(exc, "code", "provider-unavailable")})
        return {
            "status": "PASS" if not errors else "FAIL",
            "deconstructionId": deconstruction_id,
            "state": state["state"],
            "errors": errors,
            "progressReadOnly": True,
        }


__all__ = ["VIDEO_DECONSTRUCTION_VERSION", "VIDEO_DECONSTRUCTION_MODES", "VideoCopyDeconstruction"]
