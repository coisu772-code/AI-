# AI 视频频道生产系统 RC

当前预发布候选版本是 `v0.14.0-rc.1`。本版把 Codex 视觉计划升级为 schema 1.5，新增按视觉语义合并配音行、角色生命周期外观绑定、战斗关键瞬间约束、分类音效时长、失败步骤选择性续跑和更强的多方向动态镜头；配套新漫剧工坊版本为 `2.7.0-rc.1`。YouTube 发布中心 `0.9.0-rc.4` 补齐 Publish Package v2.1.0 正式交接、实时状态和回执命令。统一安装器与全部组件锁定到本版本，系统不会代替用户执行 Google／YouTube OAuth。

## 当前内容主流程

新任务先建立不绑定频道的自由创作工作区。`content-source` 只负责取得并保存视频字幕、上传文本、资料库或按需联网资料；热点研究必须先展示带来源、日期与趋势依据的中文选择卡。用户本次提供的提示词文件只按当前任务登记用途、顺序、字段映射与 SHA-256，不复制进 Skill。用户明确要求直接生成完整文章时，`content-rewrite` 使用 `direct-draft` 路线，附件中的分析和构思作为内部方法执行，不再强制大纲确认；用户提供或确认不少于 80 字的大纲时则使用 `provided-outline`。随后由 `content-review-edit` 审核修改并冻结正式稿，`content-title-description` 生成标题、YouTube 简介和正式封面。旧 `content-deconstruct`、迁移／仿写方向和旧 8 方向入口不再用于新任务。

标题、简介和封面现由一个 `content-title-description` Skill 同时提供，对外保存为 `title-asset-v1`、`description-asset-v1` 和 `thumbnail-asset-v1`。封面先由同一标题提示词确定短文案与视觉方向，再调用内置图片生成能力产出五张16:9候选并选定正式图；不再保留独立封面 Skill 或未来等待点。

每个项目只为本次实际执行的创作、审核、包装与制作阶段生成版本化用户审核文档，不再固定补齐 `01`–`11`。稳定文件名指向最新版本，历史版本、路径、大小和 SHA-256 继续保留。中文版和中文包装翻译只供审核，不会进入配音、字幕、分镜或 YouTube 正式字段。

## Windows 一键安装

[下载 Windows 统一安装器（v0.14.0-rc.1）](https://github.com/coisu772-code/AI-/releases/download/v0.14.0-rc.1/AI-Video-Channel-Production-Unified-Installer-v0.14.0-rc.1.zip)

普通联网用户只需下载这一个 ZIP，解压并双击 `install.cmd`。入口只从锁定的 `v0.14.0-rc.1` Release URL 获取总清单，不使用 `latest`；随后逐项校验大小和 SHA-256，再事务式安装全部组件。新漫剧工坊需要 Kokoro 时，会按 CPU、NVIDIA 或 NVIDIA Blackwell 选择对应的公开分卷运行包，先校验清单、大小和 SHA-256，再在工坊程序目录内安装；本次继续复用 `v0.10.0-rc.1` 中内容未变化且已校验的公开 Kokoro 运行包，不重复上传相同大资产，也不会写入频道、项目、凭据或运行数据目录。

先决条件：Windows 10/11 x64、PowerShell 5.1 或更高版本、统一系统约 1 GB 可用空间，以及 Codex 桌面版或支持 `plugin` 命令的 Codex CLI。无需预装 Python、uv 或 FFmpeg。Kokoro 是可选本地语音运行时，按所选硬件还需要约 2–6 GB 额外空间。

安装时会分别确认“程序目录”和“用户数据目录”。程序目录默认是 `%LOCALAPPDATA%\AIVCP`；用户数据目录保存资料库、审核文档、音频、图片、视频、生产任务和备份，安装器优先推荐空间最大的非系统盘，只有没有合适数据盘时才推荐用户视频目录。用户可以直接输入其他目录。全新静默安装必须显式提供 `-DataRoot`，不会再把大型用户数据悄悄放进 C 盘。已有安装、升级、修复、回滚和卸载会沿用并保留原数据目录，不静默迁移、删除或覆盖。自定义安装目录过长时，安装器会在解压前给出明确错误并要求选择更短路径。

安装完成后，如提示需要手动注册，请按安装目录中的 `CODEX-PLUGIN-SETUP.txt` 操作：先注册随产品提供的 repository marketplace，再在 Codex 的 Plugins 页面安装或启用插件。然后重启 Codex 并新建任务；已有任务不会重新加载插件。安装器会在被缓存前把插件的 MCP 描述符直接绑定到该安装拥有的 bundled Python、独立数据目录、工坊、FFmpeg/ffprobe、预扫描音色目录和发布中心只读/离线 CLI，不依赖系统 Python、uv 或 PowerShell stdin 代理。启动时会拒绝指向安装树外的组件路径和过期缓存版本。

若频道建库提示“系统没有可用的预扫描音色目录”，请使用同版或更高版本安装包执行 `Repair-AIVideoChannelProduction.ps1`，再重启 Codex 并新建任务。修复会恢复随核心包提供的无密钥音色目录，不启动 VOICEVOX/Kokoro 服务、不调用收费配音 API，也不改写项目、角色、配音设置或媒体数据。目录同时覆盖本地引擎和具有真实预扫描列表的在线引擎；没有公开音色列表的 Seed Audio 以明确策略记录，绝不伪造 voice ID 或把 API Key 打进目录。

完全离线安装、升级、修复、回滚、卸载和备份恢复说明见 [安装与生命周期说明](docs/install-upgrade-rollback-uninstall.md)。历史阶段记录见 [实现历史](docs/implementation-history.md)。

## 安全边界

候选包不含 Token、API Key、OAuth 凭据、用户项目或频道数据。默认不发起 Google/YouTube OAuth，不执行真实上传，不读取真实 Studio 私有数据，也不写回长期学习。升级、修复、回滚和卸载保留独立用户数据；正式 Release、OAuth、真实 private 上传、Studio 数据和长期学习写回仍需分别批准。
