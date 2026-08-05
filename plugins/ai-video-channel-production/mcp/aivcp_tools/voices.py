from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .errors import ToolError
from .security import contains_sensitive_material


VOICE_CATALOG_SCHEMA_VERSION = "1.0.0"


@dataclass(slots=True)
class VoiceCatalog:
    path: Path | None

    def capabilities(self) -> dict[str, Any]:
        return {
            "available": bool(self.path and self.path.is_file()),
            "schemaVersion": VOICE_CATALOG_SCHEMA_VERSION,
            "source": "pre-scanned-local-catalog",
            "reasonCode": None if self.path and self.path.is_file() else "VOICE_CATALOG_UNAVAILABLE",
        }

    def read(self) -> dict[str, Any]:
        if not self.path or not self.path.is_file():
            raise ToolError(
                "VOICE_CATALOG_UNAVAILABLE",
                "没有可用的预扫描音色目录；请先运行安装器修复或刷新正式音色目录。",
                retryable=True,
            )
        try:
            document = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ToolError("VOICE_CATALOG_INVALID", "预扫描音色目录不可读。") from exc
        if not isinstance(document, dict) or document.get("schemaVersion") != VOICE_CATALOG_SCHEMA_VERSION:
            raise ToolError("VOICE_CATALOG_INVALID", "预扫描音色目录版本不受支持。")
        if contains_sensitive_material(document):
            raise ToolError("VOICE_CATALOG_UNSAFE", "预扫描音色目录包含不应暴露的敏感字段。")
        engines = document.get("engines")
        if not isinstance(engines, list):
            raise ToolError("VOICE_CATALOG_INVALID", "预扫描音色目录缺少 engines 数组。")
        normalized: list[dict[str, Any]] = []
        for engine in engines:
            if not isinstance(engine, dict):
                raise ToolError("VOICE_CATALOG_INVALID", "音色引擎记录无效。")
            engine_id = engine.get("engineId")
            voices = engine.get("voices")
            if not isinstance(engine_id, str) or not engine_id or not isinstance(voices, list):
                raise ToolError("VOICE_CATALOG_INVALID", "音色引擎缺少 engineId 或 voices。")
            clean_voices = []
            for voice in voices:
                if not isinstance(voice, dict) or not isinstance(voice.get("voiceId"), str) or not voice["voiceId"]:
                    raise ToolError("VOICE_CATALOG_INVALID", "音色记录缺少 voiceId。")
                clean_voices.append(
                    {
                        key: voice[key]
                        for key in ("voiceId", "displayName", "languages", "genderStyle", "recommended")
                        if key in voice
                    }
                )
            normalized.append(
                {
                    "engineId": engine_id,
                    "displayName": engine.get("displayName", engine_id),
                    "installed": bool(engine.get("installed", True)),
                    "voices": clean_voices,
                }
            )
        policies = document.get("enginePolicies", [])
        if not isinstance(policies, list):
            raise ToolError("VOICE_CATALOG_INVALID", "预扫描音色目录的 enginePolicies 无效。")
        clean_policies: list[dict[str, Any]] = []
        for policy in policies:
            if not isinstance(policy, dict) or not isinstance(policy.get("engineId"), str) or not policy["engineId"]:
                raise ToolError("VOICE_CATALOG_INVALID", "预扫描音色目录包含无效的引擎策略。")
            clean_policies.append(
                {
                    key: policy[key]
                    for key in ("engineId", "displayName", "catalogMode", "selectableFromCatalog", "reasonCode")
                    if key in policy
                }
            )
        return {
            "schemaVersion": VOICE_CATALOG_SCHEMA_VERSION,
            "generatedAt": document.get("generatedAt"),
            "engines": normalized,
            "enginePolicies": clean_policies,
        }

    def validate_selection(self, engine_id: Any, voice_id: Any) -> None:
        catalog = self.read()
        for engine in catalog["engines"]:
            if engine["engineId"] != engine_id or not engine["installed"]:
                continue
            if any(voice["voiceId"] == voice_id for voice in engine["voices"]):
                return
        raise ToolError(
            "VOICE_SELECTION_NOT_FOUND",
            "选择的默认配音不在当前已安装的预扫描真实音色目录中。",
            details={"engineId": engine_id, "voiceId": voice_id},
        )
