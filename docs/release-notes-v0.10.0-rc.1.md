# AI 视频频道生产系统 v0.10.0-rc.1

这是一个 Windows prerelease 候选，重点补齐新漫剧工坊的一键本地 Kokoro 语音运行时和统一 Release 分发链路。

## 本次包含

- AI 视频频道生产系统核心插件 `0.10.0-rc.1`。
- 新漫剧工坊 `2.3.0-rc.1`，支持 VOICEVOX，以及 Kokoro-FastAPI 的 CPU、NVIDIA、NVIDIA Blackwell 三种一键安装选择。
- 已发布并重新验收的 YouTube 发布中心 `0.8.0-rc.2`。
- 独立 Python 3.12.13 runtime 与 FFmpeg/ffprobe 8.1.1。
- 三套可选 Kokoro 运行包的 JSON 清单和分卷附件；工坊按用户选择下载，不随统一安装默认落盘。

## 安装与更新

联网用户下载统一安装器 ZIP，解压后双击 `install.cmd`。安装器只从该版本锁定的 GitHub Release URL 读取总清单，校验所有核心资产的文件名、大小和 SHA-256 后事务式安装。Kokoro 运行包由工坊在用户明确选择后单独下载，并再次校验分卷和整包哈希。

安装或更新插件后需要重启 Codex，并新建任务，使新插件版本和 MCP 运行时绑定生效。仅在工坊内新增或切换 Kokoro 运行包、且系统插件版本没有变化时，不需要重启 Codex。

## 数据与安全边界

发布资产不包含频道、项目、成品、凭据、Token、API Key、OAuth 会话或运行数据。升级、修复、回滚和卸载继续把程序目录与用户数据目录分离，不迁移、覆盖或删除现有用户数据。本地验收未执行 Google/YouTube OAuth、真实上传、Studio 私有数据读取或长期学习写回。

## 发布门

GitHub 推送、标签和 Release 创建必须在完整本地验收通过后，取得针对本候选版本、清单哈希和源提交的明确发布确认。代码签名、发布许可负责人批准、干净 Windows 验收、真实 private 上传、Studio 数据与长期学习写回仍是各自独立的外部门。
