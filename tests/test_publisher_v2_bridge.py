from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch


ROOT = Path(__file__).resolve().parents[1]
MCP_ROOT = ROOT / "plugins" / "ai-video-channel-production" / "mcp"
if str(MCP_ROOT) not in sys.path:
    sys.path.insert(0, str(MCP_ROOT))

from aivcp_tools.publisher_v2_bridge import PublisherV2Bridge  # noqa: E402


class PublisherV2BridgeTests(unittest.TestCase):
    @patch("aivcp_tools.publisher_v2_bridge.subprocess.Popen")
    def test_formal_handoff_can_start_desktop_execution_owner(self, popen: Mock) -> None:
        popen.return_value.pid = 4312
        bridge = PublisherV2Bridge(
            Path("publish-package-v2.exe"),
            Path("youtube-publisher-center.exe"),
        )
        result = bridge._ensure_publisher_running()
        self.assertEqual({"configured": True, "started": True, "pid": 4312}, result)
        popen.assert_called_once()
        self.assertEqual(["youtube-publisher-center.exe"], popen.call_args.args[0])


if __name__ == "__main__":
    unittest.main()
