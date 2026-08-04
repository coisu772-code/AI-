# 本地工具服务与发布中心只读接口 v1

## 1. 边界

阶段2正式读取 YouTube 发布中心已经冻结的只读命令接口，不另定义或要求发布中心实现新的 stdin 协议。OAuth、Client Secret、Cookie、验证码、密码和系统安全存储内容必须留在发布中心进程内。

本地工具服务当前候选版本为 `0.6.0-dev.1`，内部 MCP／工具协议仍为向后兼容的 `1.0.0`。发布中心正式接口版本仍为：

```text
youtube-publisher-center/channel-list/v1
```

发布中心原始契约与安全边界由其源码中的 `docs/channel-list-api-v1.md` 和 `internal/channelapi/schemas/channel-list-v1.schema.json` 定义；本地工具服务只做字段映射、超时、错误适配和第二层敏感信息检查。

## 2. 正式发布中心命令

标准调用：

```powershell
youtube-publisher-channel-list.exe --api-version v1
```

本地工具从以下任一非敏感配置读取程序位置，优先级从高到低：

1. `AIVCP_PUBLISHER_CHANNEL_LIST_COMMAND_JSON`：包含程序和可选固定参数的 JSON 字符串数组。
2. `AIVCP_PUBLISHER_CHANNEL_LIST_EXE`：只包含程序绝对路径。
3. `%LOCALAPPDATA%\AIVCP-Config\publisher-interface.json`：安装器拥有的非敏感发现文件；自定义程序根不改变此稳定发现位置。
4. 阶段1保留的 `AIVCP_PUBLISHER_COMMAND_JSON` 扩展提供方，仅供向后兼容，不是阶段2正式路径。

发现文件格式：

```json
{
  "schemaVersion": "1.0.0",
  "apiVersion": "youtube-publisher-center/channel-list/v1",
  "command": ["C:\\Program Files\\Publisher Center\\youtube-publisher-channel-list.exe"]
}
```

默认超时 8 秒，可通过 `AIVCP_PUBLISHER_TIMEOUT_SECONDS` 调整到 0.1–60 秒。调用使用 `shell=false`，不写 stdin，不启动 Wails、OAuth、Token 刷新、上传队列或 YouTube API。

成功响应：

```json
{
  "apiVersion": "youtube-publisher-center/channel-list/v1",
  "status": "OK",
  "generatedAt": "2026-08-04T04:00:00Z",
  "channelCount": 1,
  "channels": [
    {
      "publisherProfileId": "publisher_profile_local_001",
      "channelSerial": "01",
      "youtubeChannelId": "UC...",
      "channelName": "频道名称",
      "enabled": true,
      "authorizationStatus": "ACTIVE",
      "defaultPrivacy": "private",
      "timezone": "Asia/Tokyo",
      "uploadPolicy": "REQUIRE_REVIEW"
    }
  ]
}
```

本地工具服务映射为：

| 发布中心 v1 | 本地工具字段 | 说明 |
| --- | --- | --- |
| `publisherProfileId` | `publisherProfileId` | 身份链第二层 |
| `channelSerial` | `channelSerial` | 用户可识别序号 |
| `youtubeChannelId` | `youtubeChannelId` | 真实目标频道 ID |
| `channelName` | `displayName` | 频道显示名称 |
| `enabled` | `enabled` | 发布中心启停状态 |
| `authorizationStatus` | `authorizationStatus` | 最后已知授权状态，不代表联网刷新 |
| `defaultPrivacy` | `privacyStatus` | 非敏感发布默认值 |
| `timezone` | `timeZone` | IANA 时区或 UTC |
| `uploadPolicy` | `uploadPolicy` | 只读默认值，不授予自动上传权限 |

适配器要求九字段精确白名单、`channelCount` 与数组长度一致，并再次检查三层发布身份分别唯一。任何额外字段、敏感字段或结构不一致都会整次拒绝。

## 3. 正式错误适配

发布中心 `status=ERROR` 时，本地工具保留其安全错误码、用户消息和 `retryable`，不把 stderr、数据库路径或堆栈传给 Codex。正式错误包括：

- `CHANNEL_API_ARGUMENT_INVALID`
- `CHANNEL_API_VERSION_UNSUPPORTED`
- `PUBLISHER_DATA_DIRECTORY_UNAVAILABLE`
- `PUBLISHER_DATABASE_PATH_INVALID`
- `PUBLISHER_DATABASE_NOT_FOUND`
- `PUBLISHER_DATABASE_OPEN_FAILED`
- `PUBLISHER_DATABASE_BUSY`
- `PUBLISHER_SCHEMA_INCOMPATIBLE`
- `PUBLISHER_CHANNEL_QUERY_FAILED`
- `PUBLISHER_CHANNEL_RECORD_INVALID`

程序超时、无法启动、响应过大、非 JSON、接口版本错误或敏感信息检查失败由本地工具转换为 `PUBLISHER_TIMEOUT`、`PUBLISHER_START_FAILED`、`PUBLISHER_RESPONSE_TOO_LARGE`、`PUBLISHER_RESPONSE_INVALID`、`PUBLISHER_PROTOCOL_MISMATCH` 或 `PUBLISHER_RESPONSE_UNSAFE`。

## 4. MCP 边界

插件通过 `.mcp.json` 启动 `mcp/start.ps1`，启动器依次使用：

1. 管理员配置的 `AIVCP_PYTHON`。
2. 安装器提供的本地 Python 运行时。
3. `uv run --no-project python` 开发回退。

MCP 使用逐行 JSON-RPC 2.0，支持 `initialize`、`ping`、`tools/list` 和 `tools/call`。单条消息上限 2 MiB，工具调用默认 60 秒。标准输出只用于协议响应。

阶段2工具继续开放：

- `system_capabilities`
- `system_voice_catalog`
- `publisher_list_channels`
- `channel_onboarding_start`
- `channel_onboarding_complete`
- `channel_list`
- `channel_get`
- `channel_bind_task`
- `channel_resolve_production`
- `channel_update_defaults`
- `channel_integrity_check`
- `channel_backup`
- `channel_export`
- `channel_import`
- `channel_restore`

阶段3在同一协议中追加以下工具，不改变阶段2工具名称和参数主结构：

- `source_library_capabilities`
- `source_add_prepare`
- `source_add_confirm`
- `source_job_get`
- `source_job_cancel`
- `source_job_resume`
- `source_search`
- `source_get`
- `source_update_prepare`
- `source_integrity_check`

`source_add_prepare` 只建立 `WAITING_CONFIRMATION` 任务并返回统一确认卡，不下载或分析内容；只有带相同 `acquisitionJobId`、`planHash`、频道绑定校验值和明确确认的 `source_add_confirm` 才会执行。任务逐项持久化，完成项在取消或恢复时不会重做。

资料写入每频道独立 `channel.db` 和 `sources/`。平台 ID、规范 URL 和内容 SHA-256 用于去重；来源变化建立新的语义版本，已引用版本不原地覆盖。`Source Package v1` 继续使用冻结的 `schemaVersion=1.0.0`，详细元数据、原始内容、标准化内容和采集报告作为带哈希的包内资产保存。

阶段4继续追加以下工具，不改变阶段2/3工具名称和参数主结构：

- `content_capabilities`
- `content_project_start`
- `content_topic_checkpoint`
- `content_topic_finalize`
- `content_manuscript_finalize`
- `content_publishing_finalize`
- `content_project_get`
- `content_integrity_check`
- `content_handoff_check`

阶段4工具只生成和校验 Topic、Manuscript 与 Publishing Asset 三类版本化内容包。`content_handoff_check` 是只读资格检查；它不会调用制作中心、工坊、发布中心、OAuth、上传或 Analytics。趋势、单作品、多作品、拆书和仿写扩展未安装时返回 `CONTENT_EXTENSION_UNAVAILABLE`，不根据标题或元数据伪造分析。

阶段5在同一 `1.0.0` 本地工具协议中追加 11 个工具：

- `production_capabilities`
- `production_package_assemble`
- `production_task_start`
- `production_task_get`
- `production_task_run`
- `production_task_pause`
- `production_task_resume`
- `production_task_retry`
- `production_task_invalidate`
- `production_jianying_export_ingest`
- `production_result_validate`

除 `production_capabilities` 外，写入调用继续要求任务、频道和 binding proof。`production_task_get` 与 `production_capabilities` 只读；不得因查询进度改变任务。Production Package 必须为 `2.1`，非合成任务必须配置实际工坊 2.1 适配桥。桥只允许健康检查、能力读取、隔离导入、制作启动和只读状态，拒绝 `.ready`、发布、上传、OAuth、回执、Analytics 和长期学习相关命令。

合成 runner 只在 manifest 和 production config 同时明确标记 synthetic 时可用。它仍经过 Production Task、资产登记、FFmpeg／ffprobe 和结果包验证；返回值明确记录外部图片、视频和 TTS 服务未调用。

## 5. 数据与安全

- 默认数据根目录为 `%LOCALAPPDATA%\AI Video Channel Production Data`，程序根为 `%LOCALAPPDATA%\AIVCP`；隔离测试使用 `AIVCP_DATA_ROOT` 覆盖。旧长路径下的既有 data 不自动迁移、删除或覆盖。
- 每个写入调用同时校验 `taskId`、`channelProfileId` 和任务绑定校验值。
- 一个 `taskId` 只能绑定一个频道；同一真实 YouTube 频道 ID 在系统注册库中唯一。
- 新建和迁移导入都重新比对当前发布中心正式 v1 身份映射。
- 禁用或授权异常频道仍可建立和读取本地资料库；对应状态只阻塞后续真实发布，不冒充整个系统不可用。
- 测试频道夹具只有同时设置 `AIVCP_ALLOW_TEST_FIXTURES=1` 时才可使用，正式流程不接受虚拟频道。
- `uploadPolicy=AUTO` 只是发布中心当前默认值；阶段2建库明确拒绝以此获得真实自动上传权限。
- 阶段3采集不执行拆视频、拆书、仿写、选题、文稿、工坊、OAuth 或上传。
- 阶段4只读消费频道上下文、Source Package 和频道学习快照；拒绝长期学习写回，一次性修改只进入当前项目记录。
- 阶段4的 `READY_FOR_PRODUCTION` 只表示三个内容包已确认且完整，不构成制作、授权、上传或发布许可。
- 阶段5只到 `VIDEO_READY`。不得创建 `.ready` 发布包、Publish Intent 或发布队列，不得调用发布中心、OAuth、上传或长期频道学习写回。
- YouTube 无足够字幕且未配置可用本地转录时保存可核验元数据并标记 `BLOCKED`，要求用户补充本地媒体、字幕或文字；不得由标题、封面或简介编造正文。
- 网站适配器只执行版本化能力清单允许的公开读取；不得绕过登录、付费墙、DRM、验证码或访问限制。

## 6. 隔离联合测试

阶段2测试用临时 SQLite 数据库构造发布中心所需字段，再调用已经构建的正式：

```text
E:\YouTube视频自动上传\youtube-publisher-center\build\bin\youtube-publisher-channel-list.exe
```

测试显式传 `--database <临时文件>`，比较调用前后 SHA-256，证明正式 CLI 未修改数据库；不会读取默认用户数据库、OAuth 或真实频道。
