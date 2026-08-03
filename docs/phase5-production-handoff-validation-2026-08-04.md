# 阶段5“标准生产包 v2 与工坊移交闭环”验证报告（2026-08-04）

## 结论

阶段5分发候选与最新工坊源码的隔离集成：**GO**。正式已安装工坊启用 Production Package 2.1：**NO-GO，等待单独审核部署**。

本阶段把阶段4 `READY_FOR_PRODUCTION` 的 Manuscript Package v1 与 Publishing Asset Package v1 转为 `schemaVersion=2.1` 的 Production Package v2，建立 Production Task v1、P0–P11、自动成片／剪映精修、FFmpeg 技术验收和 `VIDEO_READY` Production Result Package v1。没有创建 `.ready`，没有调用发布中心、OAuth、真实上传、Analytics 或长期频道学习写回。

离线媒体由明确标记的 deterministic synthetic runner 生成，经相同任务、资产登记和技术门验证；不代表真实图片、视频或 TTS 模型调用。非合成任务没有实际工坊 2.1 适配桥时会在活动任务创建前失败。

## 基线与仓库边界

- 分发仓库：`E:\小说漫全自动化生产\distribution\novel-manga-production`
- 阶段4基线：`6c9ad02806420e794b1e04788ead693fd86bd6d9`
- 工作区根仓库／控制中心 HEAD：`2949fd70cc30ed9d68f025ca6a677060ba826abd`
- 最新工坊源码 HEAD：`c649d68279bbefe6c71310ecd85a8acb9d53d9b3`
- 正式工坊：`E:\小说漫全自动化生产\apps\新漫剧工坊\ZMS\Z 漫剧工坊.exe`
- 正式工坊当前 SHA-256：`2c168cf5e1a886427fc564fc0d381d7a0915786a6d6ad10dec04131bb9d786a4`；18,625,536 bytes；本阶段未覆盖。

控制中心所在根仓库和工坊源码在阶段5开始前已有大量用户修改。控制中心不做源码写入，分发仓库新增只读／隔离桥；工坊只保留阶段5适配文件和对重叠前端文件的最小必要修改，不提交、不覆盖正式程序、不迁移用户项目。

## 实现摘要

### Production Package v2.1

固定文件为 `project.json`、`characters.json`、`episodes.json`、`script_lines.json`、`production_config.json`、`target_script_quality_gate.json`、`publishing.json`、`confirmed_thumbnail.png`、`source_lock.json`，并由 `manifest.json` 按相对路径排序登记大小、媒体类型和 SHA-256。包哈希明确排除 manifest 自身。

硬门验证两个上游包的确认状态、项目／频道／语言、版本和哈希绑定，质量门、唯一目标语言母稿、真实 16:9 封面、版本化音色目录、制作方式、四种视频范围、fallback、隔离目录、磁盘、FFmpeg 和 ffprobe。包外路径、中文审核稿、未知音色、敏感字段和个人绝对路径均拒绝。

### 工坊与权威任务

分发桥只允许健康检查、`--no-probe` 能力读取、隔离导入、隔离制作和只读状态；硬拒 `.ready`、publish、upload、OAuth、receipt、analytics 和 learning。实际工坊 2.1 导入锁定文本、行切分、说话人、类型、情绪、顺序、音色和视觉锚点，并按 `projectId + packageVersion + packageHash` 幂等复用。

Production Task v1 持久化 P0–P11 状态、依赖、运行 ID、进度、资产、输入指纹、尝试次数和历史。支持单通道、暂停／恢复、重启读取、失败资产重试和选择性失效。标题、简介、Hashtags 和封面只使发布引用失效，不使已完成正片媒体失效。进度查询只读。

### 两条成片路径

- 自动成片：实际 FFmpeg 输出带 H.264 视频流和 AAC 音频流的 16:9 MP4，同时输出目标语言 SRT、timeline map、asset index 和技术报告。
- 剪映精修：输出自包含 Jianying Draft Package v1、原生字幕轨描述、SRT、媒体、时间线和项目／任务／包指纹；不启动或点击剪映。用户导出 MP4 只能从隔离目录回收，并核对项目、任务、包哈希和视频 SHA-256；重复同一导出幂等复用，错项目拒绝。

两条路径均进入相同 ffprobe 解码、音视频流、分辨率、时长和字幕映射门，最终只产生 `VIDEO_READY` Production Result Package v1。

## 三市场离线端到端证据

可复验根目录：`E:\小说漫全自动化生产\runtime\stage5-validation-synthetic\production-core-20260804-final`

摘要 SHA-256：`22787da033b77e4924577af55ad881973a6fd6b40f3d77f181b555946606761e`

| 市场 | 流程证据 | Production Package SHA-256 | Result contentHash | Final MP4 SHA-256 | SRT SHA-256 |
| --- | --- | --- | --- | --- | --- |
| 日语／日本 | P4 后暂停、重启读取、恢复、自动成片 | `75227a1afbec211c68584c0bfbea88945eb679fea431b8c595552b3318505636` | `e266068ff3534ae25612748f8c99de059e330cd088ff93f98661dc157004e91a` | `ba4792b3cb95ffe24c26d17d279a5e6f4b379161c9196716fa407b1b652c6804` | `860f54b5c6d3adafbd6cba670f8f457951d9c20cea7ab0061f76ae2538ef0aeb` |
| 简中／中国 | 项目前 1 镜、明确授权静态回退、自动成片 | `97484b788d75da8c4aa3af89e1fcdde588ed6bba5f2e853761fd77b984474661` | `74bf993908f7822b3c17e3fffa5ba90f1a53a7da0a45469ee1c1df9ac71ef664` | `ba4792b3cb95ffe24c26d17d279a5e6f4b379161c9196716fa407b1b652c6804` | `6c1a43d223a91ca4cb05ecebc12628277d8d4eec14dad26c6da6ce2a3ebb83a0` |
| 英语／美国 | 未授权回退暂停、只重试失败资产、剪映草稿、身份校验回收 | `df32a4891fcf9aed83e39235e6d47f2ba885532f0ad1ac2151726c2ae6707aba` | `f2a4f8be38baac0f1319f80ccba399c976ee5a5acef3c6d469e1e2d413b16e96` | `ba4792b3cb95ffe24c26d17d279a5e6f4b379161c9196716fa407b1b652c6804` | `5ca2289a121a4f06808c14a569406f3817a96c962f97b3dc54124fa7492a2f84` |

三组 MP4 均为 54,741 bytes、640×360、16:9、3.000 秒、H.264 + AAC，并由系统 ffprobe 实测；它们是小型确定性验收媒体，不是正式发布分辨率。日语结果路径为 `ja-JP\workspace\data\production\results\synthetic-jp-content-loop\task-stage5-jp`，中文为 `zh-CN\workspace\data\production\results\synthetic-cn-content-loop\task-stage5-cn`，英文为 `en-US\workspace\data\production\results\synthetic-us-content-loop\task-stage5-us`。

## 实际工坊集成证据

最终隔离构建：`E:\小说漫全自动化生产\runtime\stage5-validation-synthetic\workshop-adapter-20260804\ZMS-stage5-production-v21-final-mainline-v2-isolated.exe`

- SHA-256：`2a08727d22cacb1a5fec57df3a0073b06a7f38fc1cc8d56fa0ff953d01a33b37`
- 大小：15,617,024 bytes
- 最新源码 v2.1 定向 Go 测试 5/5、`go test ./...`、TypeScript typecheck、Vite 隔离构建和相关自动生产策略测试通过。
- 正式安装程序仍只声明包版本 `[1.0, 2.0]`，未覆盖；隔离构建声明 `[1.0, 2.0, 2.1]`。
- 最终冻结日语包实际验证根：`E:\小说漫全自动化生产\runtime\stage5-validation-synthetic\workshop-adapter-20260804\mainline-ja-final-frozen-validation-r2`。
- 汇总 `mainline-final-roundtrip-validation.json` SHA-256：`f8c7e5edb41f17a4de762a94e75f57f55d3d51ad3e5108d5b254fe83862d923d`。
- 首次导入结果 SHA-256 `0502e5e17a9ad0481e49d55530c6910eef60083d2b4d7329dc3612c89885669a`：`duplicate=false`、`roundTripValidated=true`、2 集／2 角色／4 行、`warnings=[]`。
- 重复导入结果 SHA-256 `34bc06ea7bbf4a8c3e651520e454ae38cc2d3baff86dc5c0029d24fc8da58592`：`duplicate=true`、`roundTripValidated=true`、`warnings=[]`。
- 六组独立往返全部为 true：身份／标题、分集／lineIds、逐行顺序及字段、角色／锁定音色、视觉锚点／提示词、生产配置／Publishing。
- 项目 JSON 首次与重导 SHA-256 均为 `503d2c7c930c3d3ca9458636460115485aa1acfda34f8e9ee7c5855e7d3c2ea6`。
- 源包 tree SHA-256 前后均为 `04c57435ec0d9e0e5d1aadcf8ae6e2315060b330c924fa62406caa0ad25709d5`；manifest SHA-256 前后均为 `f0028f0535706278d81345473e63d4ff4fba4b52176862659f10ff6a86a8a88e`；10 个声明文件大小／哈希均有效，中文审核稿为 false，`.ready` 数量为 0。

这里的“实际工坊集成”指真实工坊源码和真实 CLI 导入／持久化逻辑在隔离构建中运行；不是 contract adapter 自测。收费／外部图片、视频、TTS 服务没有调用，所以不能解释为真实媒体模型生产已通过。

## 测试与实际命令

关键命令：

```powershell
uv run python tools/validate_contracts.py
uv run python tools/validate_plugin.py
uv run python tools/validate_release_manifest.py
uv run python tools/check_repository_safety.py
uv run python -m unittest -q tests.test_stage5_production_handoff tests.test_stage5_workshop_bridge
powershell -NoProfile -ExecutionPolicy Bypass -File tools/Test-Stage2.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File tools/Test-Stage3.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File tools/Test-Stage4.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File tools/Test-Stage5.ps1
uv run python tools/generate_stage5_fixture_outputs.py --output E:\小说漫全自动化生产\runtime\stage5-validation-synthetic\production-core-20260804-final
uv run python tools/validate_stage5_outputs.py --output E:\小说漫全自动化生产\runtime\stage5-validation-synthetic\production-core-20260804-final
```

结果：

- 阶段5核心／桥接测试：22/22 PASS。
- 全仓 Python 回归：103 项，101 PASS、2 项因正式发布中心 CLI 在该环境不可用而 SKIP。
- 阶段3隔离 Source Library／MCP／Skill 回归：PASS。
- 阶段4内容测试：12/12 PASS；3 市场、9 个冻结包校验 PASS。
- 阶段5三市场输出：3/3 PASS。
- Skills：7/7 quick validation PASS；安装健康检查验证 20 个阶段4／5工具及 Production Package 2.1 能力。
- 控制中心相关既有测试：41/41 PASS；未写入控制中心。
- 工坊：v2.1 定向 5/5、完整 Go、前端类型检查、Vite 隔离构建和相关策略测试 PASS。

## 失败矩阵

| 失败分支 | 结果 |
| --- | --- |
| 未确认上游 | 创建生产包前拒绝 |
| 上游坏哈希 | 创建生产包前拒绝 |
| 中文审核稿混入 | `PRODUCTION_AUDIT_SCRIPT_FORBIDDEN` |
| 包外路径 | 路径硬门拒绝 |
| 未知音色 | `PRODUCTION_VOICE_UNKNOWN` |
| 重复活动任务 | `PRODUCTION_ACTIVE_TASK_EXISTS` |
| 未授权静态回退 | P8 失败并暂停；不静默回退 |
| 坏 MP4 | `PRODUCTION_VIDEO_DECODE_FAILED` |
| 错字幕／时间线映射 | `PRODUCTION_SUBTITLE_MAPPING_MISMATCH` |
| 剪映错项目导出 | `PRODUCTION_JIANYING_EXPORT_IDENTITY_MISMATCH` |
| 发布越权／`.ready` | `PRODUCTION_PUBLISH_BOUNDARY_VIOLATION` |
| 非合成包无实际工坊桥 | `PRODUCTION_WORKSHOP_UNAVAILABLE`，不创建活动任务 |

## 退出矩阵

| 退出条件 | 结论 |
| --- | --- |
| Production Package v2.1 文件集、相对路径、SHA-256、安全 | PASS |
| 上游、质量门、封面、音色、制作配置和环境硬门 | PASS |
| 正式字段锁定、逐字段往返、幂等导入 | PASS（隔离真实工坊源码） |
| Production Task v1、单通道、恢复、重试、指纹与选择性失效 | PASS |
| P0–P11 与 synthetic 同任务技术门 | PASS |
| 自动成片 MP4／SRT／timeline／asset index／技术报告 | PASS |
| Jianying Draft、自包含字幕和导出回收 | PASS |
| 四种视频范围、selected IDs、默认暂停和授权回退 | PASS |
| Production Result Package v1、`VIDEO_READY`、无发布触发 | PASS |
| Production Handoff Skill、协议、健康检查、兼容矩阵 | PASS |
| 日／中／英同链端到端 | PASS |
| 规定失败分支 | PASS |
| 阶段2–4、工坊构建、阶段5、隔离安装 | PASS；发布中心两项环境性 SKIP 不涉及阶段5发布授权 |
| 本地提交与敏感文件检查 | 分发仓库安全检查 PASS；提交在报告冻结后创建；无 push／Release |

## 外部源码改动与残余边界

控制中心仓库已有大范围用户改动，阶段5没有修改或提交该仓库。旧 `AutoProductionHandoff`／手动导出回收会进入 `.ready` 或回执链，明确禁止复用；只复用其单通道、暂停／恢复、运行 ID 保护语义，并由分发桥实施阶段5安全边界。

工坊阶段5文件为 `backend/production_package_v21.go`、`backend/production_package_v21_test.go`、`backend/production_package_import.go`、`backend/novel_manga_capabilities.go`，以及与既有用户改动重叠的 `frontend/src/modes/novelManga/components/NovelMangaAutoProductionPanel.tsx`。因为工作树已有大量修改且前端文件重叠，未创建工坊 commit；所有改动保留为未提交并与正式 exe 隔离。

残余边界：正式工坊程序尚未部署 2.1；真实图片、视频、TTS 服务和正式媒体质量尚未调用／验证；640×360 仅用于小型技术验收；发布中心、频道授权、OAuth、上传、Analytics 和长期学习完全未进入。本阶段不批准正式工坊替换或真实发布。
