# 阶段3 Source Library 验收报告（2026-08-04）

## 结论

阶段3“资料最小闭环”退出条件已满足，结论为 **PASS**。

本地未发布候选版本为 `0.3.0-dev.1`。Source Package、阶段2频道档案契约和本地工具协议继续使用 `1.0.0` 主版本；`channel.db` 通过迁移前备份和事务回滚从 Schema 1 增量升级为 Schema 2。候选发布清单状态仍为 `draft`，未创建 GitHub Release、未推送、未执行 OAuth、未上传视频、未改动控制中心或工坊，也未进入阶段4内容分析或生成。

## 完成范围

### 统一 Source Library

- 每个频道使用独立 `channel.db` 和 `sources/` 目录。
- 保存来源登记、Source Package、版本、资产、别名、采集任务、逐项检查点和恢复状态。
- 支持平台 ID、规范 URL、标准化内容 SHA-256 三层去重。
- 同内容不同文件名直接复用一个资料包和一个内容版本，同时记录两个来源别名。
- 同一 URL 内容发生真实变化时生成修订版本；仅采集时间变化不会制造新版本。
- 提供添加／更新确认卡、进度、取消、恢复、完成卡、检索、详情和完整性检查。
- 服务重启后数据库、索引、任务和 Source Package 仍可读取。

### YouTube 适配器

- 频道：尽力完整的轻量视频清单、公开指标、缺失字段完整性和增量变化。
- 单视频：标题、简介、公开 Hashtags、最大可用封面、公开指标和采集时间。
- 文字优先级：人工字幕 → 自动字幕 → 用户允许且已配置时的临时音频本地转录。
- 默认不保存完整视频；本地转录后删除临时音频。
- 无字幕、字幕不完整、不可访问或未配置转录器时保存明确边界、失败原因和补充路径。
- `bodyGeneratedFromMetadata=false`，不会根据标题、封面或指标编造正文。
- 子进程使用 `shell=False`，限制运行时间和输出大小，并对错误输出脱敏。

真实公开只读小样本核验：

- 视频 `jNQXAC9IVRw`：`CONTENT_READY`，取得真实标题、封面、人工字幕和规范文本。
- 频道 `UC4QobU6STFB0P71PMvOGN5A`：`METADATA_READY`，取得真实频道身份和 1 条尽力完整轻量清单；缺失简介／发布时间标记为 `partial`。
- 核验过程未登录、未转录、未保存完整视频或长期媒体。

### 本地文档适配器

- 支持 TXT、MD、EPUB、PDF、DOCX。
- 保留原文件 SHA-256、检测编码、语言、章节／页／段结构、期望与实际单元数、完整性、警告和来源。
- 同文字的不同编码文件生成相同标准化内容 SHA-256。
- 扫描 PDF 没有可搜索文字时返回 `BLOCKED` 和 OCR／可搜索 PDF 补充路径，不生成文字。
- 未经当前任务确认的本地文件不读取、不哈希。

### 小说网站适配器框架

能力清单 `site-capability-manifest-v1.json` 版本为 `1.0.0`，首版覆盖：

| 市场 | 站点 | 默认边界 |
| --- | --- | --- |
| 日文 | 小説家になろう、カクヨム、青空文庫 | 前两者元数据／用户授权导入；青空文庫公开全文有条件读取 |
| 中文 | 起点中文网、番茄小说、中文维基文库 | 前两者元数据／用户授权导入；维基文库公开全文有条件读取 |
| 英文 | Royal Road、Scribble Hub、Project Gutenberg | 前两者元数据／用户授权导入；Gutenberg 公开全文有条件读取 |

每个站点声明允许字段、获取方式、权利条件、规则来源、核验日期、限速和降级策略。商业站点不会自动获取正文；只接受来源建档、允许的元数据通道或用户明确授权的本地文件。三个公开全文资料源只有在能力规则未过期、逐作品权利证据有效且获取方式属于清单允许项时才接收正文，否则丢弃返回内容并降级。默认安装没有配置站点网络获取器时安全退回来源建档／用户导入。

### MCP 与 Skills

新增十个 `source_*` 本地工具：能力清单、添加准备、添加确认、任务查询、取消、恢复、检索、详情、更新准备和完整性检查。

新增 `$source-library` Skill，并由 `$channel-production` 总入口路由自然语言资料请求。Skill 为显式／编排调用，不会在普通内容对话中隐式启动。拆视频、拆书、仿写只登记为阶段4后的可插拔能力；阶段3完成卡明确 `contentAnalysisStarted=false`。

## 退出条件证据

| 退出条件 | 证据 | 结果 |
| --- | --- | --- |
| 日、中、英代表资料添加→标准化→去重→检索→重启持久 | 隔离安装 MCP 导入三种语言夹具；四个输入得到 `added=3, reused=1`；新服务进程检索为三个资料包 | PASS |
| 同 URL 不重复 | 规范化 Gutenberg URL 去除跟踪参数后复用；YouTube 视频 URL 统一为 watch URL | PASS |
| 同内容不同文件不重复 | 真实 DocumentAdapter 同内容不同文件名仅保留 `1.0.0`，记录两个别名 | PASS |
| YouTube 无字幕不编造 | `BLOCKED`、`method=none`、`bodyGeneratedFromMetadata=false`，提供字幕／媒体／文字补充路径 | PASS |
| 网页不可访问不编造 | `SITE_UNAVAILABLE`、无内容哈希、无正文资产，提供用户授权文件路径 | PASS |
| 用户补充后恢复 | 无字幕任务从 `BLOCKED 1.0.0` 恢复为 `CONTENT_READY 1.0.1` | PASS |
| Source Package v1 可验证 | JSON Schema 2020-12 校验，来源边界、SHA-256、版本、资产索引和上游频道哈希完整 | PASS |
| 增量更新 | URL 身份不变、内容／revision signal 改变时生成新修订；仅时间变化不更新 | PASS |
| 隔离安装闭环 | 安装后的插件、MCP、三个 Skills、确认卡、入库、去重、重启检索和完整性检查通过 | PASS |
| 阶段1、阶段2回归 | 安装／幂等安装／升级／回滚／卸载、隔离 Codex 加载、频道库、正式只读发布接口均通过 | PASS |
| 阶段3边界 | `contentProduction=false`；未调用工坊、OAuth、上传、Analytics 或内容生成 | PASS |

## 测试证据

### 全仓自动化测试

命令：

```powershell
$env:AIVCP_TEST_PUBLISHER_CLI_EXE='E:\YouTube视频自动上传\youtube-publisher-center\build\bin\youtube-publisher-channel-list.exe'
uv run python -m unittest discover -s tests -v
```

结果：`55/55 PASS`，无跳过。包括：

- 契约与候选发布清单；
- 阶段2频道库、迁移失败回滚、任务隔离、备份／恢复、正式发布中心只读 CLI；
- 文档和网站适配器 16 项；
- YouTube 适配器 11 项；
- Source Library 去重、版本、取消、用户补充恢复、重启持久和 Schema 2。

### 阶段1回归

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\tools\Test-Stage1.ps1
```

结果：PASS。插件／契约／发布清单／安全校验、当次 54 项测试、安装、幂等安装、升级备份、回滚、卸载和隔离 `CODEX_HOME` 加载均通过；真实 Codex 用户配置未改变。随后新增的“用户补充后恢复”测试只扩充测试证据、不改变阶段1实现，并已包含在最终全仓 `55/55` 结果中。

### 阶段2回归与正式只读接口

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\tools\Test-Stage2.ps1 `
  -PublisherCliPath 'E:\YouTube视频自动上传\youtube-publisher-center\build\bin\youtube-publisher-channel-list.exe'
```

结果：PASS。三个 Skills 校验、当次 54 项测试、候选幂等隔离安装、MCP 启动、频道库和正式发布中心 `channel-list/v1` 只读适配通过。测试使用隔离合成数据库，未读取真实频道或凭据；新增的恢复测试已包含在最终全仓 `55/55` 结果中。

### 阶段3隔离闭环

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\tools\Test-Stage3.ps1
```

结果：PASS。安装后的 `$source-library`、MCP `source_*` 工具、日中英入库、同内容复用、服务重启检索、Source Package v1 和完整性检查均通过，临时安装与数据自动清理。

### 验收中发现并修复的问题

未隐藏失败过程。隔离验收先后暴露并修复：

1. 中文工作区中的 Python 路径经 Windows 捕获链转码后失真：改用 `uv python find` 获取原生路径。
2. PowerShell 本机参数传递破坏 `--arguments` JSON 引号：改为 MCP stdio `tools/call`，并保留结构化错误诊断。
3. PowerShell 到本机进程的管道损坏含中文路径：把 JSON 非 ASCII 字符编码为标准 `\uXXXX` 后传输，服务端正常还原。
4. 同内容不同文件名被误判为本地资料新修订：本地文件在内容 SHA-256 相同条件下直接复用资料包并记录别名；新增真实适配器回归。

每个问题都先运行对应定向测试，再运行一次完整隔离验收；最终结果为 PASS。

## 版本与兼容性

- 产品候选：`0.3.0-dev.1`，`draft`。
- 候选发布清单内容哈希：`18f26a3198d79ed26779cdcb718d063ba251c97fd61fa3aebaa3b04ae89b297f`。
- Source Package：`1.0.0`，未静默修改 Schema。
- 本地工具协议：`1.0.0`，阶段2工具保持兼容。
- `system.db`：Schema 1。
- `channel.db`：Schema 2，迁移决策见 `docs/change-records/CR-002-source-library-channel-schema-v2.md`。
- 完整矩阵见 `docs/compatibility-matrix.md`。

## 残余风险

1. YouTube 页面和 `yt-dlp` 输出可能变化；已通过可替换后端、版本化适配器和安全失败路径隔离。
2. 默认安装未配置真实本地 ASR 引擎；临时音频生命周期和转录降级已用夹具验证，未把 ASR 可用性伪装为事实。
3. 网站规则、页面结构和作品权利状态会变化；能力清单到期后自动降级，真实公开全文读取仍需注入合规只读获取器。
4. 扫描 PDF 不包含 OCR；当前明确阻断并要求用户补充 OCR 文本或可搜索 PDF。
5. 候选尚未发布；本报告不授权推送、Release、OAuth、上传或真实数据迁移。

这些风险都有保守失败路径，不破坏阶段3资料最小闭环。

## 阶段4进入建议

建议结论：**GO（有条件）**。

进入阶段4前必须继续满足：

- 阶段4以新的版本化能力和测试开启，不回写或静默改变 Source Package v1；
- 内容分析只消费 `CONTENT_READY` 或用户明确接受的 `PARTIAL` 资料，不把标题、封面或元数据当正文；
- 拆视频、拆书、仿写分别作为可插拔能力实现，并继续保留来源、权利、事实／推断／未知边界；
- 内容分析、推荐和生成必须有新的确认／质量门，不复用资料添加确认作为生成授权；
- 商业站点和受限制内容继续禁止绕过登录、付费墙、DRM、验证码或访问限制；
- 阶段4仍不得自动扩大为 OAuth、工坊生产或视频上传授权。

阶段3到此停止。
