# 统一 Release 流程（RC.2）

CI 只做只读源码预检，不因 tag 自动发布，也不在工坊、发布中心或独立 runtime 缺失时创建不完整 Release。

本地构建必须显式提供三个只读输入：冻结工坊资产目录、冻结发布中心资产目录和 Python 3.12.13 独立 runtime。`tools/Build-UnifiedRelease.ps1` 复算上游 ZIP，构建 core/installer/runtime，复制冻结资产并生成总清单、`SHA256SUMS.txt` 和机器构建报告。至少在两个空输出目录各构建一次并比较七个 Release 文件的哈希。

正式发布前运行：

```powershell
.\tools\Publish-UnifiedRelease.ps1 -AssetRoot <最终资产目录>
```

默认只做 dry-run/preflight，输出 `DRY_RUN_PASS`，不执行 push、tag 或 Release。只有同时传入 `-Execute` 和机器批准文件，且批准文件绑定精确 tag、总清单哈希与 implementation/source commit，并把许可负责人、干净 Windows、代码签名和 GitHub Release 批准全部设为 `true`，脚本才会调用一次 `gh release create` 上传全部已验证资产。执行分支还会确认预先存在的 tag 精确解析到绑定 implementation/source commit；脚本不会创建或 push tag。

installer/core 的 implementation/source commit、绑定 metadata commit 和最终报告 HEAD 分开记录。metadata/报告提交不得冒充资产源码，报告不把自身 HEAD 或哈希反写进自身。精确 SHA 见统一总清单、最终审批清单和机器验证报告。

正式批准前仍须关闭：发布负责人/法律审核者许可批准、当前候选干净 Windows 默认路径重跑、Codex 重启与新任务缓存插件检查、代码签名/发布者身份和 GitHub Release 批准。OAuth、真实 private 上传、Studio 私有数据和长期学习写回分别需要独立批准，不能由合成测试替代。
