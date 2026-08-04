# v0.8.0-rc.2（本地候选）

## 单一安装入口

- 普通 Windows 用户只需下载统一安装器 ZIP，解压后双击 `install.cmd`。
- 在线模式只从锁定的 `v0.8.0-rc.2` Release URL 获取总清单；离线模式要求总清单和四个组件 ZIP 同目录。
- 每个资产先做大小与 SHA-256 校验，再事务式安装；无需预装 Python、py 或 uv。
- 默认程序根为 `%LOCALAPPDATA%\AIVCP`，用户数据位于独立目录。旧长路径数据不迁移、不删除、不覆盖。

## 本轮组件整合修复

- runtime-bound `.mcp.json` 直接绑定当前安装的 bundled Python，以及安装树内的工坊、FFmpeg、ffprobe、发布中心只读 `channel-list.exe` 和离线 `publish-package-v2.exe`。
- 工坊隔离根固定为 `<DataRoot>\workshop-isolation`；发布中心和 MCP 默认保持 `networkExecution=false`。
- `server.py` 在启动服务前核对缓存插件版本、解释器、安装 marker、install-state、runtime locator、统一 manifest 及其 SHA-256，并要求全部组件处于当前 InstallRoot/DataRoot 的精确受管位置且真实存在。
- 安装、幂等重装、升级、修复和回滚都会在 Codex 注册前重新生成描述符；失败继续恢复 current、marker、locator 和描述符事务状态。
- 安装健康门和 fresh Codex CLI 会实际执行工坊 `health-check` 与 `get-production-capabilities --no-probe`，确认 Production Package 2.1、FFmpeg/ffprobe、发布中心只读接口和 v2 离线桥；不探测收费外部服务，不进行 OAuth 或上传。
- 任一组件路径被改到安装树/数据根外，或缓存/绑定版本过旧，均以 `RUNTIME_BINDING_MISMATCH` 在服务启动前拒绝。

## 既有安全修复

- ZIP 解压剥离上游 archive root，使用短 staging/extract 目录，并在解压前执行 248 字符路径预算。
- Install/Upgrade/Repair/Rollback/Uninstall 使用同一用户全局互斥锁；locator 接管显式可追踪。
- Uninstall 的 `-WhatIf`、程序删除失败和非 owner 卸载不会破坏 locator 或 Codex 注册。
- WinPS 5.1 健康请求继续使用无 BOM JSONL 文件和 ASCII relay，不使用 PowerShell StandardInput、BaseStream 或 StreamWriter；MCP 严格 UTF-8/JSON 规则未放宽。
- Restore `-WhatIf` 零临时目录、零解压并返回 `WHATIF_NO_CHANGE`。

## 作废候选

以下集合全部为 `INVALID_DO_NOT_RELEASE_AS_A_SET`：

- implementation `511954e...`，manifest `cd6fdd...`；
- implementation `421a935...`，manifest `dffd391a...`；
- implementation `5f5955d5f12cfbf5d2a94026ac543b9d043be374`，metadata `cb7d1600958d1363d408cfe4a4d9b84b1816aecc`，manifest SHA-256 `ff30bc2cb55295269fcbb2977ba253f9fecfda888fbf62da6e8162fe77759712`。

冻结 Python、工坊和发布中心只有在新总清单中重新计算一致后才可复用。Sandbox attempt 9 仍只是已作废候选的历史证据；新候选状态保持 `WAITING_FOR_RERUN`。

## 仍需外部批准

GitHub push/tag/Release、代码签名、许可负责人/法律审批、最终干净 Windows/Sandbox、可见 Codex 重启新任务、Google/YouTube OAuth、真实 private 上传、Studio 私有数据和长期学习写回均未执行，不能由本地合成或只读结果替代。
