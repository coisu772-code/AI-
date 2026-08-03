# 最终真实 MVP 验收运行手册（0.8.0-rc.1）

本手册只在用户明确批准 `final-mvp-live-acceptance-v1` 后使用。阶段 8 本地 RC 验收没有执行这里的任何外部动作。

## 一次授权包

一次确认必须明确包含：GitHub push/tag/Release、是否部署两套正式程序、Google／YouTube 最小 OAuth、向指定测试频道上传一条私密测试视频、是否迁移指定测试数据，以及对最终学习建议只做“接受或拒绝”而不默认写入。任一项未确认就保持原门状态，不用其他确认推定。

## 操作前只读检查

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\tools\Test-FinalAcceptancePrerequisites.ps1 -ReleaseCandidateZip <RC-ZIP> -AsJson
```

结果必须是 `READY_FOR_USER_AUTHORIZATION`，两套正式 EXE 的 SHA-256 必须与冻结基线一致。检查只读，不会启动程序、OAuth、上传、迁移或学习写回。

## 获批后的单次验收会话

1. 在一台不含源码、使用全新 Windows 用户配置的机器核对 RC ZIP 与 `SHA256SUMS.txt`，执行在线安装；需要断网安装时使用同版本离线 wheelhouse 和 `RuntimeMode=Offline`。
2. 启动 Codex，新建任务并确认插件显示名为“AI 视频频道生产系统”。只绑定用户指定的测试频道，记录 Channel Profile 和 Production Profile 的版本与 hash。
3. 各用 ja-JP、zh-CN、en-US 完成一条代表项目；全过程只使用测试资料和用户明确允许的测试媒体。
4. 通过 G6 后仅上传一条用户指定的私密测试视频，保存真实 Publication Receipt v1、YouTube video ID、频道身份回读和处理状态。重试同一 Publish Intent，确认没有第二条上传。
5. 生成公开表现快照；只有独立 Analytics 授权有效时读取 owner 指标，否则保留 `AUTH_REQUIRED`，不得补造数据。
6. 展示 Recommendation Card，由用户明确接受或拒绝。只有用户另行批准长期写回时才记录频道规则。
7. 把真实证据追加到阶段8报告，将相应 `AUTH_REQUIRED`／`NO-GO` 改为 GO；此前不得宣布完整 MVP 完成。

GitHub Release 应最后执行：先在干净机器验证从候选资产安装成功，再 push、tag 并创建 Release。任何失败先停止远端动作，保留本地数据并使用已验收回滚入口。
