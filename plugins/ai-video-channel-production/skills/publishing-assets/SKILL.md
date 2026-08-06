---
name: publishing-assets
description: 在标题、简介和封面三个独立 Skills 都已交付并确认后，只负责校验它们与同一 Manuscript Package v1 的版本、事实和哈希绑定，汇总为 Publishing Asset Package v1。用户说“汇总发布素材”“检查标题简介封面是否齐全”“生成发布素材包”时使用；不自行生成标题、简介、Hashtags 或封面，任一扩展尚未开发或缺少结果时明确返回 PLANNED_UNAVAILABLE。
---

# 发布素材汇总

本 Skill 是汇总器，不是标题、简介或封面生成器。三个资产必须由未来独立 Skills 提供：

- `content-title` → `title-asset-v1`；
- `content-description` → `description-asset-v1`；
- `content-thumbnail` → `thumbnail-asset-v1`。

## 进入

1. 调用 `content_capabilities` 和 `content_project_get`，只接收 `SCRIPT_READY`、质量门通过且哈希有效的 Manuscript Package v1。
2. 读取 `assets/content-extension-slots.json`。任一槽位仍为 `PLANNED_UNAVAILABLE` 时，显示缺失的 Skill 和稳定接口名称，然后停止；不得临时生成对应资产。
3. 三个 Skill 已可用时，分别读取已确认的资产包，并验证它们绑定同一项目、频道、目标语言、母稿版本与 SHA-256。

## 汇总质量门

- 标题只能有一个正式选择，事实承诺必须被正式文本兑现；
- 简介和 Hashtags 必须来自 `description-asset-v1`，不得在本 Skill 补写；
- 封面必须来自 `thumbnail-asset-v1`，为真实可读的 16:9 文件并带大小与 SHA-256；
- 任一资产未确认、版本错配、坏哈希、事实越界或仍是提示词／占位图时停止；
- 参考频道身份不得冒充目标发布频道，不读取 Token、OAuth 或浏览器登录态。

## 冻结

1. 展示唯一标题、简介与 Hashtags、唯一封面、三个资产包版本、母稿版本和目标频道引用。
2. 审核模式等待联合确认；已有明确自动确认授权时仍须先通过全部硬门。
3. 调用 `content_publishing_finalize`，只提交三个独立资产包的已确认结果和来源锁，不新增或改写内容。
4. 调用 `content_integrity_check`；只有包完整时才称为 `PUBLISHING_ASSETS_READY`。
5. 调用只读 `content_handoff_check` 检查是否具备制作条件；不在本 Skill 启动工坊。

## 边界

- 不生成、改写或重选标题、简介、Hashtags、封面和正式母稿。
- 不调用工坊、Google／YouTube 授权、上传、发布回执、Analytics 或长期频道学习。
- 当前三个未来 Skill 尚未正式实现时，正常结果就是 `PLANNED_UNAVAILABLE`，不得用旧流程回退。
