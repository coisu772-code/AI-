from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PLUGIN_ROOT = ROOT / "plugins" / "ai-video-channel-production"
sys.path.insert(0, str(PLUGIN_ROOT / "mcp"))

from aivcp_tools.publisher import FixturePublisherProvider  # noqa: E402
from aivcp_tools.service import LocalToolService, ServiceConfig  # noqa: E402


def write_fixture(config_root: Path) -> tuple[Path, Path]:
    config_root.mkdir(parents=True, exist_ok=True)
    publisher = config_root / "publisher-fixture.json"
    publisher.write_text(
        json.dumps(
            {
                "fixtureNotice": "synthetic local lifecycle fixture; not a real YouTube channel",
                "channels": [
                    {
                        "publisherProfileId": "publisher_stage8_fixture",
                        "channelSerial": "88",
                        "youtubeChannelId": "UCSYNTHETICSTAGE80001",
                        "displayName": "Stage8 Synthetic Fixture",
                        "enabled": True,
                        "authorizationStatus": "AUTHORIZED",
                        "defaultLanguage": "ja-JP",
                        "privacyStatus": "private",
                        "timeZone": "Asia/Tokyo",
                        "uploadPolicy": "REQUIRE_REVIEW",
                    }
                ],
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    voice = config_root / "voice-catalog.json"
    catalog = {
        "schemaVersion": "1.0.0",
        "catalogId": "stage8-synthetic-voice-catalog",
        "version": "1.0.0",
        "generatedAt": "2026-08-04T00:00:00Z",
        "syntheticFixture": True,
        "engines": [
            {
                "engineId": "fixture-tts",
                "displayName": "Stage8 Fixture TTS",
                "installed": True,
                "voices": [
                    {"voiceId": "fixture-ja-stage8", "displayName": "Fixture Voice", "languages": ["ja-JP"], "recommended": True}
                ],
            }
        ],
    }
    catalog["contentHash"] = hashlib.sha256(
        json.dumps(catalog, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    voice.write_text(json.dumps(catalog, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return publisher, voice


def service(data_root: Path, config_root: Path) -> LocalToolService:
    publisher, voice = write_fixture(config_root)
    return LocalToolService(
        ServiceConfig(data_root=data_root, plugin_root=PLUGIN_ROOT, voice_catalog_path=voice),
        publisher_provider=FixturePublisherProvider(publisher),
    )


def seed(data_root: Path, config_root: Path) -> dict[str, object]:
    local = service(data_root, config_root)
    started = local.call(
        "channel_onboarding_start",
        {"taskId": "stage8-before-backup", "channelSerial": "88", "targetRegion": "Japan", "outputLanguage": "ja-JP"},
    )
    channel_id = started["channel"]["channelProfileId"]
    completed = local.call(
        "channel_onboarding_complete",
        {
            "taskId": "stage8-before-backup",
            "channelProfileId": channel_id,
            "bindingProof": started["taskBinding"]["bindingProof"],
            "defaults": {
                "voice": {"engineId": "fixture-tts", "voiceId": "fixture-ja-stage8"},
                "manuscript": {"mode": "auto_by_topic", "preferredCharacters": 12000, "minCharacters": 8000, "maxCharacters": 16000},
                "episodes": {"mode": "auto_by_topic", "preferredCount": 8, "minCount": 6, "maxCount": 12},
                "deliveryMode": "auto_render",
                "videoGeneration": {"enabled": False, "selectionMode": "none", "fallbackPolicy": "pause"},
                "uploadPolicy": "REQUIRE_REVIEW",
            },
        },
    )
    return {"status": "SEEDED", "channelProfileId": channel_id, "profileHash": completed["channelProfile"]["contentHash"]}


def verify(data_root: Path, config_root: Path) -> dict[str, object]:
    local = service(data_root, config_root)
    channels = local.call("channel_list")["channels"]
    if len(channels) != 1:
        raise RuntimeError(f"expected one restored channel, got {len(channels)}")
    channel_id = channels[0]["channelProfileId"]
    binding = local.call("channel_bind_task", {"taskId": "stage8-after-restore", "channelProfileId": channel_id})
    resolved = local.call(
        "channel_resolve_production",
        {"taskId": "stage8-after-restore", "channelProfileId": channel_id, "bindingProof": binding["bindingProof"]},
    )
    return {
        "status": "RESTORED_AND_REBOUND",
        "channelProfileId": channel_id,
        "bindingProofPresent": bool(binding.get("bindingProof")),
        "productionProfileId": resolved["productionProfile"]["presetId"],
        "crossChannelRead": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("operation", choices=("seed", "verify"))
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--config-root", type=Path, required=True)
    args = parser.parse_args()
    result = seed(args.data_root.resolve(), args.config_root.resolve()) if args.operation == "seed" else verify(args.data_root.resolve(), args.config_root.resolve())
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
