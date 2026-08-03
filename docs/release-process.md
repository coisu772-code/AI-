# Release Candidate 发布流程与门禁

`0.8.0-rc.1` 当前只形成本地候选。未经用户明确授权，不 push、不打 tag、不创建 GitHub Release，也不把草案清单改成 published。

## 本地 RC 门

1. 更新当前插件、服务、项目版本和 `release-v0.8.0-rc.1.json`。
2. 运行 `tools/update_release_manifest.py`，再验证 canonical manifest hash 和四类内置工件目录 hash。
3. 连续运行阶段1–8脚本和全仓单元测试；阶段2注入正式发布中心只读 CLI 时，真实数据库前后 hash 必须不变。
4. 用 `tools/Build-ReleaseCandidate.ps1` 构建两次 ZIP，确认 SHA-256 完全一致。
5. 验证 ZIP 内部 `RC-ASSET-MANIFEST.json`、外部 `SHA256SUMS.txt`、路径穿越／重复项、Unicode／空格路径和敏感信息扫描。
6. 核对安装、旧版升级、故意失败自动回滚、修复、卸载保留数据、备份、恢复和新任务重新绑定频道。
7. 核对三市场 recorded synthetic 链，所有真实上传／Studio 字段必须保持 false 或 null。
8. 核对 `final-acceptance-approval-checklist-v0.8.0-rc.1.json` 六个外部门全部 `executed=false`。

## ZIP 可复现规则

ZIP 项按 Unicode 序数路径排序，统一使用 `2026-08-04T00:00:00` 固定时间、UTF-8 名称、固定权限和 Deflate 9。文本移除 UTF-8 BOM并统一 LF；二进制保持原字节。阶段验证报告不进入普通安装 ZIP，避免本地证据路径和构建结果形成自引用。相同工作树构建两次必须得到相同 SHA-256。

目录工件仍使用 `relative/path<TAB>normalized-size<TAB>sha256<LF>` 排序聚合规则。Release manifest 自身使用 `canonical-json-v1`，移除 `contentHash` 后按 key 排序、紧凑 UTF-8 JSON 求 SHA-256。

## 获得一次性最终验收授权后

1. 运行 `tools/Test-FinalAcceptancePrerequisites.ps1 -ReleaseCandidateZip <RC> -AsJson`，状态必须是 `READY_FOR_USER_AUTHORIZATION`。
2. 按 `docs/final-live-acceptance-runbook-v0.8.0-rc.1.md` 在干净 Windows 测试机和指定私密测试频道执行真实闭环。
3. 取得真实 Publication Receipt v1、video ID、目标频道回读和公开数据快照；owner Analytics 没有独立授权时保持 `AUTH_REQUIRED`。
4. 把真实证据追加到阶段8报告。任一真实门未通过时不得把完整 MVP 改为 GO。
5. 用户再次核对最终提交和 RC SHA-256 后，才允许 push、创建 `v0.8.0-rc.1` tag 和 GitHub prerelease。
6. GitHub Actions 必须重新跑仓库验证、构建同 hash 资产并上传 ZIP 与 `SHA256SUMS.txt`。Release 页面先保持 prerelease；干净机器 GitHub 下载安装复验通过后再决定是否发布稳定版。

两套正式 EXE、用户频道库、凭据、数据库、项目、媒体和日志从不进入 GitHub 资产。正式程序覆盖、OAuth、上传、迁移和长期学习分别受机器审批表约束，不能由 Release 授权推定。
