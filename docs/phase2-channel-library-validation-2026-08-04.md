# 阶段2频道资料库与本地工具服务验收记录（2026-08-04）

## 结论

阶段2的“频道资料库与本地工具服务”独立开发方向已在隔离目录通过验收，并已连接发布中心正式只读 CLI。它不代表整个阶段2已经完成：最终安装布局仍需配置发布中心程序发现，并携带正式 Python 运行时与预扫描真实音色目录，之后由阶段2主任务执行联合验收。

本次没有连接真实 YouTube 频道，没有执行 OAuth，没有读取或迁移现有用户数据，没有调用工坊、上传视频、读取 Analytics、推送 GitHub 或创建 Release。

## 已实现

- 插件内可安装的 stdio MCP 本地工具服务骨架，协议 `1.0.0`，服务版本 `0.2.0-dev.1`。
- 发布中心正式 `youtube-publisher-center/channel-list/v1` CLI 适配器：不写 stdin，支持结构化错误、超时、输出上限、协议检查、身份去重、九字段白名单和敏感材料拒绝；另保留抽象 subprocess 提供方供未来扩展。
- `system.db` 频道注册库和每频道独立 `channel.db`、标准资料目录、Channel Profile 与 Production Profile v1 实例。
- 首次建库阶段 A／B、状态约束、真实频道再校验、预扫描音色再校验和阶段2自动上传阻断。
- 一个任务只绑定一个频道、新任务重新绑定、绑定校验值轮换、重复建库幂等与错绑拦截。
- 仅本次覆盖和频道长期默认分离；频道默认变更生成新版本，不影响已有项目。
- 快速／完整备份基础格式、`.avchannel` 导出／导入、身份冲突处理、恢复前备份、失败回滚和完整性检查。
- system/channel Schema 版本检查、升级前数据库备份、失败恢复和更高版本只读保护。
- `channel-production` 与 `channel-onboarding` 阶段2流程、确认门和安全边界。
- draft 候选清单 `release-v0.2.0-dev.1.json`，不改变已发布 `v0.1.0-beta.2`。

## 验证

统一入口：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\tools\Test-Stage2.ps1
```

联合正式发布中心 CLI 时增加：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\tools\Test-Stage2.ps1 -PublisherCliPath <youtube-publisher-channel-list.exe>
```

最近结果：

- 插件与 marketplace 校验通过。
- 两项 Skills 通过 `quick_validate.py`。
- 10 类冻结契约示例继续通过。
- 仓库安全扫描通过。
- 阶段2单元／集成测试 15 项全部通过。
- 全部 21 项仓库测试通过。
- 使用 draft 清单完成 `0.2.0-dev.1` 隔离安装与幂等重装，再从安装目录通过 PowerShell 启动器启动 MCP，完成 `initialize` 握手并只在隔离数据根创建 `system.db`。
- 测试结束后隔离目录自动清除。

覆盖场景包括：双阶段建库、v1 契约校验、重复调用幂等、新任务重绑、跨频道错绑、无频道、未知音色、阶段2自动上传阻断、发布中心正式 CLI 与结构化错误、临时发布数据库调用前后 SHA-256 不变、扩展命令超时与脱敏、本次覆盖、默认版本升级、备份、迁移导入、身份冲突、恢复失败回滚、数据库迁移失败回滚、重启持久化和更高 Schema 保护。

## 接口依赖

1. YouTube 发布中心已经提供 `youtube-publisher-channel-list.exe --api-version v1`；联合发布需要安装器携带或定位该程序。
2. 安装器写入 `config/publisher-interface.json` 非敏感发现文件，或配置 `AIVCP_PUBLISHER_CHANNEL_LIST_EXE`／`AIVCP_PUBLISHER_CHANNEL_LIST_COMMAND_JSON`。
3. 安装器提供兼容 Python 运行时；开发环境允许使用 `uv` 回退。
4. 新漫剧工坊或安装组件提供不含密钥的 `voice-catalog.json` v1；没有真实目录时阶段 B 明确阻塞。
5. 阶段2联合任务需要在不读取真实凭据的前提下验证发布中心正式命令输出，但 OAuth 与真实频道确认仍由用户操作。

## 残余风险

- 当前是未发布工作树实现，没有更新、推送或发布新的 GitHub Beta。
- 已使用发布中心真实构建程序和隔离临时数据库完成联合调用；尚未在正式安装布局中完成程序发现。
- 正式 Python 运行时与真实音色目录尚未进入发布工件。
- `.avchannel` 当前提供完整文件哈希与身份再校验，但尚未增加发布方数字签名；导入只允许当前发布中心已确认的同一真实频道。
- 恢复替换是破坏性动作，Skill 已要求用户明确确认；本次仅在隔离测试数据上执行。

## 独立方向退出条件

本方向的本地实现与隔离验证通过，可以交给阶段2主任务联合发布中心接口。整个阶段2尚不能退出，直至正式发布中心接口、真实音色目录、安装运行时和联合安装验收全部通过。
