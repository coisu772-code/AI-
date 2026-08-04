# 阶段 8C 统一安装验收（v0.8.0-rc.2）

## 结论

本地统一 RC 状态为 `LOCAL_UNIFIED_RC_PASS`，完整 MVP 状态仍为 `WAITING_FOR_CONTROLLED_REAL_ACCEPTANCE`。五个发布资产、单文件联网入口、完全离线入口、独立 Python 运行时、工坊、发布中心和显式 FFmpeg 组件已经整合。未执行 GitHub push/tag/Release、Google/YouTube OAuth、真实上传、正式程序覆盖、用户数据迁移/删除或长期学习写回。

## 本地已证明

- 插件 manifest 与仓库 marketplace 结构通过校验；未写个人 marketplace。
- 144 项单元测试通过，2 项需要正式发布中心 CLI 的旧环境用例按条件跳过；仓库安全检查覆盖 317 个文件。
- 五资产安全扫描通过：核心 ZIP 无大型 EXE，包内无凭据、用户数据和开发机绝对路径。
- Stage6 约束目录已按发布中心嵌入的 CRLF 精确字节重新锁定为 `a57cf04014db7512b420771fe9f412e47a3bd69048b0d34fc9c4765085ad5e13`；三个市场包由发布中心 CLI 独立验证通过，旧 `28788480...` 目录仍以 `CONSTRAINTS_CATALOG_MISMATCH` 拒绝。
- 两次空目录构建的入口、核心、Python 运行时、工坊、发布中心、总清单和校验和哈希完全一致。
- 隔离生命周期实际覆盖：单文件伪在线清单下载、完全离线、无 Python/uv、中文/空格路径、重复安装、篡改拒绝、升级、故障回滚、显式回滚、修复、Codex CLI 缺失说明、卸载保留数据。
- 日/中/英三市场 recorded-synthetic 链通过；网络执行、OAuth、真实上传、真实回执、Studio 私有数据与长期学习写回均为 false。
- 本地发布脚本 dry-run 通过；CI 只有只读源码预检，不能自动发布缺少桌面资产的 Release。
- 统一入口和核心资产已绑定 implementation/source commit `421a935030ca5fa63a87c214c95ba7db7291248e`；后续仅含绑定与发行哈希的 metadata commit 不会冒充资产源码绑定。总清单不存在 commit 占位，发布预检会拒绝占位清单。此项是已完成的本地证据，不是外部批准门。

后续提交只更新绑定工具、报告或验收元数据，属于 metadata commits；机器报告记录当前 metadata HEAD，但不把报告文件哈希或当前 HEAD 反写进自身，因此没有自绑定循环。

## 许可证边界

工坊包含应用许可证、FFmpeg GPLv3 文本及 Gyan build README。Python 运行时含 Python `LICENSE.txt`，12 个包的 58 个许可证条目均有声明和许可证文件。发布中心包含产品 `LICENSE.md`、JSON/Markdown 第三方告知及 101 份第三方许可证文本，机器清单 `REVIEW_REQUIRED=0`。三套技术库存均已验证，但正式 Release 仍需发布负责人/法律审核者批准；本地技术验证不构成法律意见或签署。

## 尚需外部批准/环境

发布负责人/法律审核者许可批准、另一台干净 Windows 安装、代码签名与发布者身份、预先存在的发布 tag 到已绑定源码历史的核对、GitHub Release、Google/YouTube OAuth、受控 private 上传与真实回执、Studio 私有数据、正式工坊真实服务烟测和长期学习写回，均不能由本地合成结果代替。机器批准清单和真实验收矩阵分别见 `final-acceptance-approval-checklist-v0.8.0-rc.2.json` 与 `real-acceptance-matrix-v0.8.0-rc.2.json`。

Windows Sandbox attempt 7（Windows 11 Enterprise 22621、WinPS 5.1、无 Python/py/uv、网络禁用）否决了上一套候选：仅访问 PowerShell 的重定向输入对象，就把预期 `58 0a` 的探针变成 `ef bb bf 58 0a`，严格 MCP UTF-8/JSON 解析因此返回 `-32700 Parse error`；同一包内 Python 与 `server.py` 通过无 BOM JSONL 请求文件和 Python relay 立即成功，`fileRelay.exitCode=0`。新修复彻底不创建、不访问 PowerShell 输入重定向对象；每次请求使用唯一临时目录、无 BOM UTF-8 JSONL、固定 ASCII relay，并在 `finally` 清理。服务端解析规则未放宽。本地 WinPS 5.1 源码与最终包回归必须通过，但 Sandbox 状态仍为 `WAITING_FOR_RERUN`，主线程第三轮重跑前不得标为 PASS。旧 implementation `511954e...` / installer `69099e...` / core `c00c49...` / manifest `cd6fdd...` / SHA256SUMS `99a9a4...` 整套已标为 `INVALID_DO_NOT_RELEASE_AS_A_SET`；冻结 Python、工坊和发布中心仅在复算一致后复用。
