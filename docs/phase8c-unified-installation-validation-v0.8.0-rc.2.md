# 阶段 8C 统一安装与组件整合验收（v0.8.0-rc.2）

## 当前结论

本地目标状态为 `LOCAL_UNIFIED_RC_PASS`，完整 MVP 仍为 `WAITING_FOR_CONTROLLED_REAL_ACCEPTANCE`。本阶段只修改、构建和测试分发仓库；未执行 GitHub push/tag/Release、OAuth、上传、正式程序覆盖、用户数据迁移/删除或长期学习写回。

真实受控验收确认旧 implementation `5f5955d...` 的新 Codex 任务能够加载 MCP，但描述符没有绑定已安装工坊、FFmpeg/ffprobe 和发布中心 CLI，导致 `workshopBridgeConfigured=false`。该 implementation 与 manifest `ff30bc2...` 已整套作废，不得发布。

## 本轮本地硬门

- 描述符精确绑定 bundled Python、工坊、FFmpeg、ffprobe、发布中心只读 CLI、发布中心 v2 CLI、独立数据根和工坊隔离根。
- 安装时对 staging 中同一相对位置验真；激活后服务启动前重新验证 current、marker、state、locator、manifest、版本、解释器和组件文件。
- WinPS 5.1 脚本不硬编码中文 EXE 字面量，而从已验证工坊根中唯一的顶层 EXE 取得原始文件名；Python 运行时仍要求最终精确受管路径。
- 安装健康门实际运行工坊 `health-check` 与 `get-production-capabilities --no-probe`，要求 `workshopBridgeConfigured=true`、Production Package 2.1、FFmpeg/ffprobe 可用且 `externalServiceProbeExecuted=false`。
- `system_capabilities` 必须显示发布中心只读接口与 v2 离线桥已配置，且网络执行为 false。
- fresh cached plugin 和真实 Codex CLI 均调用 system/content/production/data capabilities；真实 CLI 有 90 秒硬超时和按 PID 的进程树清理。
- 六个组件路径外移和旧版本绑定共七个负例全部必须在服务启动前拒绝。
- 默认/自定义 Unicode 路径、在线/离线、幂等、升级、修复、回滚、篡改、故障恢复和卸载保留数据继续通过。

## 非循环绑定

installer/core 绑定新的 implementation/source commit。随后审批清单与测试元数据使用单独 metadata commit 记录；最终资产清单再由独立 asset-record commit 落库。报告不绑定自身最终 HEAD 或自身哈希。

## 仍需外部批准或真实环境

主线程需用新候选重新运行干净 Windows/Sandbox，并在 Codex 重启后新建可见任务复核组件能力。许可负责人/法律审批、代码签名、GitHub Release、Google/YouTube OAuth、受控 private 上传与真实回执、Studio 私有数据和长期学习写回仍是外部门。
