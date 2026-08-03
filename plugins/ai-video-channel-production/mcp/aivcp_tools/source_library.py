from __future__ import annotations

import hashlib
import json
import mimetypes
import os
import re
import shutil
import sqlite3
import tempfile
import uuid
from contextlib import closing
from pathlib import Path
from typing import Any, Callable
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from .contracts import canonical_hash, utc_now, with_hash
from .errors import ToolError
from .store import ChannelStore


SOURCE_LIBRARY_VERSION = "1.0.0"
SOURCE_PACKAGE_SCHEMA_VERSION = "1.0.0"
SOURCE_STATUSES = {
    "DISCOVERED",
    "METADATA_READY",
    "CONTENT_READY",
    "PARTIAL",
    "BLOCKED",
    "FAILED",
    "ARCHIVED",
}
TERMINAL_JOB_STATES = {"COMPLETED", "PARTIAL", "NEEDS_SUPPLEMENT", "FAILED", "CANCELLED"}
TRACKING_QUERY_KEYS = {"fbclid", "gclid", "mc_cid", "mc_eid", "si", "feature"}
YOUTUBE_HOSTS = {"youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be"}
SITE_HOSTS = {
    "syosetu.com",
    "ncode.syosetu.com",
    "api.syosetu.com",
    "kakuyomu.jp",
    "aozora.gr.jp",
    "www.aozora.gr.jp",
    "qidian.com",
    "www.qidian.com",
    "book.qidian.com",
    "fanqienovel.com",
    "www.fanqienovel.com",
    "zh.wikisource.org",
    "royalroad.com",
    "www.royalroad.com",
    "scribblehub.com",
    "www.scribblehub.com",
    "gutenberg.org",
    "www.gutenberg.org",
    "dev.gutenberg.org",
}
SOURCE_DIRECTORY = {
    "reference-channel": "reference-channels",
    "youtube-video": "youtube-videos",
    "novel-web": "novels",
    "local-file": "user-files",
    "pasted-text": "user-files",
    "batch-links": "user-files",
}


def _json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _json_hash(value: Any) -> str:
    return hashlib.sha256(_json_dumps(value).encode("utf-8")).hexdigest()


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_filename(value: str, fallback: str) -> str:
    name = Path(value).name.strip().replace("\x00", "")
    name = re.sub(r"[<>:\"/\\|?*]+", "_", name)
    name = re.sub(r"\s+", " ", name).strip(" .")
    return (name or fallback)[:180]


def _atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(value, stream, ensure_ascii=False, sort_keys=True, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_name, path)
    except Exception:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass
        raise


def canonicalize_url(value: str) -> str:
    try:
        parsed = urlsplit(value.strip())
    except ValueError as exc:
        raise ToolError("SOURCE_URL_INVALID", "资料网址无效。") from exc
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
        raise ToolError("SOURCE_URL_INVALID", "资料网址必须是 http 或 https 公开网址。")
    scheme = parsed.scheme.lower()
    hostname = parsed.hostname.lower().rstrip(".")
    port = parsed.port
    netloc = hostname if port is None or (scheme, port) in {("http", 80), ("https", 443)} else f"{hostname}:{port}"
    path = re.sub(r"/{2,}", "/", parsed.path or "/")
    if path != "/":
        path = path.rstrip("/")
    query_items = []
    for key, item in parse_qsl(parsed.query, keep_blank_values=True):
        lowered = key.lower()
        if lowered.startswith("utm_") or lowered in TRACKING_QUERY_KEYS:
            continue
        query_items.append((key, item))
    query_items.sort()
    query = urlencode(query_items, doseq=True)

    if hostname in YOUTUBE_HOSTS:
        video_id: str | None = None
        if hostname == "youtu.be":
            video_id = path.strip("/").split("/")[0]
        elif path == "/watch":
            video_id = dict(query_items).get("v")
        elif path.startswith(("/shorts/", "/live/", "/embed/")):
            video_id = path.split("/")[2]
        if video_id and re.fullmatch(r"[A-Za-z0-9_-]{6,32}", video_id):
            return f"https://www.youtube.com/watch?v={video_id}"
        netloc = "www.youtube.com"
    return urlunsplit((scheme, netloc, path, query, ""))


def _youtube_kind(url: str) -> str:
    parsed = urlsplit(url)
    query = dict(parse_qsl(parsed.query))
    if parsed.hostname in YOUTUBE_HOSTS and (
        parsed.path in {"/watch"} and query.get("v")
        or parsed.hostname == "youtu.be"
        or parsed.path.startswith(("/shorts/", "/live/", "/embed/"))
    ):
        return "youtube-video"
    return "reference-channel"


def _next_version(current: str | None) -> str:
    if not current:
        return "1.0.0"
    match = re.fullmatch(r"(\d+)\.(\d+)\.(\d+)(?:-[0-9A-Za-z.-]+)?", current)
    if not match:
        raise ToolError("SOURCE_VERSION_INVALID", "资料包当前版本无效，禁止覆盖。")
    return f"{match.group(1)}.{match.group(2)}.{int(match.group(3)) + 1}"


class SourceLibrary:
    def __init__(
        self,
        store: ChannelStore,
        *,
        adapter_factory: Callable[[dict[str, Any], Path], dict[str, Any]] | None = None,
    ) -> None:
        self.store = store
        self.adapter_factory = adapter_factory

    def capabilities(self) -> dict[str, Any]:
        return {
            "available": True,
            "version": SOURCE_LIBRARY_VERSION,
            "sourcePackageSchemaVersion": SOURCE_PACKAGE_SCHEMA_VERSION,
            "sourceTypes": sorted(SOURCE_DIRECTORY),
            "localFileTypes": [".txt", ".md", ".epub", ".pdf", ".docx"],
            "deduplication": ["platform-id", "canonical-url", "sha256"],
            "supports": {
                "confirmationCard": True,
                "progress": True,
                "cancelResume": True,
                "incrementalUpdate": True,
                "persistentSearch": True,
                "contentAnalysis": False,
                "contentGeneration": False,
            },
        }

    def _connection(self, channel_profile_id: str) -> sqlite3.Connection:
        path = self.store.channel_path(channel_profile_id) / "channel.db"
        if not path.is_file():
            raise ToolError("CHANNEL_LIBRARY_NOT_READY", "频道资料库尚未创建或不可用。")
        self.store._ensure_channel_schema(path, channel_profile_id)
        connection = sqlite3.connect(path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        return connection

    def _normalize_item(self, value: Any) -> dict[str, Any]:
        item = {"locator": value} if isinstance(value, str) else dict(value) if isinstance(value, dict) else None
        if item is None:
            raise ToolError("SOURCE_INPUT_INVALID", "每项资料必须是链接、文件路径或资料对象。")
        if isinstance(item.get("text"), str):
            text = item["text"]
            if not text.strip():
                raise ToolError("SOURCE_INPUT_INVALID", "粘贴文字不能为空。")
            item["kind"] = "pasted-text"
            item.setdefault("locator", f"user-input:{_sha256_bytes(text.encode('utf-8'))}")
            return item
        locator = item.get("locator") or item.get("path")
        if not isinstance(locator, str) or not locator.strip():
            raise ToolError("SOURCE_INPUT_INVALID", "资料项缺少 locator、path 或 text。")
        locator = locator.strip()
        item["locator"] = locator
        if re.match(r"^https?://", locator, re.IGNORECASE):
            canonical = canonicalize_url(locator)
            host = (urlsplit(canonical).hostname or "").lower()
            item["canonicalLocator"] = canonical
            if host in YOUTUBE_HOSTS:
                item["kind"] = item.get("kind") or _youtube_kind(canonical)
            elif host in SITE_HOSTS:
                item["kind"] = item.get("kind") or "novel-web"
            else:
                item["kind"] = item.get("kind") or "public-url"
            return item
        path = Path(locator).expanduser().resolve()
        if not path.is_file():
            raise ToolError(
                "SOURCE_FILE_NOT_FOUND",
                "本地资料文件不存在。",
                details={"filename": Path(locator).name},
            )
        extension = path.suffix.lower()
        if extension not in {".txt", ".md", ".epub", ".pdf", ".docx", ".srt", ".vtt", ".mp3", ".wav", ".mp4"}:
            raise ToolError("SOURCE_FILE_TYPE_UNSUPPORTED", "本地资料文件类型暂不支持。", details={"extension": extension})
        item["locator"] = str(path)
        item["canonicalLocator"] = str(path).casefold()
        item["kind"] = item.get("kind") or "local-file"
        item["fileSha256"] = _sha256_file(path)
        item["sizeBytes"] = path.stat().st_size
        return item

    def prepare_add(
        self,
        *,
        task_id: Any,
        channel_profile_id: Any,
        binding_proof: Any,
        inputs: Any,
        options: Any = None,
    ) -> dict[str, Any]:
        self.store.assert_binding(
            task_id=task_id,
            channel_profile_id=channel_profile_id,
            binding_proof=binding_proof,
        )
        if not isinstance(inputs, list) or not inputs or len(inputs) > 500:
            raise ToolError("SOURCE_INPUT_INVALID", "inputs 必须包含 1 到 500 项资料。")
        normalized = [self._normalize_item(item) for item in inputs]
        safe_options = dict(options) if isinstance(options, dict) else {}
        request = {"inputs": normalized, "options": safe_options}
        plan_hash = _json_hash(request)
        job_id = f"acq_{uuid.uuid4().hex}"
        now = utc_now()
        channel_summary = self.store.get_channel(channel_profile_id)
        channel = channel_summary.get("channelProfile")
        if not isinstance(channel, dict):
            raise ToolError("CHANNEL_LIBRARY_NOT_READY", "频道正式档案缺失，禁止写入资料包。")
        kinds = sorted({item["kind"] for item in normalized})
        scopes = {
            "reference-channel": "尽量完整的轻量视频清单",
            "youtube-video": "单视频元数据、封面与可用文稿",
            "novel-web": "网站能力范围内的作品建档、目录与允许内容",
            "local-file": "保留原文件并生成标准化文本",
            "pasted-text": "保留用户输入并生成标准化文本",
            "public-url": "公开页面轻量读取或明确补充路径",
        }
        card = {
            "cardType": "source-add-confirmation",
            "acquisitionJobId": job_id,
            "planHash": plan_hash,
            "storeInChannel": {
                "channelProfileId": channel_profile_id,
                "channelSerial": channel["publisherBinding"]["channelSerial"],
                "displayName": channel["displayName"],
            },
            "source": {"types": kinds, "count": len(normalized)},
            "collectionScope": [scopes.get(kind, "来源建档与允许范围内读取") for kind in kinds],
            "willSave": ["来源元数据", "来源边界", "原始文件或公开资产", "标准化文本", "采集报告", "哈希与版本索引"],
            "automaticFallback": "视频按人工字幕、自动字幕、已配置本地转录降级；失败时要求用户补充文件。",
            "notExecuted": ["拆视频", "拆书", "仿写", "推荐选题", "生成文案", "工坊生产"],
            "estimatedWork": {
                "items": len(normalized),
                "bytes": sum(int(item.get("sizeBytes", 0)) for item in normalized) or None,
                "note": "网络清单和转录工作量在开始后计算。",
            },
            "choices": ["确认入库", "修改本次范围", "取消"],
        }
        with closing(self._connection(channel_profile_id)) as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                """
                INSERT INTO acquisition_jobs(
                    acquisition_job_id,task_id,channel_profile_id,plan_hash,state,stage,request_json,
                    confirmation_json,checkpoint_json,cancel_requested,recoverable,error_code,error_message,
                    created_at,updated_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    job_id,
                    task_id,
                    channel_profile_id,
                    plan_hash,
                    "WAITING_CONFIRMATION",
                    "IDENTIFYING",
                    _json_dumps(request),
                    None,
                    _json_dumps({"total": len(normalized), "completed": 0}),
                    0,
                    1,
                    None,
                    None,
                    now,
                    now,
                ),
            )
            connection.executemany(
                "INSERT INTO acquisition_job_items VALUES(?,?,?,?,?,?,?,?,?,?)",
                [
                    (job_id, index, _json_dumps(item), "WAITING", None, None, None, None, 0, now)
                    for index, item in enumerate(normalized)
                ],
            )
            connection.commit()
        return card

    def confirm_add(
        self,
        *,
        task_id: Any,
        channel_profile_id: Any,
        binding_proof: Any,
        acquisition_job_id: Any,
        plan_hash: Any,
        confirmation: Any,
    ) -> dict[str, Any]:
        self.store.assert_binding(
            task_id=task_id,
            channel_profile_id=channel_profile_id,
            binding_proof=binding_proof,
        )
        if not isinstance(confirmation, dict) or confirmation.get("confirmed") is not True:
            raise ToolError("SOURCE_CONFIRMATION_REQUIRED", "资料入库需要用户明确确认。")
        job = self._job_row(channel_profile_id, acquisition_job_id)
        if job["task_id"] != task_id or job["channel_profile_id"] != channel_profile_id:
            raise ToolError("SOURCE_JOB_BINDING_MISMATCH", "资料任务不属于当前频道任务。")
        if job["plan_hash"] != plan_hash:
            raise ToolError("SOURCE_PLAN_CHANGED", "资料计划已变化，请重新查看确认卡。")
        if job["state"] == "WAITING_CONFIRMATION":
            with closing(self._connection(channel_profile_id)) as connection:
                connection.execute(
                    "UPDATE acquisition_jobs SET state='QUEUED',stage='DOWNLOADING',confirmation_json=?,updated_at=? WHERE acquisition_job_id=?",
                    (_json_dumps(confirmation), utc_now(), acquisition_job_id),
                )
                connection.commit()
        return self.resume_job(
            task_id=task_id,
            channel_profile_id=channel_profile_id,
            binding_proof=binding_proof,
            acquisition_job_id=acquisition_job_id,
        )

    def _job_row(self, channel_profile_id: str, acquisition_job_id: Any) -> sqlite3.Row:
        if not isinstance(acquisition_job_id, str) or not acquisition_job_id:
            raise ToolError("INVALID_ARGUMENT", "acquisitionJobId 是必填项。")
        with closing(self._connection(channel_profile_id)) as connection:
            row = connection.execute(
                "SELECT * FROM acquisition_jobs WHERE acquisition_job_id=?", (acquisition_job_id,)
            ).fetchone()
        if row is None:
            raise ToolError("SOURCE_JOB_NOT_FOUND", "没有找到指定资料任务。")
        return row

    def _collect(self, item: dict[str, Any], work_dir: Path) -> dict[str, Any]:
        if self.adapter_factory is not None:
            return self.adapter_factory(item, work_dir)
        kind = item["kind"]
        if kind == "pasted-text":
            text = item["text"]
            language = item.get("language") or "und"
            return {
                "sourceType": "pasted-text",
                "status": "CONTENT_READY",
                "title": item.get("title") or "用户粘贴文字",
                "language": language,
                "canonicalLocator": item["locator"],
                "provenance": {
                    "kind": "user-input",
                    "locator": item["locator"],
                    "collectedAt": utc_now(),
                    "adapterId": "builtin-pasted-text",
                    "adapterVersion": SOURCE_LIBRARY_VERSION,
                },
                "rightsBoundary": {
                    "accessLevel": "user-authorized",
                    "basis": "用户在当前任务中主动提供文字。",
                    "confirmedByUser": True,
                },
                "metadata": {"characterCount": len(text), "paragraphCount": len([x for x in text.splitlines() if x.strip()])},
                "contentSha256": _sha256_bytes(text.encode("utf-8")),
                "assets": [
                    {"role": "raw", "mediaType": "text/plain", "filename": "pasted.txt", "data": text},
                    {"role": "normalized", "mediaType": "text/plain", "filename": "content.txt", "data": text.replace("\r\n", "\n")},
                ],
                "report": {"complete": True, "sourceBoundary": "user-input"},
            }
        if kind in {"youtube-video", "reference-channel"}:
            try:
                from .source_youtube import YouTubeAdapter
            except ImportError as exc:
                raise ToolError("SOURCE_ADAPTER_UNAVAILABLE", "YouTube 资料适配器尚未安装。") from exc
            adapter = YouTubeAdapter.from_environment() if hasattr(YouTubeAdapter, "from_environment") else YouTubeAdapter()
            if kind == "youtube-video":
                return adapter.collect_video(
                    item["locator"],
                    requested_language=item.get("language"),
                    allow_transcription=bool(item.get("allowTranscription", False)),
                    work_dir=work_dir,
                )
            return adapter.collect_channel(item["locator"], work_dir=work_dir, previous_snapshot=item.get("previousSnapshot"))
        if kind == "local-file":
            try:
                from .source_documents import DocumentAdapter
            except ImportError as exc:
                raise ToolError("SOURCE_ADAPTER_UNAVAILABLE", "本地文档适配器尚未安装。") from exc
            return DocumentAdapter().collect(
                item["locator"], language=item.get("language"), authorized=item.get("authorized", True)
            )
        if kind in {"novel-web", "public-url"}:
            try:
                from .source_sites import SiteAdapterRegistry
            except ImportError as exc:
                raise ToolError("SOURCE_ADAPTER_UNAVAILABLE", "小说网站适配器尚未安装。") from exc
            registry = SiteAdapterRegistry.from_environment() if hasattr(SiteAdapterRegistry, "from_environment") else SiteAdapterRegistry()
            return registry.collect(
                item["locator"],
                language=item.get("language"),
                user_authorized=bool(item.get("authorized", False)),
                supplied_file=item.get("suppliedFile"),
            )
        raise ToolError("SOURCE_TYPE_UNSUPPORTED", "当前资料类型尚不支持。", details={"kind": kind})

    def resume_job(
        self,
        *,
        task_id: Any,
        channel_profile_id: Any,
        binding_proof: Any,
        acquisition_job_id: Any,
        supplements: Any = None,
    ) -> dict[str, Any]:
        self.store.assert_binding(
            task_id=task_id,
            channel_profile_id=channel_profile_id,
            binding_proof=binding_proof,
        )
        job = self._job_row(channel_profile_id, acquisition_job_id)
        if job["task_id"] != task_id:
            raise ToolError("SOURCE_JOB_BINDING_MISMATCH", "资料任务不属于当前 Codex 任务。")
        if job["state"] == "WAITING_CONFIRMATION":
            raise ToolError("SOURCE_CONFIRMATION_REQUIRED", "请先确认资料入库卡。")
        if isinstance(supplements, list):
            self._apply_supplements(channel_profile_id, acquisition_job_id, supplements)
        with closing(self._connection(channel_profile_id)) as connection:
            connection.execute(
                "UPDATE acquisition_jobs SET state='RUNNING',stage='DOWNLOADING',cancel_requested=0,error_code=NULL,error_message=NULL,updated_at=? WHERE acquisition_job_id=?",
                (utc_now(), acquisition_job_id),
            )
            connection.commit()

        work_root = self.store.data_root / "temp" / "acquisition" / acquisition_job_id
        work_root.mkdir(parents=True, exist_ok=True)
        with closing(self._connection(channel_profile_id)) as connection:
            rows = connection.execute(
                "SELECT * FROM acquisition_job_items WHERE acquisition_job_id=? ORDER BY item_index",
                (acquisition_job_id,),
            ).fetchall()
        for row in rows:
            if row["state"] == "COMPLETED":
                continue
            current = self._job_row(channel_profile_id, acquisition_job_id)
            if current["cancel_requested"]:
                with closing(self._connection(channel_profile_id)) as connection:
                    connection.execute(
                        "UPDATE acquisition_jobs SET state='CANCELLED',stage='CANCELLED',updated_at=? WHERE acquisition_job_id=?",
                        (utc_now(), acquisition_job_id),
                    )
                    connection.commit()
                return self.get_job(channel_profile_id=channel_profile_id, acquisition_job_id=acquisition_job_id)
            item = json.loads(row["input_json"])
            with closing(self._connection(channel_profile_id)) as connection:
                connection.execute(
                    "UPDATE acquisition_job_items SET state='RUNNING',attempts=attempts+1,updated_at=? WHERE acquisition_job_id=? AND item_index=?",
                    (utc_now(), acquisition_job_id, row["item_index"]),
                )
                connection.commit()
            try:
                result = self._collect(item, work_root / f"item-{row['item_index']:04d}")
                registered = self.register(channel_profile_id=channel_profile_id, item=item, result=result)
                item_state = "COMPLETED" if registered["status"] not in {"BLOCKED", "FAILED"} else "NEEDS_SUPPLEMENT" if registered["status"] == "BLOCKED" else "FAILED"
                with closing(self._connection(channel_profile_id)) as connection:
                    connection.execute(
                        """
                        UPDATE acquisition_job_items
                        SET state=?,source_package_id=?,outcome=?,error_code=NULL,error_message=NULL,updated_at=?
                        WHERE acquisition_job_id=? AND item_index=?
                        """,
                        (
                            item_state,
                            registered["sourcePackageId"],
                            registered["outcome"],
                            utc_now(),
                            acquisition_job_id,
                            row["item_index"],
                        ),
                    )
                    connection.commit()
            except ToolError as exc:
                state = "NEEDS_SUPPLEMENT" if exc.code in {
                    "YOUTUBE_TEXT_UNAVAILABLE",
                    "SOURCE_ACCESS_BLOCKED",
                    "SOURCE_USER_FILE_REQUIRED",
                    "SOURCE_CONTENT_INCOMPLETE",
                } else "FAILED"
                with closing(self._connection(channel_profile_id)) as connection:
                    connection.execute(
                        """
                        UPDATE acquisition_job_items
                        SET state=?,error_code=?,error_message=?,updated_at=?
                        WHERE acquisition_job_id=? AND item_index=?
                        """,
                        (state, exc.code, exc.message, utc_now(), acquisition_job_id, row["item_index"]),
                    )
                    connection.commit()
            except Exception as exc:
                with closing(self._connection(channel_profile_id)) as connection:
                    connection.execute(
                        """
                        UPDATE acquisition_job_items SET state='FAILED',error_code='SOURCE_ADAPTER_FAILED',
                        error_message='资料适配器执行失败。',updated_at=?
                        WHERE acquisition_job_id=? AND item_index=?
                        """,
                        (utc_now(), acquisition_job_id, row["item_index"]),
                    )
                    connection.commit()
                del exc
            self._refresh_job_checkpoint(channel_profile_id, acquisition_job_id)
        self._refresh_job_checkpoint(channel_profile_id, acquisition_job_id, finalize=True)
        try:
            shutil.rmtree(work_root)
        except OSError:
            pass
        return self.get_job(channel_profile_id=channel_profile_id, acquisition_job_id=acquisition_job_id)

    def _apply_supplements(self, channel_profile_id: str, acquisition_job_id: str, supplements: list[Any]) -> None:
        with closing(self._connection(channel_profile_id)) as connection:
            connection.execute("BEGIN IMMEDIATE")
            for value in supplements:
                if not isinstance(value, dict) or not isinstance(value.get("itemIndex"), int):
                    raise ToolError("SOURCE_SUPPLEMENT_INVALID", "补充资料必须包含 itemIndex。")
                row = connection.execute(
                    "SELECT input_json FROM acquisition_job_items WHERE acquisition_job_id=? AND item_index=?",
                    (acquisition_job_id, value["itemIndex"]),
                ).fetchone()
                if row is None:
                    raise ToolError("SOURCE_SUPPLEMENT_INVALID", "补充资料指向不存在的任务项。")
                item = json.loads(row["input_json"])
                for key in ("suppliedFile", "text", "language", "authorized", "allowTranscription"):
                    if key in value:
                        item[key] = value[key]
                connection.execute(
                    """
                    UPDATE acquisition_job_items SET input_json=?,state='WAITING',error_code=NULL,error_message=NULL,updated_at=?
                    WHERE acquisition_job_id=? AND item_index=?
                    """,
                    (_json_dumps(item), utc_now(), acquisition_job_id, value["itemIndex"]),
                )
            connection.commit()

    def _refresh_job_checkpoint(self, channel_profile_id: str, acquisition_job_id: str, *, finalize: bool = False) -> None:
        with closing(self._connection(channel_profile_id)) as connection:
            rows = connection.execute(
                "SELECT state,outcome FROM acquisition_job_items WHERE acquisition_job_id=?",
                (acquisition_job_id,),
            ).fetchall()
            counts: dict[str, int] = {}
            outcomes: dict[str, int] = {}
            for row in rows:
                counts[row["state"]] = counts.get(row["state"], 0) + 1
                if row["outcome"]:
                    outcomes[row["outcome"]] = outcomes.get(row["outcome"], 0) + 1
            checkpoint = {
                "total": len(rows),
                "completed": counts.get("COMPLETED", 0),
                "needsSupplement": counts.get("NEEDS_SUPPLEMENT", 0),
                "failed": counts.get("FAILED", 0),
                "outcomes": outcomes,
            }
            state, stage = "RUNNING", "STANDARDIZING"
            if finalize:
                if checkpoint["needsSupplement"]:
                    state, stage = "NEEDS_SUPPLEMENT", "WAITING_USER_INPUT"
                elif checkpoint["failed"] and checkpoint["completed"]:
                    state, stage = "PARTIAL", "COMPLETED"
                elif checkpoint["failed"]:
                    state, stage = "FAILED", "FAILED"
                else:
                    state, stage = "COMPLETED", "COMPLETED"
            connection.execute(
                "UPDATE acquisition_jobs SET state=?,stage=?,checkpoint_json=?,updated_at=? WHERE acquisition_job_id=?",
                (state, stage, _json_dumps(checkpoint), utc_now(), acquisition_job_id),
            )
            connection.commit()

    def cancel_job(
        self,
        *,
        task_id: Any,
        channel_profile_id: Any,
        binding_proof: Any,
        acquisition_job_id: Any,
    ) -> dict[str, Any]:
        self.store.assert_binding(
            task_id=task_id,
            channel_profile_id=channel_profile_id,
            binding_proof=binding_proof,
        )
        job = self._job_row(channel_profile_id, acquisition_job_id)
        if job["task_id"] != task_id:
            raise ToolError("SOURCE_JOB_BINDING_MISMATCH", "资料任务不属于当前 Codex 任务。")
        if job["state"] in TERMINAL_JOB_STATES:
            return self.get_job(channel_profile_id=channel_profile_id, acquisition_job_id=acquisition_job_id)
        with closing(self._connection(channel_profile_id)) as connection:
            connection.execute(
                "UPDATE acquisition_jobs SET cancel_requested=1,state='CANCELLED',stage='CANCELLED',updated_at=? WHERE acquisition_job_id=?",
                (utc_now(), acquisition_job_id),
            )
            connection.commit()
        return self.get_job(channel_profile_id=channel_profile_id, acquisition_job_id=acquisition_job_id)

    def get_job(self, *, channel_profile_id: Any, acquisition_job_id: Any) -> dict[str, Any]:
        job = self._job_row(channel_profile_id, acquisition_job_id)
        with closing(self._connection(channel_profile_id)) as connection:
            items = connection.execute(
                "SELECT item_index,state,source_package_id,outcome,error_code,error_message,attempts FROM acquisition_job_items WHERE acquisition_job_id=? ORDER BY item_index",
                (acquisition_job_id,),
            ).fetchall()
        checkpoint = json.loads(job["checkpoint_json"])
        result = {
            "acquisitionJobId": acquisition_job_id,
            "channelProfileId": channel_profile_id,
            "state": job["state"],
            "stage": job["stage"],
            "progress": checkpoint,
            "recoverable": bool(job["recoverable"]),
            "items": [dict(row) for row in items],
            "updatedAt": job["updated_at"],
        }
        if job["state"] in TERMINAL_JOB_STATES:
            result["completionCard"] = {
                "success": checkpoint.get("outcomes", {}).get("ADDED", 0),
                "updated": checkpoint.get("outcomes", {}).get("UPDATED", 0),
                "reused": checkpoint.get("outcomes", {}).get("REUSED", 0),
                "partial": checkpoint.get("needsSupplement", 0),
                "failed": checkpoint.get("failed", 0),
                "nextActions": ["继续添加资料", "查看资料库"],
                "contentAnalysisStarted": False,
            }
        return result

    def register(self, *, channel_profile_id: str, item: dict[str, Any], result: Any) -> dict[str, Any]:
        if not isinstance(result, dict):
            if hasattr(result, "to_dict"):
                result = result.to_dict()
            elif hasattr(result, "__dict__"):
                result = dict(result.__dict__)
            else:
                raise ToolError("SOURCE_ADAPTER_RESULT_INVALID", "资料适配器返回了无效结果。")
        status = str(result.get("status", "FAILED")).upper()
        if status not in SOURCE_STATUSES:
            raise ToolError("SOURCE_ADAPTER_RESULT_INVALID", "资料适配器返回了未知状态。")
        source_type = result.get("sourceType") or item.get("kind")
        if source_type not in SOURCE_DIRECTORY:
            if item.get("kind") == "public-url":
                source_type = "novel-web"
            else:
                raise ToolError("SOURCE_ADAPTER_RESULT_INVALID", "资料适配器返回了未知资料类型。")
        collected_at = result.get("provenance", {}).get("collectedAt") or utc_now()
        canonical_locator = result.get("canonicalLocator") or item.get("canonicalLocator") or item["locator"]
        canonical_url = result.get("canonicalUrl")
        if canonical_url:
            canonical_url = canonicalize_url(canonical_url)
        elif re.match(r"^https?://", canonical_locator, re.IGNORECASE):
            canonical_url = canonicalize_url(canonical_locator)
        platform = result.get("platform")
        platform_id = result.get("platformId")
        content_sha256 = result.get("contentSha256") or item.get("fileSha256")
        if content_sha256 is not None and not re.fullmatch(r"[0-9a-f]{64}", str(content_sha256)):
            raise ToolError("SOURCE_ADAPTER_RESULT_INVALID", "资料内容哈希无效。")

        assets_input = list(result.get("assets") or [])
        metadata = dict(result.get("metadata") or {})
        metadata.setdefault("sourceBoundary", result.get("report", {}).get("sourceBoundary", "unknown"))
        metadata.setdefault("completeness", result.get("report", {}).get("completeness", result.get("report", {}).get("complete")))
        prepared_assets = self._prepare_asset_payloads(assets_input)
        normalized_summary = {
            "sourceType": source_type,
            "status": status,
            "title": result.get("title"),
            "language": result.get("language") or "und",
            "platform": platform,
            "platformId": platform_id,
            "canonicalUrl": canonical_url,
            "contentSha256": content_sha256,
            "metadata": metadata,
            "assetHashes": sorted((asset["role"], asset["sha256"]) for asset in prepared_assets),
        }
        version_fingerprint = _json_hash(normalized_summary)
        metadata["_versionFingerprint"] = version_fingerprint

        with closing(self._connection(channel_profile_id)) as connection:
            matches: list[tuple[str, sqlite3.Row]] = []
            if platform and platform_id:
                row = connection.execute(
                    "SELECT * FROM source_packages WHERE platform=? AND platform_id=?", (platform, platform_id)
                ).fetchone()
                if row:
                    matches.append(("platform-id", row))
            if canonical_url:
                row = connection.execute(
                    "SELECT * FROM source_packages WHERE canonical_url=?", (canonical_url,)
                ).fetchone()
                if row and all(existing[1]["source_package_id"] != row["source_package_id"] for existing in matches):
                    matches.append(("canonical-url", row))
            if content_sha256:
                row = connection.execute(
                    "SELECT * FROM source_packages WHERE content_sha256=? ORDER BY created_at LIMIT 1", (content_sha256,)
                ).fetchone()
                if row and all(existing[1]["source_package_id"] != row["source_package_id"] for existing in matches):
                    matches.append(("content-sha256", row))
        if len({row["source_package_id"] for _, row in matches}) > 1:
            raise ToolError("SOURCE_IDENTITY_CONFLICT", "平台 ID、规范 URL 与内容哈希指向不同资料包，需要人工修复。")
        existing = matches[0][1] if matches else None
        match_reason = matches[0][0] if matches else None
        if existing is not None:
            previous_metadata = json.loads(existing["metadata_json"])
            same_local_content = (
                source_type == "local-file"
                and content_sha256 is not None
                and existing["content_sha256"] == content_sha256
            )
            if (
                match_reason == "content-sha256"
                or same_local_content
                or previous_metadata.get("_versionFingerprint") == version_fingerprint
            ):
                self._record_alias(
                    channel_profile_id,
                    existing["source_package_id"],
                    item,
                    canonical_locator,
                    content_sha256,
                )
                return {
                    "sourcePackageId": existing["source_package_id"],
                    "version": existing["current_version"],
                    "status": existing["status"],
                    "outcome": "REUSED",
                    "deduplicatedBy": match_reason,
                }
            source_package_id = existing["source_package_id"]
            version = _next_version(existing["current_version"])
            outcome = "UPDATED"
        else:
            identity = f"{platform or ''}:{platform_id or ''}:{canonical_url or ''}:{content_sha256 or canonical_locator}"
            source_package_id = f"source_{hashlib.sha256(identity.encode('utf-8')).hexdigest()[:24]}"
            version = "1.0.0"
            outcome = "ADDED"

        package_root = self.store.channel_path(channel_profile_id) / "sources" / SOURCE_DIRECTORY[source_type] / source_package_id
        version_number = sum(int(part) * multiplier for part, multiplier in zip(version.split(".")[:3], (1_000_000, 1_000, 1)))
        stored_assets = self._store_assets(
            channel_profile_id=channel_profile_id,
            source_package_id=source_package_id,
            package_root=package_root,
            version=version,
            version_number=version_number,
            prepared_assets=prepared_assets,
            metadata=metadata,
            report=dict(result.get("report") or {}),
        )
        provenance = dict(result.get("provenance") or {})
        provenance = {
            "kind": provenance.get("kind") or ("public-url" if canonical_url else "local-file" if source_type == "local-file" else "user-input"),
            "locator": provenance.get("locator") or item["locator"],
            "collectedAt": collected_at,
            "adapterId": provenance.get("adapterId") or "unknown-adapter",
            "adapterVersion": provenance.get("adapterVersion") or "1.0.0",
        }
        rights = dict(result.get("rightsBoundary") or {})
        rights = {
            "accessLevel": rights.get("accessLevel") or "unknown",
            "basis": rights.get("basis") or "适配器没有提供更具体的权利依据。",
            "confirmedByUser": bool(rights.get("confirmedByUser", False)),
        }
        channel_summary = self.store.get_channel(channel_profile_id)
        channel = channel_summary.get("channelProfile")
        if not isinstance(channel, dict):
            raise ToolError("CHANNEL_LIBRARY_NOT_READY", "频道正式档案缺失，禁止写入资料包。")
        manifest = with_hash(
            {
                "schemaVersion": SOURCE_PACKAGE_SCHEMA_VERSION,
                "contractType": "source-package",
                "id": source_package_id,
                "version": version,
                "createdAt": collected_at,
                "hashAlgorithm": "SHA-256",
                "hashRule": "canonical-json-v1",
                "upstream": [
                    {
                        "targetContractType": "channel-profile",
                        "targetId": channel["id"],
                        "targetVersion": channel["version"],
                        "targetSchemaVersion": channel["schemaVersion"],
                        "targetHash": channel["contentHash"],
                    }
                ],
                "sourcePackageId": source_package_id,
                "channelProfileId": channel_profile_id,
                "sourceType": source_type,
                "status": status,
                "provenance": provenance,
                "rightsBoundary": rights,
                "assets": [
                    {
                        "assetId": asset["assetId"],
                        "relativePath": asset["relativePath"],
                        "mediaType": asset["mediaType"],
                        "sizeBytes": asset["sizeBytes"],
                        "sha256": asset["sha256"],
                    }
                    for asset in stored_assets
                ],
            }
        )
        _atomic_json(package_root / "versions" / f"v{version}" / "manifest.json", manifest)
        _atomic_json(package_root / "manifest.json", manifest)
        manifest_relative = (package_root / "manifest.json").relative_to(self.store.channel_path(channel_profile_id)).as_posix()
        now = utc_now()
        with closing(self._connection(channel_profile_id)) as connection:
            connection.execute("BEGIN IMMEDIATE")
            if existing is None:
                connection.execute(
                    """
                    INSERT INTO source_packages(
                        source_package_id,source_type,platform,platform_id,canonical_url,canonical_locator,
                        current_version,status,language,title,content_sha256,manifest_relative_path,adapter_id,
                        adapter_version,rights_access_level,metadata_json,created_at,updated_at
                    ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        source_package_id,
                        source_type,
                        platform,
                        platform_id,
                        canonical_url,
                        canonical_locator,
                        version,
                        status,
                        result.get("language") or "und",
                        result.get("title") or Path(item["locator"]).name,
                        content_sha256,
                        manifest_relative,
                        provenance["adapterId"],
                        provenance["adapterVersion"],
                        rights["accessLevel"],
                        _json_dumps(metadata),
                        now,
                        now,
                    ),
                )
            else:
                connection.execute("UPDATE source_versions SET is_current=0 WHERE source_package_id=?", (source_package_id,))
                connection.execute(
                    """
                    UPDATE source_packages SET source_type=?,platform=?,platform_id=?,canonical_url=?,canonical_locator=?,
                    current_version=?,status=?,language=?,title=?,content_sha256=?,manifest_relative_path=?,adapter_id=?,
                    adapter_version=?,rights_access_level=?,metadata_json=?,updated_at=? WHERE source_package_id=?
                    """,
                    (
                        source_type,
                        platform,
                        platform_id,
                        canonical_url,
                        canonical_locator,
                        version,
                        status,
                        result.get("language") or "und",
                        result.get("title") or existing["title"],
                        content_sha256,
                        manifest_relative,
                        provenance["adapterId"],
                        provenance["adapterVersion"],
                        rights["accessLevel"],
                        _json_dumps(metadata),
                        now,
                        source_package_id,
                    ),
                )
            connection.execute(
                "INSERT INTO source_versions VALUES(?,?,?,?,?,?,?,1)",
                (
                    source_package_id,
                    version,
                    status,
                    _json_dumps(manifest),
                    _json_dumps(metadata),
                    manifest["contentHash"],
                    collected_at,
                ),
            )
            connection.executemany(
                "INSERT INTO source_assets VALUES(?,?,?,?,?,?,?,?)",
                [
                    (
                        source_package_id,
                        version,
                        asset["assetId"],
                        asset["relativePath"],
                        asset["mediaType"],
                        asset["sizeBytes"],
                        asset["sha256"],
                        asset["role"],
                    )
                    for asset in stored_assets
                ],
            )
            connection.commit()
        self._record_alias(channel_profile_id, source_package_id, item, canonical_locator, content_sha256)
        return {
            "sourcePackageId": source_package_id,
            "version": version,
            "status": status,
            "outcome": outcome,
            "manifestPath": str(package_root / "manifest.json"),
        }

    def _prepare_asset_payloads(self, assets: list[Any]) -> list[dict[str, Any]]:
        prepared: list[dict[str, Any]] = []
        for index, value in enumerate(assets):
            if not isinstance(value, dict):
                raise ToolError("SOURCE_ADAPTER_RESULT_INVALID", "资料资产描述必须是对象。")
            declared_role = str(value.get("role", "assets")).strip().lower()
            role_aliases = {
                "original": "raw",
                "raw-source": "raw",
                "source": "raw",
                "subtitle-original": "raw",
                "transcript-raw": "raw",
                "normalized-text": "normalized",
                "transcript-normalized": "normalized",
                "channel-list": "normalized",
                "cover": "assets",
                "thumbnail": "assets",
                "report": "reports",
                "acquisition-report": "reports",
            }
            role = role_aliases.get(declared_role, declared_role)
            if role not in {"raw", "normalized", "assets", "reports"}:
                role = "assets"
            source_path = value.get("sourcePath") or value.get("path")
            data = value.get("data")
            if source_path is not None:
                path = Path(source_path).resolve()
                if not path.is_file():
                    raise ToolError("SOURCE_ASSET_MISSING", "资料适配器声明的资产文件不存在。")
                payload: bytes | Path = path
                size = path.stat().st_size
                sha256 = _sha256_file(path)
                default_name = path.name
            elif isinstance(data, str):
                encoded = data.encode("utf-8")
                payload = encoded
                size = len(encoded)
                sha256 = _sha256_bytes(encoded)
                default_name = f"asset-{index:03d}.txt"
            elif isinstance(data, (bytes, bytearray)):
                encoded = bytes(data)
                payload = encoded
                size = len(encoded)
                sha256 = _sha256_bytes(encoded)
                default_name = f"asset-{index:03d}.bin"
            else:
                raise ToolError("SOURCE_ADAPTER_RESULT_INVALID", "资料资产缺少 sourcePath 或 data。")
            filename = _safe_filename(str(value.get("filename") or default_name), default_name)
            media_type = value.get("mediaType") or mimetypes.guess_type(filename)[0] or "application/octet-stream"
            prepared.append(
                {
                    "role": role,
                    "filename": filename,
                    "mediaType": media_type,
                    "payload": payload,
                    "sizeBytes": size,
                    "sha256": sha256,
                }
            )
        return prepared

    def _store_assets(
        self,
        *,
        channel_profile_id: str,
        source_package_id: str,
        package_root: Path,
        version: str,
        version_number: int,
        prepared_assets: list[dict[str, Any]],
        metadata: dict[str, Any],
        report: dict[str, Any],
    ) -> list[dict[str, Any]]:
        automatic = [
            {
                "role": "normalized",
                "filename": "metadata.json",
                "mediaType": "application/json",
                "payload": (json.dumps(metadata, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8"),
            },
            {
                "role": "reports",
                "filename": "acquisition-report.json",
                "mediaType": "application/json",
                "payload": (json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8"),
            },
        ]
        for value in automatic:
            value["sizeBytes"] = len(value["payload"])
            value["sha256"] = _sha256_bytes(value["payload"])
            prepared_assets.append(value)
        existing_by_hash: dict[tuple[str, str], sqlite3.Row] = {}
        if (package_root / "manifest.json").is_file():
            with closing(self._connection(channel_profile_id)) as connection:
                rows = connection.execute(
                    "SELECT * FROM source_assets WHERE source_package_id=? ORDER BY version DESC",
                    (source_package_id,),
                ).fetchall()
                for row in rows:
                    existing_by_hash.setdefault((row["role"], row["sha256"]), row)
        used_paths: set[str] = set()
        stored: list[dict[str, Any]] = []
        for index, value in enumerate(prepared_assets):
            existing = existing_by_hash.get((value["role"], value["sha256"]))
            if existing and (package_root / existing["relative_path"]).is_file():
                relative = existing["relative_path"]
            else:
                filename = value["filename"]
                relative = f"{value['role']}/v{version_number:09d}/{filename}"
                suffix = 1
                while relative in used_paths or (package_root / relative).exists():
                    stem, extension = os.path.splitext(filename)
                    relative = f"{value['role']}/v{version_number:09d}/{stem}-{suffix}{extension}"
                    suffix += 1
                target = package_root / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                payload = value["payload"]
                if isinstance(payload, Path):
                    shutil.copy2(payload, target)
                else:
                    target.write_bytes(payload)
                if _sha256_file(target) != value["sha256"]:
                    raise ToolError("SOURCE_ASSET_HASH_MISMATCH", "资料资产写入后哈希不一致。")
            used_paths.add(relative)
            stored.append(
                {
                    "assetId": f"asset_{hashlib.sha256(f'{source_package_id}:{version}:{index}:{value['sha256']}'.encode()).hexdigest()[:24]}",
                    "relativePath": relative,
                    "mediaType": value["mediaType"],
                    "sizeBytes": value["sizeBytes"],
                    "sha256": value["sha256"],
                    "role": value["role"],
                }
            )
        return stored

    def _record_alias(
        self,
        channel_profile_id: str,
        source_package_id: str,
        item: dict[str, Any],
        canonical_locator: str,
        content_sha256: str | None,
    ) -> None:
        locator_kind = "url" if re.match(r"^https?://", canonical_locator, re.IGNORECASE) else "file" if item.get("kind") == "local-file" else "user-input"
        alias_id = f"alias_{hashlib.sha256(f'{locator_kind}:{canonical_locator}'.encode('utf-8')).hexdigest()[:24]}"
        with closing(self._connection(channel_profile_id)) as connection:
            connection.execute(
                """
                INSERT OR IGNORE INTO source_aliases VALUES(?,?,?,?,?,?,?)
                """,
                (alias_id, source_package_id, locator_kind, item["locator"], canonical_locator, content_sha256, utc_now()),
            )
            connection.commit()

    def search(
        self,
        *,
        channel_profile_id: Any,
        query: Any = None,
        source_type: Any = None,
        status: Any = None,
        language: Any = None,
        limit: Any = 50,
    ) -> dict[str, Any]:
        if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 200:
            raise ToolError("INVALID_ARGUMENT", "limit 必须是 1 到 200 的整数。")
        clauses: list[str] = []
        params: list[Any] = []
        if isinstance(query, str) and query.strip():
            clauses.append("(title LIKE ? OR canonical_locator LIKE ? OR metadata_json LIKE ?)")
            needle = f"%{query.strip()}%"
            params.extend([needle, needle, needle])
        for column, value in (("source_type", source_type), ("status", status), ("language", language)):
            if isinstance(value, str) and value:
                clauses.append(f"{column}=?")
                params.append(value)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        with closing(self._connection(channel_profile_id)) as connection:
            rows = connection.execute(
                f"""
                SELECT source_package_id,source_type,current_version,status,language,title,platform,platform_id,
                       canonical_url,content_sha256,rights_access_level,updated_at
                FROM source_packages {where} ORDER BY updated_at DESC LIMIT ?
                """,
                (*params, limit),
            ).fetchall()
        return {"sources": [dict(row) for row in rows], "count": len(rows), "contentAnalysisIncluded": False}

    def get_source(self, *, channel_profile_id: Any, source_package_id: Any) -> dict[str, Any]:
        if not isinstance(source_package_id, str) or not source_package_id:
            raise ToolError("INVALID_ARGUMENT", "sourcePackageId 是必填项。")
        with closing(self._connection(channel_profile_id)) as connection:
            row = connection.execute(
                "SELECT * FROM source_packages WHERE source_package_id=?", (source_package_id,)
            ).fetchone()
            if row is None:
                raise ToolError("SOURCE_NOT_FOUND", "没有找到指定资料包。")
            versions = connection.execute(
                "SELECT version,status,content_hash,collected_at,is_current FROM source_versions WHERE source_package_id=? ORDER BY collected_at",
                (source_package_id,),
            ).fetchall()
            aliases = connection.execute(
                "SELECT locator_kind,original_locator,canonical_locator,original_sha256,first_seen_at FROM source_aliases WHERE source_package_id=? ORDER BY first_seen_at",
                (source_package_id,),
            ).fetchall()
        manifest = json.loads(
            (self.store.channel_path(channel_profile_id) / row["manifest_relative_path"]).read_text(encoding="utf-8")
        )
        return {
            "source": {key: value for key, value in dict(row).items() if key != "metadata_json"},
            "metadata": json.loads(row["metadata_json"]),
            "manifest": manifest,
            "versions": [dict(value) for value in versions],
            "aliases": [dict(value) for value in aliases],
            "contentAnalysisIncluded": False,
        }

    def update_source(
        self,
        *,
        task_id: Any,
        channel_profile_id: Any,
        binding_proof: Any,
        source_package_id: Any,
        options: Any = None,
    ) -> dict[str, Any]:
        source = self.get_source(channel_profile_id=channel_profile_id, source_package_id=source_package_id)
        provenance = source["manifest"]["provenance"]
        item: dict[str, Any] = {"locator": provenance["locator"]}
        if isinstance(options, dict):
            item.update(options)
        card = self.prepare_add(
            task_id=task_id,
            channel_profile_id=channel_profile_id,
            binding_proof=binding_proof,
            inputs=[item],
            options={"updateSourcePackageId": source_package_id},
        )
        card["cardType"] = "source-update-confirmation"
        return card

    def integrity_check(self, *, channel_profile_id: Any) -> dict[str, Any]:
        errors: list[dict[str, Any]] = []
        checked = 0
        with closing(self._connection(channel_profile_id)) as connection:
            packages = connection.execute("SELECT * FROM source_packages ORDER BY source_package_id").fetchall()
            assets = connection.execute(
                "SELECT source_package_id,version,relative_path,sha256 FROM source_assets ORDER BY source_package_id,version"
            ).fetchall()
        root = self.store.channel_path(channel_profile_id)
        for row in packages:
            checked += 1
            path = root / row["manifest_relative_path"]
            if not path.is_file():
                errors.append({"sourcePackageId": row["source_package_id"], "issue": "manifest-missing"})
                continue
            try:
                manifest = json.loads(path.read_text(encoding="utf-8"))
                if canonical_hash(manifest) != manifest.get("contentHash"):
                    errors.append({"sourcePackageId": row["source_package_id"], "issue": "manifest-hash"})
            except (OSError, json.JSONDecodeError):
                errors.append({"sourcePackageId": row["source_package_id"], "issue": "manifest-invalid"})
        for asset in assets:
            path = root / "sources" / SOURCE_DIRECTORY[
                next(row["source_type"] for row in packages if row["source_package_id"] == asset["source_package_id"])
            ] / asset["source_package_id"] / asset["relative_path"]
            if not path.is_file() or _sha256_file(path) != asset["sha256"]:
                errors.append(
                    {
                        "sourcePackageId": asset["source_package_id"],
                        "version": asset["version"],
                        "issue": "asset-missing-or-hash",
                    }
                )
        return {"status": "PASS" if not errors else "NEEDS_REPAIR", "checkedPackages": checked, "errors": errors}
