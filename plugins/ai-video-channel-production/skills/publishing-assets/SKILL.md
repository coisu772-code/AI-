---
name: publishing-assets
description: 在标题、简介和封面资产都由 content-title-description 交付并确认后，校验它们与同一 Manuscript Package v1 的版本、事实和哈希绑定，并汇总为 Publishing Asset Package v1。用户说“汇总发布素材”“检查标题简介封面是否齐全”或“生成发布素材包”时使用；本 Skill 只汇总，不自行生成或补写资产。
---

# 发布素材汇总

先读取 [逐阶段确认契约](../channel-production/references/manual-stage-confirmations.md)。频道预设或历史项目中的自动字段不能替代当前任务确认。

本 Skill 是汇总器，不是内容生成器：

- `$content-title-description` 同时提供 `content-title` → `title-asset-v1`、`content-description` → `description-asset-v1` 和 `content-thumbnail` → `thumbnail-asset-v1`。

## 进入

1. 调用 `content_capabilities` 和 `content_project_get`，只接收 `SCRIPT_READY`、质量门通过且哈希有效的 Manuscript Package v1。
2. 读取 `assets/content-extension-slots.json`。标题、简介和封面都必须为 `AVAILABLE`，并绑定同一 `content-title-description`。
3. 所有资产可用时，读取已确认资产包，验证项目、频道、目标语言、母稿版本与 SHA-256。

## 汇总质量门

- 标题只能有一个正式选择；六个候选均须有中文翻译，且事实承诺必须被正式文本兑现；
- 简介和 Hashtags 必须来自 `description-asset-v1`，目标语言简介须有完整中文翻译，每个 Hashtag 须有中文含义；不得在本 Skill 补写；
- 封面必须来自 `thumbnail-asset-v1`，为真实可读的 16:9 文件并带大小与 SHA-256；
- 任一资产未确认、版本错配、坏哈希、事实越界或仍是提示词／占位图时停止；
- 参考频道身份不得冒充目标发布频道，不读取 Token、OAuth 或浏览器登录态。

## 冻结

1. 展示唯一标题、简介与 Hashtags、唯一封面、资产包版本、母稿版本和目标频道引用。
2. 审核模式停在 `G5_PUBLISHING_ASSETS` 等待联合确认；只有当前任务已有明确自动授权时才可自动确认，且仍须先通过全部硬门。
3. 调用 `content_publishing_finalize`，提交六个标题候选与中文翻译、唯一标题、简介双语对照、中文故事摘要 `storySummaryChinese`、Hashtags 中文对照、五张封面结果及正式封面短文案中文含义；不新增或改写内容。
4. 工具生成 `09_标题简介标签_双语审核.md` 和 `10_封面候选与选择结果.md`。调用 `content_review_documents_get`，向用户显示这两份文档以及 07–08 正式稿的路径、版本和 SHA-256。
5. `publishing.json` 和正式发布包仍只包含目标语言发布字段，中文审核译文不得进入 YouTube 上传字段。
6. 调用 `content_integrity_check`；只有包和审核文档完整时才称为 `PUBLISHING_ASSETS_READY`。
7. 调用只读 `content_handoff_check` 检查是否具备制作条件；不在本 Skill 启动工坊。

G5 联合确认卡必须按中文故事、中文标题、中文简介、中文标签含义和中文封面文案在前，目标语言正式字段在后的顺序展示；频道、隐私状态与上传策略仍留待成片后的 G6 最终中文验收卡集中确认。

## 边界

- 不生成、改写或重选标题、简介、Hashtags、封面和正式母稿。
- 不调用工坊、Google／YouTube 授权、上传、发布回执、Analytics 或长期频道学习。
- 任一资产缺失时返回具体缺失项，不得使用旧流程、提示词文本或占位图回退。
