# 更新记录

## 0.11.0-rc.4 - GitHub prerelease

- 修复视频／文本仿写请求误入“素材研究与原创重构”的路由问题；来源取得后固定进入完整拆解，默认停在迁移方向确认门。
- 拆解新增来源故事 DNA、自然扩展缺口、三档各5个来源锚定方向和105组去重矩阵；无来源依据的通用职业、机构、灾难、听证会、系统、追放或打脸模板不能冻结。
- 仿写移除统一四章和固定九段式冲突，改为读取项目已确认的短篇／长篇、精确篇幅和集数，并校验方向来源贴合与自然扩展依据。
- 修正内容拆解工具接口未暴露完整审核文档和方向包、视频拆解接口反而错误要求这些字段的问题。

## 0.11.0-rc.3 - GitHub prerelease

- `content-deconstruct` 改为通用三档迁移：高贴合迁移、中度重构、大胆创新各 5 个，共 15 个方向，并执行组内与跨组七维去重。
- 每个方向新增 `mustPreserve`、`allowedToChange`、`mustRebuild` 与 `protectedExpressionBoundary`，同时执行原文核心体验保留门和非换皮原创门。
- `content-rewrite` 按用户确认的改编档位执行，不再把同时重建人物、关系、主因果、高潮和结局作为所有档位的统一要求。
- 旧版尚未确认的方向卡需要重新生成；已经进入正文的旧项目保持原锁，不自动改写。
- 工坊、发布中心、Publish Package 2.1.0 与便携运行时保持 `0.11.0-rc.2` 已验证组件，不包含或迁移用户频道、项目、凭据和运行数据。

## 0.11.0-rc.2 - GitHub prerelease

- 完整保留 `0.11.0-rc.1` 的外语质量保险门、中文优先双语确认卡、上传前最终中文验收卡与 Publish Package v2.1.0。
- YouTube 发布中心升级为 `0.9.0-rc.2`，内置 Windows 便携时区数据库；在新电脑或隔离安装环境中也能正确识别 `Asia/Tokyo` 等 IANA 时区。
- 发布中心继续强制 MANUAL、SCHEDULED、AUTO 全部停在 `FINAL_CHINESE_REVIEW_CONFIRMATION_REQUIRED`，确认最终中文验收不会解除 OAuth、频道授权、配额等其他安全门。
- 新漫剧工坊仍为 `2.4.0-rc.1`，按本系统 `rc.2` 重新封装完整便携包，并复验 FFmpeg、Python、Node.js、Wenku8 与 Sharp。
- 不包含 Token、API Key、Cookie、OAuth 凭据、频道、项目或运行数据；升级不迁移、不删除、不覆盖用户数据。

## 0.11.0-rc.1 - GitHub prerelease

- 内容流程改为四阶段创作 Skills，并新增独立外语质量保险门；非中文正式稿缺少目标语言质量证据时不得进入发布。
- 所有用户确认卡采用中文优先、目标语言对照；上传前新增最终中文验收卡，正式发布包升级为 Publish Package v2.1.0。
- YouTube 发布中心升级为 `0.9.0-rc.1`，校验并导入最终中文验收卡；MANUAL、SCHEDULED、AUTO 均不能跳过 `FINAL_CHINESE_REVIEW_CONFIRMATION_REQUIRED`。
- 新漫剧工坊升级为 `2.4.0-rc.1`，纳入安全书籍导入、本地 Wenku8 CLI、单行字幕、可见动态、宫格预设和 NVIDIA H.264 探测；完整包包含 FFmpeg、Python、Node.js、Wenku8 与 Sharp。
- 合并跨电脑工坊隔离交接和正式发布中心交接修复，保留离线 Codex 交接边界；未执行 Google/YouTube OAuth 或真实视频上传。
- 不包含 Token、API Key、Cookie、OAuth 凭据、频道、项目或运行数据；升级不迁移用户数据。

## 0.10.2-rc.1 - 本地候选

- 修复工坊项目默认目标落在隔离根之外而触发 `WORKSHOP_TARGET_NOT_ISOLATED` 的问题。
- 把完整生产预设合同转换为工坊可校验的标准来源引用，修复 `PRODUCTION_PACKAGE_V21_SOURCE_LOCK_INVALID: productionPreset`。
- 频道首次预设明确确认动态分镜范围和上传策略；不再把“自动成片”静默冻结成 `videoGeneration.enabled=false`。
- 发布包默认正式交接到 YouTube 发布中心主数据库；Codex 交接保持离线，OAuth 与真实上传仍只由桌面发布中心按安全门执行。
- 统一约束目录的换行归一化哈希，消除 Windows/Linux 或不同解压工具导致的跨电脑误判。
- 新增正式交接、实时状态和真实回执查询测试；未执行 OAuth 或真实视频上传。

## 0.10.1-rc.1 - GitHub prerelease

- 内置固定版本的 `yt-dlp`、`yt-dlp-ejs` 与 Deno JavaScript 运行时，其他电脑无需预装 Python、下载器或浏览器扩展即可读取可公开访问的 YouTube 视频资料与字幕。
- 安装、升级、修复、启动和健康检查统一绑定并校验便携 YouTube 采集器，拒绝环境变量篡改、系统 PATH 误用和不完整运行时。
- 新漫剧工坊升级为 `2.3.1-rc.1`，Kokoro 清单与全部分卷严格绑定到同一个公开系统 Release，修复错误校验到私有工坊仓库而导致的一键安装失败。
- 三套未变化的 Kokoro 大型运行包继续复用 `v0.10.0-rc.1` 的公开、哈希锁定资产，本次 Release 仅上传实际变化的组件。
- 不包含 Token、API Key、OAuth 凭据、频道、项目或运行数据；未执行 Google/YouTube OAuth 或真实视频上传。

## 0.10.0-rc.1 - GitHub prerelease

- 新漫剧工坊升级为 `2.3.0-rc.1`，新增 Kokoro-FastAPI CPU、NVIDIA 和 NVIDIA Blackwell 三种一键本地运行时选择，并保留现有 VOICEVOX 流程。
- Kokoro 运行包改从公开的统一系统 GitHub Release 获取，支持 prerelease；严格锁定分卷清单、大小、SHA-256 和来源地址，拒绝私有仓库或不受信任下载地址。
- 统一 Release 新增三套 Kokoro 清单与分卷附件的构建、组装哈希、发布前校验和上传清单；统一安装器仍只安装五个核心 ZIP，不会自动安装大型可选语音包。
- 新漫剧工坊便携包名称、根目录、版本和源提交均已锁定，继续复用已发布并重新校验的 YouTube 发布中心 `0.8.0-rc.2`。
- 不包含 Token、API Key、OAuth 凭据、频道、项目或运行数据；已在明确确认后完成 GitHub 推送和 prerelease 创建，未执行 Google/YouTube OAuth 或真实上传。

## 0.9.0-rc.1 - GitHub prerelease

- 新增安全更新中心：只读取版本索引和发布清单，校验版本、大小与 SHA-256 后执行事务式升级，并在显式定位信息异常时关闭更新。
- 新增频道蒸馏、视频拆解和原创仿写三组内容分析 Skills、数据契约与本地工具能力。
- 新漫剧工坊升级为 `2.2.0-rc.1`，合并 Production Package 2.1、Seed Audio、生产提速与单行字幕，并保留锁定音色校验。
- 统一安装包继续复用已发布且重新校验哈希的 YouTube 发布中心 `0.8.0-rc.2`，不包含其工作区未提交修改。
- 未包含 Token、API Key、OAuth 凭据、频道、项目或运行数据；未执行 GitHub 推送、Release 创建、OAuth 或真实上传。

## 0.8.0-rc.2 - 本地统一候选（未发布）

- 新增锁定五资产的 Windows 统一安装入口：核心插件、独立 Python 3.12.13 运行时、工坊与发布中心分别校验。
- 支持同目录离线或受清单控制的在线下载、SHA-256 拒绝、事务切换、自动回滚、幂等重装、升级、修复、回滚与卸载保留数据。
- FFmpeg/ffprobe 作为工坊内的显式受管组件记录版本、哈希、GPL-3.0 许可证和健康检查。
- Codex CLI 缺失时输出手动注册说明；CI 仅预检，不能自动产生缺少桌面资产的 Release。
- 未执行 OAuth、真实上传、Studio 私有数据读取或长期学习写回；发布中心第三方告知仍需人工审查。

## 历史

阶段 1–8 RC.1 的详细记录已移到 `docs/implementation-history.md` 和各阶段验证报告。
