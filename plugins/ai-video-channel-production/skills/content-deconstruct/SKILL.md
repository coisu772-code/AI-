---
name: content-deconstruct
description: 完整拆解一个或多个视频字幕、用户上传文本、小说正文或资料库规范正文，输出事实、结构、钩子、节奏、叙述声音、表达方式、情绪与观众回报、可信度、可迁移方法及禁止复制边界。用户说“拆解这个视频文案”“拆这份文本”“分析结构和写法”“比较这些文案”或“拆完后仿写”时使用；输入必须来自可追溯 Source Package，完成后可直接交给 content-rewrite。
---

# 文案拆解

视频字幕与上传文本使用同一条完整拆解管道。输入长度只改变分批方式，不减少维度、结构层级或质量门。

## 进入

1. 取得 `$content-source` 返回的 `CONTENT_READY` Source Package；`PARTIAL` 必须有本次接受记录。
2. 调用 `content_deconstruction_capabilities`。
3. 调用 `content_deconstruction_prepare`：一条使用 `single`，多条并列使用 `parallel`，需要比较时使用 `compare`。
4. 用 `content_deconstruction_read_source` 读到 `complete=true`。不得只读开头后推断全文。

## 每个来源的完整拆解

分别生成以下五类结果，并绑定段落、章节或时间证据：

- `originalFacts`：原文直接支持的事实。
- `analysisConclusions`：由 fact ID 支持的分析结论及置信度。
- `transferableMethods`：可迁移功能、适用条件和不能照搬的实现边界。
- `prohibitedCopy`：原句、专名、标志性表达、完整事件顺序、单一作品主线和其他可识别内容。
- `unknowns`：资料无法证明的信息。

完整覆盖：核心承诺、目标受众体验、开场兑现、逐段功能、事件因果、人物与关系功能、世界／规则、信息释放、钩子与转场、段落呼吸、叙述视角、声音与句式、情绪曲线、阶段回报、高潮与结尾、标题承诺兑现、时间节奏、可信度限制、生产适配和原创边界。

逐段功能图必须连续覆盖全文，不重叠、不漏段。视频有时间映射时保留起止秒；普通文本使用稳定段落或章节 ID。

## 冻结

1. 每个来源调用一次 `content_deconstruction_checkpoint`；多来源仍保持独立分析。
2. 调用 `content_deconstruction_finalize`，生成 Content Deconstruction Package v1。
3. `compare` 只在独立拆解完成后比较共享功能与差异；禁止求平均或按来源段落拼接。
4. 调用 `content_deconstruction_integrity_check` 验证来源版本、全文覆盖、证据定位和哈希。
5. 查询或恢复已有拆解时调用 `content_deconstruction_get`；查询只读，不改写检查点。

若用户原请求包含仿写，完成后直接调用 `$content-rewrite`。详细输出见 [references/deconstruction-contract.md](references/deconstruction-contract.md)。

## 边界

- 不下载来源，不直接写新文案，不生成多个方向菜单。
- 不把公开播放量写成 CTR、留存率或 Studio 受众事实。
- 不调用标题、简介、封面、工坊、上传或长期学习。
