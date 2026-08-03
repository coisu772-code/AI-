---
name: channel-production
description: 作为 AI 视频频道生产系统唯一默认总入口，识别系统管理、频道建库、资料、选题、文稿、发布素材、制作、上传或数据复盘意图，并只路由到当前安装版本真实具备的能力。用户说“启动系统”“开始频道生产”“建立或进入频道资料库”“添加资料”“给我选题”“按大纲写”“生成口播稿”“准备标题封面”“开始或继续制作”“修复失败素材”或询问六大中心状态时使用；阶段5开放安全制作到 VIDEO_READY，不模拟上传、数据分析或长期学习成功。
---

# AI 视频频道生产系统总入口

## 启动与恢复

1. 调用 `system_capabilities`、`content_capabilities` 和 `production_capabilities`，分别读取系统管理、内容与阶段 5 制作能力。
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
- 趋势、单作品、多作品、拆书、拆文、拆视频、同类型改写或仿写：先由 `$topic-selection` 检查稳定 `Analysis Package v1` 扩展接口。提供方或对应 Skill 未安装时明确显示 unavailable，并提供原创、频道锚定或大纲直通路线；不得临时伪造分析结果。
- 工坊制作只允许走阶段 5 的 Production Package v2.1、Production Task v1 与隔离桥；不得调用旧 `.ready` 自动移交链。
- Google／YouTube 授权、发布包、真实上传或回执属于阶段 6，当前安装不调用。`VIDEO_READY` 不等于可发布或已上传。
- Analytics、数据报告或长期频道学习属于阶段 7，当前安装不执行；一次性内容修改只记在项目中。

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
3. Source、Topic、Manuscript、Publishing Asset、Production Package、Production Task 与 Production Result 各状态、版本和确认门。
4. 当前真实进度，例如 `topic n/10` 或文稿第 `n/m` 集；不要把测试 fixture 或占位数据报告为真实产出。
5. 下一项可执行动作、不可用扩展及所缺条件。

## 永久边界

- 目标发布频道身份只来自发布中心只读接口；参考频道永远只是资料来源。
- 一个任务只绑定一个 `channelProfileId`；仅本次覆盖不得污染频道默认值。
- 只读频道学习快照，不执行长期学习写回。
- 工坊只通过阶段 5 安全桥进入隔离项目；不调用旧控制中心发布自动移交，不创建 `.ready`，不执行 Google／YouTube OAuth、上传、远端删除或 Analytics。
- 所有成功结论以本地持久化状态、Schema、确认记录和哈希校验为准，不凭对话记忆自评通过。
