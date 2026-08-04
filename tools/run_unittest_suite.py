from __future__ import annotations

import argparse
import json
import sys
import unittest
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the full unit suite and write exact machine-readable counts")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    suite = unittest.defaultTestLoader.discover(str(root / "tests"), pattern="test_*.py")
    result = unittest.TextTestRunner(stream=sys.stderr, verbosity=1).run(suite)
    summary = {
        "schemaVersion": "1.0.0",
        "status": "PASS" if result.wasSuccessful() else "FAIL",
        "total": result.testsRun,
        "passed": result.testsRun - len(result.failures) - len(result.errors) - len(result.skipped) - len(result.expectedFailures),
        "failed": len(result.failures),
        "errors": len(result.errors),
        "skipped": len(result.skipped),
        "expectedFailures": len(result.expectedFailures),
        "unexpectedSuccesses": len(result.unexpectedSuccesses),
    }
    args.output.resolve().write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps(summary, sort_keys=True))
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
