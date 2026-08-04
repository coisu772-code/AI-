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
class WindowsPowerShellMcpStdinTests(unittest.TestCase):
    def test_real_mcp_tools_and_capabilities_accept_no_bom_utf8_stdin(self) -> None:
        completed = subprocess.run(
            [
                shutil.which("powershell") or "powershell",
                "-NoProfile",
                "-NonInteractive",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(ROOT / "tools/Test-McpUtf8Stdin.ps1"),
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
        self.assertEqual(0, report["stdin"]["preambleBytes"])
        self.assertTrue(report["stdin"]["rawBaseStreamWrite"])
        self.assertEqual("PASS", report["stdin"]["unicodeJsonProbe"])
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
