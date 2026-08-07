from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
COMMON = ROOT / "installer/Common.ps1"
ROLLBACK = ROOT / "installer/Rollback-AIVideoChannelProduction.ps1"
RESTORE = ROOT / "installer/Restore-AIVideoChannelProductionData.ps1"
HEALTH = ROOT / "installer/Test-AIVideoChannelProductionHealth.ps1"
START_INSTALLER = ROOT / "installer/Start-AIVideoChannelProductionInstall.ps1"
PLUGIN = ROOT / "plugins/ai-video-channel-production"
POWERSHELL = shutil.which("powershell") or "powershell"


def write_json(path: Path, value: object) -> bytes:
    payload = (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return payload


@unittest.skipUnless(os.name == "nt" and shutil.which("powershell"), "Windows PowerShell integration requires Windows")
class InstallerSafetyTransactionTests(unittest.TestCase):
    def test_runtime_descriptor_binds_portable_youtube_collector_without_path_lookup(self) -> None:
        with tempfile.TemporaryDirectory(prefix="aivcp-portable-youtube-binding-") as temporary:
            base = Path(temporary)
            local = base / "Local App Data"
            install = base / "Program Root"
            current = install / "current"
            plugin = current / "plugins/ai-video-channel-production"
            data = base / "User Data"
            (data / "workshop-isolation").mkdir(parents=True)
            write_json(plugin / ".codex-plugin/plugin.json", {"name": "ai-video-channel-production", "version": "0.10.1-rc.1"})
            write_json(plugin / "assets/voice-catalog.json", {"schemaVersion": "1.0.0", "engines": [{"engineId": "fixture"}]})
            (plugin / "assets").mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT / "plugins/ai-video-channel-production/assets/portable-youtube-runtime.json", plugin / "assets/portable-youtube-runtime.json")
            required = (
                current / "runtime/python/python.exe",
                current / "runtime/python/Lib/site-packages/yt_dlp/__init__.py",
                current / "runtime/python/Lib/site-packages/yt_dlp_ejs/__init__.py",
                current / "runtime/python/tools/deno.exe",
                current / "apps/workshop/Workshop.exe",
                current / "apps/workshop/tools/ffmpeg/bin/ffmpeg.exe",
                current / "apps/workshop/tools/ffmpeg/bin/ffprobe.exe",
                current / "apps/publisher/channel-list.exe",
                current / "apps/publisher/publish-package-v2.exe",
            )
            for path in required:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b"fixture")
            wrapper = base / "bind.ps1"
            wrapper.write_text(
                f'''
. "{COMMON}"
Write-AivcpRuntimeBoundMcpDescriptor -PluginRoot "{plugin}" -InstallRoot "{install}" -DataRoot "{data}" -ProductVersion "0.10.1-rc.1" -ReleaseManifestSha256 "{'a' * 64}" -ComponentVerificationRoot "{current}" | Write-Output
'''.lstrip(),
                encoding="utf-8-sig",
            )
            environment = os.environ.copy()
            environment["LOCALAPPDATA"] = str(local)
            completed = subprocess.run(
                [POWERSHELL, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(wrapper)],
                capture_output=True,
                text=True,
                encoding="utf-8",
                env=environment,
            )
            self.assertEqual(0, completed.returncode, completed.stderr)
            descriptor = json.loads((plugin / ".mcp.json").read_text(encoding="utf-8-sig"))
            command = json.loads(descriptor["mcpServers"]["ai-video-channel-tools"]["env"]["AIVCP_YT_DLP_COMMAND_JSON"])
            self.assertEqual(str((current / "runtime/python/python.exe").resolve()), command[0])
            self.assertEqual(["-m", "yt_dlp"], command[1:3])
            self.assertEqual("--js-runtimes", command[3])
            self.assertEqual("deno:" + str((current / "runtime/python/tools/deno.exe").resolve()), command[4])
            self.assertEqual("--ffmpeg-location", command[5])
            self.assertEqual(str((current / "apps/workshop/tools/ffmpeg/bin").resolve()), command[6])

            (current / "runtime/python/tools/deno.exe").unlink()
            missing = subprocess.run(
                [POWERSHELL, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(wrapper)],
                capture_output=True,
                text=True,
                encoding="utf-8",
                env=environment,
            )
            self.assertNotEqual(0, missing.returncode)
            self.assertIn("youtubeJavascriptRuntime", missing.stderr)

    def test_fresh_noninteractive_install_requires_explicit_data_root(self) -> None:
        with tempfile.TemporaryDirectory(prefix="aivcp-data-root-required-") as temporary:
            completed = subprocess.run(
                [
                    POWERSHELL,
                    "-NoProfile",
                    "-NonInteractive",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-File",
                    str(START_INSTALLER),
                    "-NonInteractive",
                    "-InstallRoot",
                    str(Path(temporary) / "Program"),
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=15,
            )
            self.assertNotEqual(0, completed.returncode)
            self.assertIn("requires -DataRoot", completed.stderr)

    def test_existing_install_rejects_silent_data_root_rebind(self) -> None:
        with tempfile.TemporaryDirectory(prefix="aivcp-data-root-rebind-") as temporary:
            base = Path(temporary)
            install = base / "Program"
            original_data = base / "Original Data"
            requested_data = base / "Other Data"
            write_json(install / "installation.json", {"userDataRoot": str(original_data)})
            completed = subprocess.run(
                [
                    POWERSHELL,
                    "-NoProfile",
                    "-NonInteractive",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-File",
                    str(START_INSTALLER),
                    "-NonInteractive",
                    "-InstallRoot",
                    str(install),
                    "-DataRoot",
                    str(requested_data),
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=15,
            )
            self.assertNotEqual(0, completed.returncode)
            self.assertIn("instead of silently rebinding", completed.stderr)

    def test_global_operation_mutex_rejects_concurrent_mutator(self) -> None:
        with tempfile.TemporaryDirectory(prefix="aivcp-lock-") as temporary:
            base = Path(temporary)
            holder_script = base / "holder.ps1"
            contender_script = base / "contender.ps1"
            holder_script.write_text(
                f'. "{COMMON}"\n$lock = Enter-AivcpOperationLock -TimeoutSeconds 1\nWrite-Output "READY"\nStart-Sleep -Seconds 15\nExit-AivcpOperationLock $lock\n',
                encoding="utf-8-sig",
            )
            contender_script.write_text(
                f'. "{COMMON}"\ntry {{ $lock = Enter-AivcpOperationLock -TimeoutSeconds 0; Exit-AivcpOperationLock $lock; exit 2 }} catch {{ Write-Error $_.Exception.Message; exit 0 }}\n',
                encoding="utf-8-sig",
            )
            holder = subprocess.Popen(
                [POWERSHELL, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(holder_script)],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8-sig",
            )
            try:
                deadline = time.monotonic() + 5
                ready = ""
                while time.monotonic() < deadline and "READY" not in ready:
                    ready += holder.stdout.readline() if holder.stdout else ""
                self.assertIn("READY", ready)
                contender = subprocess.run(
                    [POWERSHELL, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(contender_script)],
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    timeout=10,
                )
                self.assertEqual(0, contender.returncode, contender.stderr)
                self.assertIn("already running", contender.stderr)
            finally:
                holder.terminate()
                try:
                    holder.communicate(timeout=5)
                except subprocess.TimeoutExpired:
                    holder.kill()
                    holder.communicate(timeout=5)

    def test_overlong_archive_target_is_rejected_before_extraction(self) -> None:
        with tempfile.TemporaryDirectory(prefix="aivcp-path-budget-") as temporary:
            base = Path(temporary)
            archive = base / "asset.zip"
            with zipfile.ZipFile(archive, "w") as handle:
                handle.writestr("root/payload.txt", "safe")
            wrapper = base / "path-budget.ps1"
            wrapper.write_text(
                f'''
. "{COMMON}"
$tooLong = "C:\\" + ("x" * 245)
try {{
    Assert-AivcpArchivePathBudget -ArchivePath "{archive}" -ExpectedRoot "root" -ExtractionRoot "$tooLong" -StagedInstallRoot "C:\\AIVCP\\.s-12345678" -ActiveInstallRoot "C:\\AIVCP\\current" -AssetId "test"
    exit 2
}}
catch {{
    if ($_.Exception.Message -notmatch "Install path budget exceeded before extraction") {{ throw }}
}}
'''.lstrip(),
                encoding="utf-8-sig",
            )
            completed = subprocess.run(
                [POWERSHELL, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(wrapper)],
                capture_output=True,
                text=True,
                encoding="utf-8",
            )
            self.assertEqual(0, completed.returncode, completed.stderr)

    def test_zip_extraction_strips_upstream_archive_root(self) -> None:
        with tempfile.TemporaryDirectory(prefix="aivcp-strip-zip-root-") as temporary:
            base = Path(temporary)
            archive = base / "asset.zip"
            destination = base / "short" / "x" / "0"
            with zipfile.ZipFile(archive, "w") as handle:
                handle.writestr("very-long-upstream-product-archive-root/payload/nested.txt", "safe")
            wrapper = base / "strip-root.ps1"
            wrapper.write_text(
                f'''
. "{COMMON}"
$expanded = Expand-AivcpVerifiedZip -ArchivePath "{archive}" -DestinationPath "{destination}" -ExpectedRoot "very-long-upstream-product-archive-root"
if (-not (Test-Path -LiteralPath (Join-Path $expanded "payload\\nested.txt") -PathType Leaf)) {{ throw "stripped payload missing" }}
if (Test-Path -LiteralPath (Join-Path $expanded "very-long-upstream-product-archive-root")) {{ throw "archive root was retained" }}
'''.lstrip(),
                encoding="utf-8-sig",
            )
            completed = subprocess.run(
                [POWERSHELL, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(wrapper)],
                capture_output=True,
                text=True,
                encoding="utf-8",
            )
            self.assertEqual(0, completed.returncode, completed.stderr)
            self.assertEqual("safe", (destination / "payload/nested.txt").read_text(encoding="utf-8"))

    def test_locator_rejects_user_data_root_mismatch(self) -> None:
        with tempfile.TemporaryDirectory(prefix="aivcp-locator-mismatch-") as temporary:
            base = Path(temporary)
            local = base / "LocalAppData"
            install = base / "Program"
            state_data = base / "State Data"
            wrong_data = base / "Wrong Data"
            runtime = install / "current/runtime/python/python.exe"
            runtime.parent.mkdir(parents=True)
            runtime.write_bytes(b"placeholder")
            state_data.mkdir()
            wrong_data.mkdir()
            release_hash = "4" * 64
            write_json(
                install / "installation.json",
                {
                    "schemaVersion": "2.0.0",
                    "productId": "ai-video-channel-production",
                    "activeVersion": "0.8.0-rc.2",
                    "activeRoot": "current",
                    "userDataRoot": str(state_data),
                    "releaseManifestSha256": release_hash,
                },
            )
            write_json(
                install / "current/install-state.json",
                {
                    "schemaVersion": "2.0.0",
                    "productId": "ai-video-channel-production",
                    "productVersion": "0.8.0-rc.2",
                    "userDataRoot": str(state_data),
                    "releaseManifestSha256": release_hash,
                    "runtime": {"bundled": True, "python": "runtime/python/python.exe"},
                },
            )
            write_json(
                local / "AIVCP-Config/runtime-locator.json",
                {
                    "schemaVersion": "1.0.0",
                    "productId": "ai-video-channel-production",
                    "productVersion": "0.8.0-rc.2",
                    "installRoot": str(install),
                    "activeRoot": "current",
                    "pythonRelativePath": "runtime/python/python.exe",
                    "userDataRoot": str(wrong_data),
                },
            )
            wrapper = base / "locator-mismatch.ps1"
            wrapper.write_text(
                f'''
. "{COMMON}"
try {{ Get-AivcpRuntimeLocatorRecord | Out-Null; exit 2 }}
catch {{ if ($_.Exception.Message -notmatch "user data root does not match") {{ throw }} }}
'''.lstrip(),
                encoding="utf-8-sig",
            )
            environment = os.environ.copy()
            environment["LOCALAPPDATA"] = str(local)
            completed = subprocess.run(
                [POWERSHELL, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(wrapper)],
                capture_output=True,
                text=True,
                encoding="utf-8",
                env=environment,
            )
            self.assertEqual(0, completed.returncode, completed.stderr)

    def test_rollback_failure_after_locator_write_restores_exact_state(self) -> None:
        with tempfile.TemporaryDirectory(prefix="aivcp-rollback-transaction-") as temporary:
            base = Path(temporary)
            local = base / "Local App Data"
            install = base / "Program Root"
            current = install / "current"
            candidate = install / "backups" / "candidate-v0.7"
            data = base / "User Data"
            locator = local / "AIVCP-Config" / "runtime-locator.json"
            data.mkdir(parents=True)
            current.mkdir(parents=True)
            candidate.mkdir(parents=True)
            (current / "old-current.txt").write_text("old current", encoding="utf-8")
            (candidate / "candidate.txt").write_text("candidate", encoding="utf-8")
            (candidate / "runtime/python").mkdir(parents=True)
            (candidate / "runtime/python/python.exe").write_bytes(b"test placeholder")
            write_json(
                candidate / "plugins/ai-video-channel-production/.codex-plugin/plugin.json",
                {"name": "ai-video-channel-production", "version": "0.7.0"},
            )
            write_json(
                candidate / "plugins/ai-video-channel-production/.mcp.json",
                {"mcpServers": {"ai-video-channel-tools": {"command": "powershell", "args": ["legacy"]}}},
            )
            old_hash = "1" * 64
            new_hash = "2" * 64
            write_json(
                current / "install-state.json",
                {
                    "schemaVersion": "2.0.0",
                    "productId": "ai-video-channel-production",
                    "productVersion": "0.8.0-rc.2",
                    "releaseManifestSha256": old_hash,
                    "userDataRoot": str(data),
                    "runtime": {"bundled": True, "python": "runtime/python/python.exe"},
                },
            )
            write_json(
                candidate / "install-state.json",
                {
                    "schemaVersion": "2.0.0",
                    "productId": "ai-video-channel-production",
                    "productVersion": "0.7.0",
                    "releaseManifestSha256": new_hash,
                    "userDataRoot": str(data),
                    "runtime": {"bundled": True, "python": "runtime/python/python.exe"},
                },
            )
            marker_bytes = write_json(
                install / "installation.json",
                {
                    "schemaVersion": "2.0.0",
                    "productId": "ai-video-channel-production",
                    "activeVersion": "0.8.0-rc.2",
                    "activeRoot": "current",
                    "userDataRoot": str(data),
                    "releaseManifestSha256": old_hash,
                },
            )
            locator_bytes = write_json(
                locator,
                {
                    "schemaVersion": "1.0.0",
                    "productId": "ai-video-channel-production",
                    "productVersion": "0.8.0-rc.2",
                    "installRoot": str(install),
                    "activeRoot": "current",
                    "pythonRelativePath": "runtime/python/python.exe",
                    "userDataRoot": str(data),
                    "updatedAt": "2026-08-04T00:00:00Z",
                },
            )
            environment = os.environ.copy()
            environment["LOCALAPPDATA"] = str(local)
            environment["AIVCP_DISABLE_CODEX_AUTO_REGISTRATION"] = "1"
            rollback_wrapper = base / "invoke-rollback.ps1"
            rollback_wrapper.write_text(
                """
param([string]$RollbackScript, [string]$InstallRoot, [string]$BackupName)
& $RollbackScript -InstallRoot $InstallRoot -BackupName $BackupName -SkipCodexRegistration -FailureInjectionPoint AfterLocatorWrite -Confirm:$false
""".lstrip(),
                encoding="utf-8-sig",
            )
            completed = subprocess.run(
                [
                    POWERSHELL,
                    "-NoProfile",
                    "-NonInteractive",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-File",
                    str(rollback_wrapper),
                    "-RollbackScript",
                    str(ROLLBACK),
                    "-InstallRoot",
                    str(install),
                    "-BackupName",
                    candidate.name,
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                env=environment,
            )
            self.assertNotEqual(0, completed.returncode)
            self.assertIn("current program, marker, and runtime locator were restored", completed.stderr)
            self.assertEqual(marker_bytes, (install / "installation.json").read_bytes())
            self.assertEqual(locator_bytes, locator.read_bytes())
            self.assertTrue((current / "old-current.txt").is_file())
            self.assertTrue((candidate / "candidate.txt").is_file())

    def test_restore_whatif_creates_nothing_and_reports_no_change(self) -> None:
        with tempfile.TemporaryDirectory(prefix="aivcp-restore-whatif-") as temporary:
            base = Path(temporary)
            install = base / "Program Root"
            data = base / "Existing Data"
            archive = base / "backup.zip"
            install.mkdir()
            data.mkdir()
            (data / "sentinel.txt").write_text("unchanged", encoding="utf-8")
            write_json(
                install / "installation.json",
                {"productId": "ai-video-channel-production", "userDataRoot": str(data)},
            )
            with zipfile.ZipFile(archive, "w") as handle:
                handle.writestr("backup-manifest.json", "{}")
                handle.writestr("payload/example.txt", "payload")
            before = sorted(str(path.relative_to(base)) for path in base.rglob("*"))
            completed = subprocess.run(
                [
                    POWERSHELL,
                    "-NoProfile",
                    "-NonInteractive",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-File",
                    str(RESTORE),
                    "-ArchivePath",
                    str(archive),
                    "-InstallRoot",
                    str(install),
                    "-WhatIf",
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
            )
            self.assertEqual(0, completed.returncode, completed.stderr)
            after = sorted(str(path.relative_to(base)) for path in base.rglob("*"))
            self.assertEqual(before, after)
            self.assertEqual("unchanged", (data / "sentinel.txt").read_text(encoding="utf-8"))
            self.assertIn('"status":  "WHATIF_NO_CHANGE"', completed.stdout)
            self.assertNotIn("RESTORE_COMPLETE", completed.stdout)

    def test_health_ignores_broken_global_locator_when_configured_python_is_available(self) -> None:
        with tempfile.TemporaryDirectory(prefix="aivcp-health-stale-locator-") as temporary:
            base = Path(temporary)
            locator = base / "AIVCP-Config" / "runtime-locator.json"
            locator.parent.mkdir(parents=True)
            locator.write_text("{not valid json", encoding="utf-8")
            environment = os.environ.copy()
            environment["LOCALAPPDATA"] = str(base)
            environment["AIVCP_PYTHON"] = sys.executable
            completed = subprocess.run(
                [
                    POWERSHELL,
                    "-NoProfile",
                    "-NonInteractive",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-File",
                    str(HEALTH),
                    "-PluginRoot",
                    str(PLUGIN),
                    "-AsJson",
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                env=environment,
                timeout=60,
            )
            self.assertEqual(0, completed.returncode, completed.stderr)
            report = json.loads(completed.stdout.lstrip("\ufeff"))
            self.assertEqual("PASS", report["status"])
            self.assertTrue(report["serviceChecked"])

    def test_cached_plugin_version_mismatch_is_rejected_before_python_start(self) -> None:
        with tempfile.TemporaryDirectory(prefix="aivcp-cache-version-") as temporary:
            base = Path(temporary)
            cached = base / "Codex Cache" / "ai-video-channel-production"
            shutil.copytree(PLUGIN, cached)
            plugin_manifest = json.loads((cached / ".codex-plugin/plugin.json").read_text(encoding="utf-8-sig"))
            plugin_manifest["version"] = "0.7.0-stale-cache"
            write_json(cached / ".codex-plugin/plugin.json", plugin_manifest)
            local = base / "LocalAppData"
            install = base / "Custom Program"
            data = base / "User Data"
            runtime = install / "current/runtime/python/python.exe"
            runtime.parent.mkdir(parents=True)
            runtime.write_bytes(b"must not execute")
            data.mkdir()
            manifest_hash = "3" * 64
            write_json(
                install / "installation.json",
                {
                    "schemaVersion": "2.0.0",
                    "productId": "ai-video-channel-production",
                    "activeVersion": "0.8.0-rc.2",
                    "activeRoot": "current",
                    "userDataRoot": str(data),
                    "releaseManifestSha256": manifest_hash,
                },
            )
            write_json(
                install / "current/install-state.json",
                {
                    "schemaVersion": "2.0.0",
                    "productId": "ai-video-channel-production",
                    "productVersion": "0.8.0-rc.2",
                    "userDataRoot": str(data),
                    "releaseManifestSha256": manifest_hash,
                    "runtime": {"bundled": True, "python": "runtime/python/python.exe"},
                },
            )
            write_json(
                local / "AIVCP-Config/runtime-locator.json",
                {
                    "schemaVersion": "1.0.0",
                    "productId": "ai-video-channel-production",
                    "productVersion": "0.8.0-rc.2",
                    "installRoot": str(install),
                    "activeRoot": "current",
                    "pythonRelativePath": "runtime/python/python.exe",
                    "userDataRoot": str(data),
                },
            )
            environment = os.environ.copy()
            environment["LOCALAPPDATA"] = str(local)
            environment.pop("AIVCP_PYTHON", None)
            completed = subprocess.run(
                [
                    POWERSHELL,
                    "-NoProfile",
                    "-NonInteractive",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-File",
                    str(cached / "mcp/start.ps1"),
                ],
                input=b'{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}\n',
                capture_output=True,
                env=environment,
            )
            self.assertNotEqual(0, completed.returncode)
            self.assertIn("cached plugin version", completed.stderr.decode("utf-8", errors="replace").lower())


if __name__ == "__main__":
    unittest.main()
