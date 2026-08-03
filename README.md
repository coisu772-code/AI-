# AI 视频频道生产系统

这是面向普通用户安装的 GitHub 发布仓库骨架。产品通过 Codex 插件组织工作流，通过本地工具和独立桌面程序执行确定性动作。

当前版本为阶段 1 Beta `0.1.0-beta.1`，只交付：

- Codex 插件与 marketplace 骨架。
- 总入口和频道建库入口 Skills。
- 六大中心的版本化跨中心契约、示例和校验工具。
- Windows 本地安装、升级、卸载与回滚骨架。
- 组件兼容清单和阶段 1 验证报告。

当前版本不会创建真实频道资料库、下载资料、生成内容、调用工坊、上传视频或读取 Analytics。

## 仓库结构

- `.agents/plugins/marketplace.json`：Codex marketplace 入口。
- `plugins/ai-video-channel-production/`：产品插件、总入口与频道建库入口。
- `contracts/`：10 类跨中心契约、Schema、目录和有效示例链。
- `release-manifests/`：产品、组件、协议、Schema 与工件哈希的统一发布事实源。
- `installer/`：Windows 安装、升级、回滚和卸载脚本。
- `tools/` 与 `tests/`：结构、引用、哈希、安全和本地生命周期验证。

## 本地验证入口

在仓库根目录运行：

```powershell
powershell -ExecutionPolicy Bypass -File .\installer\Install-AIVideoChannelProduction.ps1 -InstallRoot .\.stage1-smoke -SkipCodexRegistration
```

完整验收会在隔离目录中执行插件发现、安装、升级、回滚、卸载与 Codex 加载，不修改真实 Codex 用户配置：

```powershell
powershell -ExecutionPolicy Bypass -File .\tools\Test-Stage1.ps1
```

## 安装 Beta

使用 Codex CLI 从 GitHub marketplace 安装固定版本：

```powershell
codex plugin marketplace add coisu772-code/AI- --ref v0.1.0-beta.1
codex plugin add ai-video-channel-production@novel-manga-production
```

也可以从 GitHub Release 下载 `ai-video-channel-production-v0.1.0-beta.1.zip`，核对 `SHA256SUMS.txt` 后解压并运行 `installer\install.cmd`。安装完成后重启 Codex 并新建任务。

文档入口：

- `docs/baseline-inventory-2026-08-03.md`
- `docs/contract-ownership-and-flow.md`
- `docs/compatibility-matrix.md`
- `docs/install-upgrade-rollback-uninstall.md`
- `docs/release-process.md`
- `docs/phase1-validation-report-2026-08-03.md`

`0.1.0-beta.1` 是阶段 1 骨架预发布，不包含频道建库、资料采集、内容生成、视频生产、真实上传或 Analytics。
