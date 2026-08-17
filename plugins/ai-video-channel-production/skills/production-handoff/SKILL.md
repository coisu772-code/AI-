---
name: production-handoff
description: 用户明确说开始制作后，把无频道自由创作工作区绑定到用户选择的发布频道，确认制作设置，整理唯一配音稿，复用已确认包装素材并只补齐缺失项，再组装 Production Package v2.1 移交新漫剧工坊。管理制作、恢复、重试和成片验收；只到 VIDEO_READY，不负责上传。
---

# 制作中心

先读取 [逐阶段确认契约](../channel-production/references/manual-stage-confirmations.md) 和 [Codex 视觉方案合同](references/codex-visual-plan.md)。只生成媒体资产并完成技术验收。保持目标语言正式母稿、角色音色和发布素材只读；视觉方案在本次制作设置确认后由 Codex 根据锁定文稿、角色和画风生成，进入生产包后只读。任何内容修改都返回对应上游中心建立新版本。

## 开始制作

1. 调用 `content_workspace_get`。确认当前工作区属于本任务，列出已确认文稿与包装素材；不得读取旧频道项目填充。
2. 只有用户明确说“开始制作／进入工坊／移交制作”后才查询频道列表。让用户选择目标发布频道，绝不能把参考频道或旧项目频道当作默认频道。
3. 调用 `production_capabilities`，读取频道预设、预扫描音色目录和 [36 个图片风格预设](../../assets/image-style-presets.json)，显示中文优先制作设置卡：唯一正式文稿、频道、地区、语言、集数、配音引擎／模型／音色、章节标题是否朗读、宫格与画幅、图片提示词（关闭／由 Codex 生成）、视频提示词（关闭／由 Codex 生成）、画风、制作方式、实际镜头视频范围、视频输入模式（仅首帧／首尾帧）、失败策略和能力状态。用户只选开关和范围，不要求用户编写提示词。
4. 故事图片画风使用独立 `S` 编号组，分组但完整列出 `visual_01`–`visual_36` 全部预设的编号和名称，并提供自定义入口；可以标注一个有理由的推荐项，但不得只显示推荐项。频道预设和旧项目只作为预选，不能代替当前项目确认。审核模式停在 `G5B_PRODUCTION` 等待确认；即使当前任务已授权自动完成，如果自动授权语句没有逐项给出本卡设置，也必须等待本次确认。
5. 把“视频提示词”和“实际生成镜头视频”显示为两个独立的是／否或范围项。未明确要求视频提示词时固定关闭；未明确要求实际视频及具体镜头范围时固定 `enabled=false`、`selectionMode=none`、`count=0`。仅确认视频提示词不得开启实际视频生成。图片或视频提示词一旦开启，作者固定为 Codex；工坊旧提示词生成器不再重写。
   视频输入模式默认 `first_frame`。只有用户在本次制作卡明确选择首尾帧时才使用 `first_last_frame`，且不能借此自动开启上述两个独立开关。首尾帧模式为已选分镜独立生成同镜头尾帧，并提交首帧、尾帧和该分镜的明确视频提示词；缺少任一输入或模型不支持时暂停，不得静默退回仅首帧。
6. 用户确认制作设置后先调用 `content_workspace_bind_production`，再调用 `content_workspace_narration_prepare` 整理正式配音稿。默认不朗读“第一章／Chapter 1”等结构标题；只有本次制作卡明确允许时才保留。然后调用 `$publishing-assets` 复用已确认标题、简介、Hashtags 和封面，只生成缺失项。全部就绪后，Codex 按 [视觉方案合同](references/codex-visual-plan.md) 基于唯一正式配音稿、角色关系与已选画风，先规划开篇钩子、人物关系、核心矛盾、铺垫／反转／回报、复杂度自适应页数与连续性圣经，再生成漫画角色设计、逐镜表演和已开启的图片／视频提示词，作为 `productionConfig.codexVisualPlan` 交给 `production_package_assemble`。重要情绪必须用特写或破格构图和至少两个可见信号表达，相邻镜头不得重复同一种情绪爆点；不得用画面文字代替表演。每镜先分段分析再压缩合并，图片提示词不超过 600 字符，视频提示词不超过 500 字符。这个过程不新增强制确认门；组装工具会生成用户可查看文档。生产配置必须明确：
   - `imageStyle.presetId` 与 `imageStyle.prompt`：每个新任务都由用户从当前 `visual_01`–`visual_36` 预设或自定义画风中选择或确认，提示词不得为空；已退役预设不得进入新包；
   - `storyImageTextPolicy=forbid_visible_text`：只约束角色图、分镜图和宫格图，正式封面文字继续使用已确认封面资产；
   - `codexVisualPlan`：图片或视频提示词任一开启时必填，使用 schema 1.1，角色参考固定 `identity_only`，逐镜完整且仅覆盖正式稿行；必须绑定故事节拍、镜头合同、可见情绪信号、地点／服装／道具连续性和长度预算，工坊不得覆盖已锁定提示词；
   - `deliveryMode`：`auto_render` 或 `jianying_refine`；
   - `videoGeneration.selectionMode`：`none`、`project_first_n_storyboards`、`episode_first_n_storyboards` 或 `all_storyboards`；
   - `videoGeneration.frameInputMode`：`first_frame` 或 `first_last_frame`；后者必须同时使用 `endFrameSource=dedicated_generated`；
   - 用户没有在当前任务明确指定视频镜头范围时，必须固定 `enabled=false`、`selectionMode=none`，不得采用频道默认值或旧项目设置；
   - 开启视频生成时必须存在绑定当前 `taskId` 的确认记录，且只选择用户明确范围内的分镜；
   - 显式视频生成默认 `fallbackPolicy=pause`；只有用户已经明确允许时使用 `use_static_image`；
   - 工坊兼容接口必须为 `2.1`。
7. 组装工具必须验证 `content_workspace_narration_prepare` 的来源正式稿版本／哈希与 `script_lines.json` 一致，并确认中文版禁止生产。随后生成完整生产资料总览，列出唯一配音稿、中文审核稿、各自路径与 SHA-256，以及角色、音色、制作方式、视频范围、标题、封面、简介和标签。
8. `Production Package v2.1` 仍是机器读取包：生产正文只包含目标语言正式稿，并保留角色、音色、视觉锚点、制作配置和既有工坊界面所需的 `titleZhTranslation`；中文版长稿、中文简介／标签审核译文、拆解报告和审稿报告不得混入机器输入。
9. 只有组装工具返回完整、无敏感字段的标准包后，调用 `production_task_start`。相同项目与包版本已经有活动任务时，继续原任务，不新建第二个活动任务。

## 运行、查看与修复

- 调用 `production_task_run` 执行 P0–P11。不要自行跳过依赖；工具会复用指纹仍有效的已完成资产。
- 正式任务必须由已安装的新漫剧工坊执行。只有明确标记 `synthetic=true` 的测试夹具可以使用合成 runner；正式任务不得调用本地占位音频、重复封面或其他备用执行器并把结果冒充工坊产物。
- 同一项目只允许一个工坊启动请求和一个活动任务。启动等待超时时标记为“启动待确认”，继续查询原请求；不得把超时当成普通可重试错误而再次打开工坊。本地配音服务已经启动、仍在启动或处于启动租约内时，同样只等待原进程，不得重复打开程序或脚本窗口。
- 调用 `production_task_get` 只读查询。查询不得变更、暂停或重写任务。
- 用户要求暂停时调用 `production_task_pause`；恢复时先调用 `production_task_resume`，再调用 `production_task_run`。
- 失败资产存在时调用 `production_task_retry`，只重试失败或失效资产。向用户说明失败位置、已保留资产、下一动作和是否可能增加外部服务成本。
- 上游内容或生产参数形成新版本时调用 `production_task_invalidate`。标题、简介、Hashtags 或封面变化只失效发布引用，不得重做正片媒体。
- `selected_storyboard_ids` 与每一项静态回退必须出现在任务和最终报告中。未授权的静态回退视为失败并暂停。

## 两种交付方式

### 软件内自动成片

等待 P10 产出 MP4、目标语言 SRT、timeline map 和资产索引；所有路径必须位于当前任务的隔离工坊目录且绑定同一请求、项目和生产包。P11 必须通过真实 ffprobe 解码、音视频流、16:9、时长和字幕映射检查，同时记录分镜图数量、唯一图片哈希数、精确重复率及抽样视频帧变化。多场景项目若只有一张唯一分镜、超过半数图片精确重复或抽样帧完全不变化，必须失败，不能把重复封面口播版冒充正式成片。只有 `production_result_validate` 验证真实工坊来源、`placeholder=false`、媒体完整性 `PASSED` 后才称为 `VIDEO_READY`。

### 剪映精修

P10 只生成自包含 Jianying Draft Package v1、原生字幕轨描述和独立 SRT，不启动或点击剪映。任务进入 `AWAITING_JIANYING_EXPORT` 后，向用户显示工程名和隔离导出目录。

用户导出 MP4 后调用 `production_jianying_export_ingest`。必须同时提供绑定 `projectId`、`productionTaskId`、`packageHash` 和视频 SHA-256 的身份旁车文件；身份错误或不同成片重复回收必须拒绝。回收后执行与自动成片相同的 P11 技术门和结果包校验。

## 完成边界

完成卡只显示：任务、制作方式、成片、字幕、技术参数、回退项、结果包路径和 `VIDEO_READY`。不得在本 Skill 中：

- 创建或复制 `.ready` 发布包；
- 调用发布中心、OAuth、上传、回执或 Analytics；
- 改写正式母稿、重排文稿行、替换说话人或情绪；
- 重选锁定音色或重写角色视觉锚点；
- 写入长期频道学习账本。

正式安装工坊尚未声明 2.1 时，明确报告“契约和隔离构建已通过、正式部署未升级”，不得把隔离测试说成正式程序已经部署。
