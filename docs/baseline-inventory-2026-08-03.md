# 阶段 1 基线盘点（2026-08-03）

本记录是阶段 1 开始前的只读快照。盘点没有读取凭据内容，没有迁移用户资料，也没有修改三个既有组件仓库。

## 组件与 Git 状态

| 组件 | 路径 | 版本基线 | Git 基线 | 当时状态 |
| --- | --- | --- | --- | --- |
| 工作区／控制中心 | `E:\小说漫全自动化生产` | 控制中心 `0.11.0`，Python `>=3.10` | `main` / `2949fd70cc30ed9d68f025ca6a677060ba826abd` | 已有 34 个受跟踪改动、1122 个未跟踪项；无 `origin` |
| 新漫剧工坊源码 | `E:\新漫剧工坊` | Wails 产品版本 `1.0.0`；前端包 `0.1.0` | `codex/backup-before-creator-studio-phase2-20260613` / `c649d68279bbefe6c71310ecd85a8acb9d53d9b3` | 已有 18 个受跟踪改动、41 个未跟踪项；现有远端仍指向旧名称仓库，本阶段不使用 |
| YouTube 发布中心源码 | `E:\YouTube视频自动上传\youtube-publisher-center` | Wails 产品版本 `0.1.0`；前端包 `0.0.0` | 父仓库 `E:\YouTube视频自动上传` 的 `master` / `5909e8de2e30fa331c1b86e1a4a56012fe7483d3` | 已有 15 个受跟踪改动、46 个未跟踪项；无 `origin` |
| 现有 Skills | 工作区 Skills 清单 | 35 个 Skill，其中 16 个项目 Skill | 不适用 | 只读登记，未复制用户运行数据 |
| 旧本地安装包 | `distribution/friend-beta` | `0.1.0` | 工作区内既有文件 | 保留不改；其旧插件缺少 Skill 且默认提示超过当前规范上限，不能作为新骨架 |

## 当前可运行程序

| 程序 | 文件 | SHA-256 | 大小 |
| --- | --- | --- | --- |
| 新漫剧工坊 | `E:\小说漫全自动化生产\apps\新漫剧工坊\ZMS\Z 漫剧工坊.exe` | `2c168cf5e1a886427fc564fc0d381d7a0915786a6d6ad10dec04131bb9d786a4` | 18,625,536 字节 |
| YouTube 发布中心 | `E:\YouTube视频自动上传\youtube-publisher-center\build\bin\YouTube 发布中心.exe` | `ae02ee691d9ee52f819827115aa6cd4216c1f2053fe604246c282cbeb304b7e0` | 27,251,200 字节 |

## 只读基线验证

- 新漫剧工坊：`go test ./...` 通过；前端构建通过。
- YouTube 发布中心：前端构建通过；Go 测试有 2 个既有失败。失败来自测试夹具中的伪 MP4 被真实 FFprobe 判定为缺少 `moov atom`，不属于阶段 1 发布骨架改动。
- 控制中心：当前项目环境没有安装 `pytest`，测试在收集前即停止。这是基线环境缺口；阶段 1 不修改控制中心依赖。

## 受保护范围

以下内容禁止进入本发布仓库，也不属于阶段 1 的读写目标：

- 工作区的 `apps/`、`runtime/`、`projects/`、`outputs/`、`logs/`；
- 本地配置中的密钥、Token、Cookie、OAuth 文件、频道凭据和设备绑定；
- 活动数据库、队列、任务状态、成片、音频、图片和缓存；
- 新漫剧工坊与发布中心的用户数据目录；
- 旧仓库 `D:\Backup\Documents\Z_Manga_Workshop_GitHub_Clean` 与任何旧版自动化压缩包。

阶段 1 的新增文件全部限定在 `E:\小说漫全自动化生产\distribution\novel-manga-production`。
