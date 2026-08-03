# AI 视频频道生产系统 0.8.0-rc.1

这是阶段8本地 Release Candidate，不是已经发布的 GitHub Release。

本候选包含频道建库与资料库、三种内容路线、目标语言文稿与中文审核稿、发布素材、Production Package v2.1、隔离制作与真实媒体技术门、Publish Package v2 本地安全门、数据快照／报告／建议门，以及完整的 Windows 安装生命周期。

RC 已支持联网和 wheelhouse 断网安装、从 `0.1.0-beta.2` 升级、自动失败回滚、修复、手动回滚、卸载保留用户数据、备份和恢复。安装包不包含两套正式 EXE、数据库、频道资料、凭据、日志或用户媒体。

三市场端到端证据使用清楚标记的 recorded synthetic fixtures 和由 FFmpeg 生成、经 ffprobe 实测的合成媒体。它们证明本地契约、hash、版本、恢复、幂等和隔离，不代表真实上传、真实回执或真实 YouTube Studio 数据。

正式发布仍需用户批准 GitHub push/tag/Release；完整 MVP 仍需在干净电脑完成一次真实测试频道 OAuth、私密上传、Publication Receipt、公开数据快照及用户学习决定。获批前这些项目保持 `AUTH_REQUIRED` 或 `NO-GO`。
