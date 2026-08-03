---
name: publishing-assets
description: 从已确认且哈希有效的 Manuscript Package v1 生成并联合确认唯一目标语言标题、简介、8～12 个 Hashtags、封面策略、候选与唯一正式封面、CTR 联评和 Publishing Asset Package v1。用户说“生成标题封面”“准备发布素材”“写简介标签”“重做封面”“确认发布卡”时使用；只准备资产，不进入工坊、授权或上传。
---

# 发布素材中心

只完成发布中心阶段 A 的包装资产。正式素材必须以已确认目标语言母稿为唯一故事事实源；不要调用工坊、组装成片上传包、授权频道或上传视频。

## 进入与来源冻结

1. 调用 `content_capabilities`，确认 Publishing Asset Package v1、`image-provider-v1`、封面模式和验证规则可用。
2. 调用 `content_project_get`。只接收 `SCRIPT_READY`、联合确认记录完整、质量门通过、逐行映射通过且哈希有效的 Manuscript Package v1。
3. 冻结 Publishing Brief：项目与频道引用、地区、目标语言、正式母稿版本与哈希、故事事实、核心冲突、高潮、结局、观众承诺、标题方向、封面任务和只读频道学习快照。
4. 目标发布频道可以保存为非敏感档案引用；参考频道绝不能冒充目标发布频道。本阶段不要求 OAuth 可用，也不读取 Token。

## 标题与元数据

- 生成多个目标语言标题候选并附中文翻译，记录事实依据、承诺兑现、观众适配、点击理由和相似度风险。
- 审核模式由用户确认唯一标题；自动模式只有事实、相似度和当前项目授权门通过后才可选定一个。正式包只能有一个标题。
- 生成目标语言简介正文，前两行先交代反常冲突、好奇缺口与观看回报。
- 生成 8～12 个 Hashtags，分为故事事实、题材／叙事机制与经证据支持的当前热词。正文未涉及的 IP、人名或事件不得蹭词；默认不生成后台 Tags。

## 封面与 CTR 联评

1. 先冻结 `thumbnailProvider`：真实 `providerId`、`interfaceVersion`、`integrationMode`（`built-in|plugin|user-provided|fixture`）和 `status`（`available|unavailable`）；不可用时同时保存清楚原因，不得假称供应商可用。
2. 再锁定 16:9 封面策略：主体、关系、冲突、构图、表情、目标语言短文案、安全区和移动端可读性。
3. 图片供应商可用时生成恰好 5 个构图实质不同的候选并逐张检查文字、事实、题材和点击潜力；不可用时仍保存恰好 5 个有明确差异的 `prompt_only` 候选，绝不能把提示词或占位图称为真实封面。
4. 真实封面必须存在于包内、可读取、实际为 16:9，并记录文件大小与 SHA-256。测试 PNG fixture 只可在测试模式使用，`integrationMode` 必须为 `fixture`，并明确标注 synthetic fixture，不得冒充线上生成结果。
5. 从合格候选中选择唯一正式封面，保存候选和未入选原因；执行唯一标题与唯一封面的 CTR 联评，核对最大钩子是否被视觉化、短文案是否准确互补、移动端是否易懂以及正文是否兑现承诺。

## 联合确认与冻结

1. 一次展示唯一标题及中文翻译、唯一封面或明确 `prompt_only` 状态、简介、8～12 个 Hashtags、CTR 结论、正文依据、目标频道引用和全部来源版本。
2. 审核模式等待用户明确确认；自动模式仅在事实、文字、图片和 CTR 硬门全部通过且项目已授权例行自动确认时锁定。
3. 调用 `content_publishing_finalize`，提交发布简报、标题选择、简介与 Hashtags、`thumbnailProvider`、封面策略／恰好 5 个候选／选择、CTR 联评、变更记录、来源锁和确认记录。
4. 只有工具返回确认状态且 `content_integrity_check` 通过时才称为 Publishing Asset Package v1 已冻结。`prompt_only` 可以作为明确的待补资产结果；若契约要求真实封面，则必须保持未就绪，不能伪报 `PUBLISHING_ASSETS_READY`。
5. 需要检查能否进入生产时只调用只读 `content_handoff_check`。未确认、坏哈希、标签数量错误、封面比例错误或版本错配均不得移交；即使检查通过，本 Skill 也只报告“已具备后续条件”，不调用制作中心。

## 修改与永久边界

- 修改标题、简介、Hashtags 或封面只建立新的发布素材版本，不修改母稿版本或哈希。
- 只读取频道学习快照；一次性修改只写项目变更记录，不调用长期学习写回。
- 不调用新漫剧工坊、控制中心生产、Google／YouTube 授权、上传 API、发布回执或 Analytics。
