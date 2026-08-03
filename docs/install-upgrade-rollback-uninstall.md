# Windows 安装、升级、回滚与卸载

## 前提

- Windows PowerShell 5.1 或 PowerShell 7；
- Codex CLI 已安装并能运行；
- 从可信发布来源取得完整仓库或 Release 包，并核对发布清单中的 SHA-256。

默认程序目录是 `%LOCALAPPDATA%\AI Video Channel Production`。程序目录不用于保存频道资料、凭据、项目或媒体。

## 安装

在包根目录运行：

```powershell
powershell -ExecutionPolicy Bypass -File .\installer\Install-AIVideoChannelProduction.ps1
```

安装器先复制到临时目录，校验插件目录指纹，再切换 `current`。之后注册本地 marketplace 和插件。重启 Codex 并新建任务后生效。

如只验证文件、不修改 Codex 用户配置：

```powershell
powershell -ExecutionPolicy Bypass -File .\installer\Install-AIVideoChannelProduction.ps1 -InstallRoot .\.stage1-smoke -SkipCodexRegistration
```

相同版本重复安装是幂等的；`-Force` 会把当前版本移入 `backups` 后重新安装。

## 升级

下载并核验新版本，在当前包根目录运行：

```powershell
powershell -ExecutionPolicy Bypass -File .\installer\Upgrade-AIVideoChannelProduction.ps1 -SourceRoot <新版本解压目录>
```

升级只替换程序文件，旧 `current` 会成为带时间戳的备份。阶段 1 不迁移用户数据。

## 回滚

列出默认安装目录下的 `backups`，然后运行：

```powershell
powershell -ExecutionPolicy Bypass -File .\installer\Rollback-AIVideoChannelProduction.ps1 -BackupName <备份目录名>
```

不指定 `-BackupName` 时选择最新备份。脚本只接受带本产品安装标记的目录；当前版本会先保存为 `pre-rollback-*`。

## 卸载

```powershell
powershell -ExecutionPolicy Bypass -File .\installer\Uninstall-AIVideoChannelProduction.ps1
```

卸载器先核对产品标记，再移除插件注册和程序目录。它不定位、不删除频道资料库、凭据、项目、成片或工作区数据。若只希望移除程序文件且不改 Codex 配置，可加 `-SkipCodexRemoval`。

## 失败处理

- 插件或 marketplace 注册失败时，已安装文件会保留，并明确报错；修复 Codex CLI 后可重复安装。
- 升级复制或校验失败时，临时目录会删除，原 `current` 不变。
- 切换后注册失败时，可使用备份回滚；不会自动删除用户资料。
- 安装目录缺少正确产品标记时，卸载与回滚都会拒绝递归操作。
