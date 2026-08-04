# 跨中心数据契约 v1

本目录定义六大中心之间可冻结、可校验、可追溯的正式交付边界。所有 Schema 使用 JSON Schema Draft 2020-12，契约版本从 `1.0.0` 开始。

## 契约链

```text
Channel Profile + Production Profile + Source Package
+ 可选 Analysis Package v1 / Writing Style Contract v1
→ Topic Package
→ Manuscript Package
→ Publishing Asset Package
→ Production Result Package
→ Publish Intent
→ Publication Receipt
→ Analytics Snapshot
```

## `canonical-json-v1`

根级 `contentHash` 按以下规则计算：

1. 复制完整 JSON 对象并只删除根级 `contentHash`。
2. 对所有对象键按 Unicode 码点升序排序；数组顺序保持不变。
3. 按 JSON 标准序列化，使用 UTF-8、无 BOM、无额外空白，布尔值和 `null` 使用 JSON 小写字面量。
4. 对所得字节计算 SHA-256，写入 64 位小写十六进制 `contentHash`。

`upstream[].targetHash` 必须等于所引用上游契约当前冻结版本的 `contentHash`。正式包冻结后不得原地覆盖；任何内容修改都生成新的语义化版本，并使受影响下游引用失效。

## 阶段 4 内容冻结边界

三类内容包继续使用契约主版本 `1.0.0`，但必须保存完整冻结信息，不能只交付摘要：

- `Topic Package v1` 保存路线、受众地区／语言、Source Package 接受状态、`fact`／`inference`／`unknown` 证据及来源、完整候选、七项评分、连续排名、唯一选择、G3 确认、故事事实和精确篇幅／时长／集数。频道画像锚定的正式已选包必须恰好有 10 个真实候选及 10 个逐项检查点；生成中或 `PARTIAL` 快照可以少于 10 个，但不得标为 `TOPIC_SELECTED`。
- Topic 只能消费 `CONTENT_READY`，或带有用户显式接受记录和已知限制的 `PARTIAL` Source Package。趋势、单作品、多作品、拆视频、拆书和仿写通过 `extensionCapabilities` 声明 `available` 或 `unavailable`；缺少 Skill 时必须给出原因，不能伪造分析结果。
- `Writing Style Contract v1` 只由原创仿写方向的人工 8 选 1 门产生，冻结来源角色与权重、统一因果、功能同构、可信度与反复制边界。权重不是来源片段占比；原句、专名、完整事件顺序和单一作品主线均不得进入下游。
- `Manuscript Package v1` 冻结 Story Bible、持续角色、真实音色目录绑定、目标语言原生母稿、中文审核稿、逐行映射、逐集合并质量门、选择性失效策略和 G4 联合确认。`targetScript.role=target-language-production-master` 且 `isSoleProductionSource=true`；非中文必须逐行回译，中文使用 `same-as-target` 且不得创建重复审核文件。
- `Publishing Asset Package v1` 只绑定已确认文稿，保存唯一标题及中文翻译、目标语言简介、8–12 个 Hashtags、标题候选、封面策略、5 个候选记录、唯一选择、CTR 联评、G5 联合确认和生产移交判定。`prompt_only` 必须显式标记且不能成为 `PUBLISHING_ASSETS_READY`；可移交包必须使用存在、可读、哈希匹配且声明为 `16:9` 的真实图片。
- 三个确认门均保存 `review` 或显式授权后的 `auto` 来源。未确认包、质量门失败包、映射失败包和 `prompt_only` 封面包不得移交下一中心。

`contracts/examples/valid/fixtures/confirmed-thumbnail-1600x900.png` 是清楚标注的本地合成 PNG，只用于契约测试，不是线上数据、用户数据或正式封面。

## 阶段 5 制作契约

`production-package-v2.schema.json` 校验 Production Package v2.1 的 manifest。清单恰好声明九个包内文件，路径按字典序排列并绑定大小、媒体类型和 SHA-256；`manifest.json` 自身按明确的 `manifestSelfExcluded` 规则计算包哈希。

`production-task.schema.json` 和 `jianying-draft-package.schema.json` 是制作中心内部、但可安装验证的辅助 Schema。前者描述权威 Production Task v1 和 P0–P11；后者描述自包含剪映草稿的项目、任务、生产包指纹和字幕轨。它们不扩充当前十一类跨中心 `contract-catalog`；新增的 `writing-style-contract-v1` 属于跨中心契约，制作中心内部辅助 Schema 仍不计入该集合。

Production Result Package v1 仍是制作中心对发布中心的跨中心输出，但阶段5实例只允许 `VIDEO_READY`，必须携带任务、报告、资产索引、验证报告、最终视频、字幕、发布资产引用和 source lock。任何 `.ready` 或 `publishingTriggered=true` 都是越权失败。

## 路径与安全

- 契约中的文件路径只允许包内相对路径。
- Schema 和示例不得包含真实频道、Token、密钥、Cookie、活动数据库或用户媒体。
- 示例域名使用 `example.invalid`，频道与视频 ID 均为合成测试值。

## 校验

运行 `tools/validate_contracts.py` 会检查 Schema、必填字段、ID 一致性、内容哈希和所有示例间的上游引用。`tests/test_contracts.py` 还覆盖未接受的 `PARTIAL`、未确认选题、频道候选不足、逐行映射失败、Hashtags 数量错误、封面比例声明错误、`prompt_only` 越权移交、长期学习写回字段和真实 PNG fixture 的字节／尺寸／哈希校验。
