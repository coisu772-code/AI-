from __future__ import annotations

import hashlib
import json
import os
import secrets
import shutil
import sqlite3
import tempfile
import uuid
import zipfile
from contextlib import closing, contextmanager
from pathlib import Path, PurePosixPath
from typing import Any, Iterator

from .contracts import canonical_hash, channel_contract, production_contract, utc_now, validate_defaults
from .errors import ToolError


SYSTEM_SCHEMA_VERSION = 1
CHANNEL_SCHEMA_VERSION = 2
ARCHIVE_FORMAT_VERSION = "1.0.0"
MAX_ARCHIVE_FILES = 200_000
MAX_ARCHIVE_UNCOMPRESSED_BYTES = 512 * 1024 * 1024 * 1024
MAX_ARCHIVE_MANIFEST_BYTES = 10 * 1024 * 1024
USER_DATA_DIRECTORIES = (
    "channels",
    "content-workspaces",
    "backups",
    "exports",
    "imports",
    "production",
    "analytics",
    "workshop-isolation",
)
CHANNEL_DIRECTORIES = (
    "presets",
    "sources/reference-channels",
    "sources/youtube-videos",
    "sources/novels",
    "sources/user-files",
    "analyses/channel-distillations",
    "analyses/video-deconstructions",
    "analyses/novel-deconstructions",
    "prompts",
    "topics",
    "projects",
    "publishing",
    "analytics",
    "learning",
)

SOURCE_LIBRARY_SQL = """
CREATE TABLE IF NOT EXISTS source_packages (
    source_package_id TEXT PRIMARY KEY,
    source_type TEXT NOT NULL,
    platform TEXT,
    platform_id TEXT,
    canonical_url TEXT,
    canonical_locator TEXT NOT NULL,
    current_version TEXT NOT NULL,
    status TEXT NOT NULL,
    language TEXT,
    title TEXT,
    content_sha256 TEXT,
    manifest_relative_path TEXT NOT NULL,
    adapter_id TEXT NOT NULL,
    adapter_version TEXT NOT NULL,
    rights_access_level TEXT NOT NULL,
    metadata_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_source_platform_identity
    ON source_packages(platform, platform_id)
    WHERE platform IS NOT NULL AND platform_id IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS idx_source_canonical_url
    ON source_packages(canonical_url)
    WHERE canonical_url IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_source_content_sha256 ON source_packages(content_sha256);
CREATE INDEX IF NOT EXISTS idx_source_filter
    ON source_packages(source_type, status, language, updated_at);
CREATE TABLE IF NOT EXISTS source_versions (
    source_package_id TEXT NOT NULL,
    version TEXT NOT NULL,
    status TEXT NOT NULL,
    manifest_json TEXT NOT NULL,
    metadata_json TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    collected_at TEXT NOT NULL,
    is_current INTEGER NOT NULL CHECK(is_current IN (0,1)),
    PRIMARY KEY(source_package_id, version),
    FOREIGN KEY(source_package_id) REFERENCES source_packages(source_package_id)
);
CREATE TABLE IF NOT EXISTS source_assets (
    source_package_id TEXT NOT NULL,
    version TEXT NOT NULL,
    asset_id TEXT NOT NULL,
    relative_path TEXT NOT NULL,
    media_type TEXT NOT NULL,
    size_bytes INTEGER NOT NULL,
    sha256 TEXT NOT NULL,
    role TEXT NOT NULL,
    PRIMARY KEY(source_package_id, version, asset_id),
    FOREIGN KEY(source_package_id, version)
        REFERENCES source_versions(source_package_id, version)
);
CREATE TABLE IF NOT EXISTS source_aliases (
    alias_id TEXT PRIMARY KEY,
    source_package_id TEXT NOT NULL,
    locator_kind TEXT NOT NULL,
    original_locator TEXT NOT NULL,
    canonical_locator TEXT NOT NULL,
    original_sha256 TEXT,
    first_seen_at TEXT NOT NULL,
    UNIQUE(locator_kind, canonical_locator),
    FOREIGN KEY(source_package_id) REFERENCES source_packages(source_package_id)
);
CREATE INDEX IF NOT EXISTS idx_source_alias_package ON source_aliases(source_package_id);
CREATE TABLE IF NOT EXISTS acquisition_jobs (
    acquisition_job_id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL,
    channel_profile_id TEXT NOT NULL,
    plan_hash TEXT NOT NULL,
    state TEXT NOT NULL,
    stage TEXT NOT NULL,
    request_json TEXT NOT NULL,
    confirmation_json TEXT,
    checkpoint_json TEXT NOT NULL,
    cancel_requested INTEGER NOT NULL DEFAULT 0 CHECK(cancel_requested IN (0,1)),
    recoverable INTEGER NOT NULL DEFAULT 1 CHECK(recoverable IN (0,1)),
    error_code TEXT,
    error_message TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_acquisition_job_state
    ON acquisition_jobs(state, updated_at);
CREATE TABLE IF NOT EXISTS acquisition_job_items (
    acquisition_job_id TEXT NOT NULL,
    item_index INTEGER NOT NULL,
    input_json TEXT NOT NULL,
    state TEXT NOT NULL,
    source_package_id TEXT,
    outcome TEXT,
    error_code TEXT,
    error_message TEXT,
    attempts INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL,
    PRIMARY KEY(acquisition_job_id, item_index),
    FOREIGN KEY(acquisition_job_id) REFERENCES acquisition_jobs(acquisition_job_id)
);
"""


def _json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_identifier(value: Any, field: str, *, maximum: int = 160) -> str:
    if not isinstance(value, str) or not value or len(value) > maximum:
        raise ToolError("INVALID_ARGUMENT", f"{field} 无效。", details={"field": field})
    if any(char in value for char in ("/", "\\", "\0")) or value in {".", ".."}:
        raise ToolError("INVALID_ARGUMENT", f"{field} 包含不安全字符。", details={"field": field})
    return value


def _deep_merge(base: dict[str, Any], override: dict[str, Any], prefix: str = "") -> tuple[dict[str, Any], list[str]]:
    result = json.loads(json.dumps(base, ensure_ascii=False))
    changed: list[str] = []
    for key, value in override.items():
        path = f"{prefix}.{key}" if prefix else key
        if key not in result:
            if prefix == "videoGeneration" and key == "count":
                result[key] = value
                changed.append(path)
                continue
            raise ToolError("INVALID_OVERRIDE", "本次覆盖包含未知字段。", details={"path": path})
        if isinstance(result[key], dict) and isinstance(value, dict):
            merged, nested = _deep_merge(result[key], value, path)
            result[key] = merged
            changed.extend(nested)
        else:
            result[key] = value
            changed.append(path)
    return result, changed


class ChannelStore:
    def __init__(self, data_root: Path):
        self.data_root = data_root.resolve()
        self.channels_root = self.data_root / "channels"
        self.backups_root = self.data_root / "backups"
        self.exports_root = self.data_root / "exports"
        self.imports_root = self.data_root / "imports"
        self.system_db = self.data_root / "system.db"
        self._initialize_system()

    @contextmanager
    def _system_connection(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.system_db, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        try:
            yield connection
        finally:
            connection.close()

    @contextmanager
    def _channel_connection(self, channel_profile_id: str) -> Iterator[sqlite3.Connection]:
        path = self.channel_path(channel_profile_id) / "channel.db"
        if not path.is_file():
            raise ToolError("CHANNEL_LIBRARY_NOT_READY", "频道资料库尚未创建或不可用。")
        self._ensure_channel_schema(path, channel_profile_id)
        connection = sqlite3.connect(path, timeout=10)
        connection.row_factory = sqlite3.Row
        try:
            yield connection
        finally:
            connection.close()

    def _ensure_channel_schema(self, path: Path, channel_profile_id: str) -> None:
        with closing(sqlite3.connect(path)) as probe:
            current = int(probe.execute("PRAGMA user_version").fetchone()[0])
        if current == CHANNEL_SCHEMA_VERSION:
            return
        if current > CHANNEL_SCHEMA_VERSION:
            raise ToolError(
                "MIGRATION_REQUIRED",
                "channel.db 来自更高版本，当前工具服务禁止写入。",
                details={"databaseVersion": current, "supportedVersion": CHANNEL_SCHEMA_VERSION},
            )
        backup = self._copy_upgrade_backup(path, f"channel-{channel_profile_id}", current)
        try:
            with closing(sqlite3.connect(path)) as connection:
                connection.execute("BEGIN IMMEDIATE")
                connection.executescript(
                    """
                    CREATE TABLE IF NOT EXISTS library_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                    CREATE TABLE IF NOT EXISTS channel_profile_versions (
                        version TEXT PRIMARY KEY, contract_json TEXT NOT NULL, content_hash TEXT NOT NULL,
                        active INTEGER NOT NULL CHECK(active IN (0,1)), created_at TEXT NOT NULL
                    );
                    CREATE TABLE IF NOT EXISTS production_profile_versions (
                        preset_id TEXT NOT NULL, preset_version TEXT NOT NULL, contract_json TEXT NOT NULL,
                        content_hash TEXT NOT NULL, active INTEGER NOT NULL CHECK(active IN (0,1)),
                        created_at TEXT NOT NULL, PRIMARY KEY(preset_id, preset_version)
                    );
                    CREATE TABLE IF NOT EXISTS task_override_events (
                        event_id TEXT PRIMARY KEY, task_id TEXT NOT NULL, preset_id TEXT NOT NULL,
                        preset_version TEXT NOT NULL, override_json TEXT NOT NULL,
                        changed_paths_json TEXT NOT NULL, created_at TEXT NOT NULL
                    );
                    CREATE TABLE IF NOT EXISTS migration_history (
                        migration_id TEXT PRIMARY KEY, from_version INTEGER NOT NULL, to_version INTEGER NOT NULL,
                        applied_at TEXT NOT NULL, backup_path TEXT
                    );
                    """
                    + SOURCE_LIBRARY_SQL
                )
                if os.environ.get("AIVCP_TEST_FAIL_MIGRATION") == "channel":
                    raise RuntimeError("injected channel migration failure")
                connection.execute(
                    "INSERT OR REPLACE INTO library_meta(key,value) VALUES('schemaVersion',?)",
                    (str(CHANNEL_SCHEMA_VERSION),),
                )
                connection.execute(
                    "INSERT OR REPLACE INTO migration_history VALUES(?,?,?,?,?)",
                    (
                        f"channel-{current}-{CHANNEL_SCHEMA_VERSION}",
                        current,
                        CHANNEL_SCHEMA_VERSION,
                        utc_now(),
                        str(backup),
                    ),
                )
                connection.execute(f"PRAGMA user_version={CHANNEL_SCHEMA_VERSION}")
                connection.commit()
        except Exception as exc:
            shutil.copy2(backup, path)
            raise ToolError(
                "DATABASE_MIGRATION_FAILED",
                "频道资料库升级失败，已恢复升级前状态。",
                details={"database": channel_profile_id, "errorType": type(exc).__name__},
            ) from exc

    def _initialize_system(self) -> None:
        self.data_root.mkdir(parents=True, exist_ok=True)
        for relative in USER_DATA_DIRECTORIES:
            (self.data_root / relative).mkdir(exist_ok=True)
        is_new = not self.system_db.exists()
        backup_path: Path | None = None
        if not is_new:
            with closing(sqlite3.connect(self.system_db)) as connection:
                current = int(connection.execute("PRAGMA user_version").fetchone()[0])
            if current > SYSTEM_SCHEMA_VERSION:
                raise ToolError(
                    "MIGRATION_REQUIRED",
                    "system.db 来自更高版本，当前工具服务禁止写入。",
                    details={"databaseVersion": current, "supportedVersion": SYSTEM_SCHEMA_VERSION},
                )
            if current < SYSTEM_SCHEMA_VERSION:
                backup_path = self._copy_upgrade_backup(self.system_db, "system", current)
        try:
            with closing(sqlite3.connect(self.system_db)) as connection:
                connection.execute("PRAGMA journal_mode=DELETE")
                connection.execute("BEGIN IMMEDIATE")
                connection.executescript(
                    """
                    CREATE TABLE IF NOT EXISTS system_meta (
                        key TEXT PRIMARY KEY,
                        value TEXT NOT NULL
                    );
                    CREATE TABLE IF NOT EXISTS channels (
                        channel_profile_id TEXT PRIMARY KEY,
                        publisher_profile_id TEXT NOT NULL,
                        channel_serial TEXT NOT NULL,
                        youtube_channel_id TEXT NOT NULL UNIQUE,
                        display_name TEXT NOT NULL,
                        target_region TEXT NOT NULL,
                        output_language TEXT NOT NULL,
                        lifecycle_status TEXT NOT NULL,
                        current_preset_id TEXT,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL,
                        UNIQUE(publisher_profile_id),
                        UNIQUE(channel_serial)
                    );
                    CREATE TABLE IF NOT EXISTS task_bindings (
                        task_id TEXT PRIMARY KEY,
                        binding_id TEXT NOT NULL UNIQUE,
                        channel_profile_id TEXT NOT NULL,
                        proof_hash TEXT NOT NULL,
                        bound_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL,
                        FOREIGN KEY(channel_profile_id) REFERENCES channels(channel_profile_id)
                    );
                    CREATE TABLE IF NOT EXISTS migration_history (
                        migration_id TEXT PRIMARY KEY,
                        database_kind TEXT NOT NULL,
                        from_version INTEGER NOT NULL,
                        to_version INTEGER NOT NULL,
                        applied_at TEXT NOT NULL,
                        backup_path TEXT
                    );
                    CREATE TABLE IF NOT EXISTS audit_events (
                        event_id TEXT PRIMARY KEY,
                        event_type TEXT NOT NULL,
                        channel_profile_id TEXT,
                        task_id TEXT,
                        details_json TEXT NOT NULL,
                        created_at TEXT NOT NULL
                    );
                    """
                )
                if os.environ.get("AIVCP_TEST_FAIL_MIGRATION") == "system":
                    raise RuntimeError("injected system migration failure")
                previous = int(connection.execute("PRAGMA user_version").fetchone()[0])
                connection.execute(f"PRAGMA user_version={SYSTEM_SCHEMA_VERSION}")
                connection.execute(
                    "INSERT OR REPLACE INTO system_meta(key, value) VALUES('schemaVersion', ?)",
                    (str(SYSTEM_SCHEMA_VERSION),),
                )
                if previous < SYSTEM_SCHEMA_VERSION:
                    connection.execute(
                        "INSERT OR REPLACE INTO migration_history VALUES(?,?,?,?,?,?)",
                        (
                            f"system-{previous}-{SYSTEM_SCHEMA_VERSION}",
                            "system",
                            previous,
                            SYSTEM_SCHEMA_VERSION,
                            utc_now(),
                            str(backup_path) if backup_path else None,
                        ),
                    )
                connection.commit()
        except Exception as exc:
            if backup_path and backup_path.is_file():
                shutil.copy2(backup_path, self.system_db)
            elif is_new and self.system_db.exists():
                self.system_db.unlink()
            raise ToolError(
                "DATABASE_MIGRATION_FAILED",
                "系统注册库升级失败，已恢复升级前状态。",
                details={"database": "system", "errorType": type(exc).__name__},
            ) from exc

    def _copy_upgrade_backup(self, database: Path, kind: str, version: int) -> Path:
        folder = self.backups_root / "upgrade"
        folder.mkdir(parents=True, exist_ok=True)
        target = folder / f"{kind}-schema-{version}-{uuid.uuid4().hex}.db"
        shutil.copy2(database, target)
        return target

    def _initialize_channel_database(
        self,
        path: Path,
        channel: dict[str, Any],
        production: dict[str, Any],
    ) -> None:
        with closing(sqlite3.connect(path)) as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.executescript(
                """
                CREATE TABLE library_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE channel_profile_versions (
                    version TEXT PRIMARY KEY,
                    contract_json TEXT NOT NULL,
                    content_hash TEXT NOT NULL,
                    active INTEGER NOT NULL CHECK(active IN (0,1)),
                    created_at TEXT NOT NULL
                );
                CREATE TABLE production_profile_versions (
                    preset_id TEXT NOT NULL,
                    preset_version TEXT NOT NULL,
                    contract_json TEXT NOT NULL,
                    content_hash TEXT NOT NULL,
                    active INTEGER NOT NULL CHECK(active IN (0,1)),
                    created_at TEXT NOT NULL,
                    PRIMARY KEY(preset_id, preset_version)
                );
                CREATE TABLE task_override_events (
                    event_id TEXT PRIMARY KEY,
                    task_id TEXT NOT NULL,
                    preset_id TEXT NOT NULL,
                    preset_version TEXT NOT NULL,
                    override_json TEXT NOT NULL,
                    changed_paths_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE migration_history (
                    migration_id TEXT PRIMARY KEY,
                    from_version INTEGER NOT NULL,
                    to_version INTEGER NOT NULL,
                    applied_at TEXT NOT NULL,
                    backup_path TEXT
                );
                """
                + SOURCE_LIBRARY_SQL
            )
            connection.executemany(
                "INSERT INTO library_meta(key,value) VALUES(?,?)",
                (
                    ("schemaVersion", str(CHANNEL_SCHEMA_VERSION)),
                    ("channelProfileId", channel["channelProfileId"]),
                    ("createdAt", channel["createdAt"]),
                ),
            )
            connection.execute(
                "INSERT INTO channel_profile_versions VALUES(?,?,?,?,?)",
                (channel["version"], _json_dumps(channel), channel["contentHash"], 1, channel["createdAt"]),
            )
            connection.execute(
                "INSERT INTO production_profile_versions VALUES(?,?,?,?,?,?)",
                (
                    production["presetId"],
                    production["presetVersion"],
                    _json_dumps(production),
                    production["contentHash"],
                    1,
                    production["createdAt"],
                ),
            )
            connection.execute(f"PRAGMA user_version={CHANNEL_SCHEMA_VERSION}")
            connection.commit()

    def channel_path(self, channel_profile_id: str) -> Path:
        return self.channels_root / _safe_identifier(channel_profile_id, "channelProfileId")

    def create_pending_channel(
        self,
        *,
        publisher_channel: dict[str, Any],
        target_region: str,
        output_language: str,
    ) -> tuple[dict[str, Any], bool]:
        if not isinstance(target_region, str) or not isinstance(output_language, str):
            raise ToolError("INVALID_ARGUMENT", "目标地区和输出语言是必填项。")
        target_region = _safe_identifier(target_region.strip(), "targetRegion", maximum=80)
        output_language = _safe_identifier(output_language.strip(), "outputLanguage", maximum=16)
        if not __import__("re").fullmatch(r"[a-z]{2,3}(?:-[A-Z]{2})?", output_language):
            raise ToolError("INVALID_LANGUAGE", "输出语言必须使用 ja-JP、zh-CN、en-US 等语言标签。")
        youtube_channel_id = publisher_channel["youtubeChannelId"]
        now = utc_now()
        with self._system_connection() as connection:
            existing = connection.execute(
                "SELECT * FROM channels WHERE youtube_channel_id=?",
                (youtube_channel_id,),
            ).fetchone()
            if existing:
                if (
                    existing["publisher_profile_id"] != publisher_channel["publisherProfileId"]
                    or existing["channel_serial"] != publisher_channel["channelSerial"]
                ):
                    raise ToolError(
                        "PUBLISHER_BINDING_CHANGED",
                        "同一真实频道的发布中心身份映射发生变化，必须先检查连接，禁止自动改绑。",
                        details={"channelProfileId": existing["channel_profile_id"]},
                    )
                if existing["target_region"] != target_region or existing["output_language"] != output_language:
                    raise ToolError(
                        "CHANNEL_ALREADY_EXISTS",
                        "该真实频道已有资料库；地区或语言变更必须走高影响设置变更流程。",
                        details={"channelProfileId": existing["channel_profile_id"]},
                    )
                return self._row_to_channel(existing), True
            channel_profile_id = f"ch_{uuid.uuid4().hex}"
            connection.execute(
                """INSERT INTO channels(
                    channel_profile_id,publisher_profile_id,channel_serial,youtube_channel_id,
                    display_name,target_region,output_language,lifecycle_status,current_preset_id,created_at,updated_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    channel_profile_id,
                    publisher_channel["publisherProfileId"],
                    publisher_channel["channelSerial"],
                    youtube_channel_id,
                    publisher_channel["displayName"],
                    target_region,
                    output_language,
                    "LIBRARY_DEFAULTS_PENDING",
                    None,
                    now,
                    now,
                ),
            )
            connection.commit()
            row = connection.execute("SELECT * FROM channels WHERE channel_profile_id=?", (channel_profile_id,)).fetchone()
            assert row is not None
            return self._row_to_channel(row), False

    def _row_to_channel(self, row: sqlite3.Row) -> dict[str, Any]:
        return {
            "channelProfileId": row["channel_profile_id"],
            "displayName": row["display_name"],
            "lifecycleStatus": row["lifecycle_status"],
            "targetRegion": row["target_region"],
            "outputLanguage": row["output_language"],
            "publisherBinding": {
                "publisherProfileId": row["publisher_profile_id"],
                "channelSerial": row["channel_serial"],
                "youtubeChannelId": row["youtube_channel_id"],
            },
            "currentPresetId": row["current_preset_id"],
            "createdAt": row["created_at"],
            "updatedAt": row["updated_at"],
        }

    def list_channels(self) -> list[dict[str, Any]]:
        with self._system_connection() as connection:
            rows = connection.execute("SELECT * FROM channels ORDER BY channel_serial, channel_profile_id").fetchall()
        return [self._row_to_channel(row) for row in rows]

    def get_channel(self, channel_profile_id: str) -> dict[str, Any]:
        with self._system_connection() as connection:
            row = connection.execute("SELECT * FROM channels WHERE channel_profile_id=?", (channel_profile_id,)).fetchone()
        if row is None:
            raise ToolError("CHANNEL_NOT_FOUND", "没有找到频道资料库。")
        summary = self._row_to_channel(row)
        channel_json = self.channel_path(channel_profile_id) / "channel.json"
        if channel_json.is_file():
            summary["channelProfile"] = json.loads(channel_json.read_text(encoding="utf-8"))
        if row["current_preset_id"]:
            summary["productionProfile"] = self._active_production_profile(channel_profile_id)
        return summary

    def bind_task(self, *, task_id: str, channel_profile_id: str) -> dict[str, Any]:
        task_id = _safe_identifier(task_id, "taskId")
        channel_profile_id = _safe_identifier(channel_profile_id, "channelProfileId")
        proof = secrets.token_urlsafe(32)
        proof_hash = hashlib.sha256(proof.encode("utf-8")).hexdigest()
        binding_id = f"bind_{uuid.uuid4().hex}"
        now = utc_now()
        with self._system_connection() as connection:
            channel = connection.execute("SELECT channel_profile_id FROM channels WHERE channel_profile_id=?", (channel_profile_id,)).fetchone()
            if channel is None:
                raise ToolError("CHANNEL_NOT_FOUND", "没有找到要绑定的频道资料库。")
            existing = connection.execute("SELECT * FROM task_bindings WHERE task_id=?", (task_id,)).fetchone()
            if existing and existing["channel_profile_id"] != channel_profile_id:
                raise ToolError(
                    "TASK_ALREADY_BOUND",
                    "一个 Codex 任务只能绑定一个目标频道；切换频道必须新建任务。",
                    details={"boundChannelProfileId": existing["channel_profile_id"]},
                )
            if existing:
                binding_id = existing["binding_id"]
                connection.execute(
                    "UPDATE task_bindings SET proof_hash=?,updated_at=? WHERE task_id=?",
                    (proof_hash, now, task_id),
                )
            else:
                connection.execute(
                    "INSERT INTO task_bindings VALUES(?,?,?,?,?,?)",
                    (task_id, binding_id, channel_profile_id, proof_hash, now, now),
                )
            connection.commit()
        return {
            "taskId": task_id,
            "bindingId": binding_id,
            "bindingProof": proof,
            "channelProfileId": channel_profile_id,
            "rotated": existing is not None,
        }

    def get_task_binding(self, task_id: str) -> dict[str, Any] | None:
        task_id = _safe_identifier(task_id, "taskId")
        with self._system_connection() as connection:
            row = connection.execute(
                "SELECT task_id,binding_id,channel_profile_id,bound_at,updated_at FROM task_bindings WHERE task_id=?",
                (task_id,),
            ).fetchone()
        if row is None:
            return None
        return {
            "taskId": row["task_id"],
            "bindingId": row["binding_id"],
            "channelProfileId": row["channel_profile_id"],
            "boundAt": row["bound_at"],
            "updatedAt": row["updated_at"],
        }

    def assert_binding(self, *, task_id: str, channel_profile_id: str, binding_proof: str) -> None:
        if not isinstance(binding_proof, str) or not binding_proof:
            raise ToolError("BINDING_PROOF_REQUIRED", "写入频道资料库前必须提供当前任务绑定校验值。")
        proof_hash = hashlib.sha256(binding_proof.encode("utf-8")).hexdigest()
        with self._system_connection() as connection:
            row = connection.execute("SELECT * FROM task_bindings WHERE task_id=?", (task_id,)).fetchone()
        if row is None or row["channel_profile_id"] != channel_profile_id or not secrets.compare_digest(row["proof_hash"], proof_hash):
            raise ToolError("CHANNEL_BINDING_MISMATCH", "当前任务绑定校验失败，禁止跨频道写入。")

    def complete_library(
        self,
        *,
        task_id: str,
        channel_profile_id: str,
        binding_proof: str,
        defaults: dict[str, Any],
        execution_mode: str = "review",
    ) -> dict[str, Any]:
        self.assert_binding(task_id=task_id, channel_profile_id=channel_profile_id, binding_proof=binding_proof)
        defaults = validate_defaults(defaults)
        if execution_mode != "review":
            raise ToolError(
                "PERSISTENT_AUTO_MODE_NOT_ALLOWED",
                "频道预设固定为审核模式；自动完成授权只能绑定当前任务，不能写入频道资料库。",
            )
        with self._system_connection() as connection:
            row = connection.execute("SELECT * FROM channels WHERE channel_profile_id=?", (channel_profile_id,)).fetchone()
        if row is None:
            raise ToolError("CHANNEL_NOT_FOUND", "没有找到频道。")
        if row["lifecycle_status"] == "READY":
            existing = self.get_channel(channel_profile_id)
            if existing.get("productionProfile", {}).get("defaults") == defaults:
                return {**existing, "idempotent": True}
            raise ToolError("CHANNEL_ALREADY_READY", "资料库已经建立；默认值修改必须生成新的预设版本。")
        if row["lifecycle_status"] != "LIBRARY_DEFAULTS_PENDING":
            raise ToolError("INVALID_CHANNEL_STATE", "当前频道状态不允许创建资料库。", details={"state": row["lifecycle_status"]})

        final_path = self.channel_path(channel_profile_id)
        if final_path.exists():
            raise ToolError("LIBRARY_PATH_CONFLICT", "频道资料目录已存在，已进入保护状态。")
        creating_path = self.channels_root / f".creating-{channel_profile_id}-{uuid.uuid4().hex}"
        now = utc_now()
        channel = channel_contract(
            channel_profile_id=channel_profile_id,
            display_name=row["display_name"],
            target_region=row["target_region"],
            output_language=row["output_language"],
            publisher_profile_id=row["publisher_profile_id"],
            channel_serial=row["channel_serial"],
            youtube_channel_id=row["youtube_channel_id"],
            created_at=now,
        )
        preset_id = f"preset_{uuid.uuid4().hex}"
        production = production_contract(
            preset_id=preset_id,
            channel=channel,
            defaults=defaults,
            created_at=now,
            execution_mode=execution_mode,
        )
        try:
            creating_path.mkdir(parents=True)
            for relative in CHANNEL_DIRECTORIES:
                (creating_path / relative).mkdir(parents=True, exist_ok=True)
            (creating_path / "channel.json").write_text(json.dumps(channel, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            preset_path = creating_path / "presets" / f"{preset_id}-v1.0.0.json"
            preset_path.write_text(json.dumps(production, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            self._initialize_channel_database(creating_path / "channel.db", channel, production)
            os.replace(creating_path, final_path)
            with self._system_connection() as connection:
                connection.execute(
                    "UPDATE channels SET lifecycle_status='READY',current_preset_id=?,updated_at=? WHERE channel_profile_id=?",
                    (preset_id, utc_now(), channel_profile_id),
                )
                connection.execute(
                    "INSERT INTO audit_events VALUES(?,?,?,?,?,?)",
                    (f"evt_{uuid.uuid4().hex}", "CHANNEL_LIBRARY_CREATED", channel_profile_id, task_id, "{}", utc_now()),
                )
                connection.commit()
        except Exception as exc:
            if creating_path.exists():
                shutil.rmtree(creating_path)
            if final_path.exists():
                shutil.rmtree(final_path)
            raise ToolError(
                "LIBRARY_CREATE_FAILED",
                "频道资料库创建失败，未留下半成品。",
                details={"errorType": type(exc).__name__},
            ) from exc
        result = self.get_channel(channel_profile_id)
        result["idempotent"] = False
        return result

    def _active_production_profile(self, channel_profile_id: str) -> dict[str, Any]:
        with self._channel_connection(channel_profile_id) as connection:
            row = connection.execute(
                "SELECT contract_json FROM production_profile_versions WHERE active=1 ORDER BY created_at DESC LIMIT 1"
            ).fetchone()
        if row is None:
            raise ToolError("PRODUCTION_PROFILE_MISSING", "频道没有活动生产预设。")
        return json.loads(row["contract_json"])

    def resolve_production(
        self,
        *,
        task_id: str,
        channel_profile_id: str,
        binding_proof: str,
        overrides: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        self.assert_binding(task_id=task_id, channel_profile_id=channel_profile_id, binding_proof=binding_proof)
        profile = self._active_production_profile(channel_profile_id)
        override = overrides or {}
        if not isinstance(override, dict):
            raise ToolError("INVALID_OVERRIDE", "本次覆盖必须是对象。")
        effective, changed = _deep_merge(profile["defaults"], override)
        effective = validate_defaults(effective)
        if changed:
            with self._channel_connection(channel_profile_id) as connection:
                connection.execute(
                    "INSERT INTO task_override_events VALUES(?,?,?,?,?,?,?)",
                    (
                        f"override_{uuid.uuid4().hex}",
                        task_id,
                        profile["presetId"],
                        profile["presetVersion"],
                        _json_dumps(override),
                        _json_dumps(changed),
                        utc_now(),
                    ),
                )
                connection.commit()
        return {
            "channelProfileId": channel_profile_id,
            "productionProfile": profile,
            "effectiveDefaults": effective,
            "overridePaths": changed,
            "persistedDefaultsChanged": False,
        }

    def update_defaults(
        self,
        *,
        task_id: str,
        channel_profile_id: str,
        binding_proof: str,
        defaults: dict[str, Any],
        confirmation: dict[str, Any],
    ) -> dict[str, Any]:
        self.assert_binding(task_id=task_id, channel_profile_id=channel_profile_id, binding_proof=binding_proof)
        if confirmation != {"confirmed": True, "scope": "channel_default"}:
            raise ToolError("CHANNEL_DEFAULT_CONFIRMATION_REQUIRED", "长期默认值变更必须明确确认 scope=channel_default。")
        defaults = validate_defaults(defaults)
        current = self._active_production_profile(channel_profile_id)
        if current["defaults"] == defaults:
            return {"productionProfile": current, "idempotent": True}
        channel = self.get_channel(channel_profile_id)["channelProfile"]
        major, minor, patch = (int(item) for item in current["presetVersion"].split("."))
        next_version = f"{major}.{minor + 1}.0"
        created = utc_now()
        updated = production_contract(
            preset_id=current["presetId"],
            channel=channel,
            defaults=defaults,
            created_at=created,
            preset_version=next_version,
            execution_mode=current["executionMode"],
            first_confirmation=current["firstConfirmation"],
        )
        preset_path = self.channel_path(channel_profile_id) / "presets" / f"{updated['presetId']}-v{next_version}.json"
        temporary_preset = preset_path.with_suffix(".json.tmp")
        temporary_preset.write_text(json.dumps(updated, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.replace(temporary_preset, preset_path)
        try:
            with self._channel_connection(channel_profile_id) as connection:
                connection.execute("BEGIN IMMEDIATE")
                connection.execute("UPDATE production_profile_versions SET active=0 WHERE active=1")
                connection.execute(
                    "INSERT INTO production_profile_versions VALUES(?,?,?,?,?,?)",
                    (updated["presetId"], next_version, _json_dumps(updated), updated["contentHash"], 1, created),
                )
                connection.commit()
        except Exception:
            preset_path.unlink(missing_ok=True)
            raise
        return {"productionProfile": updated, "idempotent": False, "affectsExistingProjects": False}

    def integrity_check(self, channel_profile_id: str | None = None) -> dict[str, Any]:
        checks: list[dict[str, Any]] = []
        with self._system_connection() as connection:
            system_result = connection.execute("PRAGMA integrity_check").fetchone()[0]
        checks.append({"component": "system.db", "status": "PASS" if system_result == "ok" else "FAIL", "detail": system_result})
        targets = [channel_profile_id] if channel_profile_id else [item["channelProfileId"] for item in self.list_channels()]
        for identifier in targets:
            summary = self.get_channel(identifier)
            if summary["lifecycleStatus"] != "READY":
                checks.append({"component": identifier, "status": "PENDING", "detail": summary["lifecycleStatus"]})
                continue
            path = self.channel_path(identifier)
            try:
                channel = json.loads((path / "channel.json").read_text(encoding="utf-8"))
                hash_ok = canonical_hash(channel) == channel.get("contentHash")
                with self._channel_connection(identifier) as connection:
                    db_ok = connection.execute("PRAGMA integrity_check").fetchone()[0]
                    schema = int(connection.execute("PRAGMA user_version").fetchone()[0])
                    profile_row = connection.execute(
                        "SELECT preset_id,preset_version,contract_json,content_hash FROM production_profile_versions WHERE active=1"
                    ).fetchone()
                profile_ok = False
                profile_file_ok = False
                if profile_row is not None:
                    profile = json.loads(profile_row["contract_json"])
                    profile_ok = (
                        profile.get("contentHash") == profile_row["content_hash"]
                        and canonical_hash(profile) == profile.get("contentHash")
                    )
                    profile_path = path / "presets" / f"{profile_row['preset_id']}-v{profile_row['preset_version']}.json"
                    if profile_path.is_file():
                        file_profile = json.loads(profile_path.read_text(encoding="utf-8"))
                        profile_file_ok = file_profile == profile
                status = (
                    "PASS"
                    if hash_ok and profile_ok and profile_file_ok and db_ok == "ok" and schema == CHANNEL_SCHEMA_VERSION
                    else "FAIL"
                )
                checks.append({
                    "component": identifier,
                    "status": status,
                    "detail": {
                        "channelHash": hash_ok,
                        "productionProfileHash": profile_ok,
                        "productionProfileFile": profile_file_ok,
                        "database": db_ok,
                        "schemaVersion": schema,
                    },
                })
            except (OSError, json.JSONDecodeError, sqlite3.DatabaseError) as exc:
                checks.append({"component": identifier, "status": "FAIL", "detail": type(exc).__name__})
        return {"status": "PASS" if all(item["status"] in {"PASS", "PENDING"} for item in checks) else "FAIL", "checks": checks}

    def _archive_manifest(self, channel_profile_id: str, source: Path) -> dict[str, Any]:
        files = []
        for path in sorted((item for item in source.rglob("*") if item.is_file()), key=lambda item: item.relative_to(source).as_posix()):
            relative = path.relative_to(source).as_posix()
            files.append({"path": relative, "sizeBytes": path.stat().st_size, "sha256": _sha256_file(path)})
        channel = json.loads((source / "channel.json").read_text(encoding="utf-8"))
        return {
            "archiveFormatVersion": ARCHIVE_FORMAT_VERSION,
            "channelProfileId": channel_profile_id,
            "youtubeChannelId": channel["publisherBinding"]["youtubeChannelId"],
            "createdAt": utc_now(),
            "files": files,
        }

    def _write_archive(self, channel_profile_id: str, output: Path) -> dict[str, Any]:
        source = self.channel_path(channel_profile_id)
        if not source.is_dir():
            raise ToolError("CHANNEL_LIBRARY_NOT_READY", "只有 READY 频道可以备份。")
        integrity = self.integrity_check(channel_profile_id)
        if integrity["status"] != "PASS":
            raise ToolError("INTEGRITY_CHECK_FAILED", "资料库完整性检查失败，禁止生成备份。", details=integrity)
        output.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=output.parent, prefix="archive-") as temp_name:
            snapshot = Path(temp_name) / "channel"
            def ignore_active_database(directory: str, names: list[str]) -> set[str]:
                return {"channel.db"} if Path(directory).resolve() == source.resolve() and "channel.db" in names else set()

            shutil.copytree(source, snapshot, ignore=ignore_active_database)
            with closing(sqlite3.connect(source / "channel.db")) as source_db, closing(
                sqlite3.connect(snapshot / "channel.db")
            ) as snapshot_db:
                source_db.backup(snapshot_db)
            manifest = self._archive_manifest(channel_profile_id, snapshot)
            temp_archive = Path(temp_name) / output.name
            with zipfile.ZipFile(temp_archive, "w", compression=zipfile.ZIP_DEFLATED) as archive:
                archive.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
                for item in manifest["files"]:
                    archive.write(snapshot / item["path"], f"channel/{item['path']}")
            os.replace(temp_archive, output)
        return {"archivePath": str(output), "sha256": _sha256_file(output), "manifest": manifest}

    def backup_channel(self, channel_profile_id: str, *, kind: str = "quick") -> dict[str, Any]:
        if kind not in {"quick", "full", "pre_restore"}:
            raise ToolError("INVALID_ARGUMENT", "备份类型不受支持。")
        output = self.backups_root / channel_profile_id / f"{kind}-{uuid.uuid4().hex}.avchannel"
        result = self._write_archive(channel_profile_id, output)
        result["backupKind"] = kind
        return result

    def export_channel(self, channel_profile_id: str) -> dict[str, Any]:
        output = self.exports_root / f"{channel_profile_id}-{uuid.uuid4().hex}.avchannel"
        return self._write_archive(channel_profile_id, output)

    def _resolve_archive(self, archive_path: str) -> Path:
        if not isinstance(archive_path, str) or not archive_path:
            raise ToolError("INVALID_ARGUMENT", "archivePath 是必填项。")
        candidate = Path(archive_path).resolve()
        allowed = (self.backups_root.resolve(), self.exports_root.resolve(), self.imports_root.resolve())
        if not any(candidate == root or root in candidate.parents for root in allowed):
            raise ToolError("ARCHIVE_PATH_FORBIDDEN", "迁移包只能从系统备份、导出或导入目录读取。")
        if not candidate.is_file() or candidate.suffix.lower() != ".avchannel":
            raise ToolError("ARCHIVE_NOT_FOUND", "没有找到有效的 .avchannel 文件。")
        return candidate

    def verify_archive(self, archive_path: str) -> dict[str, Any]:
        path = self._resolve_archive(archive_path)
        try:
            with zipfile.ZipFile(path, "r") as archive:
                names = archive.namelist()
                if len(names) != len(set(names)):
                    raise ToolError("ARCHIVE_DUPLICATE_PATH", "迁移包包含重复文件路径。")
                for name in names:
                    posix = PurePosixPath(name)
                    if posix.is_absolute() or ".." in posix.parts or "\\" in name:
                        raise ToolError("ARCHIVE_UNSAFE_PATH", "迁移包包含不安全路径。")
                manifest_info = archive.getinfo("manifest.json")
                if manifest_info.file_size > MAX_ARCHIVE_MANIFEST_BYTES:
                    raise ToolError("ARCHIVE_MANIFEST_TOO_LARGE", "迁移包清单超过安全上限。")
                manifest = json.loads(archive.read(manifest_info))
                if not isinstance(manifest, dict):
                    raise ToolError("ARCHIVE_MANIFEST_INVALID", "迁移包清单必须是对象。")
                if manifest.get("archiveFormatVersion") != ARCHIVE_FORMAT_VERSION:
                    raise ToolError("ARCHIVE_VERSION_UNSUPPORTED", "迁移包版本不受支持。")
                files = manifest.get("files")
                if not isinstance(files, list) or len(files) > MAX_ARCHIVE_FILES:
                    raise ToolError("ARCHIVE_MANIFEST_INVALID", "迁移包文件清单无效或超过数量上限。")
                validated_paths: set[str] = set()
                total_size = 0
                for item in files:
                    if not isinstance(item, dict) or set(item) != {"path", "sizeBytes", "sha256"}:
                        raise ToolError("ARCHIVE_MANIFEST_INVALID", "迁移包文件记录无效。")
                    relative = item["path"]
                    if not isinstance(relative, str) or not relative:
                        raise ToolError("ARCHIVE_MANIFEST_INVALID", "迁移包文件路径无效。")
                    relative_path = PurePosixPath(relative)
                    if relative_path.is_absolute() or ".." in relative_path.parts or "\\" in relative:
                        raise ToolError("ARCHIVE_UNSAFE_PATH", "迁移包清单包含不安全路径。")
                    if relative in validated_paths:
                        raise ToolError("ARCHIVE_DUPLICATE_PATH", "迁移包清单包含重复文件路径。")
                    if not isinstance(item["sizeBytes"], int) or item["sizeBytes"] < 0:
                        raise ToolError("ARCHIVE_MANIFEST_INVALID", "迁移包文件大小无效。")
                    if not isinstance(item["sha256"], str) or len(item["sha256"]) != 64:
                        raise ToolError("ARCHIVE_MANIFEST_INVALID", "迁移包文件哈希无效。")
                    validated_paths.add(relative)
                    total_size += item["sizeBytes"]
                if total_size > MAX_ARCHIVE_UNCOMPRESSED_BYTES:
                    raise ToolError("ARCHIVE_TOO_LARGE", "迁移包解压后超过安全上限。")
                expected_names = {f"channel/{item['path']}" for item in files}
                if expected_names | {"manifest.json"} != set(names):
                    raise ToolError("ARCHIVE_MANIFEST_MISMATCH", "迁移包文件清单不一致。")
                for item in files:
                    info = archive.getinfo(f"channel/{item['path']}")
                    if info.file_size != item["sizeBytes"]:
                        raise ToolError("ARCHIVE_HASH_MISMATCH", "迁移包文件大小不一致。", details={"path": item["path"]})
                    digest = hashlib.sha256()
                    observed_size = 0
                    with archive.open(info, "r") as handle:
                        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                            observed_size += len(chunk)
                            digest.update(chunk)
                    if observed_size != item["sizeBytes"] or digest.hexdigest() != item["sha256"]:
                        raise ToolError("ARCHIVE_HASH_MISMATCH", "迁移包文件哈希不一致。", details={"path": item["path"]})
                channel_profile = json.loads(archive.read("channel/channel.json"))
                if (
                    channel_profile.get("channelProfileId") != manifest.get("channelProfileId")
                    or channel_profile.get("publisherBinding", {}).get("youtubeChannelId") != manifest.get("youtubeChannelId")
                    or canonical_hash(channel_profile) != channel_profile.get("contentHash")
                ):
                    raise ToolError("ARCHIVE_IDENTITY_MISMATCH", "迁移包身份与 Channel Profile 不一致。")
        except (zipfile.BadZipFile, KeyError, json.JSONDecodeError) as exc:
            raise ToolError("ARCHIVE_INVALID", "迁移包损坏或格式无效。") from exc
        return {
            "valid": True,
            "archivePath": str(path),
            "sha256": _sha256_file(path),
            "manifest": manifest,
            "channelProfile": channel_profile,
        }

    def import_channel(self, archive_path: str, *, conflict_mode: str = "reject") -> dict[str, Any]:
        if conflict_mode not in {"reject", "reuse_existing"}:
            raise ToolError("INVALID_ARGUMENT", "conflictMode 只允许 reject 或 reuse_existing。")
        verified = self.verify_archive(archive_path)
        manifest = verified["manifest"]
        channel_profile_id = manifest["channelProfileId"]
        existing_by_id: dict[str, Any] | None = None
        try:
            existing_by_id = self.get_channel(channel_profile_id)
        except ToolError as exc:
            if exc.code != "CHANNEL_NOT_FOUND":
                raise
        with self._system_connection() as connection:
            same_youtube = connection.execute(
                "SELECT channel_profile_id FROM channels WHERE youtube_channel_id=?",
                (manifest["youtubeChannelId"],),
            ).fetchone()
        if existing_by_id or same_youtube:
            existing_id = existing_by_id["channelProfileId"] if existing_by_id else same_youtube["channel_profile_id"]
            if conflict_mode == "reuse_existing" and existing_id == channel_profile_id:
                return {"channelProfileId": existing_id, "reused": True, "imported": False}
            raise ToolError(
                "IMPORT_IDENTITY_CONFLICT",
                "迁移包与现有频道身份冲突；不会覆盖或复制真实频道。",
                details={"existingChannelProfileId": existing_id},
            )
        archive = self._resolve_archive(archive_path)
        final_path = self.channel_path(channel_profile_id)
        temp_path = self.channels_root / f".importing-{channel_profile_id}-{uuid.uuid4().hex}"
        try:
            with zipfile.ZipFile(archive, "r") as zipped:
                temp_path.mkdir(parents=True)
                for item in manifest["files"]:
                    target = temp_path / PurePosixPath(item["path"])
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with zipped.open(f"channel/{item['path']}", "r") as source, target.open("wb") as destination:
                        shutil.copyfileobj(source, destination, length=1024 * 1024)
            channel = json.loads((temp_path / "channel.json").read_text(encoding="utf-8"))
            if channel["channelProfileId"] != channel_profile_id or canonical_hash(channel) != channel["contentHash"]:
                raise ToolError("IMPORT_CONTRACT_INVALID", "迁移包中的 Channel Profile 无效。")
            with closing(sqlite3.connect(temp_path / "channel.db")) as connection:
                if connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                    raise ToolError("IMPORT_DATABASE_INVALID", "迁移包数据库完整性检查失败。")
                row = connection.execute(
                    "SELECT preset_id FROM production_profile_versions WHERE active=1 LIMIT 1"
                ).fetchone()
            if row is None:
                raise ToolError("IMPORT_PROFILE_MISSING", "迁移包没有活动生产预设。")
            os.replace(temp_path, final_path)
            now = utc_now()
            with self._system_connection() as connection:
                binding = channel["publisherBinding"]
                connection.execute(
                    """INSERT INTO channels VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        channel_profile_id,
                        binding["publisherProfileId"],
                        binding["channelSerial"],
                        binding["youtubeChannelId"],
                        channel["displayName"],
                        channel["targetRegion"],
                        channel["outputLanguage"],
                        "READY",
                        row[0],
                        channel["createdAt"],
                        now,
                    ),
                )
                connection.commit()
        except Exception:
            if temp_path.exists():
                shutil.rmtree(temp_path)
            if final_path.exists():
                shutil.rmtree(final_path)
            raise
        return {"channelProfileId": channel_profile_id, "reused": False, "imported": True}

    def restore_channel(
        self,
        archive_path: str,
        *,
        mode: str = "verify_only",
        confirmation: str | None = None,
    ) -> dict[str, Any]:
        verified = self.verify_archive(archive_path)
        channel_profile_id = verified["manifest"]["channelProfileId"]
        if mode == "verify_only":
            return {**verified, "restored": False}
        if mode != "replace" or confirmation != "RESTORE_CHANNEL_FROM_BACKUP":
            raise ToolError("RESTORE_CONFIRMATION_REQUIRED", "替换恢复必须经过外部确认并提供固定确认值。")
        current = self.get_channel(channel_profile_id)
        if current["lifecycleStatus"] != "READY":
            raise ToolError("INVALID_CHANNEL_STATE", "只有 READY 频道可以执行替换恢复。")
        pre_restore = self.backup_channel(channel_profile_id, kind="pre_restore")
        archive = self._resolve_archive(archive_path)
        final_path = self.channel_path(channel_profile_id)
        staging = self.channels_root / f".restoring-{channel_profile_id}-{uuid.uuid4().hex}"
        rollback = self.channels_root / f".rollback-{channel_profile_id}-{uuid.uuid4().hex}"
        try:
            with zipfile.ZipFile(archive, "r") as zipped:
                staging.mkdir(parents=True)
                for item in verified["manifest"]["files"]:
                    target = staging / PurePosixPath(item["path"])
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with zipped.open(f"channel/{item['path']}", "r") as source, target.open("wb") as destination:
                        shutil.copyfileobj(source, destination, length=1024 * 1024)
            os.replace(final_path, rollback)
            os.replace(staging, final_path)
            checked = self.integrity_check(channel_profile_id)
            if checked["status"] != "PASS" or os.environ.get("AIVCP_TEST_FAIL_RESTORE") == "1":
                raise ToolError("RESTORE_INTEGRITY_FAILED", "恢复后的资料库未通过完整性检查。")
            shutil.rmtree(rollback)
        except Exception as exc:
            if final_path.exists() and rollback.exists():
                shutil.rmtree(final_path)
            if rollback.exists():
                os.replace(rollback, final_path)
            if staging.exists():
                shutil.rmtree(staging)
            if isinstance(exc, ToolError):
                raise
            raise ToolError("RESTORE_FAILED", "恢复失败，已回滚至恢复前资料库。") from exc
        return {
            "channelProfileId": channel_profile_id,
            "restored": True,
            "preRestoreBackup": pre_restore["archivePath"],
            "integrity": self.integrity_check(channel_profile_id),
        }
