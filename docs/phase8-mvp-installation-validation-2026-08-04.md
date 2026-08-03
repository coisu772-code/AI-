# 阶段 8：AI 视频频道生产系统 MVP 安装验收

## 验收结论

- **本地可发布候选：GO。** `v0.8.0-rc.1` 已完成隔离安装生命周期、三市场录制端到端、阶段 1–7 回归、可复现 ZIP、哈希链和安全扫描。
- **最终 MVP 完整验收：WAITING。** 干净电脑上的真实私密上传、真实 Publication Receipt、真实 YouTube video ID 与真实 Studio/Analytics 证据仍需用户明确授权；本轮没有用 synthetic/recorded fixture 冒充它们。
- **外部操作：0。** 未 push、tag 或创建 Release；未覆盖正式程序；未发起 OAuth 或上传；未迁移正式用户数据；未写长期频道学习规则。

## Release Candidate

| 项目 | 结果 |
| --- | --- |
| 版本 | `0.8.0-rc.1` |
| ZIP | `dist/v0.8.0-rc.1/ai-video-channel-production-v0.8.0-rc.1-windows.zip` |
| SHA-256 | `240d5218dd4ac16765415cd79d60f1c1df223fcdb804f27eb5c8a77801f45f09` |
| 大小 | 361,825 bytes |
| 文件数 | 122 |
| 内部资产清单 SHA-256 | `61cabf26a9ce9c496c004c857113cc3019658ad4741993414444bab1fb96e8f2` |
| 可复现性 | 两个独立输出目录构建哈希完全一致，PASS |
| 安全扫描 | 无凭据、无 EXE、无用户数据，PASS |

发布清单采用 SHA-256 与 canonical JSON 链：文件哈希 `6b59b984060f538441dd3dc7dcfda29216ac89de16638c88a44739ad6ecaf5cb`，内容哈希 `062b0a49087f6f50a92586d8cbc950b0bed190f49fd18479cc345f66871b2a8f`。

## 安装生命周期

真正隔离的程序、用户数据与 Codex home 位于 `E:\小说漫全自动化生产\runtime\s8\rc1\installation-lifecycle\验收 space`，覆盖 Unicode、空格和三类目录分离场景。

- 首次联网安装：PASS；11 个依赖按精确版本安装到隔离运行时。
- 首次离线安装：PASS；使用本地 wheelhouse，服务健康检查通过。
- 重复安装：`IDEMPOTENT_PASS`。
- 从公开 `v0.1.0-beta.2` 构造旧版升级：PASS，旧数据保留。
- 在切换后故意注入失败：PASS，自动恢复上一可用版本。
- 备份、卸载、恢复、重装并重新绑定频道：PASS；程序被移除而用户数据保留。
- 正式 Codex 配置未触碰；正式工坊与发布中心 EXE 的前后哈希完全一致。

机器证据：[lifecycle-summary.json](E:/小说漫全自动化生产/runtime/s8/rc1/installation-lifecycle/lifecycle-summary.json)，SHA-256 `b776f5e68c402f5784672e79eb9febb33b5ab2e9c3adde337b018e419f36298f`。

## 三市场录制端到端

`ja-JP`、`zh-CN`、`en-US` 均为清楚标注的 `recorded-synthetic-stage8-e2e`，结果均为 `GO_RECORDED_SYNTHETIC`。每个市场都实际生成并校验了：

`资料 → Topic Package → Manuscript Package → Publishing Asset → Production Package → 工坊桥/真实媒体文件 → Production Result → Publish Package 本地状态 → T+28 数据快照/报告/学习建议门`

三个市场均证明跨中心版本/hash 链、重启恢复、生产幂等、发布包幂等、数据快照幂等和频道隔离。合成真实媒体的 SHA-256 为 `ba4792b3cb95ffe24c26d17d279a5e6f4b379161c9196716fa407b1b652c6804`。没有真实上传、真实回执、真实 video ID、Studio 私有数据或长期学习写回。

机器证据：[summary.json](E:/小说漫全自动化生产/runtime/s8/rc1/three-market-e2e/summary.json)，SHA-256 `6beacb2f69df5747be84de01b620e1a4831bead94537aad029bd8c1fa67e6b79`。

## 回归结果

阶段脚本 `Test-Stage1.ps1` 至 `Test-Stage8.ps1` 全部通过。完整单元测试套件在注入正式只读发布 CLI 后为 **137/137 通过、0 跳过**。重点结果：

- 阶段 4：三市场、9 个冻结包、12 项聚焦测试通过。
- 阶段 5：三市场真实媒体门与生产交接、22 项聚焦测试通过。
- 阶段 6：Publish Package v2 与离线发布边界、15 项聚焦测试通过。
- 阶段 7：三市场快照、报告、建议、隔离与 `AUTH_REQUIRED` 边界、15 项聚焦测试通过。
- 阶段 8：4 项 RC 单测和完整生命周期/E2E/可复现性/审批矩阵通过。
- 插件、市场清单、10 类契约示例、Release Manifest 与仓库安全检查全部 PASS。

正式只读 CLI：`youtube-publisher-channel-list.exe`，SHA-256 `7c7bdbe38d961cfaa139995aa483e3391fb9f9261acdd6b7181c541d8398893f`。它只用于真实适配器回归，没有触发 OAuth 或发布。

## 正式程序保护

| 资产 | 验收前后 SHA-256 | 结果 |
| --- | --- | --- |
| 新漫剧工坊正式 EXE | `2c168cf5e1a886427fc564fc0d381d7a0915786a6d6ad10dec04131bb9d786a4` | 未变化 |
| YouTube 发布中心正式 EXE | `a81ce665c4d7c7bb97e46760cdde5606e90982a692a901d552165125f3af86f9` | 未变化 |

## 审批门

只读预检结果为 `READY_FOR_USER_AUTHORIZATION`，但它不等于授权。

| 操作 | 状态 | 本轮执行 |
| --- | --- | --- |
| GitHub push/tag/Release | WAITING_AUTHORIZATION | 否 |
| 覆盖或安装正式程序 | NO-GO | 否 |
| Google/YouTube OAuth | AUTH_REQUIRED | 否 |
| 真实 YouTube 私密上传 | AUTH_REQUIRED | 否 |
| 正式用户数据迁移 | AUTH_REQUIRED | 否 |
| 长期频道学习写回 | AUTH_REQUIRED | 否 |

机器审批清单见 [final-acceptance-approval-checklist-v0.8.0-rc.1.json](final-acceptance-approval-checklist-v0.8.0-rc.1.json)。用户批准后只需对组合审批门 `final-mvp-live-acceptance-v1` 执行一次 [最终实机验收手册](final-live-acceptance-runbook-v0.8.0-rc.1.md)，即可补齐真实安装、上传、回执和 Analytics 证据；在此之前不得宣称最终 MVP 完全完成。

完整机器报告见 [phase8-validation-report-v0.8.0-rc.1.json](phase8-validation-report-v0.8.0-rc.1.json)。
