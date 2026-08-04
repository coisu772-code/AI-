# 统一 Release 流程（RC.2）

CI 只做只读源码预检，不能因 tag 自动发布，也不能在工坊、发布中心或独立运行时缺失时创建不完整 Release。

本地构建必须显式提供三个只读输入目录：冻结工坊资产目录、冻结发布中心资产目录和 Python 3.12.13 独立运行时目录。`tools/Build-UnifiedRelease.ps1` 独立复算两个上游 ZIP，构建核心/入口/运行时，复制冻结资产并生成总清单、`SHA256SUMS.txt` 和机器构建报告。至少在两个空输出目录各构建一次并比较全部资产哈希。

发布前运行：

```powershell
.\tools\Publish-UnifiedRelease.ps1 -AssetRoot <最终资产目录>
```

默认只做 dry-run/preflight，输出 `DRY_RUN_PASS`，不执行 push、tag 或 Release。只有同时传入 `-Execute` 和机器批准文件，且批准文件绑定准确 tag、总清单哈希、implementation/source commit，并把 `releaseLicenseOwnerApproved`、`cleanWindowsApproved`、`codeSigningApproved`、`githubReleaseApproved` 全部设为 `true` 时，脚本才会调用 `gh release create` 一次上传全部已验证资产。执行分支还会确认预先存在的 tag 正好解析到总清单绑定的 implementation/source commit；脚本不会创建或 push tag。

本地绑定已完成：安装入口和核心的 implementation/source commit 是 `fe4490a5b653f61f67a92584b72ddc788abe1695`；绑定元数据 commit 由总清单的 `source.metadataCommit` 精确记录，后续报告或哈希提交不自绑定为资产源码。正式批准前仍须关闭：技术库存基础上的发布负责人/法律审核者许可批准、另一台干净 Windows 验收、代码签名/发布者身份和 GitHub Release 批准。OAuth、真实 private 上传、Studio 私有数据和长期学习写回分别需要独立批准，不能由合成测试代替。
