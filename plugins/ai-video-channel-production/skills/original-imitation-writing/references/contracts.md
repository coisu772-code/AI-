# 原创仿写工具与字段契约

## 工具顺序

1. `original_imitation_capabilities`
2. `original_imitation_prepare`
3. 对每个直接小说／文本来源循环 `original_imitation_read_source`，再调用 `original_imitation_source_checkpoint`
4. `original_imitation_direction_checkpoint`，严格按 1～8 递增
5. `original_imitation_directions_finalize`
6. 展示全部 8 个方向与 TOP3，等待用户选择
7. `original_imitation_confirm`
8. `original_imitation_integrity_check`

`original_imitation_get` 可随时只读查询，不推进状态。

## 来源贡献

每个方向的 `sourceContributions[]` 与 plan 中的来源一一对应：

- `sourceKey`
- `role`
- `weight`
- `transferableFunctionIds[]`
- `newImplementation`
- 可选 `segmentShare` 只能是 `false`、`0` 或空

视频方法 ID 来自冻结 `analysis-package-v1.analysisBuckets.transferableMethods`；小说方法 ID 来自 `imitation-source-analysis-v1.analysisBuckets.transferableMethods`。

## 功能同构表

`functionalIsomorphism[]` 每项：

- `nodeId`
- `sourceKey`
- `sourceFunctionId`
- `sourceFunction`
- `sourceImplementationSummary`
- `newImplementation`
- `newCausality`
- `emotionPosition`
- `lengthShare`
- `sameEventSequence=false`

表覆盖全部来源，`lengthShare` 合计 100。这里的篇幅占比描述新故事内部功能节点，不是来源片段占比。

## 可信度审查

`credibilityAudit[]` 恰好包含 `q1`～`q10`；每项有 `passed`、`answer`、`evidence`。另需：

- `scaleControl`：`issueScale`、`identityCapacity`、`resources`、`authority`、`rationalActorBarrier`、`passed`。
- `oppositionLogic`：`ownGoal`、`interest`、`knownInformation`、`reasoningBasis`、`constraints`、`understandableWrongDecision`、`passed`。
- `protagonistCapability`：`source`、`scope`、`limit`、`cost`、`growth`、`passed`。
- `resultProcess[]`：依次为 `verify`、`stabilize`、`expand`、`new-problem`、`adjust`、`re-expand`，每项有 `action` 和 `stateChange`。

## 28 组差异检查

`pairwiseDistinctness[]` 恰好 28 项，每项：

- `directionA`、`directionB`
- `differenceCategories[]`：至少三个，且至少一个来自主角／视角、目标、规则／约束、冲突来源、故事引擎／成长
- `cosmeticOnly=false`
- `substantiallyDifferent=true`
- `explanation`

允许的差异类为：`protagonist-pov`、`goal`、`rule-constraint`、`conflict-source`、`relationships`、`fusion-method`、`story-engine-growth`、`cross-genre-expression`。

## 下游候选合规

`sourceMode=imitation` 的唯一 Topic 候选除标准字段外还必须包含：

```json
{
  "styleContractCompliance": {
    "selectedDirectionId": "direction-id",
    "unifiedCausalEngineApplied": true,
    "functionalIsomorphismApplied": true,
    "sourceRolesAndWeightsApplied": true,
    "copyBoundaryPassed": true
  }
}
```

选题与文稿中心只消费冻结 `writingStyleContract` 的哈希引用和对应下游视图，不读取未确认方向作为创作指令。
