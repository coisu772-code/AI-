from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(os.name == "nt" and shutil.which("powershell"), "Windows PowerShell integration requires Windows")
class WindowsPowerShellMcpFileRelayTests(unittest.TestCase):
    def test_real_mcp_tools_and_capabilities_accept_no_bom_jsonl_file_relay(self) -> None:
        completed = subprocess.run(
            [
                shutil.which("powershell") or "powershell",
                "-NoProfile",
                "-NonInteractive",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(ROOT / "tools/Test-McpFileRelay.ps1"),
                "-PythonExecutable",
                sys.executable,
                "-ServerScript",
                str(ROOT / "plugins/ai-video-channel-production/mcp/server.py"),
                "-AsJson",
            ],
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        self.assertEqual("", completed.stderr.strip())
        report = json.loads(completed.stdout.lstrip("\ufeff"))
        self.assertEqual("PASS", report["status"])
        self.assertTrue(report["powershell"]["desktop51"])
        self.assertEqual("NO_BOM_JSONL_FILE_PYTHON_RELAY", report["transport"]["mode"])
        self.assertEqual([0, 0, 0, 0], report["transport"]["requestPreambleBytes"])
        self.assertFalse(report["transport"]["powershellInputRedirection"])
        self.assertFalse(report["transport"]["powershellInputObjectAccess"])
        self.assertEqual("PASS", report["transport"]["unicodeJsonProbe"])
        self.assertEqual(0, report["fileRelay"]["exitCode"])
        self.assertEqual([0, 0, 0, 0], report["fileRelay"]["exitCodes"])
        self.assertEqual("efbbbf580a", report["controlledRootCauseEvidence"]["rawStdinProbeHex"])
        self.assertEqual(0, report["controlledRootCauseEvidence"]["fileRelay"]["exitCode"])
        self.assertEqual(
            {"content_capabilities", "production_capabilities", "data_center_capabilities"},
            set(report["toolsList"]["required"]),
        )
        self.assertEqual(
            {"content_capabilities": "PASS", "production_capabilities": "PASS", "data_center_capabilities": "PASS"},
            report["capabilities"],
        )


if __name__ == "__main__":
    unittest.main()
