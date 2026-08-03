---
name: data-center
description: 通过本地频道隔离的数据中心检查公开与所有者数据能力、注册真实已发布视频、采集检查点、生成视频／频道报告、查看建议并执行严格学习决定门。用户说“检查频道数据”“复盘视频”“生成7天报告”“查看建议”“查看数据进度”或询问 Publication Receipt、Analytics 授权、T+24／T+7／T+28 数据时使用；不接触 Token，不发起 OAuth，不把公开指标冒充 Studio 事实，也不自动写入长期频道学习规则。
---

# 频道数据中心

只向普通用户解释“现在有什么数据、能得出什么、还缺什么、下一步做什么”。先读取 [工具协议](references/tool-protocol.md)，再调用任何数据工具。

## 启动

1. 调用 `data_center_capabilities`，确认 Metric Catalog、快照／报告版本、频道隔离和 Analytics 授权状态。
2. 把 Analytics 授权与上传授权分开显示。默认应为 `AUTH_REQUIRED`、`available=false`；收入权限关闭且不可用。
3. 不询问、读取、保存或回显 Token、secret、客户端密钥、浏览器登录态或 OAuth 回调。不发起 OAuth。
4. 一个任务只绑定一个 `channelProfileId`；不得读取、比较或合并其他频道的数据、基线、建议或学习记录。

## 自然语言路由

- “检查频道数据”或“查看数据进度”：先调用 `data_progress_get`。没有真实回执时显示 `WAITING_FOR_PUBLICATION_RECEIPT` 和“先完成真实发布并取得回执”；不要用 Stage6 本地发布包、`.ready`、上传意图或本地状态代替回执。
- “复盘视频”：仅在尚未注册且已有真实 Publication Receipt v1 与真实 `youtube_video_id` 时调用 `data_video_register`；随后调用 `data_collection_run` 和 `data_report_generate`。已注册时幂等复用，不重复建档。
- “生成7天报告”：调用 `data_collection_run` 处理 `T+7` 触发检查点，再调用 `data_report_generate`。T+7 是调度检查点，不声称是官方精确窗口。
- “查看建议”：调用 `data_recommendations_list`，展示证据、替代解释、样本量、置信度、适用范围、验证与推翻条件；默认停在 `AWAITING_LEARNING_DECISION`。
- 用户明确决定建议：才调用 `data_learning_decide`。仅本次测试可记录项目实验；长期 `channel_default` 或 `must_avoid` 必须返回 `LONG_TERM_LEARNING_APPROVAL_REQUIRED`，不得调用既有 `channel_learning record`。

## 注册与合成验收

- 正式注册只接受哈希有效的 Publication Receipt v1、非空有效 `youtube_video_id`，以及与频道、项目、Topic、Manuscript、Publishing、Production、Publish Intent 版本和 SHA-256 一致的绑定。
- 任一回执缺失、坏哈希、跨频道或 fake／synthetic video ID 都要失败关闭。没有回执时保持 `WAITING_FOR_PUBLICATION_RECEIPT`。
- `syntheticFixture=true` 只用于明确隔离的 synthetic 命名空间；快照、报告和建议持续标注 `syntheticFixture`／recorded fixture。夹具中的事实等级仅验证来源语义，不得写入正式命名空间或表述为真实频道表现。

## 数据与报告边界

- 只使用六个事实等级：`SYSTEM_FACT`、`PUBLIC_API_FACT`、`OWNER_ANALYTICS_FACT`、`SAMPLE_OBSERVATION`、`INFERENCE`、`UNKNOWN`。
- 推断必须绑定事实、替代解释、置信度和可验证动作；未知保持 `UNKNOWN`，不得填 `0`。
- 公开视频只能产生 `PUBLIC_API_FACT`。仅有公开数据时，CTR、留存、流量来源、设备、人口、订阅归因和收入均为 `UNKNOWN`。
- `data_collection_run` 保存 `collected_at`、窗口、`data_cutoff`、时区和完整性；迟到数据生成新修订，不覆盖原始记录。重复查询结果哈希不变时幂等复用。
- `data_report_generate` 同时产出 JSON 和普通用户 Markdown，并明确 `provisional`、`complete`、`revised` 或 `superseded`、数据截止、事实／推断／未知、样本不足和不要过度解读项。
- 留存映射只生成复查证据卡。`elapsedVideoTimeRatio` 可以大于 1，映射到时间、目标语言行、分镜和故事节点时不得截断，也不得自动改稿。
- 基线优先同频道、相近发布年龄、形态、语言、时长、题材、时段和来源；样本不足时降级并标低置信度，不套用通用“优秀 CTR”阈值。

## 完成卡

显示当前频道、视频注册状态、检查点、最近数据截止、完整性、报告状态、Analytics 授权、待确认建议和下一步。只读进度查询不得推进采集、生成报告或改变学习状态。

运行安装检查时执行 `scripts/check_data_center_install.py`。默认在临时隔离数据根中检查七个工具和 `AUTH_REQUIRED` 安全边界；使用 `--static-only` 只检查文件与协议声明。
