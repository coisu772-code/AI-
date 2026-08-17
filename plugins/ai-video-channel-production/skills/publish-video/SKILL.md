---
name: publish-video
description: 从 VIDEO_READY Production Result Package v1 与已确认 Publishing Asset Package v1 安全组装、校验并隔离导入发布包 v2，显示最终中文验收卡；当前项目已取得明确自动上传授权时不重复确认，否则等待本次确认，再把 AUTO 包正式交接给 YouTube 发布中心并只读查询状态与回执。不得继承旧任务授权，也不得替代 Google／YouTube OAuth。
---

# 发布中心

先读取 [逐阶段确认契约](../channel-production/references/manual-stage-confirmations.md)。只处理发布包与发布资格。先区分“本地包就绪”“等待人工确认”“具备上传资格”和“真实远端状态”，不要把 `.ready`、导入成功或 `READY_TO_UPLOAD` 说成已经上传。

## 准备上传成片

1. 阅读 [工具协议](references/tool-protocol.md)，再执行任何组装或导入动作。
2. 调用 `publisher_list_channels` 读取发布中心的九字段非敏感频道档案。只按明确 `channelSerial` 与预期不可变 `youtubeChannelId` 匹配；缺失、重复、停用或不匹配时停止。不得按语言、地区、标题或题材猜频道。
3. 确认输入分别为 `VIDEO_READY` Production Result Package v1 与 `PUBLISHING_ASSETS_READY` Publishing Asset Package v1，并且项目、版本、哈希、目标语言和频道引用一致。正式发布必须同时验证生产来源为真实工坊、`placeholder=false`、媒体完整性为 `PASSED`，且结果包中的完整性摘要与技术报告完全一致；合成测试夹具和占位产物不得进入正式发布路线。
4. 调用 `assemble_publish_package_v2`，始终传递 `networkExecution=false`。让工具按发布意图幂等组装 `<publish_intent_id>.creating`，并只在全部校验成功后原子形成 `.ready`。
5. 调用 `validate_publish_package_v2` 独立重验 v2 文件、绑定、路径、哈希、媒体、字幕、元数据、频道、计划和额度。不要导入 `.creating`、含符号链接、未声明文件或任何验证失败的包。
6. 正式项目调用 `import_publish_package_v2` 并传 `handoffMode=formal`，把源包无损复制到正式发布中心队列；`handoffMode=isolated` 只允许合成夹具和安装验收。始终保持 `networkExecution=false`，不得由 Codex 直接调用 OAuth 或 YouTube API。
7. 读取工具返回的 `final_chinese_review_card_path`，向用户显示可点击的 `FINAL_CHINESE_REVIEW_CARD.md`。G6 卡必须中文优先，并同时显示成片来源、时长、分镜总数／唯一数／重复率、抽样帧结果、技术报告 SHA-256 和占位执行器状态。
8. 检查发布包内的项目级自动上传授权。授权必须来自当前任务用户原话，且绑定当前项目、频道、隐私状态、AUTO 策略和版本；有效时验收卡显示 `AUTO_AUTHORIZED` 并继续交接，不重复提问。没有该授权时停在 `WAITING_REVIEW / FINAL_CHINESE_REVIEW_CONFIRMATION_REQUIRED`。频道预设、旧项目或其他任务授权一律无效。
9. 显示项目、发布意图、频道序号、策略、隐私、计划、视频参数、标题、简介、Hashtags、封面、字幕、验证结论、最终中文验收状态、正式发布中心状态和下一动作。

## 执行三种策略

- `DO_NOT_UPLOAD`：只保存并导入本地任务，停在 `PACKAGE_READY`；绝不调用 YouTube。
- `REQUIRE_REVIEW`：验证通过后显示最终中文验收卡并生成不可变 Upload Intent v1，停在 `WAITING_REVIEW`。真实上传、OAuth 或授权仍必须由用户明确确认。
- `AUTO`：验证工作区、频道、当前发布意图和当前项目授权。项目授权有效时，最终中文验收卡只展示，调用 `handoff_publish_package_v2` 时以 `approvalSource=PROJECT_AUTO_UPLOAD_AUTHORIZATION` 传入授权引用、时间、版本、项目 ID、发布意图 ID 和不可变验收卡 SHA-256；无需再次要求用户确认。授权缺失或任一绑定变化时停在 `WAITING_REVIEW`，等待当前任务确认。该工具只把正式发布中心任务推进到本地 `READY`，由已持有 OAuth 的桌面程序执行上传。

正式交接后立即调用 `get_live_publication_status`。如果仍是 `READY_TO_UPLOAD`，说明发布中心的全局 AUTO 开关、频道 AUTO 开关、OAuth、排期、额度或桌面服务尚有一项未实际运行，应据实显示阻断或等待，不得重复交接或反复启动发布中心。只有状态进入真实上传阶段后才继续只读跟踪。

计划时间已过、时区无效、槽位冲突、每日额度已满或并发已满时停在 `WAITING_REVIEW`，不要擅自改时间、隐私或频道。

## 查看状态与回执

1. 隔离验收阶段调用 `get_publication_status`；完成正式交接后调用 `get_live_publication_status`。两者都只读查询指定 `publishIntentId`，不得认领包、推进状态、重试任务或改写任何记录。
2. 原样区分 `PACKAGE_READY`、`WAITING_REVIEW`、`READY_TO_UPLOAD` 与真实 `UPLOADING`、`VIDEO_CREATED_PRIVATE`、`UPLOADED_PRIVATE`、`SCHEDULED`、`PUBLISHED`。
3. 用户明确要求查看回执时，隔离阶段调用 `get_publication_receipt`，正式交接后调用 `get_live_publication_receipt`。没有真实 video ID 时只接受工具返回明确的 `not_found`／`not_available`，并答复“Publication Receipt v1 不存在”；不要生成占位回执、合成 ID 或假链接。
4. 只有回执包含非空真实 `youtubeVideoId` 时，才核对发布意图、项目、频道、上游版本、真实 video ID／URL、封面、字幕、处理、可见性和排期状态，并据实说明“已上传”或“已发布”。

## 安全边界

- Google／YouTube OAuth、远端元数据修改和远端删除仍需独立确认。真实上传可由当前项目在创作／制作阶段明确记录的自动上传授权放行，不得重复询问；未记录时必须在 G6 后取得确认。
- 不保存或回显 Token、客户端密钥、API Key、浏览器数据或发布中心数据库内容。
- 不把真实频道 ID、频道名或非脱敏频道清单写入仓库夹具、文档或报告。
- 不覆盖发布包；上游修订、替换成片或换频道时建立新的发布意图。
- 删除本地任务或包不等于删除远端视频；绝不隐式执行远端删除。
- 标题、简介、Hashtags 或封面修改只失效并重组发布包，不使已通过的 MP4 失效。
- MCP 工具默认且强制保持 `networkExecution=false`，不会直接连接 YouTube。真实上传只能由正式 YouTube 发布中心在既有 OAuth、全局 AUTO、频道 AUTO、当前发布意图，以及“项目级自动上传授权或本次 G6 确认”有效后执行。

运行安装检查时执行 `scripts/check_publisher_install.py`。默认检查安装结构与本地工具列表；使用 `--static-only` 只检查文件结构。检查器只使用临时数据目录并强制关闭网络执行。
