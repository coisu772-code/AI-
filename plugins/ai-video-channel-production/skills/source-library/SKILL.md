---
name: source-library
description: Manage the bound channel's local Source Library. Use when the user asks to add, download, import, update, find, inspect, cancel, resume, or retry source materials, including YouTube channels or videos, supported novel pages, TXT, MD, EPUB, PDF, DOCX, pasted text, or batches of links. Also use before later video/book deconstruction when the requested material is not yet CONTENT_READY. This skill only acquires and indexes sources; it never analyzes, imitates, recommends topics, writes content, runs the workshop, or uploads videos.
---

# Source Library

Use the installed local MCP tools for every file, network, hash, database, and task-state action. Keep one task bound to one `channelProfileId` and include its current `bindingProof` in every write.

## Route the request

Map natural language directly:

- “把这个频道加入资料库” → reference-channel default plan.
- “下载这个视频文案” → youtube-video default plan.
- “下载/收录这本小说” → novel-web plan within the site's declared capability.
- “导入这些文件/文字” → local-file or pasted-text plan.
- “把这些链接存下来” → one batch whose items succeed or fail independently.
- “更新上次的资料” → `source_update_prepare` for the selected package.
- “继续失败的任务” → list or read the current channel's recoverable job, then `source_job_resume`.
- “拆这个视频/这本书” → first require a matching `CONTENT_READY` package. Stop after acquisition in this Skill; a later pluggable Skill performs analysis.

If the channel is not bound, return to `channel-production` or `channel-onboarding`. Never guess a target channel from language, content, or a reference-channel ID.

## Add or update material

1. Read `source_library_capabilities` when format or site support is uncertain.
2. Call `source_add_prepare` (or `source_update_prepare`) with the current binding and inputs.
3. Show the returned confirmation card without replacing unknown estimates with invented values. Keep these fields visible: destination channel, recognized sources, collection scope, saved assets, automatic fallback, work explicitly not performed, and estimated workload.
4. Wait for an explicit “确认入库”. Do not treat “continue”, a progress question, or an earlier production authorization as acquisition confirmation.
5. Call `source_add_confirm` with the unchanged job ID, `planHash`, and explicit confirmation.
6. Show the completion card: added, updated, reused, partial, failed, completeness, and appropriate next actions. Do not automatically take a next action.

Use the default scope unless the user changes it:

- YouTube channel: create the broad lightweight list; acquire heavy assets only for explicitly selected items.
- YouTube video: metadata, public Hashtags, thumbnail, public metrics snapshot, and usable transcript; do not save the full video.
- Novel page: metadata and chapter directory, plus text only when the capability and rights boundary allow it.
- Local document: retain the original and create normalized text with encoding and chapter/page/paragraph completeness.

## Progress, cancellation, and recovery

- Use `source_job_get` for progress. Treat it as read-only; never change or close a running job because the user asked for status.
- Use `source_job_cancel` only when the user asks to cancel. Preserve packages already completed.
- Use `source_job_resume` with only the missing supplement or retry. Do not reacquire completed items.
- When a user supplies a subtitle, media file, document, or pasted text for a blocked item, attach it to that `itemIndex` as a supplement and resume from the checkpoint.
- Use `source_integrity_check` when persistence, hashes, or missing files are in doubt.

## Evidence and access boundaries

- Prefer manual subtitles, then automatic subtitles, then configured temporary-audio local transcription.
- If none yields enough text, keep verified metadata, mark the package `BLOCKED`, and request a local video, audio, subtitle, document, or transcript. Never infer body text from a title, thumbnail, description, comments, or chapter list.
- Respect each versioned site capability. Never bypass login, paywalls, DRM, CAPTCHA, robots/access restrictions, or rate limits.
- Treat commercial sites as metadata/directory plus user-authorized import unless the active capability explicitly permits public text acquisition.
- Preserve public metrics as public facts only. Do not label them CTR, retention, traffic source, demographics, or Studio facts.
- Record unknown fields as unknown, not empty invented facts.

## Storage and version rules

- Reuse an existing package for the same platform ID, canonical URL, or content SHA-256.
- Add an alias when the same content arrives under a different filename or locator; do not create a second stored copy.
- Create a new package version only when the source actually changed. Never overwrite a version already referenced by another task.
- Keep original, normalized, asset, report, and version files separate. Analysis outputs never belong inside the Source Package.
- Use `source_search` and `source_get` for indexed retrieval; do not scan unrelated channels or production queues.

This Skill ends after a persistent, valid Source Package and completion card. Return to `$channel-production` for a separate content step; do not start analysis or generation inside Source Library.
