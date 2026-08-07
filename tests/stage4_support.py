from __future__ import annotations

import binascii
import hashlib
import json
import shutil
import struct
import zlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class StaticPublisherProvider:
    def __init__(self, language: str, market_key: str):
        self.language = language
        self.market_key = market_key

    def capabilities(self) -> dict[str, Any]:
        return {"available": True, "protocolVersion": "1.0.0", "transport": "synthetic-fixture", "testOnly": True}

    def list_channels(self) -> list[dict[str, Any]]:
        return [
            {
                "publisherProfileId": f"publisher_synthetic_{self.market_key}",
                "channelSerial": "01",
                "youtubeChannelId": f"UCSYNTHETIC{self.market_key.upper()}0001",
                "displayName": f"Synthetic {self.market_key} Channel",
                "enabled": True,
                "authorizationStatus": "AUTHORIZED",
                "defaultLanguage": self.language,
                "privacyStatus": "private",
                "timeZone": "UTC",
                "uploadPolicy": "REQUIRE_REVIEW",
            }
        ]


MARKETS = {
    "ja-JP": {
        "key": "jp",
        "region": "Japan",
        "source": "これはオンラインデータではない合成資料です。閉館予定の町の図書室を、若い司書と住民が記憶の朗読会で守る物語のための短い素材です。事実、推測、未知を分けて検証します。",
        "target": [
            "町の図書室には、閉館を知らせる紙が一枚だけ貼られていた。",
            "司書の美咲は、失われる前に住民の記憶を集めようと決めた。",
            "最初の朗読会で、誰も知らなかった寄贈台帳の手掛かりが見つかった。",
            "台帳は図書室を守る証拠となり、町は新しい共同運営を選んだ。",
        ],
        "audit": [
            "镇图书室只贴着一张即将闭馆的通知。",
            "图书管理员美咲决定在一切消失前收集居民的记忆。",
            "第一次朗读会上，大家发现了无人知晓的捐赠登记线索。",
            "登记册成为保住图书室的证据，小镇选择共同运营。",
        ],
        "title": "閉館寸前の図書室で、町の記憶が未来を変えた",
        "titleZh": "濒临闭馆的图书室里，小镇记忆改变了未来",
        "description": "閉館まで残り七日。若い司書が集めた町の記憶は、最後に図書室を救う証拠へ変わります。\n静かな再出発と共同体の選択を描く合成フィクションです。",
        "hashtags": ["#物語", "#朗読", "#創作", "#図書室", "#再出発", "#町", "#人間ドラマ", "#合成データ"],
        "coverText": "記憶が未来を救う",
    },
    "zh-CN": {
        "key": "cn",
        "region": "China",
        "source": "这是明确标注为非线上数据的合成素材。社区修理铺面临停业，一名年轻钟表匠与邻居共同整理旧物记录，并从中找到让公共服务延续的新办法。所有事实、推断和未知均单独记录。",
        "target": [
            "社区修理铺门口贴出了停业通知，屋里的旧钟仍在走动。",
            "钟表匠林夏决定整理每件旧物背后的维修记录。",
            "邻居们带着故事回来，也找到了被遗漏的公共服务协议。",
            "协议通过核验，修理铺改为社区共管，并重新亮起灯牌。",
        ],
        "audit": None,
        "title": "修理铺停业前七天，她从旧钟里找回了社区的未来",
        "titleZh": "修理铺停业前七天，她从旧钟里找回了社区的未来",
        "description": "只剩七天，社区修理铺就要关门。她整理的每一份旧记录，最终拼出了被遗忘的公共承诺。\n这是关于边界、互助与重新开始的合成故事。",
        "hashtags": ["#故事", "#有声故事", "#原创", "#社区", "#逆转", "#重新开始", "#情感故事", "#合成数据"],
        "coverText": "旧钟藏着未来",
    },
    "en-US": {
        "key": "us",
        "region": "United States",
        "source": "This is synthetic material, not online or user data. A neighborhood radio host facing a final broadcast invites residents to record practical memories, revealing a forgotten community agreement that makes a cooperative future possible.",
        "target": [
            "The neighborhood station posted its final broadcast date on a quiet Monday morning.",
            "Host Maya asked residents to record the small memories the city had overlooked.",
            "One recording revealed a forgotten agreement that protected the studio for public use.",
            "After the agreement was verified, the station reopened as a community cooperative.",
        ],
        "audit": [
            "社区电台在一个安静的周一早晨公布了最后播出日期。",
            "主持人玛雅邀请居民录下这座城市忽略的小小记忆。",
            "一段录音揭示了保障演播室公共用途的遗忘协议。",
            "协议核验后，电台以社区合作社的形式重新开放。",
        ],
        "title": "Seven Days Before the Station Closed, One Recording Changed Its Future",
        "titleZh": "电台关闭前七天，一段录音改变了它的未来",
        "description": "The station has seven days left. One forgotten recording turns a farewell broadcast into a path forward.\nA synthetic story about memory, proof, and a community choosing to rebuild.",
        "hashtags": ["#Storytime", "#AudioStory", "#OriginalFiction", "#Community", "#SecondChance", "#PlotTwist", "#HumanDrama", "#SyntheticData"],
        "coverText": "ONE RECORDING SAVED IT",
    },
}


def write_png(path: Path, width: int, height: int, *, label: str = "SYNTHETIC STAGE4 FIXTURE") -> None:
    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", binascii.crc32(kind + data) & 0xFFFFFFFF)

    row = b"\x00" + (b"\x44\x66\xaa" * width)
    payload = b"\x89PNG\r\n\x1a\n"
    payload += chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
    payload += chunk(b"tEXt", b"Comment\x00" + label.encode("latin-1"))
    payload += chunk(b"IDAT", zlib.compress(row * height, 9))
    payload += chunk(b"IEND", b"")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)


@dataclass
class PipelineContext:
    service: Any
    root: Path
    task_id: str
    channel_id: str
    proof: str
    project_id: str
    source: dict[str, Any]
    market: dict[str, Any]


def create_service(root: Path, language: str, *, plugin_root: Path, local_tool_service: Any, service_config: Any) -> tuple[Any, str, str, str]:
    market = MARKETS[language]
    root.mkdir(parents=True, exist_ok=True)
    voice_catalog = root / "voice-catalog.json"
    catalog = {
                "schemaVersion": "1.0.0",
                "catalogId": f"synthetic-{market['key']}-voice-catalog",
                "version": "1.0.0",
                "generatedAt": "2026-08-04T00:00:00Z",
                "syntheticFixture": True,
                "engines": [
                    {
                        "engineId": "fixture-tts",
                        "displayName": "Synthetic Fixture TTS",
                        "installed": True,
                        "voices": [
                            {
                                "voiceId": f"fixture-{market['key']}-001",
                                "displayName": f"Synthetic {language} Voice",
                                "languages": [language],
                                "recommended": True,
                            }
                        ],
                    }
                ],
            }
    catalog["contentHash"] = hashlib.sha256(
        json.dumps(catalog, ensure_ascii=False, allow_nan=False, separators=(",", ":"), sort_keys=True).encode("utf-8")
    ).hexdigest()
    voice_catalog.write_text(json.dumps(catalog, ensure_ascii=False), encoding="utf-8")
    service = local_tool_service(
        service_config(data_root=root / "data", plugin_root=plugin_root, voice_catalog_path=voice_catalog),
        publisher_provider=StaticPublisherProvider(language, market["key"]),
    )
    task_id = f"task-stage4-{market['key']}"
    started = service.call(
        "channel_onboarding_start",
        {"taskId": task_id, "channelSerial": "01", "targetRegion": market["region"], "outputLanguage": language},
    )
    channel_id = started["channel"]["channelProfileId"]
    proof = started["taskBinding"]["bindingProof"]
    service.call(
        "channel_onboarding_complete",
        {
            "taskId": task_id,
            "channelProfileId": channel_id,
            "bindingProof": proof,
            "defaults": {
                "voice": {"engineId": "fixture-tts", "voiceId": f"fixture-{market['key']}-001"},
                "manuscript": {"mode": "auto_by_topic", "preferredCharacters": 200, "minCharacters": 20, "maxCharacters": 1000},
                "episodes": {"mode": "auto_by_topic", "preferredCount": 2, "minCount": 1, "maxCount": 4},
                "deliveryMode": "auto_render",
                "videoGeneration": {"enabled": False, "selectionMode": "none", "fallbackPolicy": "pause"},
                "uploadPolicy": "REQUIRE_REVIEW",
            },
        },
    )
    return service, task_id, channel_id, proof


def start_topic_context(root: Path, language: str, *, plugin_root: Path, local_tool_service: Any, service_config: Any) -> PipelineContext:
    service, task_id, channel_id, proof = create_service(
        root, language, plugin_root=plugin_root, local_tool_service=local_tool_service, service_config=service_config
    )
    market = MARKETS[language]
    prepared = service.call(
        "source_add_prepare",
        {
            "taskId": task_id,
            "channelProfileId": channel_id,
            "bindingProof": proof,
            "inputs": [{"text": market["source"], "title": "Synthetic Stage4 Source", "language": language}],
        },
    )
    service.call(
        "source_add_confirm",
        {
            "taskId": task_id,
            "channelProfileId": channel_id,
            "bindingProof": proof,
            "acquisitionJobId": prepared["acquisitionJobId"],
            "planHash": prepared["planHash"],
            "confirmation": {"confirmed": True, "choice": "confirm", "syntheticFixture": True},
        },
    )
    source = service.call("source_search", {"channelProfileId": channel_id, "limit": 10})["sources"][0]
    project_id = f"synthetic-{market['key']}-content-loop"
    service.call(
        "content_project_start",
        {
            "taskId": task_id,
            "channelProfileId": channel_id,
            "bindingProof": proof,
            "projectId": project_id,
            "sourceMode": "market-original",
            "sourcePackages": [{"sourcePackageId": source["source_package_id"]}],
            "learningSnapshot": {"mode": "read_only"},
            "oneTimeModifications": ["仅本合成项目使用简短两集结构。"],
        },
    )
    return PipelineContext(service, root, task_id, channel_id, proof, project_id, source, market)


def candidate(ctx: PipelineContext, number: int) -> dict[str, Any]:
    detail = ctx.service.call(
        "source_get", {"channelProfileId": ctx.channel_id, "sourcePackageId": ctx.source["source_package_id"]}
    )
    manifest = detail["manifest"]
    reference = {
        "sourcePackageId": manifest["sourcePackageId"],
        "version": manifest["version"],
        "contentHash": manifest["contentHash"],
        "locator": manifest["provenance"]["locator"],
    }
    target_characters = sum(len(text) for text in ctx.market["target"])
    suffix = f" Candidate {number} uses a distinct driver, relationship, climax, and ending for synthetic validation."
    return {
        "candidateId": f"candidate-{number:02d}",
        "audience": {
            "region": ctx.market["region"],
            "targetLanguage": next(key for key, value in MARKETS.items() if value is ctx.market),
            "locale": next(key for key, value in MARKETS.items() if value is ctx.market),
            "commercialOrientation": "general",
        },
        "evidenceClaims": [
            {"claimId": f"fact-{number:02d}", "classification": "fact", "statement": "The supplied material is explicitly synthetic.", "confidence": 1.0, "sourceRefs": [reference]},
            {"claimId": f"inference-{number:02d}", "classification": "inference", "statement": "A community-rebuilding promise can support this candidate.", "confidence": 0.7, "sourceRefs": [reference]},
            {"claimId": f"unknown-{number:02d}", "classification": "unknown", "statement": "No online audience retention data is available.", "sourceRefs": []},
        ],
        "storyDriver": f"driver-{number}: community evidence and a different relationship path",
        "coreSellingPoints": ["A visible deadline", "A verified nonviolent reversal"],
        "worldRules": ["Only verified records can change the public decision"],
        "storyFacts": {
            "lockedFacts": [
                {"factId": f"story-fact-{number:02d}-a", "statement": "The threatened place serves the community", "evidenceClaimIds": [f"fact-{number:02d}"]},
                {"factId": f"story-fact-{number:02d}-b", "statement": "The protagonist preserves local memories", "evidenceClaimIds": [f"inference-{number:02d}"]},
            ],
            "worldRules": ["A public decision changes only after evidence is verified"],
            "relationships": ["The protagonist and residents move from distance to cooperation"],
            "climax": "The forgotten agreement is publicly verified.",
            "ending": "The place reopens under community stewardship.",
        },
        "characters": [
            {"characterId": "protagonist", "name": "Maya", "role": "community archivist", "goal": "preserve the shared place", "relationshipFunction": "connects residents"}
        ],
        "completeOutline": {
            "opening": "A public notice creates a seven-day deadline and a concrete loss." + suffix,
            "development": "Residents contribute memories while the protagonist separates verified records from assumptions." + suffix,
            "climax": "A forgotten agreement is authenticated in public and changes the available decision." + suffix,
            "ending": "The community chooses a cooperative future and the protagonist gains a durable role." + suffix,
        },
        "episodePlots": [
            {"episodeNumber": 1, "startState": "closure announced", "progress": "memories collected", "audienceReward": "a document clue", "endState": "verification becomes possible"},
            {"episodeNumber": 2, "startState": "document unverified", "progress": "agreement authenticated", "audienceReward": "earned reversal", "endState": "cooperative reopening"},
        ],
        "productionRecommendation": {
            "targetCharacters": target_characters if number == 1 else target_characters + number,
            "estimatedDurationSeconds": 60 + number,
            "episodeCount": 2,
            "reason": "Short synthetic fixture with two complete state changes.",
        },
        "scores": {
            "audienceFit": 9.0 - number / 10,
            "clickPotential": 8.8 - number / 10,
            "storySustainability": 8.7 - number / 10,
            "visualPotential": 8.6 - number / 10,
            "originality": 8.9 - number / 10,
            "productionFeasibility": 9.2 - number / 10,
            "overall": 9.0 - number / 10,
        },
        "strengths": ["Clear promise and complete ending"],
        "risks": ["Synthetic brevity limits nuance"],
        "packagingBrief": {
            "titleInformationDirection": "deadline plus evidence-backed reversal",
            "thumbnailVisualTask": "one protagonist, threatened place, visible record",
            "videoPresentationDirection": "two compact episodes with static-image production compatibility",
        },
    }


def finalize_topic(ctx: PipelineContext, *, confirmed: bool = True) -> dict[str, Any]:
    for number in range(1, 4):
        ctx.service.call(
            "content_topic_checkpoint",
            {
                "taskId": ctx.task_id,
                "channelProfileId": ctx.channel_id,
                "bindingProof": ctx.proof,
                "projectId": ctx.project_id,
                "candidateNumber": number,
                "candidate": candidate(ctx, number),
            },
        )
    return ctx.service.call(
        "content_topic_finalize",
        {
            "taskId": ctx.task_id,
            "channelProfileId": ctx.channel_id,
            "bindingProof": ctx.proof,
            "projectId": ctx.project_id,
            "ranking": ["candidate-01", "candidate-02", "candidate-03"],
            "selectedCandidateId": "candidate-01",
            "selectionReasons": {
                "candidate-01": "Highest complete score and selected.",
                "candidate-02": "Traceable backup with a lower audience score.",
                "candidate-03": "Retained but not selected due to lower feasibility.",
            },
            "confirmation": {"confirmed": confirmed, "mode": "review", "confirmedBy": "synthetic-fixture-user", "confirmedAt": "2026-08-04T01:00:00Z"},
        },
    )


def manuscript_payload(ctx: PipelineContext) -> dict[str, Any]:
    state = ctx.service.call("content_project_get", {"channelProfileId": ctx.channel_id, "projectId": ctx.project_id})["state"]
    topic = json.loads(Path(state["activePackages"]["topic"]["path"]).read_text(encoding="utf-8"))
    language = topic["audience"]["targetLanguage"]
    target_lines = []
    for index, text in enumerate(ctx.market["target"], 1):
        episode = 1 if index <= 2 else 2
        target_lines.append(
            {
                "lineId": f"E{episode:02d}-L{(index - 1) % 2 + 1:03d}",
                "episodeNumber": episode,
                "sequence": (index - 1) % 2 + 1,
                "speakerId": "narrator" if index % 2 else "protagonist",
                "lineType": "narration" if index % 2 else "dialogue",
                "emotion": "calm" if index < 4 else "hopeful",
                "text": text,
            }
        )
    audit_lines = None
    if not language.startswith("zh"):
        audit_lines = [{**line, "text": ctx.market["audit"][index]} for index, line in enumerate(target_lines)]
    checks = {
        "locked-facts": True,
        "story-progress": True,
        "character-voice": True,
        "target-language-naturalness": True,
        "regional-expression": True,
        "terminology-consistency": True,
        "tts-semantic-lines": True,
        "audience-reward": True,
    }
    catalog = json.loads((ctx.root / "voice-catalog.json").read_text(encoding="utf-8"))
    catalog_hash = catalog["contentHash"]
    characters = []
    for character_id, name, role in (("narrator", "Narrator", "narration"), ("protagonist", "Maya", "protagonist")):
        characters.append(
            {
                "characterId": character_id,
                "targetLanguageName": name,
                "role": role,
                "goal": "guide the community story",
                "relationship": "connects the audience to the community",
                "speakingStyle": "clear, warm, and concise",
                "visualConsistencyRequired": character_id == "protagonist",
                **({"visualAnchorPromptZh": "单人，年轻社区记录者，深色短发，温暖坚定的眼神，简洁日常服装"} if character_id == "protagonist" else {}),
                "voice": {
                    "engineId": "fixture-tts",
                    "voiceId": f"fixture-{ctx.market['key']}-001",
                    "voiceName": f"Synthetic {language} Voice",
                    "catalogVersion": "1.0.0",
                    "catalogHash": catalog_hash,
                },
            }
        )
    return {
        "storyBible": {
            "sourceStoryFactsHash": topic["storyFactsHash"],
            "lockedFacts": [item["statement"] for item in topic["storyFacts"]["lockedFacts"]],
            "worldRules": topic["storyFacts"]["worldRules"],
            "relationships": topic["storyFacts"]["relationships"],
            "timeline": ["closure notice", "memory collection", "verification", "reopening"],
            "foreshadowing": ["The first record hints at a forgotten agreement"],
            "climax": topic["storyFacts"]["climax"],
            "ending": topic["storyFacts"]["ending"],
        },
        "characters": characters,
        "targetScript": target_lines,
        "chineseAuditScript": audit_lines,
        "qualityGate": {
            "passed": True,
            "episodes": [
                {"episode": 1, "passed": True, "revisionCount": 0, "checks": checks},
                {"episode": 2, "passed": True, "revisionCount": 1, "checks": checks},
            ],
        },
        "rewriteDraftText": "\n".join(f"初稿 {line['lineId']} {line['speakerId']}：{line['text']}" for line in target_lines),
        "editorialReviewMarkdown": (
            "# 编辑审核报告\n\n本合成稿已逐集检查事实、结构、人物、因果、情绪、节奏、语言和目标市场适配。"
            "未发现 P0 阻断项；P1 项为补强证据取得过程和结尾回报，已在正式稿中完成定向修复并复查通过。"
        ),
        "revisionLogMarkdown": (
            "# 修改记录与前后对照\n\n## 修改 1\n位置：第二集。\n修改前：证据出现较快。\n"
            "修改后：补充记录核验及居民参与。\n修改原因：修复因果跳跃。\n影响：结局回报由人物行动自然产生，未改变锁定结局。"
        ),
        "confirmation": {"confirmed": True, "mode": "review", "confirmedBy": "synthetic-fixture-user", "confirmedAt": "2026-08-04T02:00:00Z"},
    }


def finalize_manuscript(ctx: PipelineContext, *, mutate_audit: bool = False) -> dict[str, Any]:
    payload = manuscript_payload(ctx)
    for document_type, payload_key in (
        ("rewrite-draft-target", "rewriteDraftText"),
        ("editorial-review", "editorialReviewMarkdown"),
        ("revision-log", "revisionLogMarkdown"),
    ):
        ctx.service.call(
            "content_review_document_save",
            {
                "taskId": ctx.task_id,
                "channelProfileId": ctx.channel_id,
                "bindingProof": ctx.proof,
                "projectId": ctx.project_id,
                "documentType": document_type,
                "content": payload.pop(payload_key),
            },
        )
    if mutate_audit and payload["chineseAuditScript"]:
        payload["chineseAuditScript"][0]["speakerId"] = "wrong-speaker"
    return ctx.service.call(
        "content_manuscript_finalize",
        {
            "taskId": ctx.task_id,
            "channelProfileId": ctx.channel_id,
            "bindingProof": ctx.proof,
            "projectId": ctx.project_id,
            **payload,
            "authoringMode": "target-language-native",
        },
    )


def publishing_payload(ctx: PipelineContext, thumbnail_path: Path, *, hashtags: list[str] | None = None) -> dict[str, Any]:
    candidates = [
        {
            "candidateId": f"cover-{index:02d}",
            "prompt": f"Synthetic 16:9 commercial thumbnail direction {index}; do not treat as online data.",
            "renderStatus": "PROMPT_ONLY",
            "visualDifference": f"Distinct composition {index}",
            "score": 9.1 - index / 10,
            "textAccurate": True,
            "factsConsistent": True,
            "mobileReadable": True,
        }
        for index in range(1, 6)
    ]
    official_hashtags = hashtags or ctx.market["hashtags"]
    title_candidates = [
        {
            "titleId": f"title-{index:02d}",
            "text": ctx.market["title"] if index == 1 else f"{ctx.market['title']} · {index}",
            "zhTranslation": ctx.market["titleZh"] if index == 1 else f"{ctx.market['titleZh']}·候选{index}",
            "audienceFit": 9.2 - index / 10,
            "factBasis": "Synthetic candidate promise is supported by the frozen manuscript.",
            "promiseFulfilled": True,
            "sampleWordingCopied": False,
        }
        for index in range(1, 7)
    ]
    return {
        "title": ctx.market["title"],
        "titleChinese": ctx.market["titleZh"],
        "titleCandidates": title_candidates,
        "descriptionBody": ctx.market["description"],
        "descriptionChinese": ctx.market["description"] if ctx.market["key"] == "cn" else "这是对应目标语言简介的完整中文审核翻译，仅供用户检查，不进入发布字段。故事围绕期限、证据与社区重新开始展开。",
        "hashtags": official_hashtags,
        "hashtagTranslations": [
            {"hashtag": hashtag, "chinese": f"合成测试标签含义 {index}"}
            for index, hashtag in enumerate(official_hashtags, 1)
        ],
        "thumbnailProvider": {"providerId": "synthetic-png-fixture", "interfaceVersion": "1.0.0", "integrationMode": "fixture", "status": "available"},
        "thumbnailStrategy": {
            "subject": "one community protagonist",
            "conflict": "a shared place faces closure",
            "composition": "protagonist foreground, threatened place and record behind",
            "expression": "determined hope",
            "targetLanguageText": ctx.market["coverText"],
            "textSafeArea": "right third with 8 percent margin",
            "mobileReadabilityTarget": "legible at 160 pixels wide",
        },
        "thumbnailCandidates": candidates,
        "selectedThumbnailId": "cover-01",
        "thumbnail": {"mode": "real", "sourcePath": str(thumbnail_path)},
        "thumbnailTextChinese": ctx.market["coverText"] if ctx.market["key"] == "cn" else "封面短文案的中文审核含义",
        "ctrReview": {
            "status": "PASSED",
            "score": 9.0,
            "titleHookVisualized": True,
            "textComplementsTitle": True,
            "mobileReadable": True,
            "factsConsistent": True,
            "conclusion": "The selected synthetic fixture visualizes the verified story promise.",
        },
        "confirmation": {"confirmed": True, "mode": "review", "confirmedBy": "synthetic-fixture-user", "confirmedAt": "2026-08-04T03:00:00Z"},
    }


def finalize_publishing(ctx: PipelineContext, thumbnail_path: Path, **overrides: Any) -> dict[str, Any]:
    payload = publishing_payload(ctx, thumbnail_path)
    payload.update(overrides)
    return ctx.service.call(
        "content_publishing_finalize",
        {
            "taskId": ctx.task_id,
            "channelProfileId": ctx.channel_id,
            "bindingProof": ctx.proof,
            "projectId": ctx.project_id,
            **payload,
        },
    )


def build_complete_pipeline(ctx: PipelineContext, thumbnail_path: Path) -> dict[str, Any]:
    topic = finalize_topic(ctx)
    manuscript = finalize_manuscript(ctx)
    publishing = finalize_publishing(ctx, thumbnail_path)
    integrity = ctx.service.call("content_integrity_check", {"channelProfileId": ctx.channel_id, "projectId": ctx.project_id})
    handoff = ctx.service.call("content_handoff_check", {"channelProfileId": ctx.channel_id, "projectId": ctx.project_id})
    return {"topic": topic, "manuscript": manuscript, "publishing": publishing, "integrity": integrity, "handoff": handoff}


def export_packages(result: dict[str, Any], destination: Path, *, language: str) -> dict[str, Any]:
    if destination.exists():
        shutil.rmtree(destination)
    destination.mkdir(parents=True)
    paths = {}
    for key in ("topic", "manuscript", "publishing"):
        source = Path(result[key]["packagePath"])
        target = destination / source.parent.name
        shutil.copytree(source, target)
        paths[key] = target.name
    validation = {
        "syntheticFixture": True,
        "onlineData": False,
        "userData": False,
        "language": language,
        "integrity": result["integrity"],
        "handoff": result["handoff"],
        "packagePaths": paths,
    }
    (destination / "validation.json").write_text(json.dumps(validation, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return validation
