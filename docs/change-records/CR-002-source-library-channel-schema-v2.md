# CR-002：Source Library 使用 channel.db Schema 2

- 状态：已接受，阶段3本地候选
- 日期：2026-08-04
- 影响范围：本地工具服务 `channel.db`
- 不变边界：Source Package `1.0.0`、本地工具协议 `1.0.0`、阶段2频道档案与生产预设契约

## 背景

阶段3需要在每个频道的独立资料库中保存来源登记、版本、资产、别名、采集任务和恢复检查点。阶段2的 `channel.db` Schema 1 只包含频道档案、生产预设、覆盖记录和迁移历史，无法表达这些资料事实。

## 决策

把 `channel.db` 递增到 Schema 2，并仅新增以下表与索引：

- `source_packages`
- `source_versions`
- `source_assets`
- `source_aliases`
- `acquisition_jobs`
- `acquisition_job_items`

现有阶段2表、字段和读写语义保持不变。迁移继续使用既有的迁移前备份、事务提交、失败回滚和重试机制。`system.db` 仍为 Schema 1。

Source Package 对外清单继续符合 `contracts/schemas/source-package.schema.json` 的 `1.0.0`。采集方式、完整性、失败原因、来源边界、编码和章节／页／段信息写入版本化资产与采集报告，不通过静默修改 v1 契约增加必填字段。

## 兼容性与回滚

- Schema 1 数据库首次由阶段3服务打开时自动备份并迁移到 Schema 2。
- 阶段2档案和预设接口继续回归测试。
- 阶段3代码回滚时，应恢复迁移前的频道数据库备份；不得让只理解 Schema 1 的旧服务直接写入 Schema 2。
- 该变更不授权内容分析、内容生成、工坊调用、OAuth 或上传。

## 验证

阶段3验收必须覆盖新建数据库、Schema 1 迁移、迁移失败恢复、资料去重、增量版本、任务取消／恢复、服务重启后检索，以及完整阶段1和阶段2回归。
