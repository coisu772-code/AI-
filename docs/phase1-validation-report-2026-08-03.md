# 阶段 1 发布与验收报告（2026-08-03）

## 结论

阶段 1 Beta `0.1.0-beta.2` 已完成发布与安装验收，且没有进入阶段 2。插件、marketplace、安装生命周期、10 类跨中心契约、统一发布清单和最小自动验证均已落地。

GitHub 首次推送、Beta 预发布、标签来源安装和 Release 压缩包安装／卸载均已通过。所有安装验收均使用仓库内的隔离目录，没有改动真实用户 Codex 配置、用户资料或凭据。

## 已通过项目

| 验收项 | 结果 | 证据 |
| --- | --- | --- |
| marketplace 与插件结构 | 通过 | 本地校验器验证名称、来源路径、版本、默认提示数量和两项 Skill 策略 |
| Codex 实际发现与安装 | 通过 | 使用隔离 `CODEX_HOME` 添加本地 marketplace、发现插件、安装并确认已启用；真实用户配置未改动 |
| 核心契约结构 | 通过 | 10 个 JSON Schema 和 10 个有效示例全部通过 Draft 2020-12 校验 |
| 自身内容哈希 | 通过 | 所有示例按 `canonical-json-v1` 复算一致 |
| 上游引用 | 通过 | 完整示例链可解析；负向测试能拒绝错误上游哈希 |
| 必填字段 | 通过 | 负向测试能拒绝缺少必填字段的对象 |
| 统一发布清单 | 通过 | 产品、组件、协议、Schema、工件目录哈希与清单自身哈希一致 |
| 仓库安全 | 通过 | 未发现凭据型文件名、私钥材料、数据库、可执行文件或媒体资产 |
| 安装生命周期 | 通过 | 隔离目录安装、幂等重装、强制升级备份、回滚和卸载均通过 |
| 自动化入口 | 通过 | Windows 本地脚本和 GitHub Actions 工作流均已提供 |
| GitHub Actions | 通过 | Beta 2 的 `validate` 与 `beta-release` 工作流均成功完成 |
| GitHub 标签来源安装 | 通过 | 隔离 `CODEX_HOME` 从 `v0.1.0-beta.2` 添加远端 marketplace，发现、安装并启用 Beta 2 插件 |
| GitHub Release 安装包 | 通过 | 下载 ZIP 与 `SHA256SUMS.txt`，校验哈希后完成安装、状态核对和卸载 |

本地完整验收命令：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\tools\Test-Stage1.ps1
```

最近一次结果：插件检查通过，10 个示例通过，发布清单通过，仓库安全检查通过，6 个单元测试通过，安装生命周期和隔离 Codex 加载通过，测试目录已清除。

## GitHub 发布与外部安装验收

- 仓库：[`coisu772-code/AI-`](https://github.com/coisu772-code/AI-)
- Beta 预发布：[`v0.1.0-beta.2`](https://github.com/coisu772-code/AI-/releases/tag/v0.1.0-beta.2)，状态为非草稿预发布，发布时间为 `2026-08-03T16:10:46Z`。
- 标签提交：`2a5b69adb5c28e2f54b53238aa0c3ce72d5975aa`；发布清单绑定并在干净克隆中复验通过的源码提交为 `acb8586775804bec25d05cdca74c2d141dea9878`。
- 工作流：[`validate`](https://github.com/coisu772-code/AI-/actions/runs/30830889758) 与 [`beta-release`](https://github.com/coisu772-code/AI-/actions/runs/30830892649) 均为 `success`。
- 发布附件：`ai-video-channel-production-v0.1.0-beta.2.zip`（52,889 字节）和 `SHA256SUMS.txt`。
- 远端 ZIP SHA-256：`7c1e851c12e87db7f562b19b78d6140721926d3f6db5979949f573697fa9a767`，与远端校验文件一致。
- Codex 标签来源验收：使用隔离 `CODEX_HOME` 执行 marketplace 添加、可用插件发现、插件安装和启用状态检查，版本均为 `0.1.0-beta.2`。
- Release 包验收：从发布页重新下载附件，校验 SHA-256，运行包内安装器，确认 `productId=ai-video-channel-production`、`productVersion=0.1.0-beta.2`，再运行卸载器并确认程序目录已移除。
- 验收后已删除仓库内的隔离测试目录；真实用户 Codex 配置、频道数据和凭据均未触碰。

## 真实起点差异与处理

1. 旧 `distribution/friend-beta` 插件没有实际 Skills，且默认提示数超过当前官方规范；新候选使用独立目录建立，没有覆写旧包。
2. 当前桌面应用 PATH 首选的 Codex CLI 只暴露 marketplace 子命令，而同一桌面安装的较新本地 CLI 已支持插件添加与列表。安装器会只读探测候选并选择具备插件安装能力的版本；没有兼容 CLI 时明确失败，不假报成功。
3. 控制中心基线环境缺少 `pytest`；发布中心有 2 个与伪 MP4/真实 FFprobe 有关的既有测试失败。两项均已登记，本阶段没有跨范围修复。
4. 三个既有组件均有用户未提交改动；阶段 1 没有改动它们，也没有使用旧工坊仓库。

## 发布状态与剩余边界

- GitHub 远端由用户创建为 `coisu772-code/AI-`；与阶段 0 预定仓库名的差异已通过变更记录冻结。
- `main` 已完成首次推送，源码基线为 `caae41e8a09c3267310a0f39ad46b6da16f775da`。
- Git 作者由用户确认并设置为 `Codex <coisu772@gmail.com>`。
- `v0.1.0-beta.1` 标签的跨平台目录哈希检查失败，未创建 Release；标签保留作为失败构建记录。
- `v0.1.0-beta.2` 修复换行规范化后，GitHub Actions 全量验证、打包与预发布均已成功。
- Beta 2 发布清单状态为 `published`，并绑定干净克隆复验通过的源码提交 `acb8586775804bec25d05cdca74c2d141dea9878`。
- GitHub 标签来源和 Release 压缩包均已在发布后独立复验，不以工作流启动代替验收成功。
- 本地工具服务、频道读取接口和频道资料库仍为明确的阶段 2 范围。

## 阶段 2 进入条件

只有以下条件同时成立，才能在新的实施任务中进入阶段 2：

1. 用户验收并冻结阶段 1 的契约主版本、插件标识和安装目录约定。
2. 阶段 1 本地候选保持全量验证通过，没有未解释的哈希或安全失败。
3. GitHub Beta 与 GitHub 来源安装验收均成功，并保存版本、标签、工件哈希与验证结果。
4. 阶段 2 只实现已冻结规划中的发布中心频道只读接口、频道资料库创建／绑定／备份／恢复和确认卡，不夹带阶段 3 采集或阶段 4 内容生产。
5. 继续保护现有凭据、用户资料、项目、成片和活动数据库，并为任何迁移先建立可回滚方案。

本报告收口后不自动启动阶段 2。
