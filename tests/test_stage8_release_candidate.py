from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
import sys

sys.path.insert(0, str(TOOLS))
from build_unified_release import (  # noqa: E402
    PUBLISHER_NAME,
    PUBLISHER_COMPONENT_MANIFEST_SHA,
    PUBLISHER_CONSTRAINTS_SHA,
    PUBLISHER_SHA,
    PUBLISHER_SIZE,
    PUBLISHER_SOURCE_COMMIT,
    VERSION,
    WORKSHOP_NAME,
    WORKSHOP_SHA,
    WORKSHOP_SIZE,
    build_bootstrap,
    build_core,
    copy_kokoro_packages,
    reuse_kokoro_packages,
)
from validate_unified_release import safe_zip_entries  # noqa: E402


class Stage8UnifiedReleaseTests(unittest.TestCase):
    def manifest(self) -> dict[str, object]:
        return json.loads((ROOT / f"release-manifests/unified-release-v{VERSION}.json").read_text(encoding="utf-8"))

    def test_rc2_identity_and_repository_marketplace(self) -> None:
        plugin = json.loads((ROOT / "plugins/ai-video-channel-production/.codex-plugin/plugin.json").read_text(encoding="utf-8"))
        marketplace = json.loads((ROOT / ".agents/plugins/marketplace.json").read_text(encoding="utf-8"))
        self.assertEqual(VERSION, plugin["version"])
        self.assertEqual("novel-manga-production", marketplace["name"])
        self.assertEqual("./plugins/ai-video-channel-production", marketplace["plugins"][0]["source"]["path"])
        self.assertFalse((ROOT / ".codex/plugins/marketplace.json").exists())

    def test_total_manifest_has_all_components_hashes_licenses_and_gates(self) -> None:
        manifest = self.manifest()
        assets = {asset["assetId"]: asset for asset in manifest["assets"]}
        self.assertEqual({"unified-installer", "core", "python-runtime", "workshop", "publisher-center"}, set(assets))
        for asset in assets.values():
            self.assertRegex(asset["sha256"], r"^[0-9a-f]{64}$")
            self.assertGreater(asset["sizeBytes"], 0)
            self.assertTrue(asset["compatibleProductVersions"])
            self.assertTrue(asset["license"]["source"])
        self.assertTrue(assets["workshop"]["install"])
        self.assertTrue(assets["publisher-center"]["install"])
        expected_license_status = "technical-inventory-validated-release-owner-approval-required"
        self.assertEqual(expected_license_status, assets["publisher-center"]["license"]["reviewStatus"])
        self.assertEqual(expected_license_status, assets["python-runtime"]["license"]["reviewStatus"])
        self.assertEqual(expected_license_status, assets["workshop"]["license"]["reviewStatus"])
        self.assertIn("release-license-owner-approval", manifest["publicationGates"])

        runtime_packages = {package["variant"]: package for package in manifest["optionalRuntimePackages"]}
        self.assertEqual({"cpu", "nvidia", "nvidia-blackwell"}, set(runtime_packages))
        for variant, package in runtime_packages.items():
            self.assertEqual("kokoro-fastapi", package["runtimeId"])
            self.assertEqual(variant, package["variant"])
            self.assertTrue(package["parts"])
            self.assertEqual(expected_license_status, package["license"]["reviewStatus"])

    def test_kokoro_release_attachments_are_hash_bound_and_copied(self) -> None:
        with tempfile.TemporaryDirectory(prefix="aivcp-kokoro-build-") as temporary:
            base = Path(temporary)
            source, output = base / "source", base / "output"
            source.mkdir()
            output.mkdir()
            for variant in ("cpu", "nvidia", "nvidia-blackwell"):
                archive_name = f"Z-Manga-Studio-kokoro-runtime-{variant}.zip"
                archive = source / archive_name
                with zipfile.ZipFile(archive, "w") as handle:
                    handle.writestr("tools/kokoro-fastapi/LICENSE-Kokoro-FastAPI.txt", "Apache-2.0")
                    handle.writestr("tools/kokoro-fastapi/start-auto.ps1", "Write-Host ready")
                payload = archive.read_bytes()
                split = max(1, len(payload) // 2)
                parts = []
                for index, content in enumerate((payload[:split], payload[split:]), start=1):
                    part_name = f"{archive_name}.{index:03d}"
                    (source / part_name).write_bytes(content)
                    parts.append({"name": part_name, "size": len(content), "sha256": hashlib.sha256(content).hexdigest()})
                (source / f"Z-Manga-Studio-kokoro-runtime-{variant}.json").write_text(
                    json.dumps({
                        "schemaVersion": "1.0",
                        "runtimeVersion": "test-runtime",
                        "variant": variant,
                        "archiveName": archive_name,
                        "archiveSha256": hashlib.sha256(payload).hexdigest(),
                        "parts": parts,
                    }),
                    encoding="utf-8",
                )
                archive.unlink()
            packages, copied = copy_kokoro_packages(output, source)
            self.assertEqual(3, len(packages))
            self.assertEqual(9, len(copied))
            self.assertTrue(all(path.is_file() for path in copied))

    def test_unchanged_kokoro_packages_are_reused_from_one_trusted_public_release(self) -> None:
        packages = reuse_kokoro_packages()
        self.assertEqual({"cpu", "nvidia", "nvidia-blackwell"}, {package["variant"] for package in packages})
        for package in packages:
            source = package["source"]
            self.assertEqual("coisu772-code/AI-", source["repository"])
            self.assertEqual("v0.10.0-rc.1", source["releaseTag"])
            self.assertEqual("PUBLISHED_RUNTIME_REUSED_AFTER_REMOTE_DIGEST_REVALIDATION", source["reuseStatus"])
            self.assertRegex(source["releaseManifest"]["sha256"], r"^[0-9a-f]{64}$")

    def test_portable_youtube_runtime_is_pinned_and_installer_bound(self) -> None:
        contract = json.loads((ROOT / "plugins/ai-video-channel-production/assets/portable-youtube-runtime.json").read_text(encoding="utf-8"))
        requirements = (ROOT / "installer/runtime-requirements.txt").read_text(encoding="utf-8")
        builder = (TOOLS / "build_unified_release.py").read_text(encoding="utf-8")
        common = (ROOT / "installer/Common.ps1").read_text(encoding="utf-8")
        health = (ROOT / "installer/Test-AIVideoChannelProductionHealth.ps1").read_text(encoding="utf-8")
        server = (ROOT / "plugins/ai-video-channel-production/mcp/server.py").read_text(encoding="utf-8")

        self.assertEqual("2026.7.4", contract["collector"]["version"])
        self.assertEqual("0.8.0", contract["collector"]["ejsVersion"])
        self.assertEqual("2.9.4", contract["javascriptRuntime"]["version"])
        self.assertFalse(contract["requiresSystemPath"])
        for requirement in (
            "yt-dlp[default]==2026.7.4",
            "yt-dlp-ejs==0.8.0",
            "requests==2.34.2",
            "websockets==17.0.1",
        ):
            self.assertIn(requirement, requirements)
        self.assertIn("DENO_ARCHIVE_SHA", builder)
        self.assertIn("locked Deno executable size or SHA-256 mismatch", builder)
        self.assertIn("AIVCP_YT_DLP_COMMAND_JSON", common)
        self.assertIn("--js-runtimes", common)
        self.assertIn("--ffmpeg-location", common)
        self.assertIn("youtubeCollectorChecked", health)
        self.assertIn("youtube_runtime_matches", server)

    def test_frozen_upstream_records_are_exact(self) -> None:
        assets = {asset["assetId"]: asset for asset in self.manifest()["assets"]}
        self.assertEqual((WORKSHOP_NAME, WORKSHOP_SIZE, WORKSHOP_SHA), (assets["workshop"]["fileName"], assets["workshop"]["sizeBytes"], assets["workshop"]["sha256"]))
        self.assertEqual((PUBLISHER_NAME, PUBLISHER_SIZE, PUBLISHER_SHA), (assets["publisher-center"]["fileName"], assets["publisher-center"]["sizeBytes"], assets["publisher-center"]["sha256"]))
        self.assertEqual("PUBLISHED_COMPONENT_REUSED_AFTER_HASH_REVALIDATION", assets["publisher-center"]["source"]["acceptanceStatus"])
        self.assertEqual(PUBLISHER_SOURCE_COMMIT, assets["publisher-center"]["source"]["commit"])
        self.assertEqual(PUBLISHER_COMPONENT_MANIFEST_SHA, assets["publisher-center"]["source"]["componentManifest"]["sha256"])
        self.assertEqual(PUBLISHER_CONSTRAINTS_SHA, assets["publisher-center"]["source"]["constraintsCatalog"]["sha256"])

    def test_stage6_catalog_bytes_match_the_final_publisher(self) -> None:
        catalog = ROOT / "contracts/youtube-constraints/catalog-2026.08.04.1.json"
        self.assertEqual(PUBLISHER_CONSTRAINTS_SHA, hashlib.sha256(catalog.read_bytes()).hexdigest())
        self.assertIn(b"\r\n", catalog.read_bytes())

    def test_publish_execution_requires_current_approval_and_exact_tag_binding(self) -> None:
        script = (TOOLS / "Publish-UnifiedRelease.ps1").read_text(encoding="utf-8")
        self.assertIn("releaseLicenseOwnerApproved", script)
        self.assertNotIn("publisherThirdPartyNoticesApproved", script)
        self.assertIn("implementationSourceCommitSha", script)
        self.assertIn("rev-list -n 1 $Tag", script)
        self.assertIn("$tagCommit -ne $boundSourceCommit", script)
        self.assertIn("git credential fill", script)
        self.assertIn("This publisher never starts an interactive browser login", script)
        self.assertIn("Dictionary[string,object]", script)
        self.assertIn("JavaScriptSerializer", script)
        self.assertIn("ls-remote origin", script)
        self.assertIn("remote[0].digest", script)
        self.assertIn("REUSED_REMOTE_VERIFY_PASS", script)
        self.assertNotIn("gh auth login", script)
        self.assertNotIn("Get-Command gh", script)
        self.assertNotIn("$gh.Source release create", script)

    def test_runtime_is_standalone_and_ffmpeg_is_explicit(self) -> None:
        manifest = self.manifest()
        self.assertFalse(manifest["runtime"]["requiresPreinstalledPython"])
        self.assertFalse(manifest["runtime"]["requiresPreinstalledUv"])
        ffmpeg = manifest["logicalComponents"][0]
        self.assertEqual("ffmpeg-runtime", ffmpeg["componentId"])
        self.assertEqual("GPL-3.0-only", ffmpeg["license"]["expression"])
        self.assertEqual(2, len(ffmpeg["files"]))

    def test_core_and_bootstrap_are_deterministic_and_core_has_no_exe(self) -> None:
        with tempfile.TemporaryDirectory(prefix="aivcp-core-build-") as temporary:
            base = Path(temporary)
            first_core, second_core = build_core(base / "a"), build_core(base / "b")
            first_entry, second_entry = build_bootstrap(base / "a"), build_bootstrap(base / "b")
            self.assertEqual(first_core["sha256"], second_core["sha256"])
            self.assertEqual(first_entry["sha256"], second_entry["sha256"])
            errors, _ = safe_zip_entries(Path(first_core["path"]), "ai-video-channel-production-core", True)
            self.assertEqual([], errors)
            with zipfile.ZipFile(first_core["path"]) as archive:
                self.assertNotIn(
                    "ai-video-channel-production-core/docs/final-acceptance-approval-checklist-v0.8.0-rc.2.json",
                    set(archive.namelist()),
                )

    def test_zip_traversal_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory(prefix="aivcp-evil-zip-") as temporary:
            archive = Path(temporary) / "evil.zip"
            with zipfile.ZipFile(archive, "w") as handle:
                handle.writestr("root/../escape.txt", "bad")
            errors, _ = safe_zip_entries(archive, "root", False)
            self.assertTrue(any("unsafe ZIP entry" in error for error in errors))

    def test_runtime_third_party_test_keys_are_not_credentials_but_product_keys_are(self) -> None:
        marker = "-----BEGIN " + "PRIVATE KEY-----\ntest-vector\n-----END " + "PRIVATE KEY-----"
        with tempfile.TemporaryDirectory(prefix="aivcp-runtime-secret-scan-") as temporary:
            base = Path(temporary)
            allowed = base / "aivcp-python-runtime-test.zip"
            with zipfile.ZipFile(allowed, "w") as handle:
                handle.writestr("runtime/Lib/site-packages/example/self_test.py", marker)
            allowed_errors, _ = safe_zip_entries(allowed, "runtime", False)
            self.assertFalse(any("credential signature" in error for error in allowed_errors))

            rejected = base / "aivcp-python-runtime-product.zip"
            with zipfile.ZipFile(rejected, "w") as handle:
                handle.writestr("runtime/start.ps1", marker)
            rejected_errors, _ = safe_zip_entries(rejected, "runtime", False)
            self.assertTrue(any("credential signature" in error for error in rejected_errors))

    def test_installer_contains_transactional_and_no_cli_degradation_paths(self) -> None:
        installer = (ROOT / "installer/Install-AIVideoChannelProduction.ps1").read_text(encoding="utf-8")
        common = (ROOT / "installer/Common.ps1").read_text(encoding="utf-8")
        uninstall = (ROOT / "installer/Uninstall-AIVideoChannelProduction.ps1").read_text(encoding="utf-8")
        for marker in ("AfterAssetVerification", "AfterStagingHealth", "AfterSwitch", "restored automatically", "releaseManifestSha256"):
            self.assertIn(marker, installer)
        self.assertIn("Invoke-WebRequest", common)
        self.assertIn("Asset SHA-256 mismatch", common)
        self.assertIn(f"releases/download/v{VERSION}/unified-release-v{VERSION}.json", installer)
        self.assertNotIn("/latest/", installer)
        self.assertIn("AllowInsecureTestTransport", installer)
        self.assertIn("manual step", installer)
        self.assertIn("preserve user data", uninstall.lower())

    def test_uninstall_defers_locator_and_codex_removal_until_program_delete_succeeds(self) -> None:
        uninstall = (ROOT / "installer/Uninstall-AIVideoChannelProduction.ps1").read_text(encoding="utf-8")
        should_process = uninstall.index("$PSCmdlet.ShouldProcess")
        program_delete = uninstall.index("Remove-Item -LiteralPath $installFull -Recurse -Force")
        data_confirmation = uninstall.index('if (-not (Test-Path -LiteralPath $dataFull -PathType Container))')
        locator_delete = uninstall.index("Remove-AivcpRuntimeLocatorIfOwned")
        plugin_delete = uninstall.index('& $codex plugin remove "ai-video-channel-production"')
        marketplace_delete = uninstall.index('& $codex plugin marketplace remove "novel-manga-production"')
        self.assertLess(should_process, program_delete)
        self.assertLess(program_delete, data_confirmation)
        self.assertLess(data_confirmation, locator_delete)
        self.assertLess(locator_delete, plugin_delete)
        self.assertLess(plugin_delete, marketplace_delete)
        self.assertNotIn("$locatorOwnedByThisInstall", uninstall)
        self.assertGreater(uninstall.index("$locatorOwnedAtCommit = Test-AivcpRuntimeLocatorOwnedBy"), should_process)

    def test_short_default_root_and_installation_owned_runtime_locator_are_hard_gates(self) -> None:
        installer_sources = [
            ROOT / "installer/Install-AIVideoChannelProduction.ps1",
            ROOT / "installer/Upgrade-AIVideoChannelProduction.ps1",
            ROOT / "installer/Repair-AIVideoChannelProduction.ps1",
            ROOT / "installer/Rollback-AIVideoChannelProduction.ps1",
            ROOT / "installer/Test-AIVideoChannelProductionHealth.ps1",
            ROOT / "installer/Backup-AIVideoChannelProductionData.ps1",
            ROOT / "installer/Restore-AIVideoChannelProductionData.ps1",
            ROOT / "installer/Uninstall-AIVideoChannelProduction.ps1",
        ]
        for path in installer_sources:
            source = path.read_text(encoding="utf-8")
            self.assertIn('Join-Path $env:LOCALAPPDATA "AIVCP"', source, path.name)
            self.assertNotIn('Join-Path $env:LOCALAPPDATA "AI Video Channel Production"', source, path.name)

        common = (ROOT / "installer/Common.ps1").read_text(encoding="utf-8")
        plugin_start = (ROOT / "plugins/ai-video-channel-production/mcp/start.ps1").read_text(encoding="utf-8")
        lifecycle = (ROOT / "tools/Invoke-Stage8Lifecycle.ps1").read_text(encoding="utf-8")
        cached_validator = (ROOT / "tools/validate_cached_plugin_runtime.py").read_text(encoding="utf-8")
        codex_validator = (ROOT / "tools/validate_actual_codex_cli_mcp.py").read_text(encoding="utf-8")
        install = (ROOT / "installer/Install-AIVideoChannelProduction.ps1").read_text(encoding="utf-8")
        rollback = (ROOT / "installer/Rollback-AIVideoChannelProduction.ps1").read_text(encoding="utf-8")
        uninstall = (ROOT / "installer/Uninstall-AIVideoChannelProduction.ps1").read_text(encoding="utf-8")
        restore = (ROOT / "installer/Restore-AIVideoChannelProductionData.ps1").read_text(encoding="utf-8")
        health = (ROOT / "installer/Test-AIVideoChannelProductionHealth.ps1").read_text(encoding="utf-8")
        self.assertIn('$script:AivcpRuntimeLocatorFolder = "AIVCP-Config"', common)
        self.assertIn('$script:AivcpLegacyPathBudget = 248', common)
        self.assertIn('"Global\\AIVCP-ChannelProduction-Installer-v1-$($script:AivcpCurrentUserSid)"', common)
        self.assertIn("Assert-AivcpArchivePathBudget", common)
        self.assertIn("Select-Object -Skip 1", common)
        self.assertIn("Write-AivcpRuntimeLocator", common)
        self.assertIn("Test-AivcpRuntimeLocatorOwnedBy", common)
        self.assertIn("Write-AivcpRuntimeBoundMcpDescriptor", common)
        self.assertIn('command = $pythonPath', common)
        self.assertIn('args = @("./mcp/server.py", "mcp")', common)
        self.assertIn('AIVCP_DATA_ROOT = $dataFull', common)
        self.assertIn('AIVCP_INSTALL_ROOT = $installFull', common)
        self.assertIn('AIVCP_EXPECTED_PRODUCT_VERSION = $ProductVersion', common)
        self.assertIn('AIVCP_EXPECTED_RELEASE_MANIFEST_SHA256 = $ReleaseManifestSha256.ToLowerInvariant()', common)
        self.assertIn('AIVCP_WORKSHOP_EXECUTABLE = $workshopPath', common)
        self.assertIn('AIVCP_WORKSHOP_ISOLATION_ROOT = $workshopIsolationRoot', common)
        self.assertIn('AIVCP_FFMPEG_PATH = $ffmpegPath', common)
        self.assertIn('AIVCP_FFPROBE_PATH = $ffprobePath', common)
        self.assertIn('AIVCP_PUBLISHER_CHANNEL_LIST_EXE = $publisherChannelListPath', common)
        self.assertIn('AIVCP_PUBLISHER_V2_CLI = $publisherV2Path', common)
        self.assertIn('AIVCP_YT_DLP_COMMAND_JSON = $youtubeCollectorCommandJson', common)
        self.assertIn('$workshopExecutables.Count -ne 1', common)
        self.assertIn('$workshopRelativePath = Join-Path "apps\\workshop"', common)
        self.assertIn('"apps\\publisher\\channel-list.exe"', common)
        self.assertIn('"apps\\publisher\\publish-package-v2.exe"', common)
        self.assertIn('AIVCP_NETWORK_EXECUTION = "false"', common)
        self.assertIn('AIVCP_PUBLISHER_NETWORK_EXECUTION = "false"', common)
        self.assertIn("-ComponentVerificationRoot $stagingPath", install)
        self.assertIn("AfterMcpDescriptorBinding", install)
        self.assertIn("AfterMcpDescriptorBinding", rollback)
        self.assertIn("Restore-AivcpFileSnapshot $descriptorSnapshot", install)
        self.assertIn("Restore-AivcpFileSnapshot $candidateDescriptorSnapshot", rollback)
        self.assertIn('"AIVCP-Config\\runtime-locator.json"', plugin_start)
        self.assertIn('runtime.python -ne "runtime/python/python.exe"', plugin_start)
        self.assertNotIn("AI Video Channel Production\\current\\runtime", plugin_start)
        self.assertLess(plugin_start.index("$pluginManifest ="), plugin_start.index("$configuredPython ="))
        self.assertLess(plugin_start.index("$locator = Get-Content"), plugin_start.index("$configuredPython ="))
        self.assertIn('[string]$pluginManifest.version -ne [string]$locator.productVersion', plugin_start)
        self.assertIn("$env:AIVCP_DATA_ROOT = $boundDataRoot", plugin_start)
        self.assertGreater(health.index("$locatorRecord = Get-AivcpRuntimeLocatorRecord"), health.index("elseif (Test-Path -LiteralPath $installedPython"))
        for source in (install, rollback, uninstall):
            self.assertIn("Enter-AivcpOperationLock", source)
            self.assertIn("Exit-AivcpOperationLock", source)
        self.assertIn("AfterLocatorWrite", install)
        self.assertIn("Restore-AivcpFileSnapshot $locatorSnapshot", install)
        self.assertIn("AfterLocatorWrite", rollback)
        self.assertIn("Restore-AivcpFileSnapshot $markerSnapshot", rollback)
        self.assertIn("Restore-AivcpFileSnapshot $locatorSnapshot", rollback)
        self.assertLess(restore.index("$PSCmdlet.ShouldProcess"), restore.index("New-Item -ItemType Directory -Path $staging"))
        self.assertIn('status = "WHATIF_NO_CHANGE"', restore)
        self.assertIn("defaultPathMaxPathRegressionFileLength", lifecycle)
        self.assertIn("freshCachedPluginRuntimeBoundDescriptor", lifecycle)
        self.assertIn("validate_actual_codex_cli_mcp.py", lifecycle)
        self.assertIn("actualCodexCliTimeoutSeconds", lifecycle)
        self.assertIn("staleCachedPluginVersionRejectedBeforeService", lifecycle)
        self.assertIn("validate_runtime_binding_tamper.py", lifecycle)
        self.assertIn("installedWorkshopReadOnlyHealthAndCapabilities", lifecycle)
        self.assertIn("installedPublisherReadOnlyAndV2Bridges", lifecycle)
        server = (ROOT / "plugins/ai-video-channel-production/mcp/server.py").read_text(encoding="utf-8")
        self.assertIn("def _validate_runtime_binding()", server)
        self.assertIn('plugin.get("version") == expected_version', server)
        self.assertIn('locator.get("productVersion") == expected_version', server)
        self.assertIn("_same_path(Path(sys.executable), expected_python)", server)
        self.assertIn('"manifest": install_root / "current" / "unified-release-manifest.json"', server)
        self.assertIn("hashlib.sha256(manifest_bytes).hexdigest() == expected_release", server)
        self.assertIn('"AIVCP_WORKSHOP_EXECUTABLE": install_root', server)
        self.assertIn('"AIVCP_PUBLISHER_V2_CLI": install_root', server)
        self.assertIn("component_paths_match", server)
        self.assertIn("AfterLocatorWrite", lifecycle)
        self.assertIn("RUNTIME_BOUND_DESCRIPTOR_FRESH_PROCESS", cached_validator)
        self.assertIn('arguments != ["./mcp/server.py", "mcp"]', cached_validator)
        self.assertIn('"descriptorCommandDirectToPython": True', cached_validator)
        self.assertIn('"powershellOrCmdProxy": False', cached_validator)
        self.assertIn('"AIVCP_EXPECTED_PRODUCT_VERSION"', cached_validator)
        self.assertIn('"workshopHealthCheckExecuted"', cached_validator)
        self.assertIn('"publisherReadOnlyConfigured"', cached_validator)
        self.assertIn('"publisherV2Configured"', cached_validator)
        self.assertIn('environment.pop(name, None)', cached_validator)
        self.assertIn("timeout=args.timeout_seconds", codex_validator)
        self.assertIn("terminate_process_tree(process)", codex_validator)
        self.assertIn('["taskkill", "/PID", str(process.pid), "/T", "/F"]', codex_validator)
        self.assertIn('item_type in {"command_execution", "web_search", "file_change"}', codex_validator)
        self.assertIn('"ACTUAL_CODEX_CLI_RUNTIME_BOUND_MCP"', codex_validator)
        self.assertIn('"publisherReadOnly"', codex_validator)
        self.assertIn('"externalProbeFalse"', codex_validator)

    def test_health_script_uses_strict_no_bom_jsonl_file_relay(self) -> None:
        health = (ROOT / "installer/Test-AIVideoChannelProductionHealth.ps1").read_text(encoding="utf-8")
        server = (ROOT / "plugins/ai-video-channel-production/mcp/server.py").read_text(encoding="utf-8")
        for forbidden in ("RedirectStandardInput", "StandardInput", "BaseStream", "WriteLine"):
            self.assertNotIn(forbidden, health)
        self.assertIn('("aivcp-mcp-file-relay-" + [guid]::NewGuid().ToString("N"))', health)
        self.assertIn('[System.IO.File]::WriteAllText($requestPath, $RequestText + "`n", $utf8NoBom)', health)
        self.assertIn('[System.IO.File]::WriteAllText($relayPath, $relayCode, [System.Text.Encoding]::ASCII)', health)
        self.assertIn("completed = subprocess.run(", health)
        self.assertIn("input=payload", health)
        self.assertIn('"run --no-project python $quotedRelay $quotedServer $quotedRequest"', health)
        self.assertIn("Remove-Item -LiteralPath $relayRoot -Recurse -Force", health)
        self.assertIn('raw_line.decode("utf-8")', server)
        self.assertIn("json.loads", server)
        self.assertIn("UnicodeDecodeError", server)
        self.assertIn("json.JSONDecodeError", server)

    def test_release_sources_do_not_embed_credentials_or_development_root(self) -> None:
        checked = [ROOT / "installer", ROOT / "tools", ROOT / "release-manifests"]
        combined = "\n".join(path.read_text(encoding="utf-8", errors="ignore") for directory in checked for path in directory.rglob("*") if path.is_file() and path.suffix.lower() in {".ps1", ".py", ".json", ".md", ".txt"})
        self.assertNotIn("E:\\小说漫全自动化生产", combined)
        self.assertNotRegex(combined, r"(?i)(?:access|refresh)[_-]?token\s*[:=]\s*['\"][A-Za-z0-9_-]{20,}")


if __name__ == "__main__":
    unittest.main()
