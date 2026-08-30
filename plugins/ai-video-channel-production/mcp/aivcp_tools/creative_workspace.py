from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import tempfile
import uuid
from pathlib import Path
from typing import Any

from .contracts import utc_now
from .errors import ToolError
from .store import ChannelStore


CREATIVE_WORKSPACE_VERSION = "1.1.0"
PROMPT_STAGES = frozenset({"analysis", "ideation", "drafting", "review", "packaging", "custom"})
DOCUMENT_STAGES = frozenset({"input", "research", "analysis", "ideation", "drafting", "review", "final", "packaging", "custom"})
TEXT_SUFFIXES = frozenset({".txt", ".md", ".json", ".yaml", ".yml", ".prompt"})
MAX_PROMPT_BYTES = 2 * 1024 * 1024
SAFE_ID = re.compile(r"^[A-Za-z0-9_.:-]{1,160}$")
SPOKEN_HEADING = re.compile(
    r"(?im)^\s*(?:#{1,6}\s*)?(?:第\s*[一二三四五六七八九十百千万0-9]+\s*[章节话集]|序章|终章|"
    r"chapter\s+[0-9ivxlcdm]+|episode\s+[0-9]+)\s*[:：.-]?\s*$"
)


def _safe_id(value: Any, field: str, *, maximum: int = 160) -> str:
    if not isinstance(value, str):
        raise ToolError("INVALID_ARGUMENT", f"{field} 无效。", details={"field": field})
    cleaned = value.strip()
    if not cleaned or len(cleaned) > maximum or SAFE_ID.fullmatch(cleaned) is None:
        raise ToolError("INVALID_ARGUMENT", f"{field} 无效。", details={"field": field})
    return cleaned


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _atomic_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(content)
            if content and not content.endswith("\n"):
                handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


class CreativeWorkspace:
    """Channel-free content workspace used before the user starts video production."""

    def __init__(self, store: ChannelStore) -> None:
        self.store = store
        self.root = store.data_root / "content-workspaces"
        self.root.mkdir(parents=True, exist_ok=True)

    def _workspace_root(self, workspace_id: Any) -> Path:
        return self.root / _safe_id(workspace_id, "workspaceId")

    def _state_path(self, workspace_id: Any) -> Path:
        return self._workspace_root(workspace_id) / "workspace-state.json"

    def _load(self, workspace_id: Any) -> dict[str, Any]:
        path = self._state_path(workspace_id)
        if not path.is_file():
            raise ToolError("CONTENT_WORKSPACE_NOT_FOUND", "没有找到本次自由创作工作区。")
        try:
            state = json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ToolError("CONTENT_WORKSPACE_INVALID", "自由创作工作区状态损坏。") from exc
        if state.get("workspaceId") != _safe_id(workspace_id, "workspaceId"):
            raise ToolError("CONTENT_WORKSPACE_INVALID", "自由创作工作区身份不一致。")
        return state

    def _save(self, state: dict[str, Any]) -> None:
        state["updatedAt"] = utc_now()
        _atomic_json(self._state_path(state["workspaceId"]), state)

    def assert_legacy_project_start_allowed(
        self,
        *,
        task_id: Any,
        channel_profile_id: Any,
        production_handoff_path: Any = None,
    ) -> None:
        task_id = _safe_id(task_id, "taskId")
        matching: list[dict[str, Any]] = []
        for state_path in self.root.glob("*/workspace-state.json"):
            try:
                state = json.loads(state_path.read_text(encoding="utf-8-sig"))
            except (OSError, json.JSONDecodeError):
                continue
            if state.get("taskId") == task_id:
                matching.append(state)
        if not matching:
            return
        if len(matching) != 1:
            raise ToolError("CONTENT_WORKSPACE_TASK_AMBIGUOUS", "当前任务存在多个自由创作工作区，禁止旧入口猜测项目。")
        binding = matching[0].get("productionBinding")
        if (
            not isinstance(binding, dict)
            or binding.get("status") != "BOUND_FOR_PRODUCTION"
            or binding.get("channelProfileId") != channel_profile_id
            or production_handoff_path != binding.get("handoffPath")
        ):
            raise ToolError(
                "CONTENT_WORKSPACE_PRODUCTION_HANDOFF_REQUIRED",
                "本任务已经使用新自由创作流程；旧频道项目入口只能在制作绑定完成后接收精确生产交接路径。",
                details={"requiredHandoffPath": binding.get("handoffPath") if isinstance(binding, dict) else None},
            )

    def _assert(self, *, task_id: Any, workspace_id: Any, binding_proof: Any) -> dict[str, Any]:
        task_id = _safe_id(task_id, "taskId")
        state = self._load(workspace_id)
        if state.get("taskId") != task_id:
            raise ToolError("CONTENT_WORKSPACE_TASK_MISMATCH", "自由创作工作区只允许原任务继续写入。")
        if not isinstance(binding_proof, str) or not binding_proof:
            raise ToolError("CONTENT_WORKSPACE_PROOF_REQUIRED", "写入自由创作工作区需要当前任务校验值。")
        proof_hash = hashlib.sha256(binding_proof.encode("utf-8")).hexdigest()
        expected = state.get("bindingProofHash")
        if not isinstance(expected, str) or not secrets.compare_digest(expected, proof_hash):
            raise ToolError("CONTENT_WORKSPACE_BINDING_MISMATCH", "自由创作工作区校验失败，禁止跨任务写入。")
        return state

    @staticmethod
    def _public(state: dict[str, Any]) -> dict[str, Any]:
        result = {key: value for key, value in state.items() if key != "bindingProofHash"}
        result["channelBindingStatus"] = "BOUND_FOR_PRODUCTION" if state.get("productionBinding") else "UNBOUND"
        return result

    def start(
        self,
        *,
        task_id: Any,
        project_id: Any,
        workspace_id: Any = None,
        review_raw_draft: Any = False,
    ) -> dict[str, Any]:
        task_id = _safe_id(task_id, "taskId")
        project_id = _safe_id(project_id, "projectId")
        if workspace_id is None:
            workspace_id = f"cw_{uuid.uuid4().hex}"
        workspace_id = _safe_id(workspace_id, "workspaceId")
        if not isinstance(review_raw_draft, bool):
            raise ToolError("CONTENT_WORKSPACE_REVIEW_POLICY_INVALID", "初稿审核选项必须是布尔值。")
        root = self._workspace_root(workspace_id)
        if root.exists():
            raise ToolError(
                "CONTENT_WORKSPACE_ALREADY_EXISTS",
                "同名自由创作工作区已经存在；新任务不会自动恢复旧工作区。",
            )
        proof = secrets.token_urlsafe(32)
        now = utc_now()
        state = {
            "schemaVersion": CREATIVE_WORKSPACE_VERSION,
            "workspaceId": workspace_id,
            "taskId": task_id,
            "projectId": project_id,
            "bindingProofHash": hashlib.sha256(proof.encode("utf-8")).hexdigest(),
            "mode": "FLEXIBLE_CREATION",
            "state": "CREATIVE_ACTIVE",
            "channelProfileId": None,
            "channelSerial": None,
            "productionBinding": None,
            "autoUploadAuthorization": None,
            "manuscriptReviewPolicy": {
                "schemaVersion": "1.0",
                "reviewRawDraft": review_raw_draft,
                "defaultExternalGate": "D4_REWRITE_DRAFT" if review_raw_draft else "D5_FINAL_MANUSCRIPT",
                "finalTargetManuscriptConfirmationRequired": True,
                "auditTranslationsAndReportsInformational": True,
                "selectionSource": "current_task_user" if review_raw_draft else "new_task_default",
            },
            "prompts": {},
            "documents": {},
            "createdAt": now,
            "updatedAt": now,
        }
        root.mkdir(parents=True)
        self._save(state)
        return {
            "workspace": self._public(state),
            "workspaceBindingProof": proof,
            "next": "可自由登记资料、临时提示词并按用户指定顺序创作；当前未绑定任何频道。",
        }

    def register_prompt(
        self,
        *,
        task_id: Any,
        workspace_id: Any,
        binding_proof: Any,
        prompt_id: Any,
        prompt_path: Any,
        stage: Any,
        purpose: Any,
        execution_order: Any,
        field_mappings: Any = None,
        input_bindings: Any = None,
    ) -> dict[str, Any]:
        state = self._assert(task_id=task_id, workspace_id=workspace_id, binding_proof=binding_proof)
        prompt_id = _safe_id(prompt_id, "promptId", maximum=128)
        if stage not in PROMPT_STAGES:
            raise ToolError("CONTENT_WORKSPACE_PROMPT_STAGE_INVALID", "临时提示词阶段无效。")
        if not isinstance(purpose, str) or not purpose.strip() or len(purpose.strip()) > 240:
            raise ToolError("CONTENT_WORKSPACE_PROMPT_PURPOSE_INVALID", "临时提示词用途不能为空且不能超过 240 字。")
        if not isinstance(execution_order, int) or isinstance(execution_order, bool) or not 1 <= execution_order <= 1000:
            raise ToolError("CONTENT_WORKSPACE_PROMPT_ORDER_INVALID", "临时提示词执行顺序必须是 1–1000 的整数。")
        if not isinstance(prompt_path, str) or not prompt_path.strip():
            raise ToolError("CONTENT_WORKSPACE_PROMPT_PATH_INVALID", "必须提供用户本次选择的提示词文件路径。")
        source = Path(prompt_path).expanduser().resolve()
        if not source.is_file() or source.suffix.lower() not in TEXT_SUFFIXES:
            raise ToolError("CONTENT_WORKSPACE_PROMPT_FILE_INVALID", "临时提示词必须是受支持的 UTF-8 文本文件。")
        size = source.stat().st_size
        if size <= 0 or size > MAX_PROMPT_BYTES:
            raise ToolError("CONTENT_WORKSPACE_PROMPT_FILE_SIZE_INVALID", "临时提示词文件为空或超过 2MB。")
        try:
            source.read_text(encoding="utf-8-sig")
        except (OSError, UnicodeError) as exc:
            raise ToolError("CONTENT_WORKSPACE_PROMPT_ENCODING_INVALID", "临时提示词必须是 UTF-8 文本。") from exc
        field_mappings = {} if field_mappings is None else field_mappings
        input_bindings = [] if input_bindings is None else input_bindings
        if not isinstance(field_mappings, dict) or any(
            not isinstance(key, str) or not key.strip() or not isinstance(value, str) or not value.strip()
            for key, value in field_mappings.items()
        ):
            raise ToolError("CONTENT_WORKSPACE_PROMPT_MAPPING_INVALID", "字段映射必须是非空字符串对象。")
        if not isinstance(input_bindings, list) or any(not isinstance(value, str) or not value.strip() for value in input_bindings):
            raise ToolError("CONTENT_WORKSPACE_PROMPT_INPUT_INVALID", "输入绑定必须是字符串数组。")
        file_hash = _sha256_file(source)
        existing = state["prompts"].get(prompt_id)
        if existing and existing.get("sha256") != file_hash:
            raise ToolError(
                "CONTENT_WORKSPACE_PROMPT_CHANGED",
                "提示词文件内容已变化；请使用新的 promptId 重新登记，旧绑定不会继续执行。",
            )
        record = {
            "promptId": prompt_id,
            "absolutePath": str(source),
            "sha256": file_hash,
            "sizeBytes": size,
            "stage": stage,
            "purpose": purpose.strip(),
            "executionOrder": execution_order,
            "fieldMappings": {key.strip(): value.strip() for key, value in field_mappings.items()},
            "inputBindings": [value.strip() for value in input_bindings],
            "scope": "current_task_and_workspace_only",
            "bodyCopiedIntoSkill": False,
            "registeredAt": utc_now(),
        }
        state["prompts"][prompt_id] = record
        self._save(state)
        return {"prompt": record, "channelBindingStatus": "UNBOUND", "skillInstalled": False}

    def save_document(
        self,
        *,
        task_id: Any,
        workspace_id: Any,
        binding_proof: Any,
        document_id: Any,
        title: Any,
        stage: Any,
        purpose: Any,
        language: Any,
        content: Any,
        media_type: Any = "text/markdown",
        source_refs: Any = None,
        confirmation_required: Any = True,
    ) -> dict[str, Any]:
        state = self._assert(task_id=task_id, workspace_id=workspace_id, binding_proof=binding_proof)
        document_id = _safe_id(document_id, "documentId", maximum=128)
        if stage not in DOCUMENT_STAGES:
            raise ToolError("CONTENT_WORKSPACE_DOCUMENT_STAGE_INVALID", "文档阶段无效。")
        for value, field, maximum in ((title, "title", 240), (purpose, "purpose", 500), (language, "language", 32)):
            if not isinstance(value, str) or not value.strip() or len(value.strip()) > maximum:
                raise ToolError("CONTENT_WORKSPACE_DOCUMENT_INVALID", f"{field} 无效。")
        if not isinstance(content, str) or not content.strip():
            raise ToolError("CONTENT_WORKSPACE_DOCUMENT_EMPTY", "文档内容不能为空。")
        if media_type not in {"text/plain", "text/markdown", "application/json"}:
            raise ToolError("CONTENT_WORKSPACE_MEDIA_TYPE_INVALID", "自由创作文档只接受文本、Markdown 或 JSON。")
        if not isinstance(confirmation_required, bool):
            raise ToolError("CONTENT_WORKSPACE_CONFIRMATION_POLICY_INVALID", "文档确认要求必须是布尔值。")
        source_refs = [] if source_refs is None else source_refs
        if not isinstance(source_refs, list) or any(not isinstance(value, str) or not value.strip() for value in source_refs):
            raise ToolError("CONTENT_WORKSPACE_SOURCE_REF_INVALID", "来源引用必须是字符串数组。")
        current = state["documents"].get(document_id)
        version = int(current.get("version", 0)) + 1 if isinstance(current, dict) else 1
        suffix = ".md" if media_type == "text/markdown" else ".json" if media_type == "application/json" else ".txt"
        relative = Path("documents") / document_id / f"v{version:03d}{suffix}"
        target = self._workspace_root(workspace_id) / relative
        _atomic_text(target, content)
        record = {
            "documentId": document_id,
            "title": title.strip(),
            "stage": stage,
            "purpose": purpose.strip(),
            "language": language.strip(),
            "mediaType": media_type,
            "version": version,
            "absolutePath": str(target),
            "relativePath": relative.as_posix(),
            "sizeBytes": target.stat().st_size,
            "sha256": _sha256_file(target),
            "sourceRefs": [value.strip() for value in source_refs],
            "confirmationRequired": confirmation_required,
            "confirmation": {
                "confirmed": False,
                "status": "AWAITING_USER_CONFIRMATION" if confirmation_required else "INFORMATIONAL_NOT_REQUIRED",
            },
            "createdAt": utc_now(),
        }
        state["documents"][document_id] = record
        if state.get("productionBinding"):
            state["productionBinding"]["status"] = "INVALIDATED_BY_CONTENT_CHANGE"
            state["state"] = "CREATIVE_ACTIVE"
        self._save(state)
        return {"document": record, "channelBindingStatus": self._public(state)["channelBindingStatus"]}

    def confirm_document(
        self,
        *,
        task_id: Any,
        workspace_id: Any,
        binding_proof: Any,
        document_id: Any,
        confirmation: Any,
    ) -> dict[str, Any]:
        state = self._assert(task_id=task_id, workspace_id=workspace_id, binding_proof=binding_proof)
        document_id = _safe_id(document_id, "documentId", maximum=128)
        record = state["documents"].get(document_id)
        if not isinstance(record, dict):
            raise ToolError("CONTENT_WORKSPACE_DOCUMENT_NOT_FOUND", "没有找到需要确认的当前文档。")
        if record.get("confirmationRequired") is False:
            raise ToolError(
                "CONTENT_WORKSPACE_DUPLICATE_CONFIRMATION_FORBIDDEN",
                "该文档仅供查看，不设置重复确认门；请确认最终目标语言正式稿。",
            )
        if record.get("confirmation", {}).get("status") == "REJECTED_BY_USER":
            raise ToolError(
                "CONTENT_WORKSPACE_DOCUMENT_REJECTED",
                "该版本已被用户否决，不能重新确认；如需继续必须保存一个真正的新版本。",
            )
        expected_ref = f"task:{state['taskId']}:confirm-content:{state['workspaceId']}:{document_id}:v{record['version']:03d}"
        if (
            not isinstance(confirmation, dict)
            or confirmation.get("confirmed") is not True
            or confirmation.get("confirmationRef") != expected_ref
            or confirmation.get("sha256") != record["sha256"]
        ):
            raise ToolError(
                "CONTENT_WORKSPACE_CONFIRMATION_REQUIRED",
                "必须确认当前版本及其 SHA-256，旧版本确认不能复用。",
                details={"expectedConfirmationRef": expected_ref, "expectedSha256": record["sha256"]},
            )
        record["confirmation"] = {
            "confirmed": True,
            "status": "CONFIRMED",
            "confirmationRef": expected_ref,
            "confirmedAt": confirmation.get("confirmedAt") or utc_now(),
            "source": "current_task_user",
        }
        self._save(state)
        return {"document": record, "next": "只确认了该文档当前版本；不会自动进入制作。"}

    def reject_document(
        self,
        *,
        task_id: Any,
        workspace_id: Any,
        binding_proof: Any,
        document_id: Any,
        rejection: Any,
    ) -> dict[str, Any]:
        state = self._assert(task_id=task_id, workspace_id=workspace_id, binding_proof=binding_proof)
        document_id = _safe_id(document_id, "documentId", maximum=128)
        record = state["documents"].get(document_id)
        if not isinstance(record, dict):
            raise ToolError("CONTENT_WORKSPACE_DOCUMENT_NOT_FOUND", "没有找到需要否决的当前文档。")
        expected_ref = f"task:{state['taskId']}:reject-content:{state['workspaceId']}:{document_id}:v{record['version']:03d}"
        if (
            not isinstance(rejection, dict)
            or rejection.get("rejected") is not True
            or rejection.get("explicitUserInstruction") is not True
            or rejection.get("confirmationRef") != expected_ref
            or rejection.get("sha256") != record["sha256"]
            or not isinstance(rejection.get("reason"), str)
            or not rejection["reason"].strip()
        ):
            raise ToolError(
                "CONTENT_WORKSPACE_REJECTION_REQUIRED",
                "只有当前任务中用户明确否决当前版本时才能标记作废。",
                details={"expectedConfirmationRef": expected_ref, "expectedSha256": record["sha256"]},
            )
        record["confirmation"] = {
            "confirmed": False,
            "status": "REJECTED_BY_USER",
            "confirmationRef": expected_ref,
            "rejectedAt": rejection.get("rejectedAt") or utc_now(),
            "source": "current_task_user",
            "reason": rejection["reason"].strip(),
        }
        binding = state.get("productionBinding")
        if isinstance(binding, dict) and binding.get("sourceDocumentId") == document_id:
            binding["status"] = "INVALIDATED_BY_CONTENT_REJECTION"
            state["state"] = "CREATIVE_ACTIVE"
        self._save(state)
        return {
            "document": record,
            "next": "该版本已永久排除为后续输入；需要继续时必须保存全新的版本。",
        }

    def authorize_auto_upload(
        self,
        *,
        task_id: Any,
        workspace_id: Any,
        binding_proof: Any,
        authorization: Any,
    ) -> dict[str, Any]:
        state = self._assert(task_id=task_id, workspace_id=workspace_id, binding_proof=binding_proof)
        expected_ref = f"task:{state['taskId']}:auto-upload:{state['workspaceId']}"
        if (
            not isinstance(authorization, dict)
            or authorization.get("authorized") is not True
            or authorization.get("explicitUserInstruction") is not True
            or authorization.get("confirmationRef") != expected_ref
            or not isinstance(authorization.get("sourceText"), str)
            or not authorization["sourceText"].strip()
        ):
            raise ToolError(
                "PROJECT_AUTO_UPLOAD_AUTHORIZATION_REQUIRED",
                "自动上传只能来自当前任务中用户明确说出的自动上传要求。",
                details={"expectedConfirmationRef": expected_ref},
            )
        record = {
            "authorized": True,
            "granted": True,
            "version": "G6_FINAL_CHINESE_REVIEW_V1",
            "uploadPolicy": "AUTO",
            "scope": "current_task_and_project_only",
            "source": "current_task_explicit",
            "taskId": state["taskId"],
            "projectId": state["projectId"],
            "workspaceId": state["workspaceId"],
            "confirmationRef": expected_ref,
            "confirmedAt": authorization.get("confirmedAt") or utc_now(),
            "sourceTextSha256": _sha256_bytes(authorization["sourceText"].strip().encode("utf-8")),
            "revoked": False,
        }
        state["autoUploadAuthorization"] = record
        self._save(state)
        return {
            "autoUploadAuthorization": record,
            "reconfirmationRequiredAtFinalReview": False,
            "note": "最终中文验收卡仍会展示，但不会重复等待确认。",
        }

    def bind_for_production(
        self,
        *,
        task_id: Any,
        workspace_id: Any,
        binding_proof: Any,
        channel_profile_id: Any,
        channel_binding_proof: Any,
        production_source_document_id: Any,
        production_config: Any,
        confirmation: Any,
    ) -> dict[str, Any]:
        state = self._assert(task_id=task_id, workspace_id=workspace_id, binding_proof=binding_proof)
        channel_profile_id = _safe_id(channel_profile_id, "channelProfileId")
        self.store.assert_binding(
            task_id=state["taskId"],
            channel_profile_id=channel_profile_id,
            binding_proof=channel_binding_proof,
        )
        channel = self.store.get_channel(channel_profile_id)
        source_id = _safe_id(production_source_document_id, "productionSourceDocumentId", maximum=128)
        source = state["documents"].get(source_id)
        if not isinstance(source, dict) or source.get("confirmation", {}).get("confirmed") is not True:
            raise ToolError("PRODUCTION_SOURCE_NOT_CONFIRMED", "开始制作前必须选择并确认唯一正式文稿。")
        if not isinstance(production_config, dict) or not production_config:
            raise ToolError("PRODUCTION_SETTINGS_REQUIRED", "开始制作前必须确认频道号和完整生产配置。")
        production_mode = production_config.get("productionMode")
        if (
            not isinstance(production_mode, dict)
            or production_mode.get("id") not in {"fast_auto", "balanced", "director"}
            or production_mode.get("selectionSource") != "user"
            or production_mode.get("confirmed") is not True
        ):
            raise ToolError(
                "PRODUCTION_MODE_CONFIRMATION_REQUIRED",
                "每次开始制作都必须先让用户本次选择：极速自动、平衡或精品导演模式；不得继承旧项目或频道预设。",
            )
        video_generation = production_config.get("videoGeneration")
        prompt_generation = production_config.get("promptGeneration")
        scene_image_cadence = production_config.get("sceneImageCadence")
        sound_effects = production_config.get("soundEffects")
        if (
            production_config.get("settingsContractVersion") != "2.0"
            or production_config.get("deliveryMode") not in {"auto_render", "jianying_refine"}
            or production_config.get("deliveryModeSelectionSource") != "user"
            or not isinstance(video_generation, dict)
            or video_generation.get("selectionSource") != "user"
            or video_generation.get("confirmed") is not True
            or not isinstance(prompt_generation, dict)
            or prompt_generation.get("selectionSource") != "user"
            or prompt_generation.get("confirmed") is not True
            or not isinstance(scene_image_cadence, dict)
            or scene_image_cadence.get("selectionSource") != "user"
            or scene_image_cadence.get("confirmed") is not True
            or not isinstance(sound_effects, dict)
            or not isinstance(sound_effects.get("enabled"), bool)
            or sound_effects.get("selectionSource") != "user"
            or sound_effects.get("confirmed") is not True
        ):
            raise ToolError(
                "PRODUCTION_USER_SETTINGS_NOT_FROZEN",
                "新任务必须一次确认并冻结成片方式、纯音效、提示词开关、镜头视频范围和图片覆盖节奏。",
            )
        expected_ref = f"task:{state['taskId']}:start-production:{state['workspaceId']}:{channel_profile_id}"
        if (
            not isinstance(confirmation, dict)
            or confirmation.get("confirmed") is not True
            or confirmation.get("confirmationRef") != expected_ref
            or confirmation.get("channelSerial") != channel.get("publisherBinding", {}).get("channelSerial")
        ):
            raise ToolError(
                "PRODUCTION_GATE_CONFIRMATION_REQUIRED",
                "只有用户明确开始制作并确认目标频道与生产配置后才能绑定频道。",
                details={"expectedConfirmationRef": expected_ref},
            )
        confirmed_documents = {
            key: value
            for key, value in state["documents"].items()
            if value.get("confirmation", {}).get("confirmed") is True
        }
        project_upload_grant = None
        if isinstance(state.get("autoUploadAuthorization"), dict):
            upload_policy = production_config.get("uploadPolicy")
            privacy_status = production_config.get("privacyStatus")
            if upload_policy != "AUTO" or privacy_status not in {"private", "unlisted", "public", "scheduled"}:
                raise ToolError(
                    "AUTO_UPLOAD_PRODUCTION_SETTINGS_REQUIRED",
                    "已授权自动上传时，制作设置必须明确冻结 uploadPolicy=AUTO 和有效隐私状态。",
                )
            source_authorization = state["autoUploadAuthorization"]
            project_upload_grant = {
                "granted": True,
                "version": source_authorization["version"],
                "confirmedAt": source_authorization["confirmedAt"],
                "source": "current_task_explicit",
                "scope": "current_task_and_project_only",
                "projectId": state["projectId"],
                "uploadPolicy": "AUTO",
                "channelSerial": channel["publisherBinding"]["channelSerial"],
                "privacyStatus": privacy_status,
                "confirmationRef": source_authorization["confirmationRef"],
                "revoked": False,
            }
        handoff = {
            "schemaVersion": "1.0.0",
            "workspaceId": state["workspaceId"],
            "taskId": state["taskId"],
            "projectId": state["projectId"],
            "channelProfileId": channel_profile_id,
            "channelSerial": channel["publisherBinding"]["channelSerial"],
            "productionSource": {
                "documentId": source_id,
                "version": source["version"],
                "sha256": source["sha256"],
                "absolutePath": source["absolutePath"],
            },
            "confirmedDocuments": {
                key: {"version": value["version"], "sha256": value["sha256"], "absolutePath": value["absolutePath"]}
                for key, value in confirmed_documents.items()
            },
            "productionConfig": production_config,
            "autoUploadAuthorization": state.get("autoUploadAuthorization"),
            "projectAutoUploadGrant": project_upload_grant,
            "confirmationRef": expected_ref,
            "createdAt": utc_now(),
            "status": "BOUND_FOR_PRODUCTION",
        }
        handoff_path = self._workspace_root(workspace_id) / "production" / "production-handoff-v001.json"
        _atomic_json(handoff_path, handoff)
        state["productionBinding"] = {
            "status": "BOUND_FOR_PRODUCTION",
            "channelProfileId": channel_profile_id,
            "channelSerial": channel["publisherBinding"]["channelSerial"],
            "sourceDocumentId": source_id,
            "confirmationRef": expected_ref,
            "handoffPath": str(handoff_path),
            "createdAt": handoff["createdAt"],
        }
        state["channelProfileId"] = channel_profile_id
        state["channelSerial"] = channel["publisherBinding"]["channelSerial"]
        state["state"] = "PRODUCTION_BOUND"
        self._save(state)
        return {
            "productionHandoff": handoff,
            "productionHandoffPath": str(handoff_path),
            "autoUploadReconfirmationRequired": False if state.get("autoUploadAuthorization") else None,
            "next": "按正式稿生成并校验配音稿，复用已确认包装素材并只补齐缺失项。",
        }

    def prepare_narration(
        self,
        *,
        task_id: Any,
        workspace_id: Any,
        binding_proof: Any,
        source_document_id: Any,
        language: Any,
        narration_title: Any,
        narration_content: Any,
        narration_title_chinese: Any = None,
        spoken_section_headings: Any = False,
        cleanup_report: Any = None,
    ) -> dict[str, Any]:
        state = self._assert(task_id=task_id, workspace_id=workspace_id, binding_proof=binding_proof)
        binding = state.get("productionBinding")
        if not isinstance(binding, dict) or binding.get("status") != "BOUND_FOR_PRODUCTION":
            raise ToolError("PRODUCTION_BINDING_REQUIRED", "只有确认开始制作并绑定频道后才能生成正式配音稿。")
        source_document_id = _safe_id(source_document_id, "sourceDocumentId", maximum=128)
        source = state["documents"].get(source_document_id)
        if not isinstance(source, dict) or source.get("confirmation", {}).get("confirmed") is not True:
            raise ToolError("NARRATION_SOURCE_NOT_CONFIRMED", "配音稿必须来自用户已确认的当前正式文稿。")
        if binding.get("sourceDocumentId") not in (None, source_document_id):
            raise ToolError("NARRATION_SOURCE_MISMATCH", "配音稿来源与制作门选择的正式文稿不一致。")
        if not isinstance(language, str) or not language.strip():
            raise ToolError("NARRATION_LANGUAGE_REQUIRED", "配音稿语言不能为空。")
        if not isinstance(narration_title, str) or not narration_title.strip() or len(narration_title.strip()) > 100:
            raise ToolError("NARRATION_TITLE_REQUIRED", "口播稿必须带有一个不超过 100 字符的正式标题。")
        clean_title = narration_title.strip()
        if language.strip().lower().startswith("zh"):
            clean_title_chinese = narration_title_chinese.strip() if isinstance(narration_title_chinese, str) and narration_title_chinese.strip() else clean_title
        elif not isinstance(narration_title_chinese, str) or not narration_title_chinese.strip() or len(narration_title_chinese.strip()) > 200:
            raise ToolError("NARRATION_TITLE_CHINESE_REQUIRED", "非中文口播稿标题必须附中文对照供用户审核。")
        else:
            clean_title_chinese = narration_title_chinese.strip()
        if not isinstance(narration_content, str) or not narration_content.strip():
            raise ToolError("NARRATION_CONTENT_EMPTY", "配音稿不能为空。")
        if not isinstance(spoken_section_headings, bool):
            raise ToolError("NARRATION_HEADING_OPTION_INVALID", "章节标题朗读选项必须是布尔值。")
        matches = [match.group(0).strip() for match in SPOKEN_HEADING.finditer(narration_content)]
        if matches and not spoken_section_headings:
            raise ToolError(
                "NARRATION_SPOKEN_HEADING_FOUND",
                "配音稿包含未获授权朗读的章节标题；请移除，或在制作设置中明确允许朗读章节标题。",
                details={"matches": matches[:20]},
            )
        cleanup_report = {} if cleanup_report is None else cleanup_report
        if not isinstance(cleanup_report, dict):
            raise ToolError("NARRATION_CLEANUP_REPORT_INVALID", "配音稿整理报告必须是对象。")
        production_root = self._workspace_root(workspace_id) / "production" / "narration"
        existing = binding.get("narration") if isinstance(binding.get("narration"), dict) else {}
        version = int(existing.get("version", 0)) + 1
        target = production_root / f"narration-v{version:03d}.txt"
        _atomic_text(target, narration_content.strip())
        record = {
            "schemaVersion": "1.0.0",
            "version": version,
            "sourceDocumentId": source_document_id,
            "sourceDocumentVersion": source["version"],
            "sourceDocumentSha256": source["sha256"],
            "sourceDocumentTitle": source["title"],
            "language": language.strip(),
            "title": clean_title,
            "titleZhTranslation": clean_title_chinese,
            "titleSource": "confirmed_narration",
            "titleGenerationRequired": False,
            "spokenSectionHeadings": spoken_section_headings,
            "absolutePath": str(target),
            "sha256": _sha256_file(target),
            "cleanupReport": cleanup_report,
            "productionUseAllowed": True,
            "createdAt": utc_now(),
        }
        binding["sourceDocumentId"] = source_document_id
        binding["narration"] = record
        self._save(state)
        _atomic_json(Path(binding["handoffPath"]), {
            **json.loads(Path(binding["handoffPath"]).read_text(encoding="utf-8-sig")),
            "narration": record,
        })
        return {
            "narration": record,
            "next": "正式发布标题默认直接使用本口播稿标题；只补齐尚未确认的简介、Hashtags 和封面，再移交工坊。",
        }

    def production_materialization_context(
        self,
        *,
        task_id: Any,
        workspace_id: Any,
        binding_proof: Any,
        production_handoff_path: Any,
    ) -> dict[str, Any]:
        """Return a verified, read-only bridge context for machine package materialization.

        The free workspace and the legacy content-package store intentionally have
        separate roots.  This method is the single fail-closed boundary between
        them: it proves that the selected manuscript, prepared narration, channel,
        project, and handoff file all still belong to the current task before the
        content center is allowed to create its internal compatibility contracts.
        """
        state = self._assert(task_id=task_id, workspace_id=workspace_id, binding_proof=binding_proof)
        binding = state.get("productionBinding")
        if not isinstance(binding, dict) or binding.get("status") != "BOUND_FOR_PRODUCTION":
            raise ToolError("PRODUCTION_BINDING_REQUIRED", "自由创作工作区尚未完成当前任务的制作绑定。")
        handoff_path = Path(str(production_handoff_path or "")).resolve()
        expected_handoff_path = Path(str(binding.get("handoffPath") or "")).resolve()
        workspace_root = self._workspace_root(workspace_id).resolve()
        try:
            handoff_path.relative_to(workspace_root)
        except ValueError as exc:
            raise ToolError("CONTENT_WORKSPACE_HANDOFF_PATH_INVALID", "制作交接文件不在当前自由创作工作区内。") from exc
        if handoff_path != expected_handoff_path or not handoff_path.is_file():
            raise ToolError(
                "CONTENT_WORKSPACE_PRODUCTION_HANDOFF_REQUIRED",
                "必须使用当前工作区制作绑定返回的精确交接文件。",
                details={"requiredHandoffPath": str(expected_handoff_path)},
            )
        try:
            handoff = json.loads(handoff_path.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ToolError("CONTENT_WORKSPACE_HANDOFF_INVALID", "制作交接文件不可读或已损坏。") from exc
        if any(
            (
                handoff.get("taskId") != state["taskId"],
                handoff.get("workspaceId") != state["workspaceId"],
                handoff.get("projectId") != state["projectId"],
                handoff.get("channelProfileId") != binding.get("channelProfileId"),
                handoff.get("confirmationRef") != binding.get("confirmationRef"),
            )
        ):
            raise ToolError("CONTENT_WORKSPACE_HANDOFF_INVALID", "制作交接文件的任务、项目、频道或确认记录不一致。")
        source_id = binding.get("sourceDocumentId")
        source = state.get("documents", {}).get(source_id)
        if not isinstance(source, dict) or source.get("confirmation", {}).get("confirmed") is not True:
            raise ToolError("PRODUCTION_SOURCE_NOT_CONFIRMED", "制作来源正式稿不再是当前已确认版本。")
        source_path = Path(str(source.get("absolutePath") or "")).resolve()
        try:
            source_path.relative_to(workspace_root)
        except ValueError as exc:
            raise ToolError("CONTENT_WORKSPACE_SOURCE_PATH_INVALID", "制作来源正式稿不在当前工作区内。") from exc
        if not source_path.is_file() or _sha256_file(source_path) != source.get("sha256"):
            raise ToolError("CONTENT_WORKSPACE_SOURCE_HASH_MISMATCH", "制作来源正式稿缺失或 SHA-256 已变化。")
        narration = binding.get("narration")
        if not isinstance(narration, dict) or narration.get("productionUseAllowed") is not True:
            raise ToolError("NARRATION_PREPARATION_REQUIRED", "尚未生成并冻结可供制作使用的正式配音稿。")
        if (
            narration.get("sourceDocumentId") != source_id
            or narration.get("sourceDocumentVersion") != source.get("version")
            or narration.get("sourceDocumentSha256") != source.get("sha256")
        ):
            raise ToolError("NARRATION_SOURCE_MISMATCH", "配音稿没有绑定当前已确认正式稿版本与 SHA-256。")
        narration_path = Path(str(narration.get("absolutePath") or "")).resolve()
        try:
            narration_path.relative_to(workspace_root)
        except ValueError as exc:
            raise ToolError("NARRATION_PATH_INVALID", "正式配音稿不在当前工作区内。") from exc
        if not narration_path.is_file() or _sha256_file(narration_path) != narration.get("sha256"):
            raise ToolError("NARRATION_HASH_MISMATCH", "正式配音稿缺失或 SHA-256 已变化。")
        handoff_narration = handoff.get("narration")
        if not isinstance(handoff_narration, dict) or handoff_narration.get("sha256") != narration.get("sha256"):
            raise ToolError("CONTENT_WORKSPACE_HANDOFF_INVALID", "制作交接文件没有绑定当前正式配音稿。")
        return {
            "taskId": state["taskId"],
            "workspaceId": state["workspaceId"],
            "projectId": state["projectId"],
            "channelProfileId": binding["channelProfileId"],
            "productionHandoffPath": str(handoff_path),
            "productionHandoffSha256": _sha256_file(handoff_path),
            "productionConfig": handoff.get("productionConfig"),
            "sourceDocument": json.loads(json.dumps(source, ensure_ascii=False)),
            "sourceContent": source_path.read_text(encoding="utf-8-sig"),
            "narration": json.loads(json.dumps(narration, ensure_ascii=False)),
            "narrationContent": narration_path.read_text(encoding="utf-8-sig"),
        }

    def get(self, *, workspace_id: Any) -> dict[str, Any]:
        return {"workspace": self._public(self._load(workspace_id))}
