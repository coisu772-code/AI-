# Content Deconstruction Package v1

必须包含：

- `analysisKind: content-deconstruction`；
- `mode: single | parallel | compare`；
- 每个来源的版本与 SHA-256 锁；
- 五类证据结果；
- 全文连续 `sectionMap`；
- 结构、节奏、声音、表达、情绪、回报、可信度和生产适配；
- `downstreamViews.rewrite` 与 `downstreamViews.productionText`；
- `sourceStoryDNA`：观众承诺、剧情发动机、关系发动机、世界／现实规则、主要因果链、情绪曲线、高潮功能和结局回报；
- `expansionSeams`：逐项绑定来源事实的自然扩展缺口；
- 通用三档 `adaptationProfiles`：`close-structure | balanced-reconstruction | free-original`；
- `preservationContract`：`mustPreserve`、`allowedToChange`、`mustRebuild`、`protectedExpressionBoundary`；
- 默认三档各 5 个、共 15 个原创迁移方向；用户明确只看某一档时该档仍为 5 个；
- 每个方向的自由阶段因果骨架、`sourceAnchorRefs`、`expansionSeamIds`、`sourceFidelityEvidence`、`naturalExpansionRationale`、`nonCopyEvidence`、`genericTemplateRisk=false`、推荐状态和独立仿写交接卡；
- 覆盖全部方向的七维 `directionDistinctnessMatrix`；组内和跨组都去重，共享保留项不计重复，表面换皮候选必须重做；
- 完整性和反复制质量门。

`directionPackage` 是冻结迁移方向的唯一机器事实源。高贴合方向至少引用 3 个有效原文事实，中度重构至少 2 个，大胆创新至少 1 个；多来源方向必须覆盖每个已采用来源。任何方向如果只保留抽象主题，却引入没有来源锚点或扩展缺口支持的新中心职业、资产、机构、灾难、公开审判、系统、追放或打脸发动机，必须以 `genericTemplateRisk=true` 拒绝冻结。

完整人读报告与方向卡必须分别保存为 `01_原始素材说明.md`、`02_完整拆解报告.md` 和 `03_迁移方向选择.md`，并登记历史版本与 SHA-256；五类证据桶只保存下游需要的结构化索引。旧包缺少三档字段时可以只读兼容；尚未确认方向的旧包必须重新生成方向卡，已经由用户确认并进入正文的旧包不得被自动改写。`downstreamViews.productionText` 是既有 Analysis Package Schema 的兼容字段名，实际由 `content-review-edit` 消费。短证据摘录只用于定位，不能把整篇来源复制进分析包。
