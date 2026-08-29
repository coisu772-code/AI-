from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MCP_ROOT = ROOT / "plugins" / "ai-video-channel-production" / "mcp"
if str(MCP_ROOT) not in sys.path:
    sys.path.insert(0, str(MCP_ROOT))

from aivcp_tools.production import _write_copy  # noqa: E402
from aivcp_tools.publish_package_v2 import _copy_asset  # noqa: E402


class ZeroCopyAssetTests(unittest.TestCase):
    def test_production_result_uses_same_volume_hardlink(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source.mp4"
            destination = root / "result" / "final-video.mp4"
            source.write_bytes(b"video-bytes")
            _write_copy(source, destination)
            self.assertTrue(os.path.samefile(source, destination))

    def test_publish_assembly_uses_same_volume_hardlink(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source.mp4"
            destination = root / "final.mp4"
            source.write_bytes(b"video-bytes")
            _copy_asset(source, destination)
            self.assertTrue(os.path.samefile(source, destination))


if __name__ == "__main__":
    unittest.main()
