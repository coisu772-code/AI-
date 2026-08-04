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
from test_stage5_channel_distillation import (  # noqa: E402
    account_requirements,
    aggregate_profile,
    quality_gate as distillation_quality_gate,
    sample_analysis,
)


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
            "collectedAt": "2026-08-05T00:00:00Z",
            "adapterId": "synthetic-video-deconstruction-fixture",
            "adapterVersion": "1.0.0",
        },
        "rightsBoundary": {
            "accessLevel": "public-domain",
            "basis": "Synthetic test fixture permits local analysis.",
            "confirmedByUser": False,
        },
        "metadata": {
            "channelId": channel_id,
            "publishedAt": "2026-08-01T00:00:00Z",
            "publicMetrics": {"viewCount": 1000},
        },
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
    paragraphs = [
        f"{platform_id} 的开场直接提出一个可验证的异常关系，并在第一段兑现标题承诺。",
        "第二段让人物采取有成本的行动，明确资源限制和失败风险，不靠突然获得无限能力。",
        "第三段通过新证据改变人物关系和观众理解，交付阶段信息回报而不是原地重复冲突。",
        "第四段完成主要因果与情绪回报，同时说明仍未知的后台留存率和受众人口数据。",
    ]
    content = "\n\n".join(paragraphs)
    timing = json.dumps(
        {
            "schemaVersion": "1.0.0",
            "format": "canonical-text-timing-map",
            "paragraphCount": 4,
            "entries": [
                {"paragraphId": f"p{index:04d}", "startSeconds": (index - 1) * 10, "endSeconds": index * 10}
                for index in range(1, 5)
            ],
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


def deconstruction_analysis(
    source_package_id: str,
    suffix: str,
    *,
    required_sections: list[str] | None = None,
) -> dict[str, object]:
    fact_open = f"fact-open-{suffix}"
    fact_payoff = f"fact-payoff-{suffix}"
    conclusion_structure = f"conclusion-structure-{suffix}"
    conclusion_reward = f"conclusion-reward-{suffix}"
    required_sections = required_sections or []
    return {
        "analysisBuckets": {
            "originalFacts": [
                {
                    "factId": fact_open,
                    "statement": "第一段提出异常关系并兑现标题承诺。",
                    "evidenceRefs": [{"sourcePackageId": source_package_id, "locator": "content.txt#p0001"}],
                },
                {
                    "factId": fact_payoff,
                    "statement": "第三至第四段交付新证据并完成因果和情绪回报。",
                    "evidenceRefs": [{"sourcePackageId": source_package_id, "locator": "content.txt#p0003-p0004"}],
                },
            ],
            "analysisConclusions": [
                {
                    "conclusionId": conclusion_structure,
                    "statement": "文案用承诺、受限行动、新证据、收束形成四步推进。",
                    "evidenceFactIds": [fact_open, fact_payoff],
                    "confidence": 0.94,
                },
                {
                    "conclusionId": conclusion_reward,
                    "statement": "观众回报来自理解变化与因果闭合，不是重复升级。",
                    "evidenceFactIds": [fact_payoff],
                    "confidence": 0.9,
                },
            ],
            "transferableMethods": [
                {
                    "methodId": f"method-topic-{suffix}",
                    "method": "为原创故事建立承诺、受限行动、新证据和独立结局的功能链。",
                    "evidenceConclusionIds": [conclusion_structure],
                    "applicationConditions": ["重建人物、关系、事件因果、高潮和结局"],
                    "downstreamConsumers": ["topic-center"],
                },
                {
                    "methodId": f"method-script-{suffix}",
                    "method": "在段落切换处交付真实信息或情绪状态变化。",
                    "evidenceConclusionIds": [conclusion_reward],
                    "applicationConditions": ["变化必须由本片已锁定故事事实支持"],
                    "downstreamConsumers": ["manuscript-center"],
                },
            ],
            "prohibitedCopy": [
                {
                    "boundaryId": f"boundary-{suffix}",
                    "description": "不得复制原句、专名、完整事件顺序或单一视频主线。",
                    "categories": ["sentences", "proper-names", "complete-event-order", "single-work-mainline"],
                }
            ],
            "unknowns": [
                {
                    "unknownId": f"unknown-{suffix}",
                    "statement": "没有用户提供的 Studio CTR、真实留存率、流量来源和人口数据。",
                    "reason": "公开正文与页面不能证明后台数据。",
                }
            ],
        },
        "dimensions": {
            key: {"summary": f"{key}-{suffix}", "evidenceFactIds": [fact_open, fact_payoff]}
            for key in (
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
            )
        },
        "sectionMap": [
            {
                "sectionId": f"section-open-{suffix}",
                "startParagraphId": "p0001",
                "endParagraphId": "p0002",
                "startSeconds": 0,
                "endSeconds": 20,
                "functions": ["兑现承诺", "建立限制"],
                "audienceExpectation": "理解异常关系与行动代价",
                "progress": "主角从发现异常进入受限行动",
                "audienceReward": "得到第一轮冲突与约束信息",
                "emotionBefore": "好奇",
                "emotionAfter": "紧张",
                "evidenceFactIds": [fact_open],
            },
            {
                "sectionId": f"section-payoff-{suffix}",
                "startParagraphId": "p0003",
                "endParagraphId": "p0004",
                "startSeconds": 20,
                "endSeconds": 40,
                "functions": ["改变理解", "完成收束"],
                "audienceExpectation": "看到行动造成的关系和因果结果",
                "progress": "新证据改变关系并完成主因果",
                "audienceReward": "获得信息回报与完整情绪满足",
                "emotionBefore": "紧张",
                "emotionAfter": "释然",
                "evidenceFactIds": [fact_payoff],
            },
        ],
        "requirementCoverage": [
            {
                "requirement": requirement,
                "status": "COVERED",
                "evidenceRefs": [{"sourcePackageId": source_package_id, "locator": "content.txt#p0001-p0004"}],
                "observation": f"已按账号要求检查 {requirement}，并记录出现方式或明确缺失。",
            }
            for requirement in required_sections
        ],
        "qualityChecks": {
            "passed": True,
            "hardFailures": [],
            "fiveBucketsSeparated": True,
            "evidenceTraceable": True,
            "functionalSectionsMapped": True,
            "timingMappedOrUnknown": True,
            "accountRequirementsCovered": True,
            "copyBoundariesExplicit": True,
        },
    }


def final_quality_gate() -> dict[str, object]:
    return {
        "passed": True,
        "hardFailures": [],
        "independentVideoAnalysis": True,
        "fiveBucketSeparation": True,
        "evidenceTraceability": True,
        "accountRequirementCoverage": True,
        "downstreamHandoff": True,
        "antiCopyBoundary": True,
        "timingIntegrity": True,
    }


class VideoDeconstructionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="vd-")
        self.root = Path(self.temp.name)
        self.service, self.task_id, self.channel_id, self.proof = create_service(
            self.root,
            "zh-CN",
            plugin_root=PLUGIN_ROOT,
            local_tool_service=LocalToolService,
            service_config=ServiceConfig,
        )
        self.service.sources.adapter_factory = fixture_adapter
        self.ids = self._add_sources()

    def tearDown(self) -> None:
        self.temp.cleanup()

    def assert_tool_error(self, code: str, callback) -> ToolError:
        with self.assertRaises(ToolError) as caught:
            callback()
        self.assertEqual(code, caught.exception.code)
        return caught.exception

    def _add_sources(self) -> dict[str, str]:
        inputs = [
            {
                "kind": "reference-channel",
                "locator": "https://www.youtube.com/channel/UCDECONSTRUCTION",
                "platformId": "UCDECONSTRUCTION",
                "title": "Synthetic Reference",
            },
            {
                "kind": "youtube-video",
                "locator": "https://www.youtube.com/watch?v=decompose01",
                "platformId": "decompose01",
                "channelId": "UCDECONSTRUCTION",
            },
            {
                "kind": "youtube-video",
                "locator": "https://www.youtube.com/watch?v=decompose02",
                "platformId": "decompose02",
                "channelId": "UCDECONSTRUCTION",
            },
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
            result[row["platform_id"]] = row["source_package_id"]
        return result

    def _freeze_distillation(self) -> str:
        distillation_id = "d-account"
        self.service.call(
            "channel_distillation_prepare",
            {
                "taskId": self.task_id,
                "channelProfileId": self.channel_id,
                "bindingProof": self.proof,
                "distillationId": distillation_id,
                "mode": "single",
                "references": [
                    {
                        "referenceId": "ref-account",
                        "channelSourcePackageId": self.ids["UCDECONSTRUCTION"],
                        "videoSourcePackageIds": [self.ids["decompose01"], self.ids["decompose02"]],
                        "role": "account-pattern-source",
                    }
                ],
            },
        )
        for index, platform_id in enumerate(("decompose01", "decompose02"), 1):
            self.service.call(
                "channel_distillation_checkpoint",
                {
                    "taskId": self.task_id,
                    "channelProfileId": self.channel_id,
                    "bindingProof": self.proof,
                    "distillationId": distillation_id,
                    "sourcePackageId": self.ids[platform_id],
                    "status": "SUCCEEDED",
                    "analysis": sample_analysis(self.ids[platform_id], f"account-{index}"),
                },
            )
        self.service.call(
            "channel_distillation_finalize",
            {
                "taskId": self.task_id,
                "channelProfileId": self.channel_id,
                "bindingProof": self.proof,
                "distillationId": distillation_id,
                "profiles": [
                    aggregate_profile(
                        "ref-account",
                        [self.ids["decompose01"], self.ids["decompose02"]],
                    )
                ],
                "accountRequirements": account_requirements(),
                "qualityGate": distillation_quality_gate(),
            },
        )
        return distillation_id

    def test_surface_single_account_requirements_canonical_read_freeze_and_handoff(self) -> None:
        names = {item["name"] for item in tool_definitions()}
        expected = {
            "video_deconstruction_capabilities",
            "video_deconstruction_prepare",
            "video_deconstruction_read_source",
            "video_deconstruction_checkpoint",
            "video_deconstruction_finalize",
            "video_deconstruction_get",
            "video_deconstruction_integrity_check",
        }
        self.assertTrue(expected.issubset(names))
        capabilities = self.service.call("video_deconstruction_capabilities")
        self.assertEqual("available", capabilities["interfaces"]["video-analysis"])
        self.assertEqual("available-via-original-imitation-writing", capabilities["interfaces"]["style-imitation"])

        distillation_id = self._freeze_distillation()
        prepared = self.service.call(
            "video_deconstruction_prepare",
            {
                "taskId": self.task_id,
                "channelProfileId": self.channel_id,
                "bindingProof": self.proof,
                "deconstructionId": "deconstruction-single-001",
                "mode": "single",
                "videos": [{"sourcePackageId": self.ids["decompose01"], "role": "primary-reference"}],
                "distillationId": distillation_id,
            },
        )
        self.assertTrue(prepared["confirmationCard"]["accountSpecificRequirements"])
        self.assertFalse(prepared["confirmationCard"]["rawSubtitleWillBeReadOrStored"])
        self.assertEqual(["承诺兑现链", "观众心理回报"], prepared["plan"]["requiredSections"])

        canonical = self.service.call(
            "video_deconstruction_read_source",
            {
                "taskId": self.task_id,
                "channelProfileId": self.channel_id,
                "bindingProof": self.proof,
                "deconstructionId": "deconstruction-single-001",
                "sourcePackageId": self.ids["decompose01"],
                "startParagraph": 1,
                "maxParagraphs": 10,
            },
        )
        self.assertEqual(4, canonical["totalParagraphs"])
        self.assertTrue(canonical["complete"])
        self.assertTrue(canonical["timingMapAvailable"])
        self.assertFalse(canonical["rawSubtitleReadOrStored"])
        self.assertEqual("p0001", canonical["paragraphs"][0]["paragraphId"])

        invalid = deconstruction_analysis(self.ids["decompose01"], "invalid")
        invalid["requirementCoverage"] = []
        self.assert_tool_error(
            "ACCOUNT_REQUIREMENT_COVERAGE_REQUIRED",
            lambda: self.service.call(
                "video_deconstruction_checkpoint",
                {
                    "taskId": self.task_id,
                    "channelProfileId": self.channel_id,
                    "bindingProof": self.proof,
                    "deconstructionId": "deconstruction-single-001",
                    "sourcePackageId": self.ids["decompose01"],
                    "status": "SUCCEEDED",
                    "analysis": invalid,
                },
            ),
        )
        self.service.call(
            "video_deconstruction_checkpoint",
            {
                "taskId": self.task_id,
                "channelProfileId": self.channel_id,
                "bindingProof": self.proof,
                "deconstructionId": "deconstruction-single-001",
                "sourcePackageId": self.ids["decompose01"],
                "status": "SUCCEEDED",
                "analysis": deconstruction_analysis(
                    self.ids["decompose01"],
                    "single",
                    required_sections=["承诺兑现链", "观众心理回报"],
                ),
            },
        )
        finalized = self.service.call(
            "video_deconstruction_finalize",
            {
                "taskId": self.task_id,
                "channelProfileId": self.channel_id,
                "bindingProof": self.proof,
                "deconstructionId": "deconstruction-single-001",
                "qualityGate": final_quality_gate(),
            },
        )
        self.assertEqual("1/1 succeeded", finalized["completionCard"]["videoDeconstruction"])
        package = self.service.video_analysis.analysis_package(
            channel_profile_id=self.channel_id,
            deconstruction_id="deconstruction-single-001",
        )
        self.assertEqual("video-copy-deconstruction", package["analysisKind"])
        self.assertEqual(1, len(package["videoAnalyses"]))
        self.assertTrue(package["downstreamViews"]["topicCenter"]["transferableMethods"])
        self.assertTrue(package["downstreamViews"]["manuscriptCenter"]["transferableMethods"])
        self.assertEqual(
            "PASS",
            self.service.call(
                "video_deconstruction_integrity_check",
                {"channelProfileId": self.channel_id, "deconstructionId": "deconstruction-single-001"},
            )["status"],
        )
        project = self.service.call(
            "content_project_start",
            {
                "taskId": self.task_id,
                "channelProfileId": self.channel_id,
                "bindingProof": self.proof,
                "projectId": "topic-from-video-deconstruction",
                "sourceMode": "single-reference",
                "analysisPackages": [{"deconstructionId": "deconstruction-single-001"}],
            },
        )
        lock = project["state"]["analysisLocks"][0]
        self.assertEqual("deconstruction-single-001", lock["deconstructionId"])
        self.assertEqual("video-copy-deconstruction", lock["analysisKind"])

    def test_compare_keeps_video_analyses_independent_and_multi_route_consumes_package(self) -> None:
        self.service.call(
            "video_deconstruction_prepare",
            {
                "taskId": self.task_id,
                "channelProfileId": self.channel_id,
                "bindingProof": self.proof,
                "deconstructionId": "deconstruction-compare-001",
                "mode": "compare",
                "videos": [
                    {"sourcePackageId": self.ids["decompose01"], "role": "opening-model"},
                    {"sourcePackageId": self.ids["decompose02"], "role": "payoff-model"},
                ],
            },
        )
        for index, platform_id in enumerate(("decompose01", "decompose02"), 1):
            self.service.call(
                "video_deconstruction_checkpoint",
                {
                    "taskId": self.task_id,
                    "channelProfileId": self.channel_id,
                    "bindingProof": self.proof,
                    "deconstructionId": "deconstruction-compare-001",
                    "sourcePackageId": self.ids[platform_id],
                    "status": "SUCCEEDED",
                    "analysis": deconstruction_analysis(self.ids[platform_id], f"compare-{index}"),
                },
            )
        finalized = self.service.call(
            "video_deconstruction_finalize",
            {
                "taskId": self.task_id,
                "channelProfileId": self.channel_id,
                "bindingProof": self.proof,
                "deconstructionId": "deconstruction-compare-001",
                "comparison": {
                    "sharedFunctions": [
                        {
                            "statement": "承诺、受限行动、新证据、回报形成推进链",
                            "evidenceSourcePackageIds": [self.ids["decompose01"], self.ids["decompose02"]],
                        }
                    ],
                    "videoDifferences": [
                        {"sourcePackageId": self.ids["decompose01"], "difference": "开场功能权重更高"},
                        {"sourcePackageId": self.ids["decompose02"], "difference": "阶段回报功能权重更高"},
                    ],
                    "nonTransferableDifferences": ["每条视频的具体人物、专名和事件顺序"],
                    "eachVideoKeptIndependent": True,
                    "averagingUsed": False,
                    "segmentSplicingUsed": False,
                },
                "qualityGate": final_quality_gate(),
            },
        )
        self.assertEqual("2/2 succeeded", finalized["completionCard"]["videoDeconstruction"])
        package = self.service.video_analysis.analysis_package(
            channel_profile_id=self.channel_id,
            deconstruction_id="deconstruction-compare-001",
        )
        self.assertEqual(2, len(package["videoAnalyses"]))
        self.assertTrue(package["comparison"]["eachVideoKeptIndependent"])
        self.assertFalse(package["comparison"]["averagingUsed"])
        self.assertFalse(package["comparison"]["segmentSplicingUsed"])
        project = self.service.call(
            "content_project_start",
            {
                "taskId": self.task_id,
                "channelProfileId": self.channel_id,
                "bindingProof": self.proof,
                "projectId": "topic-from-multi-video-deconstruction",
                "sourceMode": "multi-reference",
                "analysisPackages": [{"deconstructionId": "deconstruction-compare-001"}],
            },
        )
        self.assertEqual("compare", project["state"]["analysisLocks"][0]["mode"])

    def test_transferable_method_requires_explicit_downstream_consumer(self) -> None:
        self.service.call(
            "video_deconstruction_prepare",
            {
                "taskId": self.task_id,
                "channelProfileId": self.channel_id,
                "bindingProof": self.proof,
                "deconstructionId": "deconstruction-invalid-consumer",
                "mode": "single",
                "videos": [{"sourcePackageId": self.ids["decompose01"]}],
            },
        )
        analysis = deconstruction_analysis(self.ids["decompose01"], "consumer")
        del analysis["analysisBuckets"]["transferableMethods"][0]["downstreamConsumers"]
        self.assert_tool_error(
            "DOWNSTREAM_CONSUMERS_REQUIRED",
            lambda: self.service.call(
                "video_deconstruction_checkpoint",
                {
                    "taskId": self.task_id,
                    "channelProfileId": self.channel_id,
                    "bindingProof": self.proof,
                    "deconstructionId": "deconstruction-invalid-consumer",
                    "sourcePackageId": self.ids["decompose01"],
                    "status": "SUCCEEDED",
                    "analysis": analysis,
                },
            ),
        )


if __name__ == "__main__":
    unittest.main()
