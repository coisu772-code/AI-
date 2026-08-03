# 跨中心契约归属与流转

阶段 1 只定义交换格式，不实现六大中心的业务动作。所有契约采用 JSON Schema 2020-12、语义版本和 `canonical-json-v1` 内容哈希。

## 契约归属

| 契约 | 主要生产方 | 主要消费方 | 用途 |
| --- | --- | --- | --- |
| Channel Profile | 系统管理中心 | 全部中心 | 频道身份、市场与语言边界；不保存凭据 |
| Production Profile | 系统管理中心 | 选题、文稿、制作、发布中心 | 频道级生产默认值与人工确认边界 |
| Source Package | 频道资料库 | 选题中心、文稿中心 | 来源事实、访问边界与可追溯资产 |
| Topic Package | 选题中心 | 文稿中心、制作中心 | 已确认故事事实、人物关系、结局与生产建议 |
| Manuscript Package | 文稿中心 | 制作中心、发布中心 | 冻结母稿、逐行结构和质量门结果 |
| Publishing Asset Package | 文稿／包装环节 | 制作中心、发布中心 | 唯一标题、封面、简介和 Hashtags |
| Production Result Package | 制作中心 | 发布中心 | 成片、字幕、生产回执和资产哈希 |
| Publish Intent | 发布中心 | YouTube 发布执行器 | 一次明确的频道、隐私、时间和上传意图 |
| Publication Receipt | YouTube 发布执行器 | 发布中心、数据中心 | 真实平台 ID、执行状态与幂等回执 |
| Analytics Snapshot | 数据中心 | 报告与后续决策 | 带观察时间窗和数据来源边界的指标快照 |

## 引用与防串包规则

每个契约根对象必须包含自身 `id`、`version`、`schemaVersion`、`contentHash` 和 `upstream`。每条上游引用必须同时锁定：

- `targetContractType`
- `targetId`
- `targetVersion`
- `targetSchemaVersion`
- `targetHash`

校验器先验证结构，再按“类型 + ID + 版本”解析上游，最后比对 Schema 版本和内容哈希。这样能发现错误项目引用、旧版本串包和上游内容被静默改写。

`canonical-json-v1` 的规则是：移除根级 `contentHash`，按 Unicode 键名递归排序，使用紧凑 JSON、UTF-8、禁止 NaN，再计算小写 SHA-256。数组顺序有业务意义，不重排。

## 版本规则

- Schema 和契约实例都使用 SemVer。
- 新增可选字段通常提升次版本；删除字段、改变含义或新增必填字段提升主版本。
- 修正文档或不改变验证语义的说明提升修订版本。
- 消费方必须拒绝不支持的主版本，不能猜测字段含义。
- 所有发布组件、Schema 和协议版本统一记录在发布清单中。

有效示例只用于验证，不含真实频道、用户资料、凭据或媒体。

## 阶段4内容闭环约束

阶段4只执行 `Source Package → Topic Package → Manuscript Package → Publishing Asset Package`。每个输出先通过对应 Schema、上游版本与 SHA-256 校验，再写入 G3、G4 或 G5 确认结果；任何未确认、坏哈希或失效下游都会阻断移交。

目标语言正式母稿是制作唯一事实源。非中文项目的中文稿只是严格逐行审核映射；中文项目直接引用母稿，不生成重复审核资产。发布资产只能引用已确认母稿，并以唯一标题、8～12 个 Hashtags、封面候选与正式封面文件／提示词状态明确区分可移交与待补齐。

`READY_FOR_PRODUCTION` 仅表示三个内容包具备移交资格，不触发制作中心、工坊、OAuth、上传、Analytics 或长期频道学习写回。

## 阶段5制作移交约束

阶段5在两个上游包均已确认、项目／版本／哈希绑定一致后组装 Production Package v2.1。包中固定包含 `manifest/project/characters/episodes/script_lines/production_config/target_script_quality_gate/publishing/confirmed_thumbnail/source_lock`；中文审核稿、缓存、凭据、Token、个人绝对路径和包外路径均被拒绝。

Production Task v1 是唯一权威制作状态。P0–P11 的完成、失败、资产指纹、暂停／恢复和重试都持久化到任务；进度查询只读。标题、简介、Hashtags 或封面改变只使发布引用失效，不使正片媒体失效。显式视频失败默认暂停，只有生产配置明确写入 `use_static_image` 才逐项登记回退。

自动成片与剪映精修最终汇合到相同的 FFmpeg／ffprobe 技术门和 Production Result Package v1。结果状态止于 `VIDEO_READY`；Publish Intent、`.ready`、发布队列、OAuth、上传和长期学习不属于本阶段授权。
