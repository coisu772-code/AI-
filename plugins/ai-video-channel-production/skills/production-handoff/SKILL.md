---
name: production-handoff
description: 将已确认的 Manuscript Package v1 与 Publishing Asset Package v1 安全组装为 Production Package v2.1，移交新漫剧工坊，管理权威 Production Task v1 的制作、暂停、恢复、失败重试、剪映导出回收和成片技术验收。用户说“开始制作”“移交工坊”“继续制作”“查看制作进度”“修复失败素材”“导出剪映工程”或“验收成片”时使用；只到 VIDEO_READY，不创建发布包或上传。
---

# 制作中心

只生成媒体资产并完成技术验收。保持目标语言正式母稿、角色音色、视觉锚点和发布素材只读；任何内容修改都返回对应上游中心建立新版本。

## 开始制作

1. 调用 `production_capabilities`。确认 Production Package `2.1`、Production Task `1.0.0`、FFmpeg、ffprobe 和所选工坊兼容接口可用。不得把无外部探测的合成 runner 描述成真实模型或收费服务调用。
2. 调用 `content_handoff_check`。只接收 `SCRIPT_READY`、`PUBLISHING_ASSETS_READY`、哈希完整、质量门有效且锁定真实 16:9 封面的项目。
3. 向用户显示一张中文优先、目标语言对照的简短制作卡：项目、地区、语言、中文标题与目标语言标题、集数、锁定音色、制作方式、视频范围、失败策略和能力状态。审核模式等待确认；已有自动制作授权且所有硬门通过时可自动继续。
4. 调用 `production_package_assemble`。生产配置必须明确：
   - `deliveryMode`：`auto_render` 或 `jianying_refine`；
   - `videoGeneration.selectionMode`：`none`、`project_first_n_storyboards`、`episode_first_n_storyboards` 或 `all_storyboards`；
   - 显式视频生成默认 `fallbackPolicy=pause`；只有用户已经明确允许时使用 `use_static_image`；
   - 工坊兼容接口必须为 `2.1`。
5. 组装工具同时生成 `用户审核文档/11_完整生产资料总览.md`，汇总正式配音文本引用、角色形象、角色音色、制作方式、视频范围、标题、封面、简介、标签和机器生产包路径。向用户显示该文档路径和 SHA-256。
6. `Production Package v2.1` 仍是机器读取包：生产正文只包含目标语言正式稿，并保留角色、音色、视觉锚点、制作配置和既有工坊界面所需的 `titleZhTranslation`；中文版长稿、中文简介／标签审核译文、拆解报告和审稿报告不得混入机器输入。
7. 只有组装工具返回完整、无敏感字段的标准包后，调用 `production_task_start`。相同项目与包版本已经有活动任务时，继续原任务，不新建第二个活动任务。

## 运行、查看与修复

- 调用 `production_task_run` 执行 P0–P11。不要自行跳过依赖；工具会复用指纹仍有效的已完成资产。
- 调用 `production_task_get` 只读查询。查询不得变更、暂停或重写任务。
- 用户要求暂停时调用 `production_task_pause`；恢复时先调用 `production_task_resume`，再调用 `production_task_run`。
- 失败资产存在时调用 `production_task_retry`，只重试失败或失效资产。向用户说明失败位置、已保留资产、下一动作和是否可能增加外部服务成本。
- 上游内容或生产参数形成新版本时调用 `production_task_invalidate`。标题、简介、Hashtags 或封面变化只失效发布引用，不得重做正片媒体。
- `selected_storyboard_ids` 与每一项静态回退必须出现在任务和最终报告中。未授权的静态回退视为失败并暂停。

## 两种交付方式

### 软件内自动成片

等待 P10 产出 MP4、目标语言 SRT、timeline map 和资产索引；P11 必须通过真实 ffprobe 解码、音视频流、16:9、时长和字幕映射检查。只有 `production_result_validate` 通过时才称为 `VIDEO_READY`。

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
