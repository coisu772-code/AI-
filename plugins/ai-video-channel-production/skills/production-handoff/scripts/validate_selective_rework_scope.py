from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any


ALLOWED_ACTIONS = {"preserve", "reuse", "regenerate", "reexport"}
ASSET_TO_STEP = {
    "character_images": "character_images",
    "voice_matching": "voice_matching",
    "audio": "audio",
    "manuscript": None,
    "image_prompts": "image_prompts",
    "storyboard": "storyboard",
    "grid_image": "grid_image",
    "video": "video",
    "export": "export",
    "final_render": "final_render",
}
EPISODE_PATTERN = re.compile(r"^E\d{2,4}$")
SHA256_PATTERN = re.compile(r"^[0-9a-fA-F]{64}$")


class ScopeError(ValueError):
    pass


def _unique_text_list(value: Any, field: str) -> list[str]:
    if not isinstance(value, list) or not value:
        raise ScopeError(f"{field} 必须是非空数组。")
    result: list[str] = []
    for item in value:
        text = str(item or "").strip()
        if not text or text in result:
            raise ScopeError(f"{field} 包含空值或重复值。")
        result.append(text)
    return result


def _protected_assets(value: Any, field: str) -> dict[str, tuple[str, str]]:
    if value is None:
        return {}
    if not isinstance(value, list):
        raise ScopeError(f"{field} 必须是数组。")
    result: dict[str, tuple[str, str]] = {}
    for index, item in enumerate(value, start=1):
        if not isinstance(item, dict):
            raise ScopeError(f"{field}[{index}] 必须是对象。")
        asset_id = str(item.get("assetId") or "").strip()
        path = str(item.get("path") or "").strip()
        sha256 = str(item.get("sha256") or "").strip().lower()
        if not asset_id or asset_id in result or not path or SHA256_PATTERN.fullmatch(sha256) is None:
            raise ScopeError(f"{field}[{index}] 的 assetId、path 或 sha256 无效。")
        result[asset_id] = (path, sha256)
    return result


def validate(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ScopeError("范围锁必须是对象。")
    if payload.get("schemaVersion") != "1.0":
        raise ScopeError("schemaVersion 必须为 1.0。")
    for field in ("taskId", "projectId", "userScopeEvidence"):
        if not str(payload.get(field) or "").strip():
            raise ScopeError(f"{field} 不能为空。")

    episode_scope = _unique_text_list(payload.get("episodeScope"), "episodeScope")
    if any(EPISODE_PATTERN.fullmatch(item) is None for item in episode_scope):
        raise ScopeError("episodeScope 只能使用 E01、E02 等集数 ID。")

    matrix = payload.get("assetActionMatrix")
    if not isinstance(matrix, dict) or set(matrix) != set(ASSET_TO_STEP):
        missing = sorted(set(ASSET_TO_STEP) - set(matrix or {}))
        extra = sorted(set(matrix or {}) - set(ASSET_TO_STEP))
        raise ScopeError(f"assetActionMatrix 必须完整声明全部资产；missing={missing}, extra={extra}。")
    for asset, action in matrix.items():
        if action not in ALLOWED_ACTIONS:
            raise ScopeError(f"assetActionMatrix.{asset} 动作无效。")
        if asset not in {"export", "final_render"} and action == "reexport":
            raise ScopeError(f"{asset} 不能使用 reexport。")
        if asset == "manuscript" and action in {"regenerate", "reexport"}:
            raise ScopeError("正式稿修改必须返回上游，不能作为工坊局部重做步骤。")

    hard_raw = payload.get("hardExclusions", [])
    if not isinstance(hard_raw, list):
        raise ScopeError("hardExclusions 必须是数组。")
    hard_exclusions: list[str] = []
    for item in hard_raw:
        text = str(item or "").strip()
        if not text or text in hard_exclusions:
            raise ScopeError("hardExclusions 包含空值或重复值。")
        hard_exclusions.append(text)
    if any(item not in matrix for item in hard_exclusions):
        raise ScopeError("hardExclusions 包含未知资产。")
    if any(matrix[item] not in {"preserve", "reuse"} for item in hard_exclusions):
        raise ScopeError("hardExclusions 中的资产不能被重新生成或重新导出。")

    command = payload.get("command")
    if not isinstance(command, dict):
        raise ScopeError("command 必须是对象。")
    selected_episodes = _unique_text_list(command.get("episodes"), "command.episodes")
    selected_steps = _unique_text_list(command.get("steps"), "command.steps")
    force_steps_raw = command.get("forceRerunSteps", [])
    if not isinstance(force_steps_raw, list):
        raise ScopeError("command.forceRerunSteps 必须是数组。")
    force_steps = []
    for item in force_steps_raw:
        text = str(item or "").strip()
        if not text or text in force_steps:
            raise ScopeError("command.forceRerunSteps 包含空值或重复值。")
        force_steps.append(text)

    expected_steps = [
        step
        for asset, step in ASSET_TO_STEP.items()
        if step is not None and matrix[asset] in {"regenerate", "reexport"}
    ]
    if selected_episodes != episode_scope:
        raise ScopeError(f"command.episodes 超出冻结范围；expected={episode_scope}, actual={selected_episodes}。")
    if selected_steps != expected_steps:
        raise ScopeError(f"command.steps 超出冻结范围；expected={expected_steps}, actual={selected_steps}。")
    if any(step not in selected_steps for step in force_steps):
        raise ScopeError("forceRerunSteps 只能包含本次已选步骤。")

    before = _protected_assets(payload.get("protectedAssetsBefore"), "protectedAssetsBefore")
    after = _protected_assets(payload.get("protectedAssetsAfter"), "protectedAssetsAfter")
    if after:
        if set(before) != set(after):
            raise ScopeError("受保护资产集合在执行后发生变化。")
        changed = [asset_id for asset_id in before if before[asset_id] != after[asset_id]]
        if changed:
            raise ScopeError(f"范围外资产路径或 SHA-256 发生变化：{changed}。")

    return {
        "ok": True,
        "taskId": str(payload["taskId"]).strip(),
        "projectId": str(payload["projectId"]).strip(),
        "episodeScope": episode_scope,
        "selectedSteps": selected_steps,
        "forceRerunSteps": force_steps,
        "hardExclusions": hard_exclusions,
        "protectedAssetCount": len(before),
        "postExecutionVerified": bool(after),
    }


def _read_payload(path: str) -> Any:
    if path == "-":
        return json.load(sys.stdin)
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate a selective Workshop rework scope lock.")
    parser.add_argument("scope", help="Scope-lock JSON path, or - for stdin.")
    args = parser.parse_args()
    try:
        result = validate(_read_payload(args.scope))
    except (OSError, json.JSONDecodeError, ScopeError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        return 1
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
