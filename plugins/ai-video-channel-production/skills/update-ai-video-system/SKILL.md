---
name: update-ai-video-system
description: 检查并更新 AI 视频频道生产系统的已发布版本。用户说“检查更新”“更新到最新版”“更新AI视频频道生产系统”或明确要求检查 stable／prerelease GitHub Release 时使用；检查阶段只读，默认只看稳定版，只有用户明确要求预发布版时才看 prerelease，并且必须在展示版本与统一安装器信息后再次取得本轮明确确认，才能下载、校验并调用现有统一安装器。
---

# 更新 AI 视频频道生产系统

只编排产品内置 GitHub Release 和现有统一安装器。不要从 `main` 安装，不要修改六中心，不要启动 OAuth、上传、数据采集或学习写回。

## 检查

1. 默认使用 `stable`；只有用户明确说“预发布版”“prerelease”或指定 RC 时才使用 `prerelease`。
2. 执行：

   ```powershell
   powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts/Update-AIVideoSystem.ps1 -Action Check -Channel stable
   ```

3. 根据脚本 JSON 显示当前版本、目标版本、Release 变更摘要、统一安装器文件名／大小／SHA-256，以及“用户数据不受此 Skill 直接写入”的说明。
4. `NO_UPDATE` 或 `NO_RELEASE_AVAILABLE` 时停止。`UPDATE_AVAILABLE` 时明确询问：`确认更新到 <targetVersion> 吗？`

“更新到最新版”等最初请求只表示更新意图，不替代查看检查结果后的确认。没有用户本轮再次明确确认时，不得执行更新命令。

## 确认后更新

用户明确确认检查卡中的目标版本后，使用同一通道并锁定该版本执行：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts/Update-AIVideoSystem.ps1 -Action Update -Channel stable -ExpectedVersion <targetVersion> -ConfirmUpdate
```

脚本会重新检查 Release，只下载该 Release 的统一安装器 ZIP，按统一 manifest 校验大小与 SHA-256，再调用 ZIP 内现有 `Install-AIVideoChannelProduction.ps1`。组件下载、安装、修复、事务回滚和用户数据保护全部由现有安装器负责。

更新失败时只报告安装器错误和其已执行的自动恢复，不自行修复或改写用户数据。更新成功后只提示：重启 Codex 并新建对话。

## 永久边界

- 不接受用户临时提供的仓库 URL；产品仓库已内置在脚本中。
- 不访问分支源码，不做后台轮询、计划任务或自动更新。
- 不直接写入频道、项目、凭据、回执、数据中心或其他用户数据路径。
- 不自动启动 Codex、OAuth、真实发布、上传、数据采集或学习写回。
