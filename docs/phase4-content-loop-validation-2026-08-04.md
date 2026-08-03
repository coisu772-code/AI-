# 阶段4“内容最小闭环”验证报告（2026-08-04）

## 1. 结论与范围

结论：**GO（仅限阶段4内容最小闭环）**。

本地未发布候选 `0.4.0-dev.1` 已实现并验证：

```text
Stage2 Channel / Production Context
  + Stage3 Source Package v1
→ Topic Package v1
→ Manuscript Package v1
→ Publishing Asset Package v1
→ 只读移交资格检查
```

该 GO 不包含阶段5制作，不表示 GitHub Release、工坊调用、Google／YouTube OAuth、上传、Analytics 或长期频道学习写回获得授权。候选清单仍为 `draft`，未推送、未发布。

基线：阶段2 `f480c4e`，阶段3 `bc5a9c9`。本次开始前工作树无未提交用户改动；提交前再次核对全部差异。

## 2. 实现结果

### 2.1 可安装入口

- 插件包含 6 个 Skills：`channel-production`、`channel-onboarding`、`source-library`、`topic-selection`、`manuscript-production`、`publishing-assets`。
- `channel-production` 是普通用户的新对话自然语言总路由；其余 5 个入口保持显式／编排调用。
- 本地服务新增 9 个 `content_*` 工具：能力查询、项目开始、选题检查点、选题冻结、母稿冻结、发布资产冻结、项目读取、完整性检查和移交资格检查。
- 安装器在 staging 中先执行静态健康检查；隔离安装后再通过真实 MCP `tools/list` 和 `content_capabilities` 验证已安装副本。
- draft release manifest：`release-manifests/release-v0.4.0-dev.1.json`；最终 `contentHash=77e93a256f46b21809edfc40e9a0b55ea2459024a6325d89927a1b41f9f6b217`。

### 2.2 Topic Package v1

- 读取 Stage2 冻结频道与生产预设，并锁定 Stage3 Source Package 的版本、SHA-256、来源和权利边界。
- 只接受 `CONTENT_READY`；`PARTIAL` 必须逐来源记录明确接受、接受时间和已知限制。
- 保留 `fact`、`inference`、`unknown`，其中事实／推断必须绑定冻结来源，未知不得伪装成有来源事实。
- 当前可执行：目标市场原创、频道画像锚定、用户大纲直通。
- 趋势、单作品、多作品、拆书、仿写保留版本化扩展接口；缺失时返回 `CONTENT_EXTENSION_UNAVAILABLE` 和所需接口，不生成替代分析。
- 普通原创严格 3～6 候选；频道画像路线按顺序逐项落盘且严格 10/10；大纲直通严格 1/1。检查点每次只增加 1，且必须先有真实候选 JSON。
- 冻结完整受众、证据、卖点、故事事实、角色、大纲、逐集剧情、精确篇幅／时长／集数、七项评分、连续排名、选择理由、唯一方案和 G3。

### 2.3 Manuscript Package v1

- 冻结 Story Bible、持续角色、视觉锚点、音色引擎／ID／名称、音色目录版本与 SHA-256。
- `target-language-native` 目标语言正式稿是唯一生产母稿。
- 非中文项目生成严格逐行中文回译，逐项校验行 ID、集号、集内顺序、说话人、旁白／对白类型和情绪；中文项目使用 `same-as-target`，不创建重复审核文件。
- 每集只有一次合并质量门，覆盖故事事实、推进、人物声音、目标语言、地区表达、术语、TTS 语义行和观众回报。
- 新 Topic 版本使 Manuscript 与 Publishing 失效；新 Manuscript 版本只使 Publishing 失效。全部版本和文件都有 SHA-256，并由 G4 联合确认。

### 2.4 Publishing Asset Package v1

- 只接受已确认且哈希有效的 Manuscript Package。
- 冻结唯一目标语言标题、中文翻译、目标语言简介、8～12 个 Hashtags、封面策略、恰好 5 个候选、唯一正式选择和 CTR 联评。
- `image-provider-v1` 支持可扩展供应商；`prompt_only` 明确标记为待补图片且不可移交。
- 可移交的真实封面必须存在、可读、为 PNG、精确 16:9 且 SHA-256 匹配。
- G5 通过后只产生 `READY_FOR_PRODUCTION` 资格；不创建 Production Package，也不调用任何外部中心。

### 2.5 学习与权限边界

- 频道学习只读 `read_only` 快照。
- 一次性修改只保存在当前项目 `learningContext.currentProjectChanges`。
- 任意长期学习写回请求以 `LONG_TERM_LEARNING_FORBIDDEN` 拒绝。
- 所有能力与完整性响应都声明：工坊、发布授权、上传、Analytics、长期学习写回为 `false`／`notExecuted`。

## 3. 三市场合成完整包

以下均为短小离线合成夹具，`onlineData=false`、`userData=false`，不是线上数据、频道结论或正式作品。三组包由同一状态机生成，经同一 3 个 Schema、G3／G4／G5、文件、哈希和映射校验。

| 市场 | 包目录 | Topic | Manuscript | 中文审核 | Publishing | 完整性／移交资格 |
| --- | --- | --- | --- | --- | --- | --- |
| 日本／日语 | `tests/fixtures/stage4/packages/ja-JP` | `TOPIC_SELECTED` | `SCRIPT_READY` | `backtranslation` | `PUBLISHING_ASSETS_READY` | PASS／eligible |
| 中国／简中 | `tests/fixtures/stage4/packages/zh-CN` | `TOPIC_SELECTED` | `SCRIPT_READY` | `same-as-target`，无重复审核文件 | `PUBLISHING_ASSETS_READY` | PASS／eligible |
| 美国／英语 | `tests/fixtures/stage4/packages/en-US` | `TOPIC_SELECTED` | `SCRIPT_READY` | `backtranslation` | `PUBLISHING_ASSETS_READY` | PASS／eligible |

每个市场包含 Topic、Manuscript、Publishing 三个冻结包，共 9 个包；每个发布资产包有 8 个 Hashtags、5 个封面候选和唯一真实选择。公共合成 PNG 为 1600×900、23,818 字节，SHA-256：

```text
a667f692ef6074c3fa5f1de9af4188ae189dfb1bf390c3b2b0fb5f31d47eb7c7
```

逐市场冻结哈希：

| 市场 | Topic SHA-256 | Manuscript SHA-256 | Publishing SHA-256 |
| --- | --- | --- | --- |
| `ja-JP` | `d6c17bf1a31e2508e57835152c1227a74e2246534fba9fc93fddd2df3c99d686` | `e457c5503cf592fae05894ab0c3295a48a13c0a78512d35031916b81cc7213e4` | `88190063164be2ca8f75dfc1c629cafa40c09057d42ac1db794e89ee5c5eb692` |
| `zh-CN` | `90a602c6467e1a7738ed2aef38d3f069ebb450d1902b03bceb5b2863e838be42` | `26c659512886c9fa118acf665de068871bfffe4e48b4d8a59558f464b9775296` | `dd573b30f9e33bed66791ec8d14f35e31b417e0c17dba2afc056921d682321ae` |
| `en-US` | `d53480ed9d321d28ed8156e1c0f2c01b15542579f0f150e3acc85dbbfb1feb95` | `de2131571470b0542b44f53472da26895097f0ec1ee1ac62737d3475a7c93a6a` | `e1110c7072d508cdefac386da7a072dfe41b04c88d5246d46abcd434b7f38ad8` |

## 4. 退出矩阵

| 退出条件 | 实证 | 结果 |
| --- | --- | --- |
| 消费 Stage2 上下文与 Stage3 资料，保留事实边界 | 运行时锁定 Channel／Production／Source 上游引用；CONTENT_READY／PARTIAL 正反测试；证据分类 Schema 与行为测试 | PASS |
| 三种当前选题路线 | 原创三市场完整链；频道第 9 个候选冻结失败、真实 10/10 后成功；大纲直通 1/1 检查点 | PASS |
| 五类稳定扩展接口 | trend、single-reference、multi-reference、book-deconstruction、imitation 均返回明确 unavailable | PASS |
| Topic Package 完整性 | Schema、10 候选契约、运行时检查点、七项评分、排名、选择、G3、版本／哈希 | PASS |
| Manuscript 唯一母稿与映射 | 日／英逐行回译；中文 same-as-target；映射错误失败；合并质量门与 G4 | PASS |
| Publishing 事实与封面硬门 | 8–12 标签、恰好 5 候选、真实 PNG、16:9、SHA-256、CTR、G5；标签数和比例错误失败 | PASS |
| 状态机与未确认阻断 | 未确认 Topic 不能冻结／移交；坏哈希完整性失败；上游变化选择性失效 | PASS |
| 学习只读 | 长期写回被运行时和 Schema 双重拒绝；当前修改限制为 `current_only` | PASS |
| 新 Skills、清单、安装、健康检查 | 6/6 Skills 快速校验；插件 manifest；隔离安装；9/9 工具；实调 `content_capabilities` | PASS |
| 三市场完整包 | 3 个市场、9 个冻结包、同一 Schema／状态机／质量门／文件／哈希／映射 | PASS |
| 指定失败路径 | 未确认、坏哈希、映射错、标签数量错、封面比例错、PARTIAL 未接受、五类扩展缺失、长期学习越权 | PASS |
| Stage2／3 回归 | Stage2 全套 81 项通过（2 项正式发布中心 CLI 因本次未提供而按设计跳过）；Stage3 隔离闭环通过 | PASS |
| 外部与用户数据边界 | 工坊、OAuth、上传、Analytics、长期学习写回均未调用；测试只使用隔离目录和合成数据 | PASS |

## 5. 实际验证命令与数量

### 阶段2回归

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\tools\Test-Stage2.ps1
```

结果：插件、10 个契约示例、draft release manifest、221 个安全检查文件、6 个 Skills、安装幂等和 MCP 隔离均通过；Python `unittest` 共 81 项通过，2 项正式发布中心 CLI 测试因该 CLI 未提供而 `skipped`。为遵守本阶段边界，本次未传入发布中心程序、未读取其数据。

### 阶段3回归

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\tools\Test-Stage3.ps1
```

结果：候选隔离安装、Source Library、MCP、日中英资料输入、SHA-256 去重、重启持久化和阶段边界全部通过。

### 阶段4全套与隔离安装

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\tools\Test-Stage4.ps1
```

结果：

- 插件／marketplace、10 个契约示例、release manifest、221 个安全检查文件通过；
- 3 个市场、9 个冻结包通过；
- 阶段4行为与失败路径 12/12 通过；
- 6/6 Skills 通过 `quick_validate.py`；
- 源码树与隔离安装副本健康检查通过；
- 已安装副本暴露 9/9 内容工具，并实际调用 `content_capabilities` 成功；
- 隔离目录在测试后清理，未修改真实 Codex 用户配置。

报告写入后又执行最终只读收口：`validate_plugin.py`、`validate_contracts.py`、`validate_release_manifest.py`、`check_repository_safety.py`、`validate_stage4_packages.py` 与 `git diff --check` 全部通过；此时安全检查覆盖 222 个文件（比总验收时多出的 1 个文件即本报告）。

## 6. 未触发的审批门和未执行动作

- 未执行 GitHub push、tag、Release 或发布资产构建。
- 未请求或使用 Google／YouTube OAuth、Token、Cookie、验证码或上传权限。
- 未进入控制中心、工坊、发布中心或数据中心。
- 未迁移、删除或覆盖用户数据；只写入仓库内代码、文档和明确的合成夹具。
- 未写入长期频道学习账本。
- 未生成 Production Result Package、Publish Intent、Publication Receipt 或 Analytics Snapshot。

## 7. GO／NO-GO

- **GO：阶段4内容最小闭环可以作为本地 `0.4.0-dev.1` draft 候选，供后续受控集成。**
- **NO-GO：阶段5制作、真实频道发布、GitHub Release、外部授权、上传、Analytics 和长期学习写回。** 这些动作需要各自后续阶段的实现、验收和明确授权。
