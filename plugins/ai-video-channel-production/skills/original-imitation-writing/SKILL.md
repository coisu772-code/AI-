---
name: original-imitation-writing
description: Integrate one or more frozen YouTube copy deconstructions and canonical novel or text sources into exactly eight substantially different original directions, run credibility, scale, causality, channel-fit, originality and anti-copy gates, rank TOP3, wait for explicit user selection, and freeze Writing Style Contract v1 for the topic and manuscript centers. Use when the user asks to 原创仿写、学习多个视频或小说后创作、融合 YouTube 文案与小说资料、做 8 个原创方向、同类型原创而不照抄，或继续已完成拆解的仿写流程。This Skill learns only topic function, structure, rhythm, expression and audience payoff; it never copies original sentences, proper names, complete event order or one work's mainline, and it does not write the full outline or manuscript itself.
---

# 原创仿写文案

把已冻结的视频拆解与规范化小说资料转成一个可审计的原创方向选择门。先完整展示 8 个实质不同方向和 TOP3，必须等用户明确选中一个合格方向，才冻结 `writing-style-contract-v1` 交给选题中心与文稿中心。

## 进入前检查

1. 调用 `original_imitation_capabilities`，确认 `style-imitation` 与 `writing-style-contract-v1` 可用。
2. 确认当前任务只绑定一个目标 `channelProfileId`。频道蒸馏产生的账号专属仿写要求只允许用于同一目标频道。
3. YouTube 来源必须先由 `$video-copy-deconstruction` 冻结为 `analysis-package-v1`，以 `deconstructionId` 引用；不得直接读取视频字幕或凭标题仿写。
4. 小说与用户文本必须先由 `$source-library` 形成 `CONTENT_READY` Source Package，正式分析输入只有规范化 `content.txt`。允许 `novel-web`、`local-file`、`pasted-text`；不接受登录、付费墙、DRM 或验证码绕过所得资料。
5. 每个来源必须声明 `role` 与 `weight`，全部权重精确合计 100。权重只表示功能参考优先级，`weightsAreSegmentShares=false`；不得解释为 A 开头、B 中段、C 结尾的拼接比例。

## 冻结来源计划

调用 `original_imitation_prepare`，传入稳定 `imitationId` 与 1～8 个来源：

- 视频拆解：`{"inputKind":"video-analysis","deconstructionId":"...","sourcePackageId":"...","role":"...","weight":40}`。单视频包可省略 `sourcePackageId`；多视频包必须逐条指定并分别分配角色／权重。
- 小说／文本：`{"inputKind":"canonical-source","sourcePackageId":"...","role":"...","weight":60}`。

可以组合单／多视频、单／多小说、YouTube＋小说、多频道文案拆解＋资料库。多个视频拆解包若绑定频道蒸馏，所有非空 `distillationId` 必须相同；不能跨频道混用账号专属要求。

## 补充分析直接小说来源

视频来源直接消费已经验收的五类拆解。每个直接小说／文本来源则先用 `original_imitation_read_source` 分批读完整 `content.txt`，再调用 `original_imitation_source_checkpoint` 冻结：

- `originalFacts`：原文可直接证明的事实；
- `analysisConclusions`：由事实支持的分析结论；
- `transferableMethods`：只描述可迁移功能、适用条件和证据；
- `prohibitedCopy`：禁止复制的原句、专名、完整事件顺序、单一作品主线与独特表达；
- `unknowns`：资料不能证明的信息。

同时覆盖故事引擎、人物与关系功能、世界规则、功能结构、节奏推进、情绪积累、观众回报、高潮资源、叙述表达、可信度与规模、原创边界。不得把原文摘要冒充新故事。

## 依次生成 8 个方向

每次只调用一次 `original_imitation_direction_checkpoint`，按 `direction 1/8` 到 `8/8` 依次保存。每个方向至少包含：暂定标题、一句话钩子、主角、核心目标、核心冲突、故事引擎、观众心理回报、情绪路线、频道适配理由、实质差异、逻辑风险、连载潜力、制作难度，以及人物关系、世界规则、统一因果引擎和来源贡献。

8 个方向不能是同一母版只换职业、地点、身份名称或数值。它们应在主角／视角、目标、规则／约束、冲突来源、人物关系、融合方式、故事引擎／成长路径、跨题材／表达方式中产生实质差异。

生成方向前先识别来源真正提供的观众心理回报与观看功能，再决定新故事的表面题材标签；不能因为来源表面都是某一职业、地点或事件，就把这些外壳当成必须保留的频道 DNA。

## 统一因果与功能同构

每个方向在写大纲前提交 `functionalIsomorphism` 表，逐节点记录：来源功能、来源实现、新实现、新因果、情绪位置和新稿篇幅占比。表必须覆盖全部来源，新稿节点 `lengthShare` 合计 100，且 `sameEventSequence=false`。

来源权重与功能同构表不授权片段拼接。每个方向必须重建统一的主角目标、人物关系、故事引擎、世界规则、完整因果、情绪曲线、高潮和结局。多来源贡献分别保留，不把冲突方法平均化。

主角能力必须说明来源、范围、限制、代价和成长；阻力方必须有自己的目标、利益、已知信息、推理依据、真实约束和可理解的错误决定。结果推进按“验证→稳定→扩展→新问题→调整→再次扩展”形成过程，不允许突然证据、临时规则或无过程的大结果。

隐藏身份只在来源确实依赖该功能、且新故事对隐瞒动机、持续成本、知情边界与揭露时机都有独立合理因果时允许使用；不能把“其实主角万能”作为修补能力来源或规模跳跃的捷径。

## 可信度与规模硬门

每个方向逐项回答 `q1`～`q10` 这 10 问：为什么主角行动、为何有资格／能力／资源、问题是否值得成为核心、规模是否匹配身份／能力／资源／权限、其他理性行动者为何不能轻易解决、是否依赖所有人愚蠢、是否依赖巧合／临时证据／临时能力、一次正常沟通能否解决、高潮是否由过程积累、结局是否自然必然而非作者强推。

以下任一硬问题会淘汰方向：小事被夸成公司／国家／战争／世界危机、突然救世主、规模跳跃、隐藏万能身份、万能技能、所有专家都错只有主角对、非沟通、巧合高潮、突然证据、临时规则、只给结果无过程、无依据巨额数字、人物工具化、只加剧情绪，以及为了避相似而丢失频道真正的观众回报。

每个方向提交 13 项 0～10 分：频道匹配、观众预期、点击潜力、逻辑可信、人物动机、冲突成立、能力／资源来源、影响规模、世界规则一致、情绪价值、原创差异、连载潜力、制作难度。`logicalPlausibility`、`characterMotivation`、`conflictValidity`、`abilityResourceSource`、`impactScale`、`audienceExpectation` 任一低于 8 即淘汰。

## 原创性硬门

`antiCopyAudit` 必须精确证明：

- `originalSentencesCopied=false`
- `properNamesCopied=false`
- `completeEventOrderCopied=false`
- `singleWorkMainlineCopied=false`
- `segmentSplicingUsed=false`
- `oneCausalEngineRebuilt=true`

本 Skill 只学习 `topicFunction`、`structure`、`rhythm`、`expression`、`audiencePayoff`。不得把原句或标志性台词写进“表达方式”，不得沿用作品名、角色名、地名、组织名、专有能力名、专有道具名，也不得把一部作品换皮后当作融合结果。

## 完整展示、TOP3 与人工确认

8 个方向保存完成后，调用 `original_imitation_directions_finalize`，提交全部 28 组两两实质差异记录和最终质量门。工具自动按合格状态、综合分和原编号连续排名，返回全部 8 个方向、全部评分与 TOP3。

必须把完整 8 个方向与 TOP3 一次展示给用户；`manualConfirmationRequired=true`、`autoSelectionAllowed=false`。即使项目处于自动模式，也不能跳过这次方向选择。只有至少 3 个方向通过全部硬门时才可进入选择。

用户明确确认一个合格方向后，调用 `original_imitation_confirm`。确认只允许 `mode=review` 且 `confirmedBy=user`。用户可以选 TOP3 中的方向，也可以选其他已通过硬门的方向；不能确认被淘汰方向。

## 冻结与下游交接

确认后工具冻结 `writing-style-contract-v1.json`，包含来源锁与权重、账号专属要求、全部排名、选中方向、允许学习项、必须重建项、禁止复制项、统一因果、功能同构、可信度约束、反复制审查和 `topic-center`／`manuscript-center` 两个精简视图。

1. 选题中心调用 `content_project_start`，使用 `sourceMode=imitation` 与 `writingStyleContracts=[{"imitationId":"..."}]`。内容中心自动锁定底层 Source Package，不要求重复手工拼来源。
2. 该路线只扩展已确认方向为一个完整 Topic 候选；候选必须提交 `styleContractCompliance`，证明已应用选中方向、统一因果、功能同构、来源角色／权重和反复制硬门。
3. 选题仍经过现有 G3 明确确认，再由 `$manuscript-production` 读取同一 `styleLocks` 和 `downstreamViews.manuscriptCenter` 生成目标语言正式母稿。
4. 查询使用 `original_imitation_get`，校验使用 `original_imitation_integrity_check`；两者只读。

## 永久边界

- 本 Skill 不下载资料、不重新蒸馏频道、不替代视频拆解，也不直接写完整大纲或正式正文。
- 未展示全部 8 个方向、TOP3 或未取得用户明确确认时，不能冻结写作契约或进入选题中心。
- 不调用工坊、发布、上传、Analytics 或长期频道学习写回。
- 所有下游引用都绑定当前目标频道、版本和 SHA-256；来源或账号要求变更后必须重新建立仿写计划。

字段与工具契约见 [references/contracts.md](references/contracts.md)。
