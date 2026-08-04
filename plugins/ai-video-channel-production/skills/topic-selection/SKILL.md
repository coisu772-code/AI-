---
name: topic-selection
description: 从已绑定频道、合格 Source Package、频道蒸馏或视频文案拆解 Analysis Package、以及用户大纲生成、逐项保存、评审并确认 Topic Package v1。用户说“给我选题”“按频道画像推荐”“按视频拆解做选题”“原创一个故事”“按我的大纲直通”“继续候选”“确认这个方案”，或请求趋势、单作品、多作品、拆书、拆文、同类型改写与仿写入口时使用；对应扩展分析能力未安装时必须明确 unavailable，不得伪造分析结果。
---

# 选题中心

只把频道上下文和有来源的资料转成可追溯完整故事方案。不要生成正式母稿、正式标题、正式封面，不要调用工坊、发布、上传或数据中心。

## 进入与恢复

1. 调用 `content_capabilities`，确认 Topic Package v1、内容状态机和所需来源模式可用。
2. 读取当前任务的唯一频道绑定与活动生产预设；一个任务不得混用其他频道资料。
3. 新项目调用 `content_project_start`。继续项目只调用 `content_project_get`，按返回检查点恢复；进度查询保持只读。
4. 读取来源前校验包状态和哈希。只接收 `CONTENT_READY`；`PARTIAL` 只有在用户看过缺失项、明确接受本次使用且工具记录接受证据后才可消费。始终保留 source reference、`fact`、`inference` 与 `unknown`，不得把推断升级为事实。

## 选择来源路线

- `market-original`（原创）：按已确认地区、语言、受众定位和生产范围原创；没有来源时也不得虚构“市场热门”证据。
- `channel-library`（频道画像锚定）：消费阶段 2 频道上下文、阶段 3 资料及已冻结频道运行画像，只在画像边界内迁移观众承诺和功能，重建人物、关系、因果、高潮和结局。
- `provided-outline`（用户大纲直通）：把用户大纲原样传给 `content_project_start`，由工具保存内容哈希；大纲已经入库时同时绑定其来源。只补真正缺失的世界规则、主要角色和生产建议，生成一个唯一方案，跳过竞争选题、市场目录和参考组合。

以下均为稳定扩展路线：`trend`、`single-reference`、`multi-reference`、`book-deconstruction`、`imitation`。先检查 `content_capabilities` 返回的 `analysis-package-v1`（Analysis Package v1）或 `writing-style-contract-v1` 提供方，再只消费对应版本化分析结果。当前 `single-reference` 与 `multi-reference` 已由 `$video-copy-deconstruction` 提供，`imitation` 已由 `$original-imitation-writing` 提供；其余路线在相应提供方未安装时明确显示 unavailable，不要凭标题、封面、评论或模型记忆补造分析包。

频道蒸馏已经提供的 `analysis-package-v1` 只服务 `channel-library` 路线。创建项目时把冻结 `distillationId` 放入 `analysisPackages` 传给 `content_project_start`，并优先读取其 `channel-runtime-profile-v1`；不得把它冒充尚未安装的单视频拆解或原创仿写提供方。

视频拆解包只服务单／多视频参考路线。单视频使用 `sourceMode=single-reference`，多视频使用 `multi-reference`，并把冻结 `deconstructionId` 放入 `analysisPackages`。生成候选时从 `downstreamViews.topicCenter` 与对应 `videoAnalyses` 读取题材功能、人物／关系功能、观众回报、可信度约束和禁止复制项；必须重建人物、专名、关系、事件因果、高潮和结局。不得把拆解摘要、完整事件顺序或单一视频主线改名后作为新选题。

原创仿写路线只接收用户已经从完整 8 个方向中明确确认的 Writing Style Contract v1。创建项目时使用 `sourceMode=imitation` 与 `writingStyleContracts=[{"imitationId":"..."}]`。只把选中方向扩展为一个完整候选，并提交 `styleContractCompliance`；不得重新挑选未确认方向、按来源片段拼接，或绕过统一因果和反复制硬门。该唯一候选仍须完成标准故事事实、完整大纲、逐集剧情、七项评分和 G3 确认。

## 生成与检查点

每个候选完整包含：受众与语言、证据引用、核心卖点、世界规则、故事事实、主要角色、完整大纲、与推荐集数一致的逐集剧情、精确口播字符数、预计时长、精确集数及理由。

- 普通原创或已安装扩展路线生成 3～6 个真正不同的完整候选。
- 频道锚定路线恰好生成 10 个真实完整候选。每完成一个才调用一次 `content_topic_checkpoint`，显示 `topic n/10`；恢复时只补下一个缺失编号。测试小样本、占位对象或一句话概念不得宣称为 10 个候选。
- 大纲直通只保存一个完整方案并明确“无备选”。
- 原创仿写只保存已确认方向对应的一个完整方案并明确“方向已在上游 8 选 1 门确认，无竞争备选”。

先完成创作，再独立审查。为每个候选记录观众适配、点击潜力、故事持续性、可视化表现、原创辨识度、制作可行性和综合分七项 0～10 分；保存连续排名、优势、风险、首选、两个备选及其余未入选原因。标题方向和封面任务只能作为后续简报，不能冒充正式发布资产。

## 确认与冻结

1. 展示完整评选卡。审核模式等待用户对唯一完整方案的明确确认；自动模式也先保存评选摘要，再按已授权 `auto_best` 规则选择合格第一名。
2. 把故事事实、人物关系、世界规则、高潮、结局、逐集剧情和精确生产建议一起锁定，不再增加重复大纲确认门。
3. 调用 `content_topic_finalize`，提交候选、评分、排名、来源锁、确认记录与当前版本。只有工具返回通过状态及可验证哈希时才称为 Topic Package v1 已冻结。
4. 调用 `content_integrity_check` 验证来源、版本和哈希。需要进入文稿中心时只报告可进入 `$manuscript-production`，不要跨中心直接改写或移交未确认包。

## 永久边界

- 只读取频道学习快照；本次修改只写项目变更记录，不调用长期频道学习写回。
- 缺资料、坏哈希、未接受的 `PARTIAL`、未确认选择或不完整排名都停在当前门，不包装为成功。
- 不读取工坊或上传队列，不授权 Google／YouTube，不创建上传意图，不调用生产或数据工具。
