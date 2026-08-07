# AI 视频频道生产系统 v0.11.0-rc.1

本预发布版把“外语正式稿质量确认—中文对照审核—上传前最终中文验收—发布中心安全执行”连成一条不可跳过的发布链，并同步更新统一安装包中的新漫剧工坊与 YouTube 发布中心。

## 主要变化

- 非中文正式稿必须具有独立外语质量保险门；缺失或未通过时，内容不得进入发布准备。
- 所有面向用户的确认卡改为中文优先，并保留目标语言逐项对照。中文翻译只供审核，不会替换正式配音、字幕、分镜或 YouTube 标题、简介和标签。
- 发布包升级为 Publish Package v2.1.0，必须包含 `FINAL_CHINESE_REVIEW_CARD.md` 和 `final_chinese_review_card.json`，并完整锁定故事、标题、简介、Hashtags、封面文案、配音、频道、隐私和上传策略。
- YouTube 发布中心升级为 `0.9.0-rc.1`。MANUAL、SCHEDULED 和 AUTO 均先停在 `FINAL_CHINESE_REVIEW_CONFIRMATION_REQUIRED`；确认最终中文验收只解除这一项阻断，OAuth、频道身份、每日限额等其他安全门仍独立生效。
- 新漫剧工坊升级为 `2.4.0-rc.1`，包含安全书籍导入、本地 TXT/EPUB 导入、Wenku8 本地 CLI、单行字幕、可见动态、宫格预设和 NVIDIA H.264 探测。便携包完整携带 FFmpeg 8.1.1、Python 3.12.3、Node.js 24.15.0、Wenku8 5.1.0 与 Sharp 0.35.3。
- 保留跨电脑工坊隔离交接和发布中心正式交接修复；Codex 交接仍固定离线，不执行 OAuth 或真实上传。

## 安装与升级

普通 Windows 用户只需下载 `AI-Video-Channel-Production-Unified-Installer-v0.11.0-rc.1.zip`，完整解压后运行 `install.cmd`。安装器会获取锁定总清单，逐项校验文件大小和 SHA-256，并事务式安装核心插件、Python 运行时、新漫剧工坊和 YouTube 发布中心。

已有用户可使用内置“系统更新”Skill，或运行同版安装器执行升级。升级不迁移、不删除也不覆盖频道、项目、Cookie、OAuth 凭据、任务数据库或其他运行数据。升级完成后必须重启 Codex 并新建任务；同时重新启动新漫剧工坊和 YouTube 发布中心。

## 安全边界

本 Release 不包含 Token、API Key、Cookie、OAuth 凭据、频道、项目、角色、音频、图片、视频或任务数据库。本次验收没有执行 Google/YouTube OAuth、真实视频上传、用户数据迁移或远端删除。
