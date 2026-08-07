# Content Deconstruction Package v1

必须包含：

- `analysisKind: content-deconstruction`；
- `mode: single | parallel | compare`；
- 每个来源的版本与 SHA-256 锁；
- 五类证据结果；
- 全文连续 `sectionMap`；
- 结构、节奏、声音、表达、情绪、回报、可信度和生产适配；
- `downstreamViews.rewrite` 与 `downstreamViews.productionText`；
- 不少于六个原创迁移方向、推荐状态和独立仿写交接卡；
- 完整性和反复制质量门。

完整人读报告与方向卡必须分别保存为 `01_原始素材说明.md`、`02_完整拆解报告.md` 和 `03_迁移方向选择.md`，并登记历史版本与 SHA-256；五类证据桶只保存下游需要的结构化索引。`downstreamViews.productionText` 是既有 Analysis Package Schema 的兼容字段名，实际由 `content-review-edit` 消费。短证据摘录只用于定位，不能把整篇来源复制进分析包。
