---
name: content-title-description
description: 根据已通过编辑审核并冻结的最终正文，生成与事实一致、适配日本、美国、中国或其他目标市场的作品书名或 YouTube 视频标题，以及可直接粘贴到 YouTube 的视频简介。用户说“生成标题和简介”“给这个成稿起标题”“写YouTube简介”或要求完成四阶段内容流程时使用；不根据早期大纲编造最终正文不存在的承诺。
---

# 标题与简介

这是四阶段内容主链的第四步。执行前必须完整阅读 [references/prompt-v2.1.txt](references/prompt-v2.1.txt) 和 [references/title-description-contract.md](references/title-description-contract.md)。原提示词中的“导言”是开场钩子，不等于 YouTube 简介；本 Skill 使用其事实提取、标题策略和导言钩子规则，再按补充契约生成完整简介。

## 进入

1. 调用 `content_project_get`，只接收 `$content-review-edit` 冻结且 `SCRIPT_READY` 的 Manuscript Package v1。
2. 校验目标频道、地区、语言、受众、母稿版本和 SHA-256。最终正文与早期大纲冲突时，以最终正文为唯一事实源。
3. 提取主角身份、处境、目标、独特机制、冲突、代价、关系、阶段结果、最强情绪、视觉场景、不能编造和不能剧透的内容。

## 标题

- 默认生成六个 YouTube 标题候选；用户要求书名时另生成作品书名，不能混为同一用途。
- 自动选择最合适的两至三种策略，控制剧透级别，按事实准确度、卖点、目标市场自然度、新颖度、点击潜力和候选差异评分。
- 低于 75 分、事实越界、翻译腔或只换词的候选必须重做。
- 审核模式让用户确认唯一标题；已有明确自动模式授权时，选最高分合格项并记录选择依据。

## YouTube 简介

- 用标题承诺和导言钩子规则写前两行，但不把导言原样当成简介。
- 接着说明核心冲突、观看回报和内容边界，避免把完整剧情大纲堆进简介。
- 使用自然目标语言；不得编造正文不存在的身份、关系、系统、数字、背叛、死亡、结果或热点。
- 默认附 8–12 个与正文事实一致的 Hashtags；用户明确不要时可省略。

## 保存与交接

按补充契约保存并绑定同一 Manuscript Package：

- `title-asset-v1`：候选、评分、事实依据、唯一确认标题和 SHA-256；
- `description-asset-v1`：简介正文、Hashtags、事实依据、目标语言和 SHA-256。

两个资产都由本 Skill `content-title-description` 提供。`content-title` 与 `content-description` 是稳定资产槽位，不是另外两个 Skill。封面仍由未来 `content-thumbnail` 提供，当前状态为 `PLANNED_UNAVAILABLE`。完成后可交给 `$publishing-assets` 等待封面并汇总。

## 边界

- 不修改正式母稿，不为吸引点击扭曲正文事实。
- 除非用户明确要求，不额外生成书名、封面短文案或正文导言。
- 不生成封面图片，不启动工坊、上传、Analytics 或长期频道学习。
