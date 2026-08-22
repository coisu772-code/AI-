# Codex 漫画视觉方案合同

## 目标与生成时机

只有用户已经明确进入制作并在制作设置卡中开启“图片提示词”或“视频提示词”时，Codex 才生成视觉方案。用户只选择开关与范围，不需要自己编写提示词。实际镜头视频仍是独立开关；只开启视频提示词不能开启视频生成。

正式配音稿、角色、图片风格和制作设置冻结后，在调用 `production_package_assemble` 前一次性生成 `productionConfig.codexVisualPlan`。当前合同使用 schema 1.3，视觉导演固定为 `manga_impact`：必须先读取全剧、再划分连续场景段、最后规划单镜，禁止只读取当前一句配音文本后独立配图。每镜是单幅剧情漫画，以一个视觉焦点和一个主动作表达一个决定性静态瞬间；人物表演、空间连续性、光色节奏与背景复杂度随剧情冲击等级变化。同一视觉时刻可以绑定多条旁白、对白和纯音效；普通语音的实际时长只控制播放，不得触发拆图。纯音效必须与相邻人声共用分镜，禁止独立成画。组装后生成可查看的 `codex-visual-plan` 文档，不增加第二张强制确认卡。

## 画风与视觉导演分离

- `imageStyle` 控制线稿、上色、材质和地区画风，由用户在制作设置卡中确认；
- `visualDirection` 控制单幅漫画、单焦点、夸张表演、动作线、漫画冲击手法和背景减法；
- 全局画风由工坊统一加入，逐镜提示词不得重复粘贴完整画风；
- 完整角色设定由身份绑定加入，逐镜提示词只写当前镜头真正需要的身份连续性和表演。

`visualDirection` 必须固定为：

```json
{
  "mode": "manga_impact",
  "panelMode": "single_panel",
  "singleFocalPoint": true,
  "expressionMode": "exaggerated_story_driven",
  "backgroundSimplification": "impact_adaptive",
  "compositionMode": "story_driven",
  "mangaDeviceLimit": 3
}
```

## 角色设计

先做群像对照，再逐个设计。每个需要持续视觉一致性的角色必须包含：

- `designIntentZh`：身份、性格和剧情功能如何转化为视觉设计；
- `identityAnchorPromptZh`：脸型、眼型与瞳色、发型发色、身体比例、服装轮廓配色、固定配饰；
- `referenceSheetPromptZh`：单画布、单角色、单次出现、单一正面略偏四分之三视角、单套主服装的身份参考图提示词；禁止正面／侧面／背面并列、三视图、多视角、拼图、分栏、宫格、重复人物、换装、剧情动作和背景文字；
- `storyboardIdentityPromptZh`：分镜使用的精简身份锚点；
- `fixedFeatures`：3–12 个必须跨镜头保持的身份特征。

主要角色至少在脸部轮廓／眼型、发型外轮廓、服装大轮廓、固定配色、标志配饰、身体比例和姿态气质中的四项与群像形成差异。标志设计必须从人物身份、经历或性格生长，不堆随机装饰。

角色参考图固定为 `identity_only`。只锁脸型、眼型与瞳色、发型发色、身体比例、一套主服装的轮廓配色和固定配饰；不锁表情、视线、头部角度、身体姿势、手势、剧情构图、光线或背景。

## 先规划故事画面

先从正式配音稿建立 `storyVisualPlan`，不得直接逐句套提示词：

- 先读取项目全部集数，建立 `seriesVisualPlan`，冻结角色成长、跨集时间线、伏笔回收、地点、服装和关键道具状态；不得只看当前集；
- 第一镜绑定最有吸引力且有原文依据的开篇钩子；
- 明确人物关系、核心矛盾、重要铺垫、情绪爆点、反转和阶段回报分别由哪些正式稿行、哪些画面承担；
- 先按动作、空间、视线、情绪与因果是否处于同一视觉时刻决定换镜；不得按配音行数、句子长度、TTS 子句数量或音频秒数决定换镜；
- 按剧情复杂度 1–5 自适应增加页数；复杂因果、地点／动作切换、关键证据、反转和情绪爆点优先一行一镜，简单过渡才可两行合一；
- 没读过原作的人应能仅靠人物距离、动作、视线、关键物、环境变化和前后因果看懂画面；
- 每页只有一个主要视觉焦点，不把人物、道具、环境和光效全部提升为同等重点；
- 画面冲击来自蓄力与爆发对比，不得连续三镜都使用 4–5 级高冲击构图。

景别、角度和视向按剧情功能选择，不机械轮换。不得连续三镜使用完全相同的景别／角度／视向，也不得连续三镜只做人物半身对话。

## 连续场景段与状态链

先把每集划分为 `visualSequences`。每个连续场景段必须冻结地点、时间与光线、综合色调与反差、人物左右位置和空间轴线，并明确镜头梯度与冲击曲线。相邻场景段改变地点时，除本集首个场景段外，下一段必须以 `establishing` 或 `transition` 镜头建立转场。

每镜必须填写 `sequenceId`、`shotRole` 与 `continuityState`。`shotRole` 只允许：`establishing`、`action`、`reaction`、`emotion_closeup`、`evidence_insert`、`consequence`、`transition`、`climax`、`aftermath`。

`continuityState` 必须同时记录：

- `entryStateId`／`entryStateZh`：进入本镜时的位置、姿势、视线、道具和环境状态；
- `exitStateId`／`exitStateZh`：本镜唯一动作完成后留下的状态；
- `characterBlockingZh`：人物左右站位、距离、面朝方向和力量关系；
- `screenDirectionZh`：画面运动方向与轴线；
- `eyelineZh`：视线对象和视线高度；
- `propStateZh`：关键道具的持有人、位置和状态；
- `lightingStateZh`：本镜继承的光线方向、冷暖和明暗关系；
- `carryOverFromSceneId`：上一镜 ID；每集首镜为空。

同一连续场景段内，下一镜 `entryStateId` 必须严格等于上一镜 `exitStateId`。场景段首尾状态必须分别等于第一镜进入状态和最后一镜离开状态。没有剧情依据时，人物不得突然换位、换向、换房间、换服装或改变道具状态。

## 连续性圣经

`continuityBible` 先冻结地点、服装和关键道具 ID 及其固定特征。每镜必须绑定地点；每个出镜角色必须绑定属于自己的服装；出现关键道具时必须绑定道具 ID。改变服装、场景或道具状态时写明剧情依据。连续性信息只保留当前画面必需项，不得为了完整而把全部场景细节塞进提示词。

## 漫画冲击等级与背景减法

每镜必须填写 `impactLevel` 与 `expressionExaggeration`，范围均为 1–5：

- 1：平静过渡，自然表演，允许保留完整环境；
- 2：轻微变化，人物动作开始承担叙事；
- 3：矛盾推进，表情、重心和镜头角度明显加强；
- 4：关键转折，近景／特写或破格构图，背景必须简化；
- 5：高潮爆点，强透视、夸张形变和抽象冲击背景。

4–5 级镜头使用近景／极近特写或破格构图，至少采用一种、最多三种漫画冲击手法，背景模式只能为 `simplified` 或 `abstract_impact`。同一冲击瞬间允许承载多条正式稿行，但仍只能表达一个视觉焦点和一个主动作。有人物出镜时，表情夸张度不得低于 4。无人镜头的表情夸张度固定为 1。

允许的漫画手法为：`speed_lines`、`impact_burst`、`extreme_foreshortening`、`dutch_angle`、`frame_breaking`、`heavy_shadow`、`high_contrast_silhouette`、`abstract_background`、`foreground_occlusion`。手法必须服务剧情，不能全部堆在一镜。

## 单幅漫画导演与表演

每镜 `mangaComposition` 必须说明：

- `coreMomentZh`：这张图唯一表达的剧情瞬间；
- `singleVisualFocusZh`：唯一视觉焦点；
- `primaryActionZh`：唯一主动作；
- `interactionZh`：人物距离、视线和力量关系；
- `shotDesignZh`：景别、角度、透视、留白与破格方式；
- `backgroundMode`：`detailed_context`、`selective_detail`、`simplified` 或 `abstract_impact`；
- `backgroundTreatmentZh`：背景保留、弱化或抽象化方式；
- `continuityEssentialsZh`：本镜必须保留的地点、服装和道具；
- `clutterControlZh`：次要人物、装饰和无关物体如何降级或排除；
- `mangaDevices`：0–3 个漫画冲击手法。

有角色出镜时，`primaryCharacterId` 必须指向本镜唯一主要角色。其他角色可以存在，但只能作为互动对象、反应者、局部、轮廓或背景压力，不得抢走焦点。

`performance` 继续记录内在／外显情绪、强度、视线、眼睛、眉形、嘴形、头部角度、身体姿态、手势、互动对象及相对上一镜变化。有角色出镜时还必须提供：

- `facialActing`：眼形、瞳孔、眉形、嘴部／下颌、面部张力和漫画夸张手法；
- `bodyActing`：身体动作线、重心、肩背、手部张力和头发／衣摆／配饰等次级运动。

不能只写“震惊、愤怒、伤心”。必须把情绪写成可见形变和动作，例如瞳孔收缩、眼睑张开、眉毛高低差、下颌僵住、肩膀收紧、脊柱弧线、手指失力或握拳。克制表演也要用眼神、肌肉紧张和小动作表达潜台词。

## 情绪爆点硬规则

震惊、愤怒、恐惧、心碎、背叛、觉醒、复仇、打脸、真相揭露、生离死别、甜蜜确认和最终和解属于关键情绪。出现时必须独占一镜，并使用近景／极近特写或明确的破格构图。

每个情绪爆点至少绑定两个可见信号，而且至少一个是人物身体信号。明暗与色彩只能辅助，不能单独承担情绪。相邻分镜不得连续重复同一情绪类别；重要情绪不能只写在旁白或画面文字里。有人物出镜时，情绪爆点的表情夸张度不得低于 3。

## 最终图片提示词编译

先分别填写结构字段，再按以下顺序压缩合并 `imagePromptZh`：

```text
单幅漫画分镜声明
→ 唯一剧情瞬间
→ 唯一视觉焦点
→ 主角核心动作
→ 漫画化面部表演
→ 身体动作线、重心、手势和次级运动
→ 人物互动与力量关系
→ 景别、角度、透视和构图
→ 最多三种漫画冲击手法
→ 必要连续性信息
→ 背景简化方式
→ 杂乱控制和无文字限制
```

图片提示词建议 280–450 字符，硬上限 600 字符；视频提示词硬上限 500 字符。最终图片提示词描述一个静态关键瞬间，不能写成事件列表或时间序列。全局画风、完整角色长设定不在逐镜提示词中重复。

提示词出现“随后、接着、然后、之后又、紧接着”或“先……再……”等时间序列表达时判定不合格，必须重新拆镜或改写为一个静止瞬间。不得使用“身体重心稳定并与动作一致”“视线落在互动对象或关键物件”等可跨项目复用的表演套话。

## 机器合同

```json
{
  "schemaVersion": "1.3",
  "author": "codex",
  "visualDirection": {
    "mode": "manga_impact",
    "panelMode": "single_panel",
    "singleFocalPoint": true,
    "expressionMode": "exaggerated_story_driven",
    "backgroundSimplification": "impact_adaptive",
    "compositionMode": "story_driven",
    "mangaDeviceLimit": 3
  },
  "seriesVisualPlan": {
    "planningMode": "full_series_then_sequence_then_shot",
    "allEpisodesRead": true,
    "episodeNumbers": [1, 2],
    "timelineSummaryZh": "全剧时间线、伏笔与回收关系",
    "crossEpisodeContinuityZh": "跨集人物、地点、服装、道具和情绪状态承接"
  },
  "characterDesigns": [
    {
      "characterId": "角色ID",
      "designIntentZh": "设计意图",
      "identityAnchorPromptZh": "身份锚点",
      "referenceSheetPromptZh": "单画布单角色单视角单套服装提示词",
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
    "visualSequences": [{
      "sequenceId": "SEQ-E01-01",
      "episodeNumber": 1,
      "sceneIds": ["CVP-E01-S001"],
      "locationId": "LOC-01",
      "timeLightingZh": "同一时段与固定主光方向",
      "paletteContrastZh": "按剧情确定主色、辅助色和明暗反差",
      "spatialAxisZh": "冻结人物左右位置、视线轴和运动方向",
      "openingStateId": "STATE-E01-001-IN",
      "closingStateId": "STATE-E01-001-OUT",
      "continuityFromPreviousZh": "本集开场状态来自全剧时间线",
      "shotLadder": ["climax"],
      "impactArc": [5]
    }],
    "promptCompiler": {
      "mode": "manga_structured_budgeted_merge",
      "imagePromptMaxChars": 600,
      "imagePromptSoftMinChars": 280,
      "imagePromptSoftMaxChars": 450,
      "videoPromptMaxChars": 500,
      "globalStyleRepeatedPerScene": false,
      "identityFullProfileRepeatedPerScene": false,
      "singlePanelDirectiveRequired": true,
      "singleFocalPointRequired": true,
      "clutterControlRequired": true,
      "fullSeriesContextRequired": true,
      "sequencePlanRequired": true,
      "continuityStateRequired": true,
      "temporalSequenceForbidden": true,
      "shotRoleRequired": true,
      "failureRepairScope": "failed_scene_only"
    }
  },
  "scenePlans": [
    {
      "sceneId": "CVP-E01-S001",
      "episodeNumber": 1,
      "sequenceId": "SEQ-E01-01",
      "shotRole": "climax",
      "scriptLineIds": ["E01-L001"],
      "visibleCharacterIds": ["角色ID"],
      "primaryCharacterId": "角色ID",
      "complexityScore": 4,
      "impactLevel": 5,
      "expressionExaggeration": 5,
      "narrativeFunction": "hook",
      "storyBeatIds": ["BEAT-01"],
      "shot": {"scale": "close_up", "angle": "dutch_angle", "view": "three_quarter", "dialogueStaging": "reaction", "breakingComposition": true, "breakingCompositionZh": "斜切画框", "focalPointZh": "骤变的眼神", "depthCompositionZh": "前景手、主体脸、后景威胁", "posterCompositionZh": "单一强焦点与压迫留白"},
      "visualReadability": {"storyInformationZh": "危险突然发生", "relationshipCueZh": "主体受到对方压迫", "conflictOrCauseEffectCueZh": "威胁导致后退", "withoutDialogueReadable": true},
      "continuity": {"locationId": "LOC-01", "costumeIdsByCharacter": {"角色ID": "CST-01"}, "propIds": ["PROP-01"], "changeJustificationZh": "延续上一场状态"},
      "continuityState": {"entryStateId": "STATE-E01-001-IN", "entryStateZh": "角色位于走廊右侧，面向逼近者", "exitStateId": "STATE-E01-001-OUT", "exitStateZh": "角色后撤并抬手防御", "characterBlockingZh": "主体在右、威胁在左前景", "screenDirectionZh": "威胁由左向右逼近", "eyelineZh": "主体看向左前景威胁", "propStateZh": "关键物仍在威胁者手中", "lightingStateZh": "走廊冷光从右后方照入", "carryOverFromSceneId": ""},
      "emotionalBeat": {"category": "shock", "visualSignals": ["pupil_constriction", "step_back", "light_color_shift"]},
      "performance": {"internalEmotion": "意识到危险", "visibleEmotion": "震惊并本能防御", "intensity": 5, "gaze": "看向逼近者", "eyes": "眼睑骤然张开", "brows": "眉头内侧抬高", "mouth": "嘴唇张开", "headPose": "头部后仰", "bodyPose": "身体重心后撤", "handGesture": "抬手遮挡", "interactionTarget": "逼近者", "changeFromPrevious": "从放松骤变为防御"},
      "mangaComposition": {"coreMomentZh": "危险击中角色的瞬间", "singleVisualFocusZh": "骤缩的瞳孔", "primaryActionZh": "角色猛然后撤并抬手防御", "interactionZh": "前景角色被后景威胁压迫", "shotDesignZh": "极近特写、倾斜画框和前景遮挡", "backgroundMode": "abstract_impact", "backgroundTreatmentZh": "背景压缩为逼近轮廓与放射冲击线", "continuityEssentialsZh": "保留白色外套、银色项链和走廊冷光", "clutterControlZh": "只保留主体、威胁轮廓和一个关键道具", "mangaDevices": ["impact_burst", "heavy_shadow"]},
      "facialActing": {"eyeShapeZh": "双眼夸张睁大", "pupilZh": "瞳孔骤缩成针点", "browZh": "眉毛内侧猛烈抬起", "mouthJawZh": "嘴巴张开、下颌僵住", "faceTensionZh": "眼下与嘴角肌肉拉紧", "exaggerationTechniqueZh": "用眼口比例变化放大惊惧"},
      "bodyActing": {"lineOfActionZh": "身体形成向后弯曲的反向弧线", "centerOfGravityZh": "重心迅速移向后脚", "shoulderSpineZh": "肩膀收紧、脊柱后撤", "handTensionZh": "手指张开形成防御", "secondaryMotionZh": "头发和衣角沿后撤方向甩动"},
      "promptComponents": {"subjectActionZh": "主体动作", "visualStoryZh": "可见因果", "performanceZh": "漫画化表演", "cameraCompositionZh": "景别角度构图", "continuityEnvironmentZh": "必要连续性", "lightingColorZh": "光色辅助", "keyObjectZh": "关键物焦点"},
      "imagePromptZh": "单幅漫画静态关键瞬间提示词",
      "videoPromptZh": "用户未开启时为空"
    }
  ]
}
```

风格 ID、风格哈希、参考图用途、无文字策略、锁和内容哈希由组装工具自动归一化；Codex 不要求用户填写。组装器与工坊在发送生图请求前自动校验绑定关系，失败就暂停。

图片生成失败或用户要求重生成时，只能诊断并修改失败镜头的提示词，保留该镜的 `sequenceId`、`shotRole`、角色身份、地点、服装、道具、进入／离开状态和相邻镜头承接；不得批量覆盖其他已确认提示词。仍由工坊调用已配置图片模型生成，不得改用 Codex 直接生图。新图片生成并校验成功后必须原位置原子替换旧主图与切图引用，禁止新旧图片同时显示在不同位置。

## 禁止

- 不让用户自己编写整套图片或视频提示词；
- 不把角色参考图的中性表情复制到剧情分镜；
- 不用文字替代重要情绪，不连续复用同一种情绪爆点；
- 不把多人、道具、背景和光效全部提升为主要焦点；
- 不用复杂背景补偿薄弱表演；
- 不为增加页数而重复口播行，也不凭空发明原稿没有的铺垫、反转或爽点；
- 不让工坊旧提示词生成器覆盖 `imagePromptSource=codex` 或 `videoPromptSource=codex`；
- 不允许图片失败自动修复覆盖整批或相邻镜头提示词；
- 不因开启视频提示词而开启实际视频生成；
- 不执行生成后的画风、外貌、服装或文字污染视觉识别检查；本合同只做生成前的确定性绑定校验。
