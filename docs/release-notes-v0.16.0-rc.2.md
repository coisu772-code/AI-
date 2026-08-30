# AI 视频频道生产系统 v0.16.0-rc.2 预发布说明

本候选修复自由创作工作区已经确认的正式稿无法直接进入工坊的问题。系统现在会在制作交接时自动生成下游需要的内部 Topic、Manuscript 和 Publishing 兼容合同；这些合同只服务机器读取，不会重新展示旧选题门、要求用户手工补包或改写已经确认的正文。

新制作桥严格绑定当前任务、工作区、项目、频道、正式稿、正式配音稿和交接文件，并在每个边界重新核对路径、版本与 SHA-256。结构化配音行必须与冻结 narration 逐字一致；Production Package 只记录必要的 ID 与哈希，不携带本机绝对路径。非中文正式稿继续要求独立外语质量门和中文审核稿，中文翻译不会替换正式配音、字幕或 YouTube 发布字段。

本版继续分发新漫剧工坊 `2.9.0-rc.1`、YouTube 发布中心 `0.10.0-rc.1`、Publish Package `2.1.0`、Python `3.12.13`、FFmpeg `8.1.2`、Node.js `24.15.0`、Wenku8 `5.1.0` 与 Sharp `0.35.3`。VOICEVOX 继续由工坊内官方 Release 安装入口按用户选择获取；Kokoro CPU、NVIDIA 与 NVIDIA Blackwell 运行包继续复用已校验的 `v0.10.0-rc.1` 公共资产。

本预发布版不包含频道、项目、API Key、Cookie、OAuth 凭据、成片、发布包或运行数据库，不迁移、不删除、不覆盖现有用户数据，也不执行 Google／YouTube OAuth 或真实视频上传。安装或更新后需要完全重启 Codex 并新建任务，才能加载新版 Skills 与 MCP 工具。
