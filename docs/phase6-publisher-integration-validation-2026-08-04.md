# 阶段6“发布中心本地集成与安全发布门”验证报告（2026-08-04）

## 结论

阶段6本地发布包与发布中心隔离集成：**GO**。

本阶段把 Stage5 `VIDEO_READY` Production Result Package v1 与 Stage4 Publishing Asset Package v1 组装为 Publish Package v2，并在真实发布中心源码新增的独立验证器、导入器和隔离 CLI 中完成三市场离线重验与导入。三种策略均停在本地状态：`PACKAGE_READY`、`WAITING_REVIEW` 或仅表示资格的 `READY_TO_UPLOAD`。工具层始终强制 `networkExecution=false`。

本阶段没有发起 Google/YouTube OAuth，没有调用 YouTube API，没有上传或修改远端视频/元数据，没有获得真实 `youtube_video_id`，没有创建 Publication Receipt v1，没有写正式发布中心数据库或正式 inbox，没有覆盖正式 EXE，没有迁移用户数据，没有写长期学习规则，没有 push 或 Release。

## 基线、仓库与隔离边界

- 工作区：`E:\小说漫全自动化生产`
- 分发仓库：`E:\小说漫全自动化生产\distribution\novel-manga-production`
- 阶段5基线：`c53bd9f`
- 发布中心父仓库：`E:\YouTube视频自动上传`
- 发布中心阶段6前 HEAD：`10c5ef1`
- 发布中心阶段6精确本地提交：`70f9a8d13143050e045b1bfd61005742724d0fa6`
- 发布中心正式程序：`E:\YouTube视频自动上传\youtube-publisher-center\build\bin\YouTube 发布中心.exe`
- 正式程序当前 SHA-256：`a81ce665c4d7c7bb97e46760cdde5606e90982a692a901d552165125f3af86f9`；27,251,712 bytes；阶段6未覆盖该文件
- 只读频道 CLI：`E:\YouTube视频自动上传\youtube-publisher-center\build\bin\youtube-publisher-channel-list.exe`
- 只读频道 CLI SHA-256：`7c7bdbe38d961cfaa139995aa483e3391fb9f9261acdd6b7181c541d8398893f`

发布中心父仓库在阶段6前已有大量用户修改和未跟踪文件。阶段6只新增并提交 `youtube-publisher-center/internal/publishv2/` 与 `youtube-publisher-center/cmd/publish-package-v2/` 两棵目录，共 23 个文件；没有修改、暂存或提交任何既有脏文件。

## Publish Package v2 协议与幂等语义

每个 `<publish_intent_id>.creating` 固定包含九个文件：

1. `manifest.json`
2. `metadata.json`
3. `upload_task.json`
4. `validation.json`
5. `production_binding.json`
6. `upload_status.json`
7. `final.mp4`
8. `thumbnail.png` 或 `thumbnail.jpg`
9. `subtitles.srt` 或 `subtitles.vtt`

只有全部 Schema、文件声明、SHA-256、上游绑定、FFprobe、封面、字幕、元数据、频道和发布策略门通过，才在同卷内原子重命名为 `.ready`；`.creating` 永不导入。manifest 声明除自身外的八个文件，未声明文件、缺失文件、符号链接、绝对路径、`..`、哈希错配和项目/版本错配全部拒绝。

`publish_intent_id` 表示一次发布意图，其幂等键绑定：项目、Production Result 版本/哈希、Publishing Asset 版本/哈希和频道档案。相同组合复用；上游版本修订、替换 MP4、替换发布资产或换频道都会生成新意图，不覆盖旧包。标题、简介、Hashtags 或封面变化只令发布包失效；Production Result 与 MP4 不会因此失效。

`metadata.json` 分开保存 `description_body`、8–12 个 `hashtags` 与可直接发送的 `description_for_youtube`。后台 `tags` 默认为空，禁止用后台 tags 冒充公开 Hashtags。

`production_binding.json` 绑定 Production Result、视频、字幕和技术报告的版本及 SHA-256；包内路径一律为安全相对路径。

## 发布中心独立集成

发布中心新增的独立 Go 包与 CLI 实施二次重验，不信任分发侧 `validation.json`。验证范围包括：

- 六份 JSON Schema、完整协议、严格文件清单和全部哈希
- FFprobe 解码、MP4 容器、H.264、AAC、分辨率、时长及字幕末尾边界
- PNG/JPEG 封面、像素和文件大小
- 目标语言、字幕语言、标题、简介、Hashtags 与后台 tags 分离
- 频道序号唯一、启用状态、预期不可变 channel ID、隐私、时区和计划时间
- 每日上限、已用额度、并发上限、当前并发和排期冲突
- 三策略、三重 AUTO 授权版本与时间有效性
- 本地状态不得伪造 video ID、上传会话、YouTube URL 或 Publication Receipt

隔离导入生命周期为 `.ready → .importing → .imported/.failed`，只使用临时 SQLite 和临时 inbox。导入不会改写包内文件，因此导入后九文件哈希与源 `.ready` 完全一致。v1/v1.1 仅作只读兼容识别；新建只允许 v2。

独立 CLI 提供 `capabilities`、`validate`、`import`、`status`、`receipt`、`execute`。`execute` 不包含可用的联网实现：`networkExecution=true` 直接拒绝；即使本地状态为 `READY_TO_UPLOAD`，仍返回 `EXTERNAL_APPROVAL_REQUIRED`。

未来上传执行接口声明并以录制式 synthetic uploader 验证：先 private、优先持久化 video ID、上传会话可恢复、封面/字幕/处理/可见性分步恢复、已有 video ID 时不重复 insert。synthetic ID 只写专门的 `synthetic_video_id` 检查点，不会写入 `youtube_video_id`，也不会生成可用假回执。

## 三策略与状态矩阵

| 策略/条件 | 本地结果 | 外部动作 |
| --- | --- | --- |
| `DO_NOT_UPLOAD` | `PACKAGE_READY` | 本地保存/导入；绝不调用 YouTube |
| `REQUIRE_REVIEW` | `WAITING_REVIEW` + `HUMAN_CONFIRMATION_REQUIRED` | 生成不可变 Upload Intent v1 和人工确认卡；等待用户确认 |
| `AUTO` 缺任一三重授权 | `WAITING_REVIEW` + 对应缺门 | 不选择替代授权，不调用 YouTube |
| `AUTO` 排期过期/冲突、时区无效、额度满或并发满 | `WAITING_REVIEW` + 精确原因 | 不擅自改排期或频道 |
| `AUTO` 三重授权、版本/时间、排期和额度全部有效 | `READY_TO_UPLOAD` + `EXTERNAL_APPROVAL_REQUIRED` | 仅表示资格；阶段6仍不上传 |
| 任一本地包伪造 video ID/回执/上传会话 | 验证失败 | 不导入、不上传 |
| 没有真实 `youtube_video_id` 查询回执 | `PUBLICATION_RECEIPT_NOT_AVAILABLE` | 不生成假回执 |

上传后状态 `UPLOADING`、`VIDEO_CREATED_PRIVATE`、`UPLOADED_PRIVATE`、`SCHEDULED`、`PUBLISHED` 与上述本地三状态严格分离；阶段6没有进入任何上传后状态。

## 三市场最终离线证据

最终可复验发布包根目录：

`E:\小说漫全自动化生产\runtime\stage6-validation-synthetic\publish-package-v2-20260804-r3`

`summary.json` SHA-256：`c0acda4ebd6badae4e88058146d72f348eab631fb5c3cf4f268a52dc67fd549b`

YouTube constraints catalog：版本 `2026.08.04.1`，按最终 Windows 发布中心嵌入的 CRLF 精确字节重新锁定，SHA-256 `a57cf04014db7512b420771fe9f412e47a3bd69048b0d34fc9c4765085ad5e13`。旧 LF 字节 SHA-256 `28788480458f37ba86584b4c63e0ef998081ac521ecd9fd0b1724c2a6074b99a` 仅用于负向夹具，发布中心必须以 `CONSTRAINTS_CATALOG_MISMATCH` 拒绝。

| 市场 | publish_intent_id | 策略 | 状态/阻断 | Package content hash | Manifest SHA-256 |
| --- | --- | --- | --- | --- | --- |
| 日语/日本 | `pi_71c7edaa74dc5547d12c294811c0665f` | `DO_NOT_UPLOAD` | `PACKAGE_READY` | `922cbc383adb6e6cbf38c9cf61781a753c39fc651c51c850f41ea9ff53f560a2` | `90782b3c45700ac43968fb5524a86846729293d77db421d0cdd920ede81f7054` |
| 简中/中国 | `pi_44902dff6f293177738de0a3132116f3` | `REQUIRE_REVIEW` | `WAITING_REVIEW` / `HUMAN_CONFIRMATION_REQUIRED` | `fc4f5abfc20cffc2e7b10be8b232e5fb32850721363ffd120f20c1da057cf8a7` | `53573d782a0f025f92d3e5749374c35982183dd52be3257b58ec6753f045389d` |
| 英语/美国 | `pi_39324b34c36ed896db6d1a1a91f486fd` | `AUTO` | `WAITING_REVIEW` / 三重授权缺失 | `d4626a9f8bb808097fadd5eb2e9c6f46e56b5315816ba1200fda4b65d2c5621e` | `a19f8c53438e7f31986baafdf4fd0e68eca412c0887728987ec3001e43545653` |

三包的 MP4 SHA-256 均为 `ba4792b3cb95ffe24c26d17d279a5e6f4b379161c9196716fa407b1b652c6804`，54,741 bytes，640×360，3.000 秒，H.264 + AAC；这是明确标注的离线合成验收媒体，不代表正式发布分辨率或真实媒体模型输出。

字幕 SHA-256：日语 `860f54b5c6d3adafbd6cba670f8f457951d9c20cea7ab0061f76ae2538ef0aeb`，简中 `6c1a43d223a91ca4cb05ecebc12628277d8d4eec14dad26c6da6ce2a3ebb83a0`，英语 `5ca2289a121a4f06808c14a569406f3817a96c962f97b3dc54124fa7492a2f84`。封面 SHA-256 均为 `a667f692ef6074c3fa5f1de9af4188ae189dfb1bf390c3b2b0fb5f31d47eb7c7`。

所有包都记录 `network_execution=false`、`youtube_video_id=null`、`publication_receipt=null`、`oauth_executed=false`、`upload_executed=false`、`remote_mutation_executed=false`。

## 真实发布中心隔离导入证据

最终隔离 CLI：

`E:\小说漫全自动化生产\runtime\stage6-validation-synthetic\publisher-isolated\publish-package-v2-final.exe`

- SHA-256：`4c887c1aceb44c33b750e615f38c5e34f2ff83bf98c043f7b3bda03eb7d27ed0`
- 大小：12,129,280 bytes
- 内嵌 IANA 时区数据；正式发布中心 EXE 未覆盖

最终 r3 隔离导入根：

`E:\小说漫全自动化生产\runtime\stage6-validation-synthetic\publisher-import-r3-final-raw`

日/中/英三包均 `imported=1`、`failed=0`，完成 `.ready → .importing → .imported`。日语为 `PACKAGE_READY`；简中为 `WAITING_REVIEW`；英语为缺三重 AUTO 授权的 `WAITING_REVIEW`。三包导入后九文件与源包逐文件 SHA-256 完全一致。三包均无 video ID、无上传会话、无回执。简中和英语生成不可变 Upload Intent v1 与人工确认卡；日语 `DO_NOT_UPLOAD` 不生成上传意图。

## 真实频道 CLI 只读接口

真实频道身份仍以发布中心为唯一事实源。阶段6只消费现有 CLI 的九字段输出：`channelSerial`、`channelId`、`channelName`、`language`、`region`、`timezone`、`uploadPolicy`、`enabled`、`profileVersion`。

真实 CLI 适配测试确认 API v1、九字段和档案数量一致；测试时发现 6 条档案，但没有把任何真实频道名称、channel ID 或字段值写入仓库、夹具或本报告。缺失、重复、停用或预期不可变 ID 不匹配均失败；不按语言、地区或题材猜频道。

只读测试前后发布中心数据文件：

| 文件 | SHA-256（前后相同） | 大小 |
| --- | --- | --- |
| `publisher-center.db` | `97347919099701ce40b67981504bf18f0ddbb0c986de47e7afa2dc610e83f4cf` | 1,011,712 |
| `publisher-center.db-shm` | `fd4c9fda9cd3f9ae7c962b0ddf37232294d55580e1aa165aa06129b8549389eb` | 32,768 |
| `publisher-center.db-wal` | `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855` | 0 |

合成频道包注入真实 CLI 时被预期的频道身份不匹配门拒绝；上述三个文件哈希仍不变。

## 官方约束目录

约束只依据 YouTube/Google 官方资料，核验日期为 2026-08-04：

- [Videos API](https://developers.google.com/youtube/v3/docs/videos)：标题最多 100 字符、简介最多 5000 bytes、后台 tags 合计最多 500 字符
- [Videos: update](https://developers.google.com/youtube/v3/docs/videos/update)：`publishAt` 只适用于 private 且从未发布的视频；过去时间会立即发布，因此本地安全门要求未来时间
- [Thumbnails: set](https://developers.google.com/youtube/v3/docs/thumbnails/set)：API 缩略图最多 2 MB，JPEG/PNG/octet-stream
- [Captions: insert](https://developers.google.com/youtube/v3/docs/captions/insert)：字幕上传最大 100 MB
- [YouTube Hashtags](https://support.google.com/youtube/answer/6390658)：超过 60 个 Hashtags 会被忽略；本协议采用更严格的 8–12 个
- [Upload videos longer than 15 minutes](https://support.google.com/youtube/answer/71673)：视频上限为 256 GB 或 12 小时，以较小者为准
- [Recommended upload encoding settings](https://support.google.com/youtube/answer/1722171)：推荐 MP4、H.264 与 AAC

约束目录为版本化、可更新数据文件；分发侧和发布中心侧副本逐字节相同，SHA-256 如上。

## 测试、构建与实际命令

分发侧关键命令：

```powershell
uv run python tools/validate_contracts.py
uv run python tools/validate_plugin.py
uv run python tools/validate_release_manifest.py
uv run python tools/check_repository_safety.py
uv run python -m unittest -q
powershell -NoProfile -ExecutionPolicy Bypass -File tools/Test-Stage2.ps1 -PublisherCliPath "E:\YouTube视频自动上传\youtube-publisher-center\build\bin\youtube-publisher-channel-list.exe"
powershell -NoProfile -ExecutionPolicy Bypass -File tools/Test-Stage3.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File tools/Test-Stage4.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File tools/Test-Stage5.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File tools/Test-Stage6.ps1
uv run python tools/generate_stage6_fixture_packages.py --output "E:\小说漫全自动化生产\runtime\stage6-validation-synthetic\publish-package-v2-20260804-r3"
uv run python tools/validate_stage6_outputs.py --output "E:\小说漫全自动化生产\runtime\stage6-validation-synthetic\publish-package-v2-20260804-r3"
```

分发结果：

- Stage6 单元测试 15/15 PASS
- 全仓 Python 回归 118/118 PASS；注入真实只读频道 CLI，原先环境性跳过转为真实适配 PASS
- Stage2、Stage3 全部 PASS
- Stage4 内容测试 12/12 PASS，三市场 Publishing Asset Package v1 均通过
- Stage5 核心 22/22 PASS，三市场输出和隔离安装均通过
- Stage6 三市场生成/独立验证/隔离插件安装全部 PASS
- 插件健康：8 Skills、25 tools、`serviceChecked=true`
- Publish Skill 健康：5/5 冻结工具、5/5 `networkExecution=false` 硬门
- Release：`v0.6.0-dev.1`；最终 content hash 以 `release-manifests/release-v0.6.0-dev.1.json` 为唯一事实源，避免报告自身进入发布指纹后形成自引用

发布中心关键命令：

```powershell
$env:STAGE6_DISTRIBUTION_FIXTURE_ROOT="E:\小说漫全自动化生产\runtime\stage6-validation-synthetic\publish-package-v2-20260804-r2"
go test ./internal/publishv2 ./cmd/publish-package-v2 -count=1
go vet ./internal/publishv2 ./cmd/publish-package-v2
go test ./... -count=1
npm run test:sites
npx vite build --outDir "E:\小说漫全自动化生产\runtime\stage6-validation-synthetic\publisher-isolated\frontend-final" --emptyOutDir
go build -trimpath -o "E:\小说漫全自动化生产\runtime\stage6-validation-synthetic\publisher-isolated\publish-package-v2-final.exe" ./cmd/publish-package-v2
```

发布中心结果：

- Stage6 定向 Go 测试 35/35 test/subtest PASS
- `go vet` PASS
- 前端测试 17/17 PASS
- 隔离 Vite 构建 PASS
- 完整 Go 回归在 hermetic PATH 下全部 package PASS
- 常规 PATH 首次完整回归只有既有 `internal/service` 两项环境断言不同：旧测试硬期待 `FFPROBE_NOT_FOUND`，而系统 FFprobe 可见并正确返回坏媒体的 `FFPROBE_EXEC_FAILED`；未为此修改任何既有脏文件。隔离 PATH 排除系统 FFprobe 后完整回归 PASS
- r2 和最终 r3 三市场包均由独立发布中心 CLI 验证/导入 PASS

## 失败与越权测试矩阵

| 失败分支 | 预期与结果 |
| --- | --- |
| `.creating` 半包 | 忽略，不导入 |
| 绝对路径、`..`、包外路径 | 拒绝 |
| 包根、上游或包内符号链接 | 拒绝 |
| 坏 SHA-256、大小错、项目/版本/上游错配 | 拒绝 |
| 未声明文件、缺失文件 | 拒绝 |
| 坏 MP4、解码失败、流/参数不合格 | 拒绝 |
| 字幕越过视频末尾、字幕/目标语言错配 | 拒绝 |
| Hashtags 数量/格式错误 | 拒绝 |
| 后台 tags 冒充 Hashtags | 拒绝 |
| 频道序号缺失/重复/停用/ID 不匹配 | 拒绝，不猜频道 |
| AUTO 三门缺失或授权版本/时间失效 | `WAITING_REVIEW` |
| 排期过期/冲突、无效时区、额度满、并发满 | `WAITING_REVIEW`，不擅自选时 |
| 重复导入 | 幂等复用，不覆盖旧意图 |
| 伪造 video ID、URL、会话或假回执 | 拒绝 |
| `execute --network-execution=true` | `NETWORK_EXECUTION_FORBIDDEN` |
| 资格齐全但尝试执行 | `EXTERNAL_APPROVAL_REQUIRED` |
| 查询无 video ID 的回执 | `PUBLICATION_RECEIPT_NOT_AVAILABLE` |
| 删除命令/隐式远端删除 | CLI 不暴露删除能力；本地删除不映射远端删除 |
| v1/v1.1 新建 | 禁止；只读兼容识别 |

## 非技术用户 Skill 与安装健康

新增 `publish-video` Skill，支持自然语言“准备上传成片”和“查看上传状态与回执”，也支持显式 `$publish-video`。Skill 精确绑定五个冻结工具：

- `assemble_publish_package_v2`
- `validate_publish_package_v2`
- `import_publish_package_v2`
- `get_publication_status`
- `get_publication_receipt`

协议明确真实上传或授权必须再次获得用户确认；所有五个工具都要求并固定 `networkExecution=false`。没有真实 video ID 时，Skill 明确回答 Publication Receipt v1 不存在。

最终干净隔离安装保留在 `E:\小说漫全自动化生产\runtime\stage6-skill-validation\`；具体冻结目录以最终安装态记录为准，避免报告自身参与发布指纹后形成路径自引用。安装态与 Release manifest hash 一致；产品健康 8 Skills/25 tools，发布 Skill 5/5 工具和 5/5 网络硬门 PASS。

## 外部源码改动、提交与保留项

发布中心精确本地提交 `70f9a8d13143050e045b1bfd61005742724d0fa6` 只含 23 个阶段6新增文件。父仓库所有既有用户修改与其他未跟踪文件仍保留，未暂存、未夹带。

分发仓库的阶段6协议、工具、Skill、测试、文档和 Release manifest 在本报告封存后作精确本地提交；提交 SHA 记录在最终交付消息。两个仓库均未 push、未创建 Release。

收口过程中，一个由本轮测试新建、不含用户数据的 `.stage6-r3-source` 临时合成源目录曾被提前清理；随后从保留的 r3 `upstream-snapshots` 按原路径恢复并执行逐文件 SHA-256 等价验证。恢复证据为 54 个文件、0 个哈希错配，tree SHA-256 `6dc579791205ff78a3f855e0a3c63592ce184bc6e0c0cac3fe1e90a7d9cb9ee2`。没有既有文件、用户数据、正式发布包或正式程序丢失；恢复后的目录保留，不再清理。

## 残余边界与 Stage6 GO/NO-GO

**Stage6 本地协议、隔离集成与安全门：GO。**

**真实发布：NO-GO，等待新的明确审批。** 具体仍未完成且不得由阶段6自动跨越的边界：

- Google/YouTube OAuth 与任何授权流程
- 真实 YouTube API 上传、修改、排期、公开或删除
- 真实 `youtube_video_id`
- Publication Receipt v1
- 正式发布中心数据库/inbox 接入与正式 EXE 部署
- 用户数据迁移、长期频道学习规则写入
- GitHub push 或 Release

因此阶段6的“GO”仅表示发布包 v2、本地验证/导入、上传意图、安全门和未来执行接口已经达到本地集成退出条件，不构成真实上传授权。
