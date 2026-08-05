# AI 视频频道生产系统 v0.10.1-rc.1

这是一个 Windows 预发布版本，重点修复新电脑上的 YouTube 资料读取和工坊 Kokoro 本地配音一键安装。

## 本次修复

- 统一安装包内置并锁定 `yt-dlp 2026.7.4`、`yt-dlp-ejs 0.8.0` 与 `Deno 2.9.4`。系统不再依赖用户电脑预先安装下载器、Python、Node.js 或浏览器扩展。
- 安装器把视频采集命令固定到本版本自带的 Python、Deno 与工坊 FFmpeg；安装、升级、修复、启动和健康检查都会核对文件大小、SHA-256 与运行时清单。
- 新漫剧工坊升级为 `2.3.1-rc.1`。Kokoro 的清单和所有分卷现在必须来自同一个公开的 AI 视频频道生产系统 Release，并同时校验仓库、标签、文件名、大小和摘要。
- 修复工坊界面显示“Release 附件地址不是受信任的 GitHub 官方地址”而无法一键安装 Kokoro 的问题。

## 资产复用

Kokoro CPU、NVIDIA 与 NVIDIA Blackwell 三套大型运行包内容没有变化，继续复用 `v0.10.0-rc.1` 中已发布并逐项 SHA-256 锁定的公开资产。本次 Release 不重复上传 10GB 以上相同文件；工坊会从公开 Release 列表中选择包含完整清单和分卷的受信版本。

YouTube 发布中心继续复用已经重新校验的 `0.8.0-rc.2` 组件。

## 安装或升级

普通用户只需下载 `AI-Video-Channel-Production-Unified-Installer-v0.10.1-rc.1.zip`，完整解压后运行 `install.cmd`。已有用户可在 Codex 中使用内置“系统更新”Skill 升级，频道、项目、凭据和运行数据不会被打包或覆盖。

## 安全边界

本 Release 不包含 Token、API Key、Google/YouTube OAuth 凭据、频道资料、项目或运行数据。发布验收没有执行 Google/YouTube OAuth、真实视频上传、用户数据迁移或长期频道学习写入。
