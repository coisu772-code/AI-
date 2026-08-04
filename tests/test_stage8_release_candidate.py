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
)
from validate_unified_release import safe_zip_entries  # noqa: E402


class Stage8UnifiedReleaseTests(unittest.TestCase):
    def manifest(self) -> dict[str, object]:
        return json.loads((ROOT / "release-manifests/unified-release-v0.8.0-rc.2.json").read_text(encoding="utf-8"))

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

    def test_frozen_upstream_records_are_exact(self) -> None:
        assets = {asset["assetId"]: asset for asset in self.manifest()["assets"]}
        self.assertEqual((WORKSHOP_NAME, WORKSHOP_SIZE, WORKSHOP_SHA), (assets["workshop"]["fileName"], assets["workshop"]["sizeBytes"], assets["workshop"]["sha256"]))
        self.assertEqual((PUBLISHER_NAME, PUBLISHER_SIZE, PUBLISHER_SHA), (assets["publisher-center"]["fileName"], assets["publisher-center"]["sizeBytes"], assets["publisher-center"]["sha256"]))
        self.assertEqual("CANDIDATE_READY_FOR_CONTROLLED_REAL_ACCEPTANCE", assets["publisher-center"]["source"]["acceptanceStatus"])
        self.assertEqual(PUBLISHER_SOURCE_COMMIT, assets["publisher-center"]["source"]["commit"])
        self.assertEqual(PUBLISHER_COMPONENT_MANIFEST_SHA, assets["publisher-center"]["source"]["componentManifest"]["sha256"])
        self.assertEqual(PUBLISHER_CONSTRAINTS_SHA, assets["publisher-center"]["source"]["constraintsCatalog"]["sha256"])

    def test_stage6_catalog_bytes_match_the_final_publisher(self) -> None:
        catalog = ROOT / "contracts/youtube-constraints/catalog-2026.08.04.1.json"
        self.assertEqual(PUBLISHER_CONSTRAINTS_SHA, hashlib.sha256(catalog.read_bytes()).hexdigest())
        self.assertIn(b"\r\n", catalog.read_bytes())

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

    def test_zip_traversal_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory(prefix="aivcp-evil-zip-") as temporary:
            archive = Path(temporary) / "evil.zip"
            with zipfile.ZipFile(archive, "w") as handle:
                handle.writestr("root/../escape.txt", "bad")
            errors, _ = safe_zip_entries(archive, "root", False)
            self.assertTrue(any("unsafe ZIP entry" in error for error in errors))

    def test_installer_contains_transactional_and_no_cli_degradation_paths(self) -> None:
        installer = (ROOT / "installer/Install-AIVideoChannelProduction.ps1").read_text(encoding="utf-8")
        common = (ROOT / "installer/Common.ps1").read_text(encoding="utf-8")
        uninstall = (ROOT / "installer/Uninstall-AIVideoChannelProduction.ps1").read_text(encoding="utf-8")
        for marker in ("AfterAssetVerification", "AfterStagingHealth", "AfterSwitch", "restored automatically", "releaseManifestSha256"):
            self.assertIn(marker, installer)
        self.assertIn("Invoke-WebRequest", common)
        self.assertIn("Asset SHA-256 mismatch", common)
        self.assertIn("releases/download/v0.8.0-rc.2/unified-release-v0.8.0-rc.2.json", installer)
        self.assertNotIn("/latest/", installer)
        self.assertIn("AllowInsecureTestTransport", installer)
        self.assertIn("manual step", installer)
        self.assertIn("preserve user data", uninstall.lower())

    def test_release_sources_do_not_embed_credentials_or_development_root(self) -> None:
        checked = [ROOT / "installer", ROOT / "tools", ROOT / "release-manifests"]
        combined = "\n".join(path.read_text(encoding="utf-8", errors="ignore") for directory in checked for path in directory.rglob("*") if path.is_file() and path.suffix.lower() in {".ps1", ".py", ".json", ".md", ".txt"})
        self.assertNotIn("E:\\小说漫全自动化生产", combined)
        self.assertNotRegex(combined, r"(?i)(?:access|refresh)[_-]?token\s*[:=]\s*['\"][A-Za-z0-9_-]{20,}")


if __name__ == "__main__":
    unittest.main()
