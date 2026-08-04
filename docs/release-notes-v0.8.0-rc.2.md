# v0.8.0-rc.2（本地候选）

- 新增面向普通 Windows 用户的统一安装入口和锁定总清单。
- 工坊 2.1.0-stage5、发布中心 0.8.0-rc.2、Python 3.12.13 运行时成为 Release 受管资产，不再标为 external baseline。
- 安装无需预装 Python 或 uv；FFmpeg/ffprobe 的哈希、许可证和健康检查显式记录。
- 支持同目录离线资产或受锁定清单控制的在线缺失下载，并覆盖校验、事务安装、自动回滚、幂等重装、升级、修复、回滚及卸载保留数据。
- Codex CLI 不可用时降级为明确的手动注册说明，不回滚健康程序。
- CI 改为只读预检；正式 tag/Release 必须使用本地完整资产并获得单独批准。
- 修复 Windows Sandbox/Windows PowerShell 5.1 中 MCP JSON-RPC 传输缺陷：健康检查不再创建或访问 PowerShell 输入重定向对象，而是写入无 BOM UTF-8 JSONL 请求文件，并由固定 ASCII Python relay 把原始字节交给严格 MCP 服务；服务端 UTF-8/JSON 解析规则没有放宽。

限制：Windows Sandbox attempt 7 是原始 `FAIL`；原始探针记录 `rawStdinProbeHex=efbbbf580a`，文件 relay 对照为 `exitCode=0`。新候选必须再次受控运行，不能由本地回归测试标为 PASS。旧 implementation `511954e...`、installer `69099e...`、core `c00c49...`、manifest `cd6fdd...`、SHA256SUMS `99a9a4...` 整套已标为 `INVALID_DO_NOT_RELEASE_AS_A_SET`；冻结 Python、工坊和发布中心经复算后可复用。发布中心仍是 `CANDIDATE_READY_FOR_CONTROLLED_REAL_ACCEPTANCE`；未执行 OAuth、真实上传、真实 Studio 数据读取或长期学习写回。发布中心 ZIP 已包含产品许可证、JSON/Markdown 告知和 101 份第三方许可证文本，Python 运行时 12 个包的 58 个许可证条目也已技术核对；这些证据不构成法律意见，正式 Release 仍需发布负责人/法律审核者批准。
