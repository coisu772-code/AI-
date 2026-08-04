from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PLUGIN_ROOT = ROOT / "plugins" / "ai-video-channel-production"
MCP_ROOT = PLUGIN_ROOT / "mcp"
sys.path.insert(0, str(MCP_ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from aivcp_tools.errors import ToolError  # noqa: E402
from aivcp_tools.service import LocalToolService, ServiceConfig, tool_definitions  # noqa: E402
from stage4_support import create_service  # noqa: E402


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def fixture_adapter(item: dict[str, object], work_dir: Path) -> dict[str, object]:
    del work_dir
    kind = str(item["kind"])
    locator = str(item["locator"])
    platform_id = str(item.get("platformId") or _sha(locator)[:12])
    channel_id = str(item.get("channelId") or platform_id)
    base = {
        "sourceType": kind,
        "status": "CONTENT_READY",
        "title": str(item.get("title") or platform_id),
        "language": "zh-CN",
        "platform": "youtube",
        "platformId": platform_id,
        "canonicalUrl": locator,
        "canonicalLocator": locator,
        "provenance": {
            "kind": "public-url",
            "locator": locator,
            "collectedAt": "2026-08-04T00:00:00Z",
            "adapterId": "synthetic-channel-distillation-fixture",
            "adapterVersion": "1.0.0",
        },
        "rightsBoundary": {
            "accessLevel": "public-domain",
            "basis": "Synthetic test fixture explicitly permits local processing.",
            "confirmedByUser": False,
        },
        "metadata": {"channelId": channel_id, "publicMetrics": {"viewCount": 1000}},
        "report": {"complete": True, "syntheticFixture": True},
    }
    if kind == "reference-channel":
        inventory = json.dumps({"channelId": platform_id, "entries": []})
        return {
            **base,
            "assets": [
                {
                    "role": "normalized",
                    "mediaType": "application/json",
                    "filename": "channel-inventory.json",
                    "data": inventory,
                }
            ],
            "contentSha256": _sha(inventory),
        }
    if item.get("canonicalReady") is False:
        return {**base, "status": "PARTIAL", "assets": [], "contentSha256": None}
    content = (
        f"{platform_id} 是合成测试视频。开场先兑现标题承诺，随后用关系变化推进，"
        "每个阶段都交付可核验的信息回报，结尾完成情绪满足。"
    )
    timing = json.dumps(
        {
            "schemaVersion": "1.0.0",
            "format": "canonical-text-timing-map",
            "paragraphCount": 1,
            "entries": [{"paragraphId": "p0001", "startSeconds": 0, "endSeconds": 12}],
        },
        ensure_ascii=False,
    )
    return {
        **base,
        "assets": [
            {"role": "normalized", "mediaType": "text/plain; charset=utf-8", "filename": "content.txt", "data": content},
            {"role": "normalized", "mediaType": "application/json", "filename": "timing-map.json", "data": timing},
        ],
        "contentSha256": _sha(content),
    }


def sample_analysis(source_package_id: str, suffix: str) -> dict[str, object]:
    fact_id = f"fact-{suffix}"
    conclusion_id = f"conclusion-{suffix}"
    return {
        "analysisBuckets": {
            "originalFacts": [
                {
                    "factId": fact_id,
                    "statement": "开场直接兑现标题承诺。",
                    "evidenceRefs": [
                        {"sourcePackageId": source_package_id, "locator": "content.txt#p0001"}
                    ],
                }
            ],
            "analysisConclusions": [
                {
                    "conclusionId": conclusion_id,
                    "statement": "承诺快速兑现降低理解成本。",
                    "evidenceFactIds": [fact_id],
                    "confidence": 0.9,
                }
            ],
            "transferableMethods": [
                {
                    "methodId": f"method-{suffix}",
                    "method": "先展示本片独立冲突，再交付第一轮信息回报。",
                    "evidenceConclusionIds": [conclusion_id],
                    "applicationConditions": ["标题承诺能在正文中真实兑现"],
                }
            ],
            "prohibitedCopy": [
                {
                    "boundaryId": f"boundary-{suffix}",
                    "description": "不得复制样本原句、专名或完整事件顺序。",
                    "categories": ["sentences", "proper-names", "event-order"],
                }
            ],
            "unknowns": [
                {
                    "unknownId": f"unknown-{suffix}",
                    "statement": "没有用户提供的 Studio 留存率。",
                }
            ],
        },
        "dimensions": {key: {"summary": f"{key}-{suffix}"} for key in (
            "storyContent", "functionalStructure", "expression", "openingHook", "title",
            "thumbnail", "description", "hashtags", "videoPresentation", "visualStyle",
            "audienceNeeds", "psychologicalPayoff", "retentionHypotheses", "channelVoice",
            "crossAssetAlignment", "lowQualityPatterns",
        )},
        "performanceEvidence": {
            "classification": "public-fact",
            "qualification": "channel-relative-outlier",
            "positiveEvidenceEligible": True,
            "evidenceBasis": ["公开播放量高于频道同形态中位数"],
            "viewCount": 1000,
            "basis": "Source Package publicMetrics",
        },
    }


def aggregate_profile(reference_id: str, sample_ids: list[str]) -> dict[str, object]:
    buckets = sample_analysis(sample_ids[0], f"profile-{reference_id}")["analysisBuckets"]
    return {
        "referenceId": reference_id,
        "analysisBuckets": buckets,
        "dimensions": {key: {"summary": f"{key}-{reference_id}"} for key in (
            "channelScope", "contentDna", "expressionDna", "videoDna", "packagingDna",
            "crossAssetAlignmentDna", "retentionHypotheses", "channelVoice", "commonLogic",
            "novelMangaAdaptation",
        )},
        "audienceProfile": {
            "commercialPositioning": "综合向故事频道",
            "populationAndUsageClaims": [
                {
                    "claimId": "audience-public-1",
                    "classification": "public-inference",
                    "statement": "偏好快速理解冲突与阶段回报的观众。",
                    "evidenceSampleIds": sample_ids,
                }
            ],
            "segments": [
                {"segmentId": "core", "role": "core"},
                {"segmentId": "secondary", "role": "secondary"},
                {"segmentId": "test", "role": "test"},
            ],
            "needsAndPreferences": ["清楚承诺", "真实推进", "完整满足"],
            "topicExpansionStrategy": {
                "allocation": {"coreProven": 6, "adjacent": 3, "exploratory": 1},
                "lanes": [
                    {
                        "laneId": "core-1",
                        "laneType": "coreProven",
                        "audienceSegmentId": "core",
                        "preferenceSignalIds": ["clear-promise"],
                        "evidenceSampleIds": sample_ids,
                        "preservedPromise": "清楚承诺与阶段回报",
                        "allowedExpansion": ["重建人物与因果的新故事"],
                        "avoid": ["复制完整事件顺序"],
                    }
                ],
            },
        },
        "corePatterns": [
            {
                "patternId": "promise-payoff",
                "statement": "承诺、推进和回报连续对齐。",
                "evidenceSampleIds": sample_ids,
            }
        ],
        "specialCases": [
            {"caseId": "special-1", "statement": "单条特殊包装", "evidenceSampleIds": [sample_ids[0]]}
        ],
        "doNotAmplify": ["低成本循环背景只能记录为原频道成片形态"],
    }


def account_requirements() -> dict[str, object]:
    return {
        "decomposition": {"requiredSections": ["承诺兑现链", "观众心理回报"]},
        "imitation": {"audienceRewards": ["快速理解", "阶段满足", "完整收束"]},
        "validationCases": {
            "decomposition": [
                {"caseId": f"decompose-{index}", "expectedChecks": ["五类结果分离", "证据可追溯"]}
                for index in range(1, 4)
            ],
            "imitation": [
                {"caseId": f"imitate-{index}", "expectedChecks": ["功能迁移", "事件因果重建", "无原句复制"]}
                for index in range(1, 4)
            ],
        },
    }


def quality_gate() -> dict[str, object]:
    return {
        "passed": True,
        "hardFailures": [],
        "bucketSeparationPassed": True,
        "copyBoundaryPassed": True,
        "crossAssetAlignmentPassed": True,
        "audienceEvidenceBoundaryPassed": True,
        "targetChannelIsolationPassed": True,
        "coverage": {
            "stopDecision": "converged",
            "primaryTypesCovered": True,
            "stableSeriesCovered": True,
            "importantNewPatternInLatestBatch": False,
        },
    }


class ChannelDistillationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="aivcp-channel-distillation-")
        self.root = Path(self.temp.name)
        self.service, self.task_id, self.channel_id, self.proof = create_service(
            self.root,
            "zh-CN",
            plugin_root=PLUGIN_ROOT,
            local_tool_service=LocalToolService,
            service_config=ServiceConfig,
        )
        self.service.sources.adapter_factory = fixture_adapter

    def tearDown(self) -> None:
        self.temp.cleanup()

    def assert_tool_error(self, code: str, callback) -> ToolError:
        with self.assertRaises(ToolError) as caught:
            callback()
        self.assertEqual(code, caught.exception.code)
        return caught.exception

    def add_sources(self) -> dict[str, str]:
        inputs = [
            {"kind": "reference-channel", "locator": "https://www.youtube.com/channel/UCREF001", "platformId": "UCREF001", "title": "Reference One"},
            {"kind": "youtube-video", "locator": "https://www.youtube.com/watch?v=video001", "platformId": "video001", "channelId": "UCREF001"},
            {"kind": "youtube-video", "locator": "https://www.youtube.com/watch?v=video002", "platformId": "video002", "channelId": "UCREF001"},
            {"kind": "youtube-video", "locator": "https://www.youtube.com/watch?v=missing01", "platformId": "missing01", "channelId": "UCREF001", "canonicalReady": False},
            {"kind": "reference-channel", "locator": "https://www.youtube.com/channel/UCREF002", "platformId": "UCREF002", "title": "Reference Two"},
            {"kind": "youtube-video", "locator": "https://www.youtube.com/watch?v=video003", "platformId": "video003", "channelId": "UCREF002"},
            {"kind": "youtube-video", "locator": "https://www.youtube.com/watch?v=video004", "platformId": "video004", "channelId": "UCREF002"},
        ]
        prepared = self.service.call(
            "source_add_prepare",
            {
                "taskId": self.task_id,
                "channelProfileId": self.channel_id,
                "bindingProof": self.proof,
                "inputs": inputs,
            },
        )
        self.service.call(
            "source_add_confirm",
            {
                "taskId": self.task_id,
                "channelProfileId": self.channel_id,
                "bindingProof": self.proof,
                "acquisitionJobId": prepared["acquisitionJobId"],
                "planHash": prepared["planHash"],
                "confirmation": {"confirmed": True},
            },
        )
        result = {}
        for row in self.service.call("source_search", {"channelProfileId": self.channel_id, "limit": 20})["sources"]:
            detail = self.service.call(
                "source_get",
                {"channelProfileId": self.channel_id, "sourcePackageId": row["source_package_id"]},
            )
            result[row["platform_id"]] = row["source_package_id"]
        return result

    def test_surface_and_single_channel_freeze_handoff_and_isolation(self) -> None:
        names = {item["name"] for item in tool_definitions()}
        self.assertTrue(
            {
                "channel_distillation_capabilities",
                "channel_distillation_prepare",
                "channel_distillation_checkpoint",
                "channel_distillation_finalize",
                "channel_distillation_get",
                "channel_distillation_integrity_check",
            }.issubset(names)
        )
        ids = self.add_sources()
        prepared = self.service.call(
            "channel_distillation_prepare",
            {
                "taskId": self.task_id,
                "channelProfileId": self.channel_id,
                "bindingProof": self.proof,
                "distillationId": "distill-single-001",
                "mode": "single",
                "references": [
                    {
                        "referenceId": "reference-one",
                        "channelSourcePackageId": ids["UCREF001"],
                        "videoSourcePackageIds": [ids["video001"], ids["video002"], ids["missing01"]],
                        "role": "primary-story-model",
                    }
                ],
            },
        )
        self.assertEqual(2, prepared["state"]["sampleTarget"])
        self.assertFalse(prepared["confirmationCard"]["rawSubtitlesWillBeRead"])
        self.assert_tool_error(
            "SAMPLE_CANONICAL_TEXT_REQUIRED",
            lambda: self.service.call(
                "channel_distillation_checkpoint",
                {
                    "taskId": self.task_id,
                    "channelProfileId": self.channel_id,
                    "bindingProof": self.proof,
                    "distillationId": "distill-single-001",
                    "sourcePackageId": ids["missing01"],
                    "status": "SUCCEEDED",
                    "analysis": sample_analysis(ids["missing01"], "missing"),
                },
            ),
        )
        self.service.call(
            "channel_distillation_checkpoint",
            {
                "taskId": self.task_id,
                "channelProfileId": self.channel_id,
                "bindingProof": self.proof,
                "distillationId": "distill-single-001",
                "sourcePackageId": ids["missing01"],
                "status": "FAILED",
                "failure": {"reason": "canonical text unavailable"},
            },
        )
        for number, platform_id in enumerate(("video001", "video002"), 1):
            self.service.call(
                "channel_distillation_checkpoint",
                {
                    "taskId": self.task_id,
                    "channelProfileId": self.channel_id,
                    "bindingProof": self.proof,
                    "distillationId": "distill-single-001",
                    "sourcePackageId": ids[platform_id],
                    "status": "SUCCEEDED",
                    "analysis": sample_analysis(ids[platform_id], str(number)),
                },
            )
        finalized = self.service.call(
            "channel_distillation_finalize",
            {
                "taskId": self.task_id,
                "channelProfileId": self.channel_id,
                "bindingProof": self.proof,
                "distillationId": "distill-single-001",
                "profiles": [aggregate_profile("reference-one", [ids["video001"], ids["video002"]])],
                "accountRequirements": account_requirements(),
                "qualityGate": quality_gate(),
            },
        )
        self.assertEqual("7/7 succeeded", finalized["completionCard"]["distillation"])
        self.assertEqual(
            "PASS",
            self.service.call(
                "channel_distillation_integrity_check",
                {"channelProfileId": self.channel_id, "distillationId": "distill-single-001"},
            )["status"],
        )
        runtime_registry = finalized["outputs"]["runtimeSkillRegistry"]
        self.assertTrue(all(item["channelProfileId"] == self.channel_id for item in runtime_registry["skills"]))
        self.assertTrue(all(item["allowImplicitInvocation"] is False for item in runtime_registry["skills"]))
        distillation_root = (
            self.service.store.channel_path(self.channel_id)
            / "content-analysis"
            / "channel-distillations"
            / "distill-single-001"
        )
        for item in runtime_registry["skills"]:
            agent_text = (distillation_root / Path(item["skillPath"]).parent / "agents" / "openai.yaml").read_text(
                encoding="utf-8"
            )
            self.assertIn("policy:\n  allow_implicit_invocation: false", agent_text)
        project = self.service.call(
            "content_project_start",
            {
                "taskId": self.task_id,
                "channelProfileId": self.channel_id,
                "bindingProof": self.proof,
                "projectId": "topic-from-distillation",
                "sourceMode": "channel-library",
                "analysisPackages": [{"distillationId": "distill-single-001"}],
            },
        )
        self.assertEqual("distill-single-001", project["state"]["analysisLocks"][0]["distillationId"])
        second, _ = self.service.store.create_pending_channel(
            publisher_channel={
                "publisherProfileId": "publisher_isolation_002",
                "channelSerial": "02",
                "youtubeChannelId": "UCISOLATION0002",
                "displayName": "Isolation Channel",
            },
            target_region="China",
            output_language="zh-CN",
        )
        second_binding = self.service.store.bind_task(
            task_id="task-isolation-002", channel_profile_id=second["channelProfileId"]
        )
        self.service.store.complete_library(
            task_id="task-isolation-002",
            channel_profile_id=second["channelProfileId"],
            binding_proof=second_binding["bindingProof"],
            defaults={
                "voice": {"engineId": "fixture-tts", "voiceId": "fixture-cn-001"},
                "manuscript": {"mode": "auto_by_topic", "preferredCharacters": 200, "minCharacters": 20, "maxCharacters": 1000},
                "episodes": {"mode": "auto_by_topic", "preferredCount": 2, "minCount": 1, "maxCount": 4},
                "deliveryMode": "auto_render",
                "videoGeneration": {"enabled": False, "selectionMode": "none", "fallbackPolicy": "pause"},
                "uploadPolicy": "REQUIRE_REVIEW",
            },
            execution_mode="review",
        )
        self.assert_tool_error(
            "CHANNEL_DISTILLATION_NOT_FOUND",
            lambda: self.service.call(
                "content_project_start",
                {
                    "taskId": "task-isolation-002",
                    "channelProfileId": second["channelProfileId"],
                    "bindingProof": second_binding["bindingProof"],
                    "projectId": "must-not-read-other-channel",
                    "sourceMode": "channel-library",
                    "analysisPackages": [{"distillationId": "distill-single-001"}],
                },
            ),
        )

    def test_fusion_keeps_channel_roles_and_rejects_bad_weight_total(self) -> None:
        ids = self.add_sources()
        references = [
            {
                "referenceId": "reference-one",
                "channelSourcePackageId": ids["UCREF001"],
                "videoSourcePackageIds": [ids["video001"], ids["video002"]],
                "role": "story-engine",
                "weight": 60,
            },
            {
                "referenceId": "reference-two",
                "channelSourcePackageId": ids["UCREF002"],
                "videoSourcePackageIds": [ids["video003"], ids["video004"]],
                "role": "packaging-and-rhythm",
                "weight": 40,
            },
        ]
        result = self.service.call(
            "channel_distillation_prepare",
            {
                "taskId": self.task_id,
                "channelProfileId": self.channel_id,
                "bindingProof": self.proof,
                "distillationId": "distill-fusion-001",
                "mode": "fusion",
                "references": references,
            },
        )
        self.assertEqual(
            [("story-engine", 60), ("packaging-and-rhythm", 40)],
            [(item["role"], item["weight"]) for item in result["plan"]["references"]],
        )
        for number, platform_id in enumerate(("video001", "video002", "video003", "video004"), 1):
            self.service.call(
                "channel_distillation_checkpoint",
                {
                    "taskId": self.task_id,
                    "channelProfileId": self.channel_id,
                    "bindingProof": self.proof,
                    "distillationId": "distill-fusion-001",
                    "sourcePackageId": ids[platform_id],
                    "status": "SUCCEEDED",
                    "analysis": sample_analysis(ids[platform_id], f"fusion-{number}"),
                },
            )
        finalized = self.service.call(
            "channel_distillation_finalize",
            {
                "taskId": self.task_id,
                "channelProfileId": self.channel_id,
                "bindingProof": self.proof,
                "distillationId": "distill-fusion-001",
                "profiles": [
                    aggregate_profile("reference-one", [ids["video001"], ids["video002"]]),
                    aggregate_profile("reference-two", [ids["video003"], ids["video004"]]),
                ],
                "accountRequirements": account_requirements(),
                "qualityGate": quality_gate(),
                "fusionProfile": {
                    "averagingUsed": False,
                    "segmentSplicingUsed": False,
                    "contributions": [
                        {"referenceId": "reference-one", "role": "story-engine", "weight": 60, "functions": ["因果推进"]},
                        {"referenceId": "reference-two", "role": "packaging-and-rhythm", "weight": 40, "functions": ["承诺包装与节奏"]},
                    ],
                    "recomposedCausalEngine": "用新的角色关系和事件因果统一承载两个频道贡献的功能。",
                },
            },
        )
        self.assertEqual(2, len(finalized["outputs"]["referenceProfiles"]))
        self.assertEqual(2, len(finalized["outputs"]["runtimeProfiles"]))
        invalid = json.loads(json.dumps(references))
        invalid[1]["weight"] = 30
        self.assert_tool_error(
            "REFERENCE_WEIGHT_TOTAL_INVALID",
            lambda: self.service.call(
                "channel_distillation_prepare",
                {
                    "taskId": self.task_id,
                    "channelProfileId": self.channel_id,
                    "bindingProof": self.proof,
                    "distillationId": "distill-fusion-invalid",
                    "mode": "fusion",
                    "references": invalid,
                },
            ),
        )


if __name__ == "__main__":
    unittest.main()
