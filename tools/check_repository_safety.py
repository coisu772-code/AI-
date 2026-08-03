from __future__ import annotations

import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
EXCLUDED_DIRS = {
    ".git",
    ".venv",
    ".stage1-smoke",
    ".stage1-codex-home",
    ".stage2-isolated",
    ".stage3-isolated",
    ".stage4-plugin-isolated",
    ".stage5-plugin-isolated",
    ".stage5-output-isolated",
    ".stage6-r3-source",
    ".github-install-smoke",
    ".release-tools",
    "__pycache__",
    "dist",
}
FORBIDDEN_SUFFIXES = {
    ".db", ".sqlite", ".sqlite3", ".exe", ".msi", ".mp3", ".wav",
    ".mp4", ".mov", ".mkv", ".png", ".jpg", ".jpeg", ".webp",
}
ALLOWED_SYNTHETIC_MEDIA_FIXTURES = {
    "contracts/examples/valid/fixtures/confirmed-thumbnail-1600x900.png",
    "tests/fixtures/stage4/packages/en-US/publishing-asset-package/confirmed-thumbnail.png",
    "tests/fixtures/stage4/packages/ja-JP/publishing-asset-package/confirmed-thumbnail.png",
    "tests/fixtures/stage4/packages/zh-CN/publishing-asset-package/confirmed-thumbnail.png",
}
SENSITIVE_NAME = re.compile(r"(?:secret|credential|cookie|oauth|client_secret)", re.IGNORECASE)
PRIVATE_KEY_MARKERS = (
    b"-----BEGIN " + b"PRIVATE KEY-----",
    b"-----BEGIN RSA " + b"PRIVATE KEY-----",
    b"-----BEGIN OPENSSH " + b"PRIVATE KEY-----",
)
SENSITIVE_TEXT = (
    re.compile(rb"\bya29\.[A-Za-z0-9_-]{40,}"),
    re.compile(rb"\bAIza[0-9A-Za-z_-]{30,}"),
    re.compile(rb"\bGOCSPX-[A-Za-z0-9_-]{20,}"),
    re.compile(rb"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(rb"\bgh[pousr]_[A-Za-z0-9]{30,}\b"),
    re.compile(rb"\bgithub_pat_[A-Za-z0-9_]{50,}\b"),
    re.compile(rb"\bsk-[A-Za-z0-9_-]{20,}\b"),
)


def repository_files() -> list[Path]:
    return [
        path
        for path in ROOT.rglob("*")
        if path.is_file() and not any(part in EXCLUDED_DIRS for part in path.relative_to(ROOT).parts)
    ]


def check_repository_safety() -> list[str]:
    errors: list[str] = []
    for path in repository_files():
        relative = path.relative_to(ROOT).as_posix()
        lowered = path.name.lower()
        if path.suffix.lower() in FORBIDDEN_SUFFIXES and relative not in ALLOWED_SYNTHETIC_MEDIA_FIXTURES:
            errors.append(f"forbidden release file type: {relative}")
        if SENSITIVE_NAME.search(path.name) and path.name != ".env.example":
            errors.append(f"sensitive-looking filename: {relative}")
        if lowered == ".env" or (lowered.startswith(".env.") and lowered != ".env.example"):
            errors.append(f"environment file is not allowed: {relative}")
        if path.stat().st_size > 10 * 1024 * 1024:
            errors.append(f"unexpected large file: {relative}")
            continue
        content = path.read_bytes()
        if any(marker in content for marker in PRIVATE_KEY_MARKERS):
            errors.append(f"private key material detected: {relative}")
        if any(pattern.search(content) for pattern in SENSITIVE_TEXT):
            errors.append(f"sensitive material signature detected: {relative}")
    return errors


def main() -> int:
    errors = check_repository_safety()
    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        print(f"Repository safety check failed with {len(errors)} error(s).")
        return 1
    print(f"Repository safety check passed: {len(repository_files())} file(s).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
