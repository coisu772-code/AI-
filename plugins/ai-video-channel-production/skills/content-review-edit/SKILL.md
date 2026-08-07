---
name: content-review-edit
description: 审查 content-rewrite 生成的仿写初稿或用户提供的完整叙事正文，逐章检查事实、结构、人物、因果、情绪、节奏、对话、语言和目标市场适配，并在授权范围内直接修改、复查和冻结可制作正式母稿。用户说“审稿”“审核并修改”“深度编辑”“检查后直接改好”或要求继续四阶段流程时使用。
---

# 编辑审核与修改

这是四阶段内容主链的第三步。执行前必须完整阅读 [逐阶段确认契约](../channel-production/references/manual-stage-confirmations.md)、[references/prompt-v4.1.txt](references/prompt-v4.1.txt) 和 [用户审核文档规范](../channel-production/references/user-review-documents.md)。逐阶段确认契约优先于提示词中关于“不等待确认”或“直接修改后继续”的旧描述；项目规则、用户本次明确要求和已冻结故事事实优先。

## 进入

1. 读取 `$content-rewrite` 生成的最新 `rewrite-draft-vNNN`、Topic Package v1、拆书包、故事事实和来源转换表。
2. 调用 `content_project_get` 核对项目、频道、目标语言、版本和 SHA-256。
3. 默认使用 L2 深度编辑和模式 B“审稿后直接修改”；只有用户明确要求大改、重构或 L3 时才改变核心结构。用户明确要求只审稿时使用模式 A。
4. 用户直接上传待审文本时也可执行本 Skill；若要进入后续制作包，必须先通过 `$content-source` 建立可追溯项目和来源锁。

## 审核与修改

- 先建立素材完整性说明和全文一致性档案，再执行全局与逐章诊断。
- 问题按 P0、P1、P2、P3 排序，先修复逻辑、身份、时间线、因果、动机、高潮和结局，再处理表达润色。
- 模式 B 必须先给简明审稿结论，再直接修改；不得只列问题不改正文。
- 保护用户禁止改变的事实。未获 L3 授权，不擅自改变人物身份、核心关系、世界规则、关键结果和结局。
- 只分“短篇”和“长篇”两档。长篇可以按连续章节分批修改并保存检查点，但不得跳章、缩写中段或降低结构质量。
- 目标语言正式文本必须自然、完整、可朗读；每行保留稳定 `lineId`、分集／章节、顺序、说话人、`narration|dialogue`、情绪和文本。

## 复查与冻结

1. 完成修改后，按提示词重新检查事实一致性、因果、人物、节奏、情绪、语言和授权边界；修复审稿引入的新问题。
2. 先调用 `content_review_document_save` 保存完整 `editorial-review`，生成 `05_编辑审核报告.md`；报告至少包含问题位置、级别、证据、影响和修改建议。
3. 再调用 `content_review_document_save` 保存完整 `revision-log`，生成 `06_修改记录与前后对照.md`；必须列明修改前、修改后、修改原因、影响范围和是否改变锁定事实。
4. 非中文目标语言生成严格逐行中文审核映射；中文稿直接复用，不二次创作。
5. 非中文目标语言必须在创作稿完成后另开独立二次审校批次，执行外语质量保险门。创作批次 ID 与审校批次 ID 不得相同；每集必须以中文记录语法、地区自然度、姓名与术语、习语搭配、翻译腔、文化称谓、TTS 可读性和中文回译一致性八项结论，失败项定向修订不超过三轮。中文目标稿明确登记 `NOT_APPLICABLE`，不得伪造外语审校。
6. 调用 `content_manuscript_finalize` 时同时提交 `qualityGate` 与 `foreignLanguageQualityGate`，冻结 Manuscript Package v1。工具同时生成 `07_正式稿_目标语言.txt`、`08_正式稿_中文版.txt` 和机器可核验的 `foreign-language-quality-gate.json`；中文版仅供用户审核，不进入配音、字幕或分镜。
7. G4 确认卡先展示中文正式稿路径、中文质量结论和外语保险门结论，再展示目标语言正式稿路径与哈希；调用 `content_review_documents_get` 展示 04–08 文档路径、版本与 SHA-256，再调用 `content_integrity_check`。
8. 只有两道质量门均通过、文档哈希有效并返回 `SCRIPT_READY` 时，才称为可用于配音、字幕、分镜和工坊的唯一事实源。

审核模式完成后展示 05–08 文档并停在 `D5_FINAL_MANUSCRIPT`；用户确认正式稿后才交给 `$content-title-description`。只有当前任务已有明确自动授权时才可连续进入包装。

## 边界

- 不进行 AI 率判断，不故意制造病句或所谓人工痕迹。
- 不生成正式标题、简介、Hashtags 或封面。
- 不启动工坊、上传、Analytics 或长期频道学习。
