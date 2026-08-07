---
name: content-rewrite
description: 根据 content-deconstruct 冻结的拆书报告、改编档位、保留契约和用户确认方向完成完整仿写正文，支持单一来源高贴合迁移、中度重构、大胆创新，以及结合资料库、上传资料或明确联网研究的多来源融合仿写。用户说“完全仿写”“按这个框架写一篇新的”“结合资料库仿写”“生成新正文”或要求继续四阶段流程时使用；在保留原文核心体验与避免换皮复制之间按已确认档位执行，完成后交给编辑审核。
---

# 仿写正文

这是四阶段内容主链的第二步。执行前必须完整阅读 [逐阶段确认契约](../channel-production/references/manual-stage-confirmations.md)、[references/prompt-v5.2.txt](references/prompt-v5.2.txt)、[references/rewrite-gates.md](references/rewrite-gates.md) 和 [用户审核文档规范](../channel-production/references/user-review-documents.md)。逐阶段确认契约优先于提示词中关于“不等待确认”或“直接继续”的旧描述。用户提供的提示词同时包含拆解与重写；本 Skill 已接收冻结拆书包时，只执行其中的改编设计、重写和自检，不重复拆书。

## 前提

1. 调用 `content_capabilities` 与 `content_project_get`，验证 Content Deconstruction Package v1、Source Package 和 SHA-256。
2. 没有合格拆书包时先调用 `$content-deconstruct`，不得凭标题、封面、简介或不完整印象直接仿写。
3. 验证已确认方向同时绑定 `adaptationMode`、`preservationContract` 和去重结果。用户未确认迁移方向时，审核模式停在方向选择；用户明确授权自动采用最高评分方向时，只能在其明确档位或适用默认档位内采用合格推荐方向。
4. 兼容旧项目：旧包已经由用户确认并进入正文时保持原锁继续；旧包仍停在方向选择且缺少三档保留契约时，返回拆解阶段生成新版方向卡，不沿用旧推荐。

## 两种模式

### 单一来源高贴合原创仿写

使用 `sourceMode=direct-rewrite`，并服从已确认的三档之一：

- `close-structure`：保留观众承诺、核心困境、主要关系功能、宏观结构功能、情绪曲线与结局回报类型；重新设计专名、表达、具体人物参数、标志性场景和证据，并至少重建一条关键因果分支、高潮行动及具体后果。不得同时复制完整主线、主要人物关系和关键事件顺序。
- `balanced-reconstruction`（中度重构）：保留观众承诺、主题、核心关系张力和部分结构功能；重建主要因果发动机、事件链、高潮实现和具体结局。
- `free-original`（大胆创新）：只保留已批准的题材体验、受众需要和表达机制；人物、关系、世界、主因果、高潮与结局全部独立创建。只有用户明确选择或自动策略明确允许时使用。

三档都不得逐句改写、近义词替换、改名换皮或复制专有名称、标志性表达和高度独特的连续事件组合。高贴合不等于复制，自由原创也不等于偏离已确认的观众承诺。

### 资料融合仿写

使用 `sourceMode=synthesis-rewrite`。资料库、用户上传资料和用户明确要求的公开联网研究，都必须先经过 `$content-source` 与 `$content-deconstruct`。每个来源记录抽象贡献和排除项，最终只建立一条统一主线、一套人物关系、一个因果引擎、一个高潮和一个完整结局；不得按来源分段拼接。

## 生成与保存

1. 调用 `content_project_start` 建立绑定项目。
2. 生成唯一完整方案及 `sourceTransformationMap`。其中每个来源条目继续记录功能迁移，同时用方向包绑定 `adaptationMode`、`mustPreserve`、`allowedToChange`、`mustRebuild`、`sourceFidelityEvidence`、`rebuiltCausalBranch` 和 `nonCopyEvidence`；调用 `content_topic_checkpoint` 和 `content_topic_finalize` 冻结 Topic Package v1。
3. 按目标市场的目标语言直接创作完整仿写稿。只分“短篇”和“长篇”两档；用户或频道预设的篇幅、集数和输出语言优先于提示词默认的四章篇幅。长篇可以分批保存，但不能压缩事件链、章节功能或结构质量。
4. 初稿完成后立即调用 `content_review_document_save`，使用 `documentType=rewrite-draft-target` 保存完整正文。不得等到审核结束才落盘，也不得用摘要代替正文。
5. 工具生成稳定文件 `用户审核文档/04_仿写初稿_目标语言.txt` 和不可覆盖的历史版本。调用 `content_review_documents_get`，向用户展示文件路径、版本和 SHA-256。
6. 调用 `content_integrity_check`，确认来源锁、Topic Package 和初稿文档仍有效。

生成的是待编辑初稿，状态只能到 `REWRITE_DRAFT_READY`，不得标记 `SCRIPT_READY`。审核模式必须展示 `04_仿写初稿_目标语言.txt` 并停在 `D4_REWRITE_DRAFT`；用户确认进入编辑审核后才交给 `$content-review-edit`。只有当前任务已有明确自动授权时才可连续进入审核。

## 边界

- 不生成正式标题、YouTube 简介、Hashtags 或封面。
- 不把推断写成来源事实，不恢复原文专名、原句或完整事件顺序。
- 不把“与原文有相似结构或桥段”本身判为失败；检查重点是是否遵守已确认保留契约、是否形成新的具体因果、人物选择和完整结局。
- 不启动工坊、上传、Analytics 或长期频道学习。
