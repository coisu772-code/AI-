# Content Deconstruction Package v1

必须包含：

- `analysisKind: content-deconstruction`；
- `mode: single | parallel | compare`；
- 每个来源的版本与 SHA-256 锁；
- 五类证据结果；
- 全文连续 `sectionMap`；
- 结构、节奏、声音、表达、情绪、回报、可信度和生产适配；
- `downstreamViews.rewrite` 与 `downstreamViews.productionText`；
- 通用三档 `adaptationProfiles`：`close-structure | balanced-reconstruction | free-original`；
- `preservationContract`：`mustPreserve`、`allowedToChange`、`mustRebuild`、`protectedExpressionBoundary`；
- 默认三档各 5 个、共 15 个原创迁移方向；用户明确只看某一档时该档仍为 5 个；
- 每个方向的完整因果骨架、`sourceFidelityEvidence`、`nonCopyEvidence`、推荐状态和独立仿写交接卡；
- 覆盖全部方向的七维 `directionDistinctnessMatrix`；组内和跨组都去重，共享保留项不计重复，表面换皮候选必须重做；
- 完整性和反复制质量门。

完整人读报告与方向卡必须分别保存为 `01_原始素材说明.md`、`02_完整拆解报告.md` 和 `03_迁移方向选择.md`，并登记历史版本与 SHA-256；五类证据桶只保存下游需要的结构化索引。旧包缺少三档字段时可以只读兼容；尚未确认方向的旧包必须重新生成方向卡，已经由用户确认并进入正文的旧包不得被自动改写。`downstreamViews.productionText` 是既有 Analysis Package Schema 的兼容字段名，实际由 `content-review-edit` 消费。短证据摘录只用于定位，不能把整篇来源复制进分析包。
