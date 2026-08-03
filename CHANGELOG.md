# 更新记录

## 未发布 - 阶段 7 工作树

- 增加 Metric Catalog v1、六级事实等级、公开／owner／system 来源边界和收入权限关闭策略。
- 增加正式 Publication Receipt 注册门、synthetic fixture 隔离空间、原始追加、快照幂等、迟到修订和重启恢复。
- 增加 T+24／T+7／T+28 视频表现报告、频道策略报告、timeline 留存证据与同频道可比基线。
- 增加 Recommendation Card v1、项目级实验和不可绕过的长期频道学习审批门。
- 增加 `$data-center`、七个数据工具、九 Skills／三十二工具安装健康检查及日中英三市场 recorded synthetic 离线链。
- 阶段7未发起 OAuth、未读取 Token、未接入真实 Studio、未迁移现有数据库、未写长期学习、未 push 或 Release。

## 未发布 - 阶段 6 工作树

- 增加发布包 v2、幂等 Publish Intent、`.creating → .ready` 原子生命周期及六文档 JSON Schema。
- 增加版本化 YouTube constraints catalog、FFprobe／封面／字幕／元数据／频道／计划／额度硬门。
- 增加 `DO_NOT_UPLOAD`、`REQUIRE_REVIEW`、`AUTO` 三策略与三重自动授权资格门，所有工具强制 `networkExecution=false`。
- 增加 `$publish-video`、五个发布工具、发布中心隔离 CLI 适配和日／中／英三市场离线包。
- 阶段6只到 `PACKAGE_READY`、`WAITING_REVIEW` 或 `READY_TO_UPLOAD`；OAuth、真实上传、远端修改、真实 video ID 与 Publication Receipt 未执行。

## 未发布 - 阶段 5 工作树

- 增加 Production Package v2.1、Production Task v1、P0–P11 依赖、输入指纹和选择性失效。
- 增加安全工坊桥、严格字段往返、幂等导入、暂停恢复、失败资产重试和重启恢复。
- 增加自动成片与 Jianying Draft Package v1／导出回收双路径，统一使用 FFmpeg／ffprobe 技术门。
- 增加 Production Result Package v1、三市场离线合成制作和 `$production-handoff` 制作中心 Skill。
- 制作终态只到 `VIDEO_READY`；`.ready`、发布中心、OAuth、上传、Analytics 和长期学习写回继续关闭。

## 未发布 - 阶段 4 工作树

- 增加 Source Library 到 Topic、Manuscript、Publishing Asset 三类 v1 冻结包的内容最小闭环。
- 增加原创、频道画像锚定、用户大纲直通路由，以及缺失趋势／参考作品／拆书／仿写能力时的明确不可用响应。
- 增加目标语言原生母稿、非中文逐行回译、合并质量门、选择性失效和 G3／G4／G5 联合确认。
- 增加封面供应商接口、5 候选、真实 PNG 文件／比例／哈希硬门与 prompt-only 非移交状态。
- 增加六个可安装 Skills、九个内容工具、隔离健康检查，以及日中英三市场合成完整包和失败路径回归。
- 工坊、OAuth、上传、Analytics 和长期频道学习写回继续保持关闭。

## 未发布 - 阶段 3 工作树

- 增加统一 Source Library、Source Package v1、日中英本地文档闭环、去重、恢复与隔离验收。

## 未发布 - 阶段 2 工作树

- 增加版本化 stdio MCP 本地工具服务和发布中心正式频道清单 v1 适配器。
- 增加隔离的系统／频道数据库、双阶段建库、任务绑定、预设版本和仅本次覆盖。
- 增加带哈希的 `.avchannel` 备份、导入、恢复回滚、迁移保护和阶段2验收。
- 资料采集、内容生成、工坊、真实上传和 Analytics 继续保持关闭。

## 0.1.0-beta.2 - 2026-08-03

- 修复 Windows 工作区与 GitHub 检出换行不同导致的目录工件哈希不一致。
- 增加 GitHub 标签来源和 Release 压缩包安装验收。

## 0.1.0-beta.1 - 2026-08-03

阶段 1 首个 Beta：

- 建立 Codex 插件与 marketplace 发布骨架；
- 增加总入口和频道建库前提检查 Skill；
- 定义 10 类版本化跨中心数据契约；
- 增加内容哈希、上游引用、统一发布清单与自动校验；
- 增加 Windows 安装、升级、回滚和卸载流程；
- 明确阶段 2 以后能力尚未开放。

该标签的 GitHub 验证在发布资产前失败，因此没有创建 Release；后续由 `0.1.0-beta.2` 取代。
