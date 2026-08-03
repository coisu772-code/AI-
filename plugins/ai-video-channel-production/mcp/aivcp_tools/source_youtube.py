from __future__ import annotations

import hashlib
import html
import json
import mimetypes
import os
import re
import subprocess
import tempfile
import urllib.error
import urllib.parse
import urllib.request
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable, Mapping, Protocol, Sequence

from .errors import ToolError
from .security import redact


ADAPTER_ID = "youtube-yt-dlp"
ADAPTER_VERSION = "1.0.0"
DEFAULT_COMMAND_TIMEOUT_SECONDS = 120.0
DEFAULT_METADATA_OUTPUT_LIMIT_BYTES = 16 * 1024 * 1024
DEFAULT_ASSET_LIMIT_BYTES = 64 * 1024 * 1024
DEFAULT_AUDIO_LIMIT_BYTES = 2 * 1024 * 1024 * 1024
_YOUTUBE_HOSTS = {
    "youtube.com",
    "www.youtube.com",
    "m.youtube.com",
    "music.youtube.com",
    "youtu.be",
    "www.youtu.be",
}
_VIDEO_ID = re.compile(r"^[A-Za-z0-9_-]{6,64}$")
_TIMESTAMP = re.compile(
    r"(?m)^(?P<start>(?:\d+:)?\d{2}:\d{2}[.,]\d{3})\s+-->\s+"
    r"(?P<end>(?:\d+:)?\d{2}:\d{2}[.,]\d{3})"
)
_HASHTAG = re.compile(r"(?<![\w#])#([^\s#]+)", re.UNICODE)
_TAG = re.compile(r"<[^>]+>")


@dataclass(slots=True)
class CommandResult:
    returncode: int
    stdout: bytes
    stderr: str


class CommandRunner(Protocol):
    def run(
        self,
        command: Sequence[str],
        *,
        timeout_seconds: float,
        max_output_bytes: int,
    ) -> CommandResult: ...


class YouTubeBackend(Protocol):
    def video_metadata(self, locator: str) -> dict[str, Any]: ...
    def channel_metadata(self, locator: str) -> dict[str, Any]: ...
    def fetch_binary(self, url: str, *, max_bytes: int) -> bytes: ...
    def download_audio(self, locator: str, work_dir: Path, stem: str) -> Path: ...


class Transcriber(Protocol):
    def transcribe(
        self,
        audio_path: Path,
        *,
        language: str | None,
        work_dir: Path,
    ) -> dict[str, Any] | str: ...


@dataclass(slots=True)
class SubprocessCommandRunner:
    """Run an argv-only child process with bounded captured output.

    Output is redirected to temporary files so a noisy child cannot grow an
    in-memory pipe without limit.  The caller receives only a redacted stderr
    tail through higher-level errors.
    """

    def run(
        self,
        command: Sequence[str],
        *,
        timeout_seconds: float,
        max_output_bytes: int,
    ) -> CommandResult:
        argv = [str(item) for item in command]
        if not argv or not all(argv):
            raise ToolError("COMMAND_INVALID", "外部工具命令必须是非空参数数组。")
        timeout = max(0.1, min(float(timeout_seconds), 24 * 60 * 60.0))
        output_limit = max(1024, int(max_output_bytes))
        with tempfile.TemporaryFile() as stdout_file, tempfile.TemporaryFile() as stderr_file:
            try:
                process = subprocess.Popen(
                    argv,
                    stdin=subprocess.DEVNULL,
                    stdout=stdout_file,
                    stderr=stderr_file,
                    shell=False,
                    env={**os.environ, "AIVCP_CALLER": "youtube-source-adapter"},
                )
            except OSError as exc:
                raise ToolError(
                    "COMMAND_START_FAILED",
                    "无法启动资料采集外部工具。",
                    retryable=True,
                    details={"osError": type(exc).__name__},
                ) from exc
            try:
                returncode = process.wait(timeout=timeout)
            except subprocess.TimeoutExpired as exc:
                process.kill()
                process.wait()
                raise ToolError(
                    "COMMAND_TIMEOUT",
                    "资料采集外部工具执行超时。",
                    retryable=True,
                    details={"timeoutSeconds": timeout},
                ) from exc

            stdout_size = stdout_file.tell()
            stderr_size = stderr_file.tell()
            if stdout_size > output_limit or stderr_size > output_limit:
                raise ToolError(
                    "COMMAND_OUTPUT_TOO_LARGE",
                    "资料采集外部工具输出超过安全上限。",
                    details={
                        "limitBytes": output_limit,
                        "stdoutBytes": stdout_size,
                        "stderrBytes": stderr_size,
                    },
                )
            stdout_file.seek(0)
            stderr_file.seek(0)
            stdout = stdout_file.read(output_limit + 1)
            stderr = stderr_file.read(output_limit + 1).decode("utf-8", errors="replace")
            return CommandResult(returncode=returncode, stdout=stdout, stderr=stderr)


@dataclass(slots=True)
class HttpsAssetFetcher:
    timeout_seconds: float = 30.0
    user_agent: str = "AI-Video-Channel-Production/0.3 YouTubeSourceAdapter"

    def fetch(self, url: str, *, max_bytes: int) -> bytes:
        parsed = urllib.parse.urlsplit(url)
        if parsed.scheme.lower() != "https" or not parsed.hostname:
            raise ToolError("YOUTUBE_ASSET_URL_UNSAFE", "YouTube 资产地址不是受支持的 HTTPS 地址。")
        request = urllib.request.Request(url, headers={"User-Agent": self.user_agent})
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                declared = response.headers.get("Content-Length")
                if declared and declared.isdigit() and int(declared) > max_bytes:
                    raise ToolError("YOUTUBE_ASSET_TOO_LARGE", "YouTube 资产超过下载上限。")
                payload = response.read(max_bytes + 1)
        except ToolError:
            raise
        except urllib.error.HTTPError as exc:
            raise ToolError(
                "YOUTUBE_ASSET_UNAVAILABLE",
                "YouTube 公开资产暂时不可取得。",
                retryable=exc.code >= 500 or exc.code == 429,
                details={"httpStatus": exc.code},
            ) from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise ToolError(
                "YOUTUBE_ASSET_UNAVAILABLE",
                "YouTube 公开资产读取失败。",
                retryable=True,
                details={"errorType": type(exc).__name__},
            ) from exc
        if len(payload) > max_bytes:
            raise ToolError("YOUTUBE_ASSET_TOO_LARGE", "YouTube 资产超过下载上限。")
        return payload


@dataclass(slots=True)
class YtDlpBackend:
    command: tuple[str, ...] = ("yt-dlp",)
    runner: CommandRunner = field(default_factory=SubprocessCommandRunner)
    fetcher: HttpsAssetFetcher = field(default_factory=HttpsAssetFetcher)
    timeout_seconds: float = DEFAULT_COMMAND_TIMEOUT_SECONDS
    metadata_output_limit_bytes: int = DEFAULT_METADATA_OUTPUT_LIMIT_BYTES
    audio_limit_bytes: int = DEFAULT_AUDIO_LIMIT_BYTES

    def _json_call(self, arguments: Sequence[str], *, failure_code: str) -> dict[str, Any]:
        result = self.runner.run(
            [*self.command, *arguments],
            timeout_seconds=self.timeout_seconds,
            max_output_bytes=self.metadata_output_limit_bytes,
        )
        if result.returncode != 0:
            raise ToolError(
                failure_code,
                "YouTube 公开资料读取失败。",
                retryable=True,
                details={
                    "exitCode": result.returncode,
                    "diagnostic": redact(result.stderr[-500:]),
                },
            )
        try:
            payload = json.loads(result.stdout.decode("utf-8", errors="strict"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ToolError("YOUTUBE_RESPONSE_INVALID", "YouTube 采集器没有返回有效 JSON。") from exc
        if not isinstance(payload, dict):
            raise ToolError("YOUTUBE_RESPONSE_INVALID", "YouTube 采集器返回结构无效。")
        return payload

    def video_metadata(self, locator: str) -> dict[str, Any]:
        return self._json_call(
            (
                "--dump-single-json",
                "--skip-download",
                "--no-playlist",
                "--no-warnings",
                locator,
            ),
            failure_code="YOUTUBE_VIDEO_UNAVAILABLE",
        )

    def channel_metadata(self, locator: str) -> dict[str, Any]:
        target = locator
        if _is_plain_channel_name(locator):
            search = self._json_call(
                (
                    "--dump-single-json",
                    "--flat-playlist",
                    "--playlist-end",
                    "1",
                    "--skip-download",
                    "--no-warnings",
                    f"ytsearch1:{locator}",
                ),
                failure_code="YOUTUBE_CHANNEL_NOT_FOUND",
            )
            entries = search.get("entries") if isinstance(search.get("entries"), list) else []
            first = next((item for item in entries if isinstance(item, dict)), None)
            if not first:
                raise ToolError("YOUTUBE_CHANNEL_NOT_FOUND", "无法根据频道名称识别唯一公开频道。")
            channel_id = _clean_string(first.get("channel_id"))
            channel_url = _clean_string(first.get("channel_url"))
            target = channel_url or (f"https://www.youtube.com/channel/{channel_id}/videos" if channel_id else "")
            if not target:
                raise ToolError("YOUTUBE_CHANNEL_NOT_FOUND", "频道名称搜索结果缺少可核验频道身份。")
        return self._json_call(
            (
                "--dump-single-json",
                "--flat-playlist",
                "--skip-download",
                "--ignore-errors",
                "--no-warnings",
                target,
            ),
            failure_code="YOUTUBE_CHANNEL_UNAVAILABLE",
        )

    def fetch_binary(self, url: str, *, max_bytes: int) -> bytes:
        return self.fetcher.fetch(url, max_bytes=max_bytes)

    def download_audio(self, locator: str, work_dir: Path, stem: str) -> Path:
        work_dir.mkdir(parents=True, exist_ok=True)
        temporary_stem = f"{stem}-{uuid.uuid4().hex[:12]}"
        template = work_dir / f"{temporary_stem}.temporary-audio.%(ext)s"
        result = self.runner.run(
            [
                *self.command,
                "--no-playlist",
                "--no-warnings",
                "-f",
                "bestaudio/best",
                "-x",
                "--audio-format",
                "wav",
                "-o",
                str(template),
                locator,
            ],
            timeout_seconds=max(self.timeout_seconds, 15 * 60.0),
            max_output_bytes=self.metadata_output_limit_bytes,
        )
        if result.returncode != 0:
            for partial in work_dir.glob(f"{temporary_stem}.temporary-audio.*"):
                if partial.is_file():
                    partial.unlink(missing_ok=True)
            raise ToolError(
                "YOUTUBE_AUDIO_UNAVAILABLE",
                "无法取得用于本地转录的临时音频。",
                retryable=True,
                details={"exitCode": result.returncode, "diagnostic": redact(result.stderr[-500:])},
            )
        created = [
            item.resolve()
            for item in work_dir.glob(f"{temporary_stem}.temporary-audio.*")
            if item.is_file()
        ]
        if not created:
            raise ToolError("YOUTUBE_AUDIO_UNAVAILABLE", "临时音频命令完成但没有生成音频文件。")
        audio = max(created, key=lambda item: item.stat().st_size)
        if audio.stat().st_size > self.audio_limit_bytes:
            audio.unlink(missing_ok=True)
            raise ToolError("YOUTUBE_AUDIO_TOO_LARGE", "临时音频超过本地转录上限。")
        return audio


@dataclass(slots=True)
class CommandTranscriber:
    """Adapter for a replaceable local transcriber command.

    Command elements may contain ``{input}``, ``{output}``, and ``{language}``.
    If the input/output placeholders are omitted, their paths are appended.  The
    command should write JSON (preferred) or UTF-8 text to ``{output}``.
    """

    command: tuple[str, ...]
    runner: CommandRunner = field(default_factory=SubprocessCommandRunner)
    timeout_seconds: float = 60 * 60.0
    output_limit_bytes: int = 32 * 1024 * 1024

    def transcribe(
        self,
        audio_path: Path,
        *,
        language: str | None,
        work_dir: Path,
    ) -> dict[str, Any] | str:
        if not self.command:
            raise ToolError("TRANSCRIBER_NOT_CONFIGURED", "尚未配置本地转录引擎。")
        output_path = work_dir / f"{audio_path.stem}.transcript.json"
        placeholders = "\n".join(self.command)
        values = {
            "input": str(audio_path),
            "output": str(output_path),
            "language": language or "auto",
        }
        command = [
            item.replace("{input}", values["input"])
            .replace("{output}", values["output"])
            .replace("{language}", values["language"])
            for item in self.command
        ]
        if "{input}" not in placeholders:
            command.append(str(audio_path))
        if "{output}" not in placeholders:
            command.append(str(output_path))
        try:
            result = self.runner.run(
                command,
                timeout_seconds=self.timeout_seconds,
                max_output_bytes=self.output_limit_bytes,
            )
            if result.returncode != 0:
                raise ToolError(
                    "TRANSCRIPTION_FAILED",
                    "本地音频转录失败。",
                    retryable=True,
                    details={"exitCode": result.returncode, "diagnostic": redact(result.stderr[-500:])},
                )
            payload: bytes
            if output_path.is_file():
                if output_path.stat().st_size > self.output_limit_bytes:
                    raise ToolError("TRANSCRIPTION_OUTPUT_TOO_LARGE", "本地转录结果超过安全上限。")
                payload = output_path.read_bytes()
            else:
                payload = result.stdout
        finally:
            output_path.unlink(missing_ok=True)
        try:
            text = payload.decode("utf-8", errors="strict")
        except UnicodeDecodeError as exc:
            raise ToolError("TRANSCRIPTION_OUTPUT_INVALID", "本地转录结果不是 UTF-8 文本。") from exc
        try:
            document = json.loads(text)
        except json.JSONDecodeError:
            document = text
        if not isinstance(document, (dict, str)):
            raise ToolError("TRANSCRIPTION_OUTPUT_INVALID", "本地转录结果结构无效。")
        return document


@dataclass(slots=True)
class _TranscriptCandidate:
    method: str
    language: str | None
    raw_text: str
    normalized_text: str
    media_type: str
    extension: str
    text_sufficient: bool
    completeness: str
    coverage_ratio: float | None
    source_url: str | None = None
    reported_complete: bool | None = None

    @property
    def score(self) -> tuple[int, float, int, int]:
        completeness_score = {"complete": 3, "unknown": 2, "incomplete": 1}.get(self.completeness, 0)
        method_score = {"manual-caption": 3, "automatic-caption": 2, "local-transcription": 1}.get(
            self.method, 0
        )
        return (
            1 if self.text_sufficient else 0,
            self.coverage_ratio if self.coverage_ratio is not None else -1.0,
            completeness_score,
            method_score,
        )


class YouTubeAdapter:
    """Collect public YouTube source facts without running content analysis.

    The returned dictionaries are storage-neutral Source Package candidates.
    They intentionally contain no generated story text and no private Studio
    metrics.  ``backend`` and ``transcriber`` are injectable for offline tests
    and for replacing yt-dlp or the local ASR implementation.
    """

    adapter_id = ADAPTER_ID
    adapter_version = ADAPTER_VERSION

    def __init__(
        self,
        backend: YouTubeBackend | None = None,
        *,
        yt_dlp_command: Sequence[str] = ("yt-dlp",),
        runner: CommandRunner | None = None,
        transcriber: Transcriber | None = None,
        transcription_command: Sequence[str] | None = None,
        clock: Callable[[], datetime | str] | None = None,
        minimum_text_characters: int = 80,
        complete_coverage_ratio: float = 0.85,
        asset_limit_bytes: int = DEFAULT_ASSET_LIMIT_BYTES,
        keep_temporary_audio: bool = False,
    ) -> None:
        command_runner = runner or SubprocessCommandRunner()
        self.backend = backend or YtDlpBackend(tuple(yt_dlp_command), runner=command_runner)
        self.transcriber = transcriber
        if self.transcriber is None and transcription_command:
            self.transcriber = CommandTranscriber(tuple(transcription_command), runner=command_runner)
        self.clock = clock or (lambda: datetime.now(UTC))
        self.minimum_text_characters = max(1, int(minimum_text_characters))
        self.complete_coverage_ratio = max(0.0, min(float(complete_coverage_ratio), 1.0))
        self.asset_limit_bytes = max(1024, int(asset_limit_bytes))
        self.keep_temporary_audio = bool(keep_temporary_audio)

    @classmethod
    def from_environment(cls) -> "YouTubeAdapter":
        """Build the production adapter from non-secret local command settings."""

        runner = SubprocessCommandRunner()
        yt_dlp_command = _environment_command(
            "AIVCP_YT_DLP_COMMAND_JSON",
            "AIVCP_YT_DLP_EXE",
            default=("yt-dlp",),
        )
        timeout = _environment_float(
            "AIVCP_YOUTUBE_TIMEOUT_SECONDS",
            DEFAULT_COMMAND_TIMEOUT_SECONDS,
            minimum=1.0,
            maximum=60 * 60.0,
        )
        output_limit = _environment_integer(
            "AIVCP_YOUTUBE_METADATA_LIMIT_BYTES",
            DEFAULT_METADATA_OUTPUT_LIMIT_BYTES,
            minimum=1024,
            maximum=256 * 1024 * 1024,
        )
        audio_limit = _environment_integer(
            "AIVCP_YOUTUBE_AUDIO_LIMIT_BYTES",
            DEFAULT_AUDIO_LIMIT_BYTES,
            minimum=1024,
            maximum=16 * 1024 * 1024 * 1024,
        )
        backend = YtDlpBackend(
            command=yt_dlp_command,
            runner=runner,
            timeout_seconds=timeout,
            metadata_output_limit_bytes=output_limit,
            audio_limit_bytes=audio_limit,
        )
        transcription_command = _environment_command(
            "AIVCP_TRANSCRIBER_COMMAND_JSON",
            "AIVCP_TRANSCRIBER_EXE",
            default=None,
        )
        transcriber: Transcriber | None = None
        if transcription_command:
            transcriber = CommandTranscriber(
                transcription_command,
                runner=runner,
                timeout_seconds=_environment_float(
                    "AIVCP_TRANSCRIPTION_TIMEOUT_SECONDS",
                    60 * 60.0,
                    minimum=1.0,
                    maximum=24 * 60 * 60.0,
                ),
                output_limit_bytes=_environment_integer(
                    "AIVCP_TRANSCRIPTION_OUTPUT_LIMIT_BYTES",
                    32 * 1024 * 1024,
                    minimum=1024,
                    maximum=512 * 1024 * 1024,
                ),
            )
        return cls(
            backend=backend,
            transcriber=transcriber,
            minimum_text_characters=_environment_integer(
                "AIVCP_YOUTUBE_MINIMUM_TEXT_CHARACTERS",
                80,
                minimum=1,
                maximum=1_000_000,
            ),
            complete_coverage_ratio=_environment_float(
                "AIVCP_YOUTUBE_COMPLETE_COVERAGE_RATIO",
                0.85,
                minimum=0.0,
                maximum=1.0,
            ),
            asset_limit_bytes=_environment_integer(
                "AIVCP_YOUTUBE_ASSET_LIMIT_BYTES",
                DEFAULT_ASSET_LIMIT_BYTES,
                minimum=1024,
                maximum=1024 * 1024 * 1024,
            ),
            keep_temporary_audio=os.environ.get("AIVCP_YOUTUBE_KEEP_TEMP_AUDIO") == "1",
        )

    def collect_video(
        self,
        locator: str,
        *,
        requested_language: str | None = None,
        allow_transcription: bool = False,
        work_dir: str | os.PathLike[str] | None = None,
    ) -> dict[str, Any]:
        collected_at = _collected_at(self.clock())
        original_locator = _clean_string(locator)
        canonical_input, parsed_id = _canonical_video_locator(original_locator)
        base = self._base_result(
            source_type="youtube-video",
            locator=original_locator or "youtube-video:missing",
            collected_at=collected_at,
            canonical_locator=canonical_input or original_locator or "youtube-video:missing",
        )
        if not original_locator or not canonical_input:
            return self._blocked(
                base,
                code="YOUTUBE_VIDEO_LOCATOR_INVALID",
                message="请提供有效的 YouTube 视频链接或视频 ID。",
                supplement_options=_video_supplement_options(include_locator=True),
            )

        try:
            metadata = self.backend.video_metadata(canonical_input)
        except ToolError as exc:
            base.update(
                {
                    "platformId": parsed_id,
                    "canonicalUrl": canonical_input if parsed_id else None,
                    "canonicalLocator": canonical_input,
                }
            )
            return self._blocked_from_error(base, exc, _video_supplement_options())
        except Exception as exc:  # keep provider faults outside the MCP boundary
            return self._blocked_from_error(
                base,
                ToolError(
                    "YOUTUBE_ADAPTER_FAILED",
                    "YouTube 适配器读取失败。",
                    retryable=True,
                    details={"errorType": type(exc).__name__},
                ),
                _video_supplement_options(),
            )

        video_id = _clean_string(metadata.get("id")) or parsed_id
        if not video_id or not _VIDEO_ID.fullmatch(video_id):
            return self._blocked(
                base,
                code="YOUTUBE_VIDEO_ID_MISSING",
                message="公开响应缺少可核验的 YouTube 视频 ID。",
                supplement_options=_video_supplement_options(include_locator=True),
            )
        canonical_url = f"https://www.youtube.com/watch?v={video_id}"
        duration = _number(metadata.get("duration"))
        title = _clean_string(metadata.get("title"))
        description = _clean_string(metadata.get("description"), allow_empty=True) or ""
        metadata_language = _clean_string(metadata.get("language"))
        requested_language = _clean_string(requested_language)
        hashtags = _public_hashtags(description, metadata.get("hashtags"))
        thumbnail = _select_thumbnail(metadata)
        failures: list[dict[str, Any]] = []
        assets: list[dict[str, Any]] = []
        missing_fields: list[str] = []
        if not title:
            missing_fields.append("title")
        if not description:
            missing_fields.append("description")

        if thumbnail and thumbnail.get("url"):
            try:
                thumbnail_data = self.backend.fetch_binary(
                    str(thumbnail["url"]), max_bytes=self.asset_limit_bytes
                )
                extension, media_type = _asset_type(str(thumbnail["url"]), thumbnail.get("ext"))
                assets.append(
                    {
                        "role": "assets",
                        "mediaType": media_type,
                        "filename": f"{video_id}-thumbnail{extension}",
                        "data": thumbnail_data,
                        "sourceUrl": thumbnail["url"],
                    }
                )
            except ToolError as exc:
                failures.append(_safe_failure(exc, stage="thumbnail"))
                missing_fields.append("thumbnail-asset")
        else:
            missing_fields.append("thumbnail")

        owned_temp: tempfile.TemporaryDirectory[str] | None = None
        if work_dir is None:
            owned_temp = tempfile.TemporaryDirectory(prefix="aivcp-youtube-")
            task_dir = Path(owned_temp.name)
        else:
            task_dir = Path(work_dir).expanduser().resolve()
            task_dir.mkdir(parents=True, exist_ok=True)

        transcript: _TranscriptCandidate | None = None
        try:
            transcript, transcript_failures = self._collect_caption_candidate(
                metadata,
                duration_seconds=duration,
                requested_language=requested_language,
                metadata_language=metadata_language,
            )
            failures.extend(transcript_failures)
            clearly_incomplete = transcript is None or transcript.completeness == "incomplete" or not transcript.text_sufficient
            if clearly_incomplete and allow_transcription:
                if self.transcriber is None:
                    failures.append(
                        _safe_failure(
                            ToolError(
                                "TRANSCRIBER_NOT_CONFIGURED",
                                "允许了临时音频转录，但本机尚未配置转录引擎。",
                                retryable=True,
                            ),
                            stage="transcription",
                        )
                    )
                else:
                    transcribed, transcription_failures = self._transcribe(
                        canonical_url,
                        video_id=video_id,
                        work_dir=task_dir,
                        requested_language=requested_language or metadata_language,
                        duration_seconds=duration,
                    )
                    failures.extend(transcription_failures)
                    if transcribed and (transcript is None or transcribed.score > transcript.score):
                        transcript = transcribed
        finally:
            if owned_temp is not None:
                owned_temp.cleanup()

        if transcript and transcript.normalized_text:
            raw_filename = f"{video_id}-{transcript.method}{transcript.extension}"
            assets.extend(
                [
                    {
                        "role": "raw",
                        "mediaType": transcript.media_type,
                        "filename": raw_filename,
                        "data": transcript.raw_text,
                        **({"sourceUrl": transcript.source_url} if transcript.source_url else {}),
                    },
                    {
                        "role": "normalized",
                        "mediaType": "text/plain; charset=utf-8",
                        "filename": f"{video_id}-transcript.txt",
                        "data": transcript.normalized_text,
                    },
                ]
            )

        text_sufficient = bool(transcript and transcript.text_sufficient)
        transcript_complete = bool(transcript and transcript.completeness == "complete")
        if not text_sufficient:
            status = "BLOCKED"
        elif transcript_complete and not missing_fields:
            status = "CONTENT_READY"
        else:
            status = "PARTIAL"
        language = (transcript.language if transcript else None) or metadata_language or requested_language
        content_sha256 = (
            hashlib.sha256(transcript.normalized_text.encode("utf-8")).hexdigest()
            if text_sufficient and transcript
            else None
        )
        public_metrics = {
            key: value
            for key, value in {
                "viewCount": _integer(metadata.get("view_count")),
                "likeCount": _integer(metadata.get("like_count")),
                "commentCount": _integer(metadata.get("comment_count")),
                "concurrentViewers": _integer(metadata.get("concurrent_view_count")),
            }.items()
            if value is not None
        }
        report = {
            "complete": status == "CONTENT_READY",
            "completeness": (
                "complete" if status == "CONTENT_READY" else "blocked" if status == "BLOCKED" else "partial"
            ),
            "collectedAt": collected_at,
            "acquisitionMethod": "yt-dlp-public-metadata",
            "textAcquisition": {
                "method": transcript.method if transcript else "none",
                "language": transcript.language if transcript else None,
                "requestedLanguage": requested_language,
                "completeness": transcript.completeness if transcript else "missing",
                "coverageRatio": transcript.coverage_ratio if transcript else None,
                "textCharacters": len(transcript.normalized_text) if transcript else 0,
                "minimumCharacters": self.minimum_text_characters,
                "textSufficient": text_sufficient,
            },
            "metadataCompleteness": {
                "level": "complete" if not missing_fields else "partial",
                "missing": sorted(set(missing_fields)),
            },
            "failures": failures,
            "sourceBoundary": _video_source_boundary(),
            "fullVideoStored": False,
            "temporaryAudioRetained": bool(
                self.keep_temporary_audio and transcript and transcript.method == "local-transcription"
            ),
            "supplementOptions": [] if text_sufficient else _video_supplement_options(),
            "bodyGeneratedFromMetadata": False,
        }
        base.update(
            {
                "status": status,
                "title": title,
                "language": language,
                "platformId": video_id,
                "canonicalUrl": canonical_url,
                "canonicalLocator": canonical_url,
                "metadata": {
                    "videoId": video_id,
                    "channelId": _clean_string(metadata.get("channel_id")),
                    "channelTitle": _clean_string(metadata.get("channel"))
                    or _clean_string(metadata.get("uploader")),
                    "title": title,
                    "description": description,
                    "publicHashtags": hashtags,
                    "publishedAt": _published_at(metadata),
                    "durationSeconds": duration,
                    "publicMetrics": public_metrics,
                    "thumbnail": thumbnail,
                    "availability": _clean_string(metadata.get("availability")),
                    "isLive": metadata.get("is_live") if isinstance(metadata.get("is_live"), bool) else None,
                },
                "assets": assets,
                "contentSha256": content_sha256,
                "report": report,
            }
        )
        return base

    def collect_channel(
        self,
        locator: str,
        *,
        work_dir: str | os.PathLike[str] | None = None,
        previous_snapshot: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        del work_dir  # channel inventory is deliberately metadata-only
        collected_at = _collected_at(self.clock())
        original_locator = _clean_string(locator)
        canonical_input = _canonical_channel_input(original_locator)
        base = self._base_result(
            source_type="reference-channel",
            locator=original_locator or "youtube-channel:missing",
            collected_at=collected_at,
            canonical_locator=canonical_input or original_locator or "youtube-channel:missing",
        )
        if not original_locator or not canonical_input:
            return self._blocked(
                base,
                code="YOUTUBE_CHANNEL_LOCATOR_INVALID",
                message="请提供有效的 YouTube 频道网址、频道 ID、Handle 或名称。",
                supplement_options=[{"kind": "youtube-channel-url-or-id", "required": True}],
            )
        try:
            metadata = self.backend.channel_metadata(canonical_input)
        except ToolError as exc:
            return self._blocked_from_error(
                base,
                exc,
                [{"kind": "youtube-channel-url-or-id", "required": True}, {"kind": "retry-public-access"}],
            )
        except Exception as exc:
            return self._blocked_from_error(
                base,
                ToolError(
                    "YOUTUBE_ADAPTER_FAILED",
                    "YouTube 频道清单适配器读取失败。",
                    retryable=True,
                    details={"errorType": type(exc).__name__},
                ),
                [{"kind": "youtube-channel-url-or-id", "required": True}],
            )

        entries = metadata.get("entries")
        if not isinstance(entries, list):
            return self._blocked(
                base,
                code="YOUTUBE_CHANNEL_RESPONSE_INVALID",
                message="频道公开响应缺少视频清单。",
                supplement_options=[{"kind": "retry-public-access"}],
            )
        channel_id = _clean_string(metadata.get("channel_id")) or _clean_string(metadata.get("uploader_id"))
        if not channel_id:
            for raw in entries:
                if isinstance(raw, dict) and _clean_string(raw.get("channel_id")):
                    channel_id = _clean_string(raw.get("channel_id"))
                    break
        channel_url = _canonical_channel_url(
            channel_id,
            _clean_string(metadata.get("channel_url")) or _clean_string(metadata.get("webpage_url")) or canonical_input,
        )
        title = _clean_string(metadata.get("channel")) or _clean_string(metadata.get("uploader")) or _clean_string(
            metadata.get("title")
        )
        previous = _previous_videos(previous_snapshot)
        videos: list[dict[str, Any]] = []
        failures: list[dict[str, Any]] = []
        seen: set[str] = set()
        missing_counts: dict[str, int] = {}
        for index, raw in enumerate(entries):
            if not isinstance(raw, dict):
                failures.append(
                    {
                        "stage": "inventory",
                        "code": "YOUTUBE_VIDEO_ENTRY_INVALID",
                        "message": "频道清单包含无法读取的视频条目。",
                        "retryable": False,
                        "details": {"entryIndex": index},
                    }
                )
                continue
            video_id = _clean_string(raw.get("id"))
            if not video_id or not _VIDEO_ID.fullmatch(video_id) or video_id in seen:
                failures.append(
                    {
                        "stage": "inventory",
                        "code": "YOUTUBE_VIDEO_ID_INVALID",
                        "message": "频道清单中的视频缺少唯一平台 ID。",
                        "retryable": False,
                        "details": {"entryIndex": index},
                    }
                )
                continue
            seen.add(video_id)
            description = _clean_string(raw.get("description"), allow_empty=True) or ""
            thumbnail = _select_thumbnail(raw)
            video = {
                "videoId": video_id,
                "canonicalUrl": f"https://www.youtube.com/watch?v={video_id}",
                "title": _clean_string(raw.get("title")),
                "description": description,
                "publicHashtags": _public_hashtags(description, raw.get("hashtags")),
                "publishedAt": _published_at(raw),
                "durationSeconds": _number(raw.get("duration")),
                "publicMetrics": {
                    key: value
                    for key, value in {
                        "viewCount": _integer(raw.get("view_count")),
                        "likeCount": _integer(raw.get("like_count")),
                        "commentCount": _integer(raw.get("comment_count")),
                    }.items()
                    if value is not None
                },
                "thumbnail": thumbnail,
            }
            for field_name in ("title", "description", "publishedAt", "durationSeconds", "thumbnail"):
                if video.get(field_name) in (None, "", []):
                    missing_counts[field_name] = missing_counts.get(field_name, 0) + 1
            old = previous.get(video_id)
            change_type = "NEW" if old is None else (
                "UNCHANGED" if _inventory_fingerprint(video) == _inventory_fingerprint(old) else "UPDATED"
            )
            video["changeType"] = change_type
            videos.append(video)

        missing_from_current = sorted(set(previous) - seen)
        change_counts = {
            kind.lower(): sum(1 for item in videos if item["changeType"] == kind)
            for kind in ("NEW", "UPDATED", "UNCHANGED")
        }
        stable_videos = [{key: value for key, value in video.items() if key != "changeType"} for video in videos]
        inventory_document = {
            "channelId": channel_id,
            "canonicalUrl": channel_url,
            "videos": stable_videos,
            "missingFromCurrent": missing_from_current,
        }
        inventory_text = json.dumps(
            inventory_document, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
        content_sha256 = hashlib.sha256(inventory_text.encode("utf-8")).hexdigest()
        completeness_level = "complete"
        name_resolution = _is_plain_channel_name(original_locator)
        if failures or missing_counts or not channel_id or name_resolution:
            completeness_level = "partial"
        status = "PARTIAL" if failures or name_resolution else "METADATA_READY"
        changes_by_video_id = {item["videoId"]: item.pop("changeType") for item in videos}
        base.update(
            {
                "status": status,
                "title": title,
                "language": _clean_string(metadata.get("language")),
                "platformId": channel_id,
                "canonicalUrl": channel_url,
                "canonicalLocator": channel_url or canonical_input,
                "metadata": {
                    "channelId": channel_id,
                    "channelTitle": title,
                    "channelDescription": _clean_string(metadata.get("description"), allow_empty=True) or "",
                    "videoCount": len(videos),
                    "videos": videos,
                },
                "assets": [
                    {
                        "role": "normalized",
                        "mediaType": "application/json",
                        "filename": f"{channel_id or 'youtube-channel'}-inventory.json",
                        "data": inventory_text,
                    }
                ],
                "contentSha256": content_sha256,
                "report": {
                    "complete": completeness_level == "complete",
                    "completeness": completeness_level,
                    "collectedAt": collected_at,
                    "acquisitionMethod": "yt-dlp-flat-playlist",
                    "inventoryCompleteness": {
                        "level": completeness_level,
                        "returnedVideos": len(videos),
                        "invalidEntries": len(failures),
                        "missingFieldCounts": missing_counts,
                        "claim": "best-effort-public-inventory",
                    },
                    "failures": failures,
                    "sourceBoundary": {
                        "included": [
                            "public channel identity",
                            "best-effort lightweight public video list",
                            "public video metadata and metrics present in the list response",
                        ],
                        "excluded": [
                            "YouTube Studio or Analytics data",
                            "private/deleted video facts not present in the public response",
                            "video story/body inference",
                        ],
                        "missingEntriesAreNotDeletionProof": True,
                    },
                    "incremental": {
                        "previousSnapshotProvided": previous_snapshot is not None,
                        "previousCount": len(previous),
                        "newCount": change_counts["new"],
                        "updatedCount": change_counts["updated"],
                        "unchangedCount": change_counts["unchanged"],
                        "missingFromCurrentCount": len(missing_from_current),
                        "changesByVideoId": changes_by_video_id,
                    },
                    "identityResolution": (
                        "name-search-first-public-result" if name_resolution else "direct-locator"
                    ),
                    "identityReviewRecommended": name_resolution,
                    "deepContentDownloaded": False,
                    "bodyGeneratedFromMetadata": False,
                },
            }
        )
        return base

    def _collect_caption_candidate(
        self,
        metadata: Mapping[str, Any],
        *,
        duration_seconds: float | None,
        requested_language: str | None,
        metadata_language: str | None,
    ) -> tuple[_TranscriptCandidate | None, list[dict[str, Any]]]:
        failures: list[dict[str, Any]] = []
        best: _TranscriptCandidate | None = None
        for method, key in (("manual-caption", "subtitles"), ("automatic-caption", "automatic_captions")):
            tracks = metadata.get(key)
            if not isinstance(tracks, dict):
                continue
            method_best: _TranscriptCandidate | None = None
            for language, track in _ordered_tracks(tracks, requested_language, metadata_language):
                try:
                    candidate = self._caption_from_track(
                        method,
                        language,
                        track,
                        duration_seconds=duration_seconds,
                    )
                except ToolError as exc:
                    failures.append(_safe_failure(exc, stage=method))
                    continue
                if method_best is None or candidate.score > method_best.score:
                    method_best = candidate
                if candidate.text_sufficient and candidate.completeness == "complete":
                    return candidate, failures
            if method_best and (best is None or method_best.score > best.score):
                best = method_best
            if method_best and method_best.text_sufficient and method_best.completeness == "unknown":
                return method_best, failures
        return best, failures

    def _caption_from_track(
        self,
        method: str,
        language: str,
        track: Mapping[str, Any],
        *,
        duration_seconds: float | None,
    ) -> _TranscriptCandidate:
        data = track.get("data")
        source_url = _clean_string(track.get("url"))
        if isinstance(data, str):
            raw = data
        elif source_url:
            payload = self.backend.fetch_binary(source_url, max_bytes=self.asset_limit_bytes)
            raw = payload.decode("utf-8-sig", errors="replace")
        else:
            raise ToolError("YOUTUBE_CAPTION_UNAVAILABLE", "字幕轨道缺少可读取的公开地址。")
        extension = _clean_string(track.get("ext")) or "vtt"
        normalized, coverage = _normalize_caption(raw, extension, duration_seconds)
        sufficient = len(_text_characters(normalized)) >= self.minimum_text_characters
        completeness = _completeness(coverage, sufficient, self.complete_coverage_ratio)
        return _TranscriptCandidate(
            method=method,
            language=language,
            raw_text=raw,
            normalized_text=normalized,
            media_type=_caption_media_type(extension),
            extension=f".{extension.lower()}",
            text_sufficient=sufficient,
            completeness=completeness,
            coverage_ratio=coverage,
            source_url=source_url,
        )

    def _transcribe(
        self,
        locator: str,
        *,
        video_id: str,
        work_dir: Path,
        requested_language: str | None,
        duration_seconds: float | None,
    ) -> tuple[_TranscriptCandidate | None, list[dict[str, Any]]]:
        failures: list[dict[str, Any]] = []
        audio_path: Path | None = None
        try:
            audio_path = self.backend.download_audio(locator, work_dir, video_id)
            result = self.transcriber.transcribe(  # type: ignore[union-attr]
                audio_path,
                language=requested_language,
                work_dir=work_dir,
            )
            if isinstance(result, str):
                raw = result
                language = requested_language
                extension = "txt"
                media_type = "text/plain; charset=utf-8"
                reported_complete = None
                reported_coverage = None
            elif isinstance(result, dict):
                raw_value = result.get("vtt") or result.get("srt") or result.get("text")
                if not isinstance(raw_value, str):
                    raise ToolError("TRANSCRIPTION_OUTPUT_INVALID", "转录结果缺少文本。")
                raw = raw_value
                language = _clean_string(result.get("language")) or requested_language
                extension = "vtt" if isinstance(result.get("vtt"), str) else (
                    "srt" if isinstance(result.get("srt"), str) else "txt"
                )
                media_type = _caption_media_type(extension)
                reported_complete = result.get("complete") if isinstance(result.get("complete"), bool) else None
                reported_coverage = _number(result.get("coverageRatio"))
            else:
                raise ToolError("TRANSCRIPTION_OUTPUT_INVALID", "转录结果结构无效。")
            normalized, parsed_coverage = _normalize_caption(raw, extension, duration_seconds)
            coverage = reported_coverage if reported_coverage is not None else parsed_coverage
            sufficient = len(_text_characters(normalized)) >= self.minimum_text_characters
            completeness = _completeness(coverage, sufficient, self.complete_coverage_ratio)
            if reported_complete is True and sufficient:
                completeness = "complete"
            elif reported_complete is False:
                completeness = "incomplete"
            candidate = _TranscriptCandidate(
                method="local-transcription",
                language=language,
                raw_text=raw,
                normalized_text=normalized,
                media_type=media_type,
                extension=f".{extension}",
                text_sufficient=sufficient,
                completeness=completeness,
                coverage_ratio=coverage,
                reported_complete=reported_complete,
            )
            if not sufficient:
                failures.append(
                    _safe_failure(
                        ToolError(
                            "TRANSCRIPTION_TEXT_INSUFFICIENT",
                            "本地转录完成，但可核验文字仍不足。",
                            details={"textCharacters": len(_text_characters(normalized))},
                        ),
                        stage="transcription",
                    )
                )
            return candidate, failures
        except ToolError as exc:
            failures.append(_safe_failure(exc, stage="transcription"))
            return None, failures
        except Exception as exc:
            failures.append(
                _safe_failure(
                    ToolError(
                        "TRANSCRIPTION_FAILED",
                        "本地音频转录失败。",
                        retryable=True,
                        details={"errorType": type(exc).__name__},
                    ),
                    stage="transcription",
                )
            )
            return None, failures
        finally:
            if audio_path is not None and not self.keep_temporary_audio:
                try:
                    audio_path.unlink(missing_ok=True)
                except OSError:
                    failures.append(
                        {
                            "stage": "temporary-audio-cleanup",
                            "code": "TEMPORARY_AUDIO_CLEANUP_FAILED",
                            "message": "临时音频转录后清理失败，请在任务详情中手动清理。",
                            "retryable": True,
                            "details": {},
                        }
                    )

    def _base_result(
        self,
        *,
        source_type: str,
        locator: str,
        collected_at: str,
        canonical_locator: str,
    ) -> dict[str, Any]:
        return {
            "sourceType": source_type,
            "status": "DISCOVERED",
            "title": None,
            "language": None,
            "platform": "youtube",
            "platformId": None,
            "canonicalUrl": None,
            "canonicalLocator": canonical_locator,
            "provenance": {
                "kind": "public-url",
                "locator": locator,
                "collectedAt": collected_at,
                "adapterId": self.adapter_id,
                "adapterVersion": self.adapter_version,
            },
            "rightsBoundary": {
                "accessLevel": "metadata-only",
                "basis": (
                    "Only public YouTube metadata/captions and optional temporary local audio transcription are used; "
                    "no login, paywall, DRM, captcha, private Studio data, or access-control bypass is performed."
                ),
                "confirmedByUser": False,
            },
            "metadata": {},
            "assets": [],
            "contentSha256": None,
            "report": {},
        }

    def _blocked_from_error(
        self,
        base: dict[str, Any],
        error: ToolError,
        supplement_options: list[dict[str, Any]],
    ) -> dict[str, Any]:
        return self._blocked(
            base,
            code=error.code,
            message=error.message,
            retryable=error.retryable,
            details=error.details,
            supplement_options=supplement_options,
        )

    def _blocked(
        self,
        base: dict[str, Any],
        *,
        code: str,
        message: str,
        supplement_options: list[dict[str, Any]],
        retryable: bool = False,
        details: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        base["status"] = "BLOCKED"
        base["report"] = {
            "complete": False,
            "completeness": "blocked",
            "collectedAt": base["provenance"]["collectedAt"],
            "failures": [
                {
                    "stage": "collection",
                    "code": code,
                    "message": message,
                    "retryable": retryable,
                    "details": redact(dict(details or {})),
                }
            ],
            "sourceBoundary": (
                _channel_source_boundary()
                if base.get("sourceType") == "reference-channel"
                else _video_source_boundary()
            ),
            "supplementOptions": supplement_options,
            "bodyGeneratedFromMetadata": False,
        }
        return base


def _clean_string(value: Any, *, allow_empty: bool = False) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = value.strip()
    return cleaned if cleaned or allow_empty else None


def _number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _integer(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return None


def _collected_at(value: datetime | str) -> str:
    if isinstance(value, datetime):
        normalized = value.astimezone(UTC) if value.tzinfo else value.replace(tzinfo=UTC)
        return normalized.isoformat(timespec="seconds").replace("+00:00", "Z")
    cleaned = _clean_string(value)
    if not cleaned:
        raise ToolError("CLOCK_INVALID", "采集时钟没有返回有效时间。")
    return cleaned


def _canonical_video_locator(locator: str | None) -> tuple[str | None, str | None]:
    if not locator:
        return None, None
    if _VIDEO_ID.fullmatch(locator) and len(locator) == 11:
        return f"https://www.youtube.com/watch?v={locator}", locator
    parsed = urllib.parse.urlsplit(locator if "://" in locator else f"https://{locator}")
    host = (parsed.hostname or "").lower()
    if host not in _YOUTUBE_HOSTS:
        return None, None
    video_id: str | None = None
    if host.endswith("youtu.be"):
        video_id = parsed.path.strip("/").split("/")[0]
    elif parsed.path.rstrip("/") == "/watch":
        video_id = urllib.parse.parse_qs(parsed.query).get("v", [None])[0]
    else:
        parts = [part for part in parsed.path.split("/") if part]
        if len(parts) >= 2 and parts[0] in {"shorts", "embed", "live"}:
            video_id = parts[1]
    if not video_id or not _VIDEO_ID.fullmatch(video_id):
        return None, None
    return f"https://www.youtube.com/watch?v={video_id}", video_id


def _is_plain_channel_name(locator: str) -> bool:
    return (
        "://" not in locator
        and "/" not in locator
        and "." not in locator
        and not locator.startswith(("UC", "@"))
    )


def _canonical_channel_input(locator: str | None) -> str | None:
    if not locator:
        return None
    if locator.startswith("UC") and _VIDEO_ID.fullmatch(locator):
        return f"https://www.youtube.com/channel/{locator}/videos"
    if locator.startswith("@") and len(locator) > 1:
        return f"https://www.youtube.com/{locator}/videos"
    if _is_plain_channel_name(locator):
        return locator
    parsed = urllib.parse.urlsplit(locator if "://" in locator else f"https://{locator}")
    if (parsed.hostname or "").lower() not in _YOUTUBE_HOSTS - {"youtu.be", "www.youtu.be"}:
        return None
    parts = [part for part in parsed.path.split("/") if part]
    if not parts or (parts[0] not in {"channel", "c", "user"} and not parts[0].startswith("@")):
        return None
    path = "/".join(parts[:2] if parts[0] in {"channel", "c", "user"} else parts[:1])
    return f"https://www.youtube.com/{path}/videos"


def _canonical_channel_url(channel_id: str | None, fallback: str | None) -> str | None:
    if channel_id:
        return f"https://www.youtube.com/channel/{channel_id}"
    if fallback and fallback.startswith("https://"):
        return fallback.removesuffix("/videos").rstrip("/")
    return None


def _public_hashtags(description: str, explicit: Any) -> list[str]:
    candidates: list[str] = []
    if isinstance(explicit, list):
        candidates.extend(item for item in explicit if isinstance(item, str))
    candidates.extend(f"#{match.group(1)}" for match in _HASHTAG.finditer(description))
    result: list[str] = []
    seen: set[str] = set()
    for raw in candidates:
        value = raw.strip().rstrip(".,!?;:，。！？；：、)]}〉》」』")
        if not value:
            continue
        if not value.startswith("#"):
            value = f"#{value}"
        key = value.casefold()
        if key not in seen:
            result.append(value)
            seen.add(key)
    return result


def _select_thumbnail(metadata: Mapping[str, Any]) -> dict[str, Any] | None:
    raw = metadata.get("thumbnails")
    candidates = [item for item in raw if isinstance(item, dict)] if isinstance(raw, list) else []
    if not candidates and _clean_string(metadata.get("thumbnail")):
        candidates = [{"url": metadata["thumbnail"]}]
    usable = [item for item in candidates if _clean_string(item.get("url"))]
    if not usable:
        return None

    def score(item: Mapping[str, Any]) -> tuple[float, float, float]:
        width = _number(item.get("width")) or 0.0
        height = _number(item.get("height")) or 0.0
        preference = _number(item.get("preference")) or 0.0
        return (width * height, preference, width)

    selected = max(usable, key=score)
    return {
        key: value
        for key, value in {
            "url": _clean_string(selected.get("url")),
            "width": _integer(selected.get("width")),
            "height": _integer(selected.get("height")),
            "id": _clean_string(selected.get("id")),
            "ext": _clean_string(selected.get("ext")),
        }.items()
        if value is not None
    }


def _asset_type(url: str, declared_extension: Any) -> tuple[str, str]:
    extension = _clean_string(declared_extension)
    if extension:
        suffix = f".{extension.lower().lstrip('.')}"
    else:
        suffix = Path(urllib.parse.urlsplit(url).path).suffix.lower()
    if suffix not in {".jpg", ".jpeg", ".png", ".webp", ".gif"}:
        suffix = ".jpg"
    return suffix, mimetypes.types_map.get(suffix, "image/jpeg")


def _caption_media_type(extension: str) -> str:
    return {
        "vtt": "text/vtt; charset=utf-8",
        "srt": "application/x-subrip; charset=utf-8",
        "json3": "application/json",
        "json": "application/json",
        "ttml": "application/ttml+xml",
        "srv1": "application/xml",
        "srv2": "application/xml",
        "srv3": "application/xml",
    }.get(extension.lower(), "text/plain; charset=utf-8")


def _ordered_tracks(
    tracks: Mapping[str, Any],
    requested_language: str | None,
    metadata_language: str | None,
) -> list[tuple[str, Mapping[str, Any]]]:
    languages = [key for key, value in tracks.items() if key != "live_chat" and isinstance(value, list)]

    def language_score(language: str) -> tuple[int, str]:
        lowered = language.casefold()
        requested = (requested_language or "").casefold()
        metadata = (metadata_language or "").casefold()
        if requested and lowered == requested:
            return (0, lowered)
        if requested and lowered.split("-")[0] == requested.split("-")[0]:
            return (1, lowered)
        if metadata and lowered == metadata:
            return (2, lowered)
        if metadata and lowered.split("-")[0] == metadata.split("-")[0]:
            return (3, lowered)
        return (4, lowered)

    extension_preference = {"vtt": 0, "srt": 1, "json3": 2, "ttml": 3, "srv3": 4, "srv2": 5, "srv1": 6}
    ordered: list[tuple[str, Mapping[str, Any]]] = []
    for language in sorted(languages, key=language_score):
        values = tracks[language]
        ordered.extend(
            (language, item)
            for item in sorted(
                (item for item in values if isinstance(item, dict)),
                key=lambda item: extension_preference.get(str(item.get("ext", "")).lower(), 99),
            )
        )
    return ordered


def _normalize_caption(raw: str, extension: str, duration_seconds: float | None) -> tuple[str, float | None]:
    coverage = _caption_coverage(raw, duration_seconds)
    lowered = extension.lower()
    if lowered in {"json3", "json"}:
        try:
            document = json.loads(raw)
        except json.JSONDecodeError:
            text = raw
        else:
            events = document.get("events") if isinstance(document, dict) else None
            fragments: list[str] = []
            if isinstance(events, list):
                if duration_seconds and duration_seconds > 0:
                    event_ends = [
                        (float(event.get("tStartMs", 0)) + float(event.get("dDurationMs", 0))) / 1000.0
                        for event in events
                        if isinstance(event, dict)
                        and isinstance(event.get("tStartMs"), (int, float))
                        and isinstance(event.get("dDurationMs"), (int, float))
                    ]
                    if event_ends:
                        coverage = round(max(0.0, min(max(event_ends) / duration_seconds, 1.0)), 4)
                for event in events:
                    if not isinstance(event, dict):
                        continue
                    segments = event.get("segs")
                    if isinstance(segments, list):
                        fragments.append("".join(str(segment.get("utf8", "")) for segment in segments if isinstance(segment, dict)))
            text = "\n".join(fragments)
    else:
        text = raw
    text = re.sub(r"(?m)^\s*(?:WEBVTT|Kind:.*|Language:.*|NOTE.*)\s*$", "", text)
    text = re.sub(r"(?m)^\s*\d+\s*$", "", text)
    text = re.sub(r"(?m)^\s*(?:\d+:)?\d{2}:\d{2}[.,]\d{3}\s+-->.*$", "", text)
    text = re.sub(r"<\d{2}:\d{2}:\d{2}[.,]\d{3}>", "", text)
    text = _TAG.sub("", text)
    text = html.unescape(text)
    lines: list[str] = []
    previous = None
    for raw_line in text.splitlines():
        line = re.sub(r"\s+", " ", raw_line).strip()
        if not line or line == previous:
            continue
        if previous and line.startswith(previous):
            lines[-1] = line
            previous = line
            continue
        if previous and previous.startswith(line):
            continue
        lines.append(line)
        previous = line
    return "\n".join(lines).strip(), coverage


def _caption_coverage(raw: str, duration_seconds: float | None) -> float | None:
    if duration_seconds is None or duration_seconds <= 0:
        return None
    ends = [_timestamp_seconds(match.group("end")) for match in _TIMESTAMP.finditer(raw)]
    if not ends:
        return None
    return round(max(0.0, min(max(ends) / duration_seconds, 1.0)), 4)


def _timestamp_seconds(value: str) -> float:
    parts = value.replace(",", ".").split(":")
    if len(parts) == 2:
        hours = 0
        minutes, seconds = parts
    else:
        hours, minutes, seconds = parts
    return int(hours) * 3600 + int(minutes) * 60 + float(seconds)


def _text_characters(text: str) -> str:
    return re.sub(r"\s+", "", text)


def _completeness(coverage: float | None, sufficient: bool, complete_ratio: float) -> str:
    if not sufficient:
        return "incomplete"
    if coverage is None:
        return "unknown"
    return "complete" if coverage >= complete_ratio else "incomplete"


def _published_at(metadata: Mapping[str, Any]) -> str | None:
    timestamp = metadata.get("timestamp")
    if isinstance(timestamp, (int, float)) and not isinstance(timestamp, bool):
        return datetime.fromtimestamp(timestamp, UTC).isoformat(timespec="seconds").replace("+00:00", "Z")
    upload_date = _clean_string(metadata.get("upload_date")) or _clean_string(metadata.get("release_date"))
    if upload_date and re.fullmatch(r"\d{8}", upload_date):
        return f"{upload_date[:4]}-{upload_date[4:6]}-{upload_date[6:]}T00:00:00Z"
    return _clean_string(metadata.get("publishedAt"))


def _safe_failure(error: ToolError, *, stage: str) -> dict[str, Any]:
    return {
        "stage": stage,
        "code": error.code,
        "message": error.message,
        "retryable": error.retryable,
        "details": redact(error.details),
    }


def _video_source_boundary() -> dict[str, Any]:
    return {
        "included": [
            "public page metadata",
            "public Hashtags found in the description",
            "public thumbnail",
            "public caption tracks or optional temporary local audio transcription",
        ],
        "excluded": [
            "YouTube Studio or Analytics data",
            "private backend Tags",
            "login-only or access-restricted material",
            "story/body text inferred from title, thumbnail, metrics, or comments",
        ],
        "unknownFactsRemainUnknown": True,
    }


def _channel_source_boundary() -> dict[str, Any]:
    return {
        "included": [
            "public channel identity",
            "best-effort lightweight public video list",
            "public metadata and metrics present in the list response",
        ],
        "excluded": [
            "YouTube Studio or Analytics data",
            "private/deleted video facts absent from the public response",
            "video transcripts, story analysis, or generated body text",
        ],
        "missingEntriesAreNotDeletionProof": True,
        "unknownFactsRemainUnknown": True,
    }


def _video_supplement_options(*, include_locator: bool = False) -> list[dict[str, Any]]:
    options: list[dict[str, Any]] = []
    if include_locator:
        options.append({"kind": "correct-youtube-video-url", "required": True})
    options.extend(
        [
            {"kind": "local-subtitle-or-transcript", "formats": ["VTT", "SRT", "TXT"]},
            {"kind": "local-video-or-audio", "formats": ["MP4", "WEBM", "MP3", "WAV", "M4A"]},
            {"kind": "pasted-text", "description": "用户可提供有权使用的字幕、文稿或剧情摘要。"},
        ]
    )
    return options


def _previous_videos(previous_snapshot: Mapping[str, Any] | None) -> dict[str, dict[str, Any]]:
    if not isinstance(previous_snapshot, Mapping):
        return {}
    metadata = previous_snapshot.get("metadata")
    videos = metadata.get("videos") if isinstance(metadata, Mapping) else previous_snapshot.get("videos")
    if not isinstance(videos, list):
        return {}
    return {
        str(item["videoId"]): dict(item)
        for item in videos
        if isinstance(item, Mapping) and isinstance(item.get("videoId"), str)
    }


def _inventory_fingerprint(video: Mapping[str, Any]) -> str:
    comparable = {
        key: video.get(key)
        for key in (
            "videoId",
            "canonicalUrl",
            "title",
            "description",
            "publicHashtags",
            "publishedAt",
            "durationSeconds",
            "publicMetrics",
            "thumbnail",
        )
    }
    encoded = json.dumps(comparable, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _environment_command(
    json_name: str,
    executable_name: str,
    *,
    default: tuple[str, ...] | None,
) -> tuple[str, ...] | None:
    raw_json = os.environ.get(json_name)
    executable = os.environ.get(executable_name)
    if raw_json:
        try:
            value = json.loads(raw_json)
        except json.JSONDecodeError as exc:
            raise ToolError("YOUTUBE_CONFIG_INVALID", f"{json_name} 不是有效 JSON 命令数组。") from exc
        if not isinstance(value, list) or not value or not all(isinstance(item, str) and item for item in value):
            raise ToolError("YOUTUBE_CONFIG_INVALID", f"{json_name} 必须是非空字符串数组。")
        return tuple(value)
    if executable:
        return (executable,)
    return default


def _environment_float(
    name: str,
    default: float,
    *,
    minimum: float,
    maximum: float,
) -> float:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        value = float(raw)
    except ValueError as exc:
        raise ToolError("YOUTUBE_CONFIG_INVALID", f"{name} 必须是数字。") from exc
    return max(minimum, min(value, maximum))


def _environment_integer(
    name: str,
    default: int,
    *,
    minimum: int,
    maximum: int,
) -> int:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise ToolError("YOUTUBE_CONFIG_INVALID", f"{name} 必须是整数。") from exc
    return max(minimum, min(value, maximum))


__all__ = [
    "ADAPTER_ID",
    "ADAPTER_VERSION",
    "CommandResult",
    "CommandRunner",
    "CommandTranscriber",
    "HttpsAssetFetcher",
    "SubprocessCommandRunner",
    "Transcriber",
    "YouTubeAdapter",
    "YouTubeBackend",
    "YtDlpBackend",
]
