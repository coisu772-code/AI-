---
name: channel-production
description: 作为 AI 视频频道生产系统唯一默认总入口，识别频道管理、视频链接或文本导入、拆书、仿写、编辑审核与修改、标题简介封面、工坊制作、上传准备与数据复盘意图。用户说“启动系统”“发你一个视频链接”“拆书”“完全仿写”“审核并修改”“生成标题简介和封面”“开始制作”“准备发布”或“检查频道数据”时使用；内容生产只路由到当前四阶段提示词流程，不加载已退役旧流程。
---

# AI 视频频道生产系统总入口

进入内容主链前读取 [用户审核文档规范](references/user-review-documents.md)。用户可读审核文档、机器生产包和 YouTube 发布包必须分层保存，不能相互替代。

## 默认内容流程

`content-source` 是视频链接、上传文本、资料库和按需联网资料的输入适配器，不计入四个创作 Skill。正式内容主链为：

```text
输入适配：content-source
→ 1. content-deconstruct（拆书与迁移方向）
→ 2. content-rewrite（完整仿写初稿）
→ 3. content-review-edit（审核、修改、复查、冻结正式稿）
→ 4. content-title-description（标题、YouTube 简介与正式封面）
→ publishing-assets 汇总
→ production-handoff
```

用户一句话要求“下载、拆解、仿写、修改并生成标题简介封面”时，按上图连续执行；每步真实保存并通过质量门。只有拆书迁移方向需要用户选择且没有自动授权，或目标语言、目标受众、篇幅档位、资料范围存在会明显改变结果的歧义时才暂停。

## 路由

- 建立／进入频道资料库、修改频道默认值、备份恢复：`$channel-onboarding`。
- 视频链接、用户文件、粘贴文本、资料库检索或用户明确要求的公开联网资料：`$content-source`。
- 完整拆书、逐章分析和不少于六个迁移方向：`$content-deconstruct`。
- 单源高贴合原创仿写或多资料融合仿写：`$content-rewrite`。
- 审稿、直接修改、复查和正式母稿冻结：`$content-review-edit`。
- 依据正式母稿生成标题、YouTube 简介和正式16:9封面：`$content-title-description`；`content-thumbnail` 只是该 Skill 的资产槽位，不是独立 Skill。
- 发布素材联合核验与汇总：`$publishing-assets`。
- 工坊制作、进度、失败重试、成片技术验收：`$production-handoff`。
- `VIDEO_READY` 后本地发布包与只读状态：`$publish-video`。
- 数据采集、报告与建议：`$data-center`。
- 系统更新：`$update-ai-video-system`。

## 状态与恢复

1. 调用 `content_capabilities` 读取内容能力；标题、简介和封面都由同一 Skill 提供。
2. 一个任务只绑定一个 `channelProfileId`，不得把参考视频频道当成发布频道。
3. 只分短篇和长篇；长篇按检查点恢复，只补缺失章节，不用摘要代替正文。
4. 正式内容主链使用 Source Package → Content Deconstruction Package → Topic Package／Rewrite Draft → Manuscript Package → Title/Description/Thumbnail Assets。
5. 每个创作阶段结束即生成对应的 `01`–`11` 用户审核文档，向用户显示可点击路径；不得等整个流程结束才保存。成片就绪后另在发布包中生成 `FINAL_CHINESE_REVIEW_CARD.md`。
6. 所有成功状态以持久化文件、Schema、确认记录和 SHA-256 为准。
7. 所有中心、所有阶段的确认卡统一使用“中文内容在前、目标语言原文在后”的双语结构；技术状态码保留，但不能用英文状态码代替中文解释。
8. 非中文正式稿在冻结前必须通过独立二次外语质量保险门；创作批次与审校批次分别标识，逐集检查语法、地区自然度、术语、习语、翻译腔、文化称谓、TTS 可读性和中文审核一致性。

## 安全边界

- 不读取或回显 Token、OAuth、Client Secret。
- 不根据标题、封面、简介或评论编造视频正文。
- 不绕过登录、付费墙、DRM、验证码或网站访问限制。
- 不逐句复制、近义词替换、改名换皮或拼接多个来源段落。
- 工坊、上传、远端修改、真实 Analytics 和长期频道学习继续遵守各自审批门。
