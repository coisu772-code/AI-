---
name: production-handoff
description: 用户明确说开始制作后，把无频道自由创作工作区绑定到用户选择的发布频道，确认制作设置，整理唯一配音稿，只复用用户已明确要求并确认的可选包装素材，再组装 Production Package v2.1 移交新漫剧工坊。简介、Hashtags 与自定义封面缺失时保持省略，不自动补齐。管理制作、恢复、重试和成片验收；只到 VIDEO_READY，不负责上传。
---

# 制作中心

先读取 [逐阶段确认契约](../channel-production/references/manual-stage-confirmations.md) 和 [三种生产模式合同](references/production-modes.md)。只有用户本次选择 `director` 精品导演模式时才读取 [Codex 视觉方案合同](references/codex-visual-plan.md)。只生成媒体资产并完成技术验收。保持目标语言正式母稿、与正式稿同批冻结的角色识别／形象锚点、角色音色和发布素材只读；任何内容修改都返回对应上游中心建立新版本。若正式稿角色包只有旁白或缺少持续出镜主要角色的形象锚点，必须返回正文阶段补齐，不能在工坊配音前临时猜角色。

## 开始制作

1. 调用 `content_workspace_get`。确认当前工作区属于本任务，列出已确认文稿与包装素材；不得读取旧频道项目填充。
2. 只有用户明确说“开始制作／进入工坊／移交制作”后，先按 [三种生产模式合同](references/production-modes.md) 显示 `A 极速自动／B 平衡（推荐）／C 精品导演` 选择卡并等待本次选择，再查询频道列表。让用户选择目标发布频道，绝不能把模式、参考频道或旧项目频道当作默认值。即使本任务已有自动完成授权，也不能跳过本次模式选择。
3. 调用 `production_capabilities`，读取频道预设、预扫描音色目录和 [36 个图片风格预设](../../assets/image-style-presets.json)，显示中文优先制作设置卡：唯一正式文稿、模式、频道、地区、语言、集数、人物配音引擎／模型／音色、是否启用纯音效、章节标题是否朗读、宫格与画幅、画风、制作方式、图片／视频提示词、实际镜头视频范围、视频输入模式（仅首帧／首尾帧）、失败策略、图片覆盖节奏和能力状态。三种模式都完整显示这些选择；模式只给推荐默认值和提示词作者，不能隐藏或禁止选项。宫格可以设置一个全局预设，也可以按集覆盖；分集覆盖写入 `gridBatch.episodeTemplates`，未覆盖的集继承 `gridBatch.template`。图片生产并发允许 1–20；当前任务已明确选择 20 时必须保留配置值 20，运行期自适应降速只能记录有效并发，不得回写覆盖配置值。人物引擎只按 `voiceSelection.humanVoiceEngines` 中 `humanVoiceSelectable=true` 的项目展示；`externalServiceProbeExecuted=false` 时，工坊旧 `available=false` 表示“未探测”而不是“不可用”，不得因此把已配置的 VOICEVOX 或 Kokoro 隐藏。本地引擎的实时健康检查和按需自动启动在制作启动时执行。用户先选择人物配音引擎，再只从该引擎的真实目录为旁白和角色推荐音色；Seed Audio 在本合同中只用于用户本次明确开启的纯音效，不得锁成人物语音引擎。关闭音效时不插入音效行、不加载 Seed Audio，首行可直接是旁白或对白；开启音效时每集必须配置一条匹配开场环境或动作的开场音效。
4. 故事图片画风使用独立 `S` 编号组，分组但完整列出 `visual_01`–`visual_36` 全部预设的编号和名称，并提供自定义入口；可以标注一个有理由的推荐项，但不得只显示推荐项。频道预设和旧项目只作为预选，不能代替当前项目确认。审核模式停在 `G5B_PRODUCTION` 等待确认；即使当前任务已授权自动完成，如果自动授权语句没有逐项给出本卡设置，也必须等待本次确认。
5. 三种模式都把“视频提示词”和“实际生成镜头视频”显示为两个独立的是／否或范围项。未明确要求视频提示词时固定关闭；未明确要求实际视频及具体镜头范围时固定 `enabled=false`、`selectionMode=none`、`count=0`。仅确认视频提示词不得开启实际视频生成。`director` 的图片与视频提示词作者固定为 Codex；`balanced` 与 `fast_auto` 按用户开关由工坊生成。
   视频输入模式默认 `first_frame`。只有用户在本次制作卡明确选择首尾帧时才使用 `first_last_frame`，且不能借此自动开启上述两个独立开关。首尾帧模式为已选分镜独立生成同镜头尾帧，并提交首帧、尾帧和该分镜的明确视频提示词；缺少任一输入或模型不支持时暂停，不得静默退回仅首帧。
6. 用户确认制作设置后，把本次选择写入 `productionMode.id + selectionSource=user + confirmed=true`，先调用 `content_workspace_bind_production`，再调用 `content_workspace_narration_prepare`，提交并冻结正式口播稿标题、中文标题对照和正式配音稿。整理稿必须保持原剧情、人物关系、关键事件、因果顺序、人物动机与结局不变；把流水账、概括交代和无意义重复改为可听见、可表演的场景、动作、自然对话、停顿、视线和情绪反应，不得凭空增加反转、人物或设定。标题只作为发布元数据，不进入配音文本；正文默认不朗读“第一章／Chapter 1”等结构标题。旁白和对白按自然语义拆行，不设置 2–8 秒建议值或 12 秒硬上限；一句出现多个可见动作、视线变化、情绪转折或因果结果时，在不删字、不改顺序的前提下拆成多个自然语义行。配音行继续独立用于 TTS 与字幕，但不得直接继承为一行一图。纯音效必须以本次设置卡中用户明确选择为准：关闭时不插入任何音效行、不加载 Seed Audio，首行可直接是旁白或对白；开启时每集第一行才使用匹配开场剧情的纯音效，其余纯音效紧跟触发它的完整旁白或对白之后，等整句说完再播放，不能抢句、重叠人声或连续堆放。开启后的纯音效必须独占一行，严格使用 `【sound：具体、简短、可直接生成的声音描述；时长1.2秒】`；同一时刻多种声音合并为一条，时长必须大于 0 且不超过 5 秒，标记内不得含对白，不朗读标记，不生成字幕，不生成独立画面，不把背景音乐当音效。然后调用 `$publishing-assets`。只有 `director` 模式在全部就绪后按 [视觉方案合同](references/codex-visual-plan.md) 生成完整逐镜方案；`fast_auto` 与 `balanced` 不读取该合同、不生成 `codexVisualPlan`。生产配置必须明确：
   - `imageStyle.presetId` 与 `imageStyle.prompt`：每个新任务都由用户从当前 `visual_01`–`visual_36` 预设或自定义画风中选择或确认，提示词不得为空；已退役预设不得进入新包；
   - `storyImageTextPolicy=forbid_visible_text`：只约束角色图、分镜图和宫格图；只有用户明确要求并确认自定义封面时，才存在独立封面资产；
   - `voiceTtsProfile`：`selectionSource=user`，保存用户本次选择的非 Seed Audio 人物配音引擎；`recommendVoicesFromSelectedEngineOnly=true`，同一 `speaker_id` 在当前项目内持续绑定同一音色，禁止中途换引擎或音色；
   - `soundEffects`：必须保存 `enabled`、`selectionSource=user`、`confirmed=true`。关闭时不接受任何 `sound_effect` 行，`engineId/modelId` 可为空，不加载 Seed Audio，`backgroundMusicEnabled=false`。开启时使用 `engineId=seed_audio`，要求每集开场音效、其余音效位于完整触发人声之后、显式时长、`maxDurationSeconds=5`、`standaloneStoryboard=false`、`mixWithAdjacentSpeech=true`、不生成字幕、`backgroundMusicEnabled=false`；时长按声音类别生成并规范化：短促动作声 0.8–1.6 秒、鼓钟回响 1.8–3.2 秒、欢呼人群 2.5–4.2 秒、风雨环境声和短旋律 3.0–4.8 秒、转场声 1.6–3.0 秒。生成后必须检查有效声音主体、完整起音与自然尾音，禁止用一秒声音加静音填满；不完整音效自动重试一次；这里的 adjacent 只表示共用分镜，不允许覆盖或打断上一条人声；
   - `codexVisualPlan`：仅 `director` 必填并接受 schema 1.5；`fast_auto` 与 `balanced` 禁止携带。完整字段与质量门只读取视觉方案合同；
   - `workshopPromptGeneration.image=true`：仅 `balanced` 由生产中心写入，用于显式调用工坊已有图片提示词分析步骤；它不是用户需要重复确认的开关；
   - `deliveryMode`：`auto_render` 或 `jianying_refine`；
   - `sceneImageCadence`：用户选择 `semantic_auto`、`seconds_range`、`line_level` 或 `custom`；八至十五秒只能作为可选推荐范围，不能成为硬编码；
   - `videoGeneration.selectionMode`：`none`、`project_first_n_storyboards`、`episode_first_n_storyboards` 或 `all_storyboards`；
   - `videoGeneration.frameInputMode`：`first_frame` 或 `first_last_frame`；后者必须同时使用 `endFrameSource=dedicated_generated`；
   - 用户没有在当前任务明确指定视频镜头范围时，必须固定 `enabled=false`、`selectionMode=none`，不得采用频道默认值或旧项目设置；
   - 开启视频生成时必须存在绑定当前 `taskId` 的确认记录，且只选择用户明确范围内的分镜；
   - 显式视频生成默认 `fallbackPolicy=pause`；只有用户已经明确允许时使用 `use_static_image`；
   - 工坊兼容接口必须为 `2.1`。
7. 调用 `production_package_assemble` 组装时，工具必须验证 `content_workspace_narration_prepare` 的来源正式稿版本／哈希与 `script_lines.json` 一致，并确认中文版禁止生产。随后生成完整生产资料总览，列出唯一配音稿、中文审核稿、各自路径与 SHA-256，以及角色、音色、制作方式、视频范围和标题；简介、Hashtags、自定义封面仅在存在时列出，否则记录为空／YouTube 自动缩略图。
8. `Production Package v2.1` 仍是机器读取包：生产正文只包含目标语言正式稿，并保留角色、音色、视觉锚点、制作配置和既有工坊界面所需的 `titleZhTranslation`；中文版长稿、中文简介／标签审核译文、拆解报告和审稿报告不得混入机器输入。
9. 只有组装工具返回完整、无敏感字段的标准包后，调用 `production_task_start`。相同项目与包版本已经有活动任务时，继续原任务，不新建第二个活动任务。

`production_task_start` 对新任务同时完成持久入队并唤醒本机常驻事件调度器。无需再次调用 `production_task_run` 才能接棒；兼容调用只负责唤醒。工坊文件状态变化会触发立即调度，六十秒看门狗只用于崩溃恢复。不得创建 Codex 定时任务来驱动生产队列。

## 已有项目局部重做与资产范围锁

用户点名旧项目并要求局部重做、修复、补做、只重新导出，或只要求打开工坊查看时，读取并严格执行 [局部重做与资产范围锁](references/selective-rework-scope.md)。未点名的既有资产默认保留；用户原话中的排除项不能被旧自动任务或完整生产默认步骤重新打开。

## 运行、查看与修复

所有模式的故障分类、单资产恢复、提示词合规修复和 Codex 最小范围接管都必须遵守 [三种生产模式合同](references/production-modes.md)，不得因接管而升级模式或扩大生产范围。

- 调用 `production_task_run` 执行 P0–P11。不要自行跳过依赖；工具会复用指纹仍有效的已完成资产。生产中心在启动前核对实际导入的一宫格／四宫格等模板与分辨率帧率设置；完成后再次核对全部已生成批次、配音与音效文件、分镜图数量和字幕排除音效。工坊项目偶发丢失音频路径但对应隔离音频文件仍存在时，只读恢复现有文件引用，不重新消耗 Seed Audio；真实文件也缺失时才报错并进入定向重试。工坊 MP4 偏离锁定分辨率或帧率时，只在生产中心隔离目录生成规范化副本，不修改工坊项目、成片包或验收报告。
- 正式任务必须由已安装的新漫剧工坊执行。只有明确标记 `synthetic=true` 的测试夹具可以使用合成 runner；正式任务不得调用本地占位音频、重复封面或其他备用执行器并把结果冒充工坊产物。
- 同一项目只允许一个工坊启动请求和一个活动任务。启动等待超时时标记为“启动待确认”，继续查询原请求；不得把超时当成普通可重试错误而再次打开工坊。本地配音服务已经启动、仍在启动或处于启动租约内时，同样只等待原进程，不得重复打开程序或脚本窗口。
- 同一台机器的工坊是全局单通道：不同对话、不同项目不得并行把命令转发到同一个工坊实例。桥接层必须先取得机器级工坊所有权；其他项目进入 `QUEUED_WAITING_WORKSHOP`，保留第一次生成的请求号并等待原所有者完成，不得反复生成请求号、启动第二个进程或把另一个项目的 CPU／FFmpeg 活动算到当前任务。只有所有者项目记录为完成／失败／取消，或所有者进程已消失且启动租约超过失效门，才能原子交给队列中的下一个项目；工坊自身还必须按内存所有者做第二次跨项目拒绝，不能只依赖可能滞后的项目 JSON 状态。
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
