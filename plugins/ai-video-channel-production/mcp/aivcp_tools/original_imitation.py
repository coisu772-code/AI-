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
from .contracts import canonical_hash, utc_now, with_hash
from .errors import ToolError


ORIGINAL_IMITATION_VERSION = "1.0.0"
REFERENCE_KINDS = {"video-analysis", "canonical-source"}
CANONICAL_SOURCE_TYPES = {"novel-web", "local-file", "pasted-text"}
SOURCE_DIMENSIONS = {
    "positioning",
    "storyEngine",
    "characterAndRelationshipFunctions",
    "worldRulesAndConstraints",
    "functionalStructure",
    "rhythmAndProgression",
    "emotionalAccumulation",
    "audienceRewards",
    "climaxResources",
    "narrativeVoiceAndExpression",
    "credibilityAndScale",
    "originalityBoundaries",
}
LEARNING_KEYS = {"topicFunction", "structure", "rhythm", "expression", "audiencePayoff"}
SCORE_KEYS = {
    "channelMatch",
    "audienceExpectation",
    "clickPotential",
    "logicalPlausibility",
    "characterMotivation",
    "conflictValidity",
    "abilityResourceSource",
    "impactScale",
    "worldRuleConsistency",
    "emotionalValue",
    "originalDifference",
    "serializationPotential",
    "productionDifficulty",
}
CORE_SCORE_KEYS = {
    "logicalPlausibility",
    "characterMotivation",
    "conflictValidity",
    "abilityResourceSource",
    "impactScale",
    "audienceExpectation",
}
CREDIBILITY_QUESTION_IDS = tuple(f"q{number}" for number in range(1, 11))
RESULT_STAGE_IDS = ("verify", "stabilize", "expand", "new-problem", "adjust", "re-expand")
ANTI_COPY_EXPECTED = {
    "originalSentencesCopied": False,
    "properNamesCopied": False,
    "completeEventOrderCopied": False,
    "singleWorkMainlineCopied": False,
    "segmentSplicingUsed": False,
    "oneCausalEngineRebuilt": True,
}
DISTINCTNESS_CATEGORIES = {
    "protagonist-pov",
    "goal",
    "rule-constraint",
    "conflict-source",
    "relationships",
    "fusion-method",
    "story-engine-growth",
    "cross-genre-expression",
}
MAJOR_DISTINCTNESS_CATEGORIES = {
    "protagonist-pov",
    "goal",
    "rule-constraint",
    "conflict-source",
    "story-engine-growth",
}
SOURCE_QUALITY_KEYS = {
    "fiveBucketsSeparated",
    "evidenceTraceable",
    "functionsMapped",
    "credibilityBoundaryExplicit",
    "copyBoundariesExplicit",
}
DIRECTION_FINAL_QUALITY_KEYS = {
    "exactlyEightDirections",
    "allDirectionsDisplayed",
    "pairwiseSubstantiveDifference",
    "credibilityAuditsComplete",
    "sourceRolesAndWeightsApplied",
    "unifiedCausalEnginesRebuilt",
    "antiCopyBoundary",
    "topThreeRanked",
    "manualConfirmationStillRequired",
}


def _read_json(path: Path, code: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ToolError(code, "原创仿写状态或契约不可读。", details={"path": str(path)}) from exc
    if not isinstance(value, dict):
        raise ToolError(code, "原创仿写状态或契约结构无效。", details={"path": str(path)})
    return value


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _nonempty(value: Any, field: str) -> Any:
    if value in (None, "", [], {}):
        raise ToolError("IMITATION_DIRECTION_INCOMPLETE", f"原创方向缺少 {field}。")
    return value


class OriginalImitationWriting:
    """Build eight original directions and freeze one user-confirmed writing contract."""

    def __init__(
        self,
        store: Any,
        sources: Any,
        *,
        video_analyses: Any = None,
        channel_distillations: Any = None,
        plugin_root: Path | None = None,
    ) -> None:
        self.store = store
        self.sources = sources
        self.video_analyses = video_analyses
        self.channel_distillations = channel_distillations
        self.plugin_root = plugin_root

    def _validate_contract_schema(self, contract: dict[str, Any], schema_name: str) -> None:
        if self.plugin_root is None:
            return
        schema_root = self.plugin_root.resolve().parents[1] / "contracts" / "schemas"
        try:
            resources = []
            for path in sorted(schema_root.glob("*.schema.json")):
                schema = json.loads(path.read_text(encoding="utf-8"))
                resources.append((schema["$id"], Resource.from_contents(schema)))
            selected = json.loads((schema_root / schema_name).read_text(encoding="utf-8"))
            validator = Draft202012Validator(
                selected,
                registry=Registry().with_resources(resources),
                format_checker=FormatChecker(),
            )
            errors = sorted(validator.iter_errors(contract), key=lambda item: list(item.absolute_path))
        except (OSError, UnicodeError, json.JSONDecodeError, KeyError) as exc:
            raise ToolError("IMITATION_SCHEMA_INVALID", "原创仿写契约 Schema 不可读。") from exc
        if errors:
            first = errors[0]
            location = "/".join(str(item) for item in first.absolute_path) or "<root>"
            raise ToolError(
                "IMITATION_CONTRACT_SCHEMA_FAILED",
                "原创仿写契约未通过 Schema。",
                details={"schema": schema_name, "location": location, "message": first.message},
            )

    def capabilities(self) -> dict[str, Any]:
        return {
            "available": True,
            "version": ORIGINAL_IMITATION_VERSION,
            "interfaces": {
                "style-imitation": "available",
                "writing-style-contract-v1": "available",
                "analysis-package-v1": "input-available",
                "source-package": "input-available",
            },
            "acceptedInputs": [
                "single-or-multiple-video-deconstruction",
                "single-or-multiple-canonical-novel",
                "video-plus-novel",
                "multi-channel-copy-plus-library",
            ],
            "directionCount": 8,
            "topCount": 3,
            "scoreKeys": sorted(SCORE_KEYS),
            "credibilityQuestions": list(CREDIBILITY_QUESTION_IDS),
            "consumers": ["topic-center", "manuscript-center"],
            "boundaries": {
                "sourceRolesRequired": True,
                "sourceWeightsTotal": 100,
                "weightsAreSegmentShares": False,
                "learnsOnly": sorted(LEARNING_KEYS),
                "copiesOriginalSentences": False,
                "copiesProperNames": False,
                "copiesCompleteEventOrder": False,
                "copiesSingleWorkMainline": False,
                "segmentSplicing": False,
                "unifiedCausalRebuildRequired": True,
                "manualDirectionConfirmationRequired": True,
                "writesFullOutlineOrManuscript": False,
            },
        }

    def _root(self, channel_profile_id: str, imitation_id: str) -> Path:
        return (
            self.store.channel_path(channel_profile_id)
            / "content-analysis"
            / "original-imitation"
            / _safe_identifier(imitation_id, "imitationId")
        )

    def _state_path(self, channel_profile_id: str, imitation_id: str) -> Path:
        return self._root(channel_profile_id, imitation_id) / "state.json"

    def _load_state(self, channel_profile_id: str, imitation_id: str) -> dict[str, Any]:
        state = _read_json(self._state_path(channel_profile_id, imitation_id), "IMITATION_NOT_FOUND")
        if state.get("channelProfileId") != channel_profile_id or state.get("imitationId") != imitation_id:
            raise ToolError("IMITATION_IDENTITY_MISMATCH", "原创仿写状态身份不匹配。")
        return state

    def _save_state(self, state: dict[str, Any]) -> None:
        state["updatedAt"] = utc_now()
        _atomic_json(self._state_path(state["channelProfileId"], state["imitationId"]), state)

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

    def _canonical_source(self, channel_profile_id: str, source_package_id: Any) -> dict[str, Any]:
        source_package_id = _safe_identifier(source_package_id, "sourcePackageId")
        detail = self.sources.get_source(
            channel_profile_id=channel_profile_id,
            source_package_id=source_package_id,
        )
        manifest = detail["manifest"]
        if canonical_hash(manifest) != manifest.get("contentHash"):
            raise ToolError("SOURCE_HASH_MISMATCH", "Source Package 的 canonical-json-v1 哈希无效。")
        if manifest.get("sourceType") not in CANONICAL_SOURCE_TYPES:
            raise ToolError("IMITATION_CANONICAL_SOURCE_INVALID", "直接仿写资料只接收小说网页、本地正文或粘贴正文；YouTube 必须先完成视频文案拆解。")
        content_asset = self._asset(manifest, "content.txt")
        if manifest.get("status") != "CONTENT_READY" or content_asset is None:
            raise ToolError("IMITATION_CANONICAL_TEXT_REQUIRED", "小说或文本资料必须先形成已验收的统一 content.txt。")
        return {"detail": detail, "manifest": manifest, "contentAsset": content_asset}

    def _asset_path(self, channel_profile_id: str, detail: dict[str, Any], asset: dict[str, Any]) -> Path:
        manifest_relative = detail.get("source", {}).get("manifest_relative_path")
        if not isinstance(manifest_relative, str):
            raise ToolError("SOURCE_ASSET_PATH_INVALID", "Source Package 缺少正式 manifest 路径。")
        channel_root = self.store.channel_path(channel_profile_id).resolve()
        package_root = (channel_root / manifest_relative).resolve().parent
        target = (package_root / str(asset.get("relativePath", ""))).resolve()
        if target != package_root and package_root not in target.parents:
            raise ToolError("SOURCE_ASSET_PATH_INVALID", "资料资产路径越出 Source Package。")
        if not target.is_file() or _sha256_file(target) != asset.get("sha256"):
            raise ToolError("SOURCE_ASSET_HASH_MISMATCH", "统一正文缺失或哈希无效。")
        return target

    @staticmethod
    def _source_lock(manifest: dict[str, Any]) -> dict[str, Any]:
        return {
            "sourcePackageId": manifest["sourcePackageId"],
            "version": manifest["version"],
            "contentHash": manifest["contentHash"],
            "status": manifest["status"],
            "acceptedPartial": False,
            "acceptedPartialAt": None,
            "knownLimitations": [],
            "provenance": manifest["provenance"],
            "rightsBoundary": manifest["rightsBoundary"],
        }

    def prepare(
        self,
        *,
        task_id: Any,
        channel_profile_id: Any,
        binding_proof: Any,
        imitation_id: Any,
        references: Any,
        distillation_id: Any = None,
    ) -> dict[str, Any]:
        self.store.assert_binding(
            task_id=task_id,
            channel_profile_id=channel_profile_id,
            binding_proof=binding_proof,
        )
        channel_profile_id = _safe_identifier(channel_profile_id, "channelProfileId", maximum=160)
        imitation_id = _safe_identifier(imitation_id, "imitationId")
        if not isinstance(references, list) or not references or len(references) > 8:
            raise ToolError("IMITATION_REFERENCES_INVALID", "references 必须包含 1–8 个明确来源。")

        planned: list[dict[str, Any]] = []
        seen: set[str] = set()
        inferred_distillations: set[str] = set()
        source_locks: dict[str, dict[str, Any]] = {}
        for index, item in enumerate(references, 1):
            if not isinstance(item, dict) or item.get("inputKind") not in REFERENCE_KINDS:
                raise ToolError("IMITATION_REFERENCE_INVALID", "每个来源必须声明 video-analysis 或 canonical-source。")
            role = item.get("role")
            weight = item.get("weight")
            if not isinstance(role, str) or not role.strip():
                raise ToolError("IMITATION_ROLE_REQUIRED", "每个仿写来源必须声明明确角色。")
            if not isinstance(weight, (int, float)) or isinstance(weight, bool) or weight <= 0 or weight > 100:
                raise ToolError("IMITATION_WEIGHT_INVALID", "每个来源权重必须是大于 0 且不超过 100 的数字。")
            if item["inputKind"] == "video-analysis":
                if self.video_analyses is None:
                    raise ToolError("VIDEO_ANALYSIS_PROVIDER_UNAVAILABLE", "视频文案拆解提供器尚未接入。")
                deconstruction_id = _safe_identifier(item.get("deconstructionId"), "deconstructionId")
                package = self.video_analyses.analysis_package(
                    channel_profile_id=channel_profile_id,
                    deconstruction_id=deconstruction_id,
                )
                if package.get("targetChannelProfileId") != channel_profile_id:
                    raise ToolError("IMITATION_TARGET_MISMATCH", "视频拆解包不属于当前目标频道。")
                if package.get("distillationId"):
                    inferred_distillations.add(package["distillationId"])
                video_analyses = package.get("videoAnalyses", [])
                selected_source_package_id = item.get("sourcePackageId")
                if selected_source_package_id is None:
                    if len(video_analyses) != 1:
                        raise ToolError(
                            "IMITATION_VIDEO_SOURCE_SELECTION_REQUIRED",
                            "多视频拆解包必须逐条指定 sourcePackageId，确保每条视频都有独立角色和权重。",
                        )
                    selected_analysis = video_analyses[0]
                else:
                    selected_source_package_id = _safe_identifier(selected_source_package_id, "sourcePackageId")
                    selected_analysis = next(
                        (analysis for analysis in video_analyses if analysis.get("sourcePackageId") == selected_source_package_id),
                        None,
                    )
                    if selected_analysis is None:
                        raise ToolError("IMITATION_VIDEO_SOURCE_NOT_IN_ANALYSIS", "指定视频不属于该冻结拆解包。")
                selected_source_package_id = selected_analysis["sourcePackageId"]
                source_key = f"video-analysis:{deconstruction_id}:{selected_source_package_id}"
                if source_key in seen:
                    raise ToolError("IMITATION_REFERENCE_DUPLICATE", "同一拆解包中的同一视频不能重复加入。")
                source = self.sources.get_source(
                    channel_profile_id=channel_profile_id,
                    source_package_id=selected_source_package_id,
                )["manifest"]
                if source.get("contentHash") != selected_analysis.get("sourcePackageHash") or canonical_hash(source) != source.get("contentHash"):
                    raise ToolError("IMITATION_SOURCE_VERSION_CHANGED", "视频拆解包绑定的 Source Package 已变化。")
                if source["sourcePackageId"] in source_locks:
                    raise ToolError("IMITATION_REFERENCE_DUPLICATE", "同一底层视频不能通过不同拆解包重复计权。")
                source_locks[source["sourcePackageId"]] = self._source_lock(source)
                planned.append(
                    {
                        "sourceKey": source_key,
                        "inputKind": "video-analysis",
                        "role": role.strip(),
                        "weight": weight,
                        "deconstructionId": deconstruction_id,
                        "sourcePackageId": selected_source_package_id,
                        "analysisPackage": _contract_ref(package),
                        "videoAnalysis": _contract_ref(selected_analysis),
                        "underlyingSources": [_source_ref(source)],
                        "status": "ANALYZED",
                    }
                )
            else:
                source = self._canonical_source(channel_profile_id, item.get("sourcePackageId"))
                manifest = source["manifest"]
                source_key = f"canonical-source:{manifest['sourcePackageId']}"
                if source_key in seen:
                    raise ToolError("IMITATION_REFERENCE_DUPLICATE", "同一规范化资料不能重复加入。")
                source_locks[manifest["sourcePackageId"]] = self._source_lock(manifest)
                planned.append(
                    {
                        "sourceKey": source_key,
                        "inputKind": "canonical-source",
                        "role": role.strip(),
                        "weight": weight,
                        "sourcePackageId": manifest["sourcePackageId"],
                        "sourcePackage": _source_ref(manifest),
                        "canonicalTextAsset": source["contentAsset"],
                        "status": "ANALYSIS_REQUIRED",
                    }
                )
            seen.add(source_key)

        total_weight = sum(float(item["weight"]) for item in planned)
        if abs(total_weight - 100) > 1e-9:
            raise ToolError("IMITATION_WEIGHT_TOTAL_INVALID", "全部来源权重必须精确合计为 100。", details={"actual": total_weight})
        explicit_distillation = None
        if distillation_id is not None:
            explicit_distillation = _safe_identifier(distillation_id, "distillationId")
            inferred_distillations.add(explicit_distillation)
        if len(inferred_distillations) > 1:
            raise ToolError("IMITATION_ACCOUNT_SCOPE_CONFLICT", "所选来源绑定了不同目标频道蒸馏要求，不能跨账号混用。")
        locked_distillation_id = next(iter(inferred_distillations), None)
        requirement_ref = None
        required_sections: list[str] = []
        account_imitation_requirements = None
        if locked_distillation_id:
            if self.channel_distillations is None:
                raise ToolError("CHANNEL_REQUIREMENT_PROVIDER_UNAVAILABLE", "频道专属仿写要求提供器尚未接入。")
            requirement = self.channel_distillations.account_requirement(
                channel_profile_id=channel_profile_id,
                distillation_id=locked_distillation_id,
                kind="imitation",
            )
            requirement_ref = _contract_ref(requirement)
            account_imitation_requirements = requirement.get("requirements")
            if not isinstance(account_imitation_requirements, dict):
                raise ToolError("ACCOUNT_IMITATION_REQUIREMENTS_INVALID", "账号专属仿写要求结构无效。")
            required_sections = account_imitation_requirements.get("audienceRewards", [])
            if not isinstance(required_sections, list) or any(not isinstance(item, str) or not item.strip() for item in required_sections):
                raise ToolError("ACCOUNT_IMITATION_REQUIREMENTS_INVALID", "账号专属仿写要求结构无效。")

        plan = {
            "schemaVersion": ORIGINAL_IMITATION_VERSION,
            "imitationId": imitation_id,
            "channelProfileId": channel_profile_id,
            "targetChannel": _contract_ref(self.store.get_channel(channel_profile_id)["channelProfile"]),
            "references": planned,
            "sourceLocks": list(source_locks.values()),
            "weightTotal": total_weight,
            "weightsAreSegmentShares": False,
            "distillationId": locked_distillation_id,
            "accountRequirement": requirement_ref,
            "accountImitationRequirements": account_imitation_requirements,
            "requiredSections": required_sections,
            "directionCount": 8,
            "topCount": 3,
            "boundaries": self.capabilities()["boundaries"],
        }
        request_hash = _json_hash(plan)
        root = self._root(channel_profile_id, imitation_id)
        if self._state_path(channel_profile_id, imitation_id).is_file():
            state = self._load_state(channel_profile_id, imitation_id)
            if state.get("requestHash") != request_hash:
                raise ToolError("IMITATION_ID_CONFLICT", "同一 imitationId 已绑定不同来源或权重。")
            return {"state": state, "plan": plan, "idempotent": True}
        root.mkdir(parents=True, exist_ok=False)
        _atomic_json(root / "plan.json", plan)
        created = utc_now()
        state = {
            "schemaVersion": ORIGINAL_IMITATION_VERSION,
            "imitationId": imitation_id,
            "channelProfileId": channel_profile_id,
            "state": "SOURCE_ANALYSIS_READY",
            "createdAt": created,
            "updatedAt": created,
            "requestHash": request_hash,
            "sourceAnalyses": {},
            "directions": [],
            "outputs": {},
        }
        self._save_state(state)
        direct_count = sum(item["inputKind"] == "canonical-source" for item in planned)
        return {
            "state": state,
            "plan": plan,
            "idempotent": False,
            "confirmationCard": {
                "references": len(planned),
                "directSourcesToAnalyze": direct_count,
                "weightTotal": total_weight,
                "weightsAreSegmentShares": False,
                "accountSpecificRequirements": bool(requirement_ref),
                "directionCount": 8,
                "topCount": 3,
                "fullOutlineOrManuscriptGenerated": False,
                "next": "analyze direct canonical sources, then checkpoint eight original directions",
            },
        }

    def read_source(
        self,
        *,
        task_id: Any,
        channel_profile_id: Any,
        binding_proof: Any,
        imitation_id: Any,
        source_package_id: Any,
        start_paragraph: Any = 1,
        max_paragraphs: Any = 60,
    ) -> dict[str, Any]:
        self.store.assert_binding(task_id=task_id, channel_profile_id=channel_profile_id, binding_proof=binding_proof)
        channel_profile_id = _safe_identifier(channel_profile_id, "channelProfileId", maximum=160)
        imitation_id = _safe_identifier(imitation_id, "imitationId")
        source_package_id = _safe_identifier(source_package_id, "sourcePackageId")
        self._load_state(channel_profile_id, imitation_id)
        plan = _read_json(self._root(channel_profile_id, imitation_id) / "plan.json", "IMITATION_PLAN_INVALID")
        planned = next(
            (item for item in plan["references"] if item.get("sourcePackageId") == source_package_id),
            None,
        )
        if planned is None:
            raise ToolError("IMITATION_SOURCE_NOT_PLANNED", "该规范化资料不属于本次原创仿写计划。")
        if not isinstance(start_paragraph, int) or isinstance(start_paragraph, bool) or start_paragraph < 1:
            raise ToolError("PARAGRAPH_RANGE_INVALID", "startParagraph 必须是从 1 开始的整数。")
        if not isinstance(max_paragraphs, int) or isinstance(max_paragraphs, bool) or not 1 <= max_paragraphs <= 100:
            raise ToolError("PARAGRAPH_RANGE_INVALID", "maxParagraphs 必须在 1–100 之间。")
        source = self._canonical_source(channel_profile_id, source_package_id)
        if source["manifest"]["contentHash"] != planned["sourcePackage"]["targetHash"]:
            raise ToolError("IMITATION_SOURCE_VERSION_CHANGED", "规范化资料版本已变化，必须重新准备原创仿写任务。")
        content_path = self._asset_path(channel_profile_id, source["detail"], source["contentAsset"])
        text = content_path.read_text(encoding="utf-8")
        paragraphs = [item.strip() for item in re.split(r"\r?\n\s*\r?\n", text) if item.strip()]
        start_index = start_paragraph - 1
        selected = paragraphs[start_index : start_index + max_paragraphs]
        rows = [
            {"paragraphId": f"p{offset:04d}", "text": paragraph}
            for offset, paragraph in enumerate(selected, start=start_paragraph)
        ]
        next_paragraph = start_paragraph + len(rows)
        return {
            "imitationId": imitation_id,
            "sourcePackageId": source_package_id,
            "sourcePackageHash": planned["sourcePackage"]["targetHash"],
            "canonicalAsset": "content.txt",
            "paragraphs": rows,
            "totalParagraphs": len(paragraphs),
            "nextParagraph": next_paragraph if next_paragraph <= len(paragraphs) else None,
            "complete": next_paragraph > len(paragraphs),
        }

    @staticmethod
    def _quality(value: Any, required: set[str], code: str) -> dict[str, Any]:
        if not isinstance(value, dict) or value.get("passed") is not True:
            raise ToolError(code, "质量门必须明确通过。")
        missing = sorted(required - set(value))
        if missing or any(value.get(key) is not True for key in required):
            raise ToolError(code, "质量硬项未全部通过。", details={"missing": missing})
        if value.get("hardFailures") not in (None, []):
            raise ToolError(code, "存在硬失败时不能冻结。")
        return json.loads(json.dumps(value, ensure_ascii=False))

    def source_checkpoint(
        self,
        *,
        task_id: Any,
        channel_profile_id: Any,
        binding_proof: Any,
        imitation_id: Any,
        source_package_id: Any,
        analysis: Any,
    ) -> dict[str, Any]:
        self.store.assert_binding(task_id=task_id, channel_profile_id=channel_profile_id, binding_proof=binding_proof)
        channel_profile_id = _safe_identifier(channel_profile_id, "channelProfileId", maximum=160)
        imitation_id = _safe_identifier(imitation_id, "imitationId")
        source_package_id = _safe_identifier(source_package_id, "sourcePackageId")
        state = self._load_state(channel_profile_id, imitation_id)
        if state["state"] in {"AWAITING_USER_CONFIRMATION", "FROZEN"}:
            raise ToolError("IMITATION_STAGE_FROZEN", "方向评选后不能改写来源分析。")
        plan = _read_json(self._root(channel_profile_id, imitation_id) / "plan.json", "IMITATION_PLAN_INVALID")
        planned = next((item for item in plan["references"] if item.get("sourcePackageId") == source_package_id), None)
        if planned is None:
            raise ToolError("IMITATION_SOURCE_NOT_PLANNED", "该规范化资料不属于本次原创仿写计划。")
        if not isinstance(analysis, dict):
            raise ToolError("IMITATION_SOURCE_ANALYSIS_REQUIRED", "规范化资料必须提交完整功能分析。")
        buckets = _validate_analysis_buckets(analysis.get("analysisBuckets"), source_package_id=source_package_id)
        dimensions = _validate_dimensions(
            analysis.get("dimensions"),
            SOURCE_DIMENSIONS,
            "IMITATION_SOURCE_DIMENSIONS_INCOMPLETE",
        )
        quality = self._quality(analysis.get("qualityChecks"), SOURCE_QUALITY_KEYS, "IMITATION_SOURCE_QUALITY_FAILED")
        input_hash = _json_hash(analysis)
        root = self._root(channel_profile_id, imitation_id)
        path = root / "source-analyses" / f"{source_package_id}.json"
        if path.is_file():
            existing = _read_json(path, "IMITATION_SOURCE_ANALYSIS_INVALID")
            if existing.get("checkpointInputHash") == input_hash:
                return {"analysis": existing, "state": state, "idempotent": True}
            raise ToolError("IMITATION_SOURCE_CHECKPOINT_CONFLICT", "同一资料已保存不同分析，不会静默覆盖。")
        contract = with_hash(
            {
                "schemaVersion": CONTENT_ANALYSIS_VERSION,
                "contractType": "imitation-source-analysis-v1",
                "id": _derived_id("imitation_source", imitation_id, source_package_id),
                "version": "1.0.0",
                "createdAt": utc_now(),
                "hashAlgorithm": "SHA-256",
                "hashRule": "canonical-json-v1",
                "upstream": [planned["sourcePackage"]],
                "imitationId": imitation_id,
                "targetChannelProfileId": channel_profile_id,
                "sourcePackageId": source_package_id,
                "sourcePackageHash": planned["sourcePackage"]["targetHash"],
                "role": planned["role"],
                "weight": planned["weight"],
                "checkpointInputHash": input_hash,
                "analysisBuckets": buckets,
                "dimensions": dimensions,
                "qualityGate": quality,
                "status": "FROZEN",
            }
        )
        _atomic_json(path, contract)
        state["sourceAnalyses"][source_package_id] = {
            "path": path.relative_to(root).as_posix(),
            "contentHash": contract["contentHash"],
        }
        direct_total = sum(item["inputKind"] == "canonical-source" for item in plan["references"])
        if len(state["sourceAnalyses"]) == direct_total:
            state["state"] = "DIRECTION_GENERATION_READY"
        self._save_state(state)
        return {"analysis": contract, "state": state, "idempotent": False}

    @staticmethod
    def _validate_string_list(value: Any, field: str, *, minimum: int = 1) -> list[str]:
        if not isinstance(value, list) or len(value) < minimum or any(not isinstance(item, str) or not item.strip() for item in value):
            raise ToolError("IMITATION_DIRECTION_INCOMPLETE", f"{field} 必须是非空字符串数组。")
        return [item.strip() for item in value]

    @staticmethod
    def _available_methods(plan: dict[str, Any], root: Path) -> dict[str, set[str]]:
        result: dict[str, set[str]] = {}
        for reference in plan["references"]:
            source_key = reference["sourceKey"]
            if reference["inputKind"] == "video-analysis":
                result[source_key] = set()
            else:
                path = root / "source-analyses" / f"{reference['sourcePackageId']}.json"
                analysis = _read_json(path, "IMITATION_SOURCE_ANALYSIS_INVALID")
                result[source_key] = {
                    item["methodId"] for item in analysis["analysisBuckets"]["transferableMethods"]
                }
        return result

    def _video_methods(self, channel_profile_id: str, plan: dict[str, Any], available: dict[str, set[str]]) -> None:
        for reference in plan["references"]:
            if reference["inputKind"] != "video-analysis":
                continue
            package = self.video_analyses.analysis_package(
                channel_profile_id=channel_profile_id,
                deconstruction_id=reference["deconstructionId"],
            )
            if package["contentHash"] != reference["analysisPackage"]["targetHash"]:
                raise ToolError("IMITATION_VIDEO_ANALYSIS_VERSION_CHANGED", "视频拆解包版本已变化。")
            selected = next(
                (
                    analysis
                    for analysis in package.get("videoAnalyses", [])
                    if analysis.get("sourcePackageId") == reference.get("sourcePackageId")
                ),
                None,
            )
            if selected is None or selected.get("contentHash") != reference["videoAnalysis"]["targetHash"]:
                raise ToolError("IMITATION_VIDEO_ANALYSIS_VERSION_CHANGED", "逐视频拆解版本已变化。")
            available[reference["sourceKey"]] = {
                item["methodId"] for item in selected["analysisBuckets"]["transferableMethods"]
            }

    def _validate_direction(self, value: Any, plan: dict[str, Any], root: Path) -> dict[str, Any]:
        if not isinstance(value, dict):
            raise ToolError("IMITATION_DIRECTION_INVALID", "原创方向必须是对象。")
        for field in (
            "directionId",
            "provisionalTitle",
            "oneSentenceHook",
            "protagonist",
            "coreGoal",
            "coreConflict",
            "storyEngine",
            "audiencePsychologicalReward",
            "emotionalRoute",
            "channelFitReason",
            "serializationPotential",
            "productionDifficulty",
            "unifiedCausalEngine",
        ):
            _nonempty(value.get(field), field)
        _safe_identifier(value["directionId"], "directionId")
        value["substantiveDifferences"] = self._validate_string_list(value.get("substantiveDifferences"), "substantiveDifferences", minimum=3)
        if not isinstance(value.get("logicRisks"), list):
            raise ToolError("IMITATION_DIRECTION_INCOMPLETE", "logicRisks 必须是数组。")
        value["charactersAndRelations"] = self._validate_string_list(value.get("charactersAndRelations"), "charactersAndRelations")
        value["worldRules"] = self._validate_string_list(value.get("worldRules"), "worldRules")

        learning = value.get("learningPlan")
        if not isinstance(learning, dict) or set(learning) != LEARNING_KEYS or any(item in (None, "", [], {}) for item in learning.values()):
            raise ToolError("IMITATION_LEARNING_SCOPE_INVALID", "学习计划必须且只能覆盖题材功能、结构、节奏、表达方式和观众回报。")

        expected_sources = {item["sourceKey"]: item for item in plan["references"]}
        contributions = value.get("sourceContributions")
        if not isinstance(contributions, list) or len(contributions) != len(expected_sources):
            raise ToolError("IMITATION_SOURCE_CONTRIBUTIONS_INCOMPLETE", "每个来源都必须逐项记录角色、权重和迁移功能。")
        available = self._available_methods(plan, root)
        self._video_methods(plan["channelProfileId"], plan, available)
        seen_sources: set[str] = set()
        for item in contributions:
            if not isinstance(item, dict) or item.get("sourceKey") not in expected_sources or item["sourceKey"] in seen_sources:
                raise ToolError("IMITATION_SOURCE_CONTRIBUTION_INVALID", "来源贡献缺失、重复或不属于冻结计划。")
            planned = expected_sources[item["sourceKey"]]
            if item.get("role") != planned["role"] or item.get("weight") != planned["weight"]:
                raise ToolError("IMITATION_SOURCE_WEIGHT_MISMATCH", "方向中的来源角色和权重必须与冻结计划一致。")
            method_ids = item.get("transferableFunctionIds")
            if not isinstance(method_ids, list) or not method_ids or not set(method_ids).issubset(available[item["sourceKey"]]):
                raise ToolError("IMITATION_SOURCE_METHOD_INVALID", "每个来源贡献必须引用该来源真实存在的可迁移方法。")
            _nonempty(item.get("newImplementation"), "sourceContributions.newImplementation")
            if item.get("segmentShare") not in (None, False, 0):
                raise ToolError("IMITATION_SEGMENT_SHARE_FORBIDDEN", "来源权重不是开头／中段／结尾的片段占比。")
            seen_sources.add(item["sourceKey"])
        if seen_sources != set(expected_sources):
            raise ToolError("IMITATION_SOURCE_CONTRIBUTIONS_INCOMPLETE", "来源贡献未覆盖全部冻结来源。")

        table = value.get("functionalIsomorphism")
        if not isinstance(table, list) or len(table) < len(expected_sources):
            raise ToolError("FUNCTIONAL_ISOMORPHISM_REQUIRED", "大纲前必须建立覆盖全部来源的功能同构替换表。")
        table_sources: set[str] = set()
        length_total = 0.0
        for row in table:
            if not isinstance(row, dict) or row.get("sourceKey") not in expected_sources:
                raise ToolError("FUNCTIONAL_ISOMORPHISM_INVALID", "功能同构表引用了未冻结来源。")
            for field in (
                "nodeId",
                "sourceFunctionId",
                "sourceFunction",
                "sourceImplementationSummary",
                "newImplementation",
                "newCausality",
                "emotionPosition",
            ):
                _nonempty(row.get(field), f"functionalIsomorphism.{field}")
            if row["sourceFunctionId"] not in available[row["sourceKey"]]:
                raise ToolError("FUNCTIONAL_ISOMORPHISM_METHOD_INVALID", "功能同构表必须引用来源已有可迁移方法。")
            if row.get("sameEventSequence") is not False:
                raise ToolError("FUNCTIONAL_ISOMORPHISM_COPY_FORBIDDEN", "新实现必须形成完整的新因果链，不能沿用原事件顺序。")
            share = row.get("lengthShare")
            if not isinstance(share, (int, float)) or isinstance(share, bool) or share <= 0:
                raise ToolError("FUNCTIONAL_ISOMORPHISM_SHARE_INVALID", "功能节点必须有大于 0 的新稿篇幅占比。")
            length_total += float(share)
            table_sources.add(row["sourceKey"])
        if table_sources != set(expected_sources) or abs(length_total - 100) > 1e-9:
            raise ToolError("FUNCTIONAL_ISOMORPHISM_COVERAGE_INVALID", "功能同构表必须覆盖全部来源，且新稿节点篇幅占比合计为 100。")

        audit = value.get("credibilityAudit")
        if not isinstance(audit, list) or len(audit) != 10:
            raise ToolError("CREDIBILITY_AUDIT_INCOMPLETE", "每个方向必须回答完整 10 项可信度审查。")
        audit_rows: dict[str, dict[str, Any]] = {}
        for row in audit:
            if not isinstance(row, dict) or row.get("questionId") in audit_rows:
                raise ToolError("CREDIBILITY_AUDIT_INVALID", "可信度审查题号缺失或重复。")
            question_id = row.get("questionId")
            if question_id not in CREDIBILITY_QUESTION_IDS or not isinstance(row.get("passed"), bool):
                raise ToolError("CREDIBILITY_AUDIT_INVALID", "可信度审查必须逐题给出 passed。")
            _nonempty(row.get("answer"), "credibilityAudit.answer")
            _nonempty(row.get("evidence"), "credibilityAudit.evidence")
            audit_rows[question_id] = row
        if tuple(sorted(audit_rows, key=lambda item: int(item[1:]))) != CREDIBILITY_QUESTION_IDS:
            raise ToolError("CREDIBILITY_AUDIT_INCOMPLETE", "可信度审查必须覆盖 q1–q10。")

        for field, required_keys in (
            ("scaleControl", {"issueScale", "identityCapacity", "resources", "authority", "rationalActorBarrier", "passed"}),
            ("oppositionLogic", {"ownGoal", "interest", "knownInformation", "reasoningBasis", "constraints", "understandableWrongDecision", "passed"}),
            ("protagonistCapability", {"source", "scope", "limit", "cost", "growth", "passed"}),
        ):
            section = value.get(field)
            if not isinstance(section, dict) or set(section) != required_keys or any(section.get(key) in (None, "", [], {}) for key in required_keys - {"passed"}) or not isinstance(section.get("passed"), bool):
                raise ToolError("IMITATION_CREDIBILITY_SECTION_INVALID", f"{field} 结构不完整。")

        process = value.get("resultProcess")
        if not isinstance(process, list) or len(process) != len(RESULT_STAGE_IDS):
            raise ToolError("IMITATION_RESULT_PROCESS_INVALID", "结果过程必须依次覆盖验证、稳定、扩展、新问题、调整、再次扩展。")
        if tuple(row.get("stageId") for row in process if isinstance(row, dict)) != RESULT_STAGE_IDS:
            raise ToolError("IMITATION_RESULT_PROCESS_INVALID", "结果过程顺序无效。")
        if any(not isinstance(row.get("action"), str) or not row["action"].strip() or not isinstance(row.get("stateChange"), str) or not row["stateChange"].strip() for row in process):
            raise ToolError("IMITATION_RESULT_PROCESS_INVALID", "每个结果阶段都必须说明行动和状态变化。")

        anti_copy = value.get("antiCopyAudit")
        if anti_copy != ANTI_COPY_EXPECTED:
            raise ToolError("IMITATION_COPY_BOUNDARY_FAILED", "方向不得复制原句、专名、完整事件顺序、单一作品主线或按片段拼接。")
        disqualifiers = value.get("disqualifiers")
        if not isinstance(disqualifiers, list) or any(not isinstance(item, str) or not item.strip() for item in disqualifiers):
            raise ToolError("IMITATION_DISQUALIFIERS_INVALID", "disqualifiers 必须是字符串数组。")
        scores = value.get("scores")
        if not isinstance(scores, dict) or set(scores) != SCORE_KEYS:
            raise ToolError("IMITATION_SCORES_INVALID", "方向必须提供完整 13 项评分且不能出现额外字段。")
        if any(not isinstance(scores[key], (int, float)) or isinstance(scores[key], bool) or not 0 <= scores[key] <= 10 for key in SCORE_KEYS):
            raise ToolError("IMITATION_SCORES_INVALID", "13 项评分必须都在 0–10 之间。")
        account_coverage = value.get("accountRequirementCoverage")
        required_sections = plan.get("requiredSections", [])
        if required_sections:
            if not isinstance(account_coverage, list) or len(account_coverage) != len(required_sections):
                raise ToolError("ACCOUNT_IMITATION_COVERAGE_REQUIRED", "每个方向必须逐项覆盖账号专属仿写要求。")
            coverage = {item.get("requirement"): item for item in account_coverage if isinstance(item, dict)}
            if set(coverage) != set(required_sections) or any(item.get("status") != "COVERED" or not item.get("implementation") for item in coverage.values()):
                raise ToolError("ACCOUNT_IMITATION_COVERAGE_INVALID", "账号专属仿写要求必须逐字对应并说明新实现。")
        elif account_coverage not in (None, []):
            raise ToolError("ACCOUNT_IMITATION_COVERAGE_INVALID", "未绑定账号专属要求时不得伪造覆盖记录。")

        audit_passed = all(row["passed"] for row in audit)
        credibility_sections_passed = all(value[field]["passed"] for field in ("scaleControl", "oppositionLogic", "protagonistCapability"))
        core_scores_passed = all(scores[key] >= 8 for key in CORE_SCORE_KEYS)
        eligible = audit_passed and credibility_sections_passed and core_scores_passed and not disqualifiers
        positive_scores = [scores[key] for key in SCORE_KEYS if key != "productionDifficulty"]
        composite = round((sum(positive_scores) + (10 - scores["productionDifficulty"])) / len(SCORE_KEYS), 4)
        result = json.loads(json.dumps(value, ensure_ascii=False))
        result["eligibility"] = {
            "eligible": eligible,
            "coreScoresPassed": core_scores_passed,
            "credibilityAuditPassed": audit_passed,
            "credibilitySectionsPassed": credibility_sections_passed,
            "disqualifiers": list(disqualifiers),
            "compositeScore": composite,
        }
        return result

    def direction_checkpoint(
        self,
        *,
        task_id: Any,
        channel_profile_id: Any,
        binding_proof: Any,
        imitation_id: Any,
        direction_number: Any,
        direction: Any,
    ) -> dict[str, Any]:
        self.store.assert_binding(task_id=task_id, channel_profile_id=channel_profile_id, binding_proof=binding_proof)
        channel_profile_id = _safe_identifier(channel_profile_id, "channelProfileId", maximum=160)
        imitation_id = _safe_identifier(imitation_id, "imitationId")
        state = self._load_state(channel_profile_id, imitation_id)
        if state["state"] in {"AWAITING_USER_CONFIRMATION", "FROZEN"}:
            raise ToolError("IMITATION_DIRECTIONS_FROZEN", "8 方向评选后不能改写方向。")
        plan = _read_json(self._root(channel_profile_id, imitation_id) / "plan.json", "IMITATION_PLAN_INVALID")
        direct_total = sum(item["inputKind"] == "canonical-source" for item in plan["references"])
        if len(state["sourceAnalyses"]) != direct_total:
            raise ToolError("IMITATION_SOURCE_ANALYSIS_INCOMPLETE", "必须先完成全部直接小说／文本来源的功能分析。")
        expected = len(state["directions"]) + 1
        if direction_number != expected or not 1 <= expected <= 8:
            raise ToolError("IMITATION_DIRECTION_SEQUENCE_INVALID", "8 个方向必须按 1–8 依次保存。", details={"expected": expected})
        root = self._root(channel_profile_id, imitation_id)
        normalized = self._validate_direction(direction, plan, root)
        if normalized["directionId"] in {item["directionId"] for item in state["directions"]}:
            raise ToolError("IMITATION_DIRECTION_DUPLICATE", "原创方向 ID 不能重复。")
        path = root / "directions" / f"{direction_number:02d}-{normalized['directionId']}.json"
        _atomic_json(path, normalized)
        state["directions"].append(
            {
                "number": direction_number,
                "directionId": normalized["directionId"],
                "path": path.relative_to(root).as_posix(),
                "contentHash": _json_hash(normalized),
                "eligible": normalized["eligibility"]["eligible"],
                "compositeScore": normalized["eligibility"]["compositeScore"],
            }
        )
        state["state"] = "DIRECTIONS_COMPLETE" if direction_number == 8 else "GENERATING_DIRECTIONS"
        self._save_state(state)
        return {
            "direction": normalized,
            "state": state,
            "progress": f"direction {direction_number}/8",
            "eligible": normalized["eligibility"]["eligible"],
        }

    @staticmethod
    def _validate_pairwise(value: Any, direction_ids: set[str]) -> list[dict[str, Any]]:
        expected_pairs = len(direction_ids) * (len(direction_ids) - 1) // 2
        if not isinstance(value, list) or len(value) != expected_pairs:
            raise ToolError("IMITATION_DISTINCTNESS_INCOMPLETE", "8 个方向必须提交完整 28 组两两差异检查。")
        seen: set[tuple[str, str]] = set()
        result: list[dict[str, Any]] = []
        for row in value:
            if not isinstance(row, dict):
                raise ToolError("IMITATION_DISTINCTNESS_INVALID", "两两差异记录必须是对象。")
            left, right = row.get("directionA"), row.get("directionB")
            if left not in direction_ids or right not in direction_ids or left == right:
                raise ToolError("IMITATION_DISTINCTNESS_INVALID", "两两差异引用了不存在或相同的方向。")
            pair = tuple(sorted((left, right)))
            if pair in seen:
                raise ToolError("IMITATION_DISTINCTNESS_INVALID", "两两差异组合重复。")
            categories = row.get("differenceCategories")
            if (
                not isinstance(categories, list)
                or len(set(categories)) < 3
                or not set(categories).issubset(DISTINCTNESS_CATEGORIES)
                or not set(categories).intersection(MAJOR_DISTINCTNESS_CATEGORIES)
                or row.get("cosmeticOnly") is not False
                or row.get("substantiallyDifferent") is not True
                or not isinstance(row.get("explanation"), str)
                or not row["explanation"].strip()
            ):
                raise ToolError("IMITATION_DISTINCTNESS_FAILED", "方向差异不能只换职业、地点或数值，且至少覆盖三个实质维度。")
            seen.add(pair)
            result.append(json.loads(json.dumps(row, ensure_ascii=False)))
        if len(seen) != expected_pairs:
            raise ToolError("IMITATION_DISTINCTNESS_INCOMPLETE", "两两差异检查未覆盖全部组合。")
        return result

    def directions_finalize(
        self,
        *,
        task_id: Any,
        channel_profile_id: Any,
        binding_proof: Any,
        imitation_id: Any,
        pairwise_distinctness: Any,
        quality_gate: Any,
    ) -> dict[str, Any]:
        self.store.assert_binding(task_id=task_id, channel_profile_id=channel_profile_id, binding_proof=binding_proof)
        channel_profile_id = _safe_identifier(channel_profile_id, "channelProfileId", maximum=160)
        imitation_id = _safe_identifier(imitation_id, "imitationId")
        state = self._load_state(channel_profile_id, imitation_id)
        if state["state"] == "FROZEN":
            return self.get(channel_profile_id=channel_profile_id, imitation_id=imitation_id)
        if state["state"] == "AWAITING_USER_CONFIRMATION":
            root = self._root(channel_profile_id, imitation_id)
            return {"state": state, "selectionCard": _read_json(root / state["outputs"]["selectionCard"]["path"], "IMITATION_SELECTION_CARD_INVALID"), "idempotent": True}
        if len(state["directions"]) != 8:
            raise ToolError("IMITATION_DIRECTIONS_INCOMPLETE", "必须先保存恰好 8 个原创方向。")
        root = self._root(channel_profile_id, imitation_id)
        directions = [_read_json(root / item["path"], "IMITATION_DIRECTION_INVALID") for item in state["directions"]]
        direction_ids = {item["directionId"] for item in directions}
        pairwise = self._validate_pairwise(pairwise_distinctness, direction_ids)
        quality = self._quality(quality_gate, DIRECTION_FINAL_QUALITY_KEYS, "IMITATION_DIRECTIONS_QUALITY_FAILED")
        eligible = [item for item in directions if item["eligibility"]["eligible"]]
        if len(eligible) < 3:
            raise ToolError("IMITATION_TOP3_INSUFFICIENT", "至少需要 3 个通过可信度与核心评分硬门的原创方向。", details={"eligible": len(eligible)})
        ranking = sorted(
            directions,
            key=lambda item: (
                not item["eligibility"]["eligible"],
                -item["eligibility"]["compositeScore"],
                next(row["number"] for row in state["directions"] if row["directionId"] == item["directionId"]),
            ),
        )
        top3 = [item["directionId"] for item in ranking if item["eligibility"]["eligible"]][:3]
        created = utc_now()
        selection_card = {
            "schemaVersion": ORIGINAL_IMITATION_VERSION,
            "imitationId": imitation_id,
            "targetChannelProfileId": channel_profile_id,
            "createdAt": created,
            "directions": directions,
            "ranking": [
                {
                    "rank": index,
                    "directionId": item["directionId"],
                    "eligible": item["eligibility"]["eligible"],
                    "compositeScore": item["eligibility"]["compositeScore"],
                    "scores": item["scores"],
                }
                for index, item in enumerate(ranking, 1)
            ],
            "top3": top3,
            "pairwiseDistinctness": pairwise,
            "qualityGate": quality,
            "manualConfirmationRequired": True,
            "autoSelectionAllowed": False,
            "fullOutlineOrManuscriptGenerated": False,
            "status": "AWAITING_USER_CONFIRMATION",
        }
        path = root / "direction-selection-card-v1.json"
        _atomic_json(path, selection_card)
        state["outputs"] = {
            "selectionCard": {"path": path.relative_to(root).as_posix(), "contentHash": _json_hash(selection_card)},
            "top3": top3,
        }
        state["state"] = "AWAITING_USER_CONFIRMATION"
        self._save_state(state)
        return {
            "state": state,
            "selectionCard": selection_card,
            "confirmationCard": {
                "allEightDisplayed": True,
                "top3": top3,
                "eligibleCount": len(eligible),
                "manualConfirmationRequired": True,
                "next": "wait for the user to confirm one eligible direction before freezing the writing contract",
            },
        }

    def confirm(
        self,
        *,
        task_id: Any,
        channel_profile_id: Any,
        binding_proof: Any,
        imitation_id: Any,
        direction_id: Any,
        confirmation: Any,
    ) -> dict[str, Any]:
        self.store.assert_binding(task_id=task_id, channel_profile_id=channel_profile_id, binding_proof=binding_proof)
        channel_profile_id = _safe_identifier(channel_profile_id, "channelProfileId", maximum=160)
        imitation_id = _safe_identifier(imitation_id, "imitationId")
        direction_id = _safe_identifier(direction_id, "directionId")
        state = self._load_state(channel_profile_id, imitation_id)
        if state["state"] == "FROZEN":
            contract = self.writing_contract(channel_profile_id=channel_profile_id, imitation_id=imitation_id)
            if contract["selectedDirection"]["directionId"] != direction_id:
                raise ToolError("IMITATION_CONFIRMATION_CONFLICT", "已冻结契约选择了不同方向。")
            return {"state": state, "writingStyleContract": contract, "idempotent": True}
        if state["state"] != "AWAITING_USER_CONFIRMATION":
            raise ToolError("IMITATION_SELECTION_NOT_READY", "必须先完成并展示 8 个方向及 TOP3。")
        if (
            not isinstance(confirmation, dict)
            or confirmation.get("confirmed") is not True
            or confirmation.get("mode") != "review"
            or confirmation.get("confirmedBy") != "user"
        ):
            raise ToolError("IMITATION_USER_CONFIRMATION_REQUIRED", "原创方向不能自动选择，必须由用户明确确认。")
        root = self._root(channel_profile_id, imitation_id)
        plan = _read_json(root / "plan.json", "IMITATION_PLAN_INVALID")
        selection_card = _read_json(root / state["outputs"]["selectionCard"]["path"], "IMITATION_SELECTION_CARD_INVALID")
        selected = next((item for item in selection_card["directions"] if item["directionId"] == direction_id), None)
        if selected is None or selected["eligibility"]["eligible"] is not True:
            raise ToolError("IMITATION_DIRECTION_NOT_ELIGIBLE", "只能确认通过全部硬门的原创方向。")
        created = utc_now()
        upstream = [plan["targetChannel"]]
        upstream.extend(
            reference["analysisPackage"] if reference["inputKind"] == "video-analysis" else reference["sourcePackage"]
            for reference in plan["references"]
        )
        if plan.get("accountRequirement"):
            upstream.append(plan["accountRequirement"])
        contract = with_hash(
            {
                "schemaVersion": ORIGINAL_IMITATION_VERSION,
                "contractType": "writing-style-contract-v1",
                "id": _derived_id("writing_style", imitation_id),
                "version": "1.0.0",
                "createdAt": created,
                "hashAlgorithm": "SHA-256",
                "hashRule": "canonical-json-v1",
                "upstream": upstream,
                "imitationId": imitation_id,
                "targetChannelProfileId": channel_profile_id,
                "distillationId": plan.get("distillationId"),
                "accountRequirement": plan.get("accountRequirement"),
                "accountImitationRequirements": plan.get("accountImitationRequirements"),
                "sources": plan["references"],
                "sourceLocks": plan["sourceLocks"],
                "sourceWeightsTotal": 100,
                "weightsAreSegmentShares": False,
                "selectedDirection": selected,
                "selectionSummary": {
                    "allDirectionIds": [item["directionId"] for item in selection_card["directions"]],
                    "ranking": selection_card["ranking"],
                    "top3": selection_card["top3"],
                    "selectedFromTop3": direction_id in selection_card["top3"],
                },
                "allowedLearning": {
                    "topicFunction": selected["learningPlan"]["topicFunction"],
                    "structure": selected["learningPlan"]["structure"],
                    "rhythm": selected["learningPlan"]["rhythm"],
                    "expression": selected["learningPlan"]["expression"],
                    "audiencePayoff": selected["learningPlan"]["audiencePayoff"],
                },
                "mustRebuild": [
                    "protagonist-and-pov",
                    "goals-and-motivations",
                    "character-relationships",
                    "world-rules-and-constraints",
                    "unified-story-engine",
                    "complete-causality",
                    "climax-and-ending",
                    "title-wording-and-thumbnail-composition",
                ],
                "prohibitedCopy": [
                    "original-sentences",
                    "proper-names",
                    "complete-event-order",
                    "single-work-mainline",
                    "opening-middle-ending-segment-splice",
                    "signature-lines-or-unique-expressions",
                ],
                "unifiedCausalEngine": selected["unifiedCausalEngine"],
                "functionalIsomorphism": selected["functionalIsomorphism"],
                "credibilityGuardrails": {
                    "audit": selected["credibilityAudit"],
                    "scaleControl": selected["scaleControl"],
                    "oppositionLogic": selected["oppositionLogic"],
                    "protagonistCapability": selected["protagonistCapability"],
                    "resultProcess": selected["resultProcess"],
                    "coreScoreMinimum": 8,
                },
                "antiCopyAudit": selected["antiCopyAudit"],
                "userConfirmation": {
                    "confirmed": True,
                    "confirmedBy": "user",
                    "confirmedAt": confirmation.get("confirmedAt") or created,
                    "mode": "review",
                },
                "downstreamViews": {
                    "topicCenter": {
                        "selectedDirectionId": direction_id,
                        "storyEngine": selected["storyEngine"],
                        "coreGoal": selected["coreGoal"],
                        "coreConflict": selected["coreConflict"],
                        "worldRules": selected["worldRules"],
                        "charactersAndRelations": selected["charactersAndRelations"],
                        "audiencePsychologicalReward": selected["audiencePsychologicalReward"],
                        "functionalIsomorphism": selected["functionalIsomorphism"],
                    },
                    "manuscriptCenter": {
                        "selectedDirectionId": direction_id,
                        "structure": selected["learningPlan"]["structure"],
                        "rhythm": selected["learningPlan"]["rhythm"],
                        "expression": selected["learningPlan"]["expression"],
                        "emotionalRoute": selected["emotionalRoute"],
                        "audiencePayoff": selected["learningPlan"]["audiencePayoff"],
                        "antiCopyAudit": selected["antiCopyAudit"],
                    },
                },
                "status": "FROZEN",
            }
        )
        self._validate_contract_schema(contract, "writing-style-contract-v1.schema.json")
        path = root / "writing-style-contract-v1.json"
        _atomic_json(path, contract)
        state["outputs"]["writingStyleContract"] = {
            **_contract_ref(contract),
            "path": path.relative_to(root).as_posix(),
        }
        state["state"] = "FROZEN"
        self._save_state(state)
        return {
            "state": state,
            "writingStyleContract": contract,
            "completionCard": {
                "selectedDirectionId": direction_id,
                "selectedFromTop3": direction_id in selection_card["top3"],
                "writingStyleContract": "FROZEN",
                "handoffReady": ["topic-center", "manuscript-center"],
                "fullOutlineOrManuscriptGenerated": False,
                "next": "start one imitation content project and expand the confirmed direction through existing topic and manuscript gates",
            },
        }

    def get(self, *, channel_profile_id: Any, imitation_id: Any) -> dict[str, Any]:
        channel_profile_id = _safe_identifier(channel_profile_id, "channelProfileId", maximum=160)
        imitation_id = _safe_identifier(imitation_id, "imitationId")
        state = self._load_state(channel_profile_id, imitation_id)
        root = self._root(channel_profile_id, imitation_id)
        return {
            "state": state,
            "plan": _read_json(root / "plan.json", "IMITATION_PLAN_INVALID"),
            "outputs": state.get("outputs", {}),
            "progressReadOnly": True,
        }

    def writing_contract(self, *, channel_profile_id: Any, imitation_id: Any) -> dict[str, Any]:
        state = self._load_state(channel_profile_id, imitation_id)
        if state.get("state") != "FROZEN":
            raise ToolError("IMITATION_NOT_FROZEN", "原创仿写方向尚未由用户确认并冻结。")
        path = self._root(channel_profile_id, imitation_id) / state["outputs"]["writingStyleContract"]["path"]
        contract = _read_json(path, "WRITING_STYLE_CONTRACT_INVALID")
        if canonical_hash(contract) != contract.get("contentHash"):
            raise ToolError("WRITING_STYLE_CONTRACT_HASH_MISMATCH", "Writing Style Contract 哈希无效。")
        return contract

    def integrity_check(self, *, channel_profile_id: Any, imitation_id: Any) -> dict[str, Any]:
        channel_profile_id = _safe_identifier(channel_profile_id, "channelProfileId", maximum=160)
        imitation_id = _safe_identifier(imitation_id, "imitationId")
        state = self._load_state(channel_profile_id, imitation_id)
        root = self._root(channel_profile_id, imitation_id)
        plan = _read_json(root / "plan.json", "IMITATION_PLAN_INVALID")
        errors: list[dict[str, Any]] = []
        for lock in plan["sourceLocks"]:
            try:
                manifest = self.sources.get_source(
                    channel_profile_id=channel_profile_id,
                    source_package_id=lock["sourcePackageId"],
                )["manifest"]
                if manifest.get("contentHash") != lock["contentHash"] or canonical_hash(manifest) != manifest.get("contentHash"):
                    errors.append({"sourcePackageId": lock["sourcePackageId"], "issue": "source-version"})
            except ToolError as exc:
                errors.append({"sourcePackageId": lock["sourcePackageId"], "issue": exc.code})
        for item in state.get("sourceAnalyses", {}).values():
            path = root / item["path"]
            contract = _read_json(path, "IMITATION_SOURCE_ANALYSIS_INVALID")
            if canonical_hash(contract) != contract.get("contentHash"):
                errors.append({"path": item["path"], "issue": "content-hash"})
        for item in state.get("directions", []):
            path = root / item["path"]
            if not path.is_file() or _json_hash(_read_json(path, "IMITATION_DIRECTION_INVALID")) != item["contentHash"]:
                errors.append({"path": item["path"], "issue": "direction-hash"})
        if state.get("state") == "FROZEN":
            try:
                contract = self.writing_contract(channel_profile_id=channel_profile_id, imitation_id=imitation_id)
                if contract.get("targetChannelProfileId") != channel_profile_id:
                    errors.append({"path": "writing-style-contract-v1.json", "issue": "target-scope"})
            except ToolError as exc:
                errors.append({"path": "writing-style-contract-v1.json", "issue": exc.code})
        if plan.get("accountRequirement"):
            try:
                requirement = self.channel_distillations.account_requirement(
                    channel_profile_id=channel_profile_id,
                    distillation_id=plan["distillationId"],
                    kind="imitation",
                )
                if requirement["contentHash"] != plan["accountRequirement"]["targetHash"]:
                    errors.append({"distillationId": plan["distillationId"], "issue": "account-requirement-version"})
            except (AttributeError, ToolError) as exc:
                errors.append({"distillationId": plan.get("distillationId"), "issue": getattr(exc, "code", "provider-unavailable")})
        return {
            "status": "PASS" if not errors else "FAIL",
            "imitationId": imitation_id,
            "state": state["state"],
            "errors": errors,
            "progressReadOnly": True,
        }


__all__ = ["ORIGINAL_IMITATION_VERSION", "OriginalImitationWriting"]
