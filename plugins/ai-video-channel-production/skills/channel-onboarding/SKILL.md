---
name: channel-onboarding
description: 通过本地安全工具读取 YouTube 发布中心的真实频道，分两阶段建立或重新绑定 AI 视频频道资料库，并处理频道生产预设、本次覆盖、备份、恢复和迁移。用户说“建立频道资料库”“绑定发布频道”“进入已有频道”“修改频道默认值”“备份频道”或“迁移频道”时使用；不得接收凭据、制造虚拟频道或跨任务混用频道。
---

# 频道建库与绑定

## 先检查能力

1. 调用 `system_capabilities`。
2. 确认本地工具协议主版本、数据库 Schema 和频道契约主版本兼容。
3. 显示 `storage.userDataRoot`，明确所有频道资料、用户审核文档、音频、图片、视频、生产任务和备份都保存在该用户数据根目录；程序更新不得改变或清空它。
4. 把发布频道接口、音色目录、资料库和备份能力分别显示为“正常、需要处理、当前不可用”。
5. 只阻塞依赖故障的步骤；发布授权异常不得阻止读取已有本地资料。

## 首次建库阶段 A

1. 调用 `publisher_list_channels`，只使用返回的真实发布频道身份。
2. 没有可用频道时，引导用户前往 YouTube 发布中心添加或重新授权频道，然后停止；不要创建虚拟频道。
3. 只有一个频道时仍显示频道序号、名称与真实频道 ID 尾部并要求确认；多个频道时显示编号卡，不按语言代选。
4. 第一张确认卡只询问目标地区和输出语言，不询问配音、篇幅、集数、制作方式或上传策略。
5. 用户确认后调用 `channel_onboarding_start`，同时传入当前 Codex `taskId`、唯一频道选择器、地区和语言。
6. 保留返回的 `channelProfileId` 与 `bindingProof` 供当前任务后续写入校验；不要向用户重复展示校验值。

## 首次建库阶段 B

1. 调用 `system_voice_catalog`，只展示已安装的预扫描真实引擎和音色；不要启动工坊扫描或手写不存在的音色 ID。
2. 音色目录不可用时，引导运行安装修复并停止建库写入。
3. 第二张确认卡只确认默认配音、`auto_by_topic` 篇幅范围、`auto_by_topic` 集数范围和制作方式。
4. 把视频生成、上传策略等可选字段保留为安全默认值；首次建库不要求自动上传授权。
5. 用户确认后调用 `channel_onboarding_complete`。成功结果必须同时满足 `READY`、存在 Channel Profile、存在 Production Profile 和完整性检查通过。
6. 创建失败时显示结构化错误和可恢复动作，不把半成品报告为成功。

## 重新绑定与日常使用

- 新任务先调用 `channel_list`。只有一个 READY 频道时仍显示确认卡；多个频道时让用户明确选择。
- 调用 `channel_bind_task` 将当前任务绑定一个频道。一个任务已经绑定其他频道时，要求新建任务，不调用改绑或删除。
- 调用 `channel_get` 读取频道档案与活动生产预设。
- 仅本次修改调用 `channel_resolve_production` 并传 `overrides`；确认返回 `persistedDefaultsChanged=false`。
- 只有用户明确确认“以后本频道都这样”时才调用 `channel_update_defaults`，并传 `confirmation={"confirmed":true,"scope":"channel_default"}`。预设必须生成新版本，不改变已冻结项目。

## 备份、恢复与迁移

- 备份前调用 `channel_integrity_check`，通过后使用当前任务的三项绑定值调用 `channel_backup`。
- 导出使用当前任务的三项绑定值调用 `channel_export`；导入同时传当前 `taskId` 并默认使用 `conflictMode=reject`，成功后保存新绑定校验值。不得覆盖、复制或换皮同一真实 YouTube 频道身份。
- 恢复先调用 `channel_restore` 的 `verify_only` 模式。替换恢复会改动用户数据，必须在当前对话取得明确确认后才使用 `replace`，并传当前任务绑定值和固定确认值；工具会先创建恢复前备份并在失败时回滚。
- 不删除备份、不删除频道资料库、不自动归档。
- 首次安装由统一安装入口单独选择“程序目录”和“用户数据目录”，优先把用户数据放在空间充足的非系统盘。已有安装必须沿用已绑定的数据目录；迁移只能通过备份、校验和恢复流程完成，不能在更新时静默改绑。

## 安全边界

- 不询问、接收、保存或回显 OAuth Token、Client Secret、Cookie、验证码、密码或私钥。
- 不把对标频道、视频频道链接或用户输入的频道 ID 写入目标发布身份链。
- 所有写入同时携带当前 `taskId`、`channelProfileId` 和 `bindingProof`。
- 工具返回 `MIGRATION_REQUIRED`、`LIBRARY_NEEDS_REPAIR` 或身份冲突时停止写入并显示修复动作。
- 不调用资料采集、选题、文稿、工坊、真实上传或 Analytics；这些属于后续阶段。
