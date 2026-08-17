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
    "source-analysis": {"filename": "01B_内容分析与提示词执行结果.md", "title": "内容分析与提示词执行结果", "stage": "planning"},
    "creative-plan": {"filename": "02_创作方案与大纲确认.md", "title": "创作方案与大纲确认", "stage": "planning"},
    "deconstruction-report": {"filename": "02_完整拆解报告.md", "title": "完整拆解报告", "stage": "deconstruction"},
    "transfer-directions": {"filename": "03_迁移方向选择.md", "title": "迁移方向选择", "stage": "deconstruction"},
    "rewrite-draft-target": {"filename": "04_仿写初稿_目标语言.txt", "title": "仿写初稿（目标语言）", "stage": "rewrite"},
    "rewrite-draft-zh": {"filename": "04B_仿写初稿_中文版.txt", "title": "仿写初稿（中文版）", "stage": "rewrite"},
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


def _document_payload(content: str) -> bytes:
    return content.rstrip().encode("utf-8") + b"\n"


def render_script_text(lines: list[dict[str, Any]]) -> str:
    """Render the exact human-readable script that mirrors structured production lines."""
    rendered: list[str] = []
    for line in lines:
        if not isinstance(line, dict) or any(not isinstance(line.get(key), str) for key in ("lineId", "speakerId", "text")):
            raise ValueError("Script line is missing lineId, speakerId, or text")
        rendered.append(f"[{line['lineId']}] {line['speakerId']}: {line['text']}")
    if not rendered:
        raise ValueError("Script lines are empty")
    return "\n".join(rendered) + "\n"


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


def sync_review_workflow_state(project_root: Path, state: dict[str, Any]) -> dict[str, Any]:
    """Bind the human-document index to the canonical project state.

    This prevents a manually written or stale index from claiming that the
    project is at a different gate than the machine packages.
    """
    index = _load_index(project_root)
    active_packages = state.get("activePackages") if isinstance(state.get("activePackages"), dict) else {}
    index["canonicalProject"] = {
        "projectId": state.get("projectId"),
        "channelProfileId": state.get("channelProfileId"),
        "createdByTaskId": state.get("createdByTaskId"),
        "projectRoot": str(project_root.resolve()),
        "statePath": str((project_root / "content-state.json").resolve()),
        "parallelWritableProjectRootsAllowed": False,
    }
    index["workflowState"] = {
        "state": state.get("state"),
        "activePackageHashes": {
            key: value.get("hash") if isinstance(value, dict) else None
            for key, value in active_packages.items()
        },
        "invalidationCount": len(state.get("invalidations", [])) if isinstance(state.get("invalidations"), list) else 0,
        "updatedAt": state.get("updatedAt"),
    }
    index["updatedAt"] = state.get("updatedAt")
    index["contentHash"] = _sha256_bytes(_canonical_bytes(_index_core(index)))
    _atomic_json(project_root / REVIEW_DIRECTORY_NAME / "index.json", index)
    return index


def save_review_document(
    project_root: Path,
    *,
    document_id: str,
    content: str,
    language: str,
    updated_at: str,
    minimum_characters: int = 20,
    source_binding: dict[str, str] | None = None,
) -> dict[str, Any]:
    spec = DOCUMENT_SPECS.get(document_id)
    if spec is None:
        raise ValueError(f"Unsupported user review document: {document_id}")
    if not isinstance(content, str) or len(content.strip()) < minimum_characters:
        raise ValueError(f"User review document is incomplete: {document_id}")
    if not isinstance(language, str) or not language.strip():
        raise ValueError(f"User review document language is invalid: {document_id}")

    payload = _document_payload(content)
    content_hash = _sha256_bytes(payload)
    review_root = project_root / REVIEW_DIRECTORY_NAME
    stable_path = review_root / spec["filename"]
    index = _load_index(project_root)
    documents = index.setdefault("documents", {})
    previous = documents.get(document_id)
    if source_binding is None and isinstance(previous, dict):
        previous_binding = previous.get("sourceBinding")
        if isinstance(previous_binding, dict):
            source_binding = previous_binding
    if (
        not isinstance(source_binding, dict)
        or not isinstance(source_binding.get("contractType"), str)
        or not source_binding["contractType"].strip()
        or not isinstance(source_binding.get("contractId"), str)
        or not source_binding["contractId"].strip()
        or not isinstance(source_binding.get("contentHash"), str)
        or len(source_binding["contentHash"]) != 64
    ):
        raise ValueError(f"User review document source binding is invalid: {document_id}")
    normalized_source_binding = {
        "contractType": source_binding["contractType"].strip(),
        "contractId": source_binding["contractId"].strip(),
        "contentHash": source_binding["contentHash"].lower(),
    }
    if (
        isinstance(previous, dict)
        and previous.get("sha256") == content_hash
        and previous.get("sourceBinding") == normalized_source_binding
        and stable_path.is_file()
    ):
        if _sha256_file(stable_path) == content_hash:
            version_relative = previous.get("versionRelativePath")
            version_absolute = (
                str((project_root / version_relative).resolve())
                if isinstance(version_relative, str) and version_relative
                else None
            )
            return {
                **previous,
                "absolutePath": str(stable_path.resolve()),
                "versionAbsolutePath": version_absolute,
                "idempotent": True,
            }

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
        "sourceBinding": normalized_source_binding,
        "updatedAt": updated_at,
    }
    documents[document_id] = entry
    index["updatedAt"] = updated_at
    index["contentHash"] = _sha256_bytes(_canonical_bytes(_index_core(index)))
    _atomic_json(review_root / "index.json", index)
    return {
        **entry,
        "absolutePath": str(stable_path.resolve()),
        "versionAbsolutePath": str(version_path.resolve()),
        "idempotent": False,
    }


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
                source_binding=entry.get("sourceBinding"),
            )
        )
    return copied


def review_documents_view(project_root: Path) -> dict[str, Any]:
    index = _load_index(project_root)
    documents = index.get("documents", {})
    visible_documents = []
    for document_id in DOCUMENT_SPECS:
        if document_id not in documents:
            continue
        entry = documents[document_id]
        stable_path = project_root / str(entry["relativePath"])
        version_path = project_root / str(entry["versionRelativePath"])
        visible_documents.append(
            {
                **entry,
                "absolutePath": str(stable_path.resolve()),
                "versionAbsolutePath": str(version_path.resolve()),
                "usageRole": (
                    "target-language-production-master"
                    if document_id == "final-script-target"
                    else "user-review-only"
                ),
                "displayRequired": True,
            }
        )
    return {
        "contextRoot": str(project_root),
        "directory": str(project_root / REVIEW_DIRECTORY_NAME),
        "indexPath": str(project_root / REVIEW_DIRECTORY_NAME / "index.json"),
        "documents": visible_documents,
        "contentHash": index.get("contentHash"),
        "canonicalProject": index.get("canonicalProject"),
        "workflowState": index.get("workflowState"),
        "displayRequired": bool(visible_documents),
        "displayInstructionZh": "自动模式也必须向用户显示本阶段新增文档的可点击绝对路径；自动授权只取消等待，不取消展示。",
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
        expected_media_type = "text/plain" if suffix == ".txt" else "text/markdown"
        expected_production_use = document_id == "final-script-target"
        if (
            entry.get("mediaType") != expected_media_type
            or entry.get("productionUseAllowed") != expected_production_use
            or not isinstance(entry.get("sizeBytes"), int)
            or entry["sizeBytes"] <= 0
            or not isinstance(entry.get("sha256"), str)
            or len(entry["sha256"]) != 64
            or not isinstance(entry.get("sourceBinding"), dict)
            or not isinstance(entry["sourceBinding"].get("contractType"), str)
            or not entry["sourceBinding"]["contractType"].strip()
            or not isinstance(entry["sourceBinding"].get("contractId"), str)
            or not entry["sourceBinding"]["contractId"].strip()
            or not isinstance(entry["sourceBinding"].get("contentHash"), str)
            or len(entry["sourceBinding"]["contentHash"]) != 64
        ):
            errors.append({"documentId": document_id, "issue": "usage-metadata"})
            continue
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


def validate_review_document_bindings(
    project_root: Path,
    expected_documents: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """Bind user-visible files to the exact text and language used by machine contracts."""
    validation = validate_review_documents(project_root, expected_documents)
    errors = list(validation["errors"])
    if validation["status"] == "PASS":
        index = _load_index(project_root)
        documents = index["documents"]
        for document_id, expected in expected_documents.items():
            entry = documents[document_id]
            content = expected.get("content")
            language = expected.get("language")
            production_use_allowed = expected.get("productionUseAllowed")
            source_contract_type = expected.get("sourceContractType")
            source_contract_id = expected.get("sourceContractId")
            source_content_hash = expected.get("sourceContentHash")
            if "content" in expected:
                if not isinstance(content, str) or entry.get("sha256") != _sha256_bytes(_document_payload(content)):
                    errors.append({"documentId": document_id, "issue": "content-binding"})
            if isinstance(language, str) and entry.get("language") != language:
                errors.append({"documentId": document_id, "issue": "language-binding"})
            if isinstance(production_use_allowed, bool) and entry.get("productionUseAllowed") != production_use_allowed:
                errors.append({"documentId": document_id, "issue": "production-boundary"})
            source_binding = entry.get("sourceBinding", {})
            if isinstance(source_contract_type, str) and source_binding.get("contractType") != source_contract_type:
                errors.append({"documentId": document_id, "issue": "source-contract-type"})
            if isinstance(source_contract_id, str) and source_binding.get("contractId") != source_contract_id:
                errors.append({"documentId": document_id, "issue": "source-contract-id"})
            if isinstance(source_content_hash, str) and source_binding.get("contentHash") != source_content_hash:
                errors.append({"documentId": document_id, "issue": "source-contract-hash"})
    return {
        "status": "PASS" if not errors else "FAIL",
        "directory": str(project_root / REVIEW_DIRECTORY_NAME),
        "checked": list(expected_documents),
        "errors": errors,
    }
