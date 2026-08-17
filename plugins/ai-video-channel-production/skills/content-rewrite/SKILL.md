---
name: content-rewrite
description: 在当前无频道自由创作工作区内，依据用户明确提供或确认的创作简报／故事大纲，以及本任务登记的外部提示词，生成完整目标语言正文与必要的中文审核版。用户说“按这个大纲写”“用我上传的提示词写正文”时使用；不绑定频道、不创建旧式频道项目，也不恢复旧拆解或仿写方向。
---

# 按确认大纲生成正文

旧拆解与方向能力已移除；本 Skill 只执行当前任务确认的大纲或外部提示词合同。

先完整阅读 [逐阶段确认契约](../channel-production/references/manual-stage-confirmations.md) 和 [用户审核文档规范](../channel-production/references/user-review-documents.md)。本 Skill 只把已经确认的创作方案写成完整正文，不负责分析来源或决定创作方向。

## 唯一入口

1. 只读取当前 `workspaceId` 中用户提供或已确认的大纲，以及当前工作区登记的外部提示词。文件名不要求是 `02_创作方案与大纲确认.md`。
2. 创作简报／故事大纲必须由用户在当前任务提供或确认，正文不少于 80 字，并明确主角、核心目标或困境、主要因果推进和结局边界。
3. 热点研究或原创重构结果只有在用户看过并确认后，才能作为 `providedOutline`；Source Package、视频标题、简介、关键词、旧拆解包、旧迁移方向和旧 8 方向结果都不能替代。
4. 用户只提供链接或原文并说“拆解、给仿写方向、完全仿写”，但没有当前任务提示词合同或确认大纲时停止，说明旧内置能力已移除；不得自行补出大纲。已经存在有效 `task-prompt-guided` 合同时，读取合同列出的原始文件路径与字段映射执行，不适用该停止规则。
5. 新任务不得读取旧项目的 `Content Deconstruction Package`、`Writing Style Contract`、`selectedDirectionId`、`activeVersionId` 或任何历史方向记录。

## 生成与保存

1. 调用 `content_workspace_get`，确认工作区仍为 `UNBOUND` 或尚未被内容修改失效；不得调用 `channel_list`、`content_project_start`、`content_topic_checkpoint` 或 `content_topic_finalize`。
2. 围绕当前确认的大纲生成唯一完整正文。临时提示词按 `executionOrder` 和 `fieldMappings` 执行，只控制本次内容方法与输出格式。
   提示词正文始终留在用户原文件，不复制进本 Skill、频道规则或安装包。
3. 按用户本次要求创作完整正文；只分短篇与长篇，不得压缩成摘要或套固定章数。
4. 调用 `content_workspace_document_save` 保存目标语言全文；外语项目另存完整中文版。文档 ID 和标题反映实际用途，不强制旧编号。中文版只供用户审核，不进入配音。
5. 展示文档绝对路径、版本和 SHA-256。审核模式等待用户用 `content_workspace_document_confirm` 确认当前版本；只有用户明确要求继续编辑时才交给 `$content-review-edit`。

## 写作边界

- 忠实执行用户确认的大纲，但重新组织具体表达，不逐句复制来源正文。
- 不读取或恢复已退役拆解、迁移方向、8 方向仿写、旧提示词示例或其他项目候选。
- 不擅自新增改变主线的世界机制、主要关系、核心冲突或结局；必要缺口先询问用户。
- 不生成正式标题、简介、Hashtags 或封面。
- 不启动工坊、上传、Analytics 或长期频道学习。
- 正式稿或发布素材已经冻结后，用户要求局部修改时先调用 `content_revision_begin`，确认引用必须精确匹配当前任务、项目和范围；只重做受影响文档与下游包，不得静默覆盖旧版本。
