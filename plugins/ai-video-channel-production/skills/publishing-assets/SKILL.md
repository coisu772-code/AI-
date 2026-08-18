---
name: publishing-assets
description: 用户明确开始制作或要求汇总发布素材后，默认继承已确认正式口播稿的标题，并只复用当前自由创作工作区中用户已经明确要求且确认的简介、Hashtags 或自定义封面。简介、Hashtags 和自定义封面全部可省略；不得为了制作或发布自动补齐，也不得读取旧项目素材填空。
---

# 发布素材汇总

先读取 [逐阶段确认契约](../channel-production/references/manual-stage-confirmations.md)。频道预设或历史项目中的自动字段不能替代当前任务确认。

本 Skill 是制作门后的汇总器，不是创作阶段必经步骤：

- `$content-title-description` 同时提供 `content-title` → `title-asset-v1`、`content-description` → `description-asset-v1` 和 `content-thumbnail` → `thumbnail-asset-v1`。

## 进入

1. 调用 `content_workspace_get` 和读取 `productionHandoffPath`，只接收用户已确认、且在制作门中选定的唯一正式文稿。
2. 读取 `assets/content-extension-slots.json` 只能用于确认可选能力是否存在，不能把简介、Hashtags 或封面槽位转成必填门。
3. 从 `content_workspace_narration_prepare` 结果读取已确认口播稿标题及中文对照，作为默认正式标题；再逐项读取当前工作区中用户本次明确要求且已确认的简介、Hashtags 和自定义封面，并验证项目、目标语言、母稿版本与 SHA-256。用户本次明确确认了另一个标题时可覆盖口播稿标题；不得从频道预设或旧项目补值。

## 汇总质量门

- 标题只能有一个正式选择。默认路线只保存一条与口播稿完全一致的正式标题记录及中文对照；只有用户明确要求生成／优化标题时才校验六个候选，且每个候选都须有中文翻译、正文事实依据和承诺兑现记录；
- 用户已经明确要求简介或 Hashtags 时，它们必须来自 `description-asset-v1`；目标语言简介须有完整中文翻译，每个实际提供的 Hashtag 须有中文含义，不得在本 Skill 擅自补写；用户未要求时提交空简介与空 Hashtags；
- 用户已经明确要求自定义封面时，封面必须来自 `thumbnail-asset-v1`，为真实可读的 16:9 文件并带大小与 SHA-256；用户未要求时使用 `youtube_auto`，不生成封面、不要求封面文件，发布时不调用 `thumbnails.set`；
- 用户确实要求的资产若版本错配、坏哈希、事实越界或仍是提示词／占位图时停止。未请求的简介、Hashtags 和封面永远不得列为缺失项。口播稿已有可用标题时不得把“未生成标题候选”列为缺失；若口播稿没有标题，先聚焦询问用户提供标题，只有用户选择生成时才调用标题能力；
- 参考频道身份不得冒充目标发布频道，不读取 Token、OAuth 或浏览器登录态。

## 冻结

1. 展示唯一标题，以及用户实际提供的简介、Hashtags 和自定义封面；未提供项明确显示“未要求／将留空／使用 YouTube 自动缩略图”，不启动生成器。
2. 展示“已复用项／本次补齐项／仍缺失项”。用户已经分别确认的内容不得再次重选；只有新增或改变的项需要确认。
3. 调用 `content_publishing_finalize`。默认提交 `titleSource=confirmed_narration`、口播稿标题与中文对照，并省略 `titleCandidates`；用户明确生成／优化过标题时才提交 `titleSource=generated_candidates` 和六个候选。简介、Hashtags、自定义封面及其中文对照只在用户实际要求并确认后提交；否则省略这些参数，由工具冻结为空简介、空 Hashtags 和 `youtube_auto`。
4. 生成一份当前项目发布素材汇总文档，显示正式稿、标题和实际存在的可选发布素材来源；未生成的简介、Hashtags 与自定义封面只记录省略状态，不伪造路径、版本或 SHA-256。
5. `publishing.json` 和正式发布包仍只包含目标语言发布字段，中文审核译文不得进入 YouTube 上传字段。
6. 调用 `content_integrity_check`；只有包和审核文档完整时才称为 `PUBLISHING_ASSETS_READY`。
7. 调用只读 `content_handoff_check` 检查是否具备制作条件；不在本 Skill 启动工坊。

G5 联合确认卡必须按中文故事、中文标题在前；简介、标签含义和封面文案仅在实际存在时展示，未提供则用清晰的省略状态代替。目标语言正式字段随后展示；频道、隐私状态与上传策略仍留待成片后的 G6 最终中文验收卡集中确认。

## 边界

- 不生成、改写或重选标题、简介、Hashtags、封面和正式母稿。
- 不调用工坊、Google／YouTube 授权、上传、发布回执、Analytics 或长期频道学习。
- 任一资产缺失时返回具体缺失项，不得使用旧流程、提示词文本或占位图回退。
