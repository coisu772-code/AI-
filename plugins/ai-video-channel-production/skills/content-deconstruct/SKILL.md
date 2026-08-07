---
name: content-deconstruct
description: 完整拆解一个或多个视频字幕、上传文本、小说正文或资料库规范正文，检查素材完整性，逐章分析结构、因果、人物、情绪、钩子、表达和商业吸引机制，并给出不少于六个真正不同的原创迁移方向及仿写交接卡。用户说“拆书”“拆解文案”“分析这个视频字幕”“给仿写方向”或要求开始四阶段内容流程时使用；本 Skill 只拆解，不生成新正文。
---

# 拆书与迁移方向

这是四阶段内容主链的第一步。执行前必须完整阅读 [references/prompt-v2.2.txt](references/prompt-v2.2.txt)；该文件是用户提供并冻结的拆书提示词。再读取 [references/deconstruction-contract.md](references/deconstruction-contract.md)，把详细报告映射为系统可持久化的五类证据桶；同时读取 [用户审核文档规范](../channel-production/references/user-review-documents.md)，不得只保存结构化摘要。

## 进入

1. 取得 `$content-source` 返回的 `CONTENT_READY` Source Package；`PARTIAL` 必须有本次接受记录。
2. 调用 `content_deconstruction_capabilities`。
3. 调用 `content_deconstruction_prepare`：单一作品使用 `single`；多个独立作品分别拆解使用 `parallel`；用户要求横向比较时使用 `compare`。
4. 调用 `content_deconstruction_read_source` 直到 `complete=true`。不得只读开头、抽样章节或跳过中段和结尾。

## 执行提示词

- 先做素材完整性检查和作品归组，再判断模式；文件数量不等于作品数量。
- 按提示词完整输出内容定位、全局结构、逐章／逐单元拆解、人物关系、因果、情绪、钩子、节奏、类型专属分析、文风、优缺点和商业潜力。
- 所有结论区分原文事实、编辑诊断、迁移建议和未知；重要判断绑定章节、段落或时间证据。
- 输出不少于六个真正不同的迁移方向，只推荐方向，不生成新大纲或正文。用户没有明确选定时，状态必须是“等待用户选择”，不能把 GPT 推荐冒充用户确认。
- 只分“短篇”和“长篇”两档。长篇允许分批并记录进度，但拆解维度、逐章覆盖和结构质量不得降低。

## 五类冻结结果

将完整报告映射为：

- `originalFacts`：原文直接支持的事实；
- `analysisConclusions`：由 fact ID 支持的分析与置信度；
- `transferableMethods`：可迁移功能、适用条件和实现边界；
- `prohibitedCopy`：原句、专名、标志性表达、完整事件顺序和其他不可照搬内容；
- `unknowns`：当前素材无法证明的信息。

每个来源调用 `content_deconstruction_checkpoint`。全部完成后调用 `content_deconstruction_finalize` 时，除结构化质量门外还必须传入：

- `deconstructionReportMarkdown`：完整拆解报告，不得缩成摘要；
- `transferDirectionsMarkdown`：全部迁移方向、评分、推荐依据、风险和用户选择状态。

工具同时保存 `01_原始素材说明.md`、`02_完整拆解报告.md`、`03_迁移方向选择.md`，再生成 Content Deconstruction Package v1。随后调用 `content_deconstruction_integrity_check`，并向用户展示三份文档的可点击路径、版本与 SHA-256。查询或恢复使用 `content_deconstruction_get`，只补缺失范围。

如果用户要求继续完整流程，将拆书报告、用户确认方向和【独立仿写提示词交接卡】直接交给 `$content-rewrite`。

## 边界

- 不下载来源，不生成新正文，不生成正式标题、简介或封面。
- 不根据标题、封面或公开视频指标编造正文、CTR、留存率或 Studio 受众事实。
- 不调用工坊、上传、Analytics 或长期频道学习。
