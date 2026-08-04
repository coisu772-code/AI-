# v0.8.0-rc.2（本地候选）

- 新增面向普通 Windows 用户的统一安装入口和锁定总清单。
- 工坊 2.1.0-stage5、发布中心 0.8.0-rc.2、Python 3.12.13 运行时成为 Release 受管资产，不再标为 external baseline。
- 安装无需预装 Python 或 uv；FFmpeg/ffprobe 的哈希、许可证和健康检查显式记录。
- 支持同目录离线资产或受锁定清单控制的在线缺失下载，并覆盖校验、事务安装、自动回滚、幂等重装、升级、修复、回滚及卸载保留数据。
- Codex CLI 不可用时降级为明确的手动注册说明，不回滚健康程序。
- CI 改为只读预检；正式 tag/Release 必须使用本地完整资产并获得单独批准。

限制：发布中心仍是 `CANDIDATE_READY_FOR_CONTROLLED_REAL_ACCEPTANCE`。未执行 OAuth、真实上传、真实 Studio 数据读取或长期学习写回。发布中心 ZIP 未单列第三方告知文件，正式 Release 前必须人工审查。
