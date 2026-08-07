---
name: content-rewrite
description: 根据 content-deconstruct 冻结的拆书报告和用户确认方向完成一篇全新的仿写正文，支持单一来源高贴合原创仿写，以及结合资料库、上传资料或明确联网研究的多来源融合仿写。用户说“完全仿写”“按这个框架写一篇新的”“结合资料库仿写”“生成新正文”或要求继续四阶段流程时使用；必须重建人物、关系、世界、事件因果、高潮和结局，完成后交给编辑审核。
---

# 仿写正文

这是四阶段内容主链的第二步。执行前必须完整阅读 [references/prompt-v5.2.txt](references/prompt-v5.2.txt)、[references/rewrite-gates.md](references/rewrite-gates.md) 和 [用户审核文档规范](../channel-production/references/user-review-documents.md)。用户提供的提示词同时包含拆解与重写；本 Skill 已接收冻结拆书包时，只执行其中的改编设计、重写和自检，不重复拆书。

## 前提

1. 调用 `content_capabilities` 与 `content_project_get`，验证 Content Deconstruction Package v1、Source Package 和 SHA-256。
2. 没有合格拆书包时先调用 `$content-deconstruct`，不得凭标题、封面、简介或不完整印象直接仿写。
3. 用户未确认迁移方向时，审核模式停在方向选择；用户明确授权自动采用最高评分方向时可采用拆书报告中的唯一推荐方向。

## 两种模式

### 单一来源高贴合原创仿写

使用 `sourceMode=direct-rewrite`。可以平移题材体验、世界观层级、宏观大纲、章节功能、人物功能、情绪曲线、钩子和表达气质；必须重新设计作品名、人物、具体关系、背景参数、事件链、证据、冲突解决、高潮行动和结局后果。不得逐句改写、近义词替换或改名换皮。

### 资料融合仿写

使用 `sourceMode=synthesis-rewrite`。资料库、用户上传资料和用户明确要求的公开联网研究，都必须先经过 `$content-source` 与 `$content-deconstruct`。每个来源记录抽象贡献和排除项，最终只建立一条统一主线、一套人物关系、一个因果引擎、一个高潮和一个完整结局；不得按来源分段拼接。

## 生成与保存

1. 调用 `content_project_start` 建立绑定项目。
2. 生成唯一完整方案及 `sourceTransformationMap`，调用 `content_topic_checkpoint` 和 `content_topic_finalize` 冻结 Topic Package v1。
3. 按目标市场的目标语言直接创作完整仿写稿。只分“短篇”和“长篇”两档；用户或频道预设的篇幅、集数和输出语言优先于提示词默认的四章篇幅。长篇可以分批保存，但不能压缩事件链、章节功能或结构质量。
4. 初稿完成后立即调用 `content_review_document_save`，使用 `documentType=rewrite-draft-target` 保存完整正文。不得等到审核结束才落盘，也不得用摘要代替正文。
5. 工具生成稳定文件 `用户审核文档/04_仿写初稿_目标语言.txt` 和不可覆盖的历史版本。调用 `content_review_documents_get`，向用户展示文件路径、版本和 SHA-256。
6. 调用 `content_integrity_check`，确认来源锁、Topic Package 和初稿文档仍有效。

生成的是待编辑初稿，状态只能到 `REWRITE_DRAFT_READY`，不得标记 `SCRIPT_READY`。完成后立即交给 `$content-review-edit` 执行审稿、修改、复查与正式母稿冻结。

## 边界

- 不生成正式标题、YouTube 简介、Hashtags 或封面。
- 不把推断写成来源事实，不恢复原文专名、原句或完整事件顺序。
- 不启动工坊、上传、Analytics 或长期频道学习。
