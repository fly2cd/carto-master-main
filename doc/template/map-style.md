# MapStyle 完整说明

> **状态公告（2026-11-18）**：品牌段（map-brand/identity）已经用户授权整体移除——它在渲染链中无消费者，移除不改变成图外观。本文已同步清理品牌遗留描述；当前协议以 `skills/carto-agent/schemas/` 与 SKILL.md 为准。

> 2026-11-09 设计收敛：采用 Encoding / Appearance / Composition 三个设计维度及独立 Renderer 执行层；模板是组合载体，不与维度一一映射。统一定义见[模板体系设计](../carto-template-dsg.md)。**所有权与词表的现行权威见[表达与符号设计结论 §11 单表](map-expression-and-symbol-design.md#11-所有权与权威源单表)与 §15 单源规范；历次修订记录见该文档 §14**（原收敛记录文件已不存在，不再作为依据）。新增模型、引用、参数与作用域调整属于目标设计，不改变当前 Schema、能力准入和审批。


> **讨论整理（2026-11-19）**：补充字段取舍、页面级样式与内容角色的关系、人口密度图示例及可证伪验收；Frame 嵌套见 [MapLayout §6.7–§6.8](map-layout.md#67-复合内容与-frame-嵌套目标设计)。这些是设计收敛，不注册新字段、不改变能力准入或审批。

## 1. 文档定位

本文定义 Carto Agent 模板体系中 MapStyle 的概念、作用、职责边界、内容结构、组合接口、兼容规则、发布产物和实例编译结果。

本文面向：

- 地图模板设计者；
- 制图规范维护者；
- MapScenario、MapStyle、MapLayout 的作者；
- 模板编译器和校验器开发者；
- 模板审核与发布人员。

本文属于设计说明。运行时机器协议仍应由 `skills/carto-agent/schemas/`、`policies/`、权威模板索引和已发布模板包定义。

除第 17 节“当前仓库状态”外，文中的扩展结构、接口和流程均为目标设计，不表示当前 CLI 已支持这些输入。

表达目录、内置方法、图表与符号资源的共同边界，以[地图表达目录、内置方法与符号库设计结论](map-expression-and-symbol-design.md)为准：表达规则约束数据与视觉含义；Scenario／任务规定目标；模型设计本次方案；MapStyle 提供兼容视觉配置；受信代码执行，验证反馈用于修订。地图表达目录统一称 Map Expression Catalog，预设不穷举所有合法组合。

---

## 2. 基本介绍

MapStyle 是一套可复用、版本化、可校验的**制图表达规范**。它在表达定义、Scenario 业务约束及适用标准范围内，通过 `symbol_roles` 与 `accepts` 配置视觉表现，例如：

- 有序数值映射所允许的具体色带、方向和对比度；
- 已确定面积编码后的符号外观与经共同验证的尺寸配置；
- 分类对象如何使用不同符号；
- 地名如何设置视觉层级；
- 各符号角色的视觉外观；实际图层顺序由 portrayal 声明；
- 无数据和异常值如何表达；
- 图例如何呈现实例编译提供的真实类别、断点和映射；
- 哪些样式参数可以调整，哪些不可调整。

MapStyle 回答的是：

> 在已确定的语义表达和业务约束下，采用怎样兼容的视觉表现？

MapStyle 不回答：

- 当前业务要画什么；
- 数据文件在哪里；
- 业务字段叫什么；
- 页面是 A3 还是 A4；
- 地图框和图例框放在哪里；
- 具体使用哪个字体文件（由 generate 请求提供）；
- 最终输出 PDF 还是 PNG；
- 交付给谁、保存到哪里。

这些内容分别属于 MapScenario、项目数据绑定、MapLayout、generate 请求的字体声明和 Delivery Target Profile。

---

### 2.1 字段取舍：有作用、有边界、有来源

大白话说，Style 管“东西画成什么样”，Layout 管“东西放在哪里”。字段能否进入模板，不能只看当前某次渲染是否改变了像素：

1. **在声明的范围内复用。** 专用于密度图或某套稳定类别语义的 Style 仍是模板；无需覆盖所有主题和纸张。区分稳定的视觉角色（水体、重点区域等）与本次业务角色/字段绑定，后者归 Scenario/请求。
2. **有条件地验证作用。** 记录消费者、触发条件和可观察结果。没有河流时修改河流符号可以不改变画面；没有碰撞时优先级可以不生效。静态消费链加上可触发条件的用例，才能证明执行效力，不能仅以一次 pixel-identical 判定死字段。
3. **区分设计、实例与推导。** 颜色、线宽、字号等作者选择进入 Style；本次字段和断点进入实例表达；字形边界等计算结果进入测量/实例产物。来源和版本有追溯作用，不要求修改它们必然改变像素。
4. **缺失语义不能靠猜。** 原件只有 `size: 2.5` 时，不能擅自解释为“直径 2.5 mm”再换算为半径；应澄清单位和尺寸含义，或明确记录为新设计决定。

设计目的、阅读顺序、选择理由与不适用情形放在 `design_spec.md`，不伪装成可执行枚举。机器契约只保存有明确消费或校验语义的声明。每项信息还应回答：谁选择、何时解析/冻结、上游变化后哪些结果必须失效重算。两类文件的权威关系见 §6，生命周期见 §15 和 §17。

依据：[设计原则 §2](../design-principles.md#二四层决策模型)、[共同所有权表 §11](map-expression-and-symbol-design.md#11-所有权与权威源单表)。当前执行缺口说明实现状态，不独自决定最终所有权；已登记的未实现能力不能被当成永久设计禁令。

## 3. MapStyle 的作用

### 3.1 统一视觉表达

MapStyle 将颜色、符号、注记和图例规则集中管理，避免同类地图在不同项目中采用互相矛盾的表达方式。

例如，使用同一版本 `blues-5` 色带与 `thematic-area-fill` 角色的地图采用相同的顺序色带方向和无数据外观；无数据含义及图例必须满足的规则来自其引用的表达定义和 Scenario 约束。

### 3.2 解耦业务与视觉设计

目标设计中，MapScenario 通过业务角色与符号角色的绑定表达视觉需求，例如：

```yaml
portrayal_bindings:
  - data_role: thematic-area
    value_role: ordered-value
    style_role: thematic-area-fill
```

该绑定无需复制 `thematic-area-fill` 的颜色、透明度或线宽。MapStyle 提供具体视觉配置，但 Scenario 仍拥有表达选择与业务约束；若 Scenario 已固定表达引用，所选角色必须与之兼容。当前 portrayal 仍持有符号、分类和缩放等字段，**唯一权威以[表达与符号设计结论 §11 单表](map-expression-and-symbol-design.md#11-所有权与权威源单表)为准**，不能同时维持两套执行定义。

### 3.3 支持跨场景复用

一个以抽象语义设计的 Style 可以被不同 Scenario 使用。例如 `sequential-area` 可以用于：

- 人口密度；
- 经济指标；
- 风险指数；
- 服务覆盖率；
- 资源利用率。

Style 使用 `ordered-numeric-value` 等稳定语义，而不是 `risk_pct`、`population_2026` 等具体业务列名。

### 3.4 支持确定性编译

MapStyle 的机器契约为编译器提供明确输入，使同一版本、同一数据、同一环境能够生成一致的制图实例。

### 3.5 支持标准符合性检查

MapStyle 可以引用制图标准，并提供满足标准约束的具体实现。编译器可以逐项验证字号、字体类别、色彩、层级和无数据规则。

### 3.6 支持审计和追溯

最终地图可以记录：

- 使用了哪个 Style 版本；
- 选择了哪些符号角色与色带；
- 应用了哪些受限覆盖；
- 受哪些制图标准约束；
- 每个最终值来自 Style、Scenario、标准还是实例计算。

---

## 4. 与其他模板的区别和联系

| 组件 | 核心问题 | 主要内容 |
|---|---|---|
| MapScenario | 画什么、为什么画 | 业务任务、数据角色、语义绑定、空间规则、用途限制、交付和质量要求 |
| MapStyle | 地图内容怎么表达 | 色带、符号、注记、图层层级、图例和尺度行为 |
| MapLayout | 地图元素放在哪里 | 画布、Frame、边距、占位符、容量和溢出策略 |
| 地图表达目录 / Map Expression Catalog | 方法适用什么、如何表达与验证 | 输入语义、参数约束、编码、图例与检查要求 |
| 内置表达方法与图表核心 | 如何执行计算和绘图 | 受信算法、数据到图形计算及可复用图表绘制 |
| 符号库 / Symbol Catalog | 使用什么图形资源 | 资源、锚点、可调通道和使用约束 |
| Delivery Profile | 以什么形式输出 | 格式、分辨率、色彩模式、文件要求和交付约束 |

推荐组合关系：

```text
MapScenario ──定义业务语义与所需符号角色────────┐
MapStyle ─────提供外观常量与适用语义─────────┤
MapLayout ────提供空间容器和容量───────────────────┤
表达定义 ────提供适用条件、编码与参数约束─────────┤
受信方法/资源─提供计算、图表和实际符号能力────────┤
制图标准 ─────提供强制约束─────────────────────────┤
数据实例 ─────提供实际值域和统计结果───────────────┘
                                                       │
                                                       ▼
                                                  RenderScene
```

MapStyle 与其他模板的关系应通过明确的 `requires`、`provides` 和精确版本引用表达，而不是通过字段级覆盖或名称猜测建立。

---

## 5. MapStyle 的职责边界

### 5.1 应当包含的内容

MapStyle 适合包含（概念广度；机器最小字段集以 §8.1 为准，二者冲突时以 §8.1 为准）：

- 设计原则（不保存 `visual_language` 枚举，该字段已废弃，见 §8.1）；
- 颜色、色带、透明度、线宽、点尺寸等**内联外观常量**（不另立 token 间接层）；
- 面、线、点、文本等符号的使用配置，引用公共资源或受支持的简单图形；
- 适用语义（accepts）；
- 支持的几何类型和抽象语义类型；
- 已注册分类、分级和比例缩放方法的引用及允许的参数默认；
- 参数默认值及允许范围；
- 表达定义与业务约束允许的无数据和异常值视觉配置；
- 注记视觉层级与重叠许可（`labeling.hierarchy`，见 §8.5；不保存 density/collision_policy 枚举）；
- 图例外观及实际映射结果的呈现配置；
- 与比例尺相关的视觉变化归 spatial-behavior，Style 不保存 `scale_behavior`（见 §8.1 删除清单）；
- 对 Layout 和 Renderer 的能力要求；
- 制图标准引用；
- 覆盖、扩展和派生策略；
- Style 级 Fixture 和质量门禁。

### 5.2 不应包含的内容

MapStyle 不应拥有：

- `risk-area`、`shelter-point` 等本次业务数据角色的定义与字段绑定（可提供相应稳定视觉角色的外观，不接管业务语义）；
- `risk_pct`、`capacity` 等源字段名；
- 数据文件路径、坐标和业务数据行；
- 当前地图实际计算出的分类断点；
- 实际最大值、最小值和图例标签；
- A3、A4、420×297 mm 等页面定义；
- Frame 的位置和大小；
- PDF、PNG、DPI 等输出参数；
- 具体字体文件（由 generate 请求提供）；
- CRS 转换、数据准备流程和表达算法的可执行代码；
- 交付目录、接收方和幂等键；
- 审批密钥、审批消费和发布事务；
- MapLibre `paint`、`layout` 等渲染器专用表达式；
- 生产能力、安全边界或公网发布声明。

### 5.3 可以引用但不能重新定义的内容

MapStyle 可以声明：

- 已与 `a3-landscape@1.0.0` 完成兼容性验证；
- 需要 `legend-container`；
- 需要 generate 请求提供显式字体声明；
- 需要 Renderer 支持 `text-halo`；
- 受 `cn-place-name-standard@1.0.0` 约束。

但不能在自身重新定义：

- A3 的尺寸和方向；
- 图例框坐标；
- 字体文件（由 generate 请求提供）；
- Renderer 私有属性；
- 制图标准中的法定约束。

---

## 6. MapStyle 的双层表达

完整 MapStyle 应同时提供人类说明和机器契约。

```text
MapStyle
├── design_spec.md
└── contracts/cartography.yaml
```

### 6.1 `design_spec.md`

面向人，负责说明：

- 设计目的；
- 适用的表达问题；
- 视觉语言；
- 符号选择的原因；
- 外部接口；
- 标准和兼容边界；
- 覆盖与派生原则；
- 已知限制和契约追溯。

### 6.2 `cartography.yaml`

面向机器，负责定义：

- 精确字段和值；
- 内联外观常量与色带；
- 符号角色；
- 参数约束；
- 资源引用；
- 兼容声明；
- 扩展策略；
- Schema 可校验规则。

### 6.3 两者的权威关系

`cartography.yaml` 是运行时权威来源。`design_spec.md` 不应成为第二份机器配置。

如果 Design Spec 为帮助理解而展示色值、字号或尺寸，发布校验应确保这些示例与机器契约一致，或者由机器契约自动生成对应表格。

---

## 7. `design_spec.md` 推荐内容

从合理复用角度，推荐采用以下目录：

```markdown
# MapStyle Design Spec

## 1. 身份与设计目标
## 2. 适用的表达问题
## 3. 视觉语言与设计原则
## 4. 表达能力清单
## 5. 符号系统
### 5.1 面符号
### 5.2 线符号
### 5.3 点符号
### 5.4 文本符号
### 5.5 无数据与异常值
## 6. 注记与图例
### 6.1 注记层级
### 6.2 碰撞与省略
### 6.3 图例生成
## 7. 外部模板接口
### 7.1 MapScenario
### 7.2 字体与署名接口（原 MapBrand，已移除）
### 7.3 MapLayout
### 7.4 Renderer
## 8. 标准与兼容性
## 9. 覆盖、扩展与派生
## 10. 验证、限制与追溯
```

### 7.1 身份与设计目标

建议记录 Style ID、版本、名称、风格定位、设计目标和机器契约引用：

```markdown
- Style ID：`technical-thematic`
- 版本：`1.0.0`
- 机器契约：`contracts/cartography.yaml`

用于技术型专题地图，强调专题变量之间的差异、数值关系和注记可读性。
```

审批详情、文件摘要和发布时间由 Manifest、依赖锁和发布回执管理。

### 7.2 适用的表达问题

应描述抽象表达问题，而不是绑定具体业务：

```markdown
适合：

- 有序数值的面分级表达；
- 非负数量的比例点表达；
- 分类对象的定性符号表达；
- 分级地名注记；
- 显式无数据表达。

不负责：

- 业务数据角色定义；
- 风险等级等业务含义；
- 页面尺寸和版面结构；
- 输出格式和交付要求。
```

### 7.3 视觉语言与设计原则

说明无法从配置值直接推导的设计理由，例如：

- 专题内容的视觉权重高于参考地理信息；
- 顺序型数据主要通过明度变化表达；
- 同一数据角色在不同地图中保持视觉一致；
- 颜色不是唯一的区分手段；
- 无数据必须与零值、背景和最低等级区分。

### 7.4 表达能力清单

列出 Style 对外提供的稳定符号角色与适用语义（词表直接用 IR，不自造 `semantic_types`）：

| 符号角色 | geometry_role | key_mode | measurement | 表达目的 |
|---|---|---|---|---|
| `sequential-area-fill` | polygon | interval | ordinal/rate/ratio/density/normalized-index | 顺序型面分级 |
| `diverging-area-fill` | polygon | interval | rate/ratio（围绕中心值） | 表达偏离 |
| `proportional-circle` | point | scaling | count | 数量型比例点 |
| `categorical-line` | line | discrete | nominal | 分类线状表达 |
| `place-name` / `neighbor-region`（注记角色） | point | — | — | 分级地名注记 |

注记角色**不是测量层次**，归 `labeling.hierarchy`；旧表的 `point/anchor` 中 `anchor` 不是几何类型（IR `geometry_role` 无此值），已删除。

这一节用于快速判断能力覆盖，不复制所有符号参数。

### 7.5 符号系统

说明符号家族、视觉变量、选择原因、协调关系和可调整边界：

```markdown
数量型点要素按引用表达的要求使用圆形面积比例符号，半径由面积推导。颜色使用专题 Token；尺寸调整必须保持规定的数量关系。若采用最小可见尺寸或截断，应明确适用范围和图例说明，不能声称所有数值仍严格满足面积比例。
```

具体参数应引用机器契约路径，例如 `/symbol_definitions/proportional-circle`。

### 7.6 注记与图例

注记部分应说明：

- 注记层级；
- 字体角色（由 generate 请求声明提供）；
- 颜色和光晕原则；
- 避让、优先和省略原则；
- 多语言策略；
- 注记与专题符号的优先关系。

图例部分应说明：

- 图例从哪些符号角色和实例结果生成；
- 分类、比例和定性符号如何展示；
- 无数据如何表达；
- 单位和数值格式原则；
- Layout 容量不足时如何处理。

图例必须从 `resolved-portrayal` 的实际结果生成，不能使用模板默认断点冒充实例结果。

### 7.7 外部模板接口

对 MapScenario，以 §8.4 的 `accepts` 声明可接受的测量层次、几何和编码形式；对 MapLayout，声明所需容器能力；对 Renderer，声明抽象渲染能力。所需字体角色通过请求提供的字体声明绑定，不恢复品牌段。

```yaml
# 目标接口片段，不是当前 CLI 的完整输入
accepts:
  - key_mode: interval
    measurement: [density]
    geometry_role: [polygon]
compatibility:
  required_layout_capabilities: [map-container, legend-container]
  required_renderer_capabilities: [fill-symbol, text-halo]
```

### 7.8 标准与兼容性

建议记录：

- 适用媒介；
- 支持语言；
- 已验证比例尺范围；
- 支持的色彩模式；
- 制图标准引用；
- 已验证的 Layout 和 Renderer 组合；
- 尚未验证的组合。

“与 A3 Layout 完成验证”属于兼容证据，不表示 MapStyle 定义了 A3。

### 7.9 覆盖、扩展与派生

明确每类变化是否允许：

| 变化类型 | 推荐策略 |
|---|---|
| 符号角色子集选择 | 允许 |
| 分类数 | 归本次表达方案与目录约束；不是 Style 的覆盖参数 |
| 透明度 | 约束范围内允许 |
| 色带方向 | 按所选色带的显式许可；不从顺序/定性名称自动推断 |
| 字体文件 | 由 generate 请求显式声明提供 |
| 新增符号角色 | 创建新版本或派生 Style |
| 渲染器私有表达式 | 禁止实例直接提供 |

### 7.10 验证、限制与追溯

记录 Style 自身的验证条件、表达限制和设计概念到机器契约路径的映射。

Style 限制示例：

```markdown
- 不提供流向符号；
- 不提供三维表达；
- 不支持双变量面填充；
- 当前地名注记角色只验证了中文环境；
- 色带尚未针对深色背景验证。
```

追溯表示例：

| 设计概念 | 机器契约路径 |
|---|---|
| 色带与来源 | `/ramps`（目标字段） |
| 符号角色与内联常量 | `/symbol_roles`（目标字段） |
| 适用语义 | `/accepts`（目标字段） |
| 字号与注记 | `/typography`、`/labeling` |
| 图例外观 / 实际项目 | Style 的字号与符号角色 / `resolved-portrayal.legend_items` |
| 覆盖规则 | `/extension_policy` |

---

## 8. 机器契约推荐结构

本节已按[表达与符号设计结论 §15](map-expression-and-symbol-design.md#15-词表与概念单源规范规范性附录)执行**概念删除**：原四层嵌套 `tokens → symbol_definitions → portrayal_profiles → labeling/legend/scale` 已废除。删除理由与证据逐项见该节 §15.2；本节只保留**有唯一权威且不交叉描述**的概念。

保留的核心关系只有两层：

```text
ramps / symbol_roles（外观常量，内联数值）
  + labeling（注记常量与层级）
  + accepts（适用语义，唯一硬匹配依据）
```

### 8.1 顶层结构

以下是目标最小字段集；`ramps`、`symbol_roles`、`accepts` 等仍待协议演进，不能把示意版本号当成已注册 Schema。完整字段和状态以共同单表为准。

| 字段组 | 保存什么 | 不接管什么 |
|---|---|---|
| `schema_version`、`style_id`、`version` | 已登记的协议版本、资产身份和版本；发布包绑定摘要 | 不以虚构版本/摘要冒充发布 |
| `accepts` | measurement × geometry_role × key_mode | 不重复目录的方法允许集和类数上限 |
| `ramps` | 精确色值、顺序、scheme、反转许可、来源 | 不保存本次分级断点或自动补色偏好 |
| `symbol_roles` | 角色对应的符号、单位明确的外观常量与可调范围 | 不绑定临时业务列名 |
| `typography` | 页面标题、正文、图例字号与行距 | 不保存字体文件路径、容器坐标 |
| `labeling` | 注记角色、优先级、重叠许可、光晕及字体角色引用 | 不替业务决定必须出现或可删除的内容 |
| `compatibility`、`extension_policy`、`standard_refs` | 能力要求、允许调整的边界、适用标准引用 | 不复制标准阈值或绕过能力准入 |
| `rules` | 已有可执行校验语义的声明，遵守共同 §12 | 不把自然语言愿望当作已执行规则 |

不是每个 Style 都必须制造所有能力：无注记的设计不必添加无用层级。`typography` 保持独立顶层；不为了组织示例再移入 `labeling`。

**已删除的顶层概念**（不得以别名重新引入）：`visual_language`、`tokens`、`symbol_definitions`、`portrayal_profiles`、`text_styles`、`layer_order`、`legend`、`scale_behavior`。其中图例外观由符号角色及 `typography.legend_pt/legend_heading_pt` 提供；图例项目与断点归 `resolved-portrayal`。

### 8.2 色带（ramps）

分级表达必需一个**有序色值序列**，因此保留 `ramps`。但**删除通用 `tokens` 间接层**（colors/dimensions/opacities + `token_ref`）：多一层命名解析就多一类悬挂引用风险，而 `symbol_catalogs` 的 11 个 ref 零实体已经演示了该失败。标量常量直接**内联**于 `symbol_roles`。

```yaml
ramps:
  - ramp_id: blues-5
    scheme: sequential               # 词表与请求 color_ramp.scheme 一致；有序性由此推导
    reversible: false                # 本例禁止实例反转；不是所有顺序色带的普遍禁令
    colors: ["#EFF3FF", "#BDD7E7", "#6BAED6", "#3182BD", "#08519C"]
    provenance:
      source_type: external-authoritative
      source_ref: "ColorBrewer / Blues / 5 classes"
      license: "Apache-2.0"
  - ramp_id: qualitative-tol-bright
    # 定性色带**不带 scheme**：无明度顺序语义，只校相邻可区分性与色盲安全
    colors: ["#4477AA", "#EE6677", "#228833", "#CCBB44", "#66CCEE", "#AA3377", "#BBBBBB"]
    provenance:
      source_type: external-authoritative
      source_ref: "Paul Tol bright qualitative scheme"
```

硬要求：

- **必须内联真实 hex 序列**，不得只写一个指向不存在注册表的 ref。
- 颜色字面量统一大写 `^#[0-9A-F]{6}$`（词表权威见仲裁文档 §15.1）。
- **`scheme ∈ {sequential, diverging}`，与请求 `color_ramp.scheme` 同一词表**；未知值由 `color_checks.check_ramp` 抛 `COLOR_RAMP_SCHEME_UNKNOWN`。定性色带不带 scheme。本文早先提案的 `perceptual_type` **已废弃**（与现有 `scheme` 重复）。
- 感知判据已由 **`policies/color-redlines-policy.yaml`** 落地为活门禁：顺序色带 L\* 单调（diverging 为升致中央亮极大值后降，Brewer）、相邻类 ΔE76 下限、CVD 模拟后 ΔE76 下限。**Style 不得另行声明一套阈值**。
- 色带不得包含页面尺寸、Frame 坐标或实例统计值。

五级 Blues 色值来源为 [ColorBrewer 原始导出数据](https://github.com/axismaps/colorbrewer/blob/master/export/colorbrewer.json)。这里只给出来源定位，不是假定已经冻结了外部依赖：发布时须核对来源版本、许可与摘要。采用既有配色不等于已经通过本地图的可读性、色觉或印刷验收。

五个色值表示一个可选资产有五项，不把“分类数必须为五”写成 Style 的业务约束。请求选择的类数、映射方向和资产必须兼容；需要七级时，应选择或设计对应资产，或显式选择已注册插值方法，不能由程序自作主张补色。定性色带虽无数值大小顺序，也不能在类别—颜色绑定冻结后随意换序；颜色反转不会自动把高程业务变成深度业务。

### 8.3 符号角色（symbol_roles）

`symbol_roles` 合并了原 `symbol_definitions` 与 `tokens`，并**直接复用 encoding-IR 的符号词汇**（`color`、`stroke`、`stroke_width_pt`、`radius_mm`），不自造 `channels` 方言。理由：IR 是唯一有渲染消费点的符号权威（page_renderer.py:355-359、371-372），另造一套必然形成双重执行来源。

数据字段到大小、颜色或方向的**计算**仍由受信表达方法执行；Style 只声明常量与允许范围，不绑定业务字段名。

```yaml
symbol_roles:
  - role: thematic-area-fill
    geometry_role: [polygon]
    key_mode: [discrete, interval]
    symbol:
      stroke: "#475569"
      stroke_width_pt: 0.57          # 0.2mm × 72/25.4
    fill_color_from: ramp            # 由 IR 按位置绑定，此处不写死
    opacity: 0.82
    adjustable:
      stroke_width_pt: {min: 0.25, max: 2.0}

  - role: proportional-circle
    geometry_role: [point]
    key_mode: [scaling]
    primitive: circle
    symbol:
      color: "#087E8B"
      stroke: "#222222"
      stroke_width_pt: 0.4
    size_semantics: radius           # 必填：radius | diameter | area
    size_range_mm: {min: 2, max: 12} # 数值内联，不用 token_ref
```

硬要求：

- **所有长度必须携带单位**；字号用 pt、符号尺寸用 mm。
- **`size_semantics` 必填**。旧示例的 `size` 未区分直径/半径/面积，而 IR 已用 `radius_mm` 明确解决；不得重新引入歧义。面积比例关系（直径 = 参考直径 × sqrt(value/参考值)）见 §6.3 of 表达与符号设计结论。
- 可选 `asset_ref` 引用外部图形资源，但**必须精确钉住 id/version/digest 且可解析**；不得引入独立的“符号库注册表”实体。
- 按 `geometry_role` 条件化必填字段：面填充不应被要求声明 `radius_mm`（当前 IR 将其列为 required，已登记为待修缺陷）。

### 8.4 适用语义（accepts）——取代 Profile

**`portrayal_profiles` / “Profile” 已删除**。理由：它的每一个组成部分都已有唯一权威，Profile 仅余一个命名层：

| 原 Profile 字段 | 已有权威 | 证据 |
|---|---|---|
| `expression_ref` | `portrayal.layers[].map_expression_ref` | portrayal.schema.json:99-118、478-494 |
| `accepts.geometry_types` | catalog `applicable_geometry` | map_expression_catalog.py:100-105 |
| `accepts.semantic_types` | IR `domain.measurement` | encoding-ir.schema.json:57 |
| `parameter_constraints` | catalog `validation.rules` | expression_validator.py:92-114 |
| `parameter_defaults.class_count` | **属本次设计决策，不属可复用 Style** | 类数随数据分布与制图目的变化（Slocum） |
| `missing_value` | IR `missing.{policy,label,symbol}` | encoding-ir.schema.json:107-113 |
| `symbol_ref` | `symbol_roles[].role` | 本文 §8.3 |

保留下来的唯一必要概念是 **`accepts`**：声明本 Style 的外观适用于哪些语义 situation，作为**唯一硬匹配依据**（取代 §11 的 profile 名子集匹配）。词表直接用 IR，不自造 `semantic_types`：

```yaml
accepts:
  - key_mode: discrete
    measurement: [nominal]
    geometry_role: [point, line, polygon, raster-cell]
  - key_mode: interval
    measurement: [ordinal, rate, ratio, density, normalized-index]
    geometry_role: [polygon, raster-cell]
  - key_mode: scaling
    measurement: [count]
    geometry_role: [point]
```

约束关系不变：表达定义、Scenario、Style 和执行环境的约束必须**同时满足**；Style 不得放宽表达适用条件、改变数量映射语义或保存某次数据计算出的分类断点。若 Scenario 已固定表达而 Style 不适配，应报告不兼容。

**方法允许集与类数范围不在 Style 重复声明**。目录是约束权威；重复声明已被实测证明会漂移（旧 IR `maxItems=32` vs 目录上限 12，13 类曾被接受）。**现已单一权威化**：三个 schema 的结构界收紧到 12，并由棘轮守卫强制与目录相等（见仲裁文档 §14.9）。

#### 表达设计与外观配置的关系

外观配置可复用，不要求为每次图形组合新增一份 Style。若实例采用未预先命名的组合，应在 Style 明确开放的范围内使用兼容配置，且由计划和表达规则拥有数据映射；不能把新增语义伪装成参数调整。若现有 Style 不适配，按现有派生、替换或方案修订流程处理。

“行业用蓝色还是紫色”可以是外观配置；“颜色表示行业还是产值高低”改变编码含义。柱状图切换为饼图还涉及分母和比较方式，须由规划重新确定方案并验证。默认推荐与硬约束沿用既有规则语义，不因某预设常用就禁止所有兼容替代方案。

表达方案和通用组合能力仍须正式协议支持，本文不新增任意脚本或运行时组合入口。

### 8.5 注记（labeling）

**`text_styles` 作为独立顶层名已删除**，与 `labeling` 合并——两者描述同一事物。同时删除三个重复或不可校验的子字段：

| 删除 | 理由 | 替代物 |
|---|---|---|
| `labeling.density`（low/medium/high） | 与请求 `labels.max_labels` 重复表达同一数量 | `labels.max_labels` |
| `labeling.font_role` | 与下方 `font_role_ref` 重复；角色定义权归外部字体声明 | `hierarchy[].font_role_ref` |
| `labeling.collision_policy`（三值枚举） | 一个枚举混了两个正交轴，且行为硬编码 | `allow_overlap: bool` + `priority: int` |

```yaml
labeling:
  halo: {color: "#FFFFFF", width_mm: 0.5}   # executed；width_mm 为向外半径
  hierarchy:
    - role: place-name
      size_pt: {default: 12, min: 10, max: 14}
      color: "#333333"
      font_role_ref: body-font
      weight: 600
      priority: 90
      allow_overlap: false
    - role: neighbor-region
      size_pt: {default: 11, min: 9, max: 13}
      color: "#888888"
      font_role_ref: body-font
      priority: 40
      allow_overlap: false
```
示例 `body-font` 是必须由请求字体声明解析的角色，不是品牌对象，也不构成静默字体回退。`halo.width_mm` 的范围以 `cartography.schema.json` 为唯一权威（当前 0.1–2mm）；本文不再另行声明一套范围。实际字体文件由 generate 请求的显式字体声明提供（品牌段已移除）；强制字号范围可由制图标准进一步约束。

注记数量上限由请求 `labels.max_labels` 拥有；避让算法由程序执行，但**哪些注记可被丢弃由 `priority` 与 `allow_overlap` 语义决定**，不由程序自定。

### 8.6 图层顺序（已删除相对约束）

**`layer_order.constraints` 已删除**。理由：

1. 执行权威已存在且唯一：`portrayal.layers[]` 的**数组声明顺序**（page_renderer.py:340-342：“later layers cover earlier ones”）与 `z_order`。
2. 相对约束存在二难：若约束集唯一确定全序，则等价于直接写出顺序，抽象零收益；若为偏序，程序必须选一个拓扑序，**而选择规则就是设计偏好**，违反 design-principles §2.3“推导过程注入零设计偏好”。

若确需表达“注记必须在专题之上”这类硬要求，应写成**对已声明顺序的可验证谓词**（检查是否满足），而不是生成式方程。页面层级与地图图层顺序是两套关系，分别由 Layout 与 portrayal 管理。

### 8.7 兼容性与扩展策略

`accepts` 已拥有适用语义，不在 `compatibility` 再复制一份 measurement / geometry 集合。后者只描述媒介、语言及组合所需能力。

```yaml
# 目标接口片段；所有能力名须经注册并验证后才能执行
compatibility:
  media: [print]
  locales: [zh-CN]
  required_layout_capabilities: [map-container, legend-container]
  required_renderer_capabilities: [fill-symbol, text-halo]
extension_policy:
  parameter_overrides: constrained
  renderer_specific_properties: forbidden
```

可调整的具体字段和范围由其唯一声明处提供，例如 §8.3 的符号参数 `adjustable`；不再复制一套 Profile 或 token 覆盖表。未声明的变更不得自动应用。新增角色或修改不可调外观应形成新版本/派生资产。允许调整不授权 Renderer 临时缩字、改色或改变数据映射。

---

### 8.8 图表配置与放置

目标设计允许 Style 为通用柱状图、饼图、折线图提供颜色、字体、线条和图例外观。若场景已有独立图表定义，应复用其通用图表部分，不为地图再复制一套绘图算法。

图表核心根据数据与配置生成局部坐标图形及测量边界。地图内使用由表达与空间编译增加地理锚定、跨要素尺度协调和避让；独立辅助图使用 Layout Frame 进行页面放置，无需强制引用地图表达目录。统计范围、Top K 与单位由 Scenario/任务和数据准备决定，不能由 Style 美化过程改写。

固定柱状图或饼图图标属于符号资源；根据数据变化的柱高或扇区需要受信图表计算。这些是复用边界，不表示当前已经存在通用 chart 协议或独立图表模板类型。

图表核心可以提供成熟预设，也可以通过已支持的图形、尺度和分组能力组合方案，不需要穷举所有完整绘图函数。代码可由模型辅助开发，但 Style 只引用可用能力和配置，不携带实现。输入输出之外的语义、特殊情况及独立验证要求，见[绘图接口契约](map-expression-and-symbol-design.md#91-绘图接口不仅约定输入输出结构)；每次制图动态执行模型代码仍未开放。

### 8.9 联合示例：某市各区人口密度概览

这是需求和参数示例，不包含虚构人口数据、分级断点或渲染验收。字号、线宽和构图是本例作者选择，不是行业标准强制值。Layout 侧对应 [MapLayout §10.3](map-layout.md#103-联合示例a4-人口密度概览)。

| 所有者 | 本例决定 |
|---|---|
| Scenario/本次方案 | 确认区界、人口与面积统计口径、字段、年份、缺失值处理；计划五级，分类方法和实际断点另行确认；选择 `blues-5` 按低到高绑定 |
| Style | `accepts` 为 density × polygon × interval；色带使用 §8.2 的 `blues-5`；专题面描边 `#666666`、`stroke_width_pt: 0.35`、不透明度 1；标题 18 pt、正文 9 pt、图例 10 pt、图例标题 11 pt、行距 1.25 |
| Layout | A4 横版，主图在左、图例在右，来源说明独立置底；只存容器和排版规则 |
| 请求资源 | 实际字体及其摘要、业务内容与数据引用；不由 Style 猜文件路径 |
| 程序 | 校验适用条件，计算/核验断点，绑定颜色，派生同源图例，测量内容并冻结实例 |

Style 不含城市名、年份、源列名和本次断点。换城市或年份可以复用，但不自动沿用旧断点。地图和图例必须消费同一份已解析映射，不能分别从 Style 和旧准备报告取色。

若改字号或更换字体，须重算文字及受影响的版面；若换纸张，先选兼容 Layout 并重新测量，不自动改变专题编码；若由五级改七级，回到表达方案及色带选择，不伪装成 Layout 的溢出修复。每个决定必须在相关产物冻结前进入链路；冻结后不得就地改锁或沿用不匹配的审批。

---
## 9. 制图标准与 MapStyle

制图标准和 MapStyle 是“约束”与“实现”的关系：

```text
制图标准：规定必须满足什么，以及允许什么范围
MapStyle：提供满足标准约束的具体视觉实现
```

例如：

| 内容 | 所有者 |
|---|---|
| 省级地名必须大于县级地名 | 制图标准 |
| 某比例尺下字号必须在 10～14 pt | 制图标准 |
| 禁止使用红色地名文字 | 制图标准 |
| 本 Style 选择 12 pt | MapStyle |
| 本 Style 选择深灰色 | MapStyle |
| 机构提供的具体字体文件 | generate 请求字体声明 |
| 地名源字段 | Scenario/项目数据绑定 |
| 最终避让位置 | 地图实例编译结果 |

MapStyle 应精确引用标准版本和摘要：

```yaml
standard_refs:
  - id: cn-thematic-place-name
    version: 1.0.0
    digest: "sha256:..."
```

编译器必须真正检查 Style 值是否满足标准，不能只接受“符合标准”的文字声明。

组合时区分所有权、硬约束和可调默认值，不建立模板之间的通用覆盖阶梯：

- 安全与平台限制、适用制图标准、Scenario 业务硬规则和表达约束必须同时满足；
- Style 拥有视觉配置，其硬约束不能被实例参数覆盖；
- 实例只能调整明确开放的参数，并记录来源；默认值被替换后仍须通过全部适用约束；
- 外部 Style 替换 Scenario 内嵌 cartography 时，须满足可替换声明并采用完整段替换。

任一硬约束无法满足都应报告冲突，返回相应所有者修订。六种规则标签用于区分约束性质，不表示数值优先级。

---

## 10. 与其他组件的接口

### 10.1 MapScenario 接口

MapScenario 声明业务数据角色、值语义和所需符号角色：

```yaml
portrayal_bindings:
  - data_role: indicator-area
    value_role: indicator-value
    measurement: ordinal
    style_role: thematic-area-fill
```

MapStyle 声明符号角色可以接受的几何与测量层次（词表直接用 IR）：

```yaml
provides:
  symbol_roles: [thematic-area-fill]

accepts:
  - key_mode: interval
    measurement: [ordinal, rate, ratio, density, normalized-index]
    geometry_role: [polygon]
```

### 10.2 品牌接口（已移除）

品牌段（map-brand/identity）已于 2026-11-18 经用户授权整体移除（渲染链无消费者）；原 `brand_roles` requires/provides 接口不再存在。字体文件由 generate 请求的显式字体声明提供，署名文本来自场景策略 notice。

### 10.3 MapLayout 接口

**页面选择一套基础 Style，内容角色使用其中相应规则；Frame 不各自绑定一套完整 Style。** Style 与 Layout 在模板库中是可兼容组合的多对多关系，不是固定配套资产。本次页面只有在接口、标准、能力和实际测量均满足时才能组合。

| 内容 | Layout 负责 | Style/表达负责 |
|---|---|---|
| 页面标题 | 容器位置、宽高、对齐、换行 | 标题字号等外观 |
| 地图视图 | 地图框与裁剪、内容绑定 | 各图层的符号/注记规则；实例映射由 portrayal 冻结 |
| 图例 | 容器、列数、间距、所服务视图 | 文字外观来自 Style；真实类别、断点与符号样本来自同一实例表达 |
| 来源说明 | 容器和可用空间 | 正文外观；文字内容归任务/场景 |
| 复合信息卡片 | 父子 Frame 的空间组织（目标） | 子内容按角色取样式，不因嵌套而复制完整 Style |

移动标题到另一 Frame 不改变其标题角色。地图框内部的河流、专题面、地名分别选所需规则，不能用“给整个 Frame 一个颜色”代替图层表达。同页多图可以在声明范围内选择不同符号角色/色带，但是否共享编码由本次方案决定；共享图例、共享编码尺度、相同地图比例尺不是同一约束。

复杂图文的拆分边界与父子关系由 [MapLayout §6.7–§6.8](map-layout.md#67-复合内容与-frame-嵌套目标设计) 拥有。多套完整 Style 的局部作用域、级联优先级和任意 Frame 覆盖未开放；确需扩展时须显式定义作用域、来源和冲突校验，不引入隐式深层合并。

**当前证据：** [page-request.schema.json](../../skills/carto-agent/schemas/page-request.schema.json) 只有一个页级 `appearance`，[resolved-appearance.schema.json](../../skills/carto-agent/schemas/resolved-appearance.schema.json) 持有一个 `style_ref`；[appearance.py](../../skills/carto-agent/scripts/carto_core/compiler/appearance.py) 从一份 cartography 解析外观，[static_page_renderer.py](../../skills/carto-agent/scripts/carto_core/adapters/static_page_renderer.py) 按标题/正文/图例用途读取字号。这不证明目标角色机制或 Style 色带已全部接线，颜色现状见 §17。

Style 声明需要地图/图例容器；Layout 提供空间，不承诺手写的“最多 12 项”。双方参数与真实内容、字体共同决定是否适配，测量机制见 [MapLayout §7](map-layout.md#7-容量测量与溢出)。

### 10.4 Renderer 接口

MapStyle 只声明抽象能力：

```yaml
requires:
  renderer_capabilities:
    - fill-symbol
    - proportional-circle
    - text-halo
```

Renderer Adapter 负责将抽象表达编译为 MapLibre 或其他渲染器的专用属性。

---

## 11. 需求与 MapStyle 的匹配

匹配不是要求需求与 Style 完全相同，而是要求 Style 覆盖需求：

```text
Scenario.required_semantics
    ⊆ MapStyle.accepts        # measurement × geometry_role × key_mode
```

**硬匹配以 `accepts` 为唯一依据，不再用 profile 名子集匹配**（后者已删除：名字不是稳定单元，而 IR 已将测量层次×几何×编码形式化）。Style 可以包含本次未使用的符号角色；编译器只选择实际需要的部分，其余定义不进入地图实例。

建议使用三种结果：

| 状态 | 含义 | 处理方式 |
|---|---|---|
| `compatible` | 完整覆盖需求 | 直接选择所需符号角色 |
| `compatible_with_declared_overrides` | 差异位于允许范围内 | 应用并记录受限覆盖 |
| `incompatible` | 缺少能力或违反标准 | 更换、升级或派生 Style |

硬性检查至少包括：

- 所需符号角色、色带及其精确引用是否存在；
- 几何类型是否兼容；
- 语义类型是否兼容；
- 制图标准是否满足；
- 字体声明是否齐全；
- Layout 是否经本次真实内容和字体测量确认可容纳；
- Renderer 是否支持所需能力；
- 媒介、语言和尺度范围是否适用；
- 依赖版本和摘要是否精确匹配。

只有通过硬性检查的候选才可以进一步评分或排序。

---

## 12. 覆盖、版本和派生

### 12.1 实例覆盖

实例只能修改 Style 明确允许的参数；允许范围只在唯一声明处定义。例如 §8.3 的 `thematic-area-fill.adjustable.stroke_width_pt` 已声明范围，本次可显式把描边由 0.57 pt 调为 0.8 pt，并验证其未越界。这里不重复范围，也不再把分类数写成 Style 的覆盖参数。

解析/调整证据应绑定基础 Style 的精确引用、目标角色与字段、原值、选定值、选择来源及适用约束。未使用角色的变更可能不影响当前像素，但仍影响资产身份；不能以图片相同为由跳过摘要绑定。记录接入现有实例产物和回执，不新建一套 style-resolution 锁。

实例覆盖不修改已发布模板。需要改变角色集合、未开放参数或业务映射时，分别返回模板版本演进或本次规划；不能由 Renderer 自行选择替代值。Style、标准和 Layout 的约束必须共同满足。

### 12.2 新版本

以下变化通常要求发布新版本：

- 修改固定 Token；
- 修改符号角色的默认外观或允许调整边界；
- 修改允许覆盖范围；
- 修改标准依赖；
- 修正符号或注记规则；
- 增加或废弃符号角色。

兼容性破坏应提升主版本号。

### 12.3 派生 Style

如果原 Style 基本合适但缺少新能力，可以创建派生 Style：

```yaml
style_id: technical-thematic-with-flow
version: 1.0.0

derived_from:
  id: technical-thematic
  version: 1.0.0
  digest: "sha256:..."
```

派生关系用于说明来源。发布物仍必须包含完整、自洽、可独立校验的机器契约，不能在运行时临时拼接父 Style。

### 12.4 仅作为设计参考

如果实际修改超出允许范围，原 Style 只能记录为：

```yaml
design_reference_ref: {...}
```

不能将最终地图声明为符合原 Style。

---

## 13. 模板包组织

建议的 MapStyle 模板包：

```text
templates/map-style/<style-id>/<version>/
├── manifest.yaml
├── design_spec.md
├── contracts/
│   └── cartography.yaml
├── dependencies.lock.yaml
├── assets/
│   ├── sprites/
│   ├── symbols/
│   └── palettes/
├── fixtures/
├── quality-gates.yaml
└── checksums.sha256
```

### 13.1 `manifest.yaml`

记录模板身份、状态、文件闭包、摘要、依赖锁路径和目标能力。

### 13.2 `design_spec.md`

记录人类可读的设计目标、原则、能力、接口和限制。

### 13.3 `contracts/cartography.yaml`

MapStyle 的机器可执行契约。

### 13.4 `dependencies.lock.yaml`

精确锁定：

- 实际引用的地图表达定义（Map Expression）；
- 实际引用的符号资源及版本，不默认锁定整个 Symbol Catalog；
- Sprite、Icon 和 Palette；
- 制图标准；
- Checker；
- 其他不可变资源。

上述为目标依赖范围。当前 Scenario 基线要求锁资源集合等于现有两项表达目录集合；按需锁定引用子集需要明确演进，不能仅改变文档示例就视为已支持。

### 13.5 `assets/`

保存允许随模板发布的非敏感视觉资产。字体是否随 Style 发布应由授权策略决定；字体文件由 generate 请求显式声明提供，Style 不打包机构字体文件。

### 13.6 `fixtures/`

使用抽象合成数据验证表达能力，例如：

- `ordered-polygon-values`；
- `proportional-point-values`；
- `hierarchical-place-labels`；
- `missing-value-area`；
- `dense-label-collision`；
- `legend-capacity-boundary`。

Fixture 不应包含真实业务数据、敏感坐标或完整业务数据行。

### 13.7 `quality-gates.yaml`

声明发布前必须运行的注册 Checker 和通过条件。

---

## 14. 验证与质量门禁

### 14.1 结构验证

- 所有文档通过 JSON Schema Draft 2020-12；
- 未知字段默认拒绝；
- ID、版本和摘要格式合法；
- 文件闭包和校验和一致；
- 依赖全部精确锁定。

### 14.2 语义验证

- 所选符号角色引用的资产存在；
- Token 引用闭合；
- 默认值位于约束范围内；
- 几何类型与表达算法兼容；
- 语义类型与视觉变量兼容；
- 无数据和异常值策略完整；
- 相对图层顺序不存在环；
- 允许覆盖不会破坏硬规则。

### 14.3 标准验证

- 标准引用版本和摘要精确匹配；
- 字体类别、字重、字号和颜色满足约束；
- 行政地名等层级关系满足标准；
- 冲突规则有确定性处理方式。

### 14.4 组合验证

- Style 提供兼容的视觉配置；
- Layout 提供所需容器和容量；
- Renderer 提供所需能力；
- Scenario 请求的符号角色和适用语义受支持。

### 14.5 Fixture 渲染验证

- 符号可辨识；
- 颜色顺序正确；
- 比例符号语义正确；
- 无数据能够识别；
- 注记碰撞行为符合规则；
- 图例与实际表达一致；
- 资源能够离线、确定性加载。

### 14.6 不属于 Style 的成品检查

以下应由 Layout、Renderer、Final Check 或 Delivery 验证，而不是 MapStyle：

- 页面尺寸和方向；
- PDF/PNG 文件签名；
- 输出像素和 DPI；
- 最终声明文本是否存在；
- 交付包白名单；
- 最终目录和接收方；
- G3 审批和交付事务。

---

### 14.7 条件化的作用验证（目标验收要求）

下表是需要实现/运行的验收设计，不声称本轮已执行实验。验证对象不仅是 PNG 文件摘要，还包括解析映射、解码后的像素区域、拒绝原因和来源闭包。

| 用例前提与变更 | 应观察的结果 |
|---|---|
| 选中确实可见、未被遮挡的类别，改变其有效色值 | 实例映射与相应像素/图例符号一致改变 |
| 只改当前未使用的符号角色 | 当前画面可保持不变，资产版本/摘要仍须正确绑定 |
| 注记确实发生碰撞，改变已声明优先级 | 按声明规则处理，保留必需内容；无碰撞用例则可不变 |
| `accepts` 与任务不兼容 | 在兼容检查拒绝，不静默改任务或选另一表达 |
| 字体、文字、字号或框几何发生变化 | 旧测量不得直接复用，重新测量受影响部分 |
| 地图与图例的映射来源不同或被冻结后被改写 | 一致性/摘要校验失败，而非重新选色掩盖差异 |

空白图、不可见要素或未触发的限制，不能证明字段无用。反过来，文件哈希改变也不单独证明目标视觉规则正确。规则路径可解析是必要条件，执行器还须真的验证约束含义，不能靠更换路径把“预览专用”等业务限制改成另一种规则。

---
## 15. MapStyle 的输出

### 15.1 模板发布输出

MapStyle 发布后得到不可变模板包和权威索引记录：

```text
manifest.yaml
design_spec.md
contracts/cartography.yaml
dependencies.lock.yaml
assets/...
fixtures/...
quality-gates.yaml
checksums.sha256
publication-receipt
template-index entry
```

### 15.2 地图实例编译输出

实例外观产物使用**已有的 `resolved-appearance`**（Schema v2，由 `compiler/appearance.py` 生产）。原提案名 `ResolvedCartography` / `resolved-cartography.yaml` **已删除**：它是重复实体，仓库中并无对应 Schema，而 `resolved-appearance.schema.json` 已存在。不得新增第四种 `resolved-*` 产物。

```yaml
# resolved-appearance（已有 Schema）
style_ref: {...}
cartography: {...}          # 冻结的 Style 契约
typography: {...}           # 含由 layout.content_padding_mm 注入的 padding_mm
color_sources: [...]        # 指向 resolved-portrayal，图例与断点不在本产物

# 实例表达结果（图例项、断点、符号）归 resolved-portrayal
# 实例排版结果归 resolved-layout
```
**来源追溯（provenance）不另立产物**：每个最终值来自 Style、Scenario、标准还是实例计算，由已有的三个 `resolved-*` 产物与 MapSpecLock 共同承载：外观常量与覆盖来源记于 `resolved-appearance`（含 `style_ref` 与冻结的 `cartography`）；实际分类断点、最终图例与符号尺寸记于 `resolved-portrayal`；框几何与排版选择记于 `resolved-layout`。标准约束通过 `standard_refs` 与 `rules`（须满足表达与符号设计结论 §12）进入冻结契约，不另建一份平行清单。

原提案中的 `selected_profiles`、`resolved_tokens`、`resolved_layers`、`resolved_labels`、`resolved_legend`、`resolved_scale_behavior` 字段**均已删除**：它们分别重复于 `symbol_roles` 选择、内联常量、portrayal 层序、`labeling.hierarchy`、`resolved-portrayal.legend_items` 与 `spatial-behavior.scale_bands`。

随后由 Renderer Adapter 生成 `RenderScene`，最终冻结到 MapSpecLock。MapStyle 本身不直接输出 PDF 或 PNG。

---

## 16. 匹配不到 MapStyle 时的处理

### 16.1 参数差异位于允许范围内

继续使用现有 Style，应用并记录受限实例覆盖。

### 16.2 缺少符号角色或兼容色带

不能静默用相似符号替代。应：

1. 选择其他兼容 Style；
2. 发布现有 Style 的新版本；
3. 创建完整的派生 Style。

### 16.3 超出平台能力

如果需求需要未注册渲染能力、动态代码或平台禁止的表达方式，应返回能力不可用，不能通过临时创建 Style 绕过安全边界。

### 16.4 模板创建流程

目标流程应为：

```text
需求分析
  → Style Brief
  → 人工审批
  → 编写完整机器契约和 Design Spec
  → Schema 与语义检查
  → 标准符合性检查
  → Fixture 渲染
  → 发布审批
  → 写入不可变模板仓库和权威索引
```

模板创建和地图生成必须使用不同 Run。新 Style 发布后，地图生成 Run 再精确引用其版本和摘要。

---

## 17. 当前仓库状态

基线于 2026-11-18 静态核对，2026-11-19 补充页级绑定、颜色来源与文档边界核对；不表示本机或真实业务验收完成，也未重跑旧稿的变异实验。**所有权与权威源以[表达与符号设计结论 §11 单表](map-expression-and-symbol-design.md#11-所有权与权威源单表)为准，`rules` 可执行性以其 §12 为准**；本节不重复定义所有权。

- v1 Scenario 内嵌 cartography，所有权组件保留 map-style → cartography 整段替换；段引用协议（S2）已接入 validate/publish/generate 三个边界，但**独立 Style 创建路由仍未开放**。
- [cartography Schema](../../skills/carto-agent/schemas/cartography.schema.json) 现有 visual_language、symbolization、labeling（含可选 halo）、generalization、defaults、**typography（required）**、rules。
- 已核对的直接外观消费包括 `typography`（appearance.py → static_page_renderer.py）与 `labeling.halo`（page_renderer.py，仅矢量要素注记）。旧稿对 `visual_language`、`symbolization.*`、`labeling.{density,collision_policy,font_role}`、`generalization.*`、`defaults.*` 记录过 pixel-identical，且部分字段用于只读匹配；本轮没有重跑该实验，不以这些记录证明所有输入下都无作用。`rules` 另有 map_candidate.py 的必需 value 门禁，但它不等于逐条解析 path 并验证声明语义，也不能归为“只用于评分”。当前具体执行状态须按消费者和触发用例判断，见 §14.7 与共同 §12。
- `symbol_catalogs` 引用的 11 个 ref（如 `maps/admin@1.0.0`、`ramps/dem@1.0.0`）**全仓无实体注册表**；分类栅格可从 CSV 颜色列或澄清答案取得颜色，缺色且显式选择相应 palette 时才按 `order` 从代码常量 `PALETTE` 兜底（raster_portrayal.py:83-88,122-134）；连续色带来自请求 `color_ramp.colors`。不能把兜底路径说成唯一颜色来源。本文 §8.2 的 `ramps`（内联 hex + 感知类型 + provenance）为目标设计，尚未落地。
- **§8.2 的“可校验声明”部分已落地（2026-11-18，配色红线）**：generate 链在色值冻结前检查顺序色带 L* 单调、分歧色带亮心中点（CIE 15 CIELAB）、相邻类 ΔE76 可区分与二色觉模拟（Machado 2009）后可区分；离散类别色查后两条。参数与执行级别在 `policies/color-redlines-policy.yaml`（pending-business-review；色觉安全首期警告），实现在 `carto_core/color_science.py` 与 `compiler/color_checks.py`，接线于 raster_preparation（连续）与 raster/vector portrayal（离散）。ramps 资产协议本体（内联 hex + provenance 的 Style 色带）仍未落地；WCAG 对比度公式已就绪但未接线（契约尚未声明文字/背景色对）。
- [表达目录](../../skills/carto-agent/policies/map-expression-catalog.yaml) 共 7 条：active 为 `categorical@2.0.0`、`graduated-color@2.0.0`、`proportional-symbol@2.0.0`；`choropleth/sequential`、`proportional-symbol/count`、`raster/categorical`、`vector/explicit` 均已 deprecated 并带 `superseded_by`。不应再把旧洪涝量化分级或半径计算描述为当前业务实现。
- 分类栅格已有冻结类别表、图例、字体及整页渲染检查（[raster_portrayal.py](../../skills/carto-agent/scripts/carto_core/compiler/raster_portrayal.py)）；矢量路径已经 encoding-IR 承载点/线/面符号与注记，登记为受限工程能力。这不代表通用图表或独立 Style 管线已完成。
- **概念删除已执行**（详见[表达与符号设计结论 §15.2](map-expression-and-symbol-design.md#152-概念删除登记)）：本文已删除 `visual_language`、`tokens`、`symbol_definitions`、`portrayal_profiles`、`text_styles`、`layer_order`、`legend`、`scale_behavior` 八个顶层概念，以及 `labeling.{density,collision_policy,font_role}`、`symbolization.*`、`generalization.*`、`defaults.*`。原三处所有权冲突（scale_behavior、missing_value 词表、parameter_constraints）已随概念删除而消失，不再待收敛。
- **词表已单源化**：几何用 IR `geometry_role`（删除 `point/anchor`）；测量层次用 IR `measurement`（删除 `semantic_types`）；缺失值策略用 IR `missing.policy ∈ {reject,symbol}`（废弃 `explicit-symbol`）；颜色统一大写 hex。
- 当前执行权威：图层顺序为 `portrayal.layers[].z_order` 与**数组声明顺序**（page_renderer.py:340-342）；尺度分段归 `spatial-behavior.scale_bands`（但**尚无消费点**）；符号尺寸与线宽归 IR `channels.symbols[]`。

目标演进顺序：先解决分类颜色早于 Style 读取而冻结的阶段障碍，再演进来源与引用协议、接通 Style 色带到 IR 的唯一来源链；由 `symbol_roles` 提供受约束外观，在现有候选/执行快照中记录实例配置，再按实际需要开放独立创建与组合。准备请求前传入带来源绑定的样式选择，或后移颜色赋值，均需协议、消费者、合法/非法样例和测试同步，不能称为“搬一个常量、无需新协议”。具体取舍见共同单表 §11.2。**实例外观产物使用已有的 `resolved-appearance`，不另定 Schema、不增加第二套实例锁**。

请求给色仍可追溯本次实例：`raster_preparation.py` 保存请求、请求摘要和 encoding；缺少的是模板级 Style 来源与复用治理，不等于完全无法审计。输入边界接受小写后归一化、冻结产物严格大写，是明确的规范化流程，不是两套颜色语义。Style 作者声明与编译后的 IR 可以都包含色值，只要来源唯一且不能分别独立修改，不构成双重权威。页级绑定与嵌套内容的目标范围见 §10.3。固定业务或标准颜色属于必须保留的语义约束，不是可任意更换的皮肤。组件替换、声明参数和作用域调整分别验证；超出接口的变更需新模板/版本，精确引用、不可变发布与审批不变。

---

## 18. 设计原则总结

MapStyle 应遵循以下原则：

1. **表达抽象语义，不绑定业务列名。**
2. **拥有视觉规则，不拥有业务、版面和交付属性。**
3. **允许选择符号角色子集，不要求使用全部符号。**
4. **默认值、允许范围和实例结果必须区分。**
5. **Design Spec 解释原因，机器契约定义精确行为。**
6. **制图标准约束 Style，Style 不复制或替代标准。**
7. **结构变更通过模板版本演进；声明式参数与限定作用域的调整须显式验证，不进行任意深层合并。**
8. **所有覆盖均显式声明、校验并记录来源。**
9. **渲染器专用表达由 Adapter 生成。**
10. **最终实例外观进入 `resolved-appearance`，表达结果进入 `resolved-portrayal`，排版结果进入 `resolved-layout`，并统一由 MapSpecLock 冻结。**

最终职责链可以概括为：

```text
MapScenario：表达什么
地图表达规则与定义：适用条件、编码语义、常用预设和验证要求
模型规划与图面设计：选择或组合本次方案，在验证反馈中修订
MapStyle：兼容的视觉配置
受信方法：表达计算与通用绘图
符号资源：图形与可调参数边界
MapLayout：内容放在哪里
制图标准：必须满足哪些规范
resolved-appearance / resolved-portrayal / resolved-layout：本次实例最终采用什么
RenderScene：渲染器如何执行
```
