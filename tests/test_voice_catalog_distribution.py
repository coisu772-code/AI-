from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PLUGIN_MCP = ROOT / "plugins/ai-video-channel-production/mcp"
CATALOG = ROOT / "plugins/ai-video-channel-production/assets/voice-catalog.json"
CONVERTER = ROOT / "tools/convert_workshop_voice_catalog.py"


def load_converter():
    spec = importlib.util.spec_from_file_location("convert_workshop_voice_catalog", CONVERTER)
    if spec is None or spec.loader is None:
        raise RuntimeError("voice catalog converter could not be loaded")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class VoiceCatalogDistributionTests(unittest.TestCase):
    def test_bundled_catalog_is_valid_and_contains_configured_workshop_engines(self) -> None:
        import sys

        sys.path.insert(0, str(PLUGIN_MCP))
        try:
            from aivcp_tools.security import contains_sensitive_material
            from aivcp_tools.voices import VoiceCatalog

            raw = json.loads(CATALOG.read_text(encoding="utf-8"))
            self.assertFalse(contains_sensitive_material(raw))
            catalog = VoiceCatalog(CATALOG).read()
        finally:
            sys.path.remove(str(PLUGIN_MCP))

        engines = {engine["engineId"]: engine for engine in catalog["engines"]}
        self.assertEqual({"voicevox_external", "fish_audio", "kokoro", "edge_tts"}, set(engines))
        self.assertTrue(all(engine["installed"] for engine in engines.values()))
        self.assertGreaterEqual(len(engines["voicevox_external"]["voices"]), 100)
        self.assertGreaterEqual(len(engines["fish_audio"]["voices"]), 100)
        self.assertGreaterEqual(len(engines["kokoro"]["voices"]), 60)
        self.assertGreaterEqual(len(engines["edge_tts"]["voices"]), 60)
        self.assertIn("81", {voice["voiceId"] for voice in engines["voicevox_external"]["voices"]})
        self.assertIn("zf_xiaobei", {voice["voiceId"] for voice in engines["kokoro"]["voices"]})
        self.assertIn("ja-JP-NanamiNeural", {voice["voiceId"] for voice in engines["edge_tts"]["voices"]})
        policies = {policy["engineId"]: policy for policy in catalog["enginePolicies"]}
        self.assertEqual("PROVIDER_HAS_NO_PUBLIC_VOICE_LIST", policies["seed_audio"]["reasonCode"])
        self.assertFalse(policies["seed_audio"]["selectableFromCatalog"])

    def test_converter_keeps_safe_configured_local_and_pre_scanned_api_engines(self) -> None:
        converter = load_converter()
        source = {
            "schemaVersion": 1,
            "generatedAt": "2026-08-05T00:00:00Z",
            "apiKey": "must-not-be-copied",
            "engines": [
                {
                    "engine": "voicevox_external",
                    "name": "VOICEVOX",
                    "configured": True,
                    "baseUrl": "http://127.0.0.1:50021",
                    "voices": [
                        {
                            "id": "81",
                            "name": "青山龍星 / ノーマル",
                            "languages": ["ja-JP"],
                            "autoMatchingEligible": True,
                        }
                    ],
                },
                {
                    "engine": "fish_audio",
                    "name": "Online API",
                    "configured": False,
                    "voices": [{"id": "remote", "name": "remote"}],
                },
                {
                    "engine": "kokoro",
                    "name": "Kokoro",
                    "configured": False,
                    "voices": [{"id": "af_alloy", "name": "alloy"}],
                },
            ],
        }
        converted = converter.convert_catalog(source)
        self.assertEqual("1.0.0", converted["schemaVersion"])
        self.assertEqual(["voicevox_external", "fish_audio"], [item["engineId"] for item in converted["engines"]])
        self.assertEqual("seed_audio", converted["enginePolicies"][0]["engineId"])
        serialized = json.dumps(converted, ensure_ascii=False)
        self.assertNotIn("apiKey", serialized)
        self.assertNotIn("baseUrl", serialized)
        self.assertNotIn("must-not-be-copied", serialized)

    def test_converter_rejects_an_empty_supported_catalog(self) -> None:
        converter = load_converter()
        with self.assertRaisesRegex(ValueError, "no supported engines with usable voices"):
            converter.convert_catalog({"engines": []})

    def test_converter_uses_a_real_configured_seed_audio_voice_instead_of_the_no_list_policy(self) -> None:
        converter = load_converter()
        converted = converter.convert_catalog(
            {
                "generatedAt": "2026-08-05T00:00:00Z",
                "engines": [
                    {
                        "engine": "edge_tts",
                        "name": "Edge TTS",
                        "configured": True,
                        "voices": [{"id": "ja-JP-NanamiNeural", "name": "Nanami"}],
                    },
                    {
                        "engine": "seed_audio",
                        "name": "Seed Audio API",
                        "configured": True,
                        "apiKey": "must-not-be-copied",
                        "voices": [{"id": "account-preset-voice", "name": "已配置预设音色"}],
                    },
                ],
            }
        )
        engines = {engine["engineId"]: engine for engine in converted["engines"]}
        self.assertEqual("account-preset-voice", engines["seed_audio"]["voices"][0]["voiceId"])
        self.assertNotIn("seed_audio", {policy["engineId"] for policy in converted["enginePolicies"]})
        self.assertNotIn("must-not-be-copied", json.dumps(converted, ensure_ascii=False))

    def test_release_health_gates_future_workshop_voice_engine_coverage(self) -> None:
        health = (ROOT / "installer/Test-AIVideoChannelProductionHealth.ps1").read_text(encoding="utf-8")
        cached_runtime = (ROOT / "tools/validate_cached_plugin_runtime.py").read_text(encoding="utf-8")
        self.assertIn("workshopCapabilities.voiceEngines", health)
        self.assertIn("$voiceCatalogCoverage -notcontains", health)
        self.assertIn("reported_voice_engines.issubset(covered_voice_engines)", cached_runtime)

    def test_mcp_catalog_output_is_utf8_even_under_a_legacy_windows_code_page(self) -> None:
        with tempfile.TemporaryDirectory(prefix="aivcp-voice-stdio-") as temporary:
            environment = os.environ.copy()
            environment["AIVCP_DATA_ROOT"] = temporary
            environment["PYTHONIOENCODING"] = "gbk"
            environment.pop("PYTHONUTF8", None)
            completed = subprocess.run(
                [
                    sys.executable,
                    str(PLUGIN_MCP / "server.py"),
                    "call",
                    "system_voice_catalog",
                    "--arguments",
                    "{}",
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=environment,
                check=False,
            )
            self.assertEqual(0, completed.returncode, completed.stderr.decode("utf-8", errors="replace"))
            decoded = completed.stdout.decode("utf-8")
            self.assertIn("四国めたん", decoded)
            self.assertEqual("1.0.0", json.loads(decoded)["result"]["schemaVersion"])


if __name__ == "__main__":
    unittest.main()
