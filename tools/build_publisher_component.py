from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import zipfile
from pathlib import Path, PurePosixPath


FIXED_TIME = (2026, 8, 7, 0, 0, 0)
BINARY_NAMES = (
    "youtube-publisher-center.exe",
    "publish-package-v2.exe",
    "channel-list.exe",
)
REPLACED_DOCUMENTS = {
    "docs/publish-package-v2-live-execution.md",
    "SHA256SUMS.txt",
}
SOURCE_EXCLUDES = {".git", "artifacts", "build", "dist", "node_modules"}


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def normalize_entry(name: str, old_root: str) -> str:
    normalized = name.replace("\\", "/").lstrip("/")
    prefix = old_root.rstrip("/") + "/"
    if not normalized.startswith(prefix):
        raise RuntimeError(f"unexpected base archive entry: {name}")
    relative = normalized[len(prefix) :]
    path = PurePosixPath(relative)
    if path.is_absolute() or ".." in path.parts:
        raise RuntimeError(f"unsafe base archive entry: {name}")
    return relative


def text(value: str) -> bytes:
    return value.replace("\r\n", "\n").replace("\r", "\n").encode("utf-8")


def source_snapshot(root: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    count = 0
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root)
        if not path.is_file() or any(part in SOURCE_EXCLUDES for part in relative.parts):
            continue
        payload = path.read_bytes()
        name = relative.as_posix().encode("utf-8")
        digest.update(len(name).to_bytes(4, "big"))
        digest.update(name)
        digest.update(len(payload).to_bytes(8, "big"))
        digest.update(payload)
        count += 1
    return digest.hexdigest(), count


def zip_info(name: str) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(name, FIXED_TIME)
    info.compress_type = zipfile.ZIP_DEFLATED
    info.create_system = 3
    info.external_attr = (0o100644 << 16)
    info.flag_bits |= 0x800
    return info


def build(args: argparse.Namespace) -> dict[str, object]:
    base_zip = Path(args.base_zip).resolve(strict=True)
    binary_dir = Path(args.binary_dir).resolve(strict=True)
    output_dir = Path(args.output_dir).resolve()
    source_root = Path(args.source_root).resolve(strict=True)
    output_dir.mkdir(parents=True, exist_ok=True)
    version = args.version
    new_root = f"youtube-publisher-center-v{version}-windows-amd64"
    archive_name = f"{new_root}.zip"
    archive_path = output_dir / archive_name

    files: dict[str, bytes] = {}
    with zipfile.ZipFile(base_zip) as archive:
        roots = {
            entry.filename.replace("\\", "/").split("/", 1)[0]
            for entry in archive.infolist()
            if entry.filename.replace("\\", "/").strip("/")
        }
        if len(roots) != 1:
            raise RuntimeError("base publisher archive must contain exactly one root")
        old_root = next(iter(roots))
        for entry in archive.infolist():
            if entry.is_dir():
                continue
            relative = normalize_entry(entry.filename, old_root)
            basename = PurePosixPath(relative).name
            if basename in BINARY_NAMES or relative in REPLACED_DOCUMENTS:
                continue
            if basename.startswith(("README-v", "INSTALL-UPGRADE-ROLLBACK-v", "SECURITY-REVIEW-v")):
                continue
            files[relative] = archive.read(entry)

    for name in BINARY_NAMES:
        path = binary_dir / name
        if not path.is_file():
            raise RuntimeError(f"missing publisher binary: {name}")
        files[name] = path.read_bytes()

    files[f"README-v{version}.md"] = text(
        f"""# YouTube 发布中心 {version}\n\n"
        "此组件由 AI 视频频道生产系统统一安装，用于管理频道授权、审核发布任务并执行真实 YouTube 上传。\n\n"
        "- `publish-package-v2.exe`：离线校验并把正式发布包交接到发布中心主数据库；该命令本身不联网、不执行 OAuth、不上传。\n"
        "- `youtube-publisher-center.exe`：桌面发布中心；只有频道 OAuth 有效、策略和上传意图均满足安全门时，才由它调用 YouTube API。\n"
        "- `channel-list.exe`：只读输出可用频道档案，供 Codex 校验频道序号和身份。\n\n"
        "升级不会把 OAuth 凭据、频道资料、任务数据库或用户媒体打进安装包。\n"
    )
    files[f"INSTALL-UPGRADE-ROLLBACK-v{version}.md"] = text(
        f"""# 安装、升级与回退 {version}\n\n"
        "请通过 AI 视频频道生产系统统一安装器安装或升级本组件。程序文件按版本隔离，用户频道、OAuth 和任务数据保存在独立数据目录。升级失败时统一安装器会恢复上一个活动版本。\n\n"
        "升级后重新启动 Codex 和 YouTube 发布中心。首次真实上传仍必须在发布中心完成账号 OAuth，并按界面确认频道、隐私状态和发布策略。\n"
    )
    files[f"SECURITY-REVIEW-v{version}.md"] = text(
        f"""# 安全边界 {version}\n\n"
        "Codex 交接命令固定为 `network_execution=false`，只进行本地校验、复制和数据库导入。真实 OAuth 与 YouTube API 调用只属于桌面发布中心。\n\n"
        "AUTO 任务仍要求：频道启用、OAuth 状态 ACTIVE、频道默认策略 AUTO、任务策略 AUTO、目标频道身份一致，以及已保存的自动上传授权。任何条件不足都会停在人工审核。\n"
    )
    files["docs/publish-package-v2-live-execution.md"] = text(
        """# Publish Package v2 正式交接\n\n"
        "`handoff` 将外部 `.ready` 包非破坏性复制到发布中心正式队列，使用真实 ffprobe、正式频道档案和主数据库重新校验后创建任务。它不会执行网络请求或启动上传。\n\n"
        "`status-live` 从主数据库读取任务状态；`receipt-live` 只在桌面发布中心真实上传并保存 YouTube video ID 后返回发布回执。\n\n"
        "`import/status/receipt` 继续保留给合成验收夹具使用，不作为真实用户默认路径。\n"
    )

    # Replace the inherited release notes with UTF-8 Chinese documentation for
    # the v2.1.0 handoff contract. These assignments intentionally come after
    # the legacy template so the packaged files cannot inherit mojibake.
    files[f"README-v{version}.md"] = text(
        f"""# YouTube 发布中心 {version}

此组件由 AI 视频频道生产系统统一安装，用于管理频道授权、审核发布任务并执行真实 YouTube 上传。

- `publish-package-v2.exe`：离线校验并导入 Publish Package v2.1.0；本命令不联网、不执行 OAuth、不上传。
- `youtube-publisher-center.exe`：桌面发布中心；只有最终中文验收、频道身份、OAuth、隐私和上传策略全部通过后，才可能调用 YouTube API。
- `channel-list.exe`：只读输出可用频道档案，供频道序号和身份校验。

升级包不包含 OAuth 凭据、频道资料、任务数据库或用户媒体。
"""
    )
    files[f"INSTALL-UPGRADE-ROLLBACK-v{version}.md"] = text(
        f"""# 安装、升级与回退 {version}

请通过 AI 视频频道生产系统统一安装器安装或升级本组件。程序文件按版本隔离；用户频道、OAuth 和任务数据保存在独立数据目录。升级失败时，统一安装器恢复上一个活动版本。

升级后请重新启动 Codex 和 YouTube 发布中心。首次真实上传仍须在发布中心完成账号 OAuth，并按界面确认最终中文验收、频道、隐私状态和发布策略。
"""
    )
    files[f"SECURITY-REVIEW-v{version}.md"] = text(
        f"""# 安全边界 {version}

Codex 交接命令固定为 `network_execution=false`，只进行本地校验、复制和数据库导入。真实 OAuth 与 YouTube API 调用只属于桌面发布中心。

所有 MANUAL、SCHEDULED 和 AUTO 任务在本次最终中文验收前都必须停在 `FINAL_CHINESE_REVIEW_CONFIRMATION_REQUIRED`。确认该卡只解除这一项阻断；频道停用、OAuth 无效、频道身份不一致、每日限额或其他安全门仍会继续阻断。AUTO 不能跳过最终中文验收。
"""
    )
    files["docs/publish-package-v2-live-execution.md"] = text(
        """# Publish Package v2.1.0 正式交接

`handoff` 将外部 `.ready` 包非破坏性复制到发布中心正式队列，使用真实 ffprobe、正式频道档案和主数据库重新校验后创建任务；它不执行网络请求或启动上传。

包内必须包含 `FINAL_CHINESE_REVIEW_CARD.md` 与 `final_chinese_review_card.json`。无论上传策略为何，任务都先停在 `FINAL_CHINESE_REVIEW_CONFIRMATION_REQUIRED`，只有用户完成本次最终中文验收后才会解除该阻断。

`status-live` 从主数据库读取任务状态；`receipt-live` 只在桌面发布中心真实上传并保存 YouTube video ID 后返回发布回执。
"""
    )

    checksum_lines = []
    for relative, payload in sorted(files.items()):
        checksum_lines.append(f"{sha256_bytes(payload)}  {relative}\n")
    files["SHA256SUMS.txt"] = "".join(checksum_lines).encode("ascii")

    with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for relative, payload in sorted(files.items()):
            archive.writestr(zip_info(f"{new_root}/{relative}"), payload)

    head = subprocess.check_output(
        ["git", "-C", str(source_root.parent), "rev-parse", "HEAD"],
        text=True,
        encoding="utf-8",
    ).strip()
    status = subprocess.check_output(
        ["git", "-C", str(source_root.parent), "status", "--porcelain", "--", source_root.name],
        text=True,
        encoding="utf-8",
    ).strip()
    snapshot_sha, source_files = source_snapshot(source_root)
    components = []
    for name in BINARY_NAMES:
        payload = files[name]
        components.append({"path": name, "size_bytes": len(payload), "sha256": sha256_bytes(payload)})

    manifest = {
        "schema_version": "1.3",
        "component": "youtube-publisher-center",
        "display_name": "YouTube 发布中心",
        "version": version,
        "release_channel": "beta",
        "distribution": "local-release-candidate",
        "source": {
            "baseline_commit": head,
            "working_tree_clean": not bool(status),
            "snapshot_sha256": snapshot_sha,
            "snapshot_file_count": source_files,
        },
        "target": {"os": "windows", "arch": "amd64", "packaging": "portable-zip", "desktop_runtime": "Wails v2.12.0"},
        "release_asset": {
            "name": archive_name,
            "size_bytes": archive_path.stat().st_size,
            "sha256": sha256_file(archive_path),
            "zip_entries": len(files),
            "file_entries": len(files),
        },
        "components": components,
        "legal_inventory": {
            "product_license": {"path": "LICENSE.md", "sha256": sha256_bytes(files["LICENSE.md"])},
            "notices_json": {"path": "THIRD-PARTY-NOTICES.json", "sha256": sha256_bytes(files["THIRD-PARTY-NOTICES.json"])},
            "notices_markdown": {"path": "THIRD-PARTY-NOTICES.md", "sha256": sha256_bytes(files["THIRD-PARTY-NOTICES.md"])},
            "license_text_files": sum(1 for name in files if name.startswith("third-party-licenses/") and not name.endswith("/")),
            "review_required": 0,
        },
        "integration_contract": {
            "constraints_catalog_version": "2026.08.04.1",
            "constraints_catalog_sha256": "28788480458f37ba86584b4c63e0ef998081ac521ecd9fd0b1724c2a6074b99a",
            "line_ending_normalization": "CRLF and CR normalize to LF before SHA-256",
            "publish_package_version": "2.1.0",
            "formal_handoff": True,
            "live_status": True,
            "live_receipt": True,
            "final_chinese_review_card_required": True,
        },
        "safety_contract": {
            "codex_handoff_network_execution": False,
            "oauth_owner": "youtube-publisher-center-desktop",
            "upload_execution_owner": "youtube-publisher-center-desktop",
            "credentials_included": False,
            "user_data_included": False,
            "auto_requires_explicit_channel_authorization": True,
            "final_chinese_review_required_for_all_upload_policies": True,
            "final_chinese_review_blocker": "FINAL_CHINESE_REVIEW_CONFIRMATION_REQUIRED",
            "publication_receipt_after_remote_video_id_only": True,
        },
    }
    manifest_path = output_dir / f"publisher-component-manifest-v{version}.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    return {"archive": str(archive_path), "manifest": str(manifest_path), "release_asset": manifest["release_asset"]}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-zip", required=True)
    parser.add_argument("--binary-dir", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--source-root", required=True)
    parser.add_argument("--version", required=True)
    result = build(parser.parse_args())
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
