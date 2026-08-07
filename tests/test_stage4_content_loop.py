from __future__ import annotations

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
sys.path.insert(0, str(ROOT / "tools"))

from aivcp_tools.errors import ToolError  # noqa: E402
from aivcp_tools.service import LocalToolService, ServiceConfig, tool_definitions  # noqa: E402
from stage4_support import (  # noqa: E402
    MARKETS,
    build_complete_pipeline,
    candidate,
    create_service,
    finalize_manuscript,
    finalize_publishing,
    finalize_topic,
    manuscript_payload,
    publishing_payload,
    start_topic_context,
    write_png,
)
import check_repository_safety as repository_safety  # noqa: E402
from validate_stage4_packages import validate_stage4_packages  # noqa: E402


SYNTHETIC_THUMBNAIL = ROOT / "contracts" / "examples" / "valid" / "fixtures" / "confirmed-thumbnail-1600x900.png"


class Stage4ContentLoopTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="aivcp-stage4-")
        self.root = Path(self.temp.name)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def context(self, language: str = "en-US"):
        return start_topic_context(
            self.root / language,
            language,
            plugin_root=PLUGIN_ROOT,
            local_tool_service=LocalToolService,
            service_config=ServiceConfig,
        )

    def assert_tool_error(self, code: str, callback) -> ToolError:
        with self.assertRaises(ToolError) as caught:
            callback()
        self.assertEqual(code, caught.exception.code)
        return caught.exception

    def test_installed_surface_exposes_eleven_stage4_tools_and_no_external_action(self) -> None:
        names = {item["name"] for item in tool_definitions()}
        expected = {
            "content_capabilities",
            "content_project_start",
            "content_topic_checkpoint",
            "content_topic_finalize",
            "content_review_document_save",
            "content_review_documents_get",
            "content_manuscript_finalize",
            "content_publishing_finalize",
            "content_project_get",
            "content_integrity_check",
            "content_handoff_check",
        }
        self.assertTrue(expected.issubset(names))
        definitions = {item["name"]: item for item in tool_definitions()}
        self.assertIn("foreignLanguageQualityGate", definitions["content_manuscript_finalize"]["inputSchema"]["required"])
        self.assertIn("storySummaryChinese", definitions["content_publishing_finalize"]["inputSchema"]["required"])
        service, _, _, _ = create_service(
            self.root / "surface", "en-US", plugin_root=PLUGIN_ROOT,
            local_tool_service=LocalToolService, service_config=ServiceConfig,
        )
        capabilities = service.call("content_capabilities")
        self.assertEqual("available", capabilities["extensionInterfaces"]["analysis-package-v1"]["status"])
        extensions = {item["capability"]: item for item in capabilities["extensions"]}
        self.assertEqual("available", extensions["title-generation"]["status"])
        self.assertEqual("content-title-description", extensions["title-generation"]["skillId"])
        self.assertEqual(["manuscript-package"], extensions["title-generation"]["inputContractTypes"])
        self.assertEqual("available", extensions["description-generation"]["status"])
        self.assertEqual("content-title-description", extensions["description-generation"]["skillId"])
        self.assertEqual("available", extensions["thumbnail-generation"]["status"])
        self.assertEqual("content-title-description", extensions["thumbnail-generation"]["skillId"])
        self.assertEqual(["manuscript-package"], extensions["thumbnail-generation"]["inputContractTypes"])
        self.assertTrue(capabilities["userReviewDocuments"]["available"])
        self.assertEqual(11, len(capabilities["userReviewDocuments"]["documentIds"]))
        system = service.call("system_capabilities")
        self.assertTrue(Path(system["storage"]["userDataRoot"]).samefile(self.root / "surface" / "data"))
        self.assertTrue(system["storage"]["largeAssetsStoredUnderUserDataRoot"])
        self.assertTrue(system["storage"]["programUpdatesPreserveUserDataRoot"])
        self.assertFalse(capabilities["boundaries"]["workshop"])
        self.assertFalse(capabilities["boundaries"]["upload"])
        self.assertFalse(capabilities["boundaries"]["longTermLearningWrite"])

    def test_repository_media_exception_is_limited_to_named_synthetic_fixtures(self) -> None:
        fixture = self.root / "contracts" / "examples" / "valid" / "fixtures" / "confirmed-thumbnail-1600x900.png"
        fixture.parent.mkdir(parents=True)
        fixture.write_bytes(b"synthetic")
        forbidden = self.root / "unexpected.png"
        forbidden.write_bytes(b"not allowed")
        original_root = repository_safety.ROOT
        try:
            repository_safety.ROOT = self.root
            errors = repository_safety.check_repository_safety()
            self.assertEqual(["forbidden release file type: unexpected.png"], errors)
            forbidden.unlink()
            self.assertEqual([], repository_safety.check_repository_safety())
        finally:
            repository_safety.ROOT = original_root

    def test_review_documents_are_versioned_in_order_and_freeze_after_manuscript(self) -> None:
        ctx = self.context("zh-CN")
        finalize_topic(ctx)

        def save(document_type: str, content: str):
            return ctx.service.call(
                "content_review_document_save",
                {
                    "taskId": ctx.task_id,
                    "channelProfileId": ctx.channel_id,
                    "bindingProof": ctx.proof,
                    "projectId": ctx.project_id,
                    "documentType": document_type,
                    "content": content,
                },
            )

        self.assert_tool_error(
            "REWRITE_DRAFT_DOCUMENT_REQUIRED",
            lambda: save("revision-log", "# 修改记录\n\n" + "尚未生成初稿，因此该记录必须被拒绝。" * 8),
        )
        first = save("rewrite-draft-target", "第一版完整仿写初稿。" * 20)
        second = save("rewrite-draft-target", "第二版完整仿写初稿。" * 20)
        self.assertEqual(1, first["document"]["version"])
        self.assertEqual(2, second["document"]["version"])
        save("editorial-review", "# 编辑审核报告\n\n" + "逐项检查事实、人物、因果、节奏与语言，记录问题证据和修改建议。" * 8)
        self.assert_tool_error(
            "REWRITE_DRAFT_REVIEW_ALREADY_STARTED",
            lambda: save("rewrite-draft-target", "审核开始后不允许替换来源初稿。" * 20),
        )
        save("revision-log", "# 修改记录与前后对照\n\n" + "位置、修改前、修改后、原因和影响范围均已逐项登记。" * 8)
        self.assert_tool_error(
            "EDITORIAL_REVIEW_REVISION_ALREADY_RECORDED",
            lambda: save("editorial-review", "修改对照完成后不允许替换审核来源。" * 20),
        )
        manuscript = manuscript_payload(ctx)
        for key in ("rewriteDraftText", "editorialReviewMarkdown", "revisionLogMarkdown"):
            manuscript.pop(key)
        final = ctx.service.call(
            "content_manuscript_finalize",
            {
                "taskId": ctx.task_id,
                "channelProfileId": ctx.channel_id,
                "bindingProof": ctx.proof,
                "projectId": ctx.project_id,
                **manuscript,
                "authoringMode": "target-language-native",
            },
        )
        self.assertEqual("SCRIPT_READY", final["package"]["status"])
        self.assert_tool_error(
            "CONTENT_REVIEW_DOCUMENTS_FROZEN",
            lambda: save("revision-log", "正式稿冻结后不能回写早期审核文档。" * 20),
        )

    def test_three_markets_use_the_same_schema_state_machine_and_quality_gates(self) -> None:
        self.assertTrue(SYNTHETIC_THUMBNAIL.is_file())
        for language in MARKETS:
            with self.subTest(language=language):
                ctx = self.context(language)
                result = build_complete_pipeline(ctx, SYNTHETIC_THUMBNAIL)
                self.assertEqual("PASS", result["integrity"]["status"])
                self.assertTrue(result["handoff"]["eligible"])
                self.assertEqual("TOPIC_SELECTED", result["topic"]["package"]["status"])
                self.assertEqual("SCRIPT_READY", result["manuscript"]["package"]["status"])
                self.assertEqual("PUBLISHING_ASSETS_READY", result["publishing"]["package"]["status"])
                self.assertEqual(language, result["manuscript"]["package"]["targetLanguage"])
                expected_foreign_status = "NOT_APPLICABLE" if language.startswith("zh") else "PASSED"
                self.assertEqual(expected_foreign_status, result["manuscript"]["package"]["foreignLanguageQualityGate"]["status"])
                self.assertTrue((Path(result["manuscript"]["packagePath"]) / "foreign-language-quality-gate.json").is_file())
                for stage in ("topic", "manuscript", "publishing"):
                    card = result[stage]["confirmationCard"]
                    self.assertEqual("CHINESE_FIRST_WITH_TARGET_LANGUAGE", card["displayMode"])
                    self.assertIn("chinesePrimary", card)
                    self.assertIn("targetLanguageComparison", card)
                self.assertEqual(5, len(result["publishing"]["package"]["thumbnailCandidates"]))
                review_root = Path(result["publishing"]["userReviewDocuments"]["directory"])
                expected_review_files = {
                    "04_仿写初稿_目标语言.txt",
                    "05_编辑审核报告.md",
                    "06_修改记录与前后对照.md",
                    "07_正式稿_目标语言.txt",
                    "08_正式稿_中文版.txt",
                    "09_标题简介标签_双语审核.md",
                    "10_封面候选与选择结果.md",
                }
                self.assertTrue(expected_review_files.issubset({item.name for item in review_root.iterdir()}))
                packaging_review = (review_root / "09_标题简介标签_双语审核.md").read_text(encoding="utf-8")
                self.assertIn(result["publishing"]["package"]["title"], packaging_review)
                self.assertIn(result["publishing"]["package"]["titleZhTranslation"], packaging_review)
                listed = ctx.service.call(
                    "content_review_documents_get",
                    {"channelProfileId": ctx.channel_id, "projectId": ctx.project_id},
                )
                self.assertTrue(listed["progressReadOnly"])
                self.assertEqual(7, len(listed["documents"]))
                manuscript_root = Path(result["manuscript"]["packagePath"])
                if language.startswith("zh"):
                    self.assertEqual("same-as-target", result["manuscript"]["package"]["auditScript"]["mode"])
                    self.assertFalse((manuscript_root / "chinese-audit-script.json").exists())
                    self.assertFalse((manuscript_root / "chinese-audit-script.txt").exists())
                else:
                    self.assertEqual("backtranslation", result["manuscript"]["package"]["auditScript"]["mode"])
                    self.assertTrue((manuscript_root / "chinese-audit-script.json").is_file())
                    self.assertTrue((manuscript_root / "chinese-audit-script.txt").is_file())
                self.assertEqual(
                    ["production-package", "workshop", "publisher-authorization", "upload", "analytics", "long-term-learning-write"],
                    result["handoff"]["notExecuted"],
                )

    def test_non_chinese_manuscript_requires_independent_foreign_language_gate(self) -> None:
        ctx = self.context("ja-JP")
        finalize_topic(ctx)
        payload = manuscript_payload(ctx)
        for document_type, payload_key in (
            ("rewrite-draft-target", "rewriteDraftText"),
            ("editorial-review", "editorialReviewMarkdown"),
            ("revision-log", "revisionLogMarkdown"),
        ):
            ctx.service.call(
                "content_review_document_save",
                {
                    "taskId": ctx.task_id,
                    "channelProfileId": ctx.channel_id,
                    "bindingProof": ctx.proof,
                    "projectId": ctx.project_id,
                    "documentType": document_type,
                    "content": payload.pop(payload_key),
                },
            )
        payload["foreignLanguageQualityGate"]["independentFromAuthoring"] = False
        self.assert_tool_error(
            "FOREIGN_LANGUAGE_REVIEW_NOT_INDEPENDENT",
            lambda: ctx.service.call(
                "content_manuscript_finalize",
                {
                    "taskId": ctx.task_id,
                    "channelProfileId": ctx.channel_id,
                    "bindingProof": ctx.proof,
                    "projectId": ctx.project_id,
                    **payload,
                    "authoringMode": "target-language-native",
                },
            ),
        )

    def test_user_review_document_tamper_blocks_integrity_and_handoff(self) -> None:
        ctx = self.context("en-US")
        result = build_complete_pipeline(ctx, SYNTHETIC_THUMBNAIL)
        review_root = Path(result["publishing"]["userReviewDocuments"]["directory"])
        revision_log = review_root / "06_修改记录与前后对照.md"
        revision_log.write_text(revision_log.read_text(encoding="utf-8") + "\n未登记篡改\n", encoding="utf-8")
        integrity = ctx.service.call(
            "content_integrity_check",
            {"channelProfileId": ctx.channel_id, "projectId": ctx.project_id},
        )
        self.assertEqual("FAIL", integrity["status"])
        self.assertTrue(
            any(item.get("documentId") == "revision-log" and item.get("issue") == "file-hash" for item in integrity["errors"])
        )
        self.assert_tool_error(
            "CONTENT_HANDOFF_BLOCKED",
            lambda: ctx.service.call(
                "content_handoff_check",
                {"channelProfileId": ctx.channel_id, "projectId": ctx.project_id},
            ),
        )

    def test_committed_three_market_package_chains_remain_valid(self) -> None:
        self.assertEqual([], validate_stage4_packages())

    def test_channel_and_outline_routes_enforce_real_candidate_cardinality(self) -> None:
        ctx = self.context("en-US")
        source_ref = {"sourcePackageId": ctx.source["source_package_id"]}

        channel_project = "channel-ten-candidates"
        ctx.service.call(
            "content_project_start",
            {
                "taskId": ctx.task_id,
                "channelProfileId": ctx.channel_id,
                "bindingProof": ctx.proof,
                "projectId": channel_project,
                "sourceMode": "channel-library",
                "sourcePackages": [source_ref],
            },
        )
        for number in range(1, 10):
            ctx.service.call(
                "content_topic_checkpoint",
                {
                    "taskId": ctx.task_id,
                    "channelProfileId": ctx.channel_id,
                    "bindingProof": ctx.proof,
                    "projectId": channel_project,
                    "candidateNumber": number,
                    "candidate": candidate(ctx, number),
                },
            )
        ranking = [f"candidate-{number:02d}" for number in range(1, 11)]
        reasons = {candidate_id: "Synthetic route cardinality check." for candidate_id in ranking}
        finalize_args = {
            "taskId": ctx.task_id,
            "channelProfileId": ctx.channel_id,
            "bindingProof": ctx.proof,
            "projectId": channel_project,
            "ranking": ranking,
            "selectedCandidateId": ranking[0],
            "selectionReasons": reasons,
            "confirmation": {"confirmed": True, "mode": "review", "confirmedBy": "synthetic-test"},
        }
        self.assert_tool_error(
            "TOPIC_CANDIDATES_INCOMPLETE",
            lambda: ctx.service.call("content_topic_finalize", finalize_args),
        )
        tenth = ctx.service.call(
            "content_topic_checkpoint",
            {
                "taskId": ctx.task_id,
                "channelProfileId": ctx.channel_id,
                "bindingProof": ctx.proof,
                "projectId": channel_project,
                "candidateNumber": 10,
                "candidate": candidate(ctx, 10),
            },
        )
        self.assertEqual("topic 10/10", tenth["progress"])
        channel_topic = ctx.service.call("content_topic_finalize", finalize_args)["package"]
        self.assertEqual(10, channel_topic["checkpoints"]["completedUnits"])
        self.assertEqual(10, len(channel_topic["candidates"]))

        outline_project = "provided-outline-one-candidate"
        ctx.service.call(
            "content_project_start",
            {
                "taskId": ctx.task_id,
                "channelProfileId": ctx.channel_id,
                "bindingProof": ctx.proof,
                "projectId": outline_project,
                "sourceMode": "provided-outline",
                "sourcePackages": [source_ref],
                "providedOutline": "这是一个明确的合成大纲：社区档案员必须在七天内验证一份被遗忘的协议，联合居民保存公共空间；证据公开后，社区以合作方式重新开放场所，并给每位主要人物一个完整结局。该文本仅用于离线接口验收。",
            },
        )
        outline_checkpoint = ctx.service.call(
            "content_topic_checkpoint",
            {
                "taskId": ctx.task_id,
                "channelProfileId": ctx.channel_id,
                "bindingProof": ctx.proof,
                "projectId": outline_project,
                "candidateNumber": 1,
                "candidate": candidate(ctx, 1),
            },
        )
        self.assertEqual("topic 1/1", outline_checkpoint["progress"])

    def test_partial_source_requires_explicit_acceptance_with_limitations(self) -> None:
        service, task_id, channel_id, proof = create_service(
            self.root / "partial", "en-US", plugin_root=PLUGIN_ROOT,
            local_tool_service=LocalToolService, service_config=ServiceConfig,
        )
        item = {"kind": "pasted-text", "locator": "user-input:synthetic-partial", "text": "partial synthetic source"}
        registered = service.sources.register(
            channel_profile_id=channel_id,
            item=item,
            result={
                "sourceType": "pasted-text",
                "status": "PARTIAL",
                "title": "Synthetic partial source",
                "language": "en-US",
                "canonicalLocator": item["locator"],
                "provenance": {"kind": "user-input", "locator": item["locator"], "collectedAt": "2026-08-04T00:00:00Z", "adapterId": "synthetic-partial", "adapterVersion": "1.0.0"},
                "rightsBoundary": {"accessLevel": "user-authorized", "basis": "Synthetic unit fixture.", "confirmedByUser": True},
                "metadata": {"sourceBoundary": "partial synthetic"},
                "assets": [{"role": "normalized", "mediaType": "text/plain", "filename": "content.txt", "data": "partial synthetic source"}],
                "report": {"complete": False, "sourceBoundary": "partial synthetic"},
            },
        )
        args = {
            "taskId": task_id,
            "channelProfileId": channel_id,
            "bindingProof": proof,
            "projectId": "partial-rejected",
            "sourceMode": "market-original",
            "sourcePackages": [{"sourcePackageId": registered["sourcePackageId"]}],
        }
        self.assert_tool_error("PARTIAL_SOURCE_ACCEPTANCE_REQUIRED", lambda: service.call("content_project_start", args))
        args["projectId"] = "partial-accepted"
        args["sourcePackages"] = [{
            "sourcePackageId": registered["sourcePackageId"],
            "acceptPartial": True,
            "acceptedAt": "2026-08-04T00:30:00Z",
            "knownLimitations": ["The final paragraph is absent."],
        }]
        accepted = service.call("content_project_start", args)
        self.assertEqual(1, accepted["confirmationCard"]["partialAcceptedCount"])

    def test_all_missing_analysis_and_imitation_extensions_are_explicitly_unavailable(self) -> None:
        service, task_id, channel_id, proof = create_service(
            self.root / "extensions", "en-US", plugin_root=PLUGIN_ROOT,
            local_tool_service=LocalToolService, service_config=ServiceConfig,
        )
        for mode in ("trend", "single-reference", "multi-reference", "book-deconstruction", "imitation"):
            with self.subTest(mode=mode):
                error = self.assert_tool_error(
                    "CONTENT_EXTENSION_UNAVAILABLE",
                    lambda mode=mode: service.call(
                        "content_project_start",
                        {"taskId": task_id, "channelProfileId": channel_id, "bindingProof": proof, "projectId": f"missing-{mode}", "sourceMode": mode},
                    ),
                )
                self.assertIn("requiredInterface", error.details)

    def test_long_term_learning_write_is_out_of_scope(self) -> None:
        service, task_id, channel_id, proof = create_service(
            self.root / "learning", "en-US", plugin_root=PLUGIN_ROOT,
            local_tool_service=LocalToolService, service_config=ServiceConfig,
        )
        self.assert_tool_error(
            "LONG_TERM_LEARNING_FORBIDDEN",
            lambda: service.call(
                "content_project_start",
                {
                    "taskId": task_id,
                    "channelProfileId": channel_id,
                    "bindingProof": proof,
                    "projectId": "forbidden-learning",
                    "sourceMode": "market-original",
                    "longTermLearning": {"scope": "channel_default", "write": True},
                },
            ),
        )

    def test_unconfirmed_topic_cannot_freeze_or_handoff(self) -> None:
        ctx = self.context()
        self.assert_tool_error("TOPIC_CONFIRMATION_REQUIRED", lambda: finalize_topic(ctx, confirmed=False))
        self.assert_tool_error(
            "CONTENT_CONFIRMATION_CHAIN_INCOMPLETE",
            lambda: ctx.service.call("content_handoff_check", {"channelProfileId": ctx.channel_id, "projectId": ctx.project_id}),
        )

    def test_bad_package_hash_is_detected_after_freeze(self) -> None:
        ctx = self.context()
        result = build_complete_pipeline(ctx, SYNTHETIC_THUMBNAIL)
        topic_manifest = Path(result["topic"]["packagePath"]) / "manifest.json"
        topic = json.loads(topic_manifest.read_text(encoding="utf-8"))
        topic["storyFacts"]["ending"] = "tampered after freeze"
        topic_manifest.write_text(json.dumps(topic, ensure_ascii=False), encoding="utf-8")
        integrity = ctx.service.call("content_integrity_check", {"channelProfileId": ctx.channel_id, "projectId": ctx.project_id})
        self.assertEqual("FAIL", integrity["status"])
        self.assertTrue(any(item["issue"] == "CONTENT_PACKAGE_HASH_MISMATCH" for item in integrity["errors"]))

    def test_non_chinese_line_mapping_mismatch_is_rejected(self) -> None:
        ctx = self.context("en-US")
        finalize_topic(ctx)
        self.assert_tool_error("SCRIPT_MAPPING_MISMATCH", lambda: finalize_manuscript(ctx, mutate_audit=True))

    def test_hashtag_count_and_thumbnail_aspect_ratio_are_hard_failures(self) -> None:
        ctx = self.context("en-US")
        finalize_topic(ctx)
        finalize_manuscript(ctx)
        bad_hashtags = publishing_payload(ctx, SYNTHETIC_THUMBNAIL, hashtags=ctx.market["hashtags"][:7])
        self.assert_tool_error("HASHTAG_COUNT_INVALID", lambda: finalize_publishing(ctx, SYNTHETIC_THUMBNAIL, **bad_hashtags))
        square = self.root / "square-synthetic.png"
        write_png(square, 100, 100)
        self.assert_tool_error("THUMBNAIL_ASPECT_RATIO_INVALID", lambda: finalize_publishing(ctx, square))


if __name__ == "__main__":
    unittest.main()
