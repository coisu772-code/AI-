from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any

from .contracts import canonical_hash, utc_now, with_hash
from .errors import ToolError
from .store import ChannelStore


TASK_PROMPT_CONTRACT_VERSION = "1.0.0"
TASK_PROMPT_STAGES = frozenset({"analysis", "ideation", "drafting", "review", "packaging", "custom"})
_TEXT_PROMPT_SUFFIXES = frozenset({".txt", ".md", ".json", ".yaml", ".yml", ".prompt"})
_MAX_PROMPT_BYTES = 2 * 1024 * 1024
_SAFE_ID = re.compile(r"^[A-Za-z0-9_.:-]{1,128}$")


def _safe_id(value: Any, field: str) -> str:
    if not isinstance(value, str) or _SAFE_ID.fullmatch(value.strip()) is None:
        raise ToolError("INVALID_ARGUMENT", f"{field} 无效。", details={"field": field})
    return value.strip()


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


class TaskPromptRegistry:
    """Register user-owned prompt files for one Codex task without installing Skills.

    Prompt bodies remain in the user-provided files.  The system only persists
    the file identity, execution order, purpose and task-local field mapping.
    Contracts cannot be reused by another task and are never copied into the
    plugin's skill or asset directories.
    """

    def __init__(self, store: ChannelStore) -> None:
        self.store = store

    def _root(self, channel_profile_id: str, task_id: str, project_id: str) -> Path:
        return (
            self.store.channel_path(channel_profile_id)
            / "prompts"
            / "task-scoped"
            / _safe_id(task_id, "taskId")
            / _safe_id(project_id, "projectId")
        )

    def register(
        self,
        *,
        task_id: Any,
        channel_profile_id: Any,
        binding_proof: Any,
        project_id: Any,
        prompt_id: Any,
        prompt_path: Any,
        stage: Any,
        purpose: Any,
        execution_order: Any,
        field_mappings: Any = None,
        input_bindings: Any = None,
    ) -> dict[str, Any]:
        self.store.assert_binding(
            task_id=task_id,
            channel_profile_id=channel_profile_id,
            binding_proof=binding_proof,
        )
        task_id = _safe_id(task_id, "taskId")
        channel_profile_id = _safe_id(channel_profile_id, "channelProfileId")
        project_id = _safe_id(project_id, "projectId")
        prompt_id = _safe_id(prompt_id, "promptId")
        if stage not in TASK_PROMPT_STAGES:
            raise ToolError(
                "TASK_PROMPT_STAGE_INVALID",
                "临时提示词阶段必须是 analysis、ideation、drafting、review、packaging 或 custom。",
            )
        if not isinstance(purpose, str) or not purpose.strip() or len(purpose.strip()) > 240:
            raise ToolError("TASK_PROMPT_PURPOSE_INVALID", "临时提示词用途不能为空且不能超过 240 字。")
        if not isinstance(execution_order, int) or not 1 <= execution_order <= 1000:
            raise ToolError("TASK_PROMPT_ORDER_INVALID", "临时提示词执行顺序必须是 1–1000 的整数。")
        if not isinstance(prompt_path, str) or not prompt_path.strip():
            raise ToolError("TASK_PROMPT_PATH_INVALID", "必须提供用户本次选择的提示词文件路径。")
        source = Path(prompt_path).expanduser().resolve()
        if not source.is_file() or source.suffix.lower() not in _TEXT_PROMPT_SUFFIXES:
            raise ToolError(
                "TASK_PROMPT_FILE_INVALID",
                "临时提示词必须是可读取的 txt、md、json、yaml、yml 或 prompt 文本文件。",
            )
        size = source.stat().st_size
        if size <= 0 or size > _MAX_PROMPT_BYTES:
            raise ToolError("TASK_PROMPT_FILE_SIZE_INVALID", "临时提示词文件为空或超过 2MB。")
        try:
            source.read_text(encoding="utf-8-sig")
        except (OSError, UnicodeError) as exc:
            raise ToolError("TASK_PROMPT_FILE_ENCODING_INVALID", "临时提示词必须是 UTF-8 文本。") from exc

        if field_mappings is None:
            field_mappings = {}
        if not isinstance(field_mappings, dict) or any(
            not isinstance(key, str)
            or not key.strip()
            or not isinstance(value, str)
            or not value.strip()
            for key, value in field_mappings.items()
        ):
            raise ToolError("TASK_PROMPT_FIELD_MAPPING_INVALID", "字段映射必须是非空字符串到非空字符串的对象。")
        if input_bindings is None:
            input_bindings = []
        if not isinstance(input_bindings, list) or any(
            not isinstance(item, str) or not item.strip() for item in input_bindings
        ):
            raise ToolError("TASK_PROMPT_INPUT_BINDING_INVALID", "输入绑定必须是字符串数组。")

        created = utc_now()
        file_hash = _sha256_file(source)
        contract_id = f"task_prompt_{prompt_id}_{file_hash[:12]}"
        contract = with_hash(
            {
                "schemaVersion": TASK_PROMPT_CONTRACT_VERSION,
                "contractType": "task-prompt-contract",
                "id": contract_id,
                "version": "1.0.0",
                "createdAt": created,
                "hashAlgorithm": "SHA-256",
                "hashRule": "canonical-json-v1",
                "upstream": [],
                "taskId": task_id,
                "channelProfileId": channel_profile_id,
                "projectId": project_id,
                "promptId": prompt_id,
                "scope": "current_task_only",
                "stage": stage,
                "purpose": purpose.strip(),
                "executionOrder": execution_order,
                "fieldMappings": {key.strip(): value.strip() for key, value in field_mappings.items()},
                "inputBindings": [item.strip() for item in input_bindings],
                "promptFile": {
                    "absolutePath": str(source),
                    "sizeBytes": size,
                    "sha256": file_hash,
                    "bodyCopiedIntoSkill": False,
                    "bodyCopiedIntoPlugin": False,
                },
                "inheritance": {
                    "otherTasks": False,
                    "otherProjects": False,
                    "channelDefault": False,
                    "futureConversations": False,
                },
            }
        )
        root = self._root(channel_profile_id, task_id, project_id)
        path = root / f"{prompt_id}.json"
        if path.is_file():
            try:
                existing = json.loads(path.read_text(encoding="utf-8-sig"))
            except (OSError, json.JSONDecodeError) as exc:
                raise ToolError("TASK_PROMPT_CONTRACT_INVALID", "现有临时提示词合同损坏。") from exc
            comparable_existing = {
                key: value for key, value in existing.items() if key not in {"createdAt", "contentHash", "id"}
            }
            comparable_new = {
                key: value for key, value in contract.items() if key not in {"createdAt", "contentHash", "id"}
            }
            if comparable_existing != comparable_new:
                raise ToolError(
                    "TASK_PROMPT_ID_CONFLICT",
                    "同一 promptId 已绑定不同文件或映射；请使用新的 promptId。",
                )
            return self._view(existing, path, idempotent=True)
        _atomic_json(path, contract)
        return self._view(contract, path, idempotent=False)

    def _read_contract(self, path: Path) -> dict[str, Any]:
        try:
            contract = json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ToolError("TASK_PROMPT_CONTRACT_INVALID", "临时提示词合同不可读。") from exc
        if (
            contract.get("contractType") != "task-prompt-contract"
            or contract.get("scope") != "current_task_only"
            or canonical_hash(contract) != contract.get("contentHash")
        ):
            raise ToolError("TASK_PROMPT_CONTRACT_INVALID", "临时提示词合同身份或哈希无效。")
        prompt_file = contract.get("promptFile", {})
        source = Path(str(prompt_file.get("absolutePath") or "")).resolve()
        if (
            not source.is_file()
            or source.stat().st_size != prompt_file.get("sizeBytes")
            or _sha256_file(source) != prompt_file.get("sha256")
        ):
            raise ToolError(
                "TASK_PROMPT_FILE_CHANGED",
                "临时提示词文件缺失或内容已变化；必须用新 promptId 重新登记并确认。",
            )
        return contract

    def get_many(
        self,
        *,
        task_id: Any,
        channel_profile_id: Any,
        project_id: Any,
        prompt_ids: Any = None,
    ) -> list[dict[str, Any]]:
        task_id = _safe_id(task_id, "taskId")
        channel_profile_id = _safe_id(channel_profile_id, "channelProfileId")
        project_id = _safe_id(project_id, "projectId")
        root = self._root(channel_profile_id, task_id, project_id)
        if prompt_ids is None:
            paths = sorted(root.glob("*.json")) if root.is_dir() else []
        else:
            if not isinstance(prompt_ids, list) or not prompt_ids:
                raise ToolError("TASK_PROMPT_IDS_INVALID", "taskPromptContractIds 必须是非空字符串数组。")
            available_paths = sorted(root.glob("*.json")) if root.is_dir() else []
            available_by_contract_id: dict[str, Path] = {}
            for available_path in available_paths:
                try:
                    payload = json.loads(available_path.read_text(encoding="utf-8-sig"))
                except (OSError, json.JSONDecodeError) as exc:
                    raise ToolError("TASK_PROMPT_CONTRACT_INVALID", "现有临时提示词合同损坏。") from exc
                contract_id = payload.get("id")
                if isinstance(contract_id, str) and contract_id:
                    available_by_contract_id[contract_id] = available_path
            paths = []
            for item in prompt_ids:
                prompt_or_contract_id = _safe_id(item, "taskPromptContractId")
                direct_path = root / f"{prompt_or_contract_id}.json"
                resolved_path = direct_path if direct_path.is_file() else available_by_contract_id.get(prompt_or_contract_id)
                if resolved_path is None:
                    raise ToolError("TASK_PROMPT_CONTRACT_NOT_FOUND", "当前任务没有找到指定临时提示词合同。")
                paths.append(resolved_path)
            if len({str(path.resolve()) for path in paths}) != len(paths):
                raise ToolError("TASK_PROMPT_IDS_INVALID", "taskPromptContractIds 不能重复引用同一份提示词合同。")
        contracts: list[dict[str, Any]] = []
        for path in paths:
            if not path.is_file():
                raise ToolError("TASK_PROMPT_CONTRACT_NOT_FOUND", "当前任务没有找到指定临时提示词合同。")
            contract = self._read_contract(path)
            if (
                contract.get("taskId") != task_id
                or contract.get("channelProfileId") != channel_profile_id
                or contract.get("projectId") != project_id
            ):
                raise ToolError("TASK_PROMPT_SCOPE_MISMATCH", "临时提示词合同不能跨任务、跨项目或跨频道复用。")
            contracts.append(contract)
        contracts.sort(key=lambda item: (int(item["executionOrder"]), str(item["promptId"])))
        return contracts

    @staticmethod
    def _view(contract: dict[str, Any], path: Path, *, idempotent: bool) -> dict[str, Any]:
        return {
            "contract": contract,
            "contractPath": str(path.resolve()),
            "promptReadPath": contract["promptFile"]["absolutePath"],
            "idempotent": idempotent,
            "skillInstalled": False,
            "pluginAssetCreated": False,
            "expiresOutsideTask": True,
        }
