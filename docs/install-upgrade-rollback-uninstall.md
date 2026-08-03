# Windows 安装、更新、修复、回滚、备份与卸载

本文适用于“AI 视频频道生产系统”`0.8.0-rc.1`。本地 RC 尚未发布到 GitHub；远端最新版仍是 `0.1.0-beta.2`。

## 下载后先核对

Release 应包含 `ai-video-channel-production-v0.8.0-rc.1-windows.zip` 和 `SHA256SUMS.txt`。在下载目录运行：

```powershell
Get-FileHash .\ai-video-channel-production-v0.8.0-rc.1-windows.zip -Algorithm SHA256
```

结果必须与 `SHA256SUMS.txt` 完全一致。解压后，安装器还会按 `release-v0.8.0-rc.1.json` 再核对插件、安装器、契约和本地工具服务的目录 SHA-256；任一不符就停止，不切换当前版本。

## 联网一键安装

已安装 Codex 和 `uv` 时，双击 `installer\install.cmd`。它会创建独立 Python 运行环境、安装锁定范围内的依赖、执行健康检查、原子切换程序版本并注册 Codex 插件。

默认位置：

- 程序：`%LOCALAPPDATA%\AI Video Channel Production\current`
- 用户数据：`%LOCALAPPDATA%\AI Video Channel Production Data`

两者分开。频道资料、项目、媒体、报告和学习记录不放在 `current` 中。

命令行入口：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\installer\Install-AIVideoChannelProduction.ps1 -RuntimeMode Online
```

## 断网安装

先在一台同为 Windows x64、可以联网的准备机生成 wheelhouse：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\installer\Build-OfflineWheelhouse.ps1 -OutputRoot D:\AIVCP-Wheelhouse
```

把原 RC 解压目录和整个 wheelhouse 一起复制到断网电脑，核对 `WHEELHOUSE-SHA256SUMS.txt`，再运行：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\installer\Install-AIVideoChannelProduction.ps1 `
  -RuntimeMode Offline `
  -OfflineWheelhouseRoot D:\AIVCP-Wheelhouse
```

`Offline` 模式给依赖安装器加上断网硬门，不会悄悄改走网络。断网电脑仍需已有兼容 Python 或由 `uv` 已准备好的 Python；正式 Release 如另附离线 Python 运行时，其 SHA-256 也必须加入 Release 资产清单。

## 重复安装与更新

相同版本、相同插件指纹的重复安装是幂等操作，不创建多余备份。更新新包时运行：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\installer\Upgrade-AIVideoChannelProduction.ps1 `
  -SourceRoot <新版本解压目录> `
  -RuntimeMode Online
```

旧 `current` 会先移动到 `backups`，新版本完成静态／动态健康检查和 Codex 注册后才算成功。复制、健康检查或注册失败时，安装器自动恢复先前 `current` 和安装标记。旧版把数据放在程序目录 `data` 时，升级会继续引用原位置，不自动迁移；真正迁移必须另行批准。

## 修复

从可信来源重新下载同版本或更新版本并核对 SHA-256，然后运行：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\installer\Repair-AIVideoChannelProduction.ps1 `
  -SourceRoot <已核对的解压目录> `
  -RuntimeMode Online
```

修复复用事务式安装，只替换程序与运行时，不改用户数据。源包本身损坏时不要用损坏的 `current` 自修复。

## 手动回滚

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\installer\Rollback-AIVideoChannelProduction.ps1 `
  -BackupName <backups 下的版本目录名>
```

不指定名称时选择最新备份。回滚只接受带本产品 `install-state.json` 的目录，当前版本先保存为 `pre-rollback-*`。用户数据路径随目标安装状态恢复，但不移动或覆盖数据。

## 用户数据备份与恢复

备份：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\installer\Backup-AIVideoChannelProductionData.ps1 `
  -DestinationRoot D:\AIVCP-Backups
```

备份包含文件级 SHA-256、聚合 payload hash 和旁路 `.sha256`。发现疑似密钥／Token 文件名或目录重解析点时会拒绝打包。备份可能包含私有频道资料，请只保存在用户控制的位置，不要上传 GitHub。

恢复到空数据目录：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\installer\Restore-AIVideoChannelProductionData.ps1 `
  -ArchivePath <.aivcp-backup.zip> `
  -DataRoot <新数据目录>
```

恢复先检查 ZIP 路径穿越、重复项、文件大小、逐文件 SHA-256 和聚合 hash，再原子切换。目标非空时默认拒绝；显式使用 `-ReplaceExisting` 时，原目录会先改名为 `pre-restore-*` 保留，不直接删除。

## 卸载并保留数据

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\installer\Uninstall-AIVideoChannelProduction.ps1
```

新安装的数据目录在程序目录外，卸载只删除程序、运行时、程序备份和 Codex 注册。兼容旧版的原位 `data` 会被单独保留，并留下 `uninstalled-user-data.json`。卸载结束还会再次确认数据根存在。

## 健康与安全检查

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\installer\Test-AIVideoChannelProductionHealth.ps1 -AsJson
```

通过结果必须显示 9 个 Skills、32 个本地工具、内容／制作／数据能力健康，并保持 `oauth=not_called`、`upload=not_called`、Analytics `AUTH_REQUIRED`、Token 未读取、长期学习未写入。安装包不包含 EXE、数据库、用户媒体、日志、密钥或 Token；新漫剧工坊和 YouTube 发布中心始终作为外部审批资产，安装器不会覆盖它们。
