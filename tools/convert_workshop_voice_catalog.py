from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


TARGET_SCHEMA_VERSION = "1.0.0"
SUPPORTED_ENGINES = (
    "voicevox_external",
    "fish_audio",
    "seed_audio",
    "kokoro",
    "edge_tts",
)
ENGINE_POLICIES = (
    {
        "engineId": "seed_audio",
        "displayName": "Seed Audio API",
        "catalogMode": "provider_default_or_explicit_voice_id",
        "selectableFromCatalog": False,
        "reasonCode": "PROVIDER_HAS_NO_PUBLIC_VOICE_LIST",
    },
)
PRE_SCANNED_PUBLIC_API_ENGINES = {"fish_audio"}


def _text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def convert_catalog(source: dict[str, Any]) -> dict[str, Any]:
    """Convert the workshop's credential-free catalog into the plugin contract.

    Only fields consumed by ``system_voice_catalog`` are copied.  In particular,
    endpoints, model settings, paths, credentials and probe results never enter
    the distributable catalog.
    """

    engines_by_id = {
        _text(engine.get("engine")): engine
        for engine in source.get("engines", [])
        if isinstance(engine, dict) and _text(engine.get("engine"))
    }
    converted_engines: list[dict[str, Any]] = []
    for engine_id in SUPPORTED_ENGINES:
        engine = engines_by_id.get(engine_id)
        if not engine:
            continue
        if not bool(engine.get("configured")) and engine_id not in PRE_SCANNED_PUBLIC_API_ENGINES:
            continue
        converted_voices: list[dict[str, Any]] = []
        seen_voice_ids: set[str] = set()
        for voice in engine.get("voices", []):
            if not isinstance(voice, dict):
                continue
            voice_id = _text(voice.get("id"))
            if not voice_id or voice_id in seen_voice_ids:
                continue
            seen_voice_ids.add(voice_id)
            converted: dict[str, Any] = {"voiceId": voice_id}
            display_name = _text(voice.get("name"))
            if display_name:
                converted["displayName"] = display_name
            languages = [
                language.strip()
                for language in voice.get("languages", [])
                if isinstance(language, str) and language.strip()
            ]
            if languages:
                converted["languages"] = languages
            gender_style = _text(voice.get("gender"))
            if gender_style:
                converted["genderStyle"] = gender_style
            if "autoMatchingEligible" in voice:
                converted["recommended"] = bool(voice.get("autoMatchingEligible"))
            converted_voices.append(converted)
        if not converted_voices:
            raise ValueError(f"configured engine has no usable voices: {engine_id}")
        converted_engines.append(
            {
                "engineId": engine_id,
                "displayName": _text(engine.get("name")) or engine_id,
                "installed": True,
                "voices": converted_voices,
            }
        )
    if not converted_engines:
        raise ValueError("source catalog has no supported engines with usable voices")
    catalogued_engine_ids = {engine["engineId"] for engine in converted_engines}
    return {
        "schemaVersion": TARGET_SCHEMA_VERSION,
        "generatedAt": source.get("generatedAt"),
        "engines": converted_engines,
        "enginePolicies": [
            policy for policy in ENGINE_POLICIES if policy["engineId"] not in catalogued_engine_ids
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Convert a Z Manga Workshop voice catalog into the AIVCP v1 catalog."
    )
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()

    source = json.loads(args.source.read_text(encoding="utf-8-sig"))
    converted = convert_catalog(source)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(converted, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
