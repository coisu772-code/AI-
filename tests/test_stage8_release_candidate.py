from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MCP_ROOT = ROOT / "plugins" / "ai-video-channel-production" / "mcp"
TOOLS_ROOT = ROOT / "tools"
sys.path.insert(0, str(MCP_ROOT))
sys.path.insert(0, str(TOOLS_ROOT))

from aivcp_tools.service import default_data_root  # noqa: E402
from build_release_candidate import build  # noqa: E402
from scan_release_candidate import scan  # noqa: E402


class Stage8ReleaseCandidateTests(unittest.TestCase):
    def test_version_identity_and_machine_readable_approval_gates(self) -> None:
        plugin = json.loads((ROOT / "plugins/ai-video-channel-production/.codex-plugin/plugin.json").read_text(encoding="utf-8"))
        release = json.loads((ROOT / "release-manifests/release-v0.8.0-rc.1.json").read_text(encoding="utf-8"))
        index = json.loads((ROOT / "release-manifests/version-index.json").read_text(encoding="utf-8"))
        approvals = json.loads((ROOT / "docs/final-acceptance-approval-checklist-v0.8.0-rc.1.json").read_text(encoding="utf-8"))
        self.assertEqual("0.8.0-rc.1", plugin["version"])
        self.assertEqual(plugin["version"], release["productVersion"])
        self.assertEqual("AI 视频频道生产系统", release["productName"])
        self.assertEqual("draft", release["releaseStatus"])
        self.assertIsNone(release["gitCommit"])
        self.assertEqual("0.8.0-rc.1", index["currentReleaseCandidate"])
        self.assertFalse(next(item for item in index["versions"] if item["version"] == "0.8.0-rc.1")["remotePublished"])
        self.assertEqual("AUTH_REQUIRED", approvals["overallStatus"])
        self.assertFalse(approvals["operationsExecutedByStage8"])
        self.assertEqual(6, len(approvals["gates"]))
        self.assertTrue(all(gate["executed"] is False for gate in approvals["gates"]))
        self.assertIn("real-youtube-upload", {gate["id"] for gate in approvals["gates"]})

    def test_installed_state_routes_user_data_outside_active_program(self) -> None:
        with tempfile.TemporaryDirectory(prefix="aivcp-stage8-data-root-") as temporary:
            base = Path(temporary)
            current = base / "program" / "current"
            plugin_root = current / "plugins" / "ai-video-channel-production"
            plugin_root.mkdir(parents=True)
            expected = base / "用户 数据 with spaces"
            (current / "install-state.json").write_text(
                json.dumps({"schemaVersion": "1.1.0", "productId": "ai-video-channel-production", "userDataRoot": str(expected)}),
                encoding="utf-8",
            )
            self.assertEqual(expected.resolve(), default_data_root(plugin_root))
            self.assertNotIn(current.resolve(), expected.resolve().parents)

    def test_lifecycle_entries_and_offline_online_runtime_strategy_are_shipped(self) -> None:
        required = {
            "Install-AIVideoChannelProduction.ps1",
            "Upgrade-AIVideoChannelProduction.ps1",
            "Repair-AIVideoChannelProduction.ps1",
            "Rollback-AIVideoChannelProduction.ps1",
            "Uninstall-AIVideoChannelProduction.ps1",
            "Backup-AIVideoChannelProductionData.ps1",
            "Restore-AIVideoChannelProductionData.ps1",
            "Test-AIVideoChannelProductionHealth.ps1",
            "Build-OfflineWheelhouse.ps1",
            "runtime-requirements.txt",
        }
        self.assertTrue(required.issubset({path.name for path in (ROOT / "installer").iterdir()}))
        install_text = (ROOT / "installer/Install-AIVideoChannelProduction.ps1").read_text(encoding="utf-8")
        self.assertIn('ValidateSet("Existing", "Online", "Offline")', install_text)
        self.assertIn("TEST_FAILURE_INJECTION:AfterSwitch", install_text)
        uninstall_text = (ROOT / "installer/Uninstall-AIVideoChannelProduction.ps1").read_text(encoding="utf-8")
        self.assertIn("PROGRAM_UNINSTALLED_USER_DATA_PRESERVED", uninstall_text)

    def test_release_candidate_zip_is_reproducible_and_safe(self) -> None:
        with tempfile.TemporaryDirectory(prefix="aivcp-stage8-build-") as temporary:
            base = Path(temporary)
            first = build(base / "first")
            second = build(base / "second")
            self.assertEqual(first["archiveSha256"], second["archiveSha256"])
            archive = Path(first["archivePath"])
            self.assertEqual(first["archiveSha256"], hashlib.sha256(archive.read_bytes()).hexdigest())
            result = scan(archive)
            self.assertEqual("PASS", result["status"], result["errors"])
            self.assertFalse(result["boundaries"]["credentialsPresent"])
            self.assertFalse(result["boundaries"]["userDataPresent"])
            self.assertFalse(result["boundaries"]["executablesPresent"])


if __name__ == "__main__":
    unittest.main()
