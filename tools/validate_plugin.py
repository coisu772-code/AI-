from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

import yaml


ROOT = Path(__file__).resolve().parents[1]
PLUGIN_NAME = "ai-video-channel-production"
MARKETPLACE_NAME = "novel-manga-production"
PLUGIN_ROOT = ROOT / "plugins" / PLUGIN_NAME
NAME_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
CURRENT_PRODUCT_VERSION = "0.8.0-rc.2"

EXPECTED_SKILLS = {
    "channel-production",
    "channel-onboarding",
    "source-library",
    "topic-selection",
    "manuscript-production",
    "publishing-assets",
    "production-handoff",
    "publish-video",
    "data-center",
    "update-ai-video-system",
}
EXPECTED_CONTENT_TOOLS = {
    "content_capabilities",
    "content_project_start",
    "content_topic_checkpoint",
    "content_topic_finalize",
    "content_manuscript_finalize",
    "content_publishing_finalize",
    "content_project_get",
    "content_integrity_check",
    "content_handoff_check",
}
EXPECTED_PRODUCTION_TOOLS = {
    "production_capabilities",
    "production_package_assemble",
    "production_task_start",
    "production_task_get",
    "production_task_run",
    "production_task_pause",
    "production_task_resume",
    "production_task_retry",
    "production_task_invalidate",
    "production_jianying_export_ingest",
    "production_result_validate",
}
EXPECTED_PUBLISH_TOOLS = {
    "assemble_publish_package_v2",
    "validate_publish_package_v2",
    "import_publish_package_v2",
    "get_publication_status",
    "get_publication_receipt",
}
EXPECTED_DATA_TOOLS = {
    "data_center_capabilities",
    "data_video_register",
    "data_collection_run",
    "data_report_generate",
    "data_recommendations_list",
    "data_learning_decide",
    "data_progress_get",
}


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def load_skill_frontmatter(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---\n"):
        raise ValueError("missing opening YAML frontmatter delimiter")
    _, raw, _ = text.split("---", 2)
    document = yaml.safe_load(raw)
    if not isinstance(document, dict):
        raise ValueError("frontmatter must be an object")
    return document


def validate_plugin() -> list[str]:
    errors: list[str] = []
    marketplace = load_json(ROOT / ".agents" / "plugins" / "marketplace.json")
    plugin = load_json(PLUGIN_ROOT / ".codex-plugin" / "plugin.json")

    if marketplace.get("name") != MARKETPLACE_NAME:
        errors.append("marketplace name mismatch")
    entries = marketplace.get("plugins", [])
    if len(entries) != 1:
        errors.append("marketplace must expose exactly one plugin")
    else:
        entry = entries[0]
        if entry.get("name") != PLUGIN_NAME:
            errors.append("marketplace plugin name mismatch")
        source = entry.get("source", {})
        if source != {"source": "local", "path": f"./plugins/{PLUGIN_NAME}"}:
            errors.append("marketplace local source path mismatch")
        if not str(source.get("path", "")).startswith("./"):
            errors.append("repository marketplace source must be relative to the marketplace root")

    plugin_manifest_dir = PLUGIN_ROOT / ".codex-plugin"
    if {path.name for path in plugin_manifest_dir.iterdir()} != {"plugin.json"}:
        errors.append(".codex-plugin must contain only plugin.json")
    if (ROOT / ".codex" / "plugins" / "marketplace.json").exists():
        errors.append("repository must not ship a user-personal marketplace")

    if plugin.get("name") != PLUGIN_NAME or not NAME_PATTERN.fullmatch(plugin.get("name", "")):
        errors.append("plugin name is invalid")
    if plugin.get("version") != CURRENT_PRODUCT_VERSION:
        errors.append(f"plugin version must be {CURRENT_PRODUCT_VERSION} for the Stage8 release candidate")
    if plugin.get("skills") != "./skills/":
        errors.append("plugin skills path must be ./skills/")
    if plugin.get("mcpServers") != "./.mcp.json":
        errors.append("plugin must declare ./.mcp.json")
    try:
        mcp = load_json(PLUGIN_ROOT / ".mcp.json")
        server = mcp.get("mcpServers", {}).get("ai-video-channel-tools", {})
        if server.get("command") != "powershell":
            errors.append("local tool service must use the guarded PowerShell launcher")
        if "./mcp/start.ps1" not in server.get("args", []):
            errors.append("local tool service launcher path mismatch")
        if not (PLUGIN_ROOT / "mcp" / "server.py").is_file():
            errors.append("local tool service server.py is missing")
    except Exception as exc:  # noqa: BLE001
        errors.append(f"invalid MCP configuration: {exc}")
    prompts = plugin.get("interface", {}).get("defaultPrompt", [])
    if not isinstance(prompts, list) or not 1 <= len(prompts) <= 3:
        errors.append("plugin defaultPrompt must contain 1 to 3 prompts")

    skill_dirs = {path.name for path in (PLUGIN_ROOT / "skills").iterdir() if path.is_dir()}
    if skill_dirs != EXPECTED_SKILLS:
        errors.append(f"unexpected skill set: {sorted(skill_dirs)}")

    policies: dict[str, bool] = {}
    skill_texts: dict[str, str] = {}
    for skill_name in sorted(EXPECTED_SKILLS):
        skill_root = PLUGIN_ROOT / "skills" / skill_name
        try:
            skill_texts[skill_name] = (skill_root / "SKILL.md").read_text(encoding="utf-8")
            frontmatter = load_skill_frontmatter(skill_root / "SKILL.md")
        except Exception as exc:  # noqa: BLE001 - aggregate validation failures
            errors.append(f"{skill_name}: invalid SKILL.md: {exc}")
            continue
        if frontmatter.get("name") != skill_name:
            errors.append(f"{skill_name}: frontmatter name mismatch")
        description = frontmatter.get("description")
        if not isinstance(description, str) or not 20 <= len(description) <= 1024:
            errors.append(f"{skill_name}: description must be 20 to 1024 characters")
        try:
            interface = yaml.safe_load((skill_root / "agents" / "openai.yaml").read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{skill_name}: invalid agents/openai.yaml: {exc}")
            continue
        for field in ("display_name", "short_description", "default_prompt"):
            if not isinstance(interface.get("interface", {}).get(field), str):
                errors.append(f"{skill_name}: missing interface.{field}")
        implicit = interface.get("policy", {}).get("allow_implicit_invocation")
        if not isinstance(implicit, bool):
            errors.append(f"{skill_name}: allow_implicit_invocation must be boolean")
        else:
            policies[skill_name] = implicit

    if policies.get("channel-production") is not True:
        errors.append("channel-production must be the implicit total entry")
    if policies.get("channel-onboarding") is not False:
        errors.append("channel-onboarding must remain explicit/orchestrated")
    if policies.get("source-library") is not False:
        errors.append("source-library must remain explicit/orchestrated")
    if policies.get("publish-video") is not True:
        errors.append("publish-video must allow natural-language Stage6 invocation")
    if policies.get("data-center") is not True:
        errors.append("data-center must allow natural-language Stage7 invocation")
    if policies.get("update-ai-video-system") is not True:
        errors.append("update-ai-video-system must allow natural-language update invocation")
    for skill_name in EXPECTED_SKILLS - {"channel-production", "publish-video", "data-center", "update-ai-video-system"}:
        if policies.get(skill_name) is not False:
            errors.append(f"{skill_name} must remain explicit/orchestrated")

    update_text = skill_texts.get("update-ai-video-system", "")
    update_root = PLUGIN_ROOT / "skills" / "update-ai-video-system"
    if not (update_root / "scripts" / "Update-AIVideoSystem.ps1").is_file():
        errors.append("update-ai-video-system is missing its deterministic PowerShell script")
    for marker in ("检查更新", "更新到最新版", "更新AI视频频道生产系统", "-ConfirmUpdate", "GitHub Release"):
        if marker not in update_text:
            errors.append(f"update-ai-video-system is missing required marker: {marker}")

    router_text = skill_texts.get("channel-production", "")
    missing_router_tools = sorted(tool for tool in EXPECTED_CONTENT_TOOLS if tool not in router_text)
    if missing_router_tools:
        errors.append(f"channel-production is missing stage 4 tool routes: {missing_router_tools}")
    missing_production_routes = sorted(tool for tool in ("production_capabilities",) if tool not in router_text)
    if missing_production_routes or "$production-handoff" not in router_text or "VIDEO_READY" not in router_text:
        errors.append("channel-production is missing the Stage5 production route")
    if "$publish-video" not in router_text or any(tool not in router_text for tool in EXPECTED_PUBLISH_TOOLS):
        errors.append("channel-production is missing the Stage6 publisher route")
    if "$data-center" not in router_text or any(tool not in router_text for tool in EXPECTED_DATA_TOOLS):
        errors.append("channel-production is missing the Stage7 data-center route")

    topic_text = skill_texts.get("topic-selection", "")
    for marker in (
        "CONTENT_READY",
        "PARTIAL",
        "fact",
        "inference",
        "unknown",
        "provided-outline",
        "channel-library",
        "analysis-package-v1",
        "unavailable",
        "content_topic_checkpoint",
        "content_topic_finalize",
    ):
        if marker not in topic_text:
            errors.append(f"topic-selection is missing required marker: {marker}")

    manuscript_text = skill_texts.get("manuscript-production", "")
    for marker in (
        "目标语言正式母稿",
        "唯一内容事实源",
        "lineId",
        "content_manuscript_finalize",
        "长期学习写回",
    ):
        if marker not in manuscript_text:
            errors.append(f"manuscript-production is missing required marker: {marker}")

    publishing_text = skill_texts.get("publishing-assets", "")
    for marker in (
        "8～12",
        "16:9",
        "SHA-256",
        "prompt_only",
        "thumbnailProvider",
        "image-provider-v1",
        "恰好 5 个",
        "content_publishing_finalize",
        "content_handoff_check",
        "不调用制作中心",
    ):
        if marker not in publishing_text:
            errors.append(f"publishing-assets is missing required marker: {marker}")
    production_text = skill_texts.get("production-handoff", "")
    for marker in (
        "Production Package v2.1",
        "Production Task v1",
        "P0–P11",
        "production_package_assemble",
        "production_task_start",
        "production_task_get",
        "production_task_run",
        "production_task_retry",
        "production_jianying_export_ingest",
        "production_result_validate",
        "VIDEO_READY",
        ".ready",
        "OAuth",
    ):
        if marker not in production_text:
            errors.append(f"production-handoff is missing required marker: {marker}")
    publish_text = skill_texts.get("publish-video", "")
    for marker in (*sorted(EXPECTED_PUBLISH_TOOLS), "networkExecution=false", "EXTERNAL_APPROVAL_REQUIRED", "youtubeVideoId"):
        if marker not in publish_text:
            errors.append(f"publish-video is missing required marker: {marker}")
    data_text = skill_texts.get("data-center", "")
    data_skill_root = PLUGIN_ROOT / "skills" / "data-center"
    for relative_path in (
        "agents/openai.yaml",
        "references/tool-protocol.md",
        "scripts/check_data_center_install.py",
    ):
        if not (data_skill_root / relative_path).is_file():
            errors.append(f"data-center is missing required file: {relative_path}")
    for marker in (
        *sorted(EXPECTED_DATA_TOOLS),
        "WAITING_FOR_PUBLICATION_RECEIPT",
        "AUTH_REQUIRED",
        "available=false",
        "syntheticFixture=true",
        "AWAITING_LEARNING_DECISION",
        "LONG_TERM_LEARNING_APPROVAL_REQUIRED",
        "OWNER_ANALYTICS_FACT",
        "UNKNOWN",
    ):
        if marker not in data_text:
            errors.append(f"data-center is missing required marker: {marker}")
    if len(EXPECTED_CONTENT_TOOLS | EXPECTED_PRODUCTION_TOOLS | EXPECTED_PUBLISH_TOOLS | EXPECTED_DATA_TOOLS) != 32:
        errors.append("health tool subset must contain exactly 32 tools")
    service_text = (PLUGIN_ROOT / "mcp" / "aivcp_tools" / "service.py").read_text(encoding="utf-8")
    missing_tools = sorted(
        tool
        for tool in EXPECTED_PRODUCTION_TOOLS | EXPECTED_PUBLISH_TOOLS | EXPECTED_DATA_TOOLS
        if tool not in service_text
    )
    if missing_tools:
        errors.append(f"local service is missing Stage5-7 tools: {missing_tools}")
    return errors


def main() -> int:
    errors = validate_plugin()
    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        print(f"Plugin validation failed with {len(errors)} error(s).")
        return 1
    print("Plugin and marketplace validation passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
