---
name: production-text
description: 把 content-rewrite 冻结的唯一方案直接写成可用于配音、字幕、分镜和工坊制作的目标语言正式文本，执行事实、结构、语言、篇幅、TTS 与映射质量门并冻结 Manuscript Package v1。用户说“输出可以直接制作的文本”“生成完整口播稿”“按拆解仿写并直接出成稿”“继续写完正式稿”时使用；不生成标题、简介或封面，但为三个后续独立 Skills 保存稳定输入位。
---

# 制作文本

只产出一份目标语言正式母稿。它是配音、字幕、分镜和后续标题／简介／封面核验的唯一事实源。

## 进入

1. 调用 `content_project_get`，只接收 `$content-rewrite` 冻结并通过哈希检查的唯一 Topic Package v1。
2. 冻结故事事实、人物关系、世界规则、时间线、高潮、结局、逐集推进和精确篇幅。
3. 从当前频道预设读取目标地区、目标语言、默认配音、篇幅、集数与制作方式；只询问真正缺失且会改变成稿的项目。
4. 需要角色配音时调用 `system_voice_catalog`，只绑定真实可用音色。

## 正式文本

- 直接用目标地区的目标语言创作，不先写另一语言长稿再逐句翻译。
- 保持完整故事结构与目标篇幅，不把大纲扩写成缩水摘要。
- 每行保存稳定 `lineId`、分集、顺序、说话人、`narration|dialogue`、情绪和完整可朗读文本。
- 文稿较长时按集或连续章节分批；每批保存检查点，恢复时只补缺失或失败部分。

## 一次合并质量门

完整草稿冻结后统一检查：

- 上游故事事实、人物关系、因果、伏笔、高潮和结局；
- 每集真实推进、情绪回报和前后状态变化；
- 目标语言自然度、人物声音、地区表达和术语一致；
- 篇幅、集数、TTS 语义切分、缺行、乱序和重复；
- 来源迁移边界，确保没有恢复原句、专名或完整事件顺序。

失败时只修改有证据的失败单元，最多三轮。非中文目标语言生成逐行中文审核稿；中文目标语言直接复用正式母稿，不重复生成。

## 冻结与交付

1. 调用 `content_manuscript_finalize` 冻结 Manuscript Package v1。
2. 调用 `content_integrity_check`；只有返回 `SCRIPT_READY` 且哈希有效时才称为“可直接制作文本”。
3. 显示正式文本、审核稿、质量门、篇幅、集数和下一步。
4. 写入三个稳定但未启用的扩展位：`content-title`、`content-description`、`content-thumbnail`。这些 Skill 未正式开发前必须显示 `PLANNED_UNAVAILABLE`，不能由本 Skill 临时冒充。

扩展接口见 [references/packaging-extension-handoff.md](references/packaging-extension-handoff.md)。

## 边界

- 不生成正式标题、简介、Hashtags 或封面。
- 不启动工坊；制作交给 `$production-handoff`。
- 不授权 Google／YouTube，不上传，不写长期频道学习规则。
