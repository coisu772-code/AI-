# 频道蒸馏契约输入

## `channel_distillation_prepare.references[]`

每项包含：

- `referenceId`：本次分析中的稳定参考频道标识。
- `channelSourcePackageId`：`reference-channel` Source Package。
- `videoSourcePackageIds`：该频道各视频的独立 `youtube-video` Source Package 列表。
- `role`：该频道在并行、比较或融合中的功能角色。
- `weight`：仅融合模式必填；全部频道合计 100。

## 单视频五类结果

`analysisBuckets` 固定包含五个非空数组：

- `originalFacts[]`：`factId`、`statement`、`evidenceRefs[]`。证据项含当前 `sourcePackageId` 和 `locator`。
- `analysisConclusions[]`：`conclusionId`、`statement`、`evidenceFactIds[]`、`confidence`。
- `transferableMethods[]`：`methodId`、`method`、`evidenceConclusionIds[]`、`applicationConditions[]`。
- `prohibitedCopy[]`：`boundaryId`、`description`、`categories[]`。
- `unknowns[]`：`unknownId`、`statement`、未知原因。

`dimensions` 固定覆盖：`storyContent`、`functionalStructure`、`expression`、`openingHook`、`title`、`thumbnail`、`description`、`hashtags`、`videoPresentation`、`visualStyle`、`audienceNeeds`、`psychologicalPayoff`、`retentionHypotheses`、`channelVoice`、`crossAssetAlignment`、`lowQualityPatterns`。

`performanceEvidence.classification` 必须为 `public-fact`，`positiveEvidenceEligible=true`，并用 `qualification` 标明 `historical-hit`、`recent-breakthrough`、`repeat-hit-series` 或 `channel-relative-outlier`，同时在 `evidenceBasis[]` 记录公开指标与频道内比较依据。公开指标不允许出现被推断出来的 CTR、留存、流量来源、展示次数、观看时长或人口后台数据。

## 聚合画像

每个 `profiles[]` 必须有相同的 `referenceId`、完整 `analysisBuckets`、`dimensions`、`audienceProfile`、`corePatterns`、`specialCases` 与 `doNotAmplify`。

聚合 `dimensions` 固定覆盖：`channelScope`、`contentDna`、`expressionDna`、`videoDna`、`packagingDna`、`crossAssetAlignmentDna`、`retentionHypotheses`、`channelVoice`、`commonLogic`、`novelMangaAdaptation`。

每个 `corePatterns[]` 至少含 `patternId` 与两条不同成功样本的 `evidenceSampleIds[]`。`specialCases[]` 可以只有一条样本证据，但不能进入核心规律。

`audienceProfile.populationAndUsageClaims[]` 的 `classification` 只允许 `studio-fact`、`public-inference` 或 `unknown`。Studio 事实必须有 `studioSourceRef`；公开推断必须有 `evidenceSampleIds`。`topicExpansionStrategy.allocation` 固定包含 `coreProven`、`adjacent`、`exploratory`，整数合计 10。

## 账号专属要求

`accountRequirements.decomposition.requiredSections[]` 列出该频道以后每条视频必须深拆的特殊区块。

`accountRequirements.imitation.audienceRewards[]` 列出该频道要稳定交付的观众回报。系统会强制补入允许学习项、必须重建项和禁止项，调用方不能删除这些母规则。

`accountRequirements.validationCases` 同时包含 `decomposition[]` 与 `imitation[]`，各至少 3 条。每条必须有唯一 `caseId` 和非空 `expectedChecks[]`，用于后续 Skill 本地验收，不生成正文。

## 冻结质量门

`qualityGate` 必须通过五类结果分离、反复制、跨资产联动、观众证据边界和目标频道隔离硬项。`coverage.stopDecision` 只允许 `converged`、`insufficient-popular-samples` 或 `complete-audit`；收敛时还要确认主要类型与稳定栏目已覆盖，且最新批次没有重要新规律，否则继续按两条扩展。
