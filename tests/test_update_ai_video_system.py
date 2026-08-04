from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import unittest
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "plugins/ai-video-channel-production/skills/update-ai-video-system"
SCRIPT = SKILL / "scripts/Update-AIVideoSystem.ps1"
POWERSHELL = shutil.which("powershell") or "powershell"


@unittest.skipUnless(os.name == "nt" and shutil.which("powershell"), "Windows PowerShell 5.1 is required")
class UpdateAiVideoSystemSkillTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="aivcp-update-skill-")
        self.base = Path(self.temporary.name)
        self.install = self.base / "Unicode 程序目录"
        self.data = self.base / "用户数据"
        self.assets = self.base / "release assets"
        self.record = self.base / "installer-invocation.json"
        self.assets.mkdir(parents=True)
        self.data.mkdir(parents=True)
        (self.data / "sentinel.txt").write_text("user-data-unchanged", encoding="utf-8")
        self._write_installed_version("1.0.0")

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _write_installed_version(self, version: str) -> None:
        marker = {
            "schemaVersion": "2.0.0",
            "productId": "ai-video-channel-production",
            "activeVersion": version,
            "activeRoot": "current",
            "userDataRoot": str(self.data),
        }
        state = {
            "schemaVersion": "2.0.0",
            "productId": "ai-video-channel-production",
            "productVersion": version,
            "userDataRoot": str(self.data),
        }
        (self.install / "current").mkdir(parents=True, exist_ok=True)
        (self.install / "installation.json").write_text(json.dumps(marker), encoding="utf-8")
        (self.install / "current/install-state.json").write_text(json.dumps(state), encoding="utf-8")

    def _build_release(
        self,
        version: str,
        *,
        prerelease: bool,
        corrupt_hash: bool = False,
        bad_manifest: bool = False,
    ) -> dict[str, object]:
        archive_root = f"AI-Video-Channel-Production-Unified-Installer-v{version}"
        installer_name = f"AI-Video-Channel-Production-Unified-Installer-v{version}.zip"
        installer_path = self.assets / installer_name
        fake_installer = r'''
[CmdletBinding()]
param(
    [string]$ManifestPath,
    [string]$AssetRoot,
    [string]$DownloadBaseUrl,
    [string]$InstallMode,
    [string]$InstallRoot,
    [switch]$Force,
    [string]$LocatorOperation
)
$record = [ordered]@{
    manifestPath = $ManifestPath
    assetRoot = $AssetRoot
    downloadBaseUrl = $DownloadBaseUrl
    installMode = $InstallMode
    installRoot = $InstallRoot
    force = [bool]$Force
    locatorOperation = $LocatorOperation
}
$record | ConvertTo-Json | Set-Content -LiteralPath $env:AIVCP_TEST_INSTALL_RECORD -Encoding UTF8
'''.lstrip()
        with zipfile.ZipFile(installer_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr(f"{archive_root}/Install-AIVideoChannelProduction.ps1", fake_installer)
        archive_bytes = installer_path.read_bytes()
        archive_hash = hashlib.sha256(archive_bytes).hexdigest()
        if corrupt_hash:
            archive_hash = "0" * 64
        manifest_name = f"unified-release-v{version}.json"
        manifest_path = self.assets / manifest_name
        if bad_manifest:
            manifest_path.write_text("{broken", encoding="utf-8")
        else:
            manifest = {
                "schemaVersion": "2.0.0",
                "productId": "ai-video-channel-production",
                "productVersion": version,
                "releaseStatus": "candidate" if prerelease else "stable",
                "hashAlgorithm": "SHA-256",
                "downloadBaseUrl": "https://github.com/coisu772-code/AI-/releases/download/v" + version,
                "safetyBoundaries": {"userDataIncluded": False, "credentialsIncluded": False},
                "assets": [
                    {
                        "assetId": "unified-installer",
                        "fileName": installer_name,
                        "sizeBytes": len(archive_bytes),
                        "sha256": archive_hash,
                        "version": version,
                        "compatibleProductVersions": [version],
                        "install": False,
                        "archiveRoot": archive_root,
                    }
                ],
            }
            manifest_path.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
        return {
            "tag_name": "v" + version,
            "name": "v" + version,
            "body": f"Changes for {version}",
            "html_url": f"https://github.com/coisu772-code/AI-/releases/tag/v{version}",
            "draft": False,
            "prerelease": prerelease,
            "assets": [
                {"name": manifest_name, "size": manifest_path.stat().st_size, "browser_download_url": manifest_path.as_uri()},
                {"name": installer_name, "size": installer_path.stat().st_size, "browser_download_url": installer_path.as_uri()},
            ],
        }

    def _write_catalog(self, releases: list[dict[str, object]]) -> None:
        (self.base / "releases.json").write_text(json.dumps(releases, ensure_ascii=False), encoding="utf-8")

    def _run(self, *arguments: str, expect_success: bool = True) -> subprocess.CompletedProcess[str]:
        environment = os.environ.copy()
        environment["AIVCP_TEST_INSTALL_RECORD"] = str(self.record)
        command = [
            POWERSHELL,
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(SCRIPT),
            "-InstallRoot",
            str(self.install),
            "-ReleaseFixturePath",
            str(self.base / "releases.json"),
            "-AllowLocalFixture",
            *arguments,
        ]
        completed = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", env=environment, timeout=30)
        if expect_success:
            self.assertEqual(0, completed.returncode, completed.stderr)
        else:
            self.assertNotEqual(0, completed.returncode, completed.stdout)
        return completed

    @staticmethod
    def _json(completed: subprocess.CompletedProcess[str]) -> dict[str, object]:
        return json.loads(completed.stdout.lstrip("\ufeff"))

    def test_skill_is_discoverable_and_contains_all_trigger_phrases(self) -> None:
        text = (SKILL / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("name: update-ai-video-system", text)
        for phrase in ("检查更新", "更新到最新版", "更新AI视频频道生产系统"):
            self.assertIn(phrase, text)
        plugin = json.loads((ROOT / "plugins/ai-video-channel-production/.codex-plugin/plugin.json").read_text(encoding="utf-8"))
        self.assertEqual("./skills/", plugin["skills"])

    def test_read_only_check_finds_stable_update_without_touching_user_data(self) -> None:
        self._write_catalog([self._build_release("1.1.0", prerelease=False)])
        before_install = (self.install / "installation.json").read_bytes()
        before_data = (self.data / "sentinel.txt").read_bytes()
        result = self._json(self._run("-Action", "Check", "-Channel", "stable"))
        self.assertEqual("UPDATE_AVAILABLE", result["status"])
        self.assertEqual("1.0.0", result["currentVersion"])
        self.assertEqual("1.1.0", result["targetVersion"])
        self.assertTrue(result["confirmationRequired"])
        self.assertEqual(before_install, (self.install / "installation.json").read_bytes())
        self.assertEqual(before_data, (self.data / "sentinel.txt").read_bytes())
        self.assertFalse(self.record.exists())

    def test_no_update(self) -> None:
        self._write_catalog([self._build_release("1.0.0", prerelease=False)])
        result = self._json(self._run("-Action", "Check"))
        self.assertEqual("NO_UPDATE", result["status"])
        self.assertFalse(result["confirmationRequired"])

    def test_stable_and_prerelease_channels_are_separate(self) -> None:
        self._write_catalog([
            self._build_release("1.1.0", prerelease=False),
            self._build_release("1.2.0-rc.1", prerelease=True),
        ])
        stable = self._json(self._run("-Action", "Check", "-Channel", "stable"))
        preview = self._json(self._run("-Action", "Check", "-Channel", "prerelease"))
        self.assertEqual("1.1.0", stable["targetVersion"])
        self.assertEqual("1.2.0-rc.1", preview["targetVersion"])

    def test_bad_manifest_is_rejected(self) -> None:
        self._write_catalog([self._build_release("1.1.0", prerelease=False, bad_manifest=True)])
        completed = self._run("-Action", "Check", expect_success=False)
        self.assertIn("manifest", completed.stderr.lower())
        self.assertFalse(self.record.exists())

    def test_unconfirmed_update_is_rejected_before_execution(self) -> None:
        self._write_catalog([self._build_release("1.1.0", prerelease=False)])
        completed = self._run("-Action", "Update", "-ExpectedVersion", "1.1.0", expect_success=False)
        self.assertIn("UPDATE_CONFIRMATION_REQUIRED", completed.stderr)
        self.assertFalse(self.record.exists())

    def test_hash_mismatch_is_rejected_before_installer_execution(self) -> None:
        self._write_catalog([self._build_release("1.1.0", prerelease=False, corrupt_hash=True)])
        completed = self._run("-Action", "Update", "-ExpectedVersion", "1.1.0", "-ConfirmUpdate", expect_success=False)
        self.assertIn("SHA-256 mismatch", completed.stderr)
        self.assertFalse(self.record.exists())

    def test_confirmed_update_invokes_existing_installer_and_only_requests_restart(self) -> None:
        self._write_catalog([self._build_release("1.1.0", prerelease=False)])
        before_data = (self.data / "sentinel.txt").read_bytes()
        result = self._json(self._run("-Action", "Update", "-ExpectedVersion", "1.1.0", "-ConfirmUpdate"))
        self.assertEqual("UPDATED", result["status"])
        self.assertTrue(result["installerInvoked"])
        self.assertTrue(result["restartRequired"])
        self.assertEqual("Restart Codex and create a new task.", result["nextStep"])
        invocation = json.loads(self.record.read_text(encoding="utf-8-sig"))
        self.assertEqual(str(self.install), invocation["installRoot"])
        self.assertEqual("Auto", invocation["installMode"])
        self.assertEqual("upgrade", invocation["locatorOperation"])
        self.assertTrue(invocation["force"])
        self.assertEqual(before_data, (self.data / "sentinel.txt").read_bytes())


if __name__ == "__main__":
    unittest.main()
