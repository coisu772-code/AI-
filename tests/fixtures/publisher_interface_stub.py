from __future__ import annotations

import json
import sys


request = json.load(sys.stdin)
if request.get("protocolVersion") != "1.0.0" or request.get("operation") != "listChannels":
    raise SystemExit(2)

json.dump(
    {
        "protocolVersion": "1.0.0",
        "requestId": request.get("requestId"),
        "channels": [
            {
                "publisherProfileId": "publisher_fixture_001",
                "channelSerial": "01",
                "youtubeChannelId": "UCFIXTURECHANNEL0001",
                "displayName": "Fixture Channel",
                "enabled": True,
                "authorizationStatus": "AUTHORIZED",
                "defaultLanguage": "ja-JP",
                "privacyStatus": "private",
                "timeZone": "Asia/Tokyo"
            }
        ]
    },
    sys.stdout,
    ensure_ascii=False,
)
