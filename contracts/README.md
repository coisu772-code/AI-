# 跨中心数据契约 v1

本目录定义六大中心之间可冻结、可校验、可追溯的正式交付边界。所有 Schema 使用 JSON Schema Draft 2020-12，契约版本从 `1.0.0` 开始。

## 契约链

```text
Channel Profile + Production Profile + Source Package
→ Topic Package
→ Manuscript Package
→ Publishing Asset Package
→ Production Result Package
→ Publish Intent
→ Publication Receipt
→ Analytics Snapshot
```

## `canonical-json-v1`

根级 `contentHash` 按以下规则计算：

1. 复制完整 JSON 对象并只删除根级 `contentHash`。
2. 对所有对象键按 Unicode 码点升序排序；数组顺序保持不变。
3. 按 JSON 标准序列化，使用 UTF-8、无 BOM、无额外空白，布尔值和 `null` 使用 JSON 小写字面量。
4. 对所得字节计算 SHA-256，写入 64 位小写十六进制 `contentHash`。

`upstream[].targetHash` 必须等于所引用上游契约当前冻结版本的 `contentHash`。正式包冻结后不得原地覆盖；任何内容修改都生成新的语义化版本，并使受影响下游引用失效。

## 路径与安全

- 契约中的文件路径只允许包内相对路径。
- Schema 和示例不得包含真实频道、Token、密钥、Cookie、活动数据库或用户媒体。
- 示例域名使用 `example.invalid`，频道与视频 ID 均为合成测试值。

## 校验

运行 `tools/validate_contracts.py` 会检查 Schema、必填字段、ID 一致性、内容哈希和所有示例间的上游引用。`tests/test_contracts.py` 同时证明哈希篡改会被拒绝。
