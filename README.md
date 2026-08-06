# AI 视频频道生产系统 RC

当前候选版本是 `v0.8.0-rc.2`。这是本地待验收候选，不表示已经发布到 GitHub，也不表示 YouTube 真实上传已经验收。

## 当前内容主流程

新内容统一走四个 Skills：`content-source`（视频链接／上传文本／资料库／按需联网资料）→ `content-deconstruct`（完整拆解）→ `content-rewrite`（单源高贴合或资料融合二选一）→ `production-text`（可直接用于配音、字幕、分镜和制作的正式文本）。旧频道蒸馏、旧视频拆文、8 方向仿写、独立选题和旧文稿 Skills 已退出新任务入口。

标题、简介和封面预留为 `content-title`、`content-description`、`content-thumbnail` 三个独立扩展位；目前状态为 `PLANNED_UNAVAILABLE`。`publishing-assets` 只在未来三个资产包都已实现并确认后负责汇总，不会临时冒充生成器。

## Windows 一键安装

[下载 Windows 统一安装器（v0.8.0-rc.2）](https://github.com/coisu772-code/AI-/releases/download/v0.8.0-rc.2/AI-Video-Channel-Production-Unified-Installer-v0.8.0-rc.2.zip)

Release 获批后，普通联网用户只需下载这一个 ZIP，解压并双击 `install.cmd`。入口只从锁定的 `v0.8.0-rc.2` Release URL 获取总清单，不使用 `latest`；随后逐项校验大小和 SHA-256，再事务式安装全部组件。

先决条件：Windows 10/11 x64、PowerShell 5.1 或更高版本、约 1 GB 可用空间，以及 Codex 桌面版或支持 `plugin` 命令的 Codex CLI。无需预装 Python、uv 或 FFmpeg。

默认程序目录是 `%LOCALAPPDATA%\AIVCP`，默认数据目录是 `%LOCALAPPDATA%\AI Video Channel Production Data`。旧的 `%LOCALAPPDATA%\AI Video Channel Production\data` 不会被迁移、删除或覆盖。自定义安装目录过长时，安装器会在解压前给出明确错误并要求选择更短路径。

安装完成后，如提示需要手动注册，请按安装目录中的 `CODEX-PLUGIN-SETUP.txt` 操作：先注册随产品提供的 repository marketplace，再在 Codex 的 Plugins 页面安装或启用插件。然后重启 Codex 并新建任务；已有任务不会重新加载插件。安装器会在被缓存前把插件的 MCP 描述符直接绑定到该安装拥有的 bundled Python、独立数据目录、工坊、FFmpeg/ffprobe、预扫描音色目录和发布中心只读/离线 CLI，不依赖系统 Python、uv 或 PowerShell stdin 代理。启动时会拒绝指向安装树外的组件路径和过期缓存版本。

若频道建库提示“系统没有可用的预扫描音色目录”，请使用同版或更高版本安装包执行 `Repair-AIVideoChannelProduction.ps1`，再重启 Codex 并新建任务。修复会恢复随核心包提供的无密钥音色目录，不启动 VOICEVOX/Kokoro 服务、不调用收费配音 API，也不改写项目、角色、配音设置或媒体数据。目录同时覆盖本地引擎和具有真实预扫描列表的在线引擎；没有公开音色列表的 Seed Audio 以明确策略记录，绝不伪造 voice ID 或把 API Key 打进目录。

完全离线安装、升级、修复、回滚、卸载和备份恢复说明见 [安装与生命周期说明](docs/install-upgrade-rollback-uninstall.md)。历史阶段记录见 [实现历史](docs/implementation-history.md)。

## 安全边界

候选包不含 Token、API Key、OAuth 凭据、用户项目或频道数据。默认不发起 Google/YouTube OAuth，不执行真实上传，不读取真实 Studio 私有数据，也不写回长期学习。升级、修复、回滚和卸载保留独立用户数据；正式 Release、OAuth、真实 private 上传、Studio 数据和长期学习写回仍需分别批准。
