# RC.2 安装、升级、回滚、修复与卸载

## 资产模型

统一 Release 使用一个锁定总清单管理五个 ZIP：明显的安装入口、无大型 EXE 的核心插件、本地 Python 3.12.13 运行时、新漫剧工坊、YouTube 发布中心。FFmpeg 8.1.2 与 ffprobe 是工坊包内的显式受管组件，清单记录两者的逐文件哈希、GPL-3.0 许可证来源和 `-version` 健康检查。

发布中心应用代码沿用产品 `LICENSE.md`。其冻结 ZIP 没有单独的 `LICENSE` 或 `THIRD-PARTY-NOTICES` 文件，因此第三方告知审查是正式 Release 前的人工阻断门；本候选不得表述为已完成合规审查。

## 安装

普通联网用户只下载统一安装入口 ZIP，解压后双击 `install.cmd`。若同目录没有总清单，入口只从版本锁定的 `v0.8.0-rc.2` HTTPS Release URL 获取它，先校验 schema、产品和准确版本，再下载缺失资产；不使用 `latest`。完全离线时必须把总清单和四个组件 ZIP 放在同目录。安装目录和用户数据目录均可自选；两者必须分离。`Auto` 优先本地资产，`Offline` 禁止下载，`Online` 允许从明确 URL 获取缺失资产。

安装器逐项校验文件名、字节数与 SHA-256，预检 ZIP 路径穿越、重复项和符号链接，再解压到临时版本。运行时依赖导入、插件静态结构、32 个本地工具和安全默认值全部健康后才切换 `current`。切换前版本移动到 `backups`；任何失败都恢复原版本。下载脚本、Token、API Key 和用户数据不进入包。

Codex 注册只通过官方 CLI 命令读取仓库内 `.agents/plugins/marketplace.json`，安装器不直接创建或修改个人 marketplace 文件。若 CLI 缺失或命令不兼容，程序仍视为已安装并生成 `CODEX-PLUGIN-SETUP.txt`；按文件执行后必须重启 Codex并新建任务。

## 管理命令

以下命令从已安装版本的 `installer` 目录执行：

```powershell
.\Upgrade-AIVideoChannelProduction.ps1 -ManifestPath <新清单> -AssetRoot <资产目录>
.\Repair-AIVideoChannelProduction.ps1 -ManifestPath <同版清单> -AssetRoot <资产目录>
.\Rollback-AIVideoChannelProduction.ps1 -Confirm:$false
.\Test-AIVideoChannelProductionHealth.ps1 -AsJson
.\Uninstall-AIVideoChannelProduction.ps1 -Confirm:$false
```

升级和修复复用同一个事务式安装器。重复安装同一清单是幂等校验。回滚只切换程序版本，不回退或迁移用户数据。卸载默认移除程序目录并保留独立用户数据；删除用户数据必须由用户另行明确决定。

## 当前未执行

本地验证没有 push、tag、GitHub Release、Google/YouTube OAuth、真实上传、正式 EXE 覆盖、用户数据迁移/删除或长期学习写回。真实干净 Windows、受控 private 上传与 Studio 私有数据验收见 RC.2 人工矩阵。
