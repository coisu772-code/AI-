# v0.12.0-rc.1 安装、升级、回滚、修复与卸载

## 统一资产

锁定总清单管理五个核心 Release ZIP：统一安装入口、无大型 EXE 的核心插件、独立 Python 3.12.13 runtime、新漫剧工坊和 YouTube 发布中心。FFmpeg 8.1.2 与 ffprobe 是工坊包内的显式受管组件，总清单记录逐文件哈希、GPL-3.0 许可来源与健康检查。

同一个 Release 另外携带 Kokoro-FastAPI 的 CPU、NVIDIA 和 NVIDIA Blackwell 三套可选分卷资产。它们不属于统一安装器的五个安装 ZIP，不会在安装或升级系统时自动下载；用户在新漫剧工坊中明确选择本地 Kokoro 后，工坊才从锁定版本的公开 Release 读取对应 JSON 清单，逐卷校验大小和 SHA-256、重组并验证整包 SHA-256，然后安装到工坊程序目录。清单只接受 `coisu772-code/AI-` 的公开 GitHub Release 地址。

发布中心冻结包含产品 `LICENSE.md`、JSON/Markdown 告知和 101 份第三方许可文本，技术清单 `REVIEW_REQUIRED=0`。Python runtime 的 12 个包共有 58 个许可条目，均有声明和许可文件；工坊应用与 FFmpeg 告知也已技术核对。技术库存不构成法律意见或签署，正式 Release 仍需发布负责人/法律审核者批准。

## 安装入口和路径

联网用户只下载统一安装器 ZIP，解压后双击 `install.cmd`。若同目录没有总清单，入口只从版本锁定的 `v0.12.0-rc.1` HTTPS Release URL 获取它，先校验 schema、产品和精确版本，再下载缺失资产；不使用 `latest`。完全离线时，把总清单和另外四个核心组件 ZIP 放在 `install.cmd` 同目录。仅在离线安装 Kokoro 时，才另行准备对应的 JSON 清单与全部分卷文件。本版本的三套 Kokoro 运行包内容未变化，继续从已校验的公开 `v0.10.0-rc.1` Release 获取。

`install.cmd` 会分别确认程序根和用户数据根。程序根默认是 `%LOCALAPPDATA%\AIVCP`；数据根保存频道资料库、来源、用户审核文档、音频、图片、视频、生产任务、导入导出与备份。安装器优先推荐可用空间最大的非系统固定盘，例如 `D:\AI Video Channel Production Data`；没有合适数据盘时才推荐当前用户的视频目录。直接按回车采用推荐值，也可以输入其他绝对路径。

全新非交互安装必须显式提供 `-DataRoot`，不会使用隐式 C 盘默认值。已有安装会从 `installation.json` 读取并沿用原 `userDataRoot`；即使升级、修复、回滚或卸载，也不改变或清空该目录。若要迁移既有数据，先用频道导出／备份完成可校验副本，再在新数据根安装并恢复；安装器会拒绝把已有安装静默改绑到另一个目录。旧 `%LOCALAPPDATA%\AI Video Channel Production\data` 只作为既有用户数据保留，不自动迁移、删除或覆盖。程序根与数据根始终分离。

安装器在任何解压前完成两层路径门：先检查已知最长 bundled runtime 目标，再逐个检查每个 ZIP 条目的临时 extraction、staging 和最终 `current` 路径。传统 Windows 路径预算锁定为 248 个字符；超限会明确要求使用更短的 `-InstallRoot`。解压使用短 `.s-xxxxxxxx\x\N` 中间目录，并在安全验证后剥离上游 archive root，从而给默认真实 profile 留出充足余量。

每个资产先核对文件名、大小和 SHA-256，再拒绝路径穿越、大小写重复项和符号链接。只有 runtime 导入、插件结构、MCP tools/list 与安全默认全部健康后才切换 `current`；失败会恢复旧 current、installation marker 和 runtime locator 的精确旧字节。

## Codex 缓存插件、运行时绑定与 locator

安装、升级、修复、回滚和幂等重装都会在 Codex 注册前重写当前插件的 `.mcp.json`：`command` 直接绑定该安装 `current\runtime\python\python.exe`，`args` 只使用缓存插件内的 `./mcp/server.py mcp`，`env` 显式绑定独立数据根、配置根、`assets\voice-catalog.json` 和离线安全默认。Codex 复制插件后直接连接 bundled Python，不经过 PowerShell/CMD stdin 代理，也不依赖系统 Python 或 uv。旧缓存保留旧版本绑定，不能借用新 runtime 打开数据；新的安装事务只有在版本化描述符、marker、state 和健康门一致后才提交。

核心包固定携带 schema `1.0.0` 的无密钥预扫描音色目录，当前包含 VOICEVOX、Kokoro、Edge TTS 与 Fish Audio 的真实 voice ID。Seed Audio 的公开 API 没有可枚举音色列表，目录使用 `PROVIDER_HAS_NO_PUBLIC_VOICE_LIST` 策略如实标记，只允许后续使用服务默认音色或使用者明确提供的账户音色 ID，不伪造预设。安装与修复在切换 `current` 前检查文件、schema、引擎和音色列表，完整健康门还会实际调用 `system_voice_catalog`，并把工坊 `--no-probe` 返回的全部配音引擎与“真实目录或明确无列表策略”逐项对账。以后工坊新增本地或 API 配音引擎而发布包漏配目录策略时，安装健康门直接失败。目录读取不探测或启动本地配音服务、不读取 API Key，也不调用收费 API；因此服务暂时未运行不会阻塞频道建库。若新包缺失、损坏或含不受支持的目录，事务会失败并保留此前可用版本。

安装器同时在 `%LOCALAPPDATA%\AIVCP-Config\runtime-locator.json` 写入不含凭据的受控 locator，用于安装所有权、修复、回滚和 generic source launcher 的严格回退。它绑定产品、版本、安装根、`current`、bundled Python 相对路径和独立数据根；locator 与 marker/state 不一致时拒绝使用。

多安装切换 locator 必须由 install/upgrade/repair/rollback 显式接管，并写入 `runtime-locator-history.jsonl`。同版本幂等校验不会从另一个安装静默抢占。卸载仅在程序删除成功后实时复核 locator 所有者；若 locator 已属于另一个安装，则保留 locator、Codex plugin 和 marketplace 注册。

Install、Upgrade、Repair、Rollback 和 Uninstall 共享包含当前 Windows 用户 SID 的 `Global\` 命名互斥锁，跨同一用户的 Windows 会话拒绝并发修改且不影响其他用户。Rollback 把 current、运行时绑定描述符、marker 和 locator 作为一个事务；Codex 刷新失败也会恢复程序与绑定。当前 Codex CLI 只有 marketplace 管理命令时属于受支持降级，安装目录会生成 `CODEX-PLUGIN-SETUP.txt`：用户先注册 repository marketplace，再在 Codex Plugins 页面安装或启用插件，最后重启 Codex 并新建任务。

## 生命周期命令

以下命令从已安装版本的 `installer` 目录执行：

```powershell
.\Upgrade-AIVideoChannelProduction.ps1 -ManifestPath <新清单> -AssetRoot <资产目录>
.\Repair-AIVideoChannelProduction.ps1 -ManifestPath <同版清单> -AssetRoot <资产目录>
.\Rollback-AIVideoChannelProduction.ps1 -Confirm:$false
.\Test-AIVideoChannelProductionHealth.ps1 -AsJson
.\Uninstall-AIVideoChannelProduction.ps1 -Confirm:$false
```

`Uninstall -WhatIf` 不改变程序、locator 或 Codex 注册；程序删除失败也不会提前移除 locator。Restore 的 `-WhatIf` 不创建临时目录、不解压，返回 `WHATIF_NO_CHANGE`，而不是 `RESTORE_COMPLETE`。真正卸载只移除程序并保留独立数据；删除用户数据必须由用户另行明确决定。

频道建库出现 `VOICE_CATALOG_UNAVAILABLE` 时，使用同版或更高版本核心包执行 Repair，然后重启 Codex 并新建任务。Repair 只恢复受管程序文件和运行绑定，不会覆盖独立数据根中的频道、项目、角色、配音配置、图片或视频。

## 未执行的外部动作

本地验证不执行 push、tag、GitHub Release、Google/YouTube OAuth、真实上传、正式 EXE 覆盖、用户数据迁移/删除或长期学习写回。新候选仍需另一轮干净 Windows、重启后新 Codex 任务、受控 private 上传和 Studio 私有数据等各自批准的真实验收。
