from __future__ import annotations

import hashlib
import json
import mimetypes
import os
import re
import shutil
import struct
import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime
from fractions import Fraction
from pathlib import Path, PurePosixPath
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .contracts import canonical_hash


PROTOCOL = "youtube-publish-package-v2"
SCHEMA_VERSION = "2.0"
PACKAGE_VERSION = "2.1.0"
LOCAL_STATES = {"PACKAGE_READY", "WAITING_REVIEW", "READY_TO_UPLOAD"}
REMOTE_STATES = {
    "UPLOADING",
    "VIDEO_CREATED_PRIVATE",
    "POST_PROCESSING",
    "UPLOADED_PRIVATE",
    "UPLOADED_UNLISTED",
    "SCHEDULED",
    "PUBLISHED",
    "RECEIPT_COMPLETE",
}
POLICIES = {"DO_NOT_UPLOAD", "REQUIRE_REVIEW", "AUTO"}
PRIVACY = {"private", "unlisted", "public", "scheduled"}
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
HASHTAG_PATTERN = re.compile(r"^#[^#\s]{1,99}$")
PRIVACY_ZH = {"private": "私享", "unlisted": "不公开", "public": "公开", "scheduled": "定时公开"}
UPLOAD_POLICY_ZH = {"DO_NOT_UPLOAD": "只生成发布包，不上传", "REQUIRE_REVIEW": "人工确认后上传", "AUTO": "已授权自动上传（仍须本次最终中文验收）"}


class PublishPackageError(RuntimeError):
    def __init__(self, code: str, message: str, *, details: dict[str, Any] | None = None):
        super().__init__(message)
        self.code = code
        self.details = details or {}


@dataclass(frozen=True)
class PackageSources:
    production_result_root: Path
    publishing_asset_root: Path
    production_result: dict[str, Any]
    publishing_asset: dict[str, Any]


def _utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _load_json(path: Path) -> dict[str, Any]:
    def no_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise PublishPackageError("PUBLISH_JSON_DUPLICATE_KEY", f"JSON contains duplicate key: {key}")
            result[key] = value
        return result

    try:
        value = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=no_duplicates)
    except PublishPackageError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise PublishPackageError("PUBLISH_JSON_INVALID", f"Cannot read JSON: {path.name}") from exc
    if not isinstance(value, dict):
        raise PublishPackageError("PUBLISH_JSON_INVALID", f"JSON root must be an object: {path.name}")
    return value


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, allow_nan=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _validate_chinese_review(publishing: dict[str, Any]) -> dict[str, Any]:
    review = publishing.get("chineseReview")
    if not isinstance(review, dict):
        raise PublishPackageError("PUBLISH_CHINESE_REVIEW_REQUIRED", "Publishing asset package is missing the Chinese review data")
    if review.get("displayMode") != "CHINESE_FIRST_WITH_TARGET_LANGUAGE" or review.get("uploadUseAllowed") is not False:
        raise PublishPackageError("PUBLISH_CHINESE_REVIEW_INVALID", "Chinese review data has an invalid display or production-use boundary")
    for field in ("storySummaryZh", "titleZh", "descriptionZh", "thumbnailTextZh"):
        value = review.get(field)
        if not isinstance(value, str) or not value.strip():
            raise PublishPackageError("PUBLISH_CHINESE_REVIEW_INVALID", f"Chinese review field is missing: {field}")
    if review.get("titleZh") != publishing.get("titleZhTranslation"):
        raise PublishPackageError("PUBLISH_CHINESE_REVIEW_INVALID", "Chinese review title does not match the frozen title translation")
    translations = review.get("hashtagTranslations")
    hashtags = publishing.get("hashtags")
    if (
        not isinstance(translations, list)
        or not isinstance(hashtags, list)
        or len(translations) != len(hashtags)
        or any(
            not isinstance(item, dict)
            or item.get("hashtag") != hashtag
            or not isinstance(item.get("chinese"), str)
            or not item["chinese"].strip()
            for item, hashtag in zip(translations, hashtags, strict=True)
        )
    ):
        raise PublishPackageError("PUBLISH_CHINESE_REVIEW_INVALID", "Chinese hashtag translations do not match the frozen hashtags")
    voices = review.get("voiceSummary")
    if not isinstance(voices, list) or not voices:
        raise PublishPackageError("PUBLISH_CHINESE_REVIEW_INVALID", "Chinese review voice summary is missing")
    return review


def _final_chinese_review_card(
    *,
    intent_id: str,
    result: dict[str, Any],
    publishing: dict[str, Any],
    channel_profile: dict[str, Any],
    final_video: Path,
    final_thumbnail: Path,
) -> dict[str, Any]:
    review = _validate_chinese_review(publishing)
    policy = publishing["uploadPolicy"]
    privacy = publishing["privacyStatus"]
    return {
        "schemaVersion": "1.0.0",
        "displayMode": "CHINESE_FIRST_WITH_TARGET_LANGUAGE",
        "displayLanguage": "zh-CN",
        "gate": "G6_FINAL_CHINESE_UPLOAD_REVIEW",
        "publishIntentId": intent_id,
        "projectId": result["projectId"],
        "chinesePrimary": {
            "titleZh": review["titleZh"],
            "storySummaryZh": review["storySummaryZh"],
            "descriptionZh": review["descriptionZh"],
            "hashtagsZh": [item["chinese"] for item in review["hashtagTranslations"]],
            "thumbnailTextZh": review["thumbnailTextZh"],
            "voices": review["voiceSummary"],
            "channel": {
                "channelProfileId": channel_profile["channel_profile_id"],
                "publisherProfileId": channel_profile["publisher_profile_id"],
                "channelSerial": channel_profile["channel_serial"],
                "youtubeChannelId": channel_profile["expected_channel_id"],
            },
            "privacyStatusZh": PRIVACY_ZH[privacy],
            "uploadPolicyZh": UPLOAD_POLICY_ZH[policy],
            "decisionRequiredZh": "请集中核对故事、包装、配音、频道、隐私状态和上传策略；明确确认后才允许进入真实上传。",
        },
        "targetLanguageComparison": {
            "labelZh": "目标语言对照",
            "language": publishing["targetLanguage"],
            "sameAsChinese": publishing["targetLanguage"].lower().startswith("zh"),
            "title": publishing["title"],
            "description": publishing["descriptionBody"],
            "hashtags": publishing["hashtags"],
            "thumbnailText": publishing["thumbnailStrategy"]["targetLanguageText"],
        },
        "finalAssets": {
            "video": {"path": final_video.name, "sha256": _sha256_file(final_video), "sizeBytes": final_video.stat().st_size},
            "thumbnail": {"path": final_thumbnail.name, "sha256": _sha256_file(final_thumbnail), "sizeBytes": final_thumbnail.stat().st_size},
        },
        "confirmation": {
            "required": policy != "DO_NOT_UPLOAD",
            "status": "NOT_REQUESTED" if policy == "DO_NOT_UPLOAD" else "AWAITING_USER_CONFIRMATION",
            "confirmed": False,
        },
        "uploadUseOfChineseTranslations": False,
        "networkExecution": False,
    }


def _render_final_chinese_review_markdown(card: dict[str, Any]) -> str:
    zh = card["chinesePrimary"]
    target = card["targetLanguageComparison"]
    lines = [
        "# 上传前最终中文验收卡",
        "",
        "> 本卡中文内容用于审核，不会替换正式目标语言发布字段。确认前不会执行真实上传。",
        "",
        "## 一、中文集中验收",
        "",
        f"- 故事：{zh['storySummaryZh']}",
        f"- 标题：{zh['titleZh']}",
        f"- 简介：{zh['descriptionZh']}",
        f"- 标签：{'；'.join(zh['hashtagsZh'])}",
        f"- 封面文案：{zh['thumbnailTextZh']}",
        f"- 频道：序号 {zh['channel']['channelSerial']}／{zh['channel']['youtubeChannelId']}",
        f"- 隐私状态：{zh['privacyStatusZh']}",
        f"- 上传策略：{zh['uploadPolicyZh']}",
        "",
        "### 配音",
        "",
        "| 角色/说话人 | 角色功能 | 引擎 | 音色 | 音色 ID |",
        "|---|---|---|---|---|",
    ]
    for voice in zh["voices"]:
        lines.append(
            f"| {voice['targetLanguageName']} ({voice['speakerId']}) | {voice['role']} | {voice['engine']} | {voice['voiceName']} | {voice['voiceId']} |"
        )
    lines.extend(
        [
            "",
            f"## 二、目标语言对照（{target['language']}）",
            "",
            f"- 标题：{target['title']}",
            f"- 封面文案：{target['thumbnailText']}",
            f"- Hashtags：{' '.join(target['hashtags'])}",
            "",
            "### 正式简介",
            "",
            target["description"],
            "",
            "## 三、确认结论",
            "",
            f"- 当前状态：{card['confirmation']['status']}",
            f"- 操作要求：{zh['decisionRequiredZh']}",
            "",
        ]
    )
    return "\n".join(lines)


def _safe_relative_path(value: Any, *, field: str) -> str:
    if not isinstance(value, str) or not value or "\\" in value or "\x00" in value:
        raise PublishPackageError("PUBLISH_PATH_UNSAFE", f"{field} must be a normalized package-relative path")
    pure = PurePosixPath(value)
    if value != pure.as_posix() or pure.is_absolute() or any(part in {"", ".", ".."} for part in pure.parts):
        raise PublishPackageError("PUBLISH_PATH_UNSAFE", f"{field} escapes or is not normalized: {value}")
    if re.match(r"^[A-Za-z]:", value):
        raise PublishPackageError("PUBLISH_PATH_UNSAFE", f"{field} must not contain a drive prefix")
    return pure.as_posix()


def _resolve_member(root: Path, relative: Any, *, field: str, must_exist: bool = True) -> Path:
    normalized = _safe_relative_path(relative, field=field)
    if root.is_symlink():
        raise PublishPackageError("PUBLISH_SYMLINK_FORBIDDEN", f"Package root is a symbolic link: {root}")
    candidate = root.joinpath(*PurePosixPath(normalized).parts)
    current = root
    for part in PurePosixPath(normalized).parts:
        current = current / part
        if current.is_symlink():
            raise PublishPackageError("PUBLISH_SYMLINK_FORBIDDEN", f"Symbolic links are forbidden: {normalized}")
    try:
        candidate.resolve(strict=must_exist).relative_to(root.resolve(strict=True))
    except (OSError, ValueError) as exc:
        raise PublishPackageError("PUBLISH_PATH_UNSAFE", f"Path is outside package root: {normalized}") from exc
    if must_exist and not candidate.is_file():
        raise PublishPackageError("PUBLISH_FILE_MISSING", f"Required file is missing: {normalized}")
    return candidate


def _actual_files(root: Path) -> set[str]:
    found: set[str] = set()
    for path in root.rglob("*"):
        relative = path.relative_to(root).as_posix()
        if path.is_symlink():
            raise PublishPackageError("PUBLISH_SYMLINK_FORBIDDEN", f"Symbolic links are forbidden: {relative}")
        if path.is_file():
            found.add(relative)
    return found


def _validate_sha(value: Any, *, field: str) -> str:
    if not isinstance(value, str) or not SHA256_PATTERN.fullmatch(value):
        raise PublishPackageError("PUBLISH_HASH_INVALID", f"{field} is not a lowercase SHA-256 value")
    return value


def _validate_declared_file(root: Path, item: dict[str, Any], *, prefix: str = "files") -> Path:
    if not isinstance(item, dict):
        raise PublishPackageError("PUBLISH_MANIFEST_INVALID", f"{prefix} item must be an object")
    path = _resolve_member(root, item.get("path"), field=f"{prefix}.path")
    expected_hash = _validate_sha(item.get("sha256"), field=f"{prefix}.sha256")
    expected_size = item.get("sizeBytes", item.get("size_bytes"))
    if not isinstance(expected_size, int) or isinstance(expected_size, bool) or expected_size < 0:
        raise PublishPackageError("PUBLISH_SIZE_INVALID", f"{prefix}.size is invalid")
    if path.stat().st_size != expected_size:
        raise PublishPackageError("PUBLISH_SIZE_MISMATCH", f"Size mismatch: {item.get('path')}")
    if _sha256_file(path) != expected_hash:
        raise PublishPackageError("PUBLISH_HASH_MISMATCH", f"SHA-256 mismatch: {item.get('path')}")
    return path


def _validate_contract_hash(document: dict[str, Any], *, expected_type: str, status: str) -> None:
    if document.get("contractType") != expected_type or document.get("status") != status:
        raise PublishPackageError("PUBLISH_UPSTREAM_CONTRACT_INVALID", f"Expected {expected_type} in {status}")
    if canonical_hash(document) != document.get("contentHash"):
        raise PublishPackageError("PUBLISH_UPSTREAM_HASH_MISMATCH", f"Invalid canonical hash: {expected_type}")


def _load_sources(production_result_root: Path, publishing_asset_root: Path) -> PackageSources:
    result_root = production_result_root.resolve(strict=True)
    publishing_root = publishing_asset_root.resolve(strict=True)
    if production_result_root.is_symlink() or publishing_asset_root.is_symlink():
        raise PublishPackageError("PUBLISH_SYMLINK_FORBIDDEN", "Upstream package roots must not be symbolic links")
    result = _load_json(result_root / "manifest.json")
    publishing = _load_json(publishing_root / "manifest.json")
    _validate_contract_hash(result, expected_type="production-result-package", status="VIDEO_READY")
    _validate_contract_hash(publishing, expected_type="publishing-asset-package", status="PUBLISHING_ASSETS_READY")

    declared: set[str] = set()
    for index, item in enumerate(result.get("files", [])):
        if not isinstance(item, dict):
            raise PublishPackageError("PUBLISH_RESULT_MANIFEST_INVALID", "Production result files must be objects")
        relative = _safe_relative_path(item.get("path"), field=f"production_result.files[{index}].path")
        if relative in declared:
            raise PublishPackageError("PUBLISH_DUPLICATE_FILE", f"Duplicate production result path: {relative}")
        declared.add(relative)
        _validate_declared_file(result_root, item, prefix=f"production_result.files[{index}]")
    actual = _actual_files(result_root) - {"manifest.json"}
    if actual != declared:
        raise PublishPackageError(
            "PUBLISH_RESULT_UNDECLARED_FILE",
            "Production result package contains missing or undeclared files",
            details={"undeclared": sorted(actual - declared), "missing": sorted(declared - actual)},
        )

    for field in ("finalVideo", "subtitles"):
        asset = result.get(field)
        if not isinstance(asset, dict):
            raise PublishPackageError("PUBLISH_RESULT_ASSET_MISSING", f"Production result is missing {field}")
        relative = _safe_relative_path(asset.get("relativePath"), field=f"production_result.{field}.relativePath")
        if relative not in declared:
            raise PublishPackageError("PUBLISH_RESULT_ASSET_UNDECLARED", f"{field} is not declared in result files")
        _validate_declared_file(
            result_root,
            {"path": relative, "sha256": asset.get("sha256"), "sizeBytes": asset.get("sizeBytes")},
            prefix=f"production_result.{field}",
        )

    thumbnail = publishing.get("thumbnail")
    if not isinstance(thumbnail, dict) or thumbnail.get("mode") != "real_file":
        raise PublishPackageError("PUBLISH_THUMBNAIL_MISSING", "Publishing asset package must contain one real thumbnail")
    thumbnail_asset = thumbnail.get("asset")
    if not isinstance(thumbnail_asset, dict):
        raise PublishPackageError("PUBLISH_THUMBNAIL_MISSING", "Publishing thumbnail asset is missing")
    thumbnail_path = _resolve_member(
        publishing_root,
        thumbnail_asset.get("relativePath"),
        field="publishing.thumbnail.asset.relativePath",
    )
    if thumbnail_path.stat().st_size != thumbnail_asset.get("sizeBytes") or _sha256_file(thumbnail_path) != thumbnail_asset.get("sha256"):
        raise PublishPackageError("PUBLISH_THUMBNAIL_HASH_MISMATCH", "Publishing thumbnail hash or size does not match")

    if result.get("projectId") != publishing.get("projectId"):
        raise PublishPackageError("PUBLISH_PROJECT_MISMATCH", "Production result and publishing asset project IDs differ")
    if result.get("channelProfileId") != publishing.get("channelProfileId"):
        raise PublishPackageError("PUBLISH_CHANNEL_PROFILE_MISMATCH", "Upstream channel profile IDs differ")
    publishing_refs = [
        item for item in result.get("upstream", [])
        if isinstance(item, dict) and item.get("targetContractType") == "publishing-asset-package"
    ]
    if len(publishing_refs) != 1:
        raise PublishPackageError("PUBLISH_BINDING_MISSING", "Production result must bind exactly one publishing asset package")
    reference = publishing_refs[0]
    expected = (publishing.get("id"), publishing.get("version"), publishing.get("contentHash"))
    actual_ref = (reference.get("targetId"), reference.get("targetVersion"), reference.get("targetHash"))
    if actual_ref != expected:
        raise PublishPackageError("PUBLISH_BINDING_MISMATCH", "Production result binds a different publishing asset version or hash")
    reference_document = _load_json(_resolve_member(result_root, "publishing-assets-reference.json", field="publishing-assets-reference"))
    if reference_document.get("publishingAssetPackage") != reference:
        raise PublishPackageError("PUBLISH_BINDING_MISMATCH", "Production result reference file disagrees with its manifest upstream binding")
    if reference_document.get("publishPackageCreated") is not False:
        raise PublishPackageError("PUBLISH_BOUNDARY_VIOLATION", "Stage5 result must not claim that it created a publish package")
    if result.get("publishingTriggered") is not False:
        raise PublishPackageError("PUBLISH_BOUNDARY_VIOLATION", "Stage5 result must stop at VIDEO_READY without triggering publishing")
    technical_report_path = _resolve_member(result_root, "validation-report.json", field="validation-report")
    if _sha256_file(technical_report_path) != result.get("validationReportHash"):
        raise PublishPackageError("PUBLISH_TECHNICAL_REPORT_MISMATCH", "Production technical report hash does not match the result manifest")
    technical_report = _load_json(technical_report_path)
    if (
        technical_report.get("status") != "PASSED"
        or technical_report.get("videoSha256") != result["finalVideo"]["sha256"]
        or technical_report.get("subtitlesSha256") != result["subtitles"]["sha256"]
    ):
        raise PublishPackageError("PUBLISH_TECHNICAL_REPORT_MISMATCH", "Production technical report does not bind the final video and subtitles")
    publishing_actual = _actual_files(publishing_root)
    thumbnail_relative = thumbnail_asset["relativePath"]
    publishing_expected = {
        "manifest.json", "publishing.json", "thumbnail-strategy.json", "thumbnail-selection.json",
        "ctr-review.json", "description-hashtags.txt", "source-lock.json", thumbnail_relative,
    }
    if publishing_actual != publishing_expected:
        raise PublishPackageError(
            "PUBLISH_ASSET_PACKAGE_FILESET_INVALID",
            "Publishing asset package contains missing, extra, or symbolic-link files",
            details={"extra": sorted(publishing_actual - publishing_expected), "missing": sorted(publishing_expected - publishing_actual)},
        )
    publishing_json = _load_json(_resolve_member(publishing_root, "publishing.json", field="publishing.json"))
    expected_publishing_json = {
        "title": publishing["title"],
        "descriptionBody": publishing["descriptionBody"],
        "hashtags": publishing["hashtags"],
        "thumbnail": thumbnail_relative,
        "thumbnailMode": "real",
        "targetChannel": publishing["targetChannel"],
        "uploadPolicy": publishing["uploadPolicy"],
        "privacyStatus": publishing["privacyStatus"],
    }
    if publishing_json != expected_publishing_json:
        raise PublishPackageError("PUBLISH_ASSET_PACKAGE_MISMATCH", "publishing.json does not match its frozen manifest")
    return PackageSources(result_root, publishing_root, result, publishing)


def _load_catalog(path: Path) -> tuple[dict[str, Any], str]:
    catalog = _load_json(path)
    if catalog.get("schema_version") != "1.0" or not isinstance(catalog.get("catalog_version"), str):
        raise PublishPackageError("PUBLISH_CONSTRAINTS_INVALID", "YouTube constraints catalog is invalid")
    rules = catalog.get("rules")
    if not isinstance(rules, dict):
        raise PublishPackageError("PUBLISH_CONSTRAINTS_INVALID", "Constraints catalog rules are missing")
    # Git may materialize the same JSON contract with CRLF or LF on different
    # machines.  Hash normalized text bytes so checkout policy cannot break the
    # publisher compatibility lock while semantic content remains unchanged.
    normalized = path.read_bytes().replace(b"\r\n", b"\n").replace(b"\r", b"\n")
    return catalog, _sha256_bytes(normalized)


def _parse_iso(value: str, *, timezone: ZoneInfo | None = None) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise PublishPackageError("PUBLISH_TIME_INVALID", f"Invalid ISO-8601 time: {value}") from exc
    if parsed.tzinfo is None:
        if timezone is None:
            raise PublishPackageError("PUBLISH_TIME_INVALID", "Time must include an offset")
        parsed = parsed.replace(tzinfo=timezone)
    return parsed


def _validate_metadata(metadata: dict[str, Any], rules: dict[str, Any]) -> None:
    title = metadata.get("title")
    if not isinstance(title, str) or not title.strip() or len(title) > rules["title_max_characters"]:
        raise PublishPackageError("PUBLISH_TITLE_INVALID", "Title is empty or exceeds the catalog limit")
    if any(char in title for char in rules["title_forbidden_characters"]):
        raise PublishPackageError("PUBLISH_TITLE_INVALID", "Title contains forbidden characters")
    body = metadata.get("description_body")
    hashtags = metadata.get("hashtags")
    combined = metadata.get("description_for_youtube")
    if not isinstance(body, str) or not body.strip():
        raise PublishPackageError("PUBLISH_DESCRIPTION_INVALID", "description_body is required")
    if not isinstance(hashtags, list) or not rules["package_hashtags_min"] <= len(hashtags) <= rules["package_hashtags_max"]:
        raise PublishPackageError("PUBLISH_HASHTAGS_INVALID", "Exactly 8-12 hashtags are required")
    if len(set(hashtags)) != len(hashtags) or any(not isinstance(item, str) or not HASHTAG_PATTERN.fullmatch(item) for item in hashtags):
        raise PublishPackageError("PUBLISH_HASHTAGS_INVALID", "Hashtags must be unique #tokens without whitespace")
    expected = body.rstrip() + "\n\n" + " ".join(hashtags)
    if combined != expected:
        raise PublishPackageError("PUBLISH_DESCRIPTION_MISMATCH", "description_for_youtube must equal body, blank line, and public hashtags")
    if len(combined.encode("utf-8")) > rules["description_max_bytes"]:
        raise PublishPackageError("PUBLISH_DESCRIPTION_INVALID", "YouTube description exceeds the UTF-8 byte limit")
    if any(char in combined for char in rules["description_forbidden_characters"]):
        raise PublishPackageError("PUBLISH_DESCRIPTION_INVALID", "Description contains forbidden characters")
    backend_tags = metadata.get("backend_tags")
    if backend_tags not in ([], None):
        raise PublishPackageError("PUBLISH_BACKEND_TAGS_NOT_EMPTY", "New v2 packages do not generate backend tags")


def _image_dimensions(path: Path) -> tuple[int, int, str]:
    data = path.read_bytes()
    if data.startswith(b"\x89PNG\r\n\x1a\n") and len(data) >= 24:
        return struct.unpack(">II", data[16:24]) + ("image/png",)
    if data.startswith(b"\xff\xd8"):
        offset = 2
        while offset + 9 <= len(data):
            if data[offset] != 0xFF:
                offset += 1
                continue
            marker = data[offset + 1]
            if marker in {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF}:
                height, width = struct.unpack(">HH", data[offset + 5:offset + 9])
                return width, height, "image/jpeg"
            if offset + 4 > len(data):
                break
            length = struct.unpack(">H", data[offset + 2:offset + 4])[0]
            if length < 2:
                break
            offset += 2 + length
    raise PublishPackageError("PUBLISH_THUMBNAIL_INVALID", "Thumbnail cannot be decoded as PNG or JPEG")


def _validate_thumbnail(path: Path, rules: dict[str, Any]) -> dict[str, Any]:
    if path.stat().st_size > rules["thumbnail_api_max_bytes"]:
        raise PublishPackageError("PUBLISH_THUMBNAIL_TOO_LARGE", "Thumbnail exceeds the thumbnails.set API limit")
    width, height, media_type = _image_dimensions(path)
    if width < 16 or height < 9 or abs(width / height - 16 / 9) > 0.02:
        raise PublishPackageError("PUBLISH_THUMBNAIL_ASPECT_INVALID", "Thumbnail must be a readable 16:9 image")
    if media_type not in {"image/png", "image/jpeg"}:
        raise PublishPackageError("PUBLISH_THUMBNAIL_INVALID", "Unsupported thumbnail type")
    return {"width": width, "height": height, "media_type": media_type, "size_bytes": path.stat().st_size}


def _parse_srt_timestamp(value: str) -> float:
    match = re.fullmatch(r"(\d{2,}):(\d{2}):(\d{2})[,.](\d{3})", value.strip())
    if not match:
        raise PublishPackageError("PUBLISH_SUBTITLE_INVALID", f"Invalid subtitle timestamp: {value}")
    hour, minute, second, milli = map(int, match.groups())
    if minute >= 60 or second >= 60:
        raise PublishPackageError("PUBLISH_SUBTITLE_INVALID", f"Invalid subtitle timestamp: {value}")
    return hour * 3600 + minute * 60 + second + milli / 1000


def _parse_subtitles(path: Path) -> tuple[list[tuple[float, float]], str]:
    try:
        text = path.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeError) as exc:
        raise PublishPackageError("PUBLISH_SUBTITLE_INVALID", "Subtitles must be UTF-8") from exc
    cues: list[tuple[float, float]] = []
    timing = re.compile(r"(?m)^\s*((?:\d{2,}:)?\d{2}:\d{2}[,.]\d{3})\s+-->\s+((?:\d{2,}:)?\d{2}:\d{2}[,.]\d{3})")
    for match in timing.finditer(text):
        start_raw, end_raw = match.groups()
        if start_raw.count(":") == 1:
            start_raw = "00:" + start_raw
        if end_raw.count(":") == 1:
            end_raw = "00:" + end_raw
        start = _parse_srt_timestamp(start_raw)
        end = _parse_srt_timestamp(end_raw)
        if end <= start:
            raise PublishPackageError("PUBLISH_SUBTITLE_INVALID", "Subtitle cue end must be after start")
        if cues and start < cues[-1][1]:
            raise PublishPackageError("PUBLISH_SUBTITLE_OVERLAP", "Subtitle cues must be ordered and non-overlapping")
        cues.append((start, end))
    if not cues:
        raise PublishPackageError("PUBLISH_SUBTITLE_EMPTY", "Subtitle file contains no cues")
    visible = timing.sub("", text)
    visible = re.sub(r"(?m)^\s*(?:WEBVTT|\d+)\s*$", "", visible).strip()
    if not visible:
        raise PublishPackageError("PUBLISH_SUBTITLE_EMPTY", "Subtitle file contains no text")
    return cues, visible


def _language_likely(text: str, language: str) -> bool:
    significant = [char for char in text if char.isalpha()]
    if not significant:
        return False
    cjk = sum("\u4e00" <= char <= "\u9fff" for char in significant)
    kana = sum("\u3040" <= char <= "\u30ff" for char in significant)
    latin = sum(("A" <= char <= "Z") or ("a" <= char <= "z") for char in significant)
    primary = language.lower().split("-", 1)[0]
    if primary == "ja":
        return kana >= 1 and (cjk + kana) / len(significant) >= 0.25
    if primary == "zh":
        return cjk >= 2 and cjk / len(significant) >= 0.25 and kana == 0
    if primary == "en":
        return latin >= 8 and latin / len(significant) >= 0.7 and kana == 0 and cjk == 0
    return True


def _probe_video(path: Path, ffprobe_path: str | None = None) -> dict[str, Any]:
    executable = ffprobe_path or shutil.which("ffprobe")
    if not executable:
        raise PublishPackageError("PUBLISH_FFPROBE_UNAVAILABLE", "ffprobe is required for independent video validation")
    command = [
        executable,
        "-v", "error",
        "-show_entries", "format=format_name,duration,size:stream=index,codec_type,codec_name,width,height,r_frame_rate,pix_fmt",
        "-of", "json",
        str(path),
    ]
    completed = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="replace", check=False)
    if completed.returncode != 0:
        raise PublishPackageError("PUBLISH_VIDEO_DECODE_FAILED", "ffprobe could not decode the final MP4")
    try:
        probe = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise PublishPackageError("PUBLISH_VIDEO_DECODE_FAILED", "ffprobe returned invalid JSON") from exc
    streams = probe.get("streams") or []
    video_streams = [item for item in streams if item.get("codec_type") == "video"]
    audio_streams = [item for item in streams if item.get("codec_type") == "audio"]
    if len(video_streams) != 1 or len(audio_streams) != 1:
        raise PublishPackageError("PUBLISH_VIDEO_STREAMS_INVALID", "Final MP4 must contain exactly one video and one audio stream")
    video = video_streams[0]
    audio = audio_streams[0]
    try:
        duration = float((probe.get("format") or {}).get("duration"))
        width = int(video.get("width"))
        height = int(video.get("height"))
    except (TypeError, ValueError) as exc:
        raise PublishPackageError("PUBLISH_VIDEO_DECODE_FAILED", "ffprobe omitted required video properties") from exc
    if duration <= 0 or width <= 0 or height <= 0:
        raise PublishPackageError("PUBLISH_VIDEO_DECODE_FAILED", "Video duration and dimensions must be positive")
    try:
        frame_rate = Fraction(str(video.get("r_frame_rate")))
    except (ValueError, ZeroDivisionError) as exc:
        raise PublishPackageError("PUBLISH_VIDEO_FRAME_RATE_INVALID", "Video frame rate is invalid") from exc
    if frame_rate <= 0:
        raise PublishPackageError("PUBLISH_VIDEO_FRAME_RATE_INVALID", "Video frame rate must be positive")
    if video.get("pix_fmt") not in {"yuv420p", "yuvj420p"}:
        raise PublishPackageError("PUBLISH_VIDEO_PIXEL_FORMAT_INVALID", "Video must use a YouTube-compatible 4:2:0 pixel format")
    return {
        "container": (probe.get("format") or {}).get("format_name"),
        "duration_seconds": duration,
        "width": width,
        "height": height,
        "video_codec": video.get("codec_name"),
        "audio_codec": audio.get("codec_name"),
        "pixel_format": video.get("pix_fmt"),
        "frame_rate": float(frame_rate),
    }


def _validate_media(
    video_path: Path,
    thumbnail_path: Path,
    subtitle_path: Path,
    *,
    target_language: str,
    rules: dict[str, Any],
    ffprobe_path: str | None,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    probe = _probe_video(video_path, ffprobe_path)
    if video_path.stat().st_size > rules["video_max_bytes"] or probe["duration_seconds"] > rules["video_max_duration_seconds"]:
        raise PublishPackageError("PUBLISH_VIDEO_LIMIT_EXCEEDED", "Video exceeds the catalog size or duration limit")
    container_names = set((probe["container"] or "").split(","))
    if "mp4" not in container_names or probe["video_codec"] != rules["recommended_video_codec"] or probe["audio_codec"] != rules["recommended_audio_codec"]:
        raise PublishPackageError("PUBLISH_VIDEO_ENCODING_INVALID", "Video must be MP4 with H.264 video and AAC audio")
    if abs(probe["width"] / probe["height"] - 16 / 9) > 0.02:
        raise PublishPackageError("PUBLISH_VIDEO_ASPECT_INVALID", "Final video must be 16:9")
    thumbnail = _validate_thumbnail(thumbnail_path, rules)
    if subtitle_path.stat().st_size > rules["caption_max_bytes"]:
        raise PublishPackageError("PUBLISH_SUBTITLE_TOO_LARGE", "Subtitle exceeds captions.insert limit")
    cues, visible = _parse_subtitles(subtitle_path)
    if max(end for _, end in cues) > probe["duration_seconds"] + 0.25:
        raise PublishPackageError("PUBLISH_SUBTITLE_OUT_OF_RANGE", "Subtitle timeline extends beyond video duration")
    if not _language_likely(visible, target_language):
        raise PublishPackageError("PUBLISH_SUBTITLE_LANGUAGE_MISMATCH", "Subtitle text does not match target language")
    subtitles = {"cue_count": len(cues), "last_end_seconds": max(end for _, end in cues), "language": target_language}
    return probe, thumbnail, subtitles


def _grant_valid(value: Any, now: datetime) -> bool:
    if not isinstance(value, dict) or value.get("granted") is not True:
        return False
    if not isinstance(value.get("version"), str) or not value["version"].strip():
        return False
    if not isinstance(value.get("confirmed_at"), str):
        return False
    try:
        confirmed = _parse_iso(value["confirmed_at"])
    except PublishPackageError:
        return False
    return confirmed <= now


def _determine_status(upload_task: dict[str, Any], *, now: datetime) -> tuple[str, list[str], bool]:
    policy = upload_task["upload_policy"]
    if policy == "DO_NOT_UPLOAD":
        return "PACKAGE_READY", [], False
    if policy == "REQUIRE_REVIEW":
        return "WAITING_REVIEW", ["FINAL_CHINESE_REVIEW_CONFIRMATION_REQUIRED"], True
    blockers: list[str] = ["FINAL_CHINESE_REVIEW_CONFIRMATION_REQUIRED"]
    if upload_task.get("schedule_conflict") is True:
        blockers.append("SCHEDULE_CONFLICT")
    if upload_task["privacy_status"] == "scheduled":
        try:
            zone = ZoneInfo(upload_task["timezone"])
            scheduled = _parse_iso(upload_task.get("scheduled_at"), timezone=zone)
            if scheduled.astimezone(UTC) <= now.astimezone(UTC):
                blockers.append("SCHEDULE_TIME_IN_PAST")
        except (ZoneInfoNotFoundError, PublishPackageError, TypeError):
            blockers.append("SCHEDULE_OR_TIMEZONE_INVALID")
    else:
        try:
            ZoneInfo(upload_task["timezone"])
        except (ZoneInfoNotFoundError, TypeError):
            blockers.append("TIMEZONE_INVALID")
        if upload_task.get("scheduled_at") not in (None, ""):
            blockers.append("UNEXPECTED_SCHEDULE_TIME")

    limits = upload_task["limits"]
    if limits["used_today"] >= limits["daily_limit"]:
        blockers.append("DAILY_LIMIT_REACHED")
    if limits["active_uploads"] >= limits["concurrency_limit"]:
        blockers.append("CONCURRENCY_LIMIT_REACHED")
    authorization = upload_task["authorization"]
    for key, code in (
        ("workspace", "WORKSPACE_AUTO_AUTHORIZATION_MISSING"),
        ("channel", "CHANNEL_AUTO_AUTHORIZATION_MISSING"),
        ("intent", "INTENT_AUTO_AUTHORIZATION_MISSING"),
    ):
        if not _grant_valid(authorization.get(key), now):
            blockers.append(code)
    return "WAITING_REVIEW", blockers, True


def _validate_channel_profile(channel_profile: dict[str, Any], publishing: dict[str, Any]) -> None:
    required = {
        "channel_profile_id", "publisher_profile_id", "channel_serial", "expected_channel_id",
        "enabled", "authorization_status", "default_language", "timezone", "upload_mode",
    }
    missing = sorted(required - set(channel_profile))
    if missing:
        raise PublishPackageError("PUBLISH_CHANNEL_PROFILE_INVALID", "Channel profile is missing required read-only fields", details={"missing": missing})
    target = publishing.get("targetChannel") or {}
    expected = (
        publishing.get("channelProfileId"),
        target.get("publisherProfileId"),
        target.get("channelSerial"),
        target.get("youtubeChannelId"),
    )
    actual = (
        channel_profile.get("channel_profile_id"),
        channel_profile.get("publisher_profile_id"),
        channel_profile.get("channel_serial"),
        channel_profile.get("expected_channel_id"),
    )
    if actual != expected:
        raise PublishPackageError("PUBLISH_CHANNEL_IDENTITY_MISMATCH", "Read-only channel identity does not match the publishing asset package")
    if channel_profile.get("enabled") is not True:
        raise PublishPackageError("PUBLISH_CHANNEL_DISABLED", "Target channel profile is disabled")
    if not isinstance(channel_profile.get("channel_serial"), str) or not re.fullmatch(r"\d{2,}", channel_profile["channel_serial"]):
        raise PublishPackageError("PUBLISH_CHANNEL_SERIAL_INVALID", "Channel serial must be a normalized numeric identifier")


def _publish_intent_id(sources: PackageSources, channel_profile: dict[str, Any]) -> str:
    identity = {
        "project_id": sources.production_result["projectId"],
        "production_result": {
            "version": sources.production_result["version"],
            "content_hash": sources.production_result["contentHash"],
        },
        "publishing_asset": {
            "version": sources.publishing_asset["version"],
            "content_hash": sources.publishing_asset["contentHash"],
        },
        "channel_profile": {
            "channel_profile_id": channel_profile["channel_profile_id"],
            "publisher_profile_id": channel_profile["publisher_profile_id"],
            "channel_serial": channel_profile["channel_serial"],
            "expected_channel_id": channel_profile["expected_channel_id"],
        },
    }
    return "pi_" + _sha256_bytes(_canonical_bytes(identity))[:32]


def _copy_asset(source: Path, destination: Path) -> None:
    if source.is_symlink():
        raise PublishPackageError("PUBLISH_SYMLINK_FORBIDDEN", f"Cannot copy symbolic link: {source.name}")
    shutil.copyfile(source, destination)


def _file_entry(path: Path, root: Path, *, role: str, media_type: str | None = None) -> dict[str, Any]:
    return {
        "path": path.relative_to(root).as_posix(),
        "sha256": _sha256_file(path),
        "size_bytes": path.stat().st_size,
        "media_type": media_type or mimetypes.guess_type(path.name)[0] or "application/octet-stream",
        "role": role,
    }


def assemble_publish_package_v2(
    *,
    production_result_root: Path,
    publishing_asset_root: Path,
    inbox_root: Path,
    channel_profile: dict[str, Any],
    constraints_catalog_path: Path,
    authorization: dict[str, Any] | None = None,
    limits: dict[str, int] | None = None,
    scheduled_at: str | None = None,
    schedule_conflict: bool = False,
    timezone: str | None = None,
    created_at: str | None = None,
    ffprobe_path: str | None = None,
) -> dict[str, Any]:
    sources = _load_sources(production_result_root, publishing_asset_root)
    _validate_channel_profile(channel_profile, sources.publishing_asset)
    catalog, catalog_hash = _load_catalog(constraints_catalog_path)
    rules = catalog["rules"]
    intent_id = _publish_intent_id(sources, channel_profile)
    inbox_root = inbox_root.resolve()
    inbox_root.mkdir(parents=True, exist_ok=True)
    creating = inbox_root / f"{intent_id}.creating"
    ready = inbox_root / f"{intent_id}.ready"
    if ready.exists():
        validated = validate_publish_package_v2(
            ready,
            constraints_catalog_path=constraints_catalog_path,
            ffprobe_path=ffprobe_path,
        )
        return {**validated, "duplicate": True, "package_path": str(ready)}
    if creating.exists():
        raise PublishPackageError("PUBLISH_CREATING_EXISTS", "A non-importable .creating package already exists; inspect or recover it explicitly")
    creating.mkdir()

    result = sources.production_result
    publishing = sources.publishing_asset
    now_text = created_at or _utc_now()
    now = _parse_iso(now_text)
    result_video = _resolve_member(sources.production_result_root, result["finalVideo"]["relativePath"], field="finalVideo")
    result_subtitle = _resolve_member(sources.production_result_root, result["subtitles"]["relativePath"], field="subtitles")
    thumbnail_asset = publishing["thumbnail"]["asset"]
    source_thumbnail = _resolve_member(sources.publishing_asset_root, thumbnail_asset["relativePath"], field="thumbnail")
    thumbnail_suffix = source_thumbnail.suffix.lower()
    if thumbnail_suffix not in {".png", ".jpg", ".jpeg"}:
        raise PublishPackageError("PUBLISH_THUMBNAIL_INVALID", "Thumbnail extension is unsupported")
    subtitle_suffix = result_subtitle.suffix.lower()
    if subtitle_suffix not in {".srt", ".vtt"}:
        raise PublishPackageError("PUBLISH_SUBTITLE_INVALID", "Subtitle extension is unsupported")

    final_video = creating / "final.mp4"
    final_thumbnail = creating / ("thumbnail.jpg" if thumbnail_suffix in {".jpg", ".jpeg"} else f"thumbnail{thumbnail_suffix}")
    final_subtitle = creating / f"subtitles{subtitle_suffix}"
    _copy_asset(result_video, final_video)
    _copy_asset(source_thumbnail, final_thumbnail)
    _copy_asset(result_subtitle, final_subtitle)

    probe, thumbnail_probe, subtitle_probe = _validate_media(
        final_video,
        final_thumbnail,
        final_subtitle,
        target_language=publishing["targetLanguage"],
        rules=rules,
        ffprobe_path=ffprobe_path,
    )
    metadata = {
        "schema_version": SCHEMA_VERSION,
        "publish_intent_id": intent_id,
        "project_id": result["projectId"],
        "target_language": publishing["targetLanguage"],
        "title": publishing["title"],
        "description_body": publishing["descriptionBody"],
        "hashtags": publishing["hashtags"],
        "description_for_youtube": publishing["descriptionBody"].rstrip() + "\n\n" + " ".join(publishing["hashtags"]),
        "backend_tags": [],
        "thumbnail_path": final_thumbnail.name,
        "subtitle_path": final_subtitle.name,
    }
    _validate_metadata(metadata, rules)
    _write_json(creating / "metadata.json", metadata)

    policy = publishing.get("uploadPolicy")
    privacy = publishing.get("privacyStatus")
    if policy not in POLICIES or privacy not in PRIVACY:
        raise PublishPackageError("PUBLISH_UPLOAD_TASK_INVALID", "Publishing upload policy or privacy is invalid")
    effective_timezone = timezone or channel_profile["timezone"]
    effective_limits = limits or {"daily_limit": 1, "used_today": 0, "concurrency_limit": 1, "active_uploads": 0}
    for key in ("daily_limit", "used_today", "concurrency_limit", "active_uploads"):
        if not isinstance(effective_limits.get(key), int) or isinstance(effective_limits[key], bool) or effective_limits[key] < 0:
            raise PublishPackageError("PUBLISH_LIMITS_INVALID", f"Invalid channel limit: {key}")
    if effective_limits["daily_limit"] < 1 or effective_limits["concurrency_limit"] < 1:
        raise PublishPackageError("PUBLISH_LIMITS_INVALID", "Daily and concurrency limits must be positive")
    empty_grant = {"granted": False, "version": "", "confirmed_at": ""}
    provided_auth = authorization or {}
    upload_task = {
        "schema_version": SCHEMA_VERSION,
        "publish_intent_id": intent_id,
        "project_id": result["projectId"],
        "channel_profile_id": channel_profile["channel_profile_id"],
        "publisher_profile_id": channel_profile["publisher_profile_id"],
        "channel_serial": channel_profile["channel_serial"],
        "expected_channel_id": channel_profile["expected_channel_id"],
        "upload_policy": policy,
        "privacy_status": privacy,
        "timezone": effective_timezone,
        "scheduled_at": scheduled_at,
        "schedule_conflict": bool(schedule_conflict),
        "category_id": "24",
        "made_for_kids": False,
        "notify_subscribers": False,
        "authorization": {
            "workspace": provided_auth.get("workspace", empty_grant),
            "channel": provided_auth.get("channel", empty_grant),
            "intent": provided_auth.get("intent", empty_grant),
        },
        "limits": effective_limits,
        "constraints_catalog_version": catalog["catalog_version"],
        "network_execution": False,
    }
    _write_json(creating / "upload_task.json", upload_task)

    final_review_card = _final_chinese_review_card(
        intent_id=intent_id,
        result=result,
        publishing=publishing,
        channel_profile=channel_profile,
        final_video=final_video,
        final_thumbnail=final_thumbnail,
    )
    _write_json(creating / "final_chinese_review_card.json", final_review_card)
    (creating / "FINAL_CHINESE_REVIEW_CARD.md").write_text(
        _render_final_chinese_review_markdown(final_review_card),
        encoding="utf-8",
    )

    source_report_sha = _validate_sha(result.get("validationReportHash"), field="production_result.validationReportHash")
    validation = {
        "schema_version": SCHEMA_VERSION,
        "publish_intent_id": intent_id,
        "valid": True,
        "validated_at": now_text,
        "constraints_catalog": {
            "version": catalog["catalog_version"],
            "sha256": catalog_hash,
            "verified_at": catalog["verified_at"],
        },
        "checks": [
            {"code": code, "status": "PASS"}
            for code in (
                "production_result_contract_and_all_declared_files",
                "publishing_asset_contract_and_thumbnail",
                "project_channel_version_hash_binding",
                "package_relative_paths_and_no_symlinks",
                "ffprobe_mp4_h264_aac_16_9",
                "thumbnail_api_surface",
                "subtitle_utf8_timeline_and_target_language",
                "metadata_description_hashtags_and_empty_backend_tags",
                "channel_identity_schedule_limits_and_authorization",
                "network_execution_forced_false",
            )
        ],
        "ffprobe": probe,
        "source_technical_report_sha256": source_report_sha,
    }
    _write_json(creating / "validation.json", validation)

    binding = {
        "schema_version": SCHEMA_VERSION,
        "publish_intent_id": intent_id,
        "project_id": result["projectId"],
        "production_result": {
            "id": result["id"],
            "version": result["version"],
            "content_hash": result["contentHash"],
            "schema_version": result["schemaVersion"],
            "status": result["status"],
        },
        "publishing_asset": {
            "id": publishing["id"],
            "version": publishing["version"],
            "content_hash": publishing["contentHash"],
            "schema_version": publishing["schemaVersion"],
            "status": publishing["status"],
        },
        "final_video": {
            "path": final_video.name,
            "sha256": _sha256_file(final_video),
            "size_bytes": final_video.stat().st_size,
        },
        "subtitle": {
            "path": final_subtitle.name,
            "sha256": _sha256_file(final_subtitle),
            "size_bytes": final_subtitle.stat().st_size,
            "language": publishing["targetLanguage"],
        },
        "technical_report": {
            "path": "validation.json",
            "sha256": _sha256_file(creating / "validation.json"),
            "size_bytes": (creating / "validation.json").stat().st_size,
            "source_sha256": source_report_sha,
        },
    }
    _write_json(creating / "production_binding.json", binding)

    status, blockers, external_approval = _determine_status(upload_task, now=now)
    upload_status = {
        "schema_version": SCHEMA_VERSION,
        "publish_intent_id": intent_id,
        "status": status,
        "last_updated_at": now_text,
        "network_execution": False,
        "external_approval_required": external_approval,
        "blockers": blockers,
        "youtube_video_id": None,
        "youtube_url": None,
        "upload_session": None,
        "publication_receipt_created": False,
        "synthetic_fixture": bool(result.get("synthetic")),
    }
    _write_json(creating / "upload_status.json", upload_status)

    role_map = {
        "FINAL_CHINESE_REVIEW_CARD.md": "human_review_card",
        "final_chinese_review_card.json": "human_review_card_data",
        "metadata.json": "metadata",
        "upload_task.json": "upload_task",
        "validation.json": "validation",
        "production_binding.json": "production_binding",
        "upload_status.json": "upload_status",
        final_video.name: "final_video",
        final_thumbnail.name: "thumbnail",
        final_subtitle.name: "subtitle",
    }
    media_types = {
        "FINAL_CHINESE_REVIEW_CARD.md": "text/markdown",
        "final_chinese_review_card.json": "application/json",
        "metadata.json": "application/json",
        "upload_task.json": "application/json",
        "validation.json": "application/json",
        "production_binding.json": "application/json",
        "upload_status.json": "application/json",
        final_video.name: "video/mp4",
        final_thumbnail.name: thumbnail_probe["media_type"],
        final_subtitle.name: "text/vtt" if subtitle_suffix == ".vtt" else "application/x-subrip",
    }
    files = [
        _file_entry(creating / name, creating, role=role_map[name], media_type=media_types[name])
        for name in sorted(role_map)
    ]
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "protocol": PROTOCOL,
        "package_version": PACKAGE_VERSION,
        "publish_intent_id": intent_id,
        "project_id": result["projectId"],
        "created_at": now_text,
        "synthetic_fixture": bool(result.get("synthetic")),
        "network_execution": False,
        "constraints_catalog": {"version": catalog["catalog_version"], "sha256": catalog_hash},
        "content_hash": _sha256_bytes(_canonical_bytes({"files": files})),
        "files": files,
    }
    _write_json(creating / "manifest.json", manifest)
    validate_publish_package_v2(
        creating,
        constraints_catalog_path=constraints_catalog_path,
        ffprobe_path=ffprobe_path,
        allow_creating=True,
        validation_time=now_text,
    )
    os.replace(creating, ready)
    validated = validate_publish_package_v2(
        ready,
        constraints_catalog_path=constraints_catalog_path,
        ffprobe_path=ffprobe_path,
        validation_time=now_text,
    )
    return {**validated, "duplicate": False, "package_path": str(ready)}


def validate_publish_package_v2(
    package_root: Path,
    *,
    constraints_catalog_path: Path,
    ffprobe_path: str | None = None,
    allow_creating: bool = False,
    validation_time: str | None = None,
) -> dict[str, Any]:
    raw_package_root = package_root
    if raw_package_root.is_symlink():
        raise PublishPackageError("PUBLISH_SYMLINK_FORBIDDEN", "Publish package root must not be a symbolic link")
    package_root = raw_package_root.resolve(strict=True)
    if package_root.name.endswith(".creating") and not allow_creating:
        raise PublishPackageError("PUBLISH_HALF_PACKAGE_FORBIDDEN", ".creating packages are incomplete and cannot be imported")
    if not (package_root.name.endswith(".ready") or (allow_creating and package_root.name.endswith(".creating"))):
        raise PublishPackageError("PUBLISH_PACKAGE_LIFECYCLE_INVALID", "v2 packages must be .ready for import")
    manifest = _load_json(package_root / "manifest.json")
    if manifest.get("schema_version") != SCHEMA_VERSION or manifest.get("protocol") != PROTOCOL or manifest.get("package_version") != PACKAGE_VERSION:
        raise PublishPackageError("PUBLISH_PROTOCOL_INVALID", "Publish package is not protocol v2")
    if manifest.get("network_execution") is not False:
        raise PublishPackageError("PUBLISH_NETWORK_EXECUTION_FORBIDDEN", "Stage6 package must force network_execution=false")
    catalog, catalog_hash = _load_catalog(constraints_catalog_path)
    if manifest.get("constraints_catalog") != {"version": catalog["catalog_version"], "sha256": catalog_hash}:
        raise PublishPackageError("PUBLISH_CONSTRAINTS_MISMATCH", "Package does not bind the installed constraints catalog")

    declared: set[str] = set()
    files = manifest.get("files")
    if not isinstance(files, list) or len(files) != 10:
        raise PublishPackageError("PUBLISH_MANIFEST_INVALID", "v2 manifest must declare exactly ten files besides itself")
    for index, item in enumerate(files):
        if not isinstance(item, dict):
            raise PublishPackageError("PUBLISH_MANIFEST_INVALID", "Manifest file records must be objects")
        relative = _safe_relative_path(item.get("path"), field=f"manifest.files[{index}].path")
        if relative in declared:
            raise PublishPackageError("PUBLISH_DUPLICATE_FILE", f"Duplicate package path: {relative}")
        declared.add(relative)
        _validate_declared_file(package_root, item, prefix=f"manifest.files[{index}]")
    if [item["path"] for item in files] != sorted(item["path"] for item in files):
        raise PublishPackageError("PUBLISH_MANIFEST_INVALID", "Manifest files must be sorted by package-relative path")
    actual = _actual_files(package_root) - {"manifest.json"}
    if actual != declared:
        raise PublishPackageError(
            "PUBLISH_UNDECLARED_FILE",
            "Package contains missing or undeclared files",
            details={"undeclared": sorted(actual - declared), "missing": sorted(declared - actual)},
        )
    expected_fixed = {
        "FINAL_CHINESE_REVIEW_CARD.md",
        "final_chinese_review_card.json",
        "metadata.json",
        "upload_task.json",
        "validation.json",
        "production_binding.json",
        "upload_status.json",
        "final.mp4",
    }
    if not expected_fixed.issubset(declared):
        raise PublishPackageError("PUBLISH_MANIFEST_INVALID", "Required v2 files are missing")
    thumbnails = [path for path in declared if re.fullmatch(r"thumbnail\.(?:png|jpg)", path)]
    subtitles = [path for path in declared if re.fullmatch(r"subtitles\.(?:srt|vtt)", path)]
    if len(thumbnails) != 1 or len(subtitles) != 1:
        raise PublishPackageError("PUBLISH_MANIFEST_INVALID", "Package must contain exactly one thumbnail and one subtitle file")
    calculated_content_hash = _sha256_bytes(_canonical_bytes({"files": files}))
    if manifest.get("content_hash") != calculated_content_hash:
        raise PublishPackageError("PUBLISH_PACKAGE_HASH_MISMATCH", "Manifest content_hash does not match canonical files array")

    metadata = _load_json(package_root / "metadata.json")
    upload_task = _load_json(package_root / "upload_task.json")
    validation = _load_json(package_root / "validation.json")
    binding = _load_json(package_root / "production_binding.json")
    upload_status = _load_json(package_root / "upload_status.json")
    final_review_card = _load_json(package_root / "final_chinese_review_card.json")
    intent_id = manifest.get("publish_intent_id")
    project_id = manifest.get("project_id")
    for name, document in (
        ("metadata", metadata), ("upload_task", upload_task), ("validation", validation),
        ("production_binding", binding), ("upload_status", upload_status),
    ):
        if document.get("schema_version") != SCHEMA_VERSION or document.get("publish_intent_id") != intent_id:
            raise PublishPackageError("PUBLISH_DOCUMENT_IDENTITY_MISMATCH", f"{name} has wrong schema or publish_intent_id")
        if "project_id" in document and document.get("project_id") != project_id:
            raise PublishPackageError("PUBLISH_PROJECT_MISMATCH", f"{name} has a different project_id")
    if not isinstance(intent_id, str) or not re.fullmatch(r"pi_[0-9a-f]{32}", intent_id):
        raise PublishPackageError("PUBLISH_INTENT_ID_INVALID", "publish_intent_id format is invalid")
    if package_root.name not in {f"{intent_id}.ready", f"{intent_id}.creating"}:
        raise PublishPackageError("PUBLISH_INTENT_ID_MISMATCH", "Directory name does not match publish_intent_id")
    _validate_metadata(metadata, catalog["rules"])
    if metadata.get("thumbnail_path") != thumbnails[0] or metadata.get("subtitle_path") != subtitles[0]:
        raise PublishPackageError("PUBLISH_METADATA_PATH_MISMATCH", "Metadata paths do not match package assets")
    if upload_task.get("constraints_catalog_version") != catalog["catalog_version"] or upload_task.get("network_execution") is not False:
        raise PublishPackageError("PUBLISH_UPLOAD_TASK_INVALID", "Upload task catalog or network safety flag is invalid")
    if upload_task.get("upload_policy") not in POLICIES or upload_task.get("privacy_status") not in PRIVACY:
        raise PublishPackageError("PUBLISH_UPLOAD_TASK_INVALID", "Upload task policy or privacy is invalid")
    if validation.get("valid") is not True or validation.get("constraints_catalog") != {
        "version": catalog["catalog_version"], "sha256": catalog_hash, "verified_at": catalog["verified_at"]
    }:
        raise PublishPackageError("PUBLISH_VALIDATION_INVALID", "Package validation record is invalid")
    checks = validation.get("checks")
    if (
        not isinstance(checks, list)
        or len(checks) != 10
        or len({item.get("code") for item in checks if isinstance(item, dict)}) != 10
        or any(not isinstance(item, dict) or item.get("status") != "PASS" for item in checks)
    ):
        raise PublishPackageError("PUBLISH_VALIDATION_INVALID", "A PACKAGE_READY v2 validation record must contain ten distinct PASS checks")
    probe, _, _ = _validate_media(
        package_root / "final.mp4",
        package_root / thumbnails[0],
        package_root / subtitles[0],
        target_language=metadata.get("target_language"),
        rules=catalog["rules"],
        ffprobe_path=ffprobe_path,
    )
    if binding.get("final_video") != {
        "path": "final.mp4", "sha256": _sha256_file(package_root / "final.mp4"), "size_bytes": (package_root / "final.mp4").stat().st_size
    }:
        raise PublishPackageError("PUBLISH_BINDING_MISMATCH", "Final video binding does not match package asset")
    subtitle_binding = binding.get("subtitle") or {}
    if (
        subtitle_binding.get("path") != subtitles[0]
        or subtitle_binding.get("sha256") != _sha256_file(package_root / subtitles[0])
        or subtitle_binding.get("size_bytes") != (package_root / subtitles[0]).stat().st_size
        or subtitle_binding.get("language") != metadata.get("target_language")
    ):
        raise PublishPackageError("PUBLISH_BINDING_MISMATCH", "Subtitle binding does not match package asset")
    technical = binding.get("technical_report") or {}
    if (
        technical.get("path") != "validation.json"
        or technical.get("sha256") != _sha256_file(package_root / "validation.json")
        or technical.get("size_bytes") != (package_root / "validation.json").stat().st_size
        or technical.get("source_sha256") != validation.get("source_technical_report_sha256")
    ):
        raise PublishPackageError("PUBLISH_BINDING_MISMATCH", "Technical validation binding does not match")
    for contract_name, expected_status in (("production_result", "VIDEO_READY"), ("publishing_asset", "PUBLISHING_ASSETS_READY")):
        contract = binding.get(contract_name)
        if not isinstance(contract, dict) or contract.get("status") != expected_status:
            raise PublishPackageError("PUBLISH_BINDING_MISMATCH", f"Invalid {contract_name} status binding")
        _validate_sha(contract.get("content_hash"), field=f"production_binding.{contract_name}.content_hash")
    if upload_status.get("status") not in LOCAL_STATES or upload_status.get("status") in REMOTE_STATES:
        raise PublishPackageError("PUBLISH_UPLOAD_STATE_FORGED", "A local package cannot claim a remote upload state")
    if upload_status.get("network_execution") is not False:
        raise PublishPackageError("PUBLISH_NETWORK_EXECUTION_FORBIDDEN", "upload_status must force network_execution=false")
    if any(upload_status.get(field) not in (None, False) for field in ("youtube_video_id", "youtube_url", "upload_session", "publication_receipt_created")):
        raise PublishPackageError("PUBLISH_FAKE_REMOTE_ID", "No video ID, URL, session, or receipt may exist before real upload")
    if any(name.lower().startswith("publication") or "receipt" in name.lower() for name in declared):
        raise PublishPackageError("PUBLISH_FAKE_RECEIPT", "Publication receipts cannot exist without a real YouTube video ID")
    status_time = _parse_iso(validation_time) if validation_time else datetime.now(UTC)
    expected_status, expected_blockers, expected_external = _determine_status(upload_task, now=status_time)
    if (
        upload_status.get("status") != expected_status
        or upload_status.get("blockers") != expected_blockers
        or upload_status.get("external_approval_required") is not expected_external
    ):
        raise PublishPackageError("PUBLISH_STATUS_MISMATCH", "upload_status does not match policy, authorization, schedule, and limits")
    if (
        final_review_card.get("schemaVersion") != "1.0.0"
        or final_review_card.get("displayMode") != "CHINESE_FIRST_WITH_TARGET_LANGUAGE"
        or final_review_card.get("gate") != "G6_FINAL_CHINESE_UPLOAD_REVIEW"
        or final_review_card.get("publishIntentId") != intent_id
        or final_review_card.get("projectId") != project_id
        or final_review_card.get("confirmation", {}).get("confirmed") is not False
        or final_review_card.get("networkExecution") is not False
        or final_review_card.get("uploadUseOfChineseTranslations") is not False
    ):
        raise PublishPackageError("PUBLISH_FINAL_CHINESE_REVIEW_INVALID", "Final Chinese review card identity or safety boundary is invalid")
    target_comparison = final_review_card.get("targetLanguageComparison") or {}
    chinese_primary = final_review_card.get("chinesePrimary") or {}
    if (
        target_comparison.get("language") != metadata.get("target_language")
        or target_comparison.get("title") != metadata.get("title")
        or target_comparison.get("description") != metadata.get("description_body")
        or target_comparison.get("hashtags") != metadata.get("hashtags")
        or chinese_primary.get("channel", {}).get("channelSerial") != upload_task.get("channel_serial")
        or chinese_primary.get("channel", {}).get("youtubeChannelId") != upload_task.get("expected_channel_id")
        or chinese_primary.get("privacyStatusZh") != PRIVACY_ZH.get(upload_task.get("privacy_status"))
        or chinese_primary.get("uploadPolicyZh") != UPLOAD_POLICY_ZH.get(upload_task.get("upload_policy"))
    ):
        raise PublishPackageError("PUBLISH_FINAL_CHINESE_REVIEW_INVALID", "Final Chinese review card does not match frozen upload data")
    review_assets = final_review_card.get("finalAssets") or {}
    if review_assets.get("video") != {
        "path": "final.mp4",
        "sha256": _sha256_file(package_root / "final.mp4"),
        "sizeBytes": (package_root / "final.mp4").stat().st_size,
    } or review_assets.get("thumbnail") != {
        "path": thumbnails[0],
        "sha256": _sha256_file(package_root / thumbnails[0]),
        "sizeBytes": (package_root / thumbnails[0]).stat().st_size,
    }:
        raise PublishPackageError("PUBLISH_FINAL_CHINESE_REVIEW_INVALID", "Final Chinese review card asset binding is invalid")
    expected_markdown = _render_final_chinese_review_markdown(final_review_card)
    try:
        actual_markdown = (package_root / "FINAL_CHINESE_REVIEW_CARD.md").read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise PublishPackageError("PUBLISH_FINAL_CHINESE_REVIEW_INVALID", "Final Chinese review card Markdown is unreadable") from exc
    if actual_markdown != expected_markdown:
        raise PublishPackageError("PUBLISH_FINAL_CHINESE_REVIEW_INVALID", "Final Chinese review card Markdown does not match its JSON source")
    return {
        "valid": True,
        "publish_intent_id": intent_id,
        "project_id": project_id,
        "status": expected_status,
        "blockers": expected_blockers,
        "external_approval_required": expected_external,
        "package_hash": manifest["content_hash"],
        "video_sha256": binding["final_video"]["sha256"],
        "subtitle_sha256": binding["subtitle"]["sha256"],
        "thumbnail_sha256": _sha256_file(package_root / thumbnails[0]),
        "final_chinese_review_card": final_review_card,
        "final_chinese_review_card_path": str(package_root / "FINAL_CHINESE_REVIEW_CARD.md"),
        "constraints_catalog_sha256": catalog_hash,
        "ffprobe": probe,
        "network_execution": False,
        "youtube_video_id": None,
        "publication_receipt": None,
    }
