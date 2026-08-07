from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any, Iterable


REVIEW_DOCUMENT_SCHEMA_VERSION = "1.0.0"
REVIEW_DIRECTORY_NAME = "用户审核文档"

DOCUMENT_SPECS: dict[str, dict[str, str]] = {
    "source-summary": {"filename": "01_原始素材说明.md", "title": "原始素材说明", "stage": "source"},
    "deconstruction-report": {"filename": "02_完整拆解报告.md", "title": "完整拆解报告", "stage": "deconstruction"},
    "transfer-directions": {"filename": "03_迁移方向选择.md", "title": "迁移方向选择", "stage": "deconstruction"},
    "rewrite-draft-target": {"filename": "04_仿写初稿_目标语言.txt", "title": "仿写初稿（目标语言）", "stage": "rewrite"},
    "editorial-review": {"filename": "05_编辑审核报告.md", "title": "编辑审核报告", "stage": "review"},
    "revision-log": {"filename": "06_修改记录与前后对照.md", "title": "修改记录与前后对照", "stage": "review"},
    "final-script-target": {"filename": "07_正式稿_目标语言.txt", "title": "正式稿（目标语言）", "stage": "manuscript"},
    "final-script-zh": {"filename": "08_正式稿_中文版.txt", "title": "正式稿（中文版）", "stage": "manuscript"},
    "packaging-bilingual": {"filename": "09_标题简介标签_双语审核.md", "title": "标题简介标签双语审核", "stage": "packaging"},
    "thumbnail-review": {"filename": "10_封面候选与选择结果.md", "title": "封面候选与选择结果", "stage": "packaging"},
    "production-overview": {"filename": "11_完整生产资料总览.md", "title": "完整生产资料总览", "stage": "production"},
}


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":"), sort_keys=True).encode("utf-8")


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _atomic_bytes(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _atomic_json(path: Path, value: Any) -> None:
    _atomic_bytes(path, json.dumps(value, ensure_ascii=False, indent=2).encode("utf-8") + b"\n")


def _index_core(index: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in index.items() if key != "contentHash"}


def _load_index(project_root: Path) -> dict[str, Any]:
    index_path = project_root / REVIEW_DIRECTORY_NAME / "index.json"
    if not index_path.is_file():
        return {
            "schemaVersion": REVIEW_DOCUMENT_SCHEMA_VERSION,
            "contractType": "user-review-document-index",
            "documents": {},
        }
    return json.loads(index_path.read_text(encoding="utf-8-sig"))


def save_review_document(
    project_root: Path,
    *,
    document_id: str,
    content: str,
    language: str,
    updated_at: str,
    minimum_characters: int = 20,
) -> dict[str, Any]:
    spec = DOCUMENT_SPECS.get(document_id)
    if spec is None:
        raise ValueError(f"Unsupported user review document: {document_id}")
    if not isinstance(content, str) or len(content.strip()) < minimum_characters:
        raise ValueError(f"User review document is incomplete: {document_id}")
    if not isinstance(language, str) or not language.strip():
        raise ValueError(f"User review document language is invalid: {document_id}")

    payload = content.rstrip().encode("utf-8") + b"\n"
    content_hash = _sha256_bytes(payload)
    review_root = project_root / REVIEW_DIRECTORY_NAME
    stable_path = review_root / spec["filename"]
    index = _load_index(project_root)
    documents = index.setdefault("documents", {})
    previous = documents.get(document_id)
    if isinstance(previous, dict) and previous.get("sha256") == content_hash and stable_path.is_file():
        if _sha256_file(stable_path) == content_hash:
            return {**previous, "idempotent": True}

    version = int(previous.get("version", 0)) + 1 if isinstance(previous, dict) else 1
    suffix = Path(spec["filename"]).suffix
    version_path = review_root / "版本记录" / document_id / f"v{version:03d}{suffix}"
    _atomic_bytes(version_path, payload)
    _atomic_bytes(stable_path, payload)
    entry = {
        "documentId": document_id,
        "title": spec["title"],
        "stage": spec["stage"],
        "language": language,
        "version": version,
        "relativePath": stable_path.relative_to(project_root).as_posix(),
        "versionRelativePath": version_path.relative_to(project_root).as_posix(),
        "mediaType": "text/plain" if suffix == ".txt" else "text/markdown",
        "sizeBytes": len(payload),
        "sha256": content_hash,
        "productionUseAllowed": document_id == "final-script-target",
        "updatedAt": updated_at,
    }
    documents[document_id] = entry
    index["updatedAt"] = updated_at
    index["contentHash"] = _sha256_bytes(_canonical_bytes(_index_core(index)))
    _atomic_json(review_root / "index.json", index)
    return {**entry, "idempotent": False}


def copy_review_documents(source_root: Path, target_root: Path, document_ids: Iterable[str], *, updated_at: str) -> list[dict[str, Any]]:
    document_ids = tuple(document_ids)
    validation = validate_review_documents(source_root, document_ids)
    if validation["status"] != "PASS":
        raise ValueError(f"Source review documents failed integrity check: {validation['errors']}")
    source_index = _load_index(source_root)
    copied: list[dict[str, Any]] = []
    for document_id in document_ids:
        entry = source_index.get("documents", {}).get(document_id)
        if not isinstance(entry, dict):
            raise ValueError(f"Required source review document is missing: {document_id}")
        source_path = source_root / REVIEW_DIRECTORY_NAME / DOCUMENT_SPECS[document_id]["filename"]
        copied.append(
            save_review_document(
                target_root,
                document_id=document_id,
                content=source_path.read_text(encoding="utf-8-sig"),
                language=str(entry.get("language") or "zh-CN"),
                updated_at=updated_at,
                minimum_characters=1,
            )
        )
    return copied


def review_documents_view(project_root: Path) -> dict[str, Any]:
    index = _load_index(project_root)
    documents = index.get("documents", {})
    return {
        "contextRoot": str(project_root),
        "directory": str(project_root / REVIEW_DIRECTORY_NAME),
        "indexPath": str(project_root / REVIEW_DIRECTORY_NAME / "index.json"),
        "documents": [documents[key] for key in DOCUMENT_SPECS if key in documents],
        "contentHash": index.get("contentHash"),
    }


def validate_review_documents(project_root: Path, required_document_ids: Iterable[str]) -> dict[str, Any]:
    required_document_ids = tuple(required_document_ids)
    index_path = project_root / REVIEW_DIRECTORY_NAME / "index.json"
    errors: list[dict[str, str]] = []
    if not index_path.is_file():
        return {"status": "FAIL", "errors": [{"documentId": "index", "issue": "missing"}]}
    try:
        index = _load_index(project_root)
    except (OSError, json.JSONDecodeError):
        return {"status": "FAIL", "errors": [{"documentId": "index", "issue": "invalid-json"}]}
    if index.get("schemaVersion") != REVIEW_DOCUMENT_SCHEMA_VERSION or index.get("contractType") != "user-review-document-index":
        errors.append({"documentId": "index", "issue": "identity"})
    if index.get("contentHash") != _sha256_bytes(_canonical_bytes(_index_core(index))):
        errors.append({"documentId": "index", "issue": "hash"})
    documents = index.get("documents")
    if not isinstance(documents, dict):
        errors.append({"documentId": "index", "issue": "documents"})
        documents = {}
    for document_id in required_document_ids:
        spec = DOCUMENT_SPECS.get(document_id)
        if spec is None:
            errors.append({"documentId": document_id, "issue": "unsupported"})
            continue
        entry = documents.get(document_id)
        if not isinstance(entry, dict):
            errors.append({"documentId": document_id, "issue": "missing"})
            continue
        expected_relative = (Path(REVIEW_DIRECTORY_NAME) / spec["filename"]).as_posix()
        if (
            entry.get("documentId") != document_id
            or entry.get("title") != spec["title"]
            or entry.get("stage") != spec["stage"]
            or entry.get("relativePath") != expected_relative
            or not isinstance(entry.get("language"), str)
            or not entry["language"].strip()
            or not isinstance(entry.get("version"), int)
            or entry["version"] < 1
        ):
            errors.append({"documentId": document_id, "issue": "metadata"})
            continue
        suffix = Path(spec["filename"]).suffix
        expected_version_relative = (
            Path(REVIEW_DIRECTORY_NAME) / "版本记录" / document_id / f"v{entry['version']:03d}{suffix}"
        ).as_posix()
        if entry.get("versionRelativePath") != expected_version_relative:
            errors.append({"documentId": document_id, "issue": "version-metadata"})
            continue
        path = project_root / expected_relative
        if not path.is_file():
            errors.append({"documentId": document_id, "issue": "file-missing"})
            continue
        if path.stat().st_size != entry.get("sizeBytes") or _sha256_file(path) != entry.get("sha256"):
            errors.append({"documentId": document_id, "issue": "file-hash"})
            continue
        version_path = project_root / expected_version_relative
        if not version_path.is_file():
            errors.append({"documentId": document_id, "issue": "version-file-missing"})
        elif version_path.stat().st_size != entry.get("sizeBytes") or _sha256_file(version_path) != entry.get("sha256"):
            errors.append({"documentId": document_id, "issue": "version-file-hash"})
    return {
        "status": "PASS" if not errors else "FAIL",
        "directory": str(project_root / REVIEW_DIRECTORY_NAME),
        "indexPath": str(index_path),
        "checked": list(required_document_ids),
        "errors": errors,
    }
