---
name: channel-production
description: 作为 AI 视频频道生产系统唯一默认总入口，识别系统管理、频道建库、资料、选题、文稿、发布素材、制作、上传准备或数据复盘意图，并只路由到当前安装版本真实具备的能力。用户说“启动系统”“开始频道生产”“建立或进入频道资料库”“添加资料”“给我选题”“按大纲写”“生成口播稿”“准备标题封面”“开始或继续制作”“修复失败素材”“准备上传成片”“查看上传状态与回执”“检查频道数据”“复盘视频”“生成7天报告”“查看建议”或询问各业务中心状态时使用；阶段7开放频道隔离的本地数据闭环，但不模拟 OAuth、真实上传、真实 video ID、发布回执、私有 Analytics 数据或长期学习成功。
---

# AI 视频频道生产系统总入口

## 启动与恢复

1. 调用 `system_capabilities`、`content_capabilities` 和 `production_capabilities`，分别读取系统管理、内容与阶段 5 制作能力；只有用户有数据复盘意图时才额外调用 `data_center_capabilities`。
2. 区分“可用”“需要用户处理”“当前安装 unavailable”，不要把插件加载或 MCP 启动等同于业务包通过。
3. 新任务先读取频道列表并确认唯一 READY 频道；同一任务不得切换到另一个频道。
4. 继续内容项目调用 `content_project_get`，按真实状态和检查点进入对应专用 Skill。进度查询只读，不修改任务、确认门或活动步骤。
5. 不读取、要求或回显任何凭据。

## 自然语言路由

- 建立频道资料库、进入已有频道、生产默认值、本次覆盖、备份、恢复或迁移：调用 `$channel-onboarding`。
- 添加、下载、导入、更新、检索、取消或恢复资料任务：调用 `$source-library`。资料库仍属于系统管理中心。
- 原创选题、按频道画像推荐、用户大纲直通、候选进度、评选或确认完整故事：调用 `$topic-selection`。
- 目标语言正式母稿、逐行中文审核稿、文稿质量门、逐集恢复或联合确认：调用 `$manuscript-production`。
- 唯一标题、简介、8～12 个 Hashtags、封面、CTR 联评或发布素材确认：调用 `$publishing-assets`。
- 标准生产包、工坊移交、制作进度、暂停恢复、失败重试、自动成片、剪映草稿、成片回收或技术验收：调用 `$production-handoff`。
- `VIDEO_READY` 后准备上传成片、重验／隔离导入发布包、查看上传状态与回执：调用 `$publish-video`。五个冻结工具为 `assemble_publish_package_v2`、`validate_publish_package_v2`、`import_publish_package_v2`、`get_publication_status`、`get_publication_receipt`。
- 检查频道数据、复盘视频、生成 T+24／T+7／T+28 报告、查看建议或数据进度：调用 `$data-center`。七个工具为 `data_center_capabilities`、`data_video_register`、`data_collection_run`、`data_report_generate`、`data_recommendations_list`、`data_learning_decide`、`data_progress_get`。没有真实 Publication Receipt v1 时保持 `WAITING_FOR_PUBLICATION_RECEIPT`；Analytics 默认 `AUTH_REQUIRED`、`available=false`。
- 趋势、单作品、多作品、拆书、拆文、拆视频、同类型改写或仿写：先由 `$topic-selection` 检查稳定 `Analysis Package v1` 扩展接口。提供方或对应 Skill 未安装时明确显示 unavailable，并提供原创、频道锚定或大纲直通路线；不得临时伪造分析结果。
- 工坊制作只允许走阶段 5 的 Production Package v2.1、Production Task v1 与隔离桥；不得调用旧 `.ready` 自动移交链。
- 阶段6只允许发布包 v2 本地组装、独立验证、隔离导入和只读状态／回执查询；始终 `networkExecution=false`。Google／YouTube OAuth、真实上传、远端修改和删除仍需外部明确批准。`VIDEO_READY`、`.ready`、`READY_TO_UPLOAD` 均不等于已上传。
- 阶段7只允许在频道隔离目录内注册真实发布回执、导入／采集有权使用的数据、生成版本化快照／报告并展示建议。它不接触 Token、不发起 OAuth、不调用私有 Analytics API；`syntheticFixture=true` 只能进入隔离命名空间。任何 `channel_default`、`must_avoid` 或其他长期学习写回都必须返回 `LONG_TERM_LEARNING_APPROVAL_REQUIRED`，自动模式也不得绕过。

## 内容包主链

```text
Stage 2 Channel Profile / Production Profile
+ Stage 3 Source Package
→ Topic Package v1（G3）
→ Manuscript Package v1（G4）
→ Publishing Asset Package v1（G5）
→ content_handoff_check
→ Production Package v2.1
→ Production Task v1（P0–P11）
→ Production Result Package v1（VIDEO_READY）
→ Publish Package v2（PACKAGE_READY／WAITING_REVIEW／READY_TO_UPLOAD，仅本地资格）
→ Publication Receipt v1 + 真实 youtube_video_id（外部真实发布后）
→ Video Registration → Analytics Snapshot v1 → Reports → Recommendation Card v1（AWAITING_LEARNING_DECISION）
```

- 来源只接 `CONTENT_READY`；`PARTIAL` 必须先展示缺失项并取得本次明确接受。所有下游保留 `fact`、`inference`、`unknown`、来源版本和 SHA-256。
- 每个正式包冻结后不可原地覆盖；修改生成新版本，并只使真正受影响的下游失效。
- 审核模式等待对应确认门；自动模式只能在该项目已有明确授权且质量硬门通过时自动确认例行内容阶段。
- 未确认、坏哈希、语言行映射错误、Hashtags 数量错误、封面比例错误或上游版本错配不得移交。
- `content_handoff_check` 只报告是否具备阶段 5 条件；只有路由到 `$production-handoff` 并通过制作输入卡后才组包、建任务或调用隔离工坊。

专用 Skill 的确定性工具顺序固定为：`content_project_start` 创建内容项目；`content_topic_checkpoint` 逐候选保存；`content_topic_finalize` 冻结选题；`content_manuscript_finalize` 冻结母稿与审核稿；`content_publishing_finalize` 冻结发布素材。每次冻结后调用 `content_integrity_check`，恢复或查进度使用 `content_project_get`，不得跳过中间确认门。

## 状态卡

用普通用户能理解的语言显示：

1. 产品与本地工具版本。
2. 当前唯一频道、地区、语言和活动生产预设。
3. Source、Topic、Manuscript、Publishing Asset、Production Package、Production Task、Production Result、Publication Receipt、Analytics Snapshot、Report 与 Recommendation 各状态、版本和确认门。
4. 当前真实进度，例如 `topic n/10` 或文稿第 `n/m` 集；不要把测试 fixture 或占位数据报告为真实产出。
5. 下一项可执行动作、不可用扩展及所缺条件。

## 永久边界

- 目标发布频道身份只来自发布中心只读接口；参考频道永远只是资料来源。
- 一个任务只绑定一个 `channelProfileId`；仅本次覆盖不得污染频道默认值。
- 只读频道学习快照，不执行长期学习写回。
- 工坊只通过阶段 5 安全桥进入隔离项目；工坊本身不创建 `.ready`。只有 `$publish-video` 可在 Stage6 本地工具中组装／重验／隔离导入 `.ready`，并且不得执行 Google／YouTube OAuth、上传、远端删除或 Analytics。
- `$data-center` 只消费哈希有效的真实发布回执或明确隔离的 synthetic fixture；Stage6 本地状态不能冒充回执，PUBLIC_API_FACT 不能冒充 OWNER_ANALYTICS_FACT，UNKNOWN 不能填 0。
- 学习建议默认等待用户决定；项目级实验与长期频道规则严格分开，不调用既有 `channel_learning record` 自动写回长期规则。
- 所有成功结论以本地持久化状态、Schema、确认记录和哈希校验为准，不凭对话记忆自评通过。
