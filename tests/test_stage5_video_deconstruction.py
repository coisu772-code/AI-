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
from stage4_support import MARKETS, PipelineContext, candidate, create_service, finalize_manuscript  # noqa: E402
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
            {
                "kind": "novel-web",
                "locator": "https://example.test/textstory01",
                "platformId": "textstory01",
                "title": "Synthetic Uploaded Text Equivalent",
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

    def test_unified_content_deconstruction_accepts_text_and_direct_rewrite_route(self) -> None:
        names = {item["name"] for item in tool_definitions()}
        expected = {
            "content_deconstruction_capabilities",
            "content_deconstruction_prepare",
            "content_deconstruction_read_source",
            "content_deconstruction_checkpoint",
            "content_deconstruction_finalize",
            "content_deconstruction_get",
            "content_deconstruction_integrity_check",
        }
        self.assertTrue(expected.issubset(names))
        capabilities = self.service.call("content_deconstruction_capabilities")
        self.assertEqual("available", capabilities["interfaces"]["content-deconstruction"])
        self.assertIn("local-file", capabilities["platforms"])
        self.assertIn("novel-web", capabilities["platforms"])

        source_id = self.ids["textstory01"]
        self.service.call(
            "content_deconstruction_prepare",
            {
                "taskId": self.task_id,
                "channelProfileId": self.channel_id,
                "bindingProof": self.proof,
                "deconstructionId": "content-text-single-001",
                "mode": "single",
                "sources": [{"sourcePackageId": source_id, "role": "primary-structure"}],
            },
        )
        canonical = self.service.call(
            "content_deconstruction_read_source",
            {
                "taskId": self.task_id,
                "channelProfileId": self.channel_id,
                "bindingProof": self.proof,
                "deconstructionId": "content-text-single-001",
                "sourcePackageId": source_id,
                "maxParagraphs": 10,
            },
        )
        self.assertTrue(canonical["complete"])
        analysis = deconstruction_analysis(source_id, "generic-text")
        analysis["analysisBuckets"]["transferableMethods"][0]["downstreamConsumers"] = ["content-rewrite"]
        analysis["analysisBuckets"]["transferableMethods"][1]["downstreamConsumers"] = ["content-review-edit"]
        self.service.call(
            "content_deconstruction_checkpoint",
            {
                "taskId": self.task_id,
                "channelProfileId": self.channel_id,
                "bindingProof": self.proof,
                "deconstructionId": "content-text-single-001",
                "sourcePackageId": source_id,
                "status": "SUCCEEDED",
                "analysis": analysis,
            },
        )
        finalized = self.service.call(
            "content_deconstruction_finalize",
            {
                "taskId": self.task_id,
                "channelProfileId": self.channel_id,
                "bindingProof": self.proof,
                "deconstructionId": "content-text-single-001",
                "qualityGate": final_quality_gate(),
                "deconstructionReportMarkdown": "# 完整拆解报告\n\n" + ("本报告逐段记录素材事实、全局结构、人物功能、因果推进、情绪变化、钩子、节奏、表达方式、优缺点与商业吸引机制。" * 8),
                "transferDirectionsMarkdown": "# 迁移方向选择\n\n" + "\n".join(f"## 方向 {index}\n重建人物、关系、世界参数、事件因果、高潮与结局，保留经证据支持的叙事功能。" for index in range(1, 7)),
            },
        )
        self.assertEqual("1/1 succeeded", finalized["completionCard"]["contentDeconstruction"])
        deconstruction_review_root = Path(finalized["outputs"]["userReviewDocuments"]["directory"])
        self.assertTrue((deconstruction_review_root / "01_原始素材说明.md").is_file())
        self.assertTrue((deconstruction_review_root / "02_完整拆解报告.md").is_file())
        self.assertTrue((deconstruction_review_root / "03_迁移方向选择.md").is_file())
        package = self.service.content_deconstruction.analysis_package(
            channel_profile_id=self.channel_id,
            deconstruction_id="content-text-single-001",
        )
        self.assertEqual("content-deconstruction", package["analysisKind"])
        self.assertEqual(1, len(package["sourceAnalyses"]))
        self.assertTrue(package["downstreamViews"]["rewrite"]["transferableMethods"])
        self.assertTrue(package["downstreamViews"]["productionText"]["transferableMethods"])
        self.assertEqual(
            "PASS",
            self.service.call(
                "content_deconstruction_integrity_check",
                {"channelProfileId": self.channel_id, "deconstructionId": "content-text-single-001"},
            )["status"],
        )

        project = self.service.call(
            "content_project_start",
            {
                "taskId": self.task_id,
                "channelProfileId": self.channel_id,
                "bindingProof": self.proof,
                "projectId": "direct-rewrite-from-text",
                "sourceMode": "direct-rewrite",
                "sourcePackages": [{"sourcePackageId": source_id}],
                "analysisPackages": [{"deconstructionId": "content-text-single-001"}],
            },
        )
        self.assertEqual("direct-rewrite", project["state"]["sourceMode"])
        self.assertEqual("content-deconstruction", project["state"]["analysisLocks"][0]["analysisKind"])
        project_review_root = Path(project["state"]["userReviewDocuments"]["directory"])
        self.assertTrue((project_review_root / "01_原始素材说明.md").is_file())
        self.assertTrue((project_review_root / "02_完整拆解报告.md").is_file())
        self.assertTrue((project_review_root / "03_迁移方向选择.md").is_file())
        ctx = PipelineContext(
            self.service,
            self.root,
            self.task_id,
            self.channel_id,
            self.proof,
            "direct-rewrite-from-text",
            {"source_package_id": source_id},
            MARKETS["zh-CN"],
        )
        rewrite_candidate = candidate(ctx, 1)
        rewrite_candidate["sourceTransformationMap"] = [
            {
                "sourcePackageId": source_id,
                "role": "structure-and-pacing-reference",
                "retainedFunction": "保留开场兑现、证据推进和阶段回报的功能顺序。",
                "newImplementation": "重建人物、社区场景、具体证据、行动成本、高潮和结局后果。",
                "newCausalLink": "主角整理维修记录，促使邻居回流，并由公共协议核验推动共管结局。",
                "protectedBoundary": "不复制原句、专名、具体人物关系或完整事件顺序。",
            }
        ]
        self.service.call(
            "content_topic_checkpoint",
            {
                "taskId": self.task_id,
                "channelProfileId": self.channel_id,
                "bindingProof": self.proof,
                "projectId": ctx.project_id,
                "candidateNumber": 1,
                "candidate": rewrite_candidate,
            },
        )
        topic = self.service.call(
            "content_topic_finalize",
            {
                "taskId": self.task_id,
                "channelProfileId": self.channel_id,
                "bindingProof": self.proof,
                "projectId": ctx.project_id,
                "ranking": ["candidate-01"],
                "selectedCandidateId": "candidate-01",
                "selectionReasons": {"candidate-01": "用户请求的唯一单源高贴合仿写方案。"},
                "confirmation": {
                    "confirmed": True,
                    "mode": "review",
                    "confirmedBy": "synthetic-fixture-user",
                    "confirmedAt": "2026-08-07T00:00:00Z",
                },
            },
        )
        self.assertEqual("TOPIC_SELECTED", topic["package"]["status"])
        self.assertEqual("direct-rewrite-request", topic["package"]["selection"]["policy"])
        self.assertEqual(source_id, topic["package"]["candidates"][0]["sourceTransformationMap"][0]["sourcePackageId"])
        manuscript = finalize_manuscript(ctx)
        self.assertEqual("SCRIPT_READY", manuscript["package"]["status"])
        manuscript_documents = {item["documentId"] for item in manuscript["userReviewDocuments"]["documents"]}
        self.assertTrue(
            {"source-summary", "deconstruction-report", "transfer-directions", "rewrite-draft-target", "editorial-review", "revision-log", "final-script-target", "final-script-zh"}.issubset(manuscript_documents)
        )

        second_source_id = self.ids["decompose01"]
        synthesis_deconstruction_id = "content-synthesis-compare-001"
        self.service.call(
            "content_deconstruction_prepare",
            {
                "taskId": self.task_id,
                "channelProfileId": self.channel_id,
                "bindingProof": self.proof,
                "deconstructionId": synthesis_deconstruction_id,
                "mode": "compare",
                "sources": [
                    {"sourcePackageId": source_id, "role": "structure-reference"},
                    {"sourcePackageId": second_source_id, "role": "reward-reference"},
                ],
            },
        )
        for index, current_source_id in enumerate((source_id, second_source_id), 1):
            current_analysis = deconstruction_analysis(current_source_id, f"synthesis-{index}")
            for method in current_analysis["analysisBuckets"]["transferableMethods"]:
                method["downstreamConsumers"] = ["content-rewrite"]
            self.service.call(
                "content_deconstruction_checkpoint",
                {
                    "taskId": self.task_id,
                    "channelProfileId": self.channel_id,
                    "bindingProof": self.proof,
                    "deconstructionId": synthesis_deconstruction_id,
                    "sourcePackageId": current_source_id,
                    "status": "SUCCEEDED",
                    "analysis": current_analysis,
                },
            )
        self.service.call(
            "content_deconstruction_finalize",
            {
                "taskId": self.task_id,
                "channelProfileId": self.channel_id,
                "bindingProof": self.proof,
                "deconstructionId": synthesis_deconstruction_id,
                "comparison": {
                    "sharedFunctions": [
                        {
                            "statement": "两个来源都以可验证信息改变关系和结局。",
                            "evidenceSourcePackageIds": [source_id, second_source_id],
                        }
                    ],
                    "videoDifferences": [
                        {"sourcePackageId": source_id, "difference": "提供文本结构与节奏功能。"},
                        {"sourcePackageId": second_source_id, "difference": "提供阶段回报功能。"},
                    ],
                    "nonTransferableDifferences": ["人物、专名、原句和完整事件顺序"],
                    "eachVideoKeptIndependent": True,
                    "averagingUsed": False,
                    "segmentSplicingUsed": False,
                },
                "qualityGate": final_quality_gate(),
                "deconstructionReportMarkdown": "# 完整拆解报告\n\n" + ("本报告分别拆解两个来源，再比较结构、人物功能、因果、节奏、回报、表达和不可复制边界。" * 10),
                "transferDirectionsMarkdown": "# 迁移方向选择\n\n" + "\n".join(f"## 方向 {index}\n以统一主线重组多来源功能，并重建人物关系、具体事件、高潮行动和完整结局。" for index in range(1, 7)),
            },
        )
        synthesis_project_id = "synthesis-rewrite-from-library"
        self.service.call(
            "content_project_start",
            {
                "taskId": self.task_id,
                "channelProfileId": self.channel_id,
                "bindingProof": self.proof,
                "projectId": synthesis_project_id,
                "sourceMode": "synthesis-rewrite",
                "sourcePackages": [
                    {"sourcePackageId": source_id},
                    {"sourcePackageId": second_source_id},
                ],
                "analysisPackages": [{"deconstructionId": synthesis_deconstruction_id}],
            },
        )
        synthesis_ctx = PipelineContext(
            self.service,
            self.root,
            self.task_id,
            self.channel_id,
            self.proof,
            synthesis_project_id,
            {"source_package_id": source_id},
            MARKETS["zh-CN"],
        )
        synthesis_candidate = candidate(synthesis_ctx, 1)
        synthesis_candidate["sourceTransformationMap"] = [
            {
                "sourcePackageId": source_id,
                "role": "structure-reference",
                "retainedFunction": "使用承诺、行动、证据和结局的功能链。",
                "newImplementation": "为新主角和社区修理铺重建全部事件。",
                "newCausalLink": "维修记录促使居民行动并触发协议核验。",
                "protectedBoundary": "不复制文本来源的原句、专名或事件顺序。",
            },
            {
                "sourcePackageId": second_source_id,
                "role": "reward-reference",
                "retainedFunction": "采用新证据带来阶段认知回报的功能。",
                "newImplementation": "把回报改造成公共服务协议的可信核验。",
                "newCausalLink": "邻居故事汇聚为可验证记录并改变管理决定。",
                "protectedBoundary": "不复制视频来源的人物、表达或具体桥段。",
            },
        ]
        self.service.call(
            "content_topic_checkpoint",
            {
                "taskId": self.task_id,
                "channelProfileId": self.channel_id,
                "bindingProof": self.proof,
                "projectId": synthesis_project_id,
                "candidateNumber": 1,
                "candidate": synthesis_candidate,
            },
        )
        synthesis_topic = self.service.call(
            "content_topic_finalize",
            {
                "taskId": self.task_id,
                "channelProfileId": self.channel_id,
                "bindingProof": self.proof,
                "projectId": synthesis_project_id,
                "ranking": ["candidate-01"],
                "selectedCandidateId": "candidate-01",
                "selectionReasons": {"candidate-01": "用户请求的唯一资料融合仿写方案。"},
                "confirmation": {
                    "confirmed": True,
                    "mode": "review",
                    "confirmedBy": "synthetic-fixture-user",
                    "confirmedAt": "2026-08-07T00:10:00Z",
                },
            },
        )
        self.assertEqual("synthesis-rewrite-request", synthesis_topic["package"]["selection"]["policy"])
        self.assertEqual(2, len(synthesis_topic["package"]["candidates"][0]["sourceTransformationMap"]))

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
