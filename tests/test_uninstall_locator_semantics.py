from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
UNINSTALL = ROOT / "installer/Uninstall-AIVideoChannelProduction.ps1"


@unittest.skipUnless(os.name == "nt" and shutil.which("powershell"), "Windows PowerShell integration requires Windows")
class UninstallRuntimeLocatorSemanticsTests(unittest.TestCase):
    def make_installation(self, base: Path) -> tuple[Path, Path, Path, bytes]:
        local_app_data = base / "Local App Data"
        install_root = local_app_data / "AIVCP Custom"
        data_root = base / "Existing User Data"
        locator_path = local_app_data / "AIVCP-Config" / "runtime-locator.json"
        install_root.mkdir(parents=True)
        data_root.mkdir(parents=True)
        locator_path.parent.mkdir(parents=True)
        (install_root / "payload.txt").write_text("program payload\n", encoding="utf-8")
        (data_root / "do-not-delete.txt").write_text("preserve me\n", encoding="utf-8")
        (install_root / "installation.json").write_text(
            json.dumps(
                {
                    "schemaVersion": "2.0.0",
                    "productId": "ai-video-channel-production",
                    "productVersion": "0.8.0-rc.2",
                    "activeVersion": "0.8.0-rc.2",
                    "activeRoot": "current",
                    "userDataRoot": str(data_root),
                    "releaseManifestSha256": "0" * 64,
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        locator_bytes = (
            json.dumps(
                {
                    "schemaVersion": "1.0.0",
                    "productId": "ai-video-channel-production",
                    "productVersion": "0.8.0-rc.2",
                    "installRoot": str(install_root),
                    "activeRoot": "current",
                    "pythonRelativePath": "runtime/python/python.exe",
                    "userDataRoot": str(data_root),
                    "updatedAt": "2026-08-04T00:00:00.0000000Z",
                },
                indent=2,
            )
            + "\n"
        ).encode("utf-8")
        locator_path.write_bytes(locator_bytes)
        return local_app_data, install_root, data_root, locator_bytes

    def environment(self, local_app_data: Path) -> dict[str, str]:
        environment = os.environ.copy()
        environment["LOCALAPPDATA"] = str(local_app_data)
        environment["AIVCP_DISABLE_CODEX_AUTO_REGISTRATION"] = "1"
        return environment

    def test_whatif_preserves_program_data_and_locator_bytes(self) -> None:
        with tempfile.TemporaryDirectory(prefix="aivcp-uninstall-whatif-") as temporary:
            local_app_data, install_root, data_root, locator_bytes = self.make_installation(Path(temporary))
            locator_path = local_app_data / "AIVCP-Config" / "runtime-locator.json"
            completed = subprocess.run(
                [
                    shutil.which("powershell") or "powershell",
                    "-NoProfile",
                    "-NonInteractive",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-File",
                    str(UNINSTALL),
                    "-InstallRoot",
                    str(install_root),
                    "-SkipCodexRemoval",
                    "-WhatIf",
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                env=self.environment(local_app_data),
            )
            self.assertEqual(0, completed.returncode, completed.stderr)
            self.assertTrue(install_root.is_dir())
            self.assertTrue((data_root / "do-not-delete.txt").is_file())
            self.assertEqual(locator_bytes, locator_path.read_bytes())

    def test_program_delete_failure_does_not_remove_locator(self) -> None:
        with tempfile.TemporaryDirectory(prefix="aivcp-uninstall-failure-") as temporary:
            local_app_data, install_root, data_root, locator_bytes = self.make_installation(Path(temporary))
            locator_path = local_app_data / "AIVCP-Config" / "runtime-locator.json"
            wrapper = Path(temporary) / "invoke-delete-failure.ps1"
            wrapper.write_text(
                """
param([string]$UninstallScript, [string]$InstallRoot)
$ErrorActionPreference = "Stop"
function Remove-Item {
    [CmdletBinding()]
    param(
        [string]$LiteralPath,
        [switch]$Recurse,
        [switch]$Force
    )
    if ([System.IO.Path]::GetFullPath($LiteralPath).Equals([System.IO.Path]::GetFullPath($env:AIVCP_FAIL_DELETE_ROOT), [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "TEST_PROGRAM_DELETE_FAILURE"
    }
    Microsoft.PowerShell.Management\\Remove-Item -LiteralPath $LiteralPath -Recurse:$Recurse -Force:$Force -ErrorAction Stop
}
try {
    & $UninstallScript -InstallRoot $InstallRoot -SkipCodexRemoval -Confirm:$false
    throw "Expected the injected program deletion failure."
}
catch {
    if ($_.Exception.Message -notmatch "TEST_PROGRAM_DELETE_FAILURE") { throw }
}
""".lstrip(),
                encoding="utf-8",
            )
            environment = self.environment(local_app_data)
            environment["AIVCP_FAIL_DELETE_ROOT"] = str(install_root)
            completed = subprocess.run(
                [
                    shutil.which("powershell") or "powershell",
                    "-NoProfile",
                    "-NonInteractive",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-File",
                    str(wrapper),
                    "-UninstallScript",
                    str(UNINSTALL),
                    "-InstallRoot",
                    str(install_root),
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                env=environment,
            )
            self.assertEqual(0, completed.returncode, completed.stderr)
            self.assertTrue(install_root.is_dir())
            self.assertTrue((data_root / "do-not-delete.txt").is_file())
            self.assertEqual(locator_bytes, locator_path.read_bytes())


if __name__ == "__main__":
    unittest.main()
