# AI 视频频道生产系统

这是面向普通用户安装的 GitHub 发布仓库骨架。产品通过 Codex 插件组织工作流，通过本地工具和独立桌面程序执行确定性动作。

当前版本为阶段 1 Beta `0.1.0-beta.2`，只交付：

- Codex 插件与 marketplace 骨架。
- 总入口和频道建库入口 Skills。
- 六大中心的版本化跨中心契约、示例和校验工具。
- Windows 本地安装、升级、卸载与回滚骨架。
- 组件兼容清单和阶段 1 验证报告。

当前版本不会创建真实频道资料库、下载资料、生成内容、调用工坊、上传视频或读取 Analytics。

## 阶段2未发布工作树

本地开发工作树已增加频道资料库与 stdio MCP 本地工具服务，支持发布中心正式只读 CLI、双阶段建库、任务单频道绑定、生产预设、本次覆盖、备份、恢复和 `.avchannel` 迁移。该能力尚未形成新的 GitHub Release；已发布的 `v0.1.0-beta.2` 标签仍保持阶段1内容。

阶段2隔离验证：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\tools\Test-Stage2.ps1 -PublisherCliPath <youtube-publisher-channel-list.exe>
```

正式建库还需要安装器配置发布中心只读程序和不含密钥的预扫描真实音色目录。没有这些依赖时，系统返回明确缺口，不制造频道或音色。

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
codex plugin marketplace add coisu772-code/AI- --ref v0.1.0-beta.2
codex plugin add ai-video-channel-production@novel-manga-production
```

也可以从 GitHub Release 下载 `ai-video-channel-production-v0.1.0-beta.2.zip`，核对 `SHA256SUMS.txt` 后解压并运行 `installer\install.cmd`。安装完成后重启 Codex 并新建任务。

文档入口：

- `docs/baseline-inventory-2026-08-03.md`
- `docs/contract-ownership-and-flow.md`
- `docs/compatibility-matrix.md`
- `docs/install-upgrade-rollback-uninstall.md`
- `docs/release-process.md`
- `docs/phase1-validation-report-2026-08-03.md`
- `docs/local-tool-service-protocol-v1.md`
- `docs/phase2-channel-library-validation-2026-08-04.md`
- `docs/phase3-source-library-validation-2026-08-04.md`
- `docs/phase4-content-loop-validation-2026-08-04.md`

`0.1.0-beta.2` 是阶段 1 骨架预发布，不包含频道建库、资料采集、内容生成、视频生产、真实上传或 Analytics。

## 阶段3未发布资料闭环

本地 `0.3.0-dev.1` 候选在阶段2频道库之上增加统一 Source Library，支持：

- 资料添加确认卡、进度、取消、恢复、完成卡、检索和增量更新；
- YouTube 频道轻量清单，以及单视频公开元数据、封面和字幕优先采集；
- TXT、MD、EPUB、PDF、DOCX 用户文件标准化；
- 日文、中文、英文共九个小说网站的版本化能力清单；
- 平台 ID、规范 URL 和 SHA-256 去重，以及重启后的持久检索；
- Source Package v1 清单、来源边界、版本化资产和采集报告。

该候选仍是未发布工作树，不改变已发布 `v0.1.0-beta.2`。它不会执行拆视频、拆书、仿写、选题、文案生成、工坊生产、OAuth、上传或 Analytics。无足够字幕或正文时只返回失败原因和用户补充路径，不根据标题、封面或页面元数据编造内容。

阶段3隔离验收入口：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\tools\Test-Stage3.ps1
```

完整证据见 `docs/phase3-source-library-validation-2026-08-04.md`。

## 阶段4未发布内容最小闭环

本地 `0.4.0-dev.1` 候选在阶段2频道上下文和阶段3 Source Package v1 之上，增加可由新 Codex 对话使用的内容生产闭环：

- Source Library → Topic Package v1 → Manuscript Package v1 → Publishing Asset Package v1；
- 原创、频道画像锚定和用户大纲直通三种当前可用选题路线；
- 频道路线逐候选检查点与严格 10 候选门，普通原创 3～6 候选，大纲直通唯一方案；
- 目标语言原生母稿、非中文逐行中文回译、合并质量门和选择性失效；
- 唯一标题、目标语言简介、8～12 个 Hashtags、5 个封面候选、唯一封面和 CTR 联评；
- G3／G4／G5 状态机、版本、SHA-256、上游引用和移交前联合确认。

趋势研究、单作品、多作品、拆书与仿写保留稳定扩展接口；当前未安装对应能力时返回 `CONTENT_EXTENSION_UNAVAILABLE`，不会伪造分析。阶段4只判断生产包是否具备移交资格，不调用工坊、发布中心、OAuth、上传、Analytics，也不写入长期频道学习。

阶段4完整验收入口：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\tools\Test-Stage4.ps1
```

三组日／中／英短小合成包位于 `tests/fixtures/stage4/packages/`。它们使用同一 Schema、状态机、质量门、文件与哈希校验，仅用于离线验收，不是线上数据或用户内容。完整证据见 `docs/phase4-content-loop-validation-2026-08-04.md`。
