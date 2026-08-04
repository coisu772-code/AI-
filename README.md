# AI 视频频道生产系统 RC

当前候选版：`v0.8.0-rc.2`。这是本地候选，不代表已经发布到 GitHub，也不代表 YouTube 真实上传已经验收。

## Windows 统一安装

从获批的 GitHub Release 只下载一个明显入口：`AI-Video-Channel-Production-Unified-Installer-v0.8.0-rc.2.zip`。解压后双击 `install.cmd`；入口只从固定的 `v0.8.0-rc.2` Release URL 获取总清单，不使用 `latest`，随后只下载缺少的锁定组件。

完全离线安装需另外把 `unified-release-v0.8.0-rc.2.json`、核心包、Python 运行时、工坊包和发布中心包放在 `install.cmd` 同目录。每个组件都会先核对大小和 SHA-256，任何不一致都会终止并自动保留原版本。

当前总清单锁定的新发布中心 SHA-256 为 `8d2644c11310fd5ee31f6e39250f75a000ccf038cd8c35a9eed8f0f23388c48d`；旧 publisher 包不能与本候选混用。发布中心、Python 运行时和工坊的技术许可证库存均已核对，但正式 Release 仍需发布负责人/法律审核者独立批准；技术核对不构成法律意见或签署。

先决条件：Windows 10/11 x64、PowerShell 5.1 或更高版本、约 1 GB 可用空间，以及 Codex 桌面版或支持 `plugin` 命令的 Codex CLI。无需预装 Python、uv 或 FFmpeg。

安装完成后，如窗口提示需要手动注册，请按 `CODEX-PLUGIN-SETUP.txt` 执行两条命令。然后重启 Codex，并新建任务；已有任务不会重新载入插件变化。

## 安全边界

候选包不含 Token、API Key、OAuth 凭据、用户项目或频道数据。默认不发起 Google/YouTube OAuth，不执行真实上传，不读取真实 Studio 私有数据，也不写回长期学习。升级、修复、回滚与卸载会把用户数据保留在独立目录。

完整安装/升级说明见 [docs/install-upgrade-rollback-uninstall.md](docs/install-upgrade-rollback-uninstall.md)，历史阶段记录见 [docs/implementation-history.md](docs/implementation-history.md)。
