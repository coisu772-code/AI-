from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry, Resource

from .contracts import canonical_hash, utc_now, with_hash
from .errors import ToolError


CONTENT_ANALYSIS_VERSION = "1.0.0"
DISTILLATION_MODES = {"single", "parallel", "compare", "fusion"}
SAMPLE_DIMENSIONS = {
    "storyContent",
    "functionalStructure",
    "expression",
    "openingHook",
    "title",
    "thumbnail",
    "description",
    "hashtags",
    "videoPresentation",
    "visualStyle",
    "audienceNeeds",
    "psychologicalPayoff",
    "retentionHypotheses",
    "channelVoice",
    "crossAssetAlignment",
    "lowQualityPatterns",
}
PROFILE_DIMENSIONS = {
    "channelScope",
    "contentDna",
    "expressionDna",
    "videoDna",
    "packagingDna",
    "crossAssetAlignmentDna",
    "retentionHypotheses",
    "channelVoice",
    "commonLogic",
    "novelMangaAdaptation",
}
BUCKET_KEYS = (
    "originalFacts",
    "analysisConclusions",
    "transferableMethods",
    "prohibitedCopy",
    "unknowns",
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
        json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        )
    ).hexdigest()


def _derived_id(prefix: str, *parts: str) -> str:
    raw = "_".join((prefix, *parts))
    if len(raw) <= 128:
        return raw
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]
    return f"{raw[:111]}_{digest}"


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


def _read_json(path: Path, code: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ToolError(code, "频道蒸馏状态或契约不可读。", details={"path": str(path)}) from exc
    if not isinstance(value, dict):
        raise ToolError(code, "频道蒸馏状态或契约结构无效。", details={"path": str(path)})
    return value


def _contract_ref(contract: dict[str, Any]) -> dict[str, Any]:
    return {
        "targetContractType": contract["contractType"],
        "targetId": contract["id"],
        "targetVersion": contract["version"],
        "targetSchemaVersion": contract["schemaVersion"],
        "targetHash": contract["contentHash"],
    }


def _source_ref(manifest: dict[str, Any]) -> dict[str, Any]:
    return _contract_ref(manifest)


def _validate_bucket_ids(items: list[Any], key: str, id_key: str) -> set[str]:
    identifiers: set[str] = set()
    for item in items:
        if not isinstance(item, dict):
            raise ToolError("ANALYSIS_BUCKET_INVALID", f"{key} 的每一项都必须是对象。")
        identifier = item.get(id_key)
        if not isinstance(identifier, str) or not identifier.strip() or identifier in identifiers:
            raise ToolError("ANALYSIS_BUCKET_INVALID", f"{key}.{id_key} 缺失或重复。")
        identifiers.add(identifier)
        statement = item.get("statement") or item.get("description") or item.get("method")
        if not isinstance(statement, str) or not statement.strip():
            raise ToolError("ANALYSIS_BUCKET_INVALID", f"{key} 必须包含非空陈述。")
    return identifiers


def _validate_analysis_buckets(buckets: Any, *, source_package_id: str | None = None) -> dict[str, Any]:
    if not isinstance(buckets, dict) or any(key not in buckets for key in BUCKET_KEYS):
        raise ToolError("ANALYSIS_BUCKETS_REQUIRED", "分析必须同时区分原文事实、分析结论、可迁移方法、禁止复制内容和未知项。")
    values = {key: buckets[key] for key in BUCKET_KEYS}
    if any(not isinstance(value, list) for value in values.values()):
        raise ToolError("ANALYSIS_BUCKET_INVALID", "五类分析结果必须全部是数组。")
    if any(not values[key] for key in BUCKET_KEYS):
        raise ToolError("ANALYSIS_BUCKET_EMPTY", "五类分析结果都必须显式填写；没有证据的字段写入未知项。")

    fact_ids = _validate_bucket_ids(values["originalFacts"], "originalFacts", "factId")
    conclusion_ids = _validate_bucket_ids(values["analysisConclusions"], "analysisConclusions", "conclusionId")
    _validate_bucket_ids(values["transferableMethods"], "transferableMethods", "methodId")
    _validate_bucket_ids(values["prohibitedCopy"], "prohibitedCopy", "boundaryId")
    _validate_bucket_ids(values["unknowns"], "unknowns", "unknownId")

    for fact in values["originalFacts"]:
        evidence = fact.get("evidenceRefs")
        if not isinstance(evidence, list) or not evidence:
            raise ToolError("FACT_EVIDENCE_REQUIRED", "每条原文事实必须绑定可追溯证据。")
        for reference in evidence:
            if not isinstance(reference, dict) or not isinstance(reference.get("locator"), str):
                raise ToolError("FACT_EVIDENCE_INVALID", "事实证据必须包含 locator。")
            if source_package_id and reference.get("sourcePackageId") != source_package_id:
                raise ToolError("FACT_EVIDENCE_SOURCE_MISMATCH", "单条视频事实只能引用当前视频 Source Package。")
    for conclusion in values["analysisConclusions"]:
        evidence_ids = conclusion.get("evidenceFactIds")
        if not isinstance(evidence_ids, list) or not evidence_ids or not set(evidence_ids).issubset(fact_ids):
            raise ToolError("CONCLUSION_EVIDENCE_INVALID", "分析结论必须引用本包已有的原文事实。")
        confidence = conclusion.get("confidence")
        if not isinstance(confidence, (int, float)) or isinstance(confidence, bool) or not 0 <= confidence <= 1:
            raise ToolError("CONCLUSION_CONFIDENCE_INVALID", "分析结论必须提供 0–1 置信度。")
    for method in values["transferableMethods"]:
        evidence_ids = method.get("evidenceConclusionIds")
        if not isinstance(evidence_ids, list) or not evidence_ids or not set(evidence_ids).issubset(conclusion_ids):
            raise ToolError("METHOD_EVIDENCE_INVALID", "可迁移方法必须由已有分析结论支持。")
        if not isinstance(method.get("applicationConditions"), list) or not method["applicationConditions"]:
            raise ToolError("METHOD_CONDITIONS_REQUIRED", "可迁移方法必须写明适用条件。")
    for boundary in values["prohibitedCopy"]:
        if not isinstance(boundary.get("categories"), list) or not boundary["categories"]:
            raise ToolError("COPY_BOUNDARY_INVALID", "禁止复制内容必须标明类别。")

    encoded = json.dumps(values, ensure_ascii=False)
    if any(len(match) > 240 for match in re.findall(r'"(?:quote|excerpt)"\s*:\s*"([^"]*)"', encoded)):
        raise ToolError("SOURCE_EXCERPT_TOO_LONG", "分析包只允许短证据摘录，不能复制长段原文。")
    return json.loads(json.dumps(values, ensure_ascii=False))


def _validate_dimensions(value: Any, required: set[str], code: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ToolError(code, "分析维度必须是对象。")
    missing = sorted(required - set(value))
    if missing:
        raise ToolError(code, "分析维度不完整。", details={"missing": missing})
    if any(value[key] in (None, "", [], {}) for key in required):
        raise ToolError(code, "分析维度不得以空值代替未知；未知信息必须进入 unknowns。")
    return json.loads(json.dumps(value, ensure_ascii=False))


def _nested_keys(value: Any) -> set[str]:
    keys: set[str] = set()
    if isinstance(value, dict):
        for key, nested in value.items():
            keys.add(str(key).lower().replace("_", "").replace("-", ""))
            keys.update(_nested_keys(nested))
    elif isinstance(value, list):
        for nested in value:
            keys.update(_nested_keys(nested))
    return keys


class ChannelDistillation:
    def __init__(self, store: Any, sources: Any, *, plugin_root: Path | None = None) -> None:
        self.store = store
        self.sources = sources
        self.plugin_root = plugin_root

    def _validate_contract_schema(self, contract: dict[str, Any], schema_name: str) -> None:
        if self.plugin_root is None:
            return
        schema_root = self.plugin_root.resolve().parents[1] / "contracts" / "schemas"
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
            raise ToolError("CONTENT_ANALYSIS_SCHEMA_INVALID", "内容分析契约 Schema 不可读。") from exc
        if errors:
            first = errors[0]
            location = "/".join(str(item) for item in first.absolute_path) or "<root>"
            raise ToolError(
                "CONTENT_ANALYSIS_CONTRACT_SCHEMA_FAILED",
                "内容分析契约未通过 Schema。",
                details={"schema": schema_name, "location": location, "message": first.message},
            )

    def capabilities(self) -> dict[str, Any]:
        return {
            "available": True,
            "version": CONTENT_ANALYSIS_VERSION,
            "platforms": ["youtube"],
            "modes": sorted(DISTILLATION_MODES),
            "stages": [
                "channel-identity",
                "lightweight-inventory",
                "popular-sample-selection",
                "per-video-deep-analysis",
                "cross-sample-aggregation",
                "quality-gate",
                "profile-freeze",
            ],
            "interfaces": {
                "analysis-package-v1": "available",
                "channel-distillation": "available",
                "video-analysis": "available-via-video-copy-deconstruction",
                "style-imitation": "available-via-original-imitation-writing",
                "writing-style-contract-v1": "available-via-original-imitation-writing",
            },
            "outputs": [
                "analysis-package-v1",
                "reference-channel-profile-v1",
                "channel-runtime-profile-v1",
                "account-decomposition-requirements-v1",
                "account-imitation-requirements-v1",
                "account-runtime-validation-v1",
            ],
            "boundaries": {
                "requiresCanonicalContentTxt": True,
                "rawSubtitleAcceptedByAnalysis": False,
                "studioMetricsAreFactsOnlyWhenUserSupplied": True,
                "privateMetricsInferredFromPublicData": False,
                "runtimeSkillsAreTargetChannelScoped": True,
                "globalSkillMutation": False,
            },
        }

    def _root(self, channel_profile_id: str, distillation_id: str) -> Path:
        return (
            self.store.channel_path(channel_profile_id)
            / "content-analysis"
            / "channel-distillations"
            / _safe_identifier(distillation_id, "distillationId")
        )

    def _state_path(self, channel_profile_id: str, distillation_id: str) -> Path:
        return self._root(channel_profile_id, distillation_id) / "state.json"

    def _load_state(self, channel_profile_id: str, distillation_id: str) -> dict[str, Any]:
        state = _read_json(
            self._state_path(channel_profile_id, distillation_id), "CHANNEL_DISTILLATION_NOT_FOUND"
        )
        if state.get("channelProfileId") != channel_profile_id or state.get("distillationId") != distillation_id:
            raise ToolError("CHANNEL_DISTILLATION_IDENTITY_MISMATCH", "频道蒸馏状态身份不匹配。")
        return state

    def _save_state(self, state: dict[str, Any]) -> None:
        state["updatedAt"] = utc_now()
        _atomic_json(
            self._state_path(state["channelProfileId"], state["distillationId"]), state
        )

    def _source(self, channel_profile_id: str, source_package_id: Any) -> dict[str, Any]:
        source_package_id = _safe_identifier(source_package_id, "sourcePackageId")
        detail = self.sources.get_source(
            channel_profile_id=channel_profile_id, source_package_id=source_package_id
        )
        manifest = detail["manifest"]
        if canonical_hash(manifest) != manifest.get("contentHash"):
            raise ToolError("SOURCE_HASH_MISMATCH", "Source Package 的 canonical-json-v1 哈希无效。")
        source = detail.get("source", {})
        return {
            **manifest,
            "platform": source.get("platform"),
            "platformId": source.get("platform_id"),
            "canonicalUrl": source.get("canonical_url"),
            "title": source.get("title"),
            "language": source.get("language"),
            "metadata": detail.get("metadata", {}),
        }

    @staticmethod
    def _content_asset(manifest: dict[str, Any]) -> dict[str, Any] | None:
        return next(
            (
                item
                for item in manifest.get("assets", [])
                if isinstance(item, dict)
                and "/normalized/" in f"/{str(item.get('relativePath', ''))}"
                and str(item.get("relativePath", "")).endswith("/content.txt")
            ),
            None,
        )

    def prepare(
        self,
        *,
        task_id: Any,
        channel_profile_id: Any,
        binding_proof: Any,
        distillation_id: Any,
        mode: Any,
        references: Any,
        previous_distillation_id: Any = None,
    ) -> dict[str, Any]:
        self.store.assert_binding(
            task_id=task_id,
            channel_profile_id=channel_profile_id,
            binding_proof=binding_proof,
        )
        channel_profile_id = _safe_identifier(channel_profile_id, "channelProfileId", maximum=160)
        distillation_id = _safe_identifier(distillation_id, "distillationId")
        if mode not in DISTILLATION_MODES:
            raise ToolError("DISTILLATION_MODE_INVALID", "频道蒸馏模式不受支持。")
        if not isinstance(references, list) or not references or len(references) > 8:
            raise ToolError("REFERENCE_CHANNELS_INVALID", "references 必须包含 1–8 个参考频道。")
        if mode == "single" and len(references) != 1:
            raise ToolError("REFERENCE_CHANNEL_COUNT_INVALID", "单频道模式必须且只能提供一个频道。")
        if mode != "single" and len(references) < 2:
            raise ToolError("REFERENCE_CHANNEL_COUNT_INVALID", "并行、对比或融合模式至少需要两个频道。")

        reference_ids: set[str] = set()
        video_ids: set[str] = set()
        normalized_references: list[dict[str, Any]] = []
        for item in references:
            if not isinstance(item, dict):
                raise ToolError("REFERENCE_CHANNEL_INVALID", "每个参考频道必须是对象。")
            reference_id = _safe_identifier(item.get("referenceId"), "referenceId")
            if reference_id in reference_ids:
                raise ToolError("REFERENCE_CHANNEL_DUPLICATE", "referenceId 不得重复。")
            reference_ids.add(reference_id)
            channel_manifest = self._source(channel_profile_id, item.get("channelSourcePackageId"))
            if channel_manifest.get("sourceType") != "reference-channel":
                raise ToolError("REFERENCE_CHANNEL_SOURCE_INVALID", "频道身份必须来自 reference-channel Source Package。")
            requested_videos = item.get("videoSourcePackageIds")
            if not isinstance(requested_videos, list) or not requested_videos or len(requested_videos) > 100:
                raise ToolError("REFERENCE_VIDEO_LIST_INVALID", "每个频道必须绑定 1–100 个独立视频 Source Package。")
            videos: list[dict[str, Any]] = []
            channel_platform_id = channel_manifest.get("platformId")
            for requested in requested_videos:
                video_manifest = self._source(channel_profile_id, requested)
                source_package_id = video_manifest["sourcePackageId"]
                if source_package_id in video_ids:
                    raise ToolError("REFERENCE_VIDEO_DUPLICATE", "同一视频不能同时归入多个参考频道。")
                video_ids.add(source_package_id)
                if video_manifest.get("sourceType") != "youtube-video":
                    raise ToolError("REFERENCE_VIDEO_SOURCE_INVALID", "深拆样本必须来自 youtube-video Source Package。")
                video_channel_id = video_manifest.get("metadata", {}).get("channelId")
                if channel_platform_id and video_channel_id and channel_platform_id != video_channel_id:
                    raise ToolError("REFERENCE_VIDEO_CHANNEL_MISMATCH", "视频与参考频道身份不一致。")
                content_asset = self._content_asset(video_manifest)
                canonical_ready = video_manifest.get("status") == "CONTENT_READY" and content_asset is not None
                videos.append(
                    {
                        "sourcePackage": _source_ref(video_manifest),
                        "sourcePackageId": source_package_id,
                        "platformId": video_manifest.get("platformId"),
                        "title": video_manifest.get("title"),
                        "publishedAt": video_manifest.get("metadata", {}).get("publishedAt"),
                        "publicMetrics": video_manifest.get("metadata", {}).get("publicMetrics", {}),
                        "canonicalReady": canonical_ready,
                        "canonicalTextAsset": content_asset,
                    }
                )
            role = item.get("role") or "reference"
            if not isinstance(role, str) or not role.strip():
                raise ToolError("REFERENCE_ROLE_INVALID", "每个参考频道必须有明确角色。")
            weight = item.get("weight")
            if mode == "fusion":
                if not isinstance(weight, (int, float)) or isinstance(weight, bool) or weight <= 0:
                    raise ToolError("REFERENCE_WEIGHT_INVALID", "融合模式每个频道必须有正数权重。")
            normalized_references.append(
                {
                    "referenceId": reference_id,
                    "role": role.strip(),
                    "weight": weight,
                    "channelSourcePackage": _source_ref(channel_manifest),
                    "channelSourcePackageId": channel_manifest["sourcePackageId"],
                    "channelIdentity": {
                        "platform": channel_manifest.get("platform"),
                        "platformId": channel_manifest.get("platformId"),
                        "canonicalUrl": channel_manifest.get("canonicalUrl"),
                        "title": channel_manifest.get("title"),
                    },
                    "videos": videos,
                }
            )
        if mode == "fusion":
            total = sum(float(item["weight"]) for item in normalized_references)
            if abs(total - 100.0) > 0.0001:
                raise ToolError("REFERENCE_WEIGHT_TOTAL_INVALID", "融合权重合计必须正好为 100。")

        eligible_count = sum(
            1 for reference in normalized_references for video in reference["videos"] if video["canonicalReady"]
        )
        if eligible_count == 0:
            raise ToolError(
                "CANONICAL_VIDEO_TEXT_REQUIRED",
                "没有任何视频具备已验收的 content.txt；频道蒸馏不能只凭标题、封面或播放量编造正文规律。",
            )
        target = min(8, eligible_count)
        plan = {
            "schemaVersion": CONTENT_ANALYSIS_VERSION,
            "distillationId": distillation_id,
            "channelProfileId": channel_profile_id,
            "targetChannel": _contract_ref(self.store.get_channel(channel_profile_id)["channelProfile"]),
            "mode": mode,
            "references": normalized_references,
            "sampleRules": {
                "defaultDeepSampleTarget": target,
                "maximumDeepSamples": min(12, eligible_count),
                "batchMaximum": 3,
                "corePatternMinimumEvidence": 2,
                "superHitClassification": "special-case-until-repeated",
                "lowPerformancePositiveEvidenceForbidden": True,
            },
            "boundaries": self.capabilities()["boundaries"],
        }
        request_hash = _json_hash(plan)
        root = self._root(channel_profile_id, distillation_id)
        state_path = root / "state.json"
        if state_path.is_file():
            state = self._load_state(channel_profile_id, distillation_id)
            if state.get("requestHash") != request_hash:
                raise ToolError("DISTILLATION_ID_CONFLICT", "同一 distillationId 已绑定不同请求。")
            return {"state": state, "plan": plan, "idempotent": True}
        root.mkdir(parents=True, exist_ok=False)
        _atomic_json(root / "plan.json", plan)
        created = utc_now()
        state = {
            "schemaVersion": CONTENT_ANALYSIS_VERSION,
            "distillationId": distillation_id,
            "channelProfileId": channel_profile_id,
            "mode": mode,
            "state": "DEEP_ANALYSIS_READY",
            "createdAt": created,
            "updatedAt": created,
            "requestHash": request_hash,
            "planPath": "plan.json",
            "sampleTarget": target,
            "eligibleSampleCount": eligible_count,
            "samples": {},
            "stages": [
                {"stage": "channel-identity", "status": "SUCCEEDED"},
                {"stage": "lightweight-inventory", "status": "SUCCEEDED"},
                {"stage": "popular-sample-selection", "status": "SUCCEEDED"},
                {"stage": "per-video-deep-analysis", "status": "IN_PROGRESS"},
                {"stage": "cross-sample-aggregation", "status": "PENDING"},
                {"stage": "quality-gate", "status": "PENDING"},
                {"stage": "profile-freeze", "status": "PENDING"},
            ],
            "outputs": {},
        }
        if previous_distillation_id is not None:
            previous_id = _safe_identifier(previous_distillation_id, "previousDistillationId")
            previous = self._load_state(channel_profile_id, previous_id)
            for source_package_id, sample in previous.get("samples", {}).items():
                planned = next(
                    (
                        video
                        for reference in normalized_references
                        for video in reference["videos"]
                        if video["sourcePackageId"] == source_package_id
                        and video["sourcePackage"]["targetHash"] == sample.get("sourceHash")
                    ),
                    None,
                )
                previous_path = self._root(channel_profile_id, previous_id) / str(sample.get("path", ""))
                if planned and previous_path.is_file() and sample.get("status") == "SUCCEEDED":
                    contract = _read_json(previous_path, "PREVIOUS_SAMPLE_INVALID")
                    destination = root / "samples" / f"{source_package_id}.json"
                    _atomic_json(destination, contract)
                    state["samples"][source_package_id] = {
                        **sample,
                        "path": destination.relative_to(root).as_posix(),
                        "reusedFrom": previous_id,
                    }
        self._save_state(state)
        return {
            "state": state,
            "plan": plan,
            "idempotent": False,
            "confirmationCard": {
                "mode": mode,
                "referenceChannels": len(normalized_references),
                "eligibleCanonicalVideos": eligible_count,
                "initialDeepSampleTarget": target,
                "rawSubtitlesWillBeRead": False,
                "next": "analyze each selected video independently in batches of at most 3",
            },
        }

    def checkpoint(
        self,
        *,
        task_id: Any,
        channel_profile_id: Any,
        binding_proof: Any,
        distillation_id: Any,
        source_package_id: Any,
        status: Any,
        analysis: Any = None,
        failure: Any = None,
    ) -> dict[str, Any]:
        self.store.assert_binding(
            task_id=task_id, channel_profile_id=channel_profile_id, binding_proof=binding_proof
        )
        distillation_id = _safe_identifier(distillation_id, "distillationId")
        source_package_id = _safe_identifier(source_package_id, "sourcePackageId")
        state = self._load_state(channel_profile_id, distillation_id)
        if state["state"] == "FROZEN":
            raise ToolError("DISTILLATION_FROZEN", "已冻结频道画像不能改写样本。")
        plan = _read_json(self._root(channel_profile_id, distillation_id) / "plan.json", "DISTILLATION_PLAN_INVALID")
        planned = next(
            (
                (reference, video)
                for reference in plan["references"]
                for video in reference["videos"]
                if video["sourcePackageId"] == source_package_id
            ),
            None,
        )
        if planned is None:
            raise ToolError("SAMPLE_NOT_PLANNED", "该视频不在本次参考频道清单中。")
        reference, video = planned
        if status not in {"SUCCEEDED", "FAILED", "SKIPPED"}:
            raise ToolError("SAMPLE_STATUS_INVALID", "样本状态不受支持。")
        now = utc_now()
        if status == "SUCCEEDED":
            if not video["canonicalReady"]:
                raise ToolError("SAMPLE_CANONICAL_TEXT_REQUIRED", "该视频没有已验收的 content.txt。")
            if not isinstance(analysis, dict):
                raise ToolError("SAMPLE_ANALYSIS_REQUIRED", "成功样本必须提交完整分析。")
            buckets = _validate_analysis_buckets(
                analysis.get("analysisBuckets"), source_package_id=source_package_id
            )
            dimensions = _validate_dimensions(
                analysis.get("dimensions"), SAMPLE_DIMENSIONS, "SAMPLE_DIMENSIONS_INCOMPLETE"
            )
            performance = analysis.get("performanceEvidence")
            if not isinstance(performance, dict) or performance.get("classification") != "public-fact":
                raise ToolError("PUBLIC_PERFORMANCE_EVIDENCE_REQUIRED", "热门样本依据必须明确标为公开事实。")
            if performance.get("qualification") not in {
                "historical-hit",
                "recent-breakthrough",
                "repeat-hit-series",
                "channel-relative-outlier",
            } or performance.get("positiveEvidenceEligible") is not True:
                raise ToolError(
                    "POPULAR_SAMPLE_QUALIFICATION_REQUIRED",
                    "深拆正向样本必须由公开表现确认是历史热门、近期突破、重复热门系列或频道相对异常值。",
                )
            if not isinstance(performance.get("evidenceBasis"), list) or not performance["evidenceBasis"]:
                raise ToolError("POPULAR_SAMPLE_EVIDENCE_REQUIRED", "热门样本必须记录公开指标与频道内比较依据。")
            private_metric_tokens = {
                "ctr",
                "retention",
                "trafficsource",
                "demographics",
                "watchtime",
                "impressions",
                "averageduration",
            }
            if any(any(token in key for token in private_metric_tokens) for key in _nested_keys(performance)):
                raise ToolError("PRIVATE_METRIC_INFERENCE_FORBIDDEN", "公开表现不能伪装成 CTR 或流量来源。")
            contract = with_hash(
                {
                    "schemaVersion": CONTENT_ANALYSIS_VERSION,
                    "contractType": "channel-distillation-sample",
                    "id": _derived_id("sample", distillation_id, source_package_id),
                    "version": "1.0.0",
                    "createdAt": now,
                    "hashAlgorithm": "SHA-256",
                    "hashRule": "canonical-json-v1",
                    "upstream": [video["sourcePackage"]],
                    "distillationId": distillation_id,
                    "targetChannelProfileId": channel_profile_id,
                    "referenceId": reference["referenceId"],
                    "sourcePackageId": source_package_id,
                    "sourceHash": video["sourcePackage"]["targetHash"],
                    "status": "SUCCEEDED",
                    "performanceEvidence": performance,
                    "analysisBuckets": buckets,
                    "dimensions": dimensions,
                }
            )
        else:
            if not isinstance(failure, dict) or not isinstance(failure.get("reason"), str):
                raise ToolError("SAMPLE_FAILURE_REQUIRED", "失败或跳过样本必须记录原因。")
            contract = with_hash(
                {
                    "schemaVersion": CONTENT_ANALYSIS_VERSION,
                    "contractType": "channel-distillation-sample",
                    "id": _derived_id("sample", distillation_id, source_package_id),
                    "version": "1.0.0",
                    "createdAt": now,
                    "hashAlgorithm": "SHA-256",
                    "hashRule": "canonical-json-v1",
                    "upstream": [video["sourcePackage"]],
                    "distillationId": distillation_id,
                    "targetChannelProfileId": channel_profile_id,
                    "referenceId": reference["referenceId"],
                    "sourcePackageId": source_package_id,
                    "sourceHash": video["sourcePackage"]["targetHash"],
                    "status": status,
                    "failure": failure,
                }
            )
        root = self._root(channel_profile_id, distillation_id)
        path = root / "samples" / f"{source_package_id}.json"
        if path.is_file():
            existing = _read_json(path, "SAMPLE_CHECKPOINT_INVALID")
            if existing.get("contentHash") == contract["contentHash"]:
                return {"sample": existing, "state": state, "idempotent": True}
            raise ToolError("SAMPLE_CHECKPOINT_CONFLICT", "同一视频样本已保存不同分析，不会静默覆盖。")
        _atomic_json(path, contract)
        state["samples"][source_package_id] = {
            "status": status,
            "referenceId": reference["referenceId"],
            "sourceHash": video["sourcePackage"]["targetHash"],
            "contentHash": contract["contentHash"],
            "path": path.relative_to(root).as_posix(),
        }
        succeeded = sum(item["status"] == "SUCCEEDED" for item in state["samples"].values())
        state["progress"] = {
            "succeeded": succeeded,
            "recorded": len(state["samples"]),
            "target": state["sampleTarget"],
        }
        if succeeded >= state["sampleTarget"]:
            state["stages"][3]["status"] = "SUCCEEDED"
            state["stages"][4]["status"] = "IN_PROGRESS"
            state["state"] = "AGGREGATION_READY"
        self._save_state(state)
        return {"sample": contract, "state": state, "idempotent": False}

    def _validate_audience_profile(self, value: Any) -> dict[str, Any]:
        if not isinstance(value, dict):
            raise ToolError("AUDIENCE_PROFILE_REQUIRED", "频道画像必须包含可更新观众画像。")
        required = {
            "commercialPositioning",
            "populationAndUsageClaims",
            "segments",
            "needsAndPreferences",
            "topicExpansionStrategy",
        }
        missing = sorted(required - set(value))
        if missing:
            raise ToolError("AUDIENCE_PROFILE_INCOMPLETE", "观众画像不完整。", details={"missing": missing})
        claims = value["populationAndUsageClaims"]
        if not isinstance(claims, list) or not claims:
            raise ToolError("AUDIENCE_CLAIMS_REQUIRED", "人口与使用环境必须逐项标事实、推断或未知。")
        for claim in claims:
            if not isinstance(claim, dict) or claim.get("classification") not in {
                "studio-fact",
                "public-inference",
                "unknown",
            }:
                raise ToolError("AUDIENCE_CLAIM_INVALID", "观众声明分类无效。")
            if claim["classification"] == "studio-fact" and not claim.get("studioSourceRef"):
                raise ToolError("STUDIO_FACT_SOURCE_REQUIRED", "Studio 事实必须绑定用户提供的数据来源。")
            if claim["classification"] == "public-inference" and not claim.get("evidenceSampleIds"):
                raise ToolError("AUDIENCE_INFERENCE_EVIDENCE_REQUIRED", "公开推断必须绑定热门样本证据。")
        strategy = value["topicExpansionStrategy"]
        allocation = strategy.get("allocation") if isinstance(strategy, dict) else None
        if not isinstance(allocation, dict) or set(allocation) != {
            "coreProven",
            "adjacent",
            "exploratory",
        }:
            raise ToolError("TOPIC_EXPANSION_ALLOCATION_INVALID", "题材通道必须动态分为核心、相邻与探索。")
        if any(not isinstance(item, int) or isinstance(item, bool) or item < 0 for item in allocation.values()):
            raise ToolError("TOPIC_EXPANSION_ALLOCATION_INVALID", "题材通道分配必须是非负整数。")
        if sum(allocation.values()) != 10:
            raise ToolError("TOPIC_EXPANSION_ALLOCATION_INVALID", "三类题材通道分配合计必须正好为 10。")
        lanes = strategy.get("lanes")
        required_lane_fields = {
            "laneId",
            "laneType",
            "audienceSegmentId",
            "preferenceSignalIds",
            "evidenceSampleIds",
            "preservedPromise",
            "allowedExpansion",
            "avoid",
        }
        if not isinstance(lanes, list) or not lanes:
            raise ToolError("TOPIC_EXPANSION_LANES_REQUIRED", "题材扩展策略必须逐通道绑定分群、偏好和热门证据。")
        for lane in lanes:
            if not isinstance(lane, dict) or not required_lane_fields.issubset(lane):
                raise ToolError("TOPIC_EXPANSION_LANE_INVALID", "每条题材通道缺少必需的观众或证据绑定。")
            if lane["laneType"] not in {"coreProven", "adjacent", "exploratory"}:
                raise ToolError("TOPIC_EXPANSION_LANE_INVALID", "题材通道类型无效。")
            for field in ("preferenceSignalIds", "evidenceSampleIds", "allowedExpansion", "avoid"):
                if not isinstance(lane[field], list) or not lane[field]:
                    raise ToolError("TOPIC_EXPANSION_LANE_INVALID", f"题材通道 {field} 必须是非空数组。")
        return json.loads(json.dumps(value, ensure_ascii=False))

    def _validate_profile(self, value: Any, reference_id: str, sample_ids: set[str]) -> dict[str, Any]:
        if not isinstance(value, dict) or value.get("referenceId") != reference_id:
            raise ToolError("REFERENCE_PROFILE_INVALID", "参考频道画像身份不匹配。")
        buckets = _validate_analysis_buckets(value.get("analysisBuckets"))
        dimensions = _validate_dimensions(
            value.get("dimensions"), PROFILE_DIMENSIONS, "PROFILE_DIMENSIONS_INCOMPLETE"
        )
        audience = self._validate_audience_profile(value.get("audienceProfile"))
        for fact in buckets["originalFacts"]:
            evidence_source_ids = {
                reference.get("sourcePackageId")
                for reference in fact.get("evidenceRefs", [])
                if isinstance(reference, dict)
            }
            if not evidence_source_ids or not evidence_source_ids.issubset(sample_ids):
                raise ToolError("PROFILE_FACT_EVIDENCE_MISMATCH", "频道聚合事实只能引用该频道的成功样本。")
        for claim in audience["populationAndUsageClaims"]:
            evidence_ids = claim.get("evidenceSampleIds")
            if claim["classification"] == "public-inference" and not set(evidence_ids).issubset(sample_ids):
                raise ToolError("AUDIENCE_INFERENCE_EVIDENCE_INVALID", "观众公开推断引用了其他频道或失败样本。")
        for lane in audience["topicExpansionStrategy"]["lanes"]:
            if not set(lane["evidenceSampleIds"]).issubset(sample_ids):
                raise ToolError("TOPIC_EXPANSION_EVIDENCE_INVALID", "题材通道引用了其他频道或失败样本。")
        core_patterns = value.get("corePatterns")
        if not isinstance(core_patterns, list):
            raise ToolError("CORE_PATTERNS_INVALID", "核心规律必须是数组。")
        pattern_ids: set[str] = set()
        for pattern in core_patterns:
            if not isinstance(pattern, dict) or not isinstance(pattern.get("patternId"), str):
                raise ToolError("CORE_PATTERN_INVALID", "核心规律必须有 patternId。")
            if pattern["patternId"] in pattern_ids:
                raise ToolError("CORE_PATTERN_INVALID", "核心规律 patternId 不得重复。")
            pattern_ids.add(pattern["patternId"])
            evidence = pattern.get("evidenceSampleIds")
            if not isinstance(evidence, list) or len(set(evidence)) < 2 or not set(evidence).issubset(sample_ids):
                raise ToolError("CORE_PATTERN_EVIDENCE_INSUFFICIENT", "核心规律至少需要两条本频道成功热门样本证据。")
        for special in value.get("specialCases", []):
            evidence = special.get("evidenceSampleIds") if isinstance(special, dict) else None
            if not isinstance(evidence, list) or not evidence or not set(evidence).issubset(sample_ids):
                raise ToolError("SPECIAL_CASE_EVIDENCE_INVALID", "热门特例必须绑定真实成功样本。")
        do_not_amplify = value.get("doNotAmplify")
        if not isinstance(do_not_amplify, list) or not do_not_amplify:
            raise ToolError("DO_NOT_AMPLIFY_REQUIRED", "画像必须记录原频道不应放大的缺点。")
        return {
            **json.loads(json.dumps(value, ensure_ascii=False)),
            "analysisBuckets": buckets,
            "dimensions": dimensions,
            "audienceProfile": audience,
        }

    @staticmethod
    def _runtime_view(profile: dict[str, Any], profile_ref: dict[str, Any], created: str) -> dict[str, Any]:
        dimensions = profile["dimensions"]
        return with_hash(
            {
                "schemaVersion": CONTENT_ANALYSIS_VERSION,
                "contractType": "channel-runtime-profile-v1",
                "id": _derived_id("runtime", profile["referenceId"], profile_ref["targetHash"][:12]),
                "version": "1.0.0",
                "createdAt": created,
                "hashAlgorithm": "SHA-256",
                "hashRule": "canonical-json-v1",
                "upstream": [profile_ref],
                "referenceId": profile["referenceId"],
                "channelScope": dimensions["channelScope"],
                "audienceProfile": profile["audienceProfile"],
                "contentDna": dimensions["contentDna"],
                "expressionDna": dimensions["expressionDna"],
                "videoDna": dimensions["videoDna"],
                "packagingDna": dimensions["packagingDna"],
                "crossAssetAlignmentDna": dimensions["crossAssetAlignmentDna"],
                "retentionHypotheses": dimensions["retentionHypotheses"],
                "transferableFunctions": profile["analysisBuckets"]["transferableMethods"],
                "doNotCopy": profile["analysisBuckets"]["prohibitedCopy"],
                "doNotAmplify": profile["doNotAmplify"],
                "novelMangaAdaptation": dimensions["novelMangaAdaptation"],
                "unknowns": profile["analysisBuckets"]["unknowns"],
            }
        )

    @staticmethod
    def _validate_account_requirements(value: Any) -> dict[str, Any]:
        if not isinstance(value, dict):
            raise ToolError("ACCOUNT_REQUIREMENTS_REQUIRED", "必须根据冻结画像生成账号专属拆解与仿写要求。")
        decomposition = value.get("decomposition")
        imitation = value.get("imitation")
        validation_cases = value.get("validationCases")
        if not isinstance(decomposition, dict) or not isinstance(imitation, dict):
            raise ToolError("ACCOUNT_REQUIREMENTS_INCOMPLETE", "账号专属拆解与仿写要求缺一不可。")
        if not isinstance(decomposition.get("requiredSections"), list) or not decomposition["requiredSections"]:
            raise ToolError("DECOMPOSITION_REQUIREMENTS_INVALID", "账号专属拆解要求必须列出必拆区块。")
        if not isinstance(imitation.get("audienceRewards"), list) or not imitation["audienceRewards"]:
            raise ToolError("IMITATION_REQUIREMENTS_INVALID", "账号专属仿写要求必须列出观众回报。")
        if not isinstance(validation_cases, dict):
            raise ToolError("ACCOUNT_VALIDATION_CASES_REQUIRED", "必须生成账号专属拆解与仿写验收样例。")
        for kind in ("decomposition", "imitation"):
            cases = validation_cases.get(kind)
            if not isinstance(cases, list) or len(cases) < 3:
                raise ToolError("ACCOUNT_VALIDATION_CASES_INVALID", "拆解与仿写各至少需要 3 个账号专属验收样例。")
            identifiers = {
                case.get("caseId") for case in cases if isinstance(case, dict) and isinstance(case.get("caseId"), str)
            }
            if len(identifiers) != len(cases) or any(
                not isinstance(case.get("expectedChecks"), list) or not case["expectedChecks"]
                for case in cases
                if isinstance(case, dict)
            ):
                raise ToolError("ACCOUNT_VALIDATION_CASES_INVALID", "验收样例必须有唯一 caseId 和预期检查项。")
        result = json.loads(json.dumps(value, ensure_ascii=False))
        result["decomposition"]["mandatoryEvidenceBuckets"] = list(BUCKET_KEYS)
        result["imitation"]["allowedLearning"] = [
            "subject-function",
            "structure",
            "rhythm",
            "expression-method",
            "audience-reward",
        ]
        result["imitation"]["mustRebuild"] = [
            "characters",
            "relationships",
            "world-rules",
            "event-causality",
            "conflict",
            "trigger",
            "reversal",
            "climax",
            "ending",
            "sentences",
            "proper-names",
        ]
        result["imitation"]["forbidden"] = [
            "original-sentences",
            "proper-names",
            "complete-event-order",
            "single-work-mainline",
            "segment-splicing",
        ]
        return result

    def finalize(
        self,
        *,
        task_id: Any,
        channel_profile_id: Any,
        binding_proof: Any,
        distillation_id: Any,
        profiles: Any,
        account_requirements: Any,
        quality_gate: Any,
        fusion_profile: Any = None,
    ) -> dict[str, Any]:
        self.store.assert_binding(
            task_id=task_id, channel_profile_id=channel_profile_id, binding_proof=binding_proof
        )
        distillation_id = _safe_identifier(distillation_id, "distillationId")
        state = self._load_state(channel_profile_id, distillation_id)
        if state["state"] == "FROZEN":
            return self.get(channel_profile_id=channel_profile_id, distillation_id=distillation_id)
        root = self._root(channel_profile_id, distillation_id)
        plan = _read_json(root / "plan.json", "DISTILLATION_PLAN_INVALID")
        successful = {
            source_id: value
            for source_id, value in state["samples"].items()
            if value["status"] == "SUCCEEDED"
        }
        if len(successful) < state["sampleTarget"]:
            raise ToolError(
                "DEEP_SAMPLE_TARGET_NOT_MET",
                "尚未完成默认深拆样本目标；不能提前把少量特例冻结成频道规律。",
                details={"required": state["sampleTarget"], "succeeded": len(successful)},
            )
        if not isinstance(profiles, list) or len(profiles) != len(plan["references"]):
            raise ToolError("REFERENCE_PROFILES_INCOMPLETE", "必须为每个参考频道分别生成独立画像。")
        profile_by_id = {
            item.get("referenceId"): item for item in profiles if isinstance(item, dict)
        }
        if set(profile_by_id) != {item["referenceId"] for item in plan["references"]}:
            raise ToolError("REFERENCE_PROFILES_INCOMPLETE", "参考频道画像集合与计划不一致。")
        validated_profiles = []
        for reference in plan["references"]:
            sample_ids = {
                source_id
                for source_id, value in successful.items()
                if value["referenceId"] == reference["referenceId"]
            }
            if not sample_ids:
                raise ToolError(
                    "REFERENCE_SAMPLE_REQUIRED",
                    "每个参考频道都必须至少有一条成功深拆样本，不能用其他频道代替。",
                    details={"referenceId": reference["referenceId"]},
                )
            validated_profiles.append(
                self._validate_profile(
                    profile_by_id[reference["referenceId"]], reference["referenceId"], sample_ids
                )
            )
        if not isinstance(quality_gate, dict) or quality_gate.get("passed") is not True:
            raise ToolError("DISTILLATION_QUALITY_GATE_FAILED", "频道蒸馏质量门未通过。")
        if quality_gate.get("hardFailures") not in (None, []):
            raise ToolError("DISTILLATION_QUALITY_GATE_FAILED", "质量门仍有硬失败项。")
        for field in (
            "bucketSeparationPassed",
            "copyBoundaryPassed",
            "crossAssetAlignmentPassed",
            "audienceEvidenceBoundaryPassed",
            "targetChannelIsolationPassed",
        ):
            if quality_gate.get(field) is not True:
                raise ToolError(
                    "DISTILLATION_QUALITY_GATE_INCOMPLETE",
                    "频道蒸馏质量门缺少必需硬项。",
                    details={"field": field},
                )
        coverage = quality_gate.get("coverage")
        if not isinstance(coverage, dict) or coverage.get("stopDecision") not in {
            "converged",
            "insufficient-popular-samples",
            "complete-audit",
        }:
            raise ToolError("DISTILLATION_COVERAGE_DECISION_REQUIRED", "冻结前必须记录样本覆盖与停止原因。")
        if coverage["stopDecision"] == "converged" and (
            coverage.get("primaryTypesCovered") is not True
            or coverage.get("stableSeriesCovered") is not True
            or coverage.get("importantNewPatternInLatestBatch") is not False
        ):
            raise ToolError(
                "DISTILLATION_EXPANSION_REQUIRED",
                "样本尚未覆盖主要类型、稳定栏目或最新批次仍产生重要新规律，应继续按两条扩展。",
            )
        if plan["mode"] == "fusion":
            if not isinstance(fusion_profile, dict):
                raise ToolError("FUSION_PROFILE_REQUIRED", "融合模式必须保存独立的功能贡献与重构规则。")
            if fusion_profile.get("averagingUsed") is not False or fusion_profile.get("segmentSplicingUsed") is not False:
                raise ToolError("FUSION_AVERAGING_FORBIDDEN", "多频道融合不能平均化或按段拼接。")
            contributions = fusion_profile.get("contributions")
            if not isinstance(contributions, list) or {
                item.get("referenceId") for item in contributions if isinstance(item, dict)
            } != {item["referenceId"] for item in plan["references"]}:
                raise ToolError("FUSION_CONTRIBUTIONS_INVALID", "融合必须逐频道记录角色、权重和功能贡献。")
            expected_contributions = {
                item["referenceId"]: {"role": item["role"], "weight": item["weight"]}
                for item in plan["references"]
            }
            for contribution in contributions:
                expected = expected_contributions[contribution["referenceId"]]
                actual_weight = contribution.get("weight")
                if (
                    contribution.get("role") != expected["role"]
                    or not isinstance(actual_weight, (int, float))
                    or isinstance(actual_weight, bool)
                    or float(actual_weight) != float(expected["weight"])
                    or not isinstance(contribution.get("functions"), list)
                    or not contribution["functions"]
                ):
                    raise ToolError(
                        "FUSION_CONTRIBUTIONS_INVALID",
                        "融合贡献必须保持计划中每个频道的角色、权重和非空功能清单。",
                    )
            if not isinstance(fusion_profile.get("recomposedCausalEngine"), str) or not fusion_profile[
                "recomposedCausalEngine"
            ].strip():
                raise ToolError("FUSION_CAUSAL_ENGINE_REQUIRED", "融合必须重建统一因果引擎。")
        elif fusion_profile is not None:
            raise ToolError("FUSION_PROFILE_UNEXPECTED", "非融合模式不得伪造融合画像。")
        requirements = self._validate_account_requirements(account_requirements)
        created = utc_now()
        source_upstream = [
            source
            for reference in plan["references"]
            for source in (
                reference["channelSourcePackage"],
                *(video["sourcePackage"] for video in reference["videos"]),
            )
        ]
        merged_buckets = {
            key: [
                {**item, "referenceId": profile["referenceId"]}
                for profile in validated_profiles
                for item in profile["analysisBuckets"][key]
            ]
            for key in BUCKET_KEYS
        }
        analysis_package = with_hash(
            {
                "schemaVersion": CONTENT_ANALYSIS_VERSION,
                "contractType": "analysis-package-v1",
                "id": _derived_id("analysis", distillation_id),
                "version": "1.0.0",
                "createdAt": created,
                "hashAlgorithm": "SHA-256",
                "hashRule": "canonical-json-v1",
                "upstream": source_upstream,
                "analysisKind": "channel-distillation",
                "distillationId": distillation_id,
                "targetChannelProfileId": channel_profile_id,
                "mode": plan["mode"],
                "analysisBuckets": merged_buckets,
                "referenceProfiles": validated_profiles,
                "fusionProfile": fusion_profile,
                "qualityGate": quality_gate,
                "status": "FROZEN",
            }
        )
        analysis_path = root / "analysis-package-v1.json"
        self._validate_contract_schema(analysis_package, "analysis-package-v1.schema.json")
        _atomic_json(analysis_path, analysis_package)

        profile_refs: list[dict[str, Any]] = []
        runtime_refs: list[dict[str, Any]] = []
        for profile in validated_profiles:
            reference_id = profile["referenceId"]
            contract = with_hash(
                {
                    "schemaVersion": CONTENT_ANALYSIS_VERSION,
                    "contractType": "reference-channel-profile-v1",
                    "id": _derived_id("reference_profile", distillation_id, reference_id),
                    "version": "1.0.0",
                    "createdAt": created,
                    "hashAlgorithm": "SHA-256",
                    "hashRule": "canonical-json-v1",
                    "upstream": [_contract_ref(analysis_package)],
                    "distillationId": distillation_id,
                    "targetChannelProfileId": channel_profile_id,
                    "referenceId": reference_id,
                    "profile": profile,
                    "status": "FROZEN",
                }
            )
            profile_path = root / "profiles" / reference_id / "reference-channel-profile-v1.json"
            self._validate_contract_schema(contract, "reference-channel-profile-v1.schema.json")
            _atomic_json(profile_path, contract)
            profile_ref = _contract_ref(contract)
            runtime = self._runtime_view(profile, profile_ref, created)
            runtime_path = root / "profiles" / reference_id / "channel-runtime-profile-v1.json"
            self._validate_contract_schema(runtime, "channel-runtime-profile-v1.schema.json")
            _atomic_json(runtime_path, runtime)
            profile_refs.append({**profile_ref, "referenceId": reference_id, "path": profile_path.relative_to(root).as_posix()})
            runtime_refs.append(
                {**_contract_ref(runtime), "referenceId": reference_id, "path": runtime_path.relative_to(root).as_posix()}
            )

        requirements_dir = root / "account-requirements"
        requirement_contracts: dict[str, dict[str, Any]] = {}
        for kind, contract_type in (
            ("decomposition", "account-decomposition-requirements-v1"),
            ("imitation", "account-imitation-requirements-v1"),
        ):
            contract = with_hash(
                {
                    "schemaVersion": CONTENT_ANALYSIS_VERSION,
                    "contractType": contract_type,
                    "id": _derived_id(f"{kind}_requirements", distillation_id),
                    "version": "1.0.0",
                    "createdAt": created,
                    "hashAlgorithm": "SHA-256",
                    "hashRule": "canonical-json-v1",
                    "upstream": [
                        {
                            key: value
                            for key, value in reference.items()
                            if key.startswith("target")
                        }
                        for reference in runtime_refs
                    ],
                    "distillationId": distillation_id,
                    "targetChannelProfileId": channel_profile_id,
                    "scope": "target-channel-only",
                    "requirements": requirements[kind],
                    "status": "ACTIVE",
                }
            )
            self._validate_contract_schema(contract, "content-analysis-requirements.schema.json")
            _atomic_json(requirements_dir / f"{kind}-requirements-v1.json", contract)
            requirement_contracts[kind] = contract

        validation_contract = with_hash(
            {
                "schemaVersion": CONTENT_ANALYSIS_VERSION,
                "contractType": "account-runtime-validation-v1",
                "id": _derived_id("runtime_validation", distillation_id),
                "version": "1.0.0",
                "createdAt": created,
                "hashAlgorithm": "SHA-256",
                "hashRule": "canonical-json-v1",
                "upstream": [
                    _contract_ref(requirement_contracts["decomposition"]),
                    _contract_ref(requirement_contracts["imitation"]),
                ],
                "distillationId": distillation_id,
                "targetChannelProfileId": channel_profile_id,
                "scope": "target-channel-only",
                "cases": requirements["validationCases"],
                "status": "READY",
            }
        )
        self._validate_contract_schema(validation_contract, "account-runtime-validation-v1.schema.json")
        _atomic_json(requirements_dir / "runtime-validation-cases-v1.json", validation_contract)

        runtime_skill_registry = self._write_runtime_skills(
            root,
            channel_profile_id,
            distillation_id,
            analysis_package,
            requirement_contracts,
        )
        outputs = {
            "analysisPackage": {**_contract_ref(analysis_package), "path": analysis_path.relative_to(root).as_posix()},
            "referenceProfiles": profile_refs,
            "runtimeProfiles": runtime_refs,
            "decompositionRequirements": {
                **_contract_ref(requirement_contracts["decomposition"]),
                "path": "account-requirements/decomposition-requirements-v1.json",
            },
            "imitationRequirements": {
                **_contract_ref(requirement_contracts["imitation"]),
                "path": "account-requirements/imitation-requirements-v1.json",
            },
            "runtimeValidation": {
                **_contract_ref(validation_contract),
                "path": "account-requirements/runtime-validation-cases-v1.json",
            },
            "runtimeSkillRegistry": runtime_skill_registry,
        }
        _atomic_json(root / "outputs.json", outputs)
        state["outputs"] = outputs
        state["state"] = "FROZEN"
        for stage in state["stages"]:
            stage["status"] = "SUCCEEDED"
        state["progress"] = {
            **state.get("progress", {}),
            "stagesSucceeded": 7,
            "stagesTotal": 7,
        }
        self._save_state(state)
        return {
            "state": state,
            "outputs": outputs,
            "completionCard": {
                "distillation": "7/7 succeeded",
                "deepSamplesSucceeded": len(successful),
                "referenceChannels": len(validated_profiles),
                "analysisPackageHash": analysis_package["contentHash"],
                "downstream": ["topic-center", "manuscript-center"],
            },
        }

    def _write_runtime_skills(
        self,
        root: Path,
        channel_profile_id: str,
        distillation_id: str,
        analysis_package: dict[str, Any],
        requirements: dict[str, dict[str, Any]],
    ) -> dict[str, Any]:
        short_scope = hashlib.sha256(channel_profile_id.encode("utf-8")).hexdigest()[:10]
        items = []
        for kind, label in (("decomposition", "视频文案拆解"), ("imitation", "原创仿写文案")):
            name = f"channel-{short_scope}-{kind}"
            skill_root = root / "runtime-skills" / kind
            requirement_relative = f"../../account-requirements/{kind}-requirements-v1.json"
            skill_text = f"""---
name: {name}
description: 仅为目标频道 {channel_profile_id} 执行{label}，并强制读取本次冻结频道画像生成的账号专属要求。其他频道不得加载。
---

# {label}（账号专属运行 Skill）

仅当当前任务绑定的 `channelProfileId` 精确等于 `{channel_profile_id}`，且频道蒸馏包 `{distillation_id}` 的哈希仍有效时使用。

1. 先读取 `{requirement_relative}` 并校验契约哈希。
2. 只读取 Source Package 的 `content.txt`；时间或章节定位读取 JSON 结构文件，不读取字幕正文副本。
3. 输出必须区分原文事实、分析结论、可迁移方法、禁止复制内容和未知项。
4. 学习功能与观众回报，不复制原句、专名、完整事件顺序或单一作品主线。
5. 将结果作为版本化契约交给选题中心或文稿中心，不在本 Skill 内启动制作或发布。

绑定的分析包 SHA-256：`{analysis_package['contentHash']}`。
"""
            _atomic_bytes(skill_root / "SKILL.md", skill_text.encode("utf-8"))
            agent_yaml = f"""interface:
  display_name: "{label}（账号专属）"
  short_description: "只为当前绑定频道执行冻结画像约束下的{label}"
  default_prompt: "Use ${name} only for its bound target channel."

policy:
  allow_implicit_invocation: false
"""
            _atomic_bytes(skill_root / "agents" / "openai.yaml", agent_yaml.encode("utf-8"))
            items.append(
                {
                    "skillName": name,
                    "kind": kind,
                    "scope": "target-channel-only",
                    "channelProfileId": channel_profile_id,
                    "distillationId": distillation_id,
                    "analysisPackageHash": analysis_package["contentHash"],
                    "skillPath": (skill_root / "SKILL.md").relative_to(root).as_posix(),
                    "requirementsHash": requirements[kind]["contentHash"],
                    "allowImplicitInvocation": False,
                }
            )
        registry = {
            "schemaVersion": CONTENT_ANALYSIS_VERSION,
            "scope": "target-channel-only",
            "channelProfileId": channel_profile_id,
            "distillationId": distillation_id,
            "analysisPackageHash": analysis_package["contentHash"],
            "skills": items,
        }
        _atomic_json(root / "runtime-skills" / "registry.json", registry)
        return {"path": "runtime-skills/registry.json", "sha256": _json_hash(registry), "skills": items}

    def get(self, *, channel_profile_id: Any, distillation_id: Any) -> dict[str, Any]:
        channel_profile_id = _safe_identifier(channel_profile_id, "channelProfileId", maximum=160)
        distillation_id = _safe_identifier(distillation_id, "distillationId")
        state = self._load_state(channel_profile_id, distillation_id)
        root = self._root(channel_profile_id, distillation_id)
        return {
            "state": state,
            "plan": _read_json(root / "plan.json", "DISTILLATION_PLAN_INVALID"),
            "outputs": state.get("outputs", {}),
            "progressReadOnly": True,
        }

    def analysis_package(self, *, channel_profile_id: Any, distillation_id: Any) -> dict[str, Any]:
        state = self._load_state(channel_profile_id, distillation_id)
        if state.get("state") != "FROZEN":
            raise ToolError("DISTILLATION_NOT_FROZEN", "频道蒸馏尚未冻结，不能交给下游。")
        path = self._root(channel_profile_id, distillation_id) / state["outputs"]["analysisPackage"]["path"]
        contract = _read_json(path, "ANALYSIS_PACKAGE_INVALID")
        if canonical_hash(contract) != contract.get("contentHash"):
            raise ToolError("ANALYSIS_PACKAGE_HASH_MISMATCH", "Analysis Package 哈希无效。")
        return contract

    def account_requirement(
        self,
        *,
        channel_profile_id: Any,
        distillation_id: Any,
        kind: str,
    ) -> dict[str, Any]:
        """Return one frozen target-channel requirement without exposing another channel."""
        if kind not in {"decomposition", "imitation"}:
            raise ToolError("ACCOUNT_REQUIREMENT_KIND_INVALID", "账号专属要求类型不受支持。")
        state = self._load_state(channel_profile_id, distillation_id)
        if state.get("state") != "FROZEN":
            raise ToolError("DISTILLATION_NOT_FROZEN", "频道蒸馏尚未冻结，不能读取账号专属要求。")
        output_key = "decompositionRequirements" if kind == "decomposition" else "imitationRequirements"
        output = state.get("outputs", {}).get(output_key)
        if not isinstance(output, dict) or not isinstance(output.get("path"), str):
            raise ToolError("ACCOUNT_REQUIREMENT_NOT_FOUND", "频道蒸馏缺少账号专属要求。")
        path = self._root(channel_profile_id, distillation_id) / output["path"]
        contract = _read_json(path, "ACCOUNT_REQUIREMENT_INVALID")
        if canonical_hash(contract) != contract.get("contentHash"):
            raise ToolError("ACCOUNT_REQUIREMENT_HASH_MISMATCH", "账号专属要求哈希无效。")
        if contract.get("targetChannelProfileId") != channel_profile_id or contract.get("distillationId") != distillation_id:
            raise ToolError("ACCOUNT_REQUIREMENT_SCOPE_MISMATCH", "账号专属要求不属于当前目标频道。")
        return contract

    def integrity_check(self, *, channel_profile_id: Any, distillation_id: Any) -> dict[str, Any]:
        state = self._load_state(channel_profile_id, distillation_id)
        root = self._root(channel_profile_id, distillation_id)
        errors: list[dict[str, Any]] = []
        paths = ["plan.json", "state.json"]
        for item in state.get("samples", {}).values():
            paths.append(item["path"])
        outputs = state.get("outputs", {})
        for key in (
            "analysisPackage",
            "decompositionRequirements",
            "imitationRequirements",
            "runtimeValidation",
        ):
            if outputs.get(key, {}).get("path"):
                paths.append(outputs[key]["path"])
        paths.extend(item["path"] for item in outputs.get("referenceProfiles", []))
        paths.extend(item["path"] for item in outputs.get("runtimeProfiles", []))
        if outputs.get("runtimeSkillRegistry", {}).get("path"):
            paths.append(outputs["runtimeSkillRegistry"]["path"])
        for relative in paths:
            path = root / relative
            if not path.is_file():
                errors.append({"path": relative, "issue": "missing"})
                continue
            if path.suffix == ".json" and path.name not in {"plan.json", "state.json", "outputs.json", "registry.json"}:
                contract = _read_json(path, "DISTILLATION_CONTRACT_INVALID")
                if "contentHash" in contract and canonical_hash(contract) != contract["contentHash"]:
                    errors.append({"path": relative, "issue": "content-hash"})
        return {
            "status": "PASS" if not errors else "FAIL",
            "distillationId": distillation_id,
            "state": state["state"],
            "errors": errors,
            "progressReadOnly": True,
        }


__all__ = ["CONTENT_ANALYSIS_VERSION", "ChannelDistillation"]
