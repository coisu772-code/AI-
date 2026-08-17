---
name: publishing-assets
description: 用户明确开始制作或要求汇总发布素材后，读取当前自由创作工作区已确认的标题、简介、Hashtags 和封面，核对正文版本并复用；只列出真正缺失项，缺失项再交给对应内容能力生成。不得读取旧项目素材填空。
---

# 发布素材汇总

先读取 [逐阶段确认契约](../channel-production/references/manual-stage-confirmations.md)。频道预设或历史项目中的自动字段不能替代当前任务确认。

本 Skill 是制作门后的汇总器，不是创作阶段必经步骤：

- `$content-title-description` 同时提供 `content-title` → `title-asset-v1`、`content-description` → `description-asset-v1` 和 `content-thumbnail` → `thumbnail-asset-v1`。

## 进入

1. 调用 `content_workspace_get` 和读取 `productionHandoffPath`，只接收用户已确认、且在制作门中选定的唯一正式文稿。
2. 读取 `assets/content-extension-slots.json`。标题、简介和封面都必须为 `AVAILABLE`，并绑定同一 `content-title-description`。
3. 逐项读取当前工作区已确认的标题、简介、Hashtags 和封面；验证项目、目标语言、母稿版本与 SHA-256。不得从频道预设或旧项目补值。

## 汇总质量门

- 标题只能有一个正式选择；六个候选均须有中文翻译，且事实承诺必须被正式文本兑现；
- 简介和 Hashtags 必须来自 `description-asset-v1`，目标语言简介须有完整中文翻译，每个 Hashtag 须有中文含义；不得在本 Skill 补写；
- 封面必须来自 `thumbnail-asset-v1`，为真实可读的 16:9 文件并带大小与 SHA-256；
- 资产版本错配、坏哈希、事实越界或仍是提示词／占位图时停止；本次缺失但制作／发布必需的资产列为明确缺失项，再由 `$content-title-description` 只生成该项；
- 参考频道身份不得冒充目标发布频道，不读取 Token、OAuth 或浏览器登录态。

## 冻结

1. 展示唯一标题、简介与 Hashtags、唯一封面、资产包版本、母稿版本和目标频道引用。
2. 展示“已复用项／本次补齐项／仍缺失项”。用户已经分别确认的内容不得再次重选；只有新增或改变的项需要确认。
3. 调用 `content_publishing_finalize`，提交六个标题候选与中文翻译、唯一标题、简介双语对照、中文故事摘要 `storySummaryChinese`、Hashtags 中文对照、五张封面结果及正式封面短文案中文含义；不新增或改写内容。
4. 生成一份当前项目发布素材汇总文档，显示正式稿、标题、简介、Hashtags、封面各自来源路径、版本和 SHA-256；不强制为未改动的素材重新生成旧编号文档。
5. `publishing.json` 和正式发布包仍只包含目标语言发布字段，中文审核译文不得进入 YouTube 上传字段。
6. 调用 `content_integrity_check`；只有包和审核文档完整时才称为 `PUBLISHING_ASSETS_READY`。
7. 调用只读 `content_handoff_check` 检查是否具备制作条件；不在本 Skill 启动工坊。

G5 联合确认卡必须按中文故事、中文标题、中文简介、中文标签含义和中文封面文案在前，目标语言正式字段在后的顺序展示；频道、隐私状态与上传策略仍留待成片后的 G6 最终中文验收卡集中确认。

## 边界

- 不生成、改写或重选标题、简介、Hashtags、封面和正式母稿。
- 不调用工坊、Google／YouTube 授权、上传、发布回执、Analytics 或长期频道学习。
- 任一资产缺失时返回具体缺失项，不得使用旧流程、提示词文本或占位图回退。
