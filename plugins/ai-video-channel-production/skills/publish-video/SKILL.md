---
name: publish-video
description: 从 VIDEO_READY Production Result Package v1 与已确认 Publishing Asset Package v1 安全组装、校验并隔离导入发布包 v2，显示人工上传确认卡，并只读查询上传状态与真实发布回执。用户说“准备上传成片”“导入发布中心”“查看上传状态”“查看发布进度”“查看回执”或询问是否已经上传／发布时使用；不得替代 Google／YouTube OAuth、用户授权或真实上传确认。
---

# 发布中心

先读取 [逐阶段确认契约](../channel-production/references/manual-stage-confirmations.md)。只处理发布包与发布资格。先区分“本地包就绪”“等待人工确认”“具备上传资格”和“真实远端状态”，不要把 `.ready`、导入成功或 `READY_TO_UPLOAD` 说成已经上传。

## 准备上传成片

1. 阅读 [工具协议](references/tool-protocol.md)，再执行任何组装或导入动作。
2. 调用 `publisher_list_channels` 读取发布中心的九字段非敏感频道档案。只按明确 `channelSerial` 与预期不可变 `youtubeChannelId` 匹配；缺失、重复、停用或不匹配时停止。不得按语言、地区、标题或题材猜频道。
3. 确认输入分别为 `VIDEO_READY` Production Result Package v1 与 `PUBLISHING_ASSETS_READY` Publishing Asset Package v1，并且项目、版本、哈希、目标语言和频道引用一致。
4. 调用 `assemble_publish_package_v2`，始终传递 `networkExecution=false`。让工具按发布意图幂等组装 `<publish_intent_id>.creating`，并只在全部校验成功后原子形成 `.ready`。
5. 调用 `validate_publish_package_v2` 独立重验 v2 文件、绑定、路径、哈希、媒体、字幕、元数据、频道、计划和额度。不要导入 `.creating`、含符号链接、未声明文件或任何验证失败的包。
6. 调用 `import_publish_package_v2` 让发布中心在隔离 inbox／数据库中执行 `.ready → .importing → .imported/.failed`。始终保持 `networkExecution=false`；不得触发 OAuth、YouTube API 或正式桌面程序。
7. 读取工具返回的 `final_chinese_review_card_path`，向用户显示可点击的 `FINAL_CHINESE_REVIEW_CARD.md`。这张 G6 卡必须先集中显示中文故事、标题、简介、标签含义、封面文案、配音、频道、隐私状态和上传策略，再显示目标语言正式标题、简介、Hashtags 与封面文案。
8. 未取得当前任务的 G6 最终中文验收确认前，任何会上传的视频都必须停在 `WAITING_REVIEW / FINAL_CHINESE_REVIEW_CONFIRMATION_REQUIRED`；不得因频道预设、旧项目或既有 AUTO 授权跳过本次内容验收。

## 执行三种策略

- `DO_NOT_UPLOAD`：只保存并导入本地任务，停在 `PACKAGE_READY`；绝不调用 YouTube。
- `REQUIRE_REVIEW`：验证通过后显示最终中文验收卡并生成不可变 Upload Intent v1，停在 `WAITING_REVIEW`。真实上传、OAuth 或授权仍必须由用户明确确认。
- `AUTO`：继续验证工作区、频道和当前发布意图授权及其时间／版本，但本次 G6 最终中文验收未确认前仍停在 `WAITING_REVIEW`；不能直接跳到 `READY_TO_UPLOAD`。

计划时间已过、时区无效、槽位冲突、每日额度已满或并发已满时停在 `WAITING_REVIEW`，不要擅自改时间、隐私或频道。

## 查看状态与回执

1. 调用 `get_publication_status` 只读查询指定 `publishIntentId`。查询不得认领包、推进状态、重试任务或改写任何记录。
2. 原样区分 `PACKAGE_READY`、`WAITING_REVIEW`、`READY_TO_UPLOAD` 与真实 `UPLOADING`、`VIDEO_CREATED_PRIVATE`、`UPLOADED_PRIVATE`、`SCHEDULED`、`PUBLISHED`。
3. 用户明确要求查看回执时，在状态查询后调用 `get_publication_receipt`。没有真实 video ID 时只接受工具返回明确的 `not_found`／`not_available`，并答复“Publication Receipt v1 不存在”；不要生成占位回执、合成 ID 或假链接。
4. 只有回执包含非空真实 `youtubeVideoId` 时，才核对发布意图、项目、频道、上游版本、真实 video ID／URL、封面、字幕、处理、可见性和排期状态，并据实说明“已上传”或“已发布”。

## 安全边界

- 对 Google／YouTube OAuth、真实视频上传、远端元数据修改、远端删除和任何授权持久化先向用户说明动作并等待明确确认。
- 不保存或回显 Token、客户端密钥、API Key、浏览器数据或发布中心数据库内容。
- 不把真实频道 ID、频道名或非脱敏频道清单写入仓库夹具、文档或报告。
- 不覆盖发布包；上游修订、替换成片或换频道时建立新的发布意图。
- 删除本地任务或包不等于删除远端视频；绝不隐式执行远端删除。
- 标题、简介、Hashtags 或封面修改只失效并重组发布包，不使已通过的 MP4 失效。
- 默认且强制保持 `networkExecution=false`。本 Skill 在 Stage6 只证明本地发布资格，不执行真实发布。

运行安装检查时执行 `scripts/check_publisher_install.py`。默认检查安装结构与本地工具列表；使用 `--static-only` 只检查文件结构。检查器只使用临时数据目录并强制关闭网络执行。
