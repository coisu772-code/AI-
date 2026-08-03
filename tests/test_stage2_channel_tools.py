from __future__ import annotations

import json
import os
import shutil
import sqlite3
import sys
import tempfile
import unittest
import hashlib
from contextlib import closing
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry, Resource


ROOT = Path(__file__).resolve().parents[1]
MCP_ROOT = ROOT / "plugins" / "ai-video-channel-production" / "mcp"
sys.path.insert(0, str(MCP_ROOT))

from aivcp_tools.errors import ToolError  # noqa: E402
from aivcp_tools.publisher import (  # noqa: E402
    CommandPublisherProvider,
    FixturePublisherProvider,
    PublisherCenterCliV1Provider,
    provider_from_environment,
)
from aivcp_tools.service import LocalToolService, ServiceConfig  # noqa: E402
from aivcp_tools.store import ChannelStore  # noqa: E402
from server import McpServer  # noqa: E402


class StaticPublisherProvider:
    def __init__(self, channels: list[dict[str, object]] | None = None):
        self.channels = channels if channels is not None else [synthetic_channel()]

    def capabilities(self) -> dict[str, object]:
        return {
            "available": True,
            "protocolVersion": "1.0.0",
            "transport": "unit-test",
            "testOnly": True,
        }

    def list_channels(self) -> list[dict[str, object]]:
        return json.loads(json.dumps(self.channels))


def synthetic_channel() -> dict[str, object]:
    return {
        "publisherProfileId": "publisher_fixture_001",
        "channelSerial": "01",
        "youtubeChannelId": "UCFIXTURECHANNEL0001",
        "displayName": "Fixture Channel",
        "enabled": True,
        "authorizationStatus": "AUTHORIZED",
        "defaultLanguage": "ja-JP",
        "privacyStatus": "private",
        "timeZone": "Asia/Tokyo",
    }


def defaults(*, preferred_characters: int = 12000) -> dict[str, object]:
    return {
        "voice": {"engineId": "fixture-tts", "voiceId": "fixture-ja-001"},
        "manuscript": {
            "mode": "auto_by_topic",
            "preferredCharacters": preferred_characters,
            "minCharacters": 8000,
            "maxCharacters": 16000,
        },
        "episodes": {"mode": "auto_by_topic", "preferredCount": 8, "minCount": 6, "maxCount": 12},
        "deliveryMode": "auto_render",
        "videoGeneration": {"enabled": False, "selectionMode": "none", "fallbackPolicy": "pause"},
        "uploadPolicy": "REQUIRE_REVIEW",
    }


def contract_validator(schema_name: str) -> Draft202012Validator:
    schema_paths = sorted((ROOT / "contracts" / "schemas").glob("*.schema.json"))
    resources = []
    selected = None
    for path in schema_paths:
        schema = json.loads(path.read_text(encoding="utf-8"))
        resources.append((schema["$id"], Resource.from_contents(schema)))
        if path.name == schema_name:
            selected = schema
    assert selected is not None
    return Draft202012Validator(selected, registry=Registry().with_resources(resources), format_checker=FormatChecker())


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def create_publisher_cli_fixture(path: Path) -> None:
    with closing(sqlite3.connect(path)) as connection:
        connection.execute(
            """CREATE TABLE youtube_profiles(
                id INTEGER PRIMARY KEY,
                profile_id TEXT NOT NULL,
                channel_serial TEXT NOT NULL,
                channel_id TEXT NOT NULL,
                channel_title TEXT NOT NULL,
                enabled INTEGER NOT NULL,
                auth_status TEXT NOT NULL,
                default_privacy TEXT NOT NULL,
                publish_timezone TEXT NOT NULL,
                upload_mode TEXT NOT NULL,
                is_demo INTEGER NOT NULL,
                deleted_at TEXT,
                created_at TEXT NOT NULL
            )"""
        )
        connection.execute(
            "INSERT INTO youtube_profiles VALUES(1,?,?,?,?,?,?,?,?,?,?,NULL,?)",
            (
                "publisher_fixture_001",
                "01",
                "UCFIXTURECHANNEL0001",
                "Fixture Channel",
                1,
                "ACTIVE",
                "private",
                "Asia/Tokyo",
                "REQUIRE_REVIEW",
                0,
                "2026-08-04T00:00:00Z",
            ),
        )
        connection.commit()


class Stage2ToolTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="aivcp-stage2-")
        self.root = Path(self.temp.name)
        voice_catalog = self.root / "voice-catalog.json"
        voice_catalog.write_text(
            json.dumps(
                {
                    "schemaVersion": "1.0.0",
                    "generatedAt": "2026-08-04T00:00:00Z",
                    "engines": [
                        {
                            "engineId": "fixture-tts",
                            "displayName": "Fixture TTS",
                            "installed": True,
                            "voices": [
                                {
                                    "voiceId": "fixture-ja-001",
                                    "displayName": "Fixture Japanese Voice",
                                    "languages": ["ja-JP"],
                                    "recommended": True,
                                }
                            ],
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        self.service = LocalToolService(
            ServiceConfig(data_root=self.root / "data", voice_catalog_path=voice_catalog),
            publisher_provider=StaticPublisherProvider(),
        )

    def tearDown(self) -> None:
        os.environ.pop("AIVCP_TEST_FAIL_MIGRATION", None)
        os.environ.pop("AIVCP_TEST_FAIL_RESTORE", None)
        self.temp.cleanup()

    def onboard(self, *, task_id: str = "task_fixture_001") -> tuple[dict[str, object], str]:
        started = self.service.call(
            "channel_onboarding_start",
            {
                "taskId": task_id,
                "channelSerial": "01",
                "targetRegion": "Japan",
                "outputLanguage": "ja-JP",
            },
        )
        proof = started["taskBinding"]["bindingProof"]
        completed = self.service.call(
            "channel_onboarding_complete",
            {
                "taskId": task_id,
                "channelProfileId": started["channel"]["channelProfileId"],
                "bindingProof": proof,
                "defaults": defaults(),
            },
        )
        return completed, proof

    def test_capabilities_and_unimplemented_centers_are_explicit(self) -> None:
        result = self.service.call("system_capabilities")
        self.assertEqual(result["protocolVersion"], "1.0.0")
        self.assertTrue(result["capabilities"]["channelOnboarding"])
        self.assertFalse(result["capabilities"]["sourceCollection"])
        self.assertFalse(result["capabilities"]["upload"])
        self.assertFalse(result["security"]["privateMaterialAccepted"])

    def test_two_phase_onboarding_contracts_and_idempotency(self) -> None:
        started = self.service.call(
            "channel_onboarding_start",
            {
                "taskId": "task_fixture_001",
                "channelSerial": "01",
                "targetRegion": "Japan",
                "outputLanguage": "ja-JP",
            },
        )
        self.assertEqual(started["phase"], "LIBRARY_DEFAULTS_PENDING")
        self.assertFalse(started["idempotentChannel"])
        channel_id = started["channel"]["channelProfileId"]
        self.assertFalse((self.root / "data" / "channels" / channel_id).exists())

        completed = self.service.call(
            "channel_onboarding_complete",
            {
                "taskId": "task_fixture_001",
                "channelProfileId": channel_id,
                "bindingProof": started["taskBinding"]["bindingProof"],
                "defaults": defaults(),
            },
        )
        self.assertEqual(completed["lifecycleStatus"], "READY")
        library = self.root / "data" / "channels" / channel_id
        self.assertTrue((library / "channel.db").is_file())
        self.assertTrue((library / "learning").is_dir())
        channel_contract = completed["channelProfile"]
        production_contract = completed["productionProfile"]
        self.assertEqual(list(contract_validator("channel-profile.schema.json").iter_errors(channel_contract)), [])
        self.assertEqual(list(contract_validator("production-profile.schema.json").iter_errors(production_contract)), [])

        repeated = self.service.call(
            "channel_onboarding_start",
            {
                "taskId": "task_fixture_001",
                "youtubeChannelId": "UCFIXTURECHANNEL0001",
                "targetRegion": "Japan",
                "outputLanguage": "ja-JP",
            },
        )
        self.assertTrue(repeated["idempotentChannel"])
        self.assertEqual(repeated["channel"]["channelProfileId"], channel_id)
        repeated_complete = self.service.call(
            "channel_onboarding_complete",
            {
                "taskId": "task_fixture_001",
                "channelProfileId": channel_id,
                "bindingProof": repeated["taskBinding"]["bindingProof"],
                "defaults": defaults(),
            },
        )
        self.assertTrue(repeated_complete["idempotent"])

    def test_task_isolation_rebind_and_one_time_override(self) -> None:
        completed, original_proof = self.onboard()
        channel_id = completed["channelProfileId"]
        rebound = self.service.call(
            "channel_bind_task", {"taskId": "task_new_conversation", "channelProfileId": channel_id}
        )
        resolved = self.service.call(
            "channel_resolve_production",
            {
                "taskId": "task_new_conversation",
                "channelProfileId": channel_id,
                "bindingProof": rebound["bindingProof"],
                "overrides": {"episodes": {"preferredCount": 10}},
            },
        )
        self.assertEqual(resolved["effectiveDefaults"]["episodes"]["preferredCount"], 10)
        self.assertEqual(resolved["productionProfile"]["defaults"]["episodes"]["preferredCount"], 8)
        self.assertFalse(resolved["persistedDefaultsChanged"])
        with self.assertRaises(ToolError) as error:
            self.service.call(
                "channel_resolve_production",
                {
                    "taskId": "task_new_conversation",
                    "channelProfileId": channel_id,
                    "bindingProof": original_proof,
                },
            )
        self.assertEqual(error.exception.code, "CHANNEL_BINDING_MISMATCH")

        second_provider = StaticPublisherProvider(
            [
                synthetic_channel(),
                {
                    "publisherProfileId": "publisher_fixture_002",
                    "channelSerial": "02",
                    "youtubeChannelId": "UCFIXTURECHANNEL0002",
                    "displayName": "Second Channel",
                    "enabled": True,
                    "authorizationStatus": "AUTHORIZED",
                },
            ]
        )
        self.service.publisher = second_provider
        with self.assertRaises(ToolError) as collision:
            self.service.call(
                "channel_onboarding_start",
                {
                    "taskId": "task_new_conversation",
                    "channelSerial": "02",
                    "targetRegion": "United States",
                    "outputLanguage": "en-US",
                },
            )
        self.assertEqual(collision.exception.code, "TASK_ALREADY_BOUND")

    def test_channel_defaults_require_confirmation_and_version(self) -> None:
        completed, proof = self.onboard()
        channel_id = completed["channelProfileId"]
        next_defaults = defaults(preferred_characters=14000)
        with self.assertRaises(ToolError) as error:
            self.service.call(
                "channel_update_defaults",
                {
                    "taskId": "task_fixture_001",
                    "channelProfileId": channel_id,
                    "bindingProof": proof,
                    "defaults": next_defaults,
                },
            )
        self.assertEqual(error.exception.code, "CHANNEL_DEFAULT_CONFIRMATION_REQUIRED")
        updated = self.service.call(
            "channel_update_defaults",
            {
                "taskId": "task_fixture_001",
                "channelProfileId": channel_id,
                "bindingProof": proof,
                "defaults": next_defaults,
                "confirmation": {"confirmed": True, "scope": "channel_default"},
            },
        )
        self.assertEqual(updated["productionProfile"]["presetVersion"], "1.1.0")
        self.assertFalse(updated["affectsExistingProjects"])

    def test_backup_export_import_conflict_and_restore_rollback(self) -> None:
        completed, proof = self.onboard()
        channel_id = completed["channelProfileId"]
        backup = self.service.call(
            "channel_backup",
            {
                "taskId": "task_fixture_001",
                "channelProfileId": channel_id,
                "bindingProof": proof,
            },
        )
        with self.assertRaises(ToolError) as binding_error:
            self.service.call("channel_backup", {"channelProfileId": channel_id})
        self.assertEqual(binding_error.exception.code, "BINDING_PROOF_REQUIRED")
        verified = self.service.call("channel_restore", {"archivePath": backup["archivePath"]})
        self.assertTrue(verified["valid"])
        self.assertFalse(verified["restored"])

        exported = self.service.call(
            "channel_export",
            {
                "taskId": "task_fixture_001",
                "channelProfileId": channel_id,
                "bindingProof": proof,
            },
        )
        other_root = self.root / "other-data"
        other = LocalToolService(ServiceConfig(data_root=other_root), publisher_provider=StaticPublisherProvider())
        other.store.imports_root.mkdir(parents=True)
        import_path = other.store.imports_root / "fixture.avchannel"
        shutil.copy2(exported["archivePath"], import_path)
        imported = other.call(
            "channel_import", {"archivePath": str(import_path), "taskId": "task_import"}
        )
        self.assertTrue(imported["imported"])
        self.assertEqual(imported["taskBinding"]["channelProfileId"], channel_id)
        reused = other.call(
            "channel_import",
            {"archivePath": str(import_path), "conflictMode": "reuse_existing", "taskId": "task_import"},
        )
        self.assertTrue(reused["reused"])
        with self.assertRaises(ToolError) as conflict:
            other.call("channel_import", {"archivePath": str(import_path), "taskId": "task_import"})
        self.assertEqual(conflict.exception.code, "IMPORT_IDENTITY_CONFLICT")

        self.service.call(
            "channel_update_defaults",
            {
                "taskId": "task_fixture_001",
                "channelProfileId": channel_id,
                "bindingProof": proof,
                "defaults": defaults(preferred_characters=14000),
                "confirmation": {"confirmed": True, "scope": "channel_default"},
            },
        )
        os.environ["AIVCP_TEST_FAIL_RESTORE"] = "1"
        with self.assertRaises(ToolError) as restore_error:
            self.service.call(
                "channel_restore",
                {
                    "archivePath": backup["archivePath"],
                    "mode": "replace",
                    "confirmation": "RESTORE_CHANNEL_FROM_BACKUP",
                    "taskId": "task_fixture_001",
                    "bindingProof": proof,
                },
            )
        self.assertEqual(restore_error.exception.code, "RESTORE_INTEGRITY_FAILED")
        current = self.service.call("channel_get", {"channelProfileId": channel_id})
        self.assertEqual(current["productionProfile"]["presetVersion"], "1.1.0")

    def test_channel_schema_upgrade_backup_and_failure_rollback(self) -> None:
        completed, _ = self.onboard()
        channel_id = completed["channelProfileId"]
        database = self.root / "data" / "channels" / channel_id / "channel.db"
        with closing(sqlite3.connect(database)) as connection:
            connection.execute("PRAGMA user_version=0")
        os.environ["AIVCP_TEST_FAIL_MIGRATION"] = "channel"
        with self.assertRaises(ToolError) as failure:
            self.service.call("channel_get", {"channelProfileId": channel_id})
        self.assertEqual(failure.exception.code, "DATABASE_MIGRATION_FAILED")
        with closing(sqlite3.connect(database)) as connection:
            self.assertEqual(connection.execute("PRAGMA user_version").fetchone()[0], 0)
        os.environ.pop("AIVCP_TEST_FAIL_MIGRATION")
        recovered = self.service.call("channel_get", {"channelProfileId": channel_id})
        self.assertEqual(recovered["lifecycleStatus"], "READY")
        with closing(sqlite3.connect(database)) as connection:
            self.assertEqual(connection.execute("PRAGMA user_version").fetchone()[0], 1)
        self.assertGreaterEqual(len(list((self.root / "data" / "backups" / "upgrade").glob("*.db"))), 2)

    def test_fixture_provider_rejects_sensitive_fields(self) -> None:
        fixture = self.root / "unsafe.json"
        unsafe = synthetic_channel()
        unsafe["accessToken"] = "ya29.fixture-secret-value"
        fixture.write_text(json.dumps({"channels": [unsafe]}), encoding="utf-8")
        provider = FixturePublisherProvider(fixture)
        with self.assertRaises(ToolError) as error:
            provider.list_channels()
        self.assertEqual(error.exception.code, "PUBLISHER_RESPONSE_UNSAFE")

    def test_command_publisher_interface_and_no_channel_boundary(self) -> None:
        provider = CommandPublisherProvider(
            (sys.executable, str(ROOT / "tests" / "fixtures" / "publisher_interface_stub.py")),
            timeout_seconds=2,
        )
        channels = provider.list_channels()
        self.assertEqual(channels[0]["youtubeChannelId"], "UCFIXTURECHANNEL0001")
        empty_service = LocalToolService(
            ServiceConfig(data_root=self.root / "empty-data", voice_catalog_path=self.service.config.voice_catalog_path),
            publisher_provider=StaticPublisherProvider([]),
        )
        self.assertEqual(empty_service.call("publisher_list_channels")["channels"], [])
        with self.assertRaises(ToolError) as error:
            empty_service.call(
                "channel_onboarding_start",
                {
                    "taskId": "task_empty",
                    "channelSerial": "01",
                    "targetRegion": "Japan",
                    "outputLanguage": "ja-JP",
                },
            )
        self.assertEqual(error.exception.code, "PUBLISHER_CHANNEL_NOT_FOUND")

    def test_real_publisher_center_cli_v1_adapter_is_read_only(self) -> None:
        configured = os.environ.get("AIVCP_TEST_PUBLISHER_CLI_EXE")
        if not configured:
            self.skipTest("formal publisher-center CLI is not available in this environment")
        executable = Path(configured)
        self.assertTrue(executable.is_file())
        database = self.root / "publisher-center-fixture.db"
        create_publisher_cli_fixture(database)
        before = file_sha256(database)
        provider = PublisherCenterCliV1Provider(
            (str(executable), "--database", str(database)), timeout_seconds=3
        )
        channels = provider.list_channels()
        self.assertEqual(file_sha256(database), before)
        self.assertEqual(
            channels,
            [
                {
                    "publisherProfileId": "publisher_fixture_001",
                    "channelSerial": "01",
                    "youtubeChannelId": "UCFIXTURECHANNEL0001",
                    "displayName": "Fixture Channel",
                    "enabled": True,
                    "authorizationStatus": "ACTIVE",
                    "privacyStatus": "private",
                    "timeZone": "Asia/Tokyo",
                    "uploadPolicy": "REQUIRE_REVIEW",
                    "interfaceVersion": "youtube-publisher-center/channel-list/v1",
                }
            ],
        )
        missing = PublisherCenterCliV1Provider(
            (str(executable), "--database", str(self.root / "missing.db")), timeout_seconds=3
        )
        with self.assertRaises(ToolError) as error:
            missing.list_channels()
        self.assertEqual(error.exception.code, "PUBLISHER_DATABASE_NOT_FOUND")
        self.assertFalse(error.exception.retryable)

    def test_publisher_interface_discovery_file_prefers_formal_cli(self) -> None:
        configured = os.environ.get("AIVCP_TEST_PUBLISHER_CLI_EXE")
        if not configured:
            self.skipTest("formal publisher-center CLI is not available in this environment")
        data_root = self.root / "discovery" / "data"
        config_root = data_root.parent / "config"
        config_root.mkdir(parents=True)
        database = self.root / "publisher-center-discovery.db"
        create_publisher_cli_fixture(database)
        (config_root / "publisher-interface.json").write_text(
            json.dumps(
                {
                    "schemaVersion": "1.0.0",
                    "apiVersion": "youtube-publisher-center/channel-list/v1",
                    "command": [configured, "--database", str(database)],
                }
            ),
            encoding="utf-8",
        )
        provider = provider_from_environment(data_root)
        self.assertIsInstance(provider, PublisherCenterCliV1Provider)
        self.assertEqual(provider.list_channels()[0]["displayName"], "Fixture Channel")

    def test_publisher_timeout_and_diagnostics_are_sanitized(self) -> None:
        failing = CommandPublisherProvider(
            (
                sys.executable,
                "-c",
                "import sys;sys.stderr.write('Bearer canary-private-value');sys.exit(3)",
            ),
            timeout_seconds=1,
        )
        with self.assertRaises(ToolError) as failed:
            failing.list_channels()
        diagnostic = failed.exception.details["diagnostic"]
        self.assertNotIn("canary-private-value", diagnostic)
        self.assertIn("[REDACTED]", diagnostic)

        timed = CommandPublisherProvider(
            (sys.executable, "-c", "import time;time.sleep(1)"), timeout_seconds=0.05
        )
        with self.assertRaises(ToolError) as timeout:
            timed.list_channels()
        self.assertEqual(timeout.exception.code, "PUBLISHER_TIMEOUT")

    def test_restart_and_new_task_rebind_preserve_profiles(self) -> None:
        completed, _ = self.onboard()
        channel_id = completed["channelProfileId"]
        restarted = LocalToolService(
            ServiceConfig(data_root=self.root / "data", voice_catalog_path=self.service.config.voice_catalog_path),
            publisher_provider=StaticPublisherProvider(),
        )
        rebound = restarted.call(
            "channel_bind_task", {"taskId": "task_after_restart", "channelProfileId": channel_id}
        )
        resolved = restarted.call(
            "channel_resolve_production",
            {
                "taskId": "task_after_restart",
                "channelProfileId": channel_id,
                "bindingProof": rebound["bindingProof"],
            },
        )
        self.assertEqual(resolved["productionProfile"]["contentHash"], completed["productionProfile"]["contentHash"])
        self.assertEqual(restarted.call("channel_integrity_check")["status"], "PASS")

    def test_unknown_voice_and_stage2_auto_upload_are_blocked(self) -> None:
        started = self.service.call(
            "channel_onboarding_start",
            {
                "taskId": "task_voice_guard",
                "channelSerial": "01",
                "targetRegion": "Japan",
                "outputLanguage": "ja-JP",
            },
        )
        bad_voice = defaults()
        bad_voice["voice"] = {"engineId": "invented-engine", "voiceId": "invented-voice"}
        with self.assertRaises(ToolError) as voice_error:
            self.service.call(
                "channel_onboarding_complete",
                {
                    "taskId": "task_voice_guard",
                    "channelProfileId": started["channel"]["channelProfileId"],
                    "bindingProof": started["taskBinding"]["bindingProof"],
                    "defaults": bad_voice,
                },
            )
        self.assertEqual(voice_error.exception.code, "VOICE_SELECTION_NOT_FOUND")
        automatic = defaults()
        automatic["uploadPolicy"] = "AUTO"
        with self.assertRaises(ToolError) as upload_error:
            self.service.call(
                "channel_onboarding_complete",
                {
                    "taskId": "task_voice_guard",
                    "channelProfileId": started["channel"]["channelProfileId"],
                    "bindingProof": started["taskBinding"]["bindingProof"],
                    "defaults": automatic,
                },
            )
        self.assertEqual(upload_error.exception.code, "AUTO_UPLOAD_NOT_AVAILABLE_STAGE2")

    def test_mcp_protocol_returns_structured_sanitized_tools(self) -> None:
        server = McpServer(self.service)
        initialized = server.handle({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
        self.assertEqual(initialized["result"]["protocolVersion"], "2025-06-18")
        listed = server.handle({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
        names = {tool["name"] for tool in listed["result"]["tools"]}
        self.assertIn("channel_onboarding_start", names)
        self.assertIn("channel_restore", names)
        missing = server.handle(
            {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {"name": "does_not_exist", "arguments": {}},
            }
        )
        self.assertTrue(missing["result"]["isError"])
        self.assertEqual(missing["result"]["structuredContent"]["error"]["code"], "TOOL_NOT_FOUND")


class SystemMigrationTestCase(unittest.TestCase):
    def test_newer_database_is_read_protected(self) -> None:
        with tempfile.TemporaryDirectory(prefix="aivcp-stage2-newer-") as name:
            root = Path(name)
            root.mkdir(parents=True, exist_ok=True)
            with closing(sqlite3.connect(root / "system.db")) as connection:
                connection.execute("PRAGMA user_version=99")
            with self.assertRaises(ToolError) as error:
                ChannelStore(root)
            self.assertEqual(error.exception.code, "MIGRATION_REQUIRED")


if __name__ == "__main__":
    unittest.main()
