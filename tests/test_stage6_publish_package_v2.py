from __future__ import annotations

import hashlib
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

import jsonschema


ROOT = Path(__file__).resolve().parents[1]
PLUGIN_ROOT = ROOT / "plugins" / "ai-video-channel-production"
sys.path.insert(0, str(PLUGIN_ROOT / "mcp"))
sys.path.insert(0, str(ROOT / "tests"))

from aivcp_tools.contracts import canonical_hash  # noqa: E402
from aivcp_tools.publish_package_v2 import (  # noqa: E402
    PublishPackageError,
    _canonical_bytes,
    assemble_publish_package_v2,
    validate_publish_package_v2,
)
from aivcp_tools.service import LocalToolService, ServiceConfig, tool_definitions  # noqa: E402
from stage5_support import build_stage5_context, mutation_arguments  # noqa: E402


CATALOG = ROOT / "contracts" / "youtube-constraints" / "catalog-2026.08.04.1.json"
CATALOG_SHA256 = "a57cf04014db7512b420771fe9f412e47a3bd69048b0d34fc9c4765085ad5e13"
STALE_CATALOG_SHA256 = "28788480458f37ba86584b4c63e0ef998081ac521ecd9fd0b1724c2a6074b99a"
THUMBNAIL = ROOT / "contracts" / "examples" / "valid" / "fixtures" / "confirmed-thumbnail-1600x900.png"
CREATED_AT = "2026-08-04T04:00:00Z"


def _read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _write(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class Stage6PublishPackageV2Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
            raise unittest.SkipTest("Stage6 requires ffmpeg and ffprobe")
        cls.shared = tempfile.TemporaryDirectory(prefix="aivcp-stage6-shared-")
        root = Path(cls.shared.name)
        context = build_stage5_context(
            root / "workspace",
            "ja-JP",
            plugin_root=PLUGIN_ROOT,
            local_tool_service=LocalToolService,
            service_config=ServiceConfig,
            thumbnail_path=THUMBNAIL,
            delivery_mode="auto_render",
            selection_mode="none",
        )
        completed = context.content.service.call("production_task_run", mutation_arguments(context))["task"]
        cls.result_root = Path(completed["resultPackagePath"])
        state = context.content.service.call(
            "content_project_get",
            {"channelProfileId": context.content.channel_id, "projectId": context.content.project_id},
        )["state"]
        cls.publishing_root = Path(state["activePackages"]["publishing"]["path"]).parent

    @classmethod
    def tearDownClass(cls) -> None:
        cls.shared.cleanup()

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="aivcp-stage6-case-")
        self.root = Path(self.temp.name)
        self._source_counter = 0

    def tearDown(self) -> None:
        self.temp.cleanup()

    def assert_publish_error(self, code: str, callback) -> PublishPackageError:
        with self.assertRaises(PublishPackageError) as caught:
            callback()
        self.assertEqual(code, caught.exception.code)
        return caught.exception

    def _source_copy(self, *, policy: str = "REQUIRE_REVIEW", privacy: str = "private", channel_suffix: str = "") -> tuple[Path, Path, dict]:
        self._source_counter += 1
        result = self.root / f"result-{self._source_counter}-{policy.lower()}-{privacy}-{channel_suffix or 'default'}"
        publishing = self.root / f"publishing-{self._source_counter}-{policy.lower()}-{privacy}-{channel_suffix or 'default'}"
        shutil.copytree(self.result_root, result)
        shutil.copytree(self.publishing_root, publishing)
        pub = _read(publishing / "manifest.json")
        pub["uploadPolicy"] = policy
        pub["privacyStatus"] = privacy
        if channel_suffix:
            pub["channelProfileId"] += channel_suffix
            pub["targetChannel"]["publisherProfileId"] += channel_suffix
            pub["targetChannel"]["channelSerial"] = "02"
            pub["targetChannel"]["youtubeChannelId"] += channel_suffix
        pub["contentHash"] = canonical_hash(pub)
        _write(publishing / "manifest.json", pub)
        publishing_json = _read(publishing / "publishing.json")
        publishing_json.update(
            {
                "title": pub["title"],
                "descriptionBody": pub["descriptionBody"],
                "hashtags": pub["hashtags"],
                "targetChannel": pub["targetChannel"],
                "uploadPolicy": pub["uploadPolicy"],
                "privacyStatus": pub["privacyStatus"],
            }
        )
        _write(publishing / "publishing.json", publishing_json)

        result_manifest = _read(result / "manifest.json")
        result_manifest["channelProfileId"] = pub["channelProfileId"]
        ref = next(item for item in result_manifest["upstream"] if item["targetContractType"] == "publishing-asset-package")
        ref.update({"targetId": pub["id"], "targetVersion": pub["version"], "targetHash": pub["contentHash"]})
        reference_path = result / "publishing-assets-reference.json"
        reference = _read(reference_path)
        reference["publishingAssetPackage"].update(ref)
        _write(reference_path, reference)
        file_record = next(item for item in result_manifest["files"] if item["path"] == "publishing-assets-reference.json")
        file_record.update({"sha256": _sha(reference_path), "sizeBytes": reference_path.stat().st_size})
        result_manifest["contentHash"] = canonical_hash(result_manifest)
        _write(result / "manifest.json", result_manifest)
        channel = {
            "channel_profile_id": pub["channelProfileId"],
            "publisher_profile_id": pub["targetChannel"]["publisherProfileId"],
            "channel_serial": pub["targetChannel"]["channelSerial"],
            "expected_channel_id": pub["targetChannel"]["youtubeChannelId"],
            "enabled": True,
            "authorization_status": "AUTHORIZED",
            "default_language": pub["targetLanguage"],
            "timezone": "Asia/Tokyo",
            "upload_mode": policy,
        }
        return result, publishing, channel

    def _assemble(self, *, policy: str = "REQUIRE_REVIEW", privacy: str = "private", name: str = "inbox", **kwargs):
        result, publishing, channel = self._source_copy(policy=policy, privacy=privacy, channel_suffix=kwargs.pop("channel_suffix", ""))
        return assemble_publish_package_v2(
            production_result_root=result,
            publishing_asset_root=publishing,
            inbox_root=self.root / name,
            channel_profile=channel,
            constraints_catalog_path=CATALOG,
            created_at=CREATED_AT,
            **kwargs,
        )

    @staticmethod
    def _refresh_manifest(package: Path) -> None:
        manifest = _read(package / "manifest.json")
        for item in manifest["files"]:
            path = package / item["path"]
            item["size_bytes"] = path.stat().st_size
            item["sha256"] = _sha(path)
        manifest["content_hash"] = hashlib.sha256(_canonical_bytes({"files": manifest["files"]})).hexdigest()
        _write(package / "manifest.json", manifest)

    def _copy_ready(self, result: dict, name: str) -> Path:
        source = Path(result["package_path"])
        target = self.root / name / source.name
        target.parent.mkdir(parents=True)
        shutil.copytree(source, target)
        return target

    def test_assemble_review_is_atomic_exact_valid_and_idempotent(self) -> None:
        first = self._assemble()
        ready = Path(first["package_path"])
        self.assertTrue(ready.name.endswith(".ready"))
        self.assertFalse(any(path.name.endswith(".creating") for path in ready.parent.iterdir()))
        self.assertEqual("WAITING_REVIEW", first["status"])
        self.assertEqual(["HUMAN_CONFIRMATION_REQUIRED"], first["blockers"])
        self.assertFalse(first["network_execution"])
        self.assertIsNone(first["youtube_video_id"])
        self.assertIsNone(first["publication_receipt"])
        self.assertEqual(
            {"manifest.json", "metadata.json", "upload_task.json", "validation.json", "production_binding.json", "upload_status.json", "final.mp4", "thumbnail.png", "subtitles.srt"},
            {path.name for path in ready.iterdir()},
        )
        result, publishing, channel = self._source_copy()
        duplicate = assemble_publish_package_v2(
            production_result_root=result,
            publishing_asset_root=publishing,
            inbox_root=ready.parent,
            channel_profile=channel,
            constraints_catalog_path=CATALOG,
            created_at=CREATED_AT,
        )
        self.assertTrue(duplicate["duplicate"])
        self.assertEqual(first["publish_intent_id"], duplicate["publish_intent_id"])

    def test_exact_publisher_catalog_is_locked_and_stale_catalog_fails(self) -> None:
        self.assertEqual(CATALOG_SHA256, _sha(CATALOG))
        exact = self._assemble(name="exact-catalog")
        stale_catalog = self.root / "stale-catalog.json"
        stale_catalog.write_bytes(CATALOG.read_bytes().replace(b"\r\n", b"\n"))
        self.assertEqual(STALE_CATALOG_SHA256, _sha(stale_catalog))
        self.assert_publish_error(
            "PUBLISH_CONSTRAINTS_MISMATCH",
            lambda: validate_publish_package_v2(Path(exact["package_path"]), constraints_catalog_path=stale_catalog),
        )

    def test_service_exposes_five_offline_stage6_tools(self) -> None:
        definitions = {item["name"]: item for item in tool_definitions()}
        expected = {
            "assemble_publish_package_v2",
            "validate_publish_package_v2",
            "import_publish_package_v2",
            "get_publication_status",
            "get_publication_receipt",
        }
        self.assertTrue(expected.issubset(definitions))
        for name in expected:
            schema = definitions[name]["inputSchema"]
            self.assertIn("networkExecution", schema["required"])
            self.assertIs(False, schema["properties"]["networkExecution"]["const"])

    def test_metadata_keeps_public_hashtags_separate_from_backend_tags(self) -> None:
        result = self._assemble()
        metadata = _read(Path(result["package_path"]) / "metadata.json")
        self.assertEqual([], metadata["backend_tags"])
        self.assertGreaterEqual(len(metadata["hashtags"]), 8)
        self.assertLessEqual(len(metadata["hashtags"]), 12)
        self.assertEqual(metadata["description_body"].rstrip() + "\n\n" + " ".join(metadata["hashtags"]), metadata["description_for_youtube"])

    def test_three_policies_stop_at_local_states(self) -> None:
        do_not = self._assemble(policy="DO_NOT_UPLOAD", name="do-not")
        self.assertEqual("PACKAGE_READY", do_not["status"])
        auto_missing = self._assemble(policy="AUTO", name="auto-missing")
        self.assertEqual("WAITING_REVIEW", auto_missing["status"])
        self.assertEqual(3, len(auto_missing["blockers"]))
        grants = {
            key: {"granted": True, "version": "1.0", "confirmed_at": "2026-08-04T03:00:00Z"}
            for key in ("workspace", "channel", "intent")
        }
        auto_ready = self._assemble(policy="AUTO", name="auto-ready", authorization=grants)
        self.assertEqual("READY_TO_UPLOAD", auto_ready["status"])
        self.assertEqual(["EXTERNAL_APPROVAL_REQUIRED"], auto_ready["blockers"])
        self.assertTrue(auto_ready["external_approval_required"])
        self.assertIsNone(auto_ready["youtube_video_id"])

    def test_publish_intent_id_changes_for_revision_video_or_channel_but_not_duplicate(self) -> None:
        base = self._assemble(name="base")
        revised_result, revised_pub, revised_channel = self._source_copy()
        pub = _read(revised_pub / "manifest.json")
        pub["descriptionBody"] += " 追記。"
        pub["contentHash"] = canonical_hash(pub)
        _write(revised_pub / "manifest.json", pub)
        publishing_json = _read(revised_pub / "publishing.json")
        publishing_json["descriptionBody"] = pub["descriptionBody"]
        _write(revised_pub / "publishing.json", publishing_json)
        result_manifest = _read(revised_result / "manifest.json")
        ref = next(item for item in result_manifest["upstream"] if item["targetContractType"] == "publishing-asset-package")
        ref["targetHash"] = pub["contentHash"]
        reference_path = revised_result / "publishing-assets-reference.json"
        reference = _read(reference_path)
        reference["publishingAssetPackage"].update(ref)
        _write(reference_path, reference)
        reference_file = next(item for item in result_manifest["files"] if item["path"] == "publishing-assets-reference.json")
        reference_file.update({"sha256": _sha(reference_path), "sizeBytes": reference_path.stat().st_size})
        result_manifest["contentHash"] = canonical_hash(result_manifest)
        _write(revised_result / "manifest.json", result_manifest)
        revised = assemble_publish_package_v2(
            production_result_root=revised_result,
            publishing_asset_root=revised_pub,
            inbox_root=self.root / "revised",
            channel_profile=revised_channel,
            constraints_catalog_path=CATALOG,
            created_at=CREATED_AT,
        )
        other_channel = self._assemble(name="channel", channel_suffix="-new")
        production_revision_result, production_revision_pub, production_revision_channel = self._source_copy()
        production_revision_manifest = _read(production_revision_result / "manifest.json")
        production_revision_manifest["version"] = "1.0.1"
        production_revision_manifest["contentHash"] = canonical_hash(production_revision_manifest)
        _write(production_revision_result / "manifest.json", production_revision_manifest)
        production_revision = assemble_publish_package_v2(
            production_result_root=production_revision_result,
            publishing_asset_root=production_revision_pub,
            inbox_root=self.root / "production-revision",
            channel_profile=production_revision_channel,
            constraints_catalog_path=CATALOG,
            created_at=CREATED_AT,
        )
        self.assertNotEqual(base["publish_intent_id"], revised["publish_intent_id"])
        self.assertNotEqual(base["publish_intent_id"], other_channel["publish_intent_id"])
        self.assertNotEqual(base["publish_intent_id"], production_revision["publish_intent_id"])
        self.assertEqual(base["video_sha256"], revised["video_sha256"], "metadata revision must preserve the accepted MP4")
        self.assertEqual(base["video_sha256"], production_revision["video_sha256"], "a result version revision may reuse the same valid MP4 without mutating it")

    def test_creating_package_is_never_importable(self) -> None:
        result = self._assemble()
        ready = Path(result["package_path"])
        creating = ready.with_suffix(".creating")
        ready.rename(creating)
        self.assert_publish_error(
            "PUBLISH_HALF_PACKAGE_FORBIDDEN",
            lambda: validate_publish_package_v2(creating, constraints_catalog_path=CATALOG),
        )

    def test_path_escape_bad_hash_and_undeclared_file_are_rejected(self) -> None:
        result = self._assemble()
        escape = self._copy_ready(result, "escape")
        manifest = _read(escape / "manifest.json")
        manifest["files"][0]["path"] = "../outside.json"
        manifest["content_hash"] = hashlib.sha256(_canonical_bytes({"files": manifest["files"]})).hexdigest()
        _write(escape / "manifest.json", manifest)
        self.assert_publish_error("PUBLISH_PATH_UNSAFE", lambda: validate_publish_package_v2(escape, constraints_catalog_path=CATALOG))
        bad_hash = self._copy_ready(result, "hash")
        (bad_hash / "metadata.json").write_text("{}", encoding="utf-8")
        self.assert_publish_error("PUBLISH_SIZE_MISMATCH", lambda: validate_publish_package_v2(bad_hash, constraints_catalog_path=CATALOG))
        undeclared = self._copy_ready(result, "undeclared")
        (undeclared / "extra.json").write_text("{}", encoding="utf-8")
        self.assert_publish_error("PUBLISH_UNDECLARED_FILE", lambda: validate_publish_package_v2(undeclared, constraints_catalog_path=CATALOG))

    def test_package_and_upstream_symlinks_are_rejected(self) -> None:
        result = self._assemble()
        ready = Path(result["package_path"])
        link = self.root / "linked.ready"
        try:
            os.symlink(ready, link, target_is_directory=True)
        except OSError:
            self.skipTest("Symbolic link creation is unavailable")
        self.assert_publish_error("PUBLISH_SYMLINK_FORBIDDEN", lambda: validate_publish_package_v2(link, constraints_catalog_path=CATALOG))

    def test_bad_mp4_subtitle_range_and_language_are_rejected(self) -> None:
        result = self._assemble()
        bad_video = self._copy_ready(result, "bad-video")
        (bad_video / "final.mp4").write_bytes(b"not an mp4")
        self._refresh_manifest(bad_video)
        binding = _read(bad_video / "production_binding.json")
        binding["final_video"].update({"sha256": _sha(bad_video / "final.mp4"), "size_bytes": (bad_video / "final.mp4").stat().st_size})
        _write(bad_video / "production_binding.json", binding)
        self._refresh_manifest(bad_video)
        self.assert_publish_error("PUBLISH_VIDEO_DECODE_FAILED", lambda: validate_publish_package_v2(bad_video, constraints_catalog_path=CATALOG))

        out_of_range = self._copy_ready(result, "subtitle-range")
        (out_of_range / "subtitles.srt").write_text("1\n00:00:00,000 --> 00:00:09,000\n日本語です。\n", encoding="utf-8")
        binding = _read(out_of_range / "production_binding.json")
        binding["subtitle"].update({"sha256": _sha(out_of_range / "subtitles.srt"), "size_bytes": (out_of_range / "subtitles.srt").stat().st_size})
        _write(out_of_range / "production_binding.json", binding)
        self._refresh_manifest(out_of_range)
        self.assert_publish_error("PUBLISH_SUBTITLE_OUT_OF_RANGE", lambda: validate_publish_package_v2(out_of_range, constraints_catalog_path=CATALOG))

        wrong_language = self._copy_ready(result, "subtitle-language")
        (wrong_language / "subtitles.srt").write_text("1\n00:00:00,000 --> 00:00:01,000\nThis subtitle is only English.\n", encoding="utf-8")
        binding = _read(wrong_language / "production_binding.json")
        binding["subtitle"].update({"sha256": _sha(wrong_language / "subtitles.srt"), "size_bytes": (wrong_language / "subtitles.srt").stat().st_size})
        _write(wrong_language / "production_binding.json", binding)
        self._refresh_manifest(wrong_language)
        self.assert_publish_error("PUBLISH_SUBTITLE_LANGUAGE_MISMATCH", lambda: validate_publish_package_v2(wrong_language, constraints_catalog_path=CATALOG))

    def test_hashtag_errors_and_backend_tag_masquerade_are_rejected(self) -> None:
        result = self._assemble()
        few = self._copy_ready(result, "few-hashtags")
        metadata = _read(few / "metadata.json")
        metadata["hashtags"] = metadata["hashtags"][:7]
        metadata["description_for_youtube"] = metadata["description_body"].rstrip() + "\n\n" + " ".join(metadata["hashtags"])
        _write(few / "metadata.json", metadata)
        self._refresh_manifest(few)
        self.assert_publish_error("PUBLISH_HASHTAGS_INVALID", lambda: validate_publish_package_v2(few, constraints_catalog_path=CATALOG))
        tags = self._copy_ready(result, "backend-tags")
        metadata = _read(tags / "metadata.json")
        metadata["backend_tags"] = metadata["hashtags"]
        _write(tags / "metadata.json", metadata)
        self._refresh_manifest(tags)
        self.assert_publish_error("PUBLISH_BACKEND_TAGS_NOT_EMPTY", lambda: validate_publish_package_v2(tags, constraints_catalog_path=CATALOG))

    def test_channel_identity_mismatch_is_rejected_before_creation(self) -> None:
        result, publishing, channel = self._source_copy()
        channel["expected_channel_id"] += "WRONG"
        self.assert_publish_error(
            "PUBLISH_CHANNEL_IDENTITY_MISMATCH",
            lambda: assemble_publish_package_v2(
                production_result_root=result,
                publishing_asset_root=publishing,
                inbox_root=self.root / "channel-mismatch",
                channel_profile=channel,
                constraints_catalog_path=CATALOG,
                created_at=CREATED_AT,
            ),
        )

    def test_schedule_timezone_quota_concurrency_and_conflict_wait_for_review(self) -> None:
        past = self._assemble(policy="AUTO", privacy="scheduled", name="past", scheduled_at="2026-08-04T03:00:00+09:00")
        self.assertIn("SCHEDULE_TIME_IN_PAST", past["blockers"])
        invalid_zone = self._assemble(policy="AUTO", name="zone", timezone="Mars/Olympus")
        self.assertIn("TIMEZONE_INVALID", invalid_zone["blockers"])
        quota = self._assemble(policy="AUTO", name="quota", limits={"daily_limit": 1, "used_today": 1, "concurrency_limit": 1, "active_uploads": 0})
        self.assertIn("DAILY_LIMIT_REACHED", quota["blockers"])
        concurrent = self._assemble(policy="AUTO", name="concurrent", limits={"daily_limit": 2, "used_today": 0, "concurrency_limit": 1, "active_uploads": 1})
        self.assertIn("CONCURRENCY_LIMIT_REACHED", concurrent["blockers"])
        conflict = self._assemble(policy="AUTO", name="conflict", schedule_conflict=True)
        self.assertIn("SCHEDULE_CONFLICT", conflict["blockers"])
        for item in (past, invalid_zone, quota, concurrent, conflict):
            self.assertEqual("WAITING_REVIEW", item["status"])

    def test_forged_remote_state_video_id_and_receipt_are_rejected(self) -> None:
        result = self._assemble()
        forged = self._copy_ready(result, "forged")
        status = _read(forged / "upload_status.json")
        status.update({"status": "UPLOADED_PRIVATE", "youtube_video_id": "SYNTHETIC", "publication_receipt_created": True})
        _write(forged / "upload_status.json", status)
        self._refresh_manifest(forged)
        self.assert_publish_error("PUBLISH_UPLOAD_STATE_FORGED", lambda: validate_publish_package_v2(forged, constraints_catalog_path=CATALOG))

    def test_source_hash_and_project_mismatch_are_rejected(self) -> None:
        result, publishing, channel = self._source_copy()
        (result / "final-video.mp4").write_bytes(b"tampered")
        self.assert_publish_error(
            "PUBLISH_SIZE_MISMATCH",
            lambda: assemble_publish_package_v2(
                production_result_root=result,
                publishing_asset_root=publishing,
                inbox_root=self.root / "source-hash",
                channel_profile=channel,
                constraints_catalog_path=CATALOG,
            ),
        )
        result, publishing, channel = self._source_copy(channel_suffix="-project")
        pub = _read(publishing / "manifest.json")
        pub["projectId"] = "different-project"
        pub["contentHash"] = canonical_hash(pub)
        _write(publishing / "manifest.json", pub)
        self.assert_publish_error(
            "PUBLISH_PROJECT_MISMATCH",
            lambda: assemble_publish_package_v2(
                production_result_root=result,
                publishing_asset_root=publishing,
                inbox_root=self.root / "project",
                channel_profile=channel,
                constraints_catalog_path=CATALOG,
            ),
        )

    def test_new_json_schemas_accept_generated_documents(self) -> None:
        result = self._assemble()
        package = Path(result["package_path"])
        mapping = {
            "manifest.json": "publish-package-v2-manifest.schema.json",
            "metadata.json": "publish-package-v2-metadata.schema.json",
            "upload_task.json": "publish-package-v2-upload-task.schema.json",
            "validation.json": "publish-package-v2-validation.schema.json",
            "production_binding.json": "publish-package-v2-production-binding.schema.json",
            "upload_status.json": "publish-package-v2-upload-status.schema.json",
        }
        for document_name, schema_name in mapping.items():
            schema = _read(ROOT / "contracts" / "schemas" / schema_name)
            jsonschema.Draft202012Validator(schema, format_checker=jsonschema.FormatChecker()).validate(_read(package / document_name))


if __name__ == "__main__":
    unittest.main()
