# AI 视频频道生产系统 v0.11.0-rc.2

本预发布版完整保留 `v0.11.0-rc.1` 的发布链，并修复发布中心便携程序在部分新电脑和隔离环境中缺少系统时区数据库的问题。`v0.11.0-rc.1` 保留为历史审计记录，不覆盖、不删除；新安装与升级请使用本版。

## 主要变化

- 非中文正式稿必须具有独立外语质量保险门；缺失或未通过时，不得进入发布准备。
- 所有面向用户的确认卡均为中文优先，并保留目标语言逐项对照。中文翻译只用于审核，不会替换正式配音、字幕、分镜或 YouTube 标题、简介和标签。
- Publish Package v2.1.0 必须包含 `FINAL_CHINESE_REVIEW_CARD.md` 和 `final_chinese_review_card.json`，并锁定故事、标题、简介、Hashtags、封面文案、配音、频道、隐私和上传策略。
- YouTube 发布中心升级为 `0.9.0-rc.2`。MANUAL、SCHEDULED、AUTO 均先停在 `FINAL_CHINESE_REVIEW_CONFIRMATION_REQUIRED`；确认最终中文验收只解除这一项阻断，其他授权和安全门仍独立生效。
- 发布中心便携程序内置时区数据库，在未预装相应系统数据的新电脑上也能正确识别 `Asia/Tokyo` 等 IANA 时区。
- 新漫剧工坊版本保持 `2.4.0-rc.1`，但按系统 `v0.11.0-rc.2` 重新封装并复验完整便携组件：FFmpeg 8.1.1、Python 3.12.3、Node.js 24.15.0、Wenku8 5.1.0 和 Sharp 0.35.3。

## 安装与升级

普通 Windows 用户只需下载 `AI-Video-Channel-Production-Unified-Installer-v0.11.0-rc.2.zip`，完整解压后运行 `install.cmd`。安装器从锁定版本 URL 获取清单，逐项校验文件大小和 SHA-256，再事务式安装全部组件。

已有用户可使用内置“系统更新”Skill，或运行同版安装器升级。升级不迁移、不删除、不覆盖频道、项目、Cookie、OAuth 凭据、任务数据库或其他运行数据。升级完成后必须重启 Codex 并新建任务，同时重新启动新漫剧工坊和 YouTube 发布中心。

## 安全边界

本 Release 不包含 Token、API Key、Cookie、OAuth 凭据、频道、项目、角色、音频、图片、视频或任务数据库。本次验收未执行 Google/YouTube OAuth、真实视频上传、用户数据迁移或远端删除。
