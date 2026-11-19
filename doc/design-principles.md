# Carto Master 设计原则：LLM 设计自由 × 程序形式验证 × 机械推导

日期：2026-11-11 初版；2026-11-18 修订（Asia/Shanghai）

状态：项目级设计原则。本文定义 LLM 与程序之间的职责边界，是所有制图能力实现的决策依据。运行时只消费 `skills/carto-agent/` 下的 Schema、策略和代码；本文是设计指导，不作为机器协议或审批回执读取。

---

## 一、总则

> **程序不该替 LLM 做表达选择，而是让 LLM 选表达方法与参数，然后是程序验证合法性。**

这是项目在创意设计层的核心原则。但它有三重限定：

1. 它仅适用于**创意设计层**，不覆盖安全边界、物理必然性或机械推导。
2. "程序验证合法性"仅能完成**形式验证**（Schema 合规、物理可行、引用一致），设计合理性仍是 LLM 与人类审图员的领地。
3. 完整的闭环是三段式，不是两段式：**LLM 注册表达 → LLM 选择表达 → 程序验证选择与注册的一致性**。

---

## 二、四层决策模型

所有系统决策点必须归入以下四层之一。跨越层级边界的代码即为需要修正的硬编码。

### 2.1 创意设计层（LLM 的领域）

程序不替 LLM 做本层任何决策。程序提供 catalog 作为选择空间，LLM 在 catalog 中选择，或在 template authoring 阶段向 catalog 注册新表达。

| 决策类型 | 示例 |
|---|---|
| 表达方法选择 | choropleth / proportional symbol / dasymetric / dot density / … |
| 视觉变量映射 | color ramp, symbol size, shape encoding, pattern fill |
| 布局构图 | grid 排列（rows/cols）、frame 空间关系、overlay 位置语义 |
| 排版风格 | 字号、字体、间距、对齐、行距 |
| 分类策略 | jenks / quantile / equal-interval / manual breaks / class count |
| 溢出策略 | clip / shrink / paginate |
| 画布参数 | 尺寸（A4/A3/自定义）、方向（横/竖）、单位（mm/px） |

**已声明的能力边界不是违规**：本层能力若尚未实现，必须在 `skills/carto-agent/policies/capability-roadmap.yaml` 登记，并以 `admission_class=not_implemented` 拒绝（见 `carto_core/roadmap.py`）；未登记或已交付的特征不得返回该分类。安全与协议类拒绝为 `forbidden`，永久有效。本文不维护“当前违规位置”清单：实现状态以代码、Schema、策略与测试为准，静态清单会随实现漂移并误导后续判断。

**原则**：LLM 输出的设计选择以语义参数形式进入模板合同（position: "bottom-right"、rows: 3、columns: 2、title_pt: 18），而不以像素坐标或渲染指令形式出现。程序只从合同中读取，不自造默认值。

### 2.2 形式验证层（程序的领域）

程序在这一层拥有排他的权威——LLM 不能绕过验证。程序的拒绝必须给出精确理由，使 LLM 能够修正重试。

| 验证类型 | 检查内容 |
|---|---|
| Schema 合规性 | `additionalProperties: false`，所有必填字段存在，类型正确，未知字段拒绝 |
| 物理可行性 | frame 在 safe margin 内，尺寸为正；frame 之间不重叠，或为契约显式声明且经程序几何核验的完整包含关系 |
| 引用完整性 | content_id 无重复、无悬挂引用，view→layer→data 绑定链完整 |
| 安全边界 | 路径在 PathGuard allowed roots 内，审批含有效 nonce，HMAC 防重放，scope 绑定 |
| 能力一致性 | 所选表达方法与 catalog 定义一致，所选后端支持声明的输出格式 |
| 协议合规 | 数据格式（GeoJSON/GeoTIFF）、CRS 一致、字段语义匹配 |

**原则**：验证是封闭世界——程序只验证它能形式化定义的约束。验证失败必须阻断流程，不允许静默降级或自动修正。验证通过不证明设计合理，只证明形式合法。

### 2.3 机械推导层（程序的领域）

程序从 LLM 提供的语义级设计参数，机械推导出数值级执行参数。推导过程注入零设计偏好——同样的语义参数总是产生相同的数值结果。

| 推导类型 | 输入（语义参数，LLM 提供） | 输出（数值参数，程序计算） |
|---|---|---|
| 毫米→像素换算 | canvas.width_mm=297, dpi=300 | page.width_px=3508 |
| 网格 cell 坐标 | rows=2, cols=2, gaps=3mm, area=[x,y,w,h] | 四个 frame 的精确 bounds |
| 颜色插值 | color_ramp="sequential-blue", n=7 | 7 个 #hex 值 |
| 分类断点 | method="jenks", class_count=7, data=[…] | 6 个断点值 |
| 图例位置 | position="bottom-right", padding=3mm, frame=[x,y,w,h] | anchor_x, anchor_y 像素坐标 |
| 摘要计算 | 任意可序列化对象 | sha256 digest |
| 字体度量 | font_family, font_size_pt, text_content | glyph 宽度（用于溢出检测） |

**原则**：程序的计算是确定性的。同样的语义参数 → 同样的数值结果。程序不在推导过程中"优化"或"美化"结果。如果推导结果违反物理约束（如 cell 太小放不下内容），程序报告 `GRID_CAPACITY_INVALID`，不自行调整参数。

### 2.4 灰色地带（逐案判断）

本层的决策需要区分语义意图和机械实现，不能直接归入前三层。以下规则指导判断：

| 场景 | 处理方式 |
|---|---|
| 颜色插值方法（linear/lch/cie76？） | LLM 在 catalog 注册时声明；程序执行。程序不替 LLM 选插值空间 |
| 标签碰撞解决（避让/缩写/删除） | MapComposer 在语义允许范围内修订；程序执行算法。程序不替 LLM 决定哪些标签可以删除 |
| 比例尺分段 | LLM 声明"显示比例尺"；程序根据 scale + 画布宽度计算分段数和标注值。程序不跳过比例尺 |
| 图例样式（连续渐变条 vs. 离散色块） | LLM 选择；程序按规则渲染。程序不默认一种样式 |
| 默认值（缺 LLM 指定时的 fallback） | 不应存在代码硬编码默认值。缺失值由模板合同提供（LLM 在 template authoring 阶段设定）。如果两者都缺失，报告缺口而非静默填入 |

**原则**：灰色地带的决策需明确记录哪部分归 LLM（语义）、哪部分归程序（机械）。拆分方式是寻找"LLM 表达意图 → 程序机械实现"的界面。如果一个决策无法拆分为语义+机械，则它应该归入创意设计层（由 LLM 选择）。

---

## 三、catalog 的三段式闭环

当前原则的薄弱环节是 catalog 的静态性——LLM 只能从预置目录中选择。完整的设计自由需要三段式：

```
T1: LLM 注册表达（template authoring 阶段）
    LLM → catalog: {"id": "dasymetric-density", "applicable_data": ["ratio", "continuous"],
                     "visual_variables": ["color_ramp"], "parameters": {...}}
    程序：验证注册声明与 catalog schema 一致；如有冲突，拒绝注册

T2: LLM 选择表达（generate 阶段）
    LLM → catalog: 选择 "dasymetric-density"，指定 data_column、color_ramp_spec、class_count
    程序：验证 selection 与 catalog definition 一致，参数在允许范围内

T3: 程序验证一致性
    程序：检查所选表达的声明约束是否满足当前数据特征
          检查所选表达的实现是否已在当前后端注册
          检查所选表达的参数是否完整且合法
```

T1 注册能力尚未开放，LLM 的选择空间受限于已登记目录。目录条目、状态（active/deprecated）、几何适用性与实际准入范围以 `policies/map-expression-catalog.yaml` 与 `policies/scenario-capabilities.yaml` 为准；本文不复制其计数或清单，以免随实现漂移。开放 T1 时须同时提供注册声明的 Schema、合法/非法样例与自动测试。

---

## 四、排他性领域——程序不可让渡的职责

以下决策不是"程序替 LLM 做选择"，因为 LLM 根本没有权限做这些选择。它们是程序的硬边界：

| 领域 | 不可让渡的理由 |
|---|---|
| 安全与隐私 | PathGuard 白名单、审批 nonce 防重放、密钥不入模型上下文。这些是安全协议，不是设计选择 |
| 物理与数学必然性 | sha256 计算、毫米→像素换算、CRS 投影参数。这些是确定性计算，没有"选择"空间 |
| 渲染引擎能力边界 | Matplotlib 不支持 DPR≠1、MapLibre 不支持 CMYK。LLM 选择了不可行的参数，程序拒绝并说明原因 |
| 确定性审计 | artifact 不可变链、摘要绑定、审批回执。非确定性（LLM 重选）会破坏审计完整性 |
| 协议合规 | Schema `additionalProperties: false`、版本兼容性。这是协议基线，不是设计自由度 |
| 业务硬约束 | 不得生成虚假数据、不得暴露敏感坐标、不得绕过 G1/G2/G3 审批。这是安全策略，不是 LLM 的灵活度 |

---

## 五、与现有设计文档的关系

| 文档 | 本文与之的关系 |
|---|---|
| [carto-agent-architecture.md](carto-agent-architecture.md) 第六节 | 架构文档的 6.4（决策所有权与允许调整范围）、6.7（分层修复与退回条件）是本文原则的架构层面展开。本文为那些决策提供方法论基础 |
| [carto-create-template-TRD.md](carto-create-template-TRD.md) | Template authoring 阶段是本文三段式闭环的 T1（注册表达）的实现载体 |
| [carto-generate-map-TRD.md](carto-generate-map-TRD.md) | Generate 阶段是本文三段式闭环的 T2+T3（选择+验证）的实现载体 |
| [template/map-expression-and-symbol-design.md](template/map-expression-and-symbol-design.md) | 表达目录是 LLM 的选择空间（catalog），本文定义 catalog 的注册、选择和验证协议 |

---

## 六、审查与修订

本文原则的修订应同时检查：

1. `doc/carto-agent-architecture.md` §6.4「决策所有权与允许调整范围」是否与本文四层模型一致
2. `doc/template/` 各模板说明与 `skills/carto-agent/SKILL.md` 的能力边界陈述是否与本文一致
3. 能力缺口是否已在 `policies/capability-roadmap.yaml` 登记，且拒绝分类（`not_implemented` / `forbidden`）与本文层级归属一致

本文不维护代码违规清单。具体缺口与整改项属于路线图、审计记录或测试守卫的职责；把它们放在原则文档里会随实现漂移，并把已声明的能力边界误标为违规。

本文是设计指导，不直接修改代码、Schema、策略或 Fixture。任何基于本文的代码修订，需经过协议定义、实现和测试的同步演进。