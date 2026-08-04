---
name: channel-distillation
description: Distill one or more YouTube reference channels into evidence-bound, target-channel-scoped production profiles. Use when the user asks why a channel works, asks to learn from a channel before production, requests channel DNA/audience/packaging/retention analysis, compares or fuses multiple reference channels, or asks for channel distillation. This Skill requires persistent Source Packages and produces Analysis Package v1 plus runtime profiles for the topic and manuscript centers. It does not perform standalone video-copy deconstruction or original imitation writing.
---

# 频道蒸馏

把 YouTube 参考频道转成可审计的完整画像和下游运行画像。参考频道只提供创作证据；当前绑定的 `channelProfileId` 始终是产物所属目标频道，绝不能把参考频道 ID 写成发布频道。

## 进入前检查

1. 调用 `channel_distillation_capabilities`。
2. 确认当前任务已绑定唯一目标频道。
3. 从 Source Library 读取参考频道的轻量全频道清单，并为拟深拆视频读取独立 `youtube-video` Source Package。
4. 深拆视频必须为 `CONTENT_READY`，且正式正文资产为 `content.txt`。可用 `timing-map.json` 定位时段，但不读取或保存 VTT/SRT/JSON3 字幕正文副本。
5. 缺正文时转回 `$source-library`。字幕、音频或视频只作为补充采集输入；不能根据标题、封面、简介、评论或播放量编造完整剧情。

当前版本只蒸馏 YouTube。小说网址下载属于 `$source-library`，不是第四个内容分析 Skill。

## 规划模式

- `single`：一个参考频道。
- `parallel`：多个频道分别蒸馏，分别供下游调用。
- `compare`：保留各频道独立画像，再给出有证据的异同与适用边界。
- `fusion`：每个频道明确角色与权重，合计正好 100；保留独立画像后再重建统一功能组合。禁止求平均、按视频段落拼接或消除频道差异。

调用 `channel_distillation_prepare` 冻结参考身份、视频资料版本、角色、权重和样本计划。同一视频不能挂到两个参考频道。

## 七阶段

1. 频道身份：核验频道 ID、链接、内容边界与目标频道隔离。
2. 轻量清单：尽量完整记录公开视频形态、发布时间、公开播放量和可见变化。
3. 热门筛选：按同形态、同龄百分位、中位数倍数、近期突破和重复热门系列选证据；低表现作品不能作为正向规律。
4. 逐条深拆：每批最多 3 条，默认先完成 8 条证据最强且覆盖主要热门类型的作品。覆盖不足时每次扩展 2 条，通常在 8–12 条内收敛。
5. 规律聚合：每个核心规律至少由 2 条成功热门样本支持。单条超级爆款只能进入热门特例。
6. 质量门：检查证据、未知、反复制、跨资产兑现、观众画像边界和多频道隔离。
7. 冻结画像：生成完整审计包、精简运行画像、账号专属后续要求及运行 Skill 注册表。

逐条调用 `channel_distillation_checkpoint`。单条失败记录 `FAILED` 或 `SKIPPED`，不能阻塞其他样本，也不能用低表现或离题视频凑数。

## 单视频分析格式

每条成功样本必须同时提交：

- `analysisBuckets.originalFacts`：页面、公开指标、`content.txt` 或时间映射可直接证明的事实，逐条绑定证据定位。
- `analysisBuckets.analysisConclusions`：由事实推出的结论，引用 fact ID 并给 0–1 置信度。
- `analysisBuckets.transferableMethods`：可迁移功能、适用条件和来源结论，不写成待复制句式。
- `analysisBuckets.prohibitedCopy`：原句、专名、完整事件顺序、单一作品主线、独特构图和其他可识别内容。
- `analysisBuckets.unknowns`：没有 Studio 或正文证据的字段，明确未知原因。

还必须覆盖故事内容、功能结构、表达、开场钩子、标题、封面、简介、Hashtags、视频呈现、视觉形态、观众需要、心理回报、留存假设、频道声音、跨资产联动和低质量模式。重点检查“标题/封面承诺—开场兑现—过程推进—阶段回报—结尾满足”。

公开数据只能支持公开事实或有限推断。没有用户提供的 YouTube Studio 数据时，CTR、留存率、流量来源、性别、年龄、设备、观看时段与观看场景必须标为未知或附限制的公开推断，不能写成后台事实。

## 聚合与冻结

每个参考频道分别形成：频道范围、内容 DNA、表达 DNA、视频 DNA、包装 DNA、跨资产联动 DNA、频道声音、通用逻辑、留存假设、观众画像、可迁移功能、禁止复制清单、不应放大的缺点和小说漫适配方式。

观众画像必须区分商业定位、人口/使用环境声明、核心/次级/测试分群、兴趣与心理回报，以及核心已验证、相邻扩展、探索测试三类题材通道。三类分配由本次证据动态生成，合计正好为 10；不得写死国家、性别、年龄、设备或题材比例。

调用 `channel_distillation_finalize` 时提交每个频道独立画像、账号专属拆解要求、账号专属仿写要求和通过的质量门。融合模式另提交逐频道功能贡献与重建因果引擎，并明确 `averagingUsed=false`、`segmentSplicingUsed=false`。

冻结产物包括：

- `analysis-package-v1.json`：完整证据包，供审计与内容项目锁定。
- `reference-channel-profile-v1.json`：逐参考频道完整画像。
- `channel-runtime-profile-v1.json`：供选题、文稿、标题、封面和元数据环节优先读取的精简画像。
- 两份目标频道专属要求：后续视频文案拆解和原创仿写的动态标准。
- `account-runtime-validation-v1`：两种后续能力各至少 3 个账号专属验收样例与预期检查，用来验证动态要求是否真正生效。
- 两个仅存在于目标频道数据目录的运行 Skill；不得复制到插件全局 `skills/`，不得让其他频道隐式加载。

下游创建频道锚定内容项目时，把 `distillationId` 作为 `analysisPackages` 传给 `content_project_start`。内容中心冻结 Analysis Package 的版本与哈希，并让选题中心和文稿中心共同读取；不得只靠对话记忆传递画像。

## 只读状态与边界

- 查询进度使用 `channel_distillation_get`，完整性检查使用 `channel_distillation_integrity_check`；两者不得改变活动步骤或样本状态。
- 完成后独立显示 `7/7 succeeded`。后续 `topic n/10` 是另一个进度，不得混报。
- 再次蒸馏可绑定 `previousDistillationId`；内容哈希未变的深拆样本可以复用，变化视频必须重做。
- 本 Skill 到冻结与交接为止，不执行单视频正式拆解、不生成 8 个原创方向、不写大纲或正文、不启动工坊、不上传、不写长期频道学习规则。

字段与契约细节见 [references/contracts.md](references/contracts.md)。
