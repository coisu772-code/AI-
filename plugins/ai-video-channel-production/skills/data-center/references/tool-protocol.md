# 数据中心本地工具协议

## 适用范围

七个工具组成 `Publication Receipt → video registration → Metric Catalog → raw/normalized → Analytics Snapshot v1 → T+24/T+7/T+28 报告 → Recommendation Card v1 → 学习决定` 的本地闭环。安装版工具暴露的 JSON Schema 是参数事实源；字段缺失或协议版本不兼容时失败关闭，不猜测参数。

数据目录固定隔离在 `data/channels/<profile>/analytics/`，下含 `metric-catalog`、`raw`、`normalized`、`snapshots`、`baselines`、`timeline-maps`、`reports`、`recommendations`、`experiments` 和 `sync-state`。不得读取或合并其他频道。既有用户数据库需要迁移时只生成迁移计划与备份要求并返回 `MIGRATION_APPROVAL_REQUIRED`，不执行迁移。

## 全局不变量

- 正式命名空间只接收哈希有效的 Publication Receipt v1 与真实非空 `youtube_video_id`。Stage6 本地包、`.ready`、Upload Intent 或本地发布状态不是回执。
- `syntheticFixture=true` 只进入隔离 synthetic 命名空间，始终标注 fixture／`SAMPLE_OBSERVATION`，不能成为正式注册或线上事实。
- Analytics 授权独立于上传授权，默认 `AUTH_REQUIRED`、`available=false`。只声明最小只读 scope；收入 scope 默认关闭。工具和 Codex 都不接收 Token、secret 或 OAuth 回调，也不发起 OAuth。
- 数据等级只允许 `SYSTEM_FACT`、`PUBLIC_API_FACT`、`OWNER_ANALYTICS_FACT`、`SAMPLE_OBSERVATION`、`INFERENCE`、`UNKNOWN`。`INFERENCE` 必须引用事实、替代解释、置信度和可验证动作；未知不填 0。
- public 适配只产生 `PUBLIC_API_FACT`；没有 owner 数据时 CTR、留存、流量来源、设备、人口、订阅归因和收入保持 `UNKNOWN`。
- 原始数据只追加；标准化、快照、报告和建议版本化并绑定 SHA-256。相同查询结果哈希幂等复用，迟到数据生成新修订。
- 所有写入按 `channelProfileId` 隔离并校验绑定；只读进度不改变状态。跨频道回执、基线、快照、报告或建议均拒绝。

## 工具表面

| 工具 | 语义输入 | 成功输出 | 必须阻断 |
| --- | --- | --- | --- |
| `data_center_capabilities` | 无凭据 | Metric Catalog／Snapshot／Report／Recommendation 版本、适配器、目录、授权和安全边界 | 不可见 Token；不发起 OAuth；收入 scope 关闭 |
| `data_video_register` | 频道、项目、真实 Publication Receipt v1 路径／内容及 SHA-256、真实 `youtube_video_id`、Topic／Manuscript／Publishing／Production／Publish Intent 版本与哈希；或显式隔离 fixture | 幂等 video registration、命名空间、完整上游绑定和注册状态 | 无回执、空／fake／synthetic ID 进入正式库、坏哈希、跨频道、Stage6 本地状态冒充回执 |
| `data_collection_run` | 已注册视频、来源、`T+24`／`T+7`／`T+28` 检查点、查询计划或有权导入／录制的响应 | raw binding、normalized metrics、Analytics Snapshot v1、查询哈希、`collected_at`、window、`data_cutoff`、时区、完整性、修订／复用状态 | 未注册、无 `data_cutoff`、公开数据标 owner、缺失填 0、重复原始报告、跨频道、凭据或收入 scope |
| `data_report_generate` | 频道、视频／频道报告类型、快照版本、检查点和可比基线条件 | Video Performance Report v1 或 Channel Strategy Report v1 的 JSON 与普通用户 Markdown、状态、截止时间、事实／推断／未知、不要过度解读项 | 无来源锁、跨频道基线、公开数据伪造 CTR／留存／Studio 事实、通用硬阈值、留存比例大于 1 被截断 |
| `data_recommendations_list` | 当前频道，可选报告／视频过滤 | Recommendation Card v1 列表及 `AWAITING_LEARNING_DECISION`，含证据、替代解释、样本量、置信度、范围、保持／修改／避免／测试、验证和推翻条件 | 无证据建议、跨频道建议、自动确认或自动长期写回 |
| `data_learning_decide` | 建议 ID、显式决定、适用范围和当前频道绑定 | 拒绝、保持、仅本次项目实验，或明确审批门 | `channel_default`／`must_avoid`／任何长期写回返回 `LONG_TERM_LEARNING_APPROVAL_REQUIRED`；不得调用既有 `channel_learning record`；自动模式不得绕过 |
| `data_progress_get` | 当前频道，可选视频 ID | 注册、检查点、采集、快照、报告、建议和授权的只读状态 | 不推进采集、不生成报告、不改建议或学习状态；无回执返回 `WAITING_FOR_PUBLICATION_RECEIPT` |

## 采集与状态

`T+24`、`T+7`、`T+28` 是触发检查点，不是精确官方窗口。每次采集保存 `collected_at`、查询窗口、`data_cutoff`、频道时区和完整性，并区分 `missing`、`threshold_protected`、真实 `0` 与 `delayed`。支持断点补采、重启恢复和迟到数据修订；旧版本保留并标记 `superseded`，不能覆盖或删除。

Analytics Snapshot v1 必须包含 manifest、query plan、raw bindings、normalized metrics、completeness 与 source lock。公开数据导入只在用户有权使用时进行；owner analytics／reporting 无授权时稳定返回 `AUTH_REQUIRED`，不造值。

## 报告与建议

Video Performance Report v1 和 Channel Strategy Report v1 同时输出 JSON 与 Markdown，标明 `provisional`、`complete`、`revised` 或 `superseded`、数据截止、事实等级、推断、未知、样本不足和不可过度解读项。

留存证据把 `elapsedVideoTimeRatio → 时间 → 目标语言行／分镜／故事节点`；允许比例大于 1，只生成复查证据卡，不自动改稿。基线优先同频道及相近发布年龄、内容形态、语言、时长、题材、发布时间和来源，样本不足时降级并标低置信度。

Recommendation Card v1 默认 `AWAITING_LEARNING_DECISION`。项目级一次性实验可以记录；任何长期频道规则都必须在新的用户确认回合后才可能执行，本协议阶段只返回 `LONG_TERM_LEARNING_APPROVAL_REQUIRED`。
