# Codex 视觉方案合同

## 何时生成

只有用户已经明确进入制作并在制作设置卡中开启“图片提示词”或“视频提示词”时，Codex 才生成视觉方案。用户只选择开关与范围，不需要自己编写提示词。实际镜头视频仍是独立开关；只开启视频提示词不能开启视频生成。

正式配音稿、角色、图片风格和制作设置冻结后，在调用 `production_package_assemble` 前一次性生成 `productionConfig.codexVisualPlan`。不增加第二张强制确认卡；组装后生成可查看的 `codex-visual-plan` 文档。

## 角色设计

先做群像对照，再逐个设计。每个需要持续视觉一致性的角色必须包含：

- `designIntentZh`：身份、性格和剧情功能如何转化为视觉设计；
- `identityAnchorPromptZh`：脸型、眼型与瞳色、发型发色、身体比例、服装轮廓配色、固定配饰；
- `referenceSheetPromptZh`：单画布、单角色、单次出现、单一正面略偏四分之三视角、单套主服装的身份参考图提示词。它不是传统多视角角色设定页；禁止正面／侧面／背面并列、三视图或任意多视角／多角度、转面设定、拼图／分栏／宫格、重复人物、两套服装、换装或服装变体，也禁止剧情动作和背景文字；
- `storyboardIdentityPromptZh`：分镜使用的精简身份锚点；
- `fixedFeatures`：3–12 个必须跨镜头保持的身份特征。

主要角色至少在脸部轮廓／眼型、发型外轮廓、服装大轮廓、固定配色、标志配饰、身体比例和姿态气质中的四项与群像形成差异。标志设计必须从人物身份、经历或性格生长，不堆随机装饰，不把“漂亮、帅气、精致”当设计。

角色参考图固定为 `identity_only`。只锁定脸型、眼型与瞳色、发型发色、身体比例、一套主服装的轮廓配色和固定配饰；不锁定表情、视线、头部角度、身体姿势、手势、剧情构图、光线或背景。`identityAnchorPromptZh` 可以记录剧情中存在的其他服装供连续性规划，但 `referenceSheetPromptZh` 只能选择其中一套主服装，绝不把多套服装同时画进角色参考图。

## 先规划故事画面，再写逐镜提示词

先从正式配音稿建立 `storyVisualPlan`，不得直接逐句套提示词：

- 第一镜绑定最有吸引力且有原文依据的开篇钩子；
- 明确人物关系、核心矛盾、重要铺垫、情绪爆点、反转和阶段回报分别由哪些正式稿行、哪些画面承担；
- 按剧情复杂度 1–5 自适应增加页数。复杂因果、地点／动作切换、关键证据、反转和情绪爆点优先一行一镜；简单过渡才可两行合一。正式稿行粒度不足时先在不改变口播文字的前提下做语义切行，再组装生产包，绝不通过重复同一行制造更多画面；
- 没读过原作的人应能仅靠人物距离、动作、视线、关键物、环境变化和前后因果看懂每一页；
- 每页都要有清晰视觉焦点、前中后景层次和适合该剧情功能的海报级构图，但不能把每页都伪装成高潮。

景别工具包括大远景、全景、中景、近景和极近特写；角度与视向包括俯视、仰视、倾斜镜头、背影和过肩。按剧情功能选择，不机械轮换。不得连续三镜使用完全相同的景别／角度／视向，也不得连续三镜只做人物半身对话。

## 连续性圣经

`continuityBible` 先冻结地点、服装和关键道具 ID 及其固定特征。每个分镜必须绑定地点；每个出镜角色必须绑定属于自己的服装；出现关键道具时必须绑定道具 ID。改变服装、场景或道具状态时写明剧情依据，不能让提示词自由漂移。角色身份参考仍只锁身份，不锁表演。

## 分镜表演

`scenePlans` 必须按正式稿顺序完整覆盖每个 `lineId` 一次且仅一次，可以把连续且属于同一可视动作／情绪节拍的行组合成一个镜头，但不能跨集。生成前可按文本估算约 3.5–7 秒来规划；TTS 完成后，工坊必须以本项目“音频合并最大时长”的真实设置为硬上限重新检查，默认 4.5 秒。一个原始 `lineId` 被 TTS 拆成 `-sentence-N` 子行时，全部子行继承原视觉方案并按真实时长继续拆镜，不得漏行，也不得因视觉方案锁定而绕过时长上限。单条音频自身超限时单独成镜；动作、地点或主要情绪切换时同样必须拆开。每镜先写表演合同，再写图片提示词：

- `internalEmotion`：人物内在情绪；
- `visibleEmotion`：观众实际看见的外显情绪；
- `intensity`：1–5；
- `gaze`、`eyes`、`brows`、`mouth`；
- `headPose`、`bodyPose`、`handGesture`；
- `interactionTarget`；
- `changeFromPrevious`：相对上一镜发生了什么可见变化。

有角色的图片提示词必须把与当前镜头相关的眉眼、嘴形、视线、身体重心和手势写成可见动作。除非文本明确是冷静、麻木、伪装或静止，不得连续复用中性表情、正视前方和站立姿势。确需克制表演时，用眼神、肌肉紧张度或小动作表达潜台词。

图片提示词描述单个静态关键瞬间；视频提示词只在用户开启时生成，描述从当前首帧出发的动作、表情变化、镜头运动、环境动态、节奏和结束状态。情绪强度决定动作幅度，不能把所有镜头统一写成“轻微动作”。

## 情绪爆点硬规则

震惊、愤怒、恐惧、心碎、背叛、觉醒、复仇、打脸、真相揭露、生离死别、甜蜜确认、最终和解属于关键情绪。出现时必须独占一镜，并使用近景／极近特写，或明确的破格构图。

每个情绪爆点至少绑定两个可见信号，而且至少一个是人物身体信号：眼神变化、瞳孔收缩、嘴角细微变化、眼泪、握紧的手、发抖的指尖、后退动作、遮挡／保护动作、人物间距离、明暗与色彩变化。明暗与色彩只能辅助，不能单独承担情绪。相邻分镜不得连续重复同一情绪类别；重要情绪不能只写在旁白或画面文字里。

## 分段生成与长度预算

每镜先分别填写主体动作、视觉叙事、人物表演、镜头构图、连续性环境、光色和关键物，再合并成最终提示词。最终图片提示词最多 600 字符，视频提示词最多 500 字符。全局画风由工坊统一加入，完整角色设定由身份绑定加入，逐镜提示词不得重复粘贴这些长内容。

## 机器合同

```json
{
  "schemaVersion": "1.1",
  "author": "codex",
  "characterDesigns": [
    {
      "characterId": "角色ID",
      "designIntentZh": "设计意图",
      "identityAnchorPromptZh": "身份锚点",
      "referenceSheetPromptZh": "角色设定图提示词",
      "storyboardIdentityPromptZh": "分镜身份短锚点",
      "fixedFeatures": ["固定特征1", "固定特征2", "固定特征3"]
    }
  ],
  "continuityBible": {
    "locations": [{"locationId": "LOC-01", "nameZh": "地点", "fixedFeatures": ["固定空间特征"]}],
    "costumes": [{"costumeId": "CST-01", "characterId": "角色ID", "nameZh": "服装", "fixedFeatures": ["固定轮廓与配色"]}],
    "props": [{"propId": "PROP-01", "nameZh": "关键物", "fixedFeatures": ["固定外观"]}]
  },
  "storyVisualPlan": {
    "openingHookSceneId": "CVP-E01-S001",
    "relationshipConflictSceneIds": ["CVP-E01-S002"],
    "complexityLevel": 4,
    "pageCountMode": "complexity_adaptive",
    "plannedPageCount": 24,
    "pageCountRationaleZh": "按因果、反转和情绪节点拆分",
    "storyBeats": [{"beatId": "BEAT-01", "type": "hook", "summaryZh": "钩子", "sourceLineIds": ["E01-L001"], "sceneIds": ["CVP-E01-S001"]}],
    "promptCompiler": {"mode": "structured_budgeted_merge", "imagePromptMaxChars": 600, "videoPromptMaxChars": 500, "globalStyleRepeatedPerScene": false, "identityFullProfileRepeatedPerScene": false}
  },
  "scenePlans": [
    {
      "sceneId": "CVP-E01-S001",
      "episodeNumber": 1,
      "scriptLineIds": ["E01-L001"],
      "visibleCharacterIds": ["角色ID"],
      "primaryCharacterId": "角色ID",
      "complexityScore": 4,
      "narrativeFunction": "hook",
      "storyBeatIds": ["BEAT-01"],
      "shot": {"scale": "close_up", "angle": "dutch_angle", "view": "three_quarter", "dialogueStaging": "reaction", "breakingComposition": true, "breakingCompositionZh": "斜切画框", "focalPointZh": "骤变的眼神", "depthCompositionZh": "前景手、主体脸、后景威胁", "posterCompositionZh": "单一强焦点与压迫留白"},
      "visualReadability": {"storyInformationZh": "危险突然发生", "relationshipCueZh": "主体受到对方压迫", "conflictOrCauseEffectCueZh": "威胁导致后退", "withoutDialogueReadable": true},
      "continuity": {"locationId": "LOC-01", "costumeIdsByCharacter": {"角色ID": "CST-01"}, "propIds": ["PROP-01"], "changeJustificationZh": "延续上一场状态"},
      "emotionalBeat": {"category": "shock", "visualSignals": ["pupil_constriction", "step_back", "light_color_shift"]},
      "performance": {
        "internalEmotion": "内在情绪",
        "visibleEmotion": "外显情绪",
        "intensity": 3,
        "gaze": "注视对象与方向",
        "eyes": "眼睛状态",
        "brows": "眉形变化",
        "mouth": "嘴形",
        "headPose": "头部角度",
        "bodyPose": "身体重心与姿态",
        "handGesture": "手势",
        "interactionTarget": "互动对象",
        "changeFromPrevious": "相对上一镜的可见变化"
      },
      "promptComponents": {"subjectActionZh": "主体动作", "visualStoryZh": "可见因果", "performanceZh": "微表情和肢体", "cameraCompositionZh": "景别角度构图", "continuityEnvironmentZh": "地点服装道具", "lightingColorZh": "光色辅助", "keyObjectZh": "关键物焦点"},
      "imagePromptZh": "图片提示词；未开启图片提示词时为空",
      "videoPromptZh": "视频提示词；未开启视频提示词时为空"
    }
  ]
}
```

示例只展示结构；正式 `storyBeats` 必须至少覆盖钩子、人物关系和核心矛盾，并与全部分镜绑定一致。风格 ID、风格哈希、参考图用途、无文字策略、完整性锁和内容哈希由组装工具自动归一化；Codex 不要求用户填写。组装器与工坊在发送生图请求前自动校验绑定关系，失败就暂停，不把内部校验变成用户操作步骤。

## 禁止

- 不让用户自己编写整套图片或视频提示词；
- 不把角色设定图的中性表情复制到剧情分镜；
- 不用文字替代重要情绪，不连续复用同一种情绪爆点；
- 不为增加页数而重复口播行，也不凭空发明原稿没有的铺垫、反转或爽点；
- 不让工坊旧提示词生成器覆盖 `imagePromptSource=codex` 或 `videoPromptSource=codex`；
- 不因开启视频提示词而开启实际视频生成；
- 不执行生成后的画风、外貌、服装或文字污染视觉识别检查；本合同只做生成前的确定性绑定校验。
