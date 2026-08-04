from __future__ import annotations

import json
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry, Resource

ROOT = Path(__file__).resolve().parents[1]
MCP_ROOT = ROOT / "plugins" / "ai-video-channel-production" / "mcp"
import sys

sys.path.insert(0, str(MCP_ROOT))

from aivcp_tools.contracts import utc_now  # noqa: E402
from aivcp_tools.errors import ToolError  # noqa: E402
from aivcp_tools.source_library import SourceLibrary  # noqa: E402
from aivcp_tools.store import CHANNEL_SCHEMA_VERSION, ChannelStore  # noqa: E402


def defaults() -> dict:
    return {
        "voice": {"engineId": "fixture", "voiceId": "fixture"},
        "manuscript": {
            "mode": "auto_by_topic",
            "preferredCharacters": 12000,
            "minCharacters": 8000,
            "maxCharacters": 16000,
        },
        "episodes": {"mode": "auto_by_topic", "preferredCount": 8, "minCount": 6, "maxCount": 10},
        "deliveryMode": "auto_render",
        "videoGeneration": {"enabled": False, "selectionMode": "none", "fallbackPolicy": "pause"},
        "uploadPolicy": "REQUIRE_REVIEW",
    }


def source_validator() -> Draft202012Validator:
    resources = []
    for path in (ROOT / "contracts" / "schemas").glob("*.schema.json"):
        schema = json.loads(path.read_text(encoding="utf-8"))
        resources.append((schema["$id"], Resource.from_contents(schema)))
    schema = json.loads((ROOT / "contracts" / "schemas" / "source-package.schema.json").read_text(encoding="utf-8"))
    return Draft202012Validator(schema, registry=Registry().with_resources(resources), format_checker=FormatChecker())


class MutableFixtureAdapter:
    def __init__(self) -> None:
        self.revision = 1

    def __call__(self, item: dict, work_dir: Path) -> dict:
        del work_dir
        if item.get("blocked") and not item.get("text"):
            return {
                "sourceType": "youtube-video",
                "status": "BLOCKED",
                "title": "No transcript fixture",
                "language": "en",
                "platform": "youtube",
                "platformId": "blocked-video-001",
                "canonicalUrl": item["canonicalLocator"],
                "canonicalLocator": item["canonicalLocator"],
                "provenance": {
                    "kind": "public-url",
                    "locator": item["locator"],
                    "collectedAt": utc_now(),
                    "adapterId": "fixture-youtube",
                    "adapterVersion": "1.0.0",
                },
                "rightsBoundary": {
                    "accessLevel": "metadata-only",
                    "basis": "No subtitle fixture.",
                    "confirmedByUser": False,
                },
                "metadata": {"textAvailable": False},
                "assets": [{"role": "normalized", "mediaType": "application/json", "filename": "metadata.json", "data": "{}"}],
                "report": {"complete": False, "sourceBoundary": "metadata-only", "supplement": ["subtitle", "media", "text"]},
            }
        if item.get("blocked") and isinstance(item.get("text"), str):
            text = item["text"]
            return {
                "sourceType": "youtube-video",
                "status": "CONTENT_READY",
                "title": "Supplemented transcript fixture",
                "language": item.get("language", "en"),
                "platform": "youtube",
                "platformId": "blocked-video-001",
                "canonicalUrl": item["canonicalLocator"],
                "canonicalLocator": item["canonicalLocator"],
                "provenance": {
                    "kind": "user-input",
                    "locator": item["locator"],
                    "collectedAt": utc_now(),
                    "adapterId": "fixture-youtube",
                    "adapterVersion": "1.0.0",
                },
                "rightsBoundary": {
                    "accessLevel": "user-authorized",
                    "basis": "Transcript supplied by the user after a blocked collection.",
                    "confirmedByUser": True,
                },
                "metadata": {"textAvailable": True, "supplemented": True},
                "contentSha256": __import__("hashlib").sha256(text.encode("utf-8")).hexdigest(),
                "assets": [
                    {"role": "normalized", "mediaType": "text/plain", "filename": "content.txt", "data": text}
                ],
                "report": {"complete": True, "sourceBoundary": "user-supplement"},
            }
        if item["kind"] == "local-file":
            path = Path(item["locator"])
            text = path.read_text(encoding="utf-8")
            digest = __import__("hashlib").sha256(path.read_bytes()).hexdigest()
            return {
                "sourceType": "local-file",
                "status": "CONTENT_READY",
                "title": path.stem,
                "language": item.get("language", "en"),
                "canonicalLocator": item["canonicalLocator"],
                "provenance": {
                    "kind": "local-file",
                    "locator": str(path),
                    "collectedAt": utc_now(),
                    "adapterId": "fixture-document",
                    "adapterVersion": "1.0.0",
                },
                "rightsBoundary": {
                    "accessLevel": "user-authorized",
                    "basis": "Test fixture supplied by user.",
                    "confirmedByUser": True,
                },
                "metadata": {"encoding": "utf-8", "paragraphs": 1},
                "contentSha256": digest,
                "assets": [
                    {"role": "raw", "mediaType": "text/plain", "filename": path.name, "sourcePath": str(path)},
                    {"role": "normalized", "mediaType": "text/plain", "filename": "content.txt", "data": text},
                ],
                "report": {"complete": True, "sourceBoundary": "local-file"},
            }
        body = f"revision-{self.revision}"
        return {
            "sourceType": "novel-web",
            "status": "CONTENT_READY",
            "title": "Fixture Novel",
            "language": "en",
            "platform": "fixture-site",
            "platformId": "fixture-work-001",
            "canonicalUrl": item["canonicalLocator"],
            "canonicalLocator": item["canonicalLocator"],
            "provenance": {
                "kind": "public-url",
                "locator": item["locator"],
                "collectedAt": utc_now(),
                "adapterId": "fixture-site",
                "adapterVersion": "1.0.0",
            },
            "rightsBoundary": {
                "accessLevel": "public-domain",
                "basis": "CC0 stage 3 fixture.",
                "confirmedByUser": False,
            },
            "metadata": {"revision": self.revision, "chapters": 1},
            "contentSha256": __import__("hashlib").sha256(body.encode()).hexdigest(),
            "assets": [{"role": "normalized", "mediaType": "text/plain", "filename": "content.txt", "data": body}],
            "report": {"complete": True, "sourceBoundary": "public-domain"},
        }


class SourceLibraryTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="aivcp-stage3-library-")
        self.root = Path(self.temporary.name)
        self.store = ChannelStore(self.root / "data")
        channel, _ = self.store.create_pending_channel(
            publisher_channel={
                "publisherProfileId": "publisher_fixture_001",
                "channelSerial": "01",
                "youtubeChannelId": "UCFIXTURECHANNEL0001",
                "displayName": "Fixture Channel",
            },
            target_region="Testland",
            output_language="en-US",
        )
        binding = self.store.bind_task(task_id="task-stage3", channel_profile_id=channel["channelProfileId"])
        completed = self.store.complete_library(
            task_id="task-stage3",
            channel_profile_id=channel["channelProfileId"],
            binding_proof=binding["bindingProof"],
            defaults=defaults(),
            execution_mode="review",
        )
        self.channel_id = completed["channelProfileId"]
        self.proof = binding["bindingProof"]
        self.adapter = MutableFixtureAdapter()
        self.library = SourceLibrary(self.store, adapter_factory=self.adapter)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def add(self, items: list[dict | str]) -> dict:
        card = self.library.prepare_add(
            task_id="task-stage3",
            channel_profile_id=self.channel_id,
            binding_proof=self.proof,
            inputs=items,
        )
        self.assertIn("notExecuted", card)
        return self.library.confirm_add(
            task_id="task-stage3",
            channel_profile_id=self.channel_id,
            binding_proof=self.proof,
            acquisition_job_id=card["acquisitionJobId"],
            plan_hash=card["planHash"],
            confirmation={"confirmed": True, "choice": "confirm"},
        )

    def test_local_content_hash_dedup_and_restart_search(self) -> None:
        first = self.root / "first.txt"
        second = self.root / "second.txt"
        first.write_text("same content", encoding="utf-8")
        second.write_text("same content", encoding="utf-8")
        added = self.add([{"path": str(first), "language": "en"}])
        reused = self.add([{"path": str(second), "language": "en"}])
        self.assertEqual(added["completionCard"]["success"], 1)
        self.assertEqual(reused["completionCard"]["reused"], 1)
        restarted = SourceLibrary(ChannelStore(self.root / "data"), adapter_factory=self.adapter)
        search = restarted.search(channel_profile_id=self.channel_id, query="first")
        self.assertEqual(search["count"], 1)
        detail = restarted.get_source(
            channel_profile_id=self.channel_id,
            source_package_id=search["sources"][0]["source_package_id"],
        )
        self.assertEqual(len(detail["aliases"]), 2)
        source_validator().validate(detail["manifest"])

    def test_real_document_adapter_reuses_same_content_under_a_new_filename(self) -> None:
        first = self.root / "original-name.txt"
        second = self.root / "different-name.txt"
        first.write_text("The same normalized document content.\n", encoding="utf-8")
        second.write_bytes(first.read_bytes())
        library = SourceLibrary(self.store)

        def add(path: Path) -> dict:
            card = library.prepare_add(
                task_id="task-stage3",
                channel_profile_id=self.channel_id,
                binding_proof=self.proof,
                inputs=[{"path": str(path), "language": "en"}],
            )
            return library.confirm_add(
                task_id="task-stage3",
                channel_profile_id=self.channel_id,
                binding_proof=self.proof,
                acquisition_job_id=card["acquisitionJobId"],
                plan_hash=card["planHash"],
                confirmation={"confirmed": True, "choice": "confirm"},
            )

        added = add(first)
        reused = add(second)
        self.assertEqual(added["completionCard"]["success"], 1)
        self.assertEqual(reused["completionCard"]["reused"], 1)
        package_id = added["items"][0]["source_package_id"]
        detail = library.get_source(channel_profile_id=self.channel_id, source_package_id=package_id)
        self.assertEqual([row["version"] for row in detail["versions"]], ["1.0.0"])
        self.assertEqual(len(detail["aliases"]), 2)

    def test_canonical_url_dedup_incremental_version_and_integrity(self) -> None:
        first = self.add([{"locator": "https://www.gutenberg.org/ebooks/1/?utm_source=x"}])
        self.assertEqual(first["completionCard"]["success"], 1)
        reused = self.add([{"locator": "https://www.gutenberg.org/ebooks/1"}])
        self.assertEqual(reused["completionCard"]["reused"], 1)
        self.adapter.revision = 2
        updated = self.add([{"locator": "https://www.gutenberg.org/ebooks/1"}])
        self.assertEqual(updated["completionCard"]["updated"], 1)
        package_id = updated["items"][0]["source_package_id"]
        detail = self.library.get_source(channel_profile_id=self.channel_id, source_package_id=package_id)
        self.assertEqual([row["version"] for row in detail["versions"]], ["1.0.0", "1.0.1"])
        self.assertEqual(self.library.integrity_check(channel_profile_id=self.channel_id)["status"], "PASS")

    def test_blocked_video_records_boundary_without_invented_text(self) -> None:
        job = self.add(
            [
                {
                    "locator": "https://youtu.be/blocked001",
                    "blocked": True,
                    "allowTranscription": False,
                }
            ]
        )
        self.assertEqual(job["state"], "NEEDS_SUPPLEMENT")
        self.assertEqual(job["progress"]["needsSupplement"], 1)
        package_id = job["items"][0]["source_package_id"]
        detail = self.library.get_source(channel_profile_id=self.channel_id, source_package_id=package_id)
        self.assertEqual(detail["manifest"]["status"], "BLOCKED")
        self.assertEqual(detail["manifest"]["rightsBoundary"]["accessLevel"], "metadata-only")
        self.assertFalse(detail["metadata"]["textAvailable"])

    def test_blocked_video_resumes_after_user_supplies_text(self) -> None:
        blocked = self.add(
            [
                {
                    "locator": "https://youtu.be/blocked001",
                    "blocked": True,
                    "allowTranscription": False,
                }
            ]
        )
        resumed = self.library.resume_job(
            task_id="task-stage3",
            channel_profile_id=self.channel_id,
            binding_proof=self.proof,
            acquisition_job_id=blocked["acquisitionJobId"],
            supplements=[
                {
                    "itemIndex": 0,
                    "text": "User supplied a complete transcript after the public subtitle path failed.",
                    "language": "en",
                    "authorized": True,
                }
            ],
        )
        self.assertEqual(resumed["state"], "COMPLETED")
        self.assertEqual(resumed["progress"]["needsSupplement"], 0)
        package_id = resumed["items"][0]["source_package_id"]
        detail = self.library.get_source(channel_profile_id=self.channel_id, source_package_id=package_id)
        self.assertEqual(detail["manifest"]["status"], "CONTENT_READY")
        self.assertTrue(detail["metadata"]["supplemented"])
        self.assertEqual([row["version"] for row in detail["versions"]], ["1.0.0", "1.0.1"])

    def test_user_subtitle_is_canonicalized_without_persisting_subtitle_asset(self) -> None:
        subtitle = self.root / "supplement.vtt"
        subtitle.write_text(
            "WEBVTT\n\n00:00:00.000 --> 00:00:08.000\n"
            "The opening fulfills the promise and establishes a clear conflict.\n\n"
            "00:00:08.000 --> 00:00:18.000\n"
            "The next beat changes the relationship and delivers a concrete audience reward.\n",
            encoding="utf-8",
        )
        result = SourceLibrary(self.store)._apply_youtube_text_supplement(
            {
                "sourceType": "youtube-video",
                "status": "BLOCKED",
                "title": "Supplement fixture",
                "language": "en",
                "platform": "youtube",
                "platformId": "supplement001",
                "metadata": {"durationSeconds": 18},
                "assets": [],
                "report": {"complete": False},
            },
            {"suppliedFile": str(subtitle), "language": "en", "complete": True},
            type("Adapter", (), {"minimum_text_characters": 80})(),
        )
        self.assertEqual("CONTENT_READY", result["status"])
        self.assertEqual({"content.txt", "timing-map.json"}, {asset["filename"] for asset in result["assets"]})
        self.assertFalse(any(asset["role"] == "raw" for asset in result["assets"]))
        content = next(asset["data"] for asset in result["assets"] if asset["filename"] == "content.txt")
        self.assertNotIn("WEBVTT", content)
        self.assertNotIn("-->", content)
        self.assertEqual("user-supplied-subtitle", result["report"]["textAcquisition"]["method"])

    def test_subtitle_cannot_be_added_as_a_second_standalone_text_source(self) -> None:
        subtitle = self.root / "standalone.vtt"
        subtitle.write_text("WEBVTT\n", encoding="utf-8")
        with self.assertRaises(ToolError) as caught:
            self.library.prepare_add(
                task_id="task-stage3",
                channel_profile_id=self.channel_id,
                binding_proof=self.proof,
                inputs=[{"path": str(subtitle)}],
            )
        self.assertEqual("SOURCE_SUPPLEMENT_CONTEXT_REQUIRED", caught.exception.code)

    def test_cancel_prepared_job_keeps_no_source(self) -> None:
        card = self.library.prepare_add(
            task_id="task-stage3",
            channel_profile_id=self.channel_id,
            binding_proof=self.proof,
            inputs=[{"text": "will not run", "language": "en"}],
        )
        cancelled = self.library.cancel_job(
            task_id="task-stage3",
            channel_profile_id=self.channel_id,
            binding_proof=self.proof,
            acquisition_job_id=card["acquisitionJobId"],
        )
        self.assertEqual(cancelled["state"], "CANCELLED")
        self.assertEqual(self.library.search(channel_profile_id=self.channel_id)["count"], 0)

    def test_new_channel_database_uses_stage3_schema(self) -> None:
        database = self.store.channel_path(self.channel_id) / "channel.db"
        with closing(__import__("sqlite3").connect(database)) as connection:
            self.assertEqual(connection.execute("PRAGMA user_version").fetchone()[0], CHANNEL_SCHEMA_VERSION)
            tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        self.assertIn("source_packages", tables)
        self.assertIn("acquisition_jobs", tables)


if __name__ == "__main__":
    unittest.main()
