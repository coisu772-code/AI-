# 发布中心本地工具协议

## 适用范围

使用以下八个工具连接 Production Result Package v1、Publishing Asset Package v1、隔离导入链和经 G6 批准的正式发布中心交接。以安装版本暴露的 JSON Schema 为参数事实源；遇到缺少字段或协议版本不兼容时停止，不猜测参数。

协议标识为 Publisher Local Tool Protocol v1；带最终中文验收卡的发布包版本为 v2.1.0；Upload Intent 与 Publication Receipt 均为 v1。版本不兼容时失败关闭。

所有 MCP 写操作必须显式设置 `networkExecution=false`，不得自行发起 OAuth 或 YouTube API。`handoff_publish_package_v2` 只在本地正式数据库创建或更新任务；真实网络上传归已经持有 OAuth 的 YouTube 发布中心桌面程序所有。

平台字段、媒体和缩略图限制只读取发布中心返回的版本化 YouTube constraints catalog，并在验证结果中保留目录版本与核验日期。不要在 Skill 中写死可能变化的限制；目录缺失、失效或版本不兼容时进入人工检查。

## 工具表面

| 工具 | 语义输入 | 成功输出 | 不变量 |
| --- | --- | --- | --- |
| `assemble_publish_package_v2` | Production Result Package v1、Publishing Asset Package v1、明确频道档案引用、`networkExecution=false` | `publishIntentId`、包路径、包哈希、幂等结果、`PACKAGE_READY` 或验证失败 | 先建 `.creating`；完整成功后才原子形成 `.ready`；相同发布组合幂等复用 |
| `validate_publish_package_v2` | 一个 `.ready` v2 包、当前约束目录版本、`networkExecution=false` | 验证报告、错误／警告、可导入结论 | 独立重验，不信任组装报告；不得修改包或导入 |
| `import_publish_package_v2` | 已通过验证的 `.ready` 包、隔离发布中心根、`networkExecution=false` | 导入任务、生命周期结果、本地发布状态、下一动作 | 只认领 `.ready`；执行 `.importing → .imported/.failed`；不得连接正式 DB／inbox 或 YouTube |
| `get_publication_status` | `publishIntentId` | 当前本地或真实状态、更新时间、video ID 是否存在、下一动作 | 严格只读；不得推进、重试或认领 |
| `get_publication_receipt` | `publishIntentId` | 真实 Publication Receipt v1，或明确 `not_found`／`not_available` | 没有真实 `youtubeVideoId` 时不得返回正式回执 |
| `handoff_publish_package_v2` | `.ready` 包、G6 卡 SHA-256、当前任务 G6 确认或当前项目自动上传授权、`networkExecution=false` | 正式任务、本地 READY 资格、是否可由桌面程序 AUTO 上传 | 只接受 AUTO；授权必须绑定当前项目与不可变验收卡；不直接上传 |
| `get_live_publication_status` | 正式 `publishIntentId` | 正式发布中心实时本地状态 | 严格只读，不触发上传或重试 |
| `get_live_publication_receipt` | 正式 `publishIntentId` | 真实 YouTube video ID／URL 或 `not_available` | 没有真实 video ID 不得生成回执 |

## 发布包 v2

`<publish_intent_id>.creating` 与最终 `.ready` 只允许以下固定十一类文件；缩略图和字幕各选择一种允许扩展名：

```text
manifest.json
FINAL_CHINESE_REVIEW_CARD.md
final_chinese_review_card.json
metadata.json
upload_task.json
validation.json
production_binding.json
upload_status.json
final.mp4
thumbnail.png|jpg
subtitles.srt|vtt
```

拒绝绝对路径、`..`、符号链接、包外目标、未声明文件、坏哈希、项目／版本错配和敏感字段。`production_binding.json` 必须绑定结果包、最终视频、字幕与技术报告哈希，所有文件引用使用包内相对路径。

`publish_intent_id` 表示一次不可覆盖的发布意图。仅当项目、Production Result 版本／哈希、Publishing Asset 版本／哈希和频道档案组合完全一致时幂等复用；任一上游修订、成片替换或换频道都生成新意图。

## 元数据与频道

`metadata.json` 分别保存：

- `description_body`：不含 Hashtags 的目标语言简介正文；
- `hashtags`：8–12 个公开 Hashtags；
- `description_for_youtube`：正文、空行和 Hashtags 的可上传组合；
- 后台 Tags：默认空或无，不得用 `tags` 冒充 Hashtags。

频道身份只来自只读 CLI 的九字段非敏感输出：`publisherProfileId`、`channelSerial`、`youtubeChannelId`、`channelName`、`enabled`、`authorizationStatus`、`defaultPrivacy`、`timezone`、`uploadPolicy`。`publisher_list_channels` 只可把其中三个显示字段规范为 `displayName`、`privacyStatus`、`timeZone`，不得补造其他频道事实。按 `channelSerial` 唯一匹配，并核对预期不可变 `youtubeChannelId`。缺失、重复、停用或不匹配时失败；不得按语言、地区、题材或标题猜频道。

## 状态与回执

本阶段允许结束在：

- `PACKAGE_READY`：发布包已就绪或已本地导入；
- `WAITING_REVIEW`：等待人工确认或计划／额度问题处理；
- `READY_TO_UPLOAD`：验证及授权资格齐全，但尚未上传。

以下状态只能来自未来真实网络执行及持久化证据：`UPLOADING`、`VIDEO_CREATED_PRIVATE`、`UPLOADED_PRIVATE`、`SCHEDULED`、`PUBLISHED`。`.ready`、`.imported`、Upload Intent v1 或 `READY_TO_UPLOAD` 均不等于已上传。

没有真实、非空 `youtubeVideoId` 时，禁止进入任何已上传状态，禁止生成 Publication Receipt v1。合成测试必须标记 `synthetic=true`，不得生成可被误认作真实的 video ID、URL 或回执。

## 策略与审批门

- `DO_NOT_UPLOAD`：本地保存／导入，停在 `PACKAGE_READY`。
- `REQUIRE_REVIEW`：生成不可变 Upload Intent v1 与最终中文验收卡，停在 `WAITING_REVIEW / FINAL_CHINESE_REVIEW_CONFIRMATION_REQUIRED`。
- `AUTO`：同时验证工作区、频道、当前发布意图授权，以及来源为 `current_task_explicit`、范围为 `current_task_and_project_only` 的项目自动上传授权。四项授权与项目、频道、隐私状态和版本全部一致时进入 `READY_TO_UPLOAD`；最终中文验收卡状态为 `AUTO_AUTHORIZED`，展示后直接交接，不再重复确认。否则停在 `WAITING_REVIEW`。

所有视频未来必须先以 private 创建；先持久化真实 video ID，再分别恢复封面、字幕、处理和最终可见性。取得 video ID 后不得再次调用 `videos.insert`。删除本地任务或包不得触发远端删除。

## 错误处理

至少将下列结果视为硬停止：

- `.creating` 半包、路径逃逸、符号链接、未声明文件、坏哈希或协议错配；
- 坏 MP4、字幕越界、字幕语言错、封面或元数据不合格；
- Hashtags 数量错误、后台 Tags 冒充 Hashtags；
- 频道缺失／重复／停用／ID 不匹配；
- AUTO 缺授权门、排期过期、无效时区、额度或并发已满；
- 伪 video ID、假 receipt、上传／OAuth／远端修改／删除越权。

对 `FINAL_CHINESE_REVIEW_CONFIRMATION_REQUIRED` 先展示 G6 最终中文验收卡，不重试为网络执行。若当前项目没有有效自动上传授权，用户在当前任务确认卡片内容并明确要求真实上传后才可交接；若授权有效则本卡只展示。OAuth 和实际上传仍由真实发布中心处理。
