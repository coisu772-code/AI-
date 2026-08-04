# 阶段 8C 统一安装验收（v0.8.0-rc.2）

## 当前结论

新候选的目标状态是 `LOCAL_UNIFIED_RC_PASS`，完整 MVP 仍为 `WAITING_FOR_CONTROLLED_REAL_ACCEPTANCE`。本轮只在分发仓库修改、构建和测试，不执行 GitHub push/tag/Release、Google/YouTube OAuth、真实上传、正式程序覆盖、用户数据迁移/删除或长期学习写回。

Sandbox attempt 9 对上一套 file-relay 候选是历史 PASS，但该集合后来暴露默认长路径 MAX_PATH 和 Codex 缓存插件无法定位自定义 InstallRoot runtime 两个阻断，因此不批准当前候选。旧 implementation `421a935...` 与 manifest `dffd391a...` 整套为 `INVALID_DO_NOT_RELEASE_AS_A_SET`；更早的 `511954e...` 集合同样保持作废。冻结 Python、工坊和发布中心只在新总清单复算一致后复用。

## 本轮本地硬门

- 默认程序根改为 `%LOCALAPPDATA%\AIVCP`，数据独立；旧长路径下的既有 data 使用 sentinel 证明不迁移、不删除、不覆盖。
- ZIP 解压剥离上游 archive root，短 staging/extract 层为 `.s-xxxxxxxx\x\N`；安装前逐 entry 检查 extraction、staging 和 active 三种路径，248 字符预算超限即在解压前拒绝。
- Install/Upgrade/Repair/Rollback/Uninstall 使用同一用户全局互斥锁。Install 和 Rollback 保存并恢复运行时绑定描述符、marker/locator 精确字节；Rollback 在描述符或 locator 写后故障注入仍恢复旧 current 与 backup candidate。
- locator 接管是显式且可追踪的；幂等重装不会从别的安装静默抢占。Uninstall 在程序删除成功后才实时重查 owner，再决定 locator 与 Codex 注册；`-WhatIf` 和程序删除失败均保持 locator 不变。
- 安装事务在注册前把活动插件 `.mcp.json` 直接绑定到该安装的 `current\runtime\python\python.exe`，参数只引用缓存内 `./mcp/server.py mcp`，环境显式绑定数据/配置根和离线默认；Codex 到 Python 不经过 PowerShell/CMD 代理。真实 Codex CLI 的临时 fresh 会话已经通过 `tools/list` 与 content/production/data 三项调用；Sandbox/可见新任务仍需用最终重锁资产重跑。generic source launcher 仍严格校验自身 manifest、locator、marker、state、activeRoot、bundled Python 和数据根，且 `AIVCP_PYTHON` 不再绕过绑定。
- 已安装/已配置 Python 可用时，Health 不解析损坏或陈旧的其他安装 locator。WinPS 5.1 健康请求继续使用无 BOM JSONL 文件和固定 ASCII relay，不访问 PowerShell StandardInput/BaseStream。
- Restore `-WhatIf` 不创建临时目录、不解压，输出 `WHATIF_NO_CHANGE`；实际恢复才可能输出 `RESTORE_COMPLETE`。
- 完整本地门还包括官方 plugin-creator validator、仓库 marketplace validator、全单元测试、五资产扫描、包内 WinPS relay、默认/自定义/在线/离线生命周期、三市场 publisher 正负夹具、三种 JSON 解析器、发布前置预检和 publish dry-run。

## 绑定模型

统一 installer/core 只绑定实现源码提交；随后审批清单和构建元数据提交单独记录，最终报告不把自身 HEAD 或报告哈希反写进自身，避免循环绑定。具体 implementation/source SHA、metadata SHA、最终 HEAD 和七个资产哈希由最终机器报告及审批清单给出。

## 仍需外部批准或真实环境

当前候选仍需主线程在另一轮干净 Windows 上验证默认路径、无 Python/py/uv、离线首次与幂等安装，并在 Codex 重启和新建任务后验证缓存插件 `tools/list` 与 content/production/data capabilities。发布负责人/法律审核者许可批准、代码签名/发布者身份、GitHub Release、Google/YouTube OAuth、受控 private 上传与真实回执、Studio 私有数据、正式工坊真实服务烟测及长期学习写回均不能由本地合成结果替代。
