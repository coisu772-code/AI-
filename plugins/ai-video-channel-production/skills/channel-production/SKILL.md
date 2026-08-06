---
name: channel-production
description: 作为 AI 视频频道生产系统唯一默认总入口，识别频道管理、视频链接或文本导入、文案拆解、单源高贴合仿写、资料融合仿写、制作文本、发布素材、工坊制作、上传准备与数据复盘意图。用户说“启动系统”“发你一个视频链接”“下载字幕并拆解”“上传文本拆解”“完全仿写”“结合资料库或联网资料仿写”“输出可制作文本”“开始制作”“准备发布”或“检查频道数据”时使用；只路由到当前真实可用 Skill，不加载已退役的频道蒸馏、旧拆文、8方向仿写或独立选题流程。
---

# AI 视频频道生产系统总入口

## 默认内容流程

```text
视频链接 / 上传文本 / 资料库 / 用户要求的公开联网资料
→ content-source
→ content-deconstruct
→ content-rewrite
   ├─ direct-rewrite：单一来源高贴合仿写
   └─ synthesis-rewrite：资料融合仿写
→ production-text
→ 未来：content-title / content-description / content-thumbnail
→ publishing-assets 汇总
→ production-handoff
```

用户在一句话中同时要求“下载、拆解、仿写并输出成稿”时，按上图连续执行；每步真实落盘并通过质量门，但不增加重复的“继续”或候选选择门。只有目标语言、目标受众、仿写模式、篇幅或来源范围存在会明显改变结果的歧义时才询问。

## 路由

- 建立／进入频道资料库、修改频道默认值、备份恢复：`$channel-onboarding`。
- 视频链接、用户文件、粘贴文本、资料库检索或用户明确要求的公开联网资料：`$content-source`。
- 拆解视频字幕或文本：`$content-deconstruct`。
- 单源高贴合仿写或多资料融合仿写：`$content-rewrite`。
- 输出可配音、字幕、分镜和制作的正式文本：`$production-text`。
- 标题、简介、封面：三个独立扩展位 `content-title`、`content-description`、`content-thumbnail`；当前未开发时显示 `PLANNED_UNAVAILABLE`，不得由其他 Skill 冒充。
- 发布素材联合核验与汇总：`$publishing-assets`。
- 工坊制作、进度、失败重试、成片技术验收：`$production-handoff`。
- `VIDEO_READY` 后本地发布包与只读状态：`$publish-video`。
- 数据采集、报告与建议：`$data-center`。
- 系统更新：`$update-ai-video-system`。

## 状态与恢复

1. 调用 `content_capabilities` 读取内容能力，再读取系统和制作能力；仅在用户要求复盘时读取数据中心能力。
2. 一个任务只绑定一个 `channelProfileId`，不得把参考视频频道当成发布频道。
3. 进度查询只读；恢复只补缺失单元，不重做哈希仍有效的来源、拆解或正式文本。
4. 正式内容主链只使用 Source Package → Content Deconstruction Package → Topic Package → Manuscript Package。旧 Analysis／Writing Style 项目只为历史只读兼容，不作为新任务入口。
5. 所有成功状态以持久化文件、Schema、确认记录和 SHA-256 为准。

## 安全边界

- 不读取或回显 Token、OAuth、Client Secret。
- 不根据标题、封面、简介或评论编造视频正文。
- 不绕过登录、付费墙、DRM、验证码或网站访问限制。
- 不逐句复制、近义词替换、改名换皮或拼接多个来源段落。
- 工坊、上传、远端修改、真实 Analytics 和长期频道学习继续遵守各自审批门。
