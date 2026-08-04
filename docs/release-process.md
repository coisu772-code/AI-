# 统一 Release 流程（RC.2）

CI 只做只读源码预检，不能因 tag 自动发布，也不能在工坊、发布中心或独立运行时缺失时创建不完整 Release。

本地构建必须显式提供三个只读输入目录：冻结工坊资产目录、冻结发布中心资产目录和 Python 3.12.13 独立运行时目录。`tools/Build-UnifiedRelease.ps1` 独立复算两个上游 ZIP，构建核心/入口/运行时，复制冻结资产并生成总清单、`SHA256SUMS.txt` 和机器构建报告。至少在两个空输出目录各构建一次并比较全部资产哈希。

发布前运行：

```powershell
.\tools\Publish-UnifiedRelease.ps1 -AssetRoot <最终资产目录>
```

默认只做 dry-run/preflight，输出 `DRY_RUN_PASS`，不执行 push、tag 或 Release。只有同时传入 `-Execute` 和机器批准文件，且批准文件绑定准确 tag、总清单哈希，并确认发布中心第三方告知、干净 Windows 与代码签名门均已通过时，脚本才会调用 `gh release create` 一次上传全部已验证资产。脚本不会创建或 push tag；批准 tag 必须预先存在。

正式批准前必须关闭以下门：用最终本地 commit 替换清单占位、发布中心第三方许可证告知审查、另一台干净 Windows 验收、代码签名/发布者身份、GitHub Release 批准。OAuth、真实 private 上传、Studio 私有数据和长期学习写回分别需要独立批准，不能由合成测试代替。
