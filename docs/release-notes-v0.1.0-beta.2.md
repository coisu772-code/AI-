# AI 视频频道生产系统 0.1.0-beta.2

这是阶段 1“GitHub 发布骨架与跨中心契约”的首个 Beta，只用于验证安装、Codex 入口和跨中心数据契约。

## 本次包含

- Codex marketplace 与 `ai-video-channel-production` 插件；
- 系统总入口和频道建库前提检查两个 Skills；
- 10 类 JSON Schema 2020-12 跨中心契约及有效示例；
- `canonical-json-v1` 内容哈希、上游版本／哈希引用和自动校验；
- Windows 安装、幂等重装、升级、回滚和卸载脚本；
- 统一发布清单、组件兼容矩阵与 GitHub Actions 验证。

## 安装

Codex CLI：

```powershell
codex plugin marketplace add coisu772-code/AI- --ref v0.1.0-beta.2
codex plugin add ai-video-channel-production@novel-manga-production
```

或下载 `ai-video-channel-production-v0.1.0-beta.2.zip`，使用同一 Release 中的 `SHA256SUMS.txt` 核验后解压，运行 `installer\install.cmd`。

## Beta 边界

本版本不会创建真实频道资料库，不采集 YouTube 或小说资料，不生成选题、文稿、封面或视频，不调用工坊正式生产，不上传 YouTube，也不读取 Analytics 或频道私有数据。

## 验收结果

- 插件与 marketplace 官方结构校验通过；
- 10 个契约示例和 6 个自动测试通过；
- 隔离环境中的安装、重复安装、升级、回滚、卸载和 Codex 本地加载通过；
- 仓库安全扫描未发现凭据、数据库、可执行文件或媒体资产。
