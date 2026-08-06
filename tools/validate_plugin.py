from __future__ import annotations

import json
import hashlib
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
    "content-source",
    "content-deconstruct",
    "content-rewrite",
    "content-review-edit",
    "content-title-description",
    "publishing-assets",
    "production-handoff",
    "publish-video",
    "data-center",
    "update-ai-video-system",
}
EXPECTED_SOURCE_TOOLS = {
    "source_library_capabilities",
    "source_add_prepare",
    "source_add_confirm",
    "source_job_get",
    "source_job_resume",
    "source_integrity_check",
}
EXPECTED_CONTENT_DECONSTRUCTION_TOOLS = {
    "content_deconstruction_capabilities",
    "content_deconstruction_prepare",
    "content_deconstruction_read_source",
    "content_deconstruction_checkpoint",
    "content_deconstruction_finalize",
    "content_deconstruction_get",
    "content_deconstruction_integrity_check",
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
EXPECTED_VIDEO_ANALYSIS_TOOLS = {
    "video_deconstruction_capabilities",
    "video_deconstruction_prepare",
    "video_deconstruction_read_source",
    "video_deconstruction_checkpoint",
    "video_deconstruction_finalize",
    "video_deconstruction_get",
    "video_deconstruction_integrity_check",
}
EXPECTED_ORIGINAL_IMITATION_TOOLS = {
    "original_imitation_capabilities",
    "original_imitation_prepare",
    "original_imitation_read_source",
    "original_imitation_source_checkpoint",
    "original_imitation_direction_checkpoint",
    "original_imitation_directions_finalize",
    "original_imitation_confirm",
    "original_imitation_get",
    "original_imitation_integrity_check",
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
    for marker in (
        "$content-source",
        "$content-deconstruct",
        "$content-rewrite",
        "$content-review-edit",
        "$content-title-description",
        "content-thumbnail",
        "PLANNED_UNAVAILABLE",
    ):
        if marker not in router_text:
            errors.append(f"channel-production is missing simplified content route marker: {marker}")
    if "$production-handoff" not in router_text or "VIDEO_READY" not in router_text:
        errors.append("channel-production is missing the Stage5 production route")
    if "$publish-video" not in router_text:
        errors.append("channel-production is missing the Stage6 publisher route")
    if "$data-center" not in router_text:
        errors.append("channel-production is missing the Stage7 data-center route")

    source_text = skill_texts.get("content-source", "")
    for marker in (
        *sorted(EXPECTED_SOURCE_TOOLS),
        "CONTENT_READY",
        "PARTIAL",
        "content.txt",
        "$content-deconstruct",
    ):
        if marker not in source_text:
            errors.append(f"content-source is missing required marker: {marker}")

    deconstruction_text = skill_texts.get("content-deconstruct", "")
    for marker in (
        *sorted(EXPECTED_CONTENT_DECONSTRUCTION_TOOLS),
        "originalFacts",
        "analysisConclusions",
        "transferableMethods",
        "prohibitedCopy",
        "unknowns",
        "$content-rewrite",
    ):
        if marker not in deconstruction_text:
            errors.append(f"content-deconstruct is missing required marker: {marker}")

    rewrite_text = skill_texts.get("content-rewrite", "")
    for marker in (
        "direct-rewrite",
        "synthesis-rewrite",
        "sourceTransformationMap",
        "content_project_start",
        "content_topic_checkpoint",
        "content_topic_finalize",
        "content_integrity_check",
        "$content-review-edit",
        "rewrite-draft-vNNN",
    ):
        if marker not in rewrite_text:
            errors.append(f"content-rewrite is missing required marker: {marker}")

    manuscript_text = skill_texts.get("content-review-edit", "")
    for marker in (
        "目标语言正式文本",
        "唯一事实源",
        "lineId",
        "content_manuscript_finalize",
        "SCRIPT_READY",
        "$content-title-description",
        "P0",
        "P1",
    ):
        if marker not in manuscript_text:
            errors.append(f"content-review-edit is missing required marker: {marker}")

    packaging_text = skill_texts.get("content-title-description", "")
    for marker in (
        "prompt-v2.1.txt",
        "title-description-contract.md",
        "title-asset-v1",
        "description-asset-v1",
        "content-title",
        "content-description",
        "content-thumbnail",
        "PLANNED_UNAVAILABLE",
        "SCRIPT_READY",
        "8–12",
        "$publishing-assets",
    ):
        if marker not in packaging_text:
            errors.append(f"content-title-description is missing required marker: {marker}")

    extension_slots_path = PLUGIN_ROOT / "assets" / "content-extension-slots.json"
    try:
        extension_slots = load_json(extension_slots_path)
        slot_ids = {item.get("skillId") for item in extension_slots.get("slots", [])}
        if slot_ids != {"content-title", "content-description", "content-thumbnail"}:
            errors.append("content extension registry must reserve exactly title, description, and thumbnail Skills")
        slot_by_id = {item.get("skillId"): item for item in extension_slots.get("slots", [])}
        for slot_id in ("content-title", "content-description"):
            slot = slot_by_id.get(slot_id, {})
            if slot.get("status") != "AVAILABLE" or slot.get("discovered") is not True:
                errors.append(f"{slot_id} must be available after the combined packaging Skill is installed")
            if slot.get("providedBySkillId") != "content-title-description":
                errors.append(f"{slot_id} must be provided by content-title-description")
        thumbnail_slot = slot_by_id.get("content-thumbnail", {})
        if thumbnail_slot.get("status") != "PLANNED_UNAVAILABLE" or thumbnail_slot.get("discovered") is not False:
            errors.append("content-thumbnail must remain PLANNED_UNAVAILABLE")
    except Exception as exc:  # noqa: BLE001
        errors.append(f"content extension registry is invalid: {exc}")

    prompt_manifest_path = PLUGIN_ROOT / "assets" / "content-prompt-bundles.json"
    try:
        prompt_manifest = load_json(prompt_manifest_path)
        expected_sequence = [
            "content-deconstruct",
            "content-rewrite",
            "content-review-edit",
            "content-title-description",
        ]
        if prompt_manifest.get("sequence") != expected_sequence:
            errors.append("content prompt bundle sequence is invalid")
        bundles = prompt_manifest.get("bundles", [])
        if [item.get("skillId") for item in bundles] != expected_sequence:
            errors.append("content prompt bundle Skills do not match the four-stage sequence")
        for item in bundles:
            relative = item.get("bundledPath")
            if not isinstance(relative, str):
                errors.append("content prompt bundle path is missing")
                continue
            prompt_path = PLUGIN_ROOT / relative
            if not prompt_path.is_file():
                errors.append(f"bundled prompt is missing: {relative}")
                continue
            payload = prompt_path.read_bytes()
            if len(payload) != item.get("sizeBytes"):
                errors.append(f"bundled prompt size mismatch: {relative}")
            if hashlib.sha256(payload).hexdigest() != item.get("sha256"):
                errors.append(f"bundled prompt SHA-256 mismatch: {relative}")
            skill_id = item.get("skillId")
            if prompt_path.name not in skill_texts.get(skill_id, ""):
                errors.append(f"{skill_id} does not require its bundled prompt reference")
    except Exception as exc:  # noqa: BLE001
        errors.append(f"content prompt bundle manifest is invalid: {exc}")

    publishing_text = skill_texts.get("publishing-assets", "")
    for marker in (
        "content-title-description",
        "content-title",
        "content-description",
        "content-thumbnail",
        "title-asset-v1",
        "description-asset-v1",
        "thumbnail-asset-v1",
        "PLANNED_UNAVAILABLE",
        "16:9",
        "SHA-256",
        "content_publishing_finalize",
        "content_handoff_check",
        "不在本 Skill 启动工坊",
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
        for tool in EXPECTED_VIDEO_ANALYSIS_TOOLS | EXPECTED_ORIGINAL_IMITATION_TOOLS | EXPECTED_PRODUCTION_TOOLS | EXPECTED_PUBLISH_TOOLS | EXPECTED_DATA_TOOLS
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
