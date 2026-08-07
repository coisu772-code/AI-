---
name: content-deconstruct
description: 完整拆解一个或多个视频字幕、上传文本、小说正文或资料库规范正文，检查素材完整性，逐章分析结构、因果、人物、情绪、钩子、表达和商业吸引机制，并用高贴合迁移、中度重构、大胆创新三档通用机制生成真正不同的迁移方向及仿写交接卡。用户说“拆书”“拆解文案”“分析这个视频字幕”“给仿写方向”“完全仿写”或要求开始四阶段内容流程时使用；本 Skill 只拆解，不生成新正文。
---

# 拆书与迁移方向

这是四阶段内容主链的第一步。执行前必须完整阅读 [逐阶段确认契约](../channel-production/references/manual-stage-confirmations.md)、[references/prompt-v2.2.txt](references/prompt-v2.2.txt) 和 [references/deconstruction-contract.md](references/deconstruction-contract.md)，把详细报告映射为系统可持久化的五类证据桶；同时读取 [用户审核文档规范](../channel-production/references/user-review-documents.md)，不得只保存结构化摘要。逐阶段确认契约优先于提示词中关于是否直接继续的旧描述。

## 进入

1. 取得 `$content-source` 返回的 `CONTENT_READY` Source Package；`PARTIAL` 必须有本次接受记录。
2. 调用 `content_deconstruction_capabilities`。
3. 调用 `content_deconstruction_prepare`：单一作品使用 `single`；多个独立作品分别拆解使用 `parallel`；用户要求横向比较时使用 `compare`。
4. 调用 `content_deconstruction_read_source` 直到 `complete=true`。不得只读开头、抽样章节或跳过中段和结尾。

## 执行提示词

- 先做素材完整性检查和作品归组，再判断模式；文件数量不等于作品数量。
- 按提示词完整输出内容定位、全局结构、逐章／逐单元拆解、人物关系、因果、情绪、钩子、节奏、类型专属分析、文风、优缺点和商业潜力。
- 所有结论区分原文事实、编辑诊断、迁移建议和未知；重要判断绑定章节、段落或时间证据。
- 完整拆解后先建立 `sourceStoryDNA`：观众承诺、剧情发动机、关系发动机、世界／现实规则、主要因果链、情绪曲线、高潮功能和结局回报。随后建立 `expansionSeams`，只记录有原文证据的可自然扩展缺口，例如未展开后果、配角未完成目标、规则推演、选择分岔、前史／后续或关系余波。
- 先建立通用 `preservationContract`，分别列出 `mustPreserve`、`allowedToChange`、`mustRebuild` 和 `protectedExpressionBoundary`。不能把人物、关系、主线因果、高潮和结局全部同时列入 `mustRebuild`，也不能把完整主线、主要人物关系和关键事件顺序同时列入 `mustPreserve`。
- 所有题材统一使用三档 `adaptationMode`：`close-structure`（高贴合迁移）、`balanced-reconstruction`（中度重构）、`free-original`（大胆创新）。档位控制保留距离，不绑定晚年情感、异世界、职场或任何固定题材模板。
- 默认同时输出三组方向：`close-structure` 5 个、`balanced-reconstruction` 5 个、`free-original` 5 个，共 15 个。用户明确只看某一档时，该档仍输出 5 个；不得为了凑数量拆成同义方向。频道画像驱动的 10 个频道原生选题属于频道选题流程，不由本 Skill 冒充。
- 每个方向必须绑定至少一个 `expansionSeam` 和可追溯的原文事实锚点；高贴合方向至少绑定 3 个事实锚点，中度重构至少 2 个，大胆创新至少 1 个。必须说明“从原文哪里自然长出来、保留什么、改变什么”，不能只保留抽象主题后另套职业、资产、机构、灾难、听证会、系统、追放或打脸模板。
- 每个方向使用最适合该素材的自由阶段名称写完整因果骨架，不能强制所有题材套“第一目标—初次受阻—中点—至暗时刻—高潮”的统一九段式。仍只到方向骨架，不生成正式大纲、场景、对白或正文。
- 对全部 15 个方向执行组内与跨组两两去重：比较主角目标、世界／现实规则、核心关系、冲突来源、因果发动机、高潮行动和结局回报。共享的 `mustPreserve` 不算重复；除共享项外只换职业、地点、性别、数值或名词必须重做。
- 逐个生成并与已完成候选比较；发现同一通用母版、相同胜利方式或相同结局回报时先重做当前方向，再生成下一个。不得一次列出 15 个同义概念后再用措辞制造差异。
- 推荐评分必须包含原文核心体验保留度、故事完整度、目标受众／频道适配、候选差异度和制作可行性。原创安全是先通过的硬门，不以“离原文越远越好”加分，也不使用没有依据的小数精度。
- 用户没有明确选定时，状态必须是“等待用户选择”，不能把 GPT 推荐冒充用户确认。
- 只分“短篇”和“长篇”两档。长篇允许分批并记录进度，但拆解维度、逐章覆盖和结构质量不得降低。

## 五类冻结结果

将完整报告映射为：

- `originalFacts`：原文直接支持的事实；
- `analysisConclusions`：由 fact ID 支持的分析与置信度；
- `transferableMethods`：可迁移功能、适用条件和实现边界；
- `prohibitedCopy`：原句、专名、标志性表达、完整事件顺序和其他不可照搬内容；
- `unknowns`：当前素材无法证明的信息。

同时冻结结构化 `directionPackage`，其中包含 `sourceStoryDNA`、`expansionSeams`、`adaptationProfiles`、每个方向的 `preservationContract`、`sourceAnchorRefs`、`sourceFidelityEvidence`、`naturalExpansionRationale`、`nonCopyEvidence`、`genericTemplateRisk=false`、`directionDistinctnessMatrix` 和等待用户选择状态，供仿写质量门复核。

每个来源调用 `content_deconstruction_checkpoint`。全部完成后调用 `content_deconstruction_finalize` 时，除结构化质量门外还必须传入：

- `deconstructionReportMarkdown`：完整拆解报告，不得缩成摘要；
- `transferDirectionsMarkdown`：全部迁移方向、评分、推荐依据、风险和用户选择状态。
- `directionPackage`：机器可校验的来源 DNA、扩展缺口、三档各 5 个方向、事实锚点、去重矩阵与选择状态。

工具同时保存 `01_原始素材说明.md`、`02_完整拆解报告.md`、`03_迁移方向选择.md`，再生成 Content Deconstruction Package v1。随后调用 `content_deconstruction_integrity_check`，并向用户展示三份文档的可点击路径、版本与 SHA-256。查询或恢复使用 `content_deconstruction_get`，只补缺失范围。

审核模式完成后状态固定为 `D2_DECONSTRUCTION_AWAITING_USER`，展示报告、15 个方向和推荐项并结束当前轮次。用户选择方向后再冻结 `D3_TOPIC`；普通“继续／按推荐”只确认当前推荐方向。只有当前任务已有明确自动授权时，才可自动采用最高分合格方向并交给 `$content-rewrite`。

## 边界

- 不下载来源，不生成新正文，不生成正式标题、简介或封面。
- 不根据标题、封面或公开视频指标编造正文、CTR、留存率或 Studio 受众事实。
- 不调用工坊、上传、Analytics 或长期频道学习。
