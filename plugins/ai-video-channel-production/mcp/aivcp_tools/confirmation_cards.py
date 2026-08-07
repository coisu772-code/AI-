from __future__ import annotations

from copy import deepcopy
from typing import Any


DISPLAY_MODE = "CHINESE_FIRST_WITH_TARGET_LANGUAGE"

_GATE_TITLES = {
    "G1": "频道与系统确认",
    "G2": "创作条件确认",
    "G3": "选题与故事确认",
    "G4": "正式文稿确认",
    "G5": "发布素材确认",
    "G6": "上传前最终验收",
}


def _gate_prefix(gate: Any) -> str:
    text = str(gate or "CONFIRMATION")
    return text.split("_", 1)[0]


def chinese_first_confirmation_card(
    *,
    gate: str,
    target_language: str | None,
    chinese_primary: dict[str, Any],
    target_language_comparison: dict[str, Any] | None = None,
    confirmed: bool = False,
    technical: dict[str, Any] | None = None,
) -> dict[str, Any]:
    language = target_language if isinstance(target_language, str) and target_language else "und"
    prefix = _gate_prefix(gate)
    return {
        "schemaVersion": "1.0.0",
        "displayMode": DISPLAY_MODE,
        "displayLanguage": "zh-CN",
        "gate": gate,
        "titleZh": _GATE_TITLES.get(prefix, "流程确认"),
        "chinesePrimary": deepcopy(chinese_primary),
        "targetLanguageComparison": {
            "labelZh": "目标语言对照",
            "language": language,
            "sameAsChinese": language.lower().startswith("zh"),
            **deepcopy(target_language_comparison or {}),
        },
        "confirmed": bool(confirmed),
        "technical": deepcopy(technical or {}),
    }


def _find_target_language(value: Any) -> str | None:
    if isinstance(value, dict):
        for key in ("targetLanguage", "target_language", "defaultLanguage", "default_language"):
            candidate = value.get(key)
            if isinstance(candidate, str) and candidate:
                return candidate
        for child in value.values():
            found = _find_target_language(child)
            if found:
                return found
    elif isinstance(value, list):
        for child in value:
            found = _find_target_language(child)
            if found:
                return found
    return None


def _normalize_card(card: dict[str, Any], *, target_language: str | None) -> dict[str, Any]:
    if card.get("displayMode") == DISPLAY_MODE:
        return card
    gate = str(card.get("gate") or "CONFIRMATION")
    confirmed = bool(card.get("confirmed", False))
    summary = "该步骤已经确认。" if confirmed else "该步骤需要用户确认后才能继续。"
    technical = deepcopy(card)
    language = target_language or _find_target_language(card)
    normalized = chinese_first_confirmation_card(
        gate=gate,
        target_language=language,
        chinese_primary={
            "summaryZh": summary,
            "decisionRequiredZh": "无需再次操作。" if confirmed else "请先阅读中文内容，再核对目标语言对照后确认。",
        },
        target_language_comparison={
            "available": bool(language and language != "und"),
            "summaryZh": "本卡暂无独立外语正文；原始技术值保留在 technical 中。",
        },
        confirmed=confirmed,
        technical=technical,
    )
    for key, value in card.items():
        if key not in normalized:
            normalized[key] = deepcopy(value)
    return normalized


def normalize_confirmation_cards(value: Any) -> Any:
    """Return a deep copy with every `confirmationCard` using the Chinese-first contract."""

    root_language = _find_target_language(value)

    def visit(node: Any, inherited_language: str | None) -> Any:
        if isinstance(node, list):
            return [visit(item, inherited_language) for item in node]
        if not isinstance(node, dict):
            return node
        local_language = _find_target_language(node) or inherited_language
        output: dict[str, Any] = {}
        for key, child in node.items():
            if key == "confirmationCard" and isinstance(child, dict):
                output[key] = _normalize_card(deepcopy(child), target_language=local_language)
            else:
                output[key] = visit(child, local_language)
        return output

    return visit(value, root_language)
