---
name: video-copy-deconstruction
description: Deconstruct one or more YouTube video copies from canonical content.txt into evidence-bound facts, conclusions, transferable methods, prohibited copying boundaries, unknowns, functional sections, emotion and reward curves, voice, rhythm, expression, credibility, and retention mechanics. Use when the user asks to 拆解视频文案、分析一条或多条视频为什么有效、比较视频结构节奏、提炼可迁移写法，或要把单视频分析交给选题中心和文稿中心。This Skill consumes Source Packages and optional target-channel decomposition requirements from channel distillation, and produces Analysis Package v1. It does not imitate, generate eight directions, write outlines, or write manuscripts.
---

# 视频文案拆解

把每条视频的统一正文拆成可审计、可迁移、不可照抄的结构化分析。一次输入多个视频时仍逐条独立冻结，不求平均、不按段落拼接，也不把比较结论冒充单条事实。

## 进入前检查

1. 调用 `video_deconstruction_capabilities`，确认 `video-analysis` 与 `analysis-package-v1` 可用；需要继续原创仿写时再转交 `$original-imitation-writing`，不能在本 Skill 内越过 8 方向选择门。
2. 确认当前任务绑定唯一目标 `channelProfileId`。
3. 每条输入必须是当前目标频道资料库中的 `youtube-video` Source Package，状态为 `CONTENT_READY`，正式正文只有 `content.txt`。时间定位只读取可选 `timing-map.json`。
4. 不读取、传递或保存 VTT、SRT、ASS、JSON3 等字幕正文文件。正文缺失时返回 `$source-library` 补齐，不能凭标题、封面、简介、评论或模型记忆编造全文。
5. 若用户要求按已蒸馏频道标准拆解，把同一目标频道已冻结的 `distillationId` 传给 `video_deconstruction_prepare`。工具会锁定账号专属拆解要求及 SHA-256；不能用其他频道要求。

## 模式与计划

- `single`：拆解一条视频。
- `parallel`：独立拆解多条视频，只并列交付。
- `compare`：先独立拆解多条视频，再比较共享功能和差异。比较必须声明 `eachVideoKeptIndependent=true`、`averagingUsed=false`、`segmentSplicingUsed=false`。

调用 `video_deconstruction_prepare` 冻结视频资料版本、角色、可选频道蒸馏要求和完整维度。每次最多 8 条；同一视频不能重复。

## 读取统一正文

用 `video_deconstruction_read_source` 按段读取正文。工具返回稳定 `p0001` 段落 ID、正文和可选起止秒数；超过一批时按 `nextParagraph` 继续，直到 `complete=true`。证据定位使用 `content.txt#p0001` 或绑定时间范围，不使用字幕文件名。

先读完整正文，再形成结论。不要只分析开头几段后推断完整事件、结局或全片节奏。

## 每条视频的五类证据

每次成功 `video_deconstruction_checkpoint` 必须同时提交五个非空数组：

- `originalFacts`：正文或公开页面能直接证明的事实；每项绑定当前 `sourcePackageId` 和段落／时间定位。
- `analysisConclusions`：由已有 fact ID 支持的分析结论，并给 0–1 置信度。
- `transferableMethods`：只描述功能和适用条件，引用 conclusion ID，并明确交给 `topic-center`、`manuscript-center` 或两者。
- `prohibitedCopy`：至少覆盖原句、专名、完整事件顺序、单一作品主线和其他可识别表达；不能把待复制文本藏进“方法”。
- `unknowns`：正文、页面或用户授权数据不能证明的信息。没有 Studio 数据时，CTR、真实留存率、流量来源和人口后台数据保持未知。

短证据摘录单项不得超过 240 字；分析包不能长期复制正文。

## 完整拆解维度

每条视频固定覆盖：定位、一句话核心、逐段概览、功能结构、情绪曲线、观众回报、兑现与反转、人物功能与关系、叙述声音与表达风格、段落呼吸、表达手法、YouTube 时间节奏、留存机制、标题承诺兑现、跨资产联动、可信度与约束、原创边界。

其中 `sectionMap` 对多段正文至少包含两个功能区段；极短正文只有一个规范段落时仍需一个完整区段。区段必须从 `p0001` 起连续覆盖全部正文，不重叠、不留空。每段记录：功能、观众预期、真实进展、阶段回报、进入／离开情绪和事实证据；有时间映射时还要写起止秒数。留存只能写成基于文本的机制或假设，不能伪装成后台留存率。

可信度检查至少指出能力、资源、流程、因果、反派或阻力是否有明确约束；不存在的信息进入未知，不能用分析自行补剧情。

## 账号专属区块

`video_deconstruction_prepare` 返回 `requiredSections` 时，逐项写入 `requirementCoverage`，原样保留 requirement 文本，标记 `COVERED`，绑定证据并记录观察。视频中未出现某特征时也要有证据地写“未出现”，不能省略、改名或以通用分析代替。

账号要求只对当前目标频道和被冻结的蒸馏版本生效；不得写回插件全局 Skill，也不得向其他频道传播。

## 冻结与交接

1. 每条视频分别调用 `video_deconstruction_checkpoint`。失败或不可访问写 `FAILED`／`SKIPPED` 和原因，不影响其他视频记录。
2. 全部计划视频有真实状态后调用 `video_deconstruction_finalize`。`compare` 模式提交差异保留的比较；其他模式不得伪造比较。
3. 最终 `analysis-package-v1` 内嵌每条冻结分析、失败清单、五类结果和两个精简视图：
   - `downstreamViews.topicCenter`：题材功能、关系／冲突功能、观众回报、可信度约束与原创边界。
   - `downstreamViews.manuscriptCenter`：结构、声音、段落呼吸、表达、时间节奏、留存方法与原创边界。
4. 选题中心创建单视频项目时传 `sourceMode=single-reference` 和 `analysisPackages=[{"deconstructionId":"..."}]`；多视频用 `multi-reference`。内容中心冻结包版本和哈希，选题与文稿共同读取。
5. 查询使用 `video_deconstruction_get`，校验使用 `video_deconstruction_integrity_check`；两者只读。

## 永久边界

- 本 Skill 不执行频道聚合蒸馏，不下载资料，不生成原创方向，不选 TOP3，不写大纲或正文。
- 不复制原句、专名、完整事件顺序、单一作品主线或独特表达；多视频也不拼接来源段落。
- 不调用工坊、发布、上传、Analytics 或长期频道学习写回。
- 原创仿写必须转交 `$original-imitation-writing`，由其生成 8 个方向、等待用户确认并冻结 `writing-style-contract-v1`；不能用本拆解包直接冒充仿写成品。

字段细节见 [references/contracts.md](references/contracts.md)。
