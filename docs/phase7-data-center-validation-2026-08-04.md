# 阶段 7 数据中心验证报告（2026-08-04）

## 1. 结论

阶段 7 的本地、可安装数据闭环达到 **GO**：Publication Receipt 注册门、Metric Catalog v1、六级事实等级、公开／owner／system 数据适配、原始数据只追加、Analytics Snapshot v1、T+24／T+7／T+28 检查点、视频与频道报告、Recommendation Card v1、timeline retention 证据映射、频道隔离和学习确认门均已实现并通过隔离测试。

正式频道数据接入仍为 **NO-GO / WAITING**，原因符合预期：阶段 6 只有本地发布包，没有真实 Publication Receipt v1 和 YouTube video ID；owner Analytics 独立显示 `AUTH_REQUIRED`。本阶段没有发起 OAuth、扩大 scope、读取或保存 token/secret、调用私有 Analytics API、迁移用户数据库、上传视频、写长期学习规则、push 或创建 Release。

## 2. 实现范围

- 新增 7 个本地数据中心工具：能力检查、视频注册、采集、报告、建议列表、学习决定、只读进度。
- 新增非技术用户 `data-center` Skill，可路由“检查频道数据”“复盘视频”“生成 7 天报告”“查看建议”等自然语言请求。
- 新增 Metric Catalog `2026.08.04.1`：27 个统一指标、14 个维度、4 类来源、9 个官方资料来源。文件 SHA-256：`498b4eea2f9f6553718b1e9cb0bbc3520613ff2d2f0b5e044ecaa158d67eeafc`。
- 强制事实等级：`SYSTEM_FACT`、`PUBLIC_API_FACT`、`OWNER_ANALYTICS_FACT`、`SAMPLE_OBSERVATION`、`INFERENCE`、`UNKNOWN`。未知、延迟和阈值保护均保持 `null`，不得填 0。
- 正式命名空间为 `data/channels/<profile>/analytics/`；测试数据只能进入 `data/synthetic-fixtures/channels/<profile>/analytics/`。隔离库为 `data-center-v1.sqlite3`，不会读取、合并或迁移其他频道的 `channel.db`。
- Analytics Snapshot v1 每版包含 `manifest`、`query-plan`、`raw-bindings`、`normalized-metrics`、`completeness`、`source-lock`；原始数据只追加，同查询结果 hash 不变时幂等复用，迟到数据产生新修订。
- 视频报告与频道策略报告同时输出 JSON 和普通用户 Markdown，状态明确区分 `provisional`、`complete`、`revised`、`superseded`。
- 建议卡默认 `AWAITING_LEARNING_DECISION`。`channel_default` 和 `must_avoid` 始终返回 `LONG_TERM_LEARNING_APPROVAL_REQUIRED`，包括自动模式；实现未调用现有 `channel_learning record`。

## 3. 权限与事实边界

Analytics 授权能力与上传授权完全分离。默认状态为 `AUTH_REQUIRED`、`available=false`；只声明最小只读 scope `https://www.googleapis.com/auth/yt-analytics.readonly`，收入 scope 默认关闭且不可用。Codex 接口只接收标准化数据，不接收凭据。

公开适配只将有权导入或录制的 YouTube Data API 公共响应标为 `PUBLIC_API_FACT`。仅有公开数据时，CTR、留存、流量来源、设备、人口、订阅者状态与收入均保持 `UNKNOWN`，不会被播放量或其他公开指标替代。三市场 T+7 中的 owner 数据均明确标记为 `syntheticFixture=true`，仅用于录制 fixture 验收，不代表真实 Studio 表现。

指标目录中的当前 API 字段与权限说明仅依据 Google/YouTube 官方资料，核验日期为 2026-08-04；资料 URL、适用字段、权限与延迟说明保存在 Metric Catalog 内。

## 4. 三市场离线数据链

验收根目录：

`E:\小说漫全自动化生产\runtime\stage7-validation-synthetic\data-center-20260804-r1`

总索引：`summary.json`，文件 SHA-256 `01ac4bbc150059d030b600f0637f1c9e67566136500597a425b2d6f28bad4c92`。所有路径均位于 `data/synthetic-fixtures/`；正式 `data/channels/` 未写入测试记录。

下表路径相对于验收根目录。每个快照路径内均有完整的六文件 Snapshot v1；报告另有同名 `.md` 普通用户版本。

| 市场／检查点 | 状态 | Snapshot 路径；hash | Video Report 路径；hash | Channel Report 路径；hash | Recommendation 路径；hash |
|---|---|---|---|---|---|
| ja-JP T+24H | provisional；public-only，owner UNKNOWN | `data\synthetic-fixtures\channels\stage7-ja-profile\analytics\snapshots\synthetic-ja-JP-stage7\tplus24h\v001-as_843b0b68b60c5f6b2f41edf3`；`cccf238d8088cdefd78e7890ff86eefb1c511965d91d97648cae03f489ad1149` | `...\reports\videos\synthetic-ja-JP-stage7\tplus24h-v001.json`；`32f906b1ff01c9eb42d8a21a495e315441c6fd2f4da5b97864c721842127ab16` | `...\reports\channel\tplus24h-synthetic-ja-JP-stage7-v001.json`；`db576a6d7a2aa65d97bf0c6f0acef4a701f20f5a2fe8ee24f85937526ad1e764` | `...\recommendations\rec_1aeada126534b48880ce32c8.json`；`59087b3028f5b7a3fe3c220da877a9b561dbe53760780a2df66c7073096b2dd1` |
| ja-JP T+7D | revised；迟到 owner fixture | `...\snapshots\synthetic-ja-JP-stage7\tplus7d\v002-as_4bc40cac397ee9b92855bef5`；`af448b11bd5e28790248a705ac99cb5f5c4e540cf0bbe8c5a1b349c7e3642e1f` | `...\reports\videos\synthetic-ja-JP-stage7\tplus7d-v002.json`；`7427d559d9e012aa700164bc0ca6f1edb8fcd391f561a74a2f42493dc4ede36b` | `...\reports\channel\tplus7d-synthetic-ja-JP-stage7-v002.json`；`af3d25f3ca4d4f563e9e7ea7d147e8bafb1ccbfea1bd2946c000ef7cf6790de1` | `...\recommendations\rec_82d43c9eb19efadca0776614.json`；`ce5371f4eb01aebda1ded18ed963017056e04aa61ff7623df94acfeb0899f386` |
| ja-JP T+28D | complete；建议门 | `...\snapshots\synthetic-ja-JP-stage7\tplus28d\v001-as_2a95fc757bfe01a102542bac`；`277cb98b10d6087eaaabfeb4fafb480e5b0075c922f9d15b9db58e842687aea5` | `...\reports\videos\synthetic-ja-JP-stage7\tplus28d-v001.json`；`f5a2984949adc9e7cb9f633d2ec8344428b66ca56233c4e8a9ee76f78ceaaacd` | `...\reports\channel\tplus28d-synthetic-ja-JP-stage7-v001.json`；`01c0df16ea400ce815b6d8e63df21cb0da58fdae07d544cc8d904052fc443fad` | `...\recommendations\rec_852a3e69ce69327086b52a86.json`；`fc68d6bccba7ca441addc33b61eb80e054d09e028bf99e00053a06b4c9d5a246` |
| zh-CN T+24H | provisional；public-only，owner UNKNOWN | `data\synthetic-fixtures\channels\stage7-zh-profile\analytics\snapshots\synthetic-zh-CN-stage7\tplus24h\v001-as_db47e5354c232d17021d2232`；`88fb44f0bc3a9b48321e1ebab10304aff1cf7c365582349a54276034a905c8df` | `...\reports\videos\synthetic-zh-CN-stage7\tplus24h-v001.json`；`ed19e76597b43f8a4221ef7ab9731e2d8d348ae8ad6d21b77417b7e0282b4fc6` | `...\reports\channel\tplus24h-synthetic-zh-CN-stage7-v001.json`；`bbe22b069589e6995309ff8082e1aef0ae17facf9508d4245476d19e536ee627` | `...\recommendations\rec_7a9768d69817d750179ad049.json`；`ac2b53fd94609787229755899c0e22b11314fbac662bcde9bb5796902c11f181` |
| zh-CN T+7D | revised；迟到 owner fixture | `...\snapshots\synthetic-zh-CN-stage7\tplus7d\v002-as_64d0a50fc3ae41a84a23b6e1`；`bab01cebf4401ea402c20831c5dc56365f8fca3eef30b285d9b85d51938d5525` | `...\reports\videos\synthetic-zh-CN-stage7\tplus7d-v002.json`；`9f6fe140efff879674ca344a265e356636e7be9097eaf4361064647eaffce596` | `...\reports\channel\tplus7d-synthetic-zh-CN-stage7-v002.json`；`2cf67f1748fcf90faec89bfdb52ccde1a263a7d90b73164f99f9efccb4817622` | `...\recommendations\rec_c9e96db0dad38e2920ca20cc.json`；`483df7b96f2af1692a03cefee3b3ae5de6a76fcf3f164b9d740236d0f0222fe0` |
| zh-CN T+28D | complete；建议门 | `...\snapshots\synthetic-zh-CN-stage7\tplus28d\v001-as_f1b3da1da7a29bcc9eb05579`；`d282c5c3af4730c93232dbcd0a3f84baad12fc9b8f2ec1a7758160ef10e7e967` | `...\reports\videos\synthetic-zh-CN-stage7\tplus28d-v001.json`；`fced5024f6164cc17c6b4a9d23161b43705cd6984547edf8e1038911a966f745` | `...\reports\channel\tplus28d-synthetic-zh-CN-stage7-v001.json`；`7625bd2e5e9286ad3550c28f24b2c9cf3a8e6cb97037815a8d1a821e0618dc12` | `...\recommendations\rec_7cc56653c3617c1b1e35812c.json`；`9b50369d7c7127e8d22ca380df032a43b1aada032299ee0c0316553c59a22fc5` |
| en-US T+24H | provisional；public-only，owner UNKNOWN | `data\synthetic-fixtures\channels\stage7-en-profile\analytics\snapshots\synthetic-en-US-stage7\tplus24h\v001-as_3e4d5afa0a48788fd43e1369`；`72e52e7d701b27595850beb4f8685071369143a2c88449b6e2465a8b6559fe8c` | `...\reports\videos\synthetic-en-US-stage7\tplus24h-v001.json`；`4b9085c667da4e19d6607985eef61a7ca952756d4d7083a3aea44d51cc30c03e` | `...\reports\channel\tplus24h-synthetic-en-US-stage7-v001.json`；`21d05547fec9dc6fed956f381b4ebdcdb08d4b89a2329f098884fbd1277f3614` | `...\recommendations\rec_5c28e7ed642c8b0dda841b06.json`；`d7758d20292164d18d855b7ead3830c2e707216dc4bc53aeaf28be867bd0cddb` |
| en-US T+7D | revised；迟到 owner fixture | `...\snapshots\synthetic-en-US-stage7\tplus7d\v002-as_7b1fd2c85aadbb669971c1d6`；`eec215105e9b74cc6bbe154d5d11ddb48f8c7843c4c451f052b6e154aa8ee7dc` | `...\reports\videos\synthetic-en-US-stage7\tplus7d-v002.json`；`59273bd998467be9afee5194bfddc93f5f3a00ae99db78deedfc0057ee5a77aa` | `...\reports\channel\tplus7d-synthetic-en-US-stage7-v002.json`；`161951c30947ac2a4137b1d3d6546a0598eab4044d3529521e87b853b0c25c44` | `...\recommendations\rec_28967ce5046d3623b4b2fed3.json`；`d3e1d62ec4b170e560073ec3e52855d3d16678925dc75ba2755073e3bb16ab94` |
| en-US T+28D | complete；建议门 | `...\snapshots\synthetic-en-US-stage7\tplus28d\v001-as_73a8decc8a818a3c93e2da71`；`0cc024b301b402b2ad8da1e8bb204f8402ef7ebba070d97452ade0e05d493ae0` | `...\reports\videos\synthetic-en-US-stage7\tplus28d-v001.json`；`fe3c465cd45e65ab134300c6cd98ab97c0f859d6688eeaae2ec89d6d73a8dcc6` | `...\reports\channel\tplus28d-synthetic-en-US-stage7-v001.json`；`8c8760a4f798e09242dd9e4d2cd9e2701ceb0801311e75b8f01fbc6de9624dd7` | `...\recommendations\rec_5baeed7d350125cdc27db9bd.json`；`a2ca6c58b6f474206016b6d5f35abe474946e9ba6aea7d76c834c2dec5a75b03` |

## 5. 测试与安装证据

在 `E:\小说漫全自动化生产\distribution\novel-manga-production` 执行：

```powershell
uv run python -m unittest -q tests.test_stage7_data_center
uv run python -m unittest discover -s tests -p 'test_*.py' -q
powershell -NoProfile -ExecutionPolicy Bypass -File tools\Test-Stage2.ps1 -PublisherCliPath 'E:\YouTube视频自动上传\youtube-publisher-center\build\bin\youtube-publisher-channel-list.exe'
powershell -NoProfile -ExecutionPolicy Bypass -File tools\Test-Stage3.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File tools\Test-Stage4-Plugin.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File tools\Test-Stage5-Plugin.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File tools\Test-Stage6-Plugin.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File tools\Test-Stage7.ps1
```

结果：

- 阶段 7 专项：15/15 通过。
- 全仓：133/133 通过；带真实发布中心只读 CLI 注入的阶段 2 回归同样 133/133 通过。
- 阶段 3 隔离安装、来源库、去重、重启恢复及边界：通过。
- 阶段 4：12/12；阶段 5：22/22；阶段 6：15/15；阶段 7 三市场链与隔离安装：全部通过。
- 插件验证：9 个 Skills、32 个本地工具；9 个 Skills 均通过 quick validation。
- 契约验证：10 个示例通过；Metric Catalog schema/catalog 注册通过；release manifest 验证通过。
- 当前发布中心用户数据库在只读回归前后 hash 不变：`publisher-center.db` 为 `97347919099701ce40b67981504bf18f0ddbb0c986de47e7afa2dc610e83f4cf`，`-shm` 为 `fd4c9fda9cd3f9ae7c962b0ddf37232294d55580e1aa165aa06129b8549389eb`，`-wal` 为空文件 hash `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855`。未将真实频道字段值写入报告或 fixture。
- 草案 release manifest：`release-v0.7.0-dev.1.json`，`releaseStatus=draft`，canonical content hash `a61c4ff9976923ad3a3c08a1bc6fa30778d59dc6a6573d4bd1760197e893e3ae`；未创建 Release。

失败测试覆盖：无 receipt 正式注册、fake/synthetic ID 写正式库、坏 hash、跨频道、公开数据冒充 owner、缺失填 0、CTR/留存伪造、缺 data cutoff、重复原始报告、跨频道基线、留存比例大于 1 被截断、无证据建议、自动长期写回、默认启用收入 scope、OAuth/token 泄漏和真实库迁移越权。

## 6. 退出矩阵

| 退出项 | 结果 | 证据摘要 |
|---|---|---|
| Metric Catalog v1 | GO | 版本化 catalog/schema、27 指标、14 维度、官方字段／权限／单位／时区／延迟／完整性／内容形态齐全 |
| 六级事实等级 | GO | 全链校验；推断绑定事实、替代解释、置信度、验证动作；UNKNOWN 不填 0 |
| 正式 video registration | GO（门控） | 无真实 receipt 返回 `WAITING_FOR_PUBLICATION_RECEIPT`；fake ID、坏 hash、跨频道和缺五类上游绑定均阻断 |
| Analytics 授权 | WAITING | 独立于上传授权；默认 `AUTH_REQUIRED`、`available=false`；未发起 OAuth |
| Snapshot／raw／normalized | GO | 原始只追加、快照版本化、source lock、幂等复用、迟到修订通过 |
| 频道隔离／迁移 | GO（门控） | 三市场隔离；现有库迁移仅返回 `MIGRATION_APPROVAL_REQUIRED`，未执行 |
| T+24／T+7／T+28 调度 | GO | 检查点、cutoff、时区、完整性、迟到修订、断点与重启恢复通过 |
| 数据适配 | GO（本地接口） | public recorded、synthetic owner、system hash binding 通过；真实 owner 为 `AUTH_REQUIRED` |
| 两类报告 JSON+Markdown | GO | provisional/complete/revised/superseded、未知项、低样本与勿过度解读齐全 |
| Timeline retention 映射 | GO | ratio→时间→行／分镜／故事节点；大于 1 不截断；只产复查证据 |
| 可比基线 | GO | 同频道优先，发布年龄／形态／语言／时长／题材／时段／来源降级；无通用 CTR 阈值 |
| Recommendation Card v1 | GO（待决定） | 默认 `AWAITING_LEARNING_DECISION`；长期写回严格阻断 |
| 三市场完整离线链 | GO | ja-JP、zh-CN、en-US 覆盖 public-only T+24、迟到修订 T+7、T+28 建议 |
| 非技术 Data Center Skill／工具协议 | GO | 自然语言路由、清楚下一步、源树与隔离安装健康检查通过 |
| 阶段 2–6 回归／阶段 7／安装 | GO | 133 全仓测试、阶段脚本及隔离安装通过 |
| 真实 Studio 数据或长期学习 | NO-GO / 未执行 | 等待真实 receipt/video ID、Analytics 授权和单独长期学习批准 |

## 7. 未触发的审批门

- Google/YouTube OAuth 与真实 Analytics 授权：未触发。
- 真实视频上传与 Publication Receipt：未触发。
- 用户数据或 `channel.db` 迁移：未触发。
- `channel_default`／`must_avoid` 长期规则写回：未触发。
- GitHub push、tag、Release：未触发。

因此，阶段 7 对“本地可安装数据中心闭环”判定 **GO**；对“真实频道 Studio 数据投入运行”判定 **NO-GO / AUTH_REQUIRED + WAITING_FOR_PUBLICATION_RECEIPT**，不得将本报告中的 synthetic/recorded fixture 解释为真实频道表现。
