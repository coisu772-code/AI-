from __future__ import annotations

import itertools
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
from stage4_support import MARKETS, PipelineContext, candidate, create_service  # noqa: E402
from test_stage5_channel_distillation import (  # noqa: E402
    account_requirements,
    aggregate_profile,
    quality_gate as distillation_quality_gate,
    sample_analysis,
)
from test_stage5_video_deconstruction import (  # noqa: E402
    deconstruction_analysis,
    final_quality_gate,
    fixture_adapter,
)


SOURCE_DIMENSIONS = (
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
)
SCORE_KEYS = (
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
)


def source_analysis(source_package_id: str) -> dict[str, object]:
    fact_id = "novel-fact-001"
    conclusion_id = "novel-conclusion-001"
    return {
        "analysisBuckets": {
            "originalFacts": [
                {
                    "factId": fact_id,
                    "statement": "规范正文包含受限行动、关系变化和完整回报。",
                    "evidenceRefs": [{"sourcePackageId": source_package_id, "locator": "content.txt#p0001-p0004"}],
                }
            ],
            "analysisConclusions": [
                {
                    "conclusionId": conclusion_id,
                    "statement": "可迁移的是受限行动推动关系变化的功能，不是事件表面。",
                    "evidenceFactIds": [fact_id],
                    "confidence": 0.92,
                }
            ],
            "transferableMethods": [
                {
                    "methodId": "novel-method-001",
                    "method": "用明确限制迫使人物通过连续验证建立新关系。",
                    "evidenceConclusionIds": [conclusion_id],
                    "applicationConditions": ["必须重建人物、世界规则、事件因果、高潮和结局"],
                }
            ],
            "prohibitedCopy": [
                {
                    "boundaryId": "novel-boundary-001",
                    "description": "不得复制原句、专名、完整事件顺序或单一作品主线。",
                    "categories": ["sentences", "proper-names", "complete-event-order", "single-work-mainline"],
                }
            ],
            "unknowns": [
                {
                    "unknownId": "novel-unknown-001",
                    "statement": "资料不能证明真实读者人口和商业转化数据。",
                    "reason": "没有所有者后台数据。",
                }
            ],
        },
        "dimensions": {
            key: {"summary": f"{key} 已由规范正文证据支持", "evidenceFactIds": [fact_id]}
            for key in SOURCE_DIMENSIONS
        },
        "qualityChecks": {
            "passed": True,
            "hardFailures": [],
            "fiveBucketsSeparated": True,
            "evidenceTraceable": True,
            "functionsMapped": True,
            "credibilityBoundaryExplicit": True,
            "copyBoundariesExplicit": True,
        },
    }


def direction(
    number: int,
    references: list[dict[str, object]],
    method_ids: dict[str, str],
    required_sections: list[str],
) -> dict[str, object]:
    contributions = []
    table = []
    shares = [50, 50] if len(references) == 2 else [100]
    for reference, share in zip(references, shares, strict=True):
        source_key = str(reference["sourceKey"])
        method_id = method_ids[source_key]
        contributions.append(
            {
                "sourceKey": source_key,
                "role": reference["role"],
                "weight": reference["weight"],
                "transferableFunctionIds": [method_id],
                "newImplementation": f"方向 {number} 把该功能改造成全新的行动约束与关系结果。",
                "segmentShare": False,
            }
        )
        table.append(
            {
                "nodeId": f"node-{number}-{len(table) + 1}",
                "sourceKey": source_key,
                "sourceFunctionId": method_id,
                "sourceFunction": "建立承诺、限制、推进或阶段回报",
                "sourceImplementationSummary": "来源通过其自身人物和事件完成该功能。",
                "newImplementation": f"方向 {number} 由新主角在新规则下付出代价并改变关系。",
                "newCausality": f"验证行动 {number} 触发资源变化，资源变化迫使双方调整，最终累积为新高潮。",
                "emotionPosition": "从好奇经受压到获得有过程的满足",
                "lengthShare": share,
                "sameEventSequence": False,
            }
        )
    scores = {key: 8.6 + number / 100 for key in SCORE_KEYS}
    scores["productionDifficulty"] = 4 + number / 10
    return {
        "directionId": f"direction-{number:02d}",
        "provisionalTitle": f"原创方向 {number}",
        "oneSentenceHook": f"一个受规则约束的普通人通过第 {number} 种验证路径重建失衡关系。",
        "protagonist": {"identity": f"新职业身份 {number}", "pointOfView": "limited-first-person" if number % 2 else "limited-third-person"},
        "coreGoal": f"在明确权限边界内完成可验证目标 {number}",
        "coreConflict": f"资源、时间、制度与价值选择共同形成冲突 {number}",
        "storyEngine": f"验证—协商—局部扩展—新约束—再调整的引擎 {number}",
        "audiencePsychologicalReward": "快速理解局面、看到真实进展，并获得有因果的关系与情绪回报。",
        "emotionalRoute": f"疑虑→受限尝试→局部信任→代价→共同选择→完整满足 {number}",
        "channelFitReason": "保留清楚承诺、阶段满足和完整收束，但人物、关系、规则和事件全部重建。",
        "substantiveDifferences": [f"主角视角差异 {number}", f"规则约束差异 {number}", f"故事引擎与成长路径差异 {number}"],
        "logicRisks": ["必须维持权限与影响规模匹配"],
        "serializationPotential": "每轮扩展引入新约束，可形成连续但不重复的状态变化。",
        "productionDifficulty": "中等；主要依靠人物、场景和可视化证据推进。",
        "unifiedCausalEngine": f"方向 {number} 以一个核心目标统摄全部来源功能，所有节点都由新世界规则连续触发。",
        "charactersAndRelations": ["主角与合作方从互不信任转为有边界协作", "阻力方因利益和信息限制做出可理解决定"],
        "worldRules": ["只有经过独立验证的信息可以改变正式决定", "每次扩大行动都消耗时间、信誉或资源"],
        "learningPlan": {
            "topicFunction": "学习普通人面对可理解制度约束时获得掌控感的题材功能",
            "structure": "学习承诺—行动—新信息—阶段回报—完整收束的功能结构",
            "rhythm": "学习每一阶段都有真实状态变化的节奏",
            "expression": "学习清楚、短句、因果先行的表达方式，但不复制措辞",
            "audiencePayoff": "学习快速理解、阶段满足和完整收束的观众回报",
        },
        "sourceContributions": contributions,
        "functionalIsomorphism": table,
        "credibilityAudit": [
            {
                "questionId": f"q{question}",
                "passed": True,
                "answer": f"方向 {number} 对可信度问题 {question} 有明确的新因果解释。",
                "evidence": "由人物目标、能力限制、资源、权限、阻力逻辑和连续状态变化共同支持。",
            }
            for question in range(1, 11)
        ],
        "scaleControl": {
            "issueScale": "社区级可验证决策",
            "identityCapacity": "普通专业人员可以影响但不能单独决定",
            "resources": "有限档案、合作网络和公开流程",
            "authority": "只能提出和验证，最终决策由正式机构完成",
            "rationalActorBarrier": "其他人受信息、时间、利益与责任边界限制",
            "passed": True,
        },
        "oppositionLogic": {
            "ownGoal": "在截止期内控制责任与成本",
            "interest": "避免未经验证的信息造成额外风险",
            "knownInformation": "只掌握不完整记录",
            "reasoningBasis": "依据现有程序和有限信息行动",
            "constraints": "预算、期限、责任和公开监督",
            "understandableWrongDecision": "过度保守但不是无理由作恶",
            "passed": True,
        },
        "protagonistCapability": {
            "source": "长期职业训练和本地协作经验",
            "scope": "整理、验证和沟通信息",
            "limit": "不能越权决策，也不能单独取得全部资源",
            "cost": "时间、信誉和关系压力",
            "growth": "从独自验证成长为建立可复用协作流程",
            "passed": True,
        },
        "resultProcess": [
            {"stageId": stage, "action": f"执行 {stage} 阶段的具体行动", "stateChange": f"状态在 {stage} 后发生可验证变化"}
            for stage in ("verify", "stabilize", "expand", "new-problem", "adjust", "re-expand")
        ],
        "antiCopyAudit": {
            "originalSentencesCopied": False,
            "properNamesCopied": False,
            "completeEventOrderCopied": False,
            "singleWorkMainlineCopied": False,
            "segmentSplicingUsed": False,
            "oneCausalEngineRebuilt": True,
        },
        "disqualifiers": [],
        "scores": scores,
        "accountRequirementCoverage": [
            {"requirement": item, "status": "COVERED", "implementation": f"方向 {number} 用新因果实现观众回报：{item}"}
            for item in required_sections
        ],
    }


def pairwise(direction_ids: list[str]) -> list[dict[str, object]]:
    return [
        {
            "directionA": left,
            "directionB": right,
            "differenceCategories": ["protagonist-pov", "rule-constraint", "story-engine-growth"],
            "cosmeticOnly": False,
            "substantiallyDifferent": True,
            "explanation": "两方向在主角视角、世界约束、决策链和成长引擎上实质不同，不是职业地点换名。",
        }
        for left, right in itertools.combinations(direction_ids, 2)
    ]


def final_quality() -> dict[str, object]:
    return {
        "passed": True,
        "hardFailures": [],
        "exactlyEightDirections": True,
        "allDirectionsDisplayed": True,
        "pairwiseSubstantiveDifference": True,
        "credibilityAuditsComplete": True,
        "sourceRolesAndWeightsApplied": True,
        "unifiedCausalEnginesRebuilt": True,
        "antiCopyBoundary": True,
        "topThreeRanked": True,
        "manualConfirmationStillRequired": True,
    }


@unittest.skip("legacy original-imitation tools were retired from the active plugin surface")
class OriginalImitationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="oi-")
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
                "locator": "https://www.youtube.com/channel/UCIMITATION",
                "platformId": "UCIMITATION",
                "title": "Synthetic Imitation Reference",
            },
            {
                "kind": "youtube-video",
                "locator": "https://www.youtube.com/watch?v=imitvideo01",
                "platformId": "imitvideo01",
                "channelId": "UCIMITATION",
            },
            {
                "kind": "youtube-video",
                "locator": "https://www.youtube.com/watch?v=imitvideo02",
                "platformId": "imitvideo02",
                "channelId": "UCIMITATION",
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
        self.service.sources.adapter_factory = None
        novel_prepared = self.service.call(
            "source_add_prepare",
            {
                "taskId": self.task_id,
                "channelProfileId": self.channel_id,
                "bindingProof": self.proof,
                "inputs": [
                    {
                        "text": "这是一个用于原创仿写验收的合成小说正文。人物在明确限制下连续验证信息，关系随真实行动变化，最后形成完整回报。" * 4,
                        "title": "Synthetic Novel",
                        "language": "zh-CN",
                    }
                ],
            },
        )
        self.service.call(
            "source_add_confirm",
            {
                "taskId": self.task_id,
                "channelProfileId": self.channel_id,
                "bindingProof": self.proof,
                "acquisitionJobId": novel_prepared["acquisitionJobId"],
                "planHash": novel_prepared["planHash"],
                "confirmation": {"confirmed": True},
            },
        )
        self.service.sources.adapter_factory = fixture_adapter
        rows = self.service.call("source_search", {"channelProfileId": self.channel_id, "limit": 20})["sources"]
        result = {
            row["platform_id"]: row["source_package_id"]
            for row in rows
        }
        novel_row = next(
            (row for row in rows if row["platform_id"] is None),
            None,
        )
        if novel_row is None:
            self.fail(f"pasted-text fixture missing: {rows!r}")
        result["imitnovel01"] = novel_row["source_package_id"]
        return result

    def _freeze_distillation(self) -> str:
        distillation_id = "imit-distillation-001"
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
                        "referenceId": "imit-reference",
                        "channelSourcePackageId": self.ids["UCIMITATION"],
                        "videoSourcePackageIds": [self.ids["imitvideo01"], self.ids["imitvideo02"]],
                        "role": "target-account-pattern",
                    }
                ],
            },
        )
        for index, source_id in enumerate((self.ids["imitvideo01"], self.ids["imitvideo02"]), 1):
            self.service.call(
                "channel_distillation_checkpoint",
                {
                    "taskId": self.task_id,
                    "channelProfileId": self.channel_id,
                    "bindingProof": self.proof,
                    "distillationId": distillation_id,
                    "sourcePackageId": source_id,
                    "status": "SUCCEEDED",
                    "analysis": sample_analysis(source_id, f"imit-{index}"),
                },
            )
        self.service.call(
            "channel_distillation_finalize",
            {
                "taskId": self.task_id,
                "channelProfileId": self.channel_id,
                "bindingProof": self.proof,
                "distillationId": distillation_id,
                "profiles": [aggregate_profile("imit-reference", [self.ids["imitvideo01"], self.ids["imitvideo02"]])],
                "accountRequirements": account_requirements(),
                "qualityGate": distillation_quality_gate(),
            },
        )
        return distillation_id

    def _freeze_video_analysis(self, distillation_id: str) -> str:
        deconstruction_id = "imit-video-analysis"
        self.service.call(
            "video_deconstruction_prepare",
            {
                "taskId": self.task_id,
                "channelProfileId": self.channel_id,
                "bindingProof": self.proof,
                "deconstructionId": deconstruction_id,
                "mode": "single",
                "videos": [{"sourcePackageId": self.ids["imitvideo01"], "role": "video-expression-reference"}],
                "distillationId": distillation_id,
            },
        )
        self.service.call(
            "video_deconstruction_checkpoint",
            {
                "taskId": self.task_id,
                "channelProfileId": self.channel_id,
                "bindingProof": self.proof,
                "deconstructionId": deconstruction_id,
                "sourcePackageId": self.ids["imitvideo01"],
                "status": "SUCCEEDED",
                "analysis": deconstruction_analysis(
                    self.ids["imitvideo01"],
                    "imitvideo",
                    required_sections=["承诺兑现链", "观众心理回报"],
                ),
            },
        )
        self.service.call(
            "video_deconstruction_finalize",
            {
                "taskId": self.task_id,
                "channelProfileId": self.channel_id,
                "bindingProof": self.proof,
                "deconstructionId": deconstruction_id,
                "qualityGate": final_quality_gate(),
            },
        )
        return deconstruction_id

    def _prepare_full(self) -> tuple[str, list[dict[str, object]], dict[str, str], list[str]]:
        distillation_id = self._freeze_distillation()
        deconstruction_id = self._freeze_video_analysis(distillation_id)
        imitation_id = "original-imitation-001"
        prepared = self.service.call(
            "original_imitation_prepare",
            {
                "taskId": self.task_id,
                "channelProfileId": self.channel_id,
                "bindingProof": self.proof,
                "imitationId": imitation_id,
                "references": [
                    {"inputKind": "video-analysis", "deconstructionId": deconstruction_id, "role": "structure-and-payoff", "weight": 40},
                    {"inputKind": "canonical-source", "sourcePackageId": self.ids["imitnovel01"], "role": "relationship-and-world-rules", "weight": 60},
                ],
            },
        )
        self.assertEqual(100, prepared["plan"]["weightTotal"])
        self.assertFalse(prepared["plan"]["weightsAreSegmentShares"])
        self.assertTrue(prepared["confirmationCard"]["accountSpecificRequirements"])
        self.assertEqual(["快速理解", "阶段满足", "完整收束"], prepared["plan"]["requiredSections"])
        read = self.service.call(
            "original_imitation_read_source",
            {
                "taskId": self.task_id,
                "channelProfileId": self.channel_id,
                "bindingProof": self.proof,
                "imitationId": imitation_id,
                "sourcePackageId": self.ids["imitnovel01"],
                "maxParagraphs": 100,
            },
        )
        self.assertTrue(read["complete"])
        self.assertEqual("content.txt", read["canonicalAsset"])
        self.service.call(
            "original_imitation_source_checkpoint",
            {
                "taskId": self.task_id,
                "channelProfileId": self.channel_id,
                "bindingProof": self.proof,
                "imitationId": imitation_id,
                "sourcePackageId": self.ids["imitnovel01"],
                "analysis": source_analysis(self.ids["imitnovel01"]),
            },
        )
        references = prepared["plan"]["references"]
        methods = {
            f"video-analysis:{deconstruction_id}:{self.ids['imitvideo01']}": "method-topic-imitvideo",
            f"canonical-source:{self.ids['imitnovel01']}": "novel-method-001",
        }
        return imitation_id, references, methods, prepared["plan"]["requiredSections"]

    def test_surface_weight_gate_copy_gate_and_manual_confirmation_handoff(self) -> None:
        expected_tools = {
            "original_imitation_capabilities",
            "original_imitation_prepare",
            "original_imitation_read_source",
            "original_imitation_source_checkpoint",
            "original_imitation_direction_checkpoint",
            "original_imitation_directions_finalize",
            "original_imitation_confirm",
            "original_imitation_get",
            "original_imitation_integrity_check",
        }
        self.assertTrue(expected_tools.issubset({item["name"] for item in tool_definitions()}))
        capabilities = self.service.call("original_imitation_capabilities")
        self.assertEqual(8, capabilities["directionCount"])
        self.assertEqual(3, capabilities["topCount"])
        self.assertEqual(100, capabilities["boundaries"]["sourceWeightsTotal"])
        self.assertFalse(capabilities["boundaries"]["segmentSplicing"])

        self.assert_tool_error(
            "IMITATION_WEIGHT_TOTAL_INVALID",
            lambda: self.service.call(
                "original_imitation_prepare",
                {
                    "taskId": self.task_id,
                    "channelProfileId": self.channel_id,
                    "bindingProof": self.proof,
                    "imitationId": "bad-weight",
                    "references": [
                        {"inputKind": "canonical-source", "sourcePackageId": self.ids["imitnovel01"], "role": "only", "weight": 99}
                    ],
                },
            ),
        )

        imitation_id, references, methods, required = self._prepare_full()
        copied = direction(1, references, methods, required)
        copied["antiCopyAudit"]["properNamesCopied"] = True
        self.assert_tool_error(
            "IMITATION_COPY_BOUNDARY_FAILED",
            lambda: self.service.call(
                "original_imitation_direction_checkpoint",
                {
                    "taskId": self.task_id,
                    "channelProfileId": self.channel_id,
                    "bindingProof": self.proof,
                    "imitationId": imitation_id,
                    "directionNumber": 1,
                    "direction": copied,
                },
            ),
        )
        for number in range(1, 9):
            candidate_direction = direction(number, references, methods, required)
            if number == 1:
                candidate_direction["scores"]["logicalPlausibility"] = 7.9
            result = self.service.call(
                "original_imitation_direction_checkpoint",
                {
                    "taskId": self.task_id,
                    "channelProfileId": self.channel_id,
                    "bindingProof": self.proof,
                    "imitationId": imitation_id,
                    "directionNumber": number,
                    "direction": candidate_direction,
                },
            )
            self.assertEqual(f"direction {number}/8", result["progress"])
            self.assertEqual(number != 1, result["eligible"])

        self.assert_tool_error(
            "IMITATION_DISTINCTNESS_INCOMPLETE",
            lambda: self.service.call(
                "original_imitation_directions_finalize",
                {
                    "taskId": self.task_id,
                    "channelProfileId": self.channel_id,
                    "bindingProof": self.proof,
                    "imitationId": imitation_id,
                    "pairwiseDistinctness": [],
                    "qualityGate": final_quality(),
                },
            ),
        )
        direction_ids = [f"direction-{number:02d}" for number in range(1, 9)]
        finalized = self.service.call(
            "original_imitation_directions_finalize",
            {
                "taskId": self.task_id,
                "channelProfileId": self.channel_id,
                "bindingProof": self.proof,
                "imitationId": imitation_id,
                "pairwiseDistinctness": pairwise(direction_ids),
                "qualityGate": final_quality(),
            },
        )
        self.assertEqual(8, len(finalized["selectionCard"]["directions"]))
        self.assertEqual(3, len(finalized["selectionCard"]["top3"]))
        self.assertTrue(finalized["selectionCard"]["manualConfirmationRequired"])
        self.assertFalse(finalized["selectionCard"]["autoSelectionAllowed"])
        eliminated = next(item for item in finalized["selectionCard"]["directions"] if item["directionId"] == "direction-01")
        self.assertFalse(eliminated["eligibility"]["eligible"])
        self.assertNotIn("direction-01", finalized["selectionCard"]["top3"])
        selected = finalized["selectionCard"]["top3"][0]

        self.assert_tool_error(
            "IMITATION_USER_CONFIRMATION_REQUIRED",
            lambda: self.service.call(
                "original_imitation_confirm",
                {
                    "taskId": self.task_id,
                    "channelProfileId": self.channel_id,
                    "bindingProof": self.proof,
                    "imitationId": imitation_id,
                    "directionId": selected,
                    "confirmation": {"confirmed": True, "mode": "auto", "confirmedBy": "user"},
                },
            ),
        )
        confirmed = self.service.call(
            "original_imitation_confirm",
            {
                "taskId": self.task_id,
                "channelProfileId": self.channel_id,
                "bindingProof": self.proof,
                "imitationId": imitation_id,
                "directionId": selected,
                "confirmation": {"confirmed": True, "mode": "review", "confirmedBy": "user", "confirmedAt": "2026-08-05T02:00:00Z"},
            },
        )
        contract = confirmed["writingStyleContract"]
        self.assertEqual("writing-style-contract-v1", contract["contractType"])
        self.assertEqual(selected, contract["selectedDirection"]["directionId"])
        self.assertEqual(100, contract["sourceWeightsTotal"])
        self.assertFalse(contract["weightsAreSegmentShares"])
        self.assertEqual(
            "PASS",
            self.service.call(
                "original_imitation_integrity_check",
                {"channelProfileId": self.channel_id, "imitationId": imitation_id},
            )["status"],
        )

        project_id = "topic-from-original-imitation"
        project = self.service.call(
            "content_project_start",
            {
                "taskId": self.task_id,
                "channelProfileId": self.channel_id,
                "bindingProof": self.proof,
                "projectId": project_id,
                "sourceMode": "imitation",
                "writingStyleContracts": [{"imitationId": imitation_id}],
            },
        )
        self.assertEqual(1, len(project["state"]["styleLocks"]))
        self.assertEqual(2, len(project["state"]["sourceLocks"]))
        source_row = next(
            row
            for row in self.service.call("source_search", {"channelProfileId": self.channel_id, "limit": 20})["sources"]
            if row["source_package_id"] == self.ids["imitnovel01"]
        )
        ctx = PipelineContext(
            self.service,
            self.root,
            self.task_id,
            self.channel_id,
            self.proof,
            project_id,
            source_row,
            MARKETS["zh-CN"],
        )
        topic_candidate = candidate(ctx, 1)
        topic_candidate["styleContractCompliance"] = {
            "selectedDirectionId": selected,
            "unifiedCausalEngineApplied": True,
            "functionalIsomorphismApplied": True,
            "sourceRolesAndWeightsApplied": True,
            "copyBoundaryPassed": True,
        }
        checkpoint = self.service.call(
            "content_topic_checkpoint",
            {
                "taskId": self.task_id,
                "channelProfileId": self.channel_id,
                "bindingProof": self.proof,
                "projectId": project_id,
                "candidateNumber": 1,
                "candidate": topic_candidate,
            },
        )
        self.assertEqual("topic 1/1", checkpoint["progress"])
        frozen_topic = self.service.call(
            "content_topic_finalize",
            {
                "taskId": self.task_id,
                "channelProfileId": self.channel_id,
                "bindingProof": self.proof,
                "projectId": project_id,
                "ranking": ["candidate-01"],
                "selectedCandidateId": "candidate-01",
                "selectionReasons": {"candidate-01": "上游 8 方向选择门已确认，本候选完整扩展该方向。"},
                "confirmation": {"confirmed": True, "mode": "review", "confirmedBy": "user", "confirmedAt": "2026-08-05T03:00:00Z"},
            },
        )
        self.assertEqual("imitation", frozen_topic["package"]["sourceMode"])
        self.assertEqual("confirmed-imitation-direction", frozen_topic["package"]["selection"]["policy"])
        self.assertTrue(
            any(item["targetContractType"] == "writing-style-contract-v1" for item in frozen_topic["package"]["upstream"])
        )

if __name__ == "__main__":
    unittest.main()
