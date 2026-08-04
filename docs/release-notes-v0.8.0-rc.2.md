# v0.8.0-rc.2（本地候选）

- 提供单文件 Windows 统一安装入口、锁定总清单和离线同目录安装。
- 工坊 2.1.0-stage5、发布中心 0.8.0-rc.2、Python 3.12.13 runtime 及 FFmpeg/ffprobe 成为受管 Release 资产；无需预装 Python 或 uv。
- 默认程序根缩短为 `%LOCALAPPDATA%\AIVCP`，数据保留在独立目录；旧长路径下的既有 data 不迁移、不删除、不覆盖。
- 解压剥离上游 archive root，使用短 staging/extract 目录，并在解压前对全部 entry 执行 248 字符路径预算门。
- 新增同一用户全局安装互斥锁；Install 和 Rollback 对 current、marker、locator 做事务恢复；Uninstall 的 `-WhatIf`、程序删除失败和非 owner 卸载不会破坏 locator 或 Codex 注册。
- 新增事务式 runtime-bound MCP 描述符：在 Codex 缓存前把插件直接绑定到任意受支持 InstallRoot 下的 bundled Python、缓存相对 server.py 和独立数据根，不经过 PowerShell/CMD 代理；locator 继续承担所有权、修复和严格 fallback 校验。
- Health 在当前安装 Python 可用时不解析无关全局 locator；Restore `-WhatIf` 零临时目录、零解压并返回正确的未变更状态。
- 保留 Windows PowerShell 5.1 无 BOM JSONL 文件 relay：健康脚本不使用 PowerShell StandardInput、BaseStream 或 StreamWriter，严格 MCP UTF-8/JSON 解析规则未放宽。
- CI 只做只读预检；正式 tag/Release、许可批准、代码签名、OAuth、真实上传、Studio 私有数据和长期学习写回仍需外部批准。

作废链：implementation `511954e...` 对应的 `69099e/c00c49/cd6fdd/99a9a4` 集合，以及 implementation `421a935...` 对应的 installer `cf5cb7...`、core `440570...`、manifest `dffd391a...` 集合，均为 `INVALID_DO_NOT_RELEASE_AS_A_SET`。冻结 Python、工坊和发布中心只有在新总清单中复算一致后才可复用。Sandbox attempt 9 的 file-relay/短路径受控结果保留为历史 PASS，但不能替代本轮默认路径与重启后缓存插件的新候选重跑；当前状态仍是 `WAITING_FOR_RERUN`。
