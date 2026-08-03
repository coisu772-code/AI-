from __future__ import annotations

import json
import sys
import tempfile
import time
import unittest
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Sequence


ROOT = Path(__file__).resolve().parents[1]
MCP_ROOT = ROOT / "plugins" / "ai-video-channel-production" / "mcp"
FIXTURE_ROOT = ROOT / "tests" / "fixtures" / "stage3" / "youtube"
sys.path.insert(0, str(MCP_ROOT))

from aivcp_tools.errors import ToolError  # noqa: E402
from aivcp_tools.source_youtube import (  # noqa: E402
    CommandResult,
    SubprocessCommandRunner,
    YouTubeAdapter,
    YtDlpBackend,
)


FIXED_TIME = datetime(2026, 8, 4, 8, 30, tzinfo=UTC)


class FixtureYouTubeBackend:
    def __init__(self) -> None:
        self.video_files = {
            "jaSuccess01": "video-success-ja.json",
            "zhNoSubs001": "video-no-subtitles-zh.json",
            "enPartial01": "video-incomplete-en.json",
        }
        self.channel_file = "channel-initial.json"
        self.audio_paths: list[Path] = []
        self.calls: list[tuple[str, str]] = []

    def _document(self, filename: str) -> dict[str, Any]:
        return json.loads((FIXTURE_ROOT / filename).read_text(encoding="utf-8"))

    def video_metadata(self, locator: str) -> dict[str, Any]:
        self.calls.append(("video", locator))
        video_id = locator.rsplit("=", 1)[-1]
        if video_id == "badVideo001":
            error = self._document("inaccessible.json")["error"]
            raise ToolError(error["code"], error["message"], retryable=error["retryable"])
        document = deepcopy(self._document(self.video_files[video_id]))
        for group in ("subtitles", "automatic_captions"):
            for tracks in document.get(group, {}).values():
                for track in tracks:
                    fixture_file = track.pop("fixtureFile", None)
                    if fixture_file:
                        track["data"] = (FIXTURE_ROOT / fixture_file).read_text(encoding="utf-8")
        return document

    def channel_metadata(self, locator: str) -> dict[str, Any]:
        self.calls.append(("channel", locator))
        if "UnavailableFixture" in locator:
            raise ToolError("YOUTUBE_CHANNEL_UNAVAILABLE", "Fixture channel cannot be reached.")
        return self._document(self.channel_file)

    def fetch_binary(self, url: str, *, max_bytes: int) -> bytes:
        self.calls.append(("fetch", url))
        payload = b"synthetic-public-thumbnail"
        if len(payload) > max_bytes:
            raise ToolError("YOUTUBE_ASSET_TOO_LARGE", "Fixture asset is too large.")
        return payload

    def download_audio(self, locator: str, work_dir: Path, stem: str) -> Path:
        self.calls.append(("audio", locator))
        path = work_dir / f"{stem}.temporary-audio.wav"
        path.write_bytes(b"synthetic temporary audio")
        self.audio_paths.append(path)
        return path


class FixtureTranscriber:
    def __init__(self, fixture_file: str = "captions/transcribed-en.vtt") -> None:
        self.fixture_file = fixture_file
        self.calls: list[tuple[Path, str | None]] = []

    def transcribe(
        self,
        audio_path: Path,
        *,
        language: str | None,
        work_dir: Path,
    ) -> dict[str, Any]:
        del work_dir
        self.calls.append((audio_path, language))
        return {
            "vtt": (FIXTURE_ROOT / self.fixture_file).read_text(encoding="utf-8"),
            "language": language or "en",
            "coverageRatio": 0.9833,
            "complete": True,
        }


class NonzeroSensitiveRunner:
    def run(
        self,
        command: Sequence[str],
        *,
        timeout_seconds: float,
        max_output_bytes: int,
    ) -> CommandResult:
        del command, timeout_seconds, max_output_bytes
        return CommandResult(
            returncode=1,
            stdout=b"",
            stderr="failed with Authorization: Bearer ya29.fixture-secret-token",
        )


class Stage3YouTubeAdapterTestCase(unittest.TestCase):
    def adapter(self, backend: FixtureYouTubeBackend, **kwargs: Any) -> YouTubeAdapter:
        return YouTubeAdapter(
            backend=backend,
            clock=lambda: FIXED_TIME,
            minimum_text_characters=40,
            **kwargs,
        )

    def test_manual_caption_metadata_thumbnail_and_public_boundary(self) -> None:
        backend = FixtureYouTubeBackend()
        result = self.adapter(backend).collect_video(
            "https://youtu.be/jaSuccess01?feature=share",
            requested_language="ja-JP",
        )

        self.assertEqual(result["status"], "CONTENT_READY")
        self.assertEqual(result["platform"], "youtube")
        self.assertEqual(result["platformId"], "jaSuccess01")
        self.assertEqual(result["canonicalUrl"], "https://www.youtube.com/watch?v=jaSuccess01")
        self.assertEqual(result["provenance"]["collectedAt"], "2026-08-04T08:30:00Z")
        self.assertEqual(result["metadata"]["publicHashtags"], ["#物語", "#日本語"])
        self.assertEqual(result["metadata"]["publicMetrics"]["viewCount"], 1200)
        public_json = json.dumps(
            {key: value for key, value in result.items() if key != "assets"},
            ensure_ascii=False,
        ).lower()
        self.assertNotIn("ctr", public_json)
        self.assertTrue(any(asset["role"] == "assets" for asset in result["assets"]))
        original = next(asset for asset in result["assets"] if asset["role"] == "raw")
        self.assertIn("人工字幕", original["data"])
        self.assertNotIn("自動字幕", original["data"])
        self.assertEqual(result["report"]["textAcquisition"]["method"], "manual-caption")
        self.assertEqual(result["report"]["textAcquisition"]["completeness"], "complete")
        self.assertFalse(result["report"]["bodyGeneratedFromMetadata"])
        self.assertIsNotNone(result["contentSha256"])

    def test_no_subtitles_is_blocked_and_never_invents_body(self) -> None:
        backend = FixtureYouTubeBackend()
        result = self.adapter(backend).collect_video(
            "https://www.youtube.com/watch?v=zhNoSubs001",
            requested_language="zh-Hans",
            allow_transcription=False,
        )

        self.assertEqual(result["status"], "BLOCKED")
        self.assertEqual(result["title"], "没有字幕的公开测试视频")
        self.assertEqual(result["report"]["textAcquisition"]["method"], "none")
        self.assertFalse(result["report"]["textAcquisition"]["textSufficient"])
        self.assertFalse(result["report"]["bodyGeneratedFromMetadata"])
        self.assertIsNone(result["contentSha256"])
        roles = {asset["role"] for asset in result["assets"]}
        self.assertEqual(roles, {"assets"})
        supplement_kinds = {item["kind"] for item in result["report"]["supplementOptions"]}
        self.assertIn("local-subtitle-or-transcript", supplement_kinds)
        self.assertIn("local-video-or-audio", supplement_kinds)

    def test_incomplete_caption_is_partial_without_transcription(self) -> None:
        backend = FixtureYouTubeBackend()
        result = self.adapter(backend).collect_video(
            "https://www.youtube.com/shorts/enPartial01",
            requested_language="en",
            allow_transcription=False,
        )

        self.assertEqual(result["status"], "PARTIAL")
        self.assertEqual(result["report"]["textAcquisition"]["method"], "manual-caption")
        self.assertEqual(result["report"]["textAcquisition"]["completeness"], "incomplete")
        self.assertLess(result["report"]["textAcquisition"]["coverageRatio"], 0.1)
        self.assertTrue(result["report"]["textAcquisition"]["textSufficient"])

    def test_incomplete_caption_falls_back_to_transcription_and_deletes_audio(self) -> None:
        backend = FixtureYouTubeBackend()
        transcriber = FixtureTranscriber()
        with tempfile.TemporaryDirectory(prefix="aivcp-youtube-test-") as temporary:
            result = self.adapter(backend, transcriber=transcriber).collect_video(
                "https://www.youtube.com/watch?v=enPartial01",
                requested_language="en",
                allow_transcription=True,
                work_dir=temporary,
            )
            self.assertEqual(result["status"], "CONTENT_READY")
            self.assertEqual(result["report"]["textAcquisition"]["method"], "local-transcription")
            self.assertEqual(result["report"]["textAcquisition"]["completeness"], "complete")
            self.assertEqual(len(transcriber.calls), 1)
            self.assertEqual(len(backend.audio_paths), 1)
            self.assertFalse(backend.audio_paths[0].exists())
            self.assertFalse(result["report"]["temporaryAudioRetained"])

    def test_allow_transcription_without_configured_engine_stays_blocked(self) -> None:
        backend = FixtureYouTubeBackend()
        result = self.adapter(backend).collect_video(
            "https://www.youtube.com/watch?v=zhNoSubs001",
            allow_transcription=True,
        )
        self.assertEqual(result["status"], "BLOCKED")
        codes = {failure["code"] for failure in result["report"]["failures"]}
        self.assertIn("TRANSCRIBER_NOT_CONFIGURED", codes)
        self.assertFalse(any(call[0] == "audio" for call in backend.calls))

    def test_channel_inventory_and_incremental_snapshot(self) -> None:
        backend = FixtureYouTubeBackend()
        adapter = self.adapter(backend)
        first = adapter.collect_channel("UCStage3ReferenceFixture")
        self.assertEqual(first["status"], "METADATA_READY")
        self.assertEqual(first["platformId"], "UCStage3ReferenceFixture")
        self.assertEqual(first["metadata"]["videoCount"], 2)
        self.assertEqual(
            first["report"]["incremental"]["changesByVideoId"],
            {"jaSuccess01": "NEW", "zhNoSubs001": "NEW"},
        )
        self.assertEqual(first["metadata"]["videos"][0]["publicHashtags"], ["#物語"])
        self.assertFalse(first["report"]["deepContentDownloaded"])

        backend.channel_file = "channel-incremental.json"
        second = adapter.collect_channel(
            "https://www.youtube.com/@stage3fixture/videos",
            previous_snapshot=first,
        )
        incremental = second["report"]["incremental"]
        self.assertEqual(incremental["newCount"], 1)
        self.assertEqual(incremental["updatedCount"], 1)
        self.assertEqual(incremental["unchangedCount"], 1)
        changes = second["report"]["incremental"]["changesByVideoId"]
        self.assertEqual(changes["enPartial01"], "NEW")
        self.assertEqual(changes["jaSuccess01"], "UPDATED")
        self.assertEqual(changes["zhNoSubs001"], "UNCHANGED")
        self.assertNotEqual(first["contentSha256"], second["contentSha256"])

    def test_collection_timestamp_does_not_create_a_false_content_change(self) -> None:
        backend = FixtureYouTubeBackend()
        first_adapter = self.adapter(backend)
        second_adapter = YouTubeAdapter(
            backend=backend,
            clock=lambda: datetime(2026, 8, 4, 9, 30, tzinfo=UTC),
            minimum_text_characters=40,
        )
        first_video = first_adapter.collect_video("https://youtu.be/jaSuccess01")
        second_video = second_adapter.collect_video("https://youtu.be/jaSuccess01")
        self.assertEqual(first_video["metadata"], second_video["metadata"])
        self.assertEqual(first_video["contentSha256"], second_video["contentSha256"])
        self.assertEqual(
            [(item["role"], item["data"]) for item in first_video["assets"]],
            [(item["role"], item["data"]) for item in second_video["assets"]],
        )

        first_channel = first_adapter.collect_channel("UCStage3ReferenceFixture")
        second_channel = second_adapter.collect_channel(
            "UCStage3ReferenceFixture",
            previous_snapshot=first_channel,
        )
        self.assertEqual(first_channel["metadata"], second_channel["metadata"])
        self.assertEqual(first_channel["contentSha256"], second_channel["contentSha256"])
        self.assertEqual(first_channel["assets"][0]["data"], second_channel["assets"][0]["data"])
        self.assertEqual(second_channel["report"]["incremental"]["unchangedCount"], 2)

    def test_unavailable_video_and_channel_return_safe_blocked_records(self) -> None:
        backend = FixtureYouTubeBackend()
        adapter = self.adapter(backend)
        video = adapter.collect_video("https://www.youtube.com/watch?v=badVideo001")
        channel = adapter.collect_channel("UnavailableFixture")

        self.assertEqual(video["status"], "BLOCKED")
        self.assertEqual(video["report"]["failures"][0]["code"], "YOUTUBE_VIDEO_UNAVAILABLE")
        self.assertFalse(video["report"]["bodyGeneratedFromMetadata"])
        self.assertEqual(channel["status"], "BLOCKED")
        self.assertEqual(channel["report"]["failures"][0]["code"], "YOUTUBE_CHANNEL_UNAVAILABLE")

    def test_non_youtube_video_url_is_rejected_before_backend_call(self) -> None:
        backend = FixtureYouTubeBackend()
        result = self.adapter(backend).collect_video("https://example.invalid/watch?v=jaSuccess01")
        self.assertEqual(result["status"], "BLOCKED")
        self.assertEqual(result["report"]["failures"][0]["code"], "YOUTUBE_VIDEO_LOCATOR_INVALID")
        self.assertEqual(backend.calls, [])

    def test_command_failure_diagnostic_is_redacted(self) -> None:
        backend = YtDlpBackend(command=("fixture-yt-dlp",), runner=NonzeroSensitiveRunner())
        result = YouTubeAdapter(backend=backend, clock=lambda: FIXED_TIME).collect_video(
            "https://www.youtube.com/watch?v=badVideo001"
        )
        serialized = json.dumps(result, ensure_ascii=False)
        self.assertEqual(result["status"], "BLOCKED")
        self.assertNotIn("ya29.fixture-secret-token", serialized)
        self.assertIn("[REDACTED]", serialized)

    def test_subprocess_runner_enforces_output_limit_and_timeout(self) -> None:
        runner = SubprocessCommandRunner()
        with self.assertRaises(ToolError) as output_error:
            runner.run(
                [sys.executable, "-c", "print('x' * 2048)"],
                timeout_seconds=5,
                max_output_bytes=1024,
            )
        self.assertEqual(output_error.exception.code, "COMMAND_OUTPUT_TOO_LARGE")

        started = time.monotonic()
        with self.assertRaises(ToolError) as timeout_error:
            runner.run(
                [sys.executable, "-c", "import time; time.sleep(2)"],
                timeout_seconds=0.1,
                max_output_bytes=1024,
            )
        self.assertEqual(timeout_error.exception.code, "COMMAND_TIMEOUT")
        self.assertLess(time.monotonic() - started, 1.5)


if __name__ == "__main__":
    unittest.main()
