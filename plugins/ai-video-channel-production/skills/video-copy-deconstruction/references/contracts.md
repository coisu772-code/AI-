# 视频文案拆解契约

## 准备

`video_deconstruction_prepare`：

- `deconstructionId`：本次拆解稳定 ID。
- `mode`：`single|parallel|compare`。
- `videos[]`：每项含 `sourcePackageId` 和可选 `role`。
- `distillationId`：可选；必须属于同一目标频道且已冻结。

返回的 plan 锁定 Source Package 引用、`content.txt`、可选 `timing-map.json`、账号专属要求引用、要求哈希和 `requiredSections`。

## 五类结果

- `originalFacts[]`：`factId`、`statement`、`evidenceRefs[]`。
- `analysisConclusions[]`：`conclusionId`、`statement`、`evidenceFactIds[]`、`confidence`。
- `transferableMethods[]`：`methodId`、`method`、`evidenceConclusionIds[]`、`applicationConditions[]`、`downstreamConsumers[]`。消费者只允许 `topic-center`、`manuscript-center`。
- `prohibitedCopy[]`：`boundaryId`、`description`、`categories[]`。
- `unknowns[]`：`unknownId`、`statement` 和未知原因。

## 功能区段

`sectionMap[]` 每项包含：

- `sectionId`
- `startParagraphId`、`endParagraphId`
- 有时间映射时的 `startSeconds`、`endSeconds`
- `functions[]`
- `audienceExpectation`
- `progress`
- `audienceReward`
- `emotionBefore`、`emotionAfter`
- `evidenceFactIds[]`

区段从 `p0001` 起按段落严格递增，连续覆盖完整正文，不重叠、不留空，每项引用当前视频事实。多段正文至少两个区段；只有一个规范段落的极短正文允许一个完整区段。

`compare` 模式的 `sharedFunctions[]` 还要提供 `statement` 与至少两个成功视频的 `evidenceSourcePackageIds[]`；`videoDifferences[]` 必须逐条覆盖每个成功视频。

## 账号要求覆盖

绑定频道蒸馏时，`requirementCoverage[]` 与冻结 `requiredSections[]` 一一对应：`requirement` 文本相同、`status=COVERED`、`evidenceRefs[]` 非空、`observation` 非空。没有绑定时该数组必须为空。

## 输出

逐视频输出为 `video-deconstruction-analysis-v1`。最终输出为 `analysis-package-v1`，且 `analysisKind=video-copy-deconstruction`，包含：

- `deconstructionId`
- 可选来源 `distillationId`
- `videoAnalyses[]`
- `failedVideos[]`
- `comparison`
- `analysisBuckets`
- `downstreamViews.topicCenter`
- `downstreamViews.manuscriptCenter`
- `qualityGate`

最终质量门必须通过：逐视频独立、五类分离、证据可追溯、账号要求覆盖、下游交接、反复制边界和时间映射完整性。
