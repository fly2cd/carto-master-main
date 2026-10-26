# MapStyle 完整说明

## 1. 文档定位

本文定义 Carto Agent 模板体系中 MapStyle 的概念、作用、职责边界、内容结构、组合接口、兼容规则、发布产物和实例编译结果。

本文面向：

- 地图模板设计者；
- 制图规范维护者；
- MapScenario、MapBrand、MapLayout 的作者；
- 模板编译器和校验器开发者；
- 模板审核与发布人员。

本文属于设计说明。运行时机器协议仍应由 `skills/carto-agent/schemas/`、`policies/`、权威模板索引和已发布模板包定义。

除第 17 节“当前仓库状态”外，文中的扩展结构、接口和流程均为目标设计，不表示当前 CLI 已支持这些输入。

表达目录、内置方法、图表与符号资源的共同边界，以[地图表达目录、内置方法与符号库设计结论](map-expression-and-symbol-design.md)为准：表达规则约束数据与视觉含义；Scenario／任务规定目标；模型设计本次方案；MapStyle 提供兼容视觉配置；受信代码执行，验证反馈用于修订。地图表达目录统一称 Map Expression Catalog，预设不穷举所有合法组合。

---

## 2. 基本介绍

MapStyle 是一套可复用、版本化、可校验的**制图表达规范**。它在表达定义、Scenario 业务约束及适用标准范围内，通过 Profile 引用表达方法并配置视觉表现，例如：

- 有序数值如何映射到颜色；
- 数量如何映射到点符号面积；
- 分类对象如何使用不同符号；
- 地名如何设置视觉层级；
- 图层之间如何确定相对顺序；
- 无数据和异常值如何表达；
- 图例如何从实际表达结果生成；
- 哪些样式参数可以调整，哪些不可调整。

MapStyle 回答的是：

> 某种几何和语义的数据应该怎么画？

MapStyle 不回答：

- 当前业务要画什么；
- 数据文件在哪里；
- 业务字段叫什么；
- 页面是 A3 还是 A4；
- 地图框和图例框放在哪里；
- 机构 Logo 和具体品牌字体是什么；
- 最终输出 PDF 还是 PNG；
- 交付给谁、保存到哪里。

这些内容分别属于 MapScenario、项目数据绑定、MapLayout、MapBrand 和 Delivery Target Profile。

---

## 3. MapStyle 的作用

### 3.1 统一视觉表达

MapStyle 将颜色、符号、注记和图例规则集中管理，避免同类地图在不同项目中采用互相矛盾的表达方式。

例如，使用同一版本 `sequential-area` Profile 的地图采用相同的顺序色带方向和无数据外观；无数据含义及图例必须满足的规则来自其引用的表达定义和 Scenario 约束。

### 3.2 解耦业务与视觉设计

目标设计中，MapScenario 通过业务角色与 Profile 的绑定表达视觉需求，例如：

```yaml
portrayal_bindings:
  - data_role: thematic-area
    value_role: ordered-value
    style_profile: sequential-area
```

该绑定无需复制 `sequential-area` 的颜色、透明度或线宽。MapStyle 提供具体视觉配置，但 Scenario 仍拥有表达选择与业务约束；若 Scenario 已固定表达引用，所选 Profile 必须与之兼容。当前 v1 的 portrayal 仍持有符号、分类和缩放等字段，迁移时必须明确唯一来源，不能同时维持两套执行定义。

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
- 选择了哪些 Profile；
- 应用了哪些受限覆盖；
- 受哪些制图标准约束；
- 每个最终值来自 Style、Brand、Scenario、标准还是实例计算。

---

## 4. 与其他模板的区别和联系

| 组件 | 核心问题 | 主要内容 |
|---|---|---|
| MapScenario | 画什么、为什么画 | 业务任务、数据角色、语义绑定、空间规则、用途限制、交付和质量要求 |
| MapBrand | 地图属于谁 | 机构名称、Logo、品牌色、字体资源和署名格式 |
| MapStyle | 地图内容怎么表达 | 色带、符号、注记、图层层级、图例和尺度行为 |
| MapLayout | 地图元素放在哪里 | 画布、Frame、边距、占位符、容量和溢出策略 |
| 地图表达目录 / Map Expression Catalog | 方法适用什么、如何表达与验证 | 输入语义、参数约束、编码、图例与检查要求 |
| 内置表达方法与图表核心 | 如何执行计算和绘图 | 受信算法、数据到图形计算及可复用图表绘制 |
| 符号库 / Symbol Catalog | 使用什么图形资源 | 资源、锚点、可调通道和使用约束 |
| Delivery Profile | 以什么形式输出 | 格式、分辨率、色彩模式、文件要求和交付约束 |

推荐组合关系：

```text
MapScenario ──定义业务语义和所需 Profile──────────┐
MapStyle ─────提供表达 Profile 和视觉规则─────────┤
MapBrand ─────提供字体、Logo 和品牌资源────────────┼─→ ResolvedCartography
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

MapStyle 适合包含：

- 视觉语言与设计原则；
- 颜色、色带、透明度、线宽、点尺寸等 Design Token；
- 面、线、点、文本等符号的使用配置，引用公共资源或受支持的简单图形；
- 表达 Profile；
- 支持的几何类型和抽象语义类型；
- 已注册分类、分级和比例缩放方法的引用及允许的参数默认；
- 参数默认值及允许范围；
- 表达定义与业务约束允许的无数据和异常值视觉配置；
- 注记视觉层级、碰撞和省略原则；
- 图层相对顺序；
- 图例外观及实际映射结果的呈现配置；
- 与比例尺相关的视觉变化；
- 对 Brand、Layout 和 Renderer 的能力要求；
- 制图标准引用；
- 覆盖、扩展和派生策略；
- Style 级 Fixture 和质量门禁。

### 5.2 不应包含的内容

MapStyle 不应拥有：

- `risk-area`、`shelter-point` 等具体业务数据角色；
- `risk_pct`、`capacity` 等源字段名；
- 数据文件路径、坐标和业务数据行；
- 当前地图实际计算出的分类断点；
- 实际最大值、最小值和图例标签；
- A3、A4、420×297 mm 等页面定义；
- Frame 的位置和大小；
- PDF、PNG、DPI 等输出参数；
- Logo、机构名称和具体品牌字体文件；
- CRS 转换、数据准备流程和表达算法的可执行代码；
- 交付目录、接收方和幂等键；
- 审批密钥、审批消费和发布事务；
- MapLibre `paint`、`layout` 等渲染器专用表达式；
- 生产能力、安全边界或公网发布声明。

### 5.3 可以引用但不能重新定义的内容

MapStyle 可以声明：

- 已与 `a3-landscape@1.0.0` 完成兼容性验证；
- 需要 `legend-container`；
- 需要 Brand 提供 `body-font`；
- 需要 Renderer 支持 `text-halo`；
- 受 `cn-place-name-standard@1.0.0` 约束。

但不能在自身重新定义：

- A3 的尺寸和方向；
- 图例框坐标；
- Brand 字体文件；
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
- Token；
- 符号通道；
- Profile；
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
### 7.2 MapBrand
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
- 同一语义角色在不同 Profile 中保持视觉一致；
- 颜色不是唯一的区分手段；
- 无数据必须与零值、背景和最低等级区分。

### 7.4 表达能力清单

列出 Style 对外提供的稳定 Profile：

| Profile | 几何要求 | 输入语义 | 表达目的 |
|---|---|---|---|
| `sequential-area` | polygon | ordered numeric | 顺序型面分级 |
| `diverging-area` | polygon | signed numeric | 围绕中心值表达偏离 |
| `proportional-point` | point | nonnegative count | 数量型比例点 |
| `categorical-line` | line | category | 分类线状表达 |
| `hierarchical-place-label` | point/anchor | place hierarchy | 分级地名注记 |

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
- Brand 字体角色；
- 颜色和光晕原则；
- 避让、优先和省略原则；
- 多语言策略；
- 注记与专题符号的优先关系。

图例部分应说明：

- 图例从哪些 Profile 和实例结果生成；
- 分类、比例和定性符号如何展示；
- 无数据如何表达；
- 单位和数值格式原则；
- Layout 容量不足时如何处理。

图例必须从 `ResolvedCartography` 的实际结果生成，不能使用模板默认断点冒充实例结果。

### 7.7 外部模板接口

对 MapScenario，声明可接受的抽象语义和几何；对 MapBrand，声明字体等资源角色；对 MapLayout，声明容器能力；对 Renderer，声明抽象渲染能力。

```yaml
accepts:
  semantic_roles: [ordered-numeric, nonnegative-count]
  geometry_types: [point, line, polygon]

requires:
  brand_roles: [body-font, heading-font]
  layout_capabilities: [map-container, legend-container]
  renderer_capabilities: [fill-symbol, proportional-circle, text-halo]
```

### 7.8 标准与兼容性

建议记录：

- 适用媒介；
- 支持语言；
- 已验证比例尺范围；
- 支持的色彩模式；
- 制图标准引用；
- 已验证的 Brand、Layout 和 Renderer 组合；
- 尚未验证的组合。

“与 A3 Layout 完成验证”属于兼容证据，不表示 MapStyle 定义了 A3。

### 7.9 覆盖、扩展与派生

明确每类变化是否允许：

| 变化类型 | 推荐策略 |
|---|---|
| Profile 子集选择 | 允许 |
| 分类数 | 约束范围内允许 |
| 透明度 | 约束范围内允许 |
| 色带方向 | 默认禁止 |
| 专题颜色被 Brand 覆盖 | 默认禁止 |
| 字体文件 | 由 Brand 角色解析 |
| 新增 Profile | 创建新版本或派生 Style |
| 渲染器私有表达式 | 禁止实例直接提供 |

### 7.10 验证、限制与追溯

记录 Style 自身的验证条件、表达限制和设计概念到机器契约路径的映射。

Style 限制示例：

```markdown
- 不提供流向符号；
- 不提供三维表达；
- 不支持双变量面填充；
- 当前地名 Profile 只验证了中文环境；
- 色带尚未针对深色背景验证。
```

追溯表示例：

| 设计概念 | 机器契约路径 |
|---|---|
| Design Token | `/tokens` |
| 符号定义 | `/symbol_definitions` |
| 表达能力 | `/portrayal_profiles` |
| 注记 | `/text_styles` |
| 图例 | `/legend` |
| 覆盖规则 | `/extension_policy` |

---

## 8. 机器契约推荐结构

建议将 MapStyle 机器契约组织为四个核心层级：

```text
tokens
  → symbol_definitions
    → portrayal_profiles
      → labeling / legend / scale policies
```

### 8.1 顶层结构

```yaml
schema_version: 1
style_id: technical-thematic
version: 1.0.0
title: 技术型专题制图风格

visual_language: {...}
tokens: {...}
symbol_definitions: [...]
portrayal_profiles: [...]
text_styles: [...]
layer_order: {...}
legend: {...}
scale_behavior: [...]
standard_refs: [...]
compatibility: {...}
extension_policy: {...}
rules: [...]
```

### 8.2 Design Token

Token 用于保存稳定、可复用的视觉常量和角色：

```yaml
tokens:
  colors:
    background: "#F8FAFC"
    boundary: "#475569"
    accent: "#087E8B"
    no_data: "#D1D5DB"

  color_ramps:
    sequential-main:
      type: sequential
      color_space: lab
      values:
        - "#FFF7BC"
        - "#FEC44F"
        - "#FE9929"
        - "#CC4C02"
        - "#7F0000"

  dimensions:
    boundary-width: {value: 0.2, unit: mm}
    point-min-size: {value: 2, unit: mm}
    point-max-size: {value: 12, unit: mm}

  opacities:
    thematic-fill: 0.82
```

所有长度必须携带单位。Token 不应包含页面尺寸、Frame 坐标或实例统计值。

### 8.3 符号定义

这里的 `symbol_definitions` 是 Style 内的符号使用配置，不是另一套公共符号库。它可以引用库中资源并指定获准参数，也可以组合渲染器支持的简单图形；公共资源的原始图形、锚点和使用限制仍由符号资源拥有。数据字段到大小、颜色或方向的计算由受信表达方法执行。

以下示例描述视觉通道，不绑定具体业务数据角色。正式协议需要明确尺寸表示直径、半径还是面积，以及从表达输出到绘制参数的换算；示意中的 `size` 不应被实现为不加区分的线性缩放：

```yaml
symbol_definitions:
  - symbol_id: sequential-area-fill
    symbol_type: fill
    geometry_types: [polygon, multipolygon]
    channels:
      fill_color:
        source: expression-output
        visual_variable: fill-color
        color_ramp_ref: sequential-main
      fill_opacity:
        token_ref: opacities.thematic-fill
      outline_color:
        token_ref: colors.boundary
      outline_width:
        token_ref: dimensions.boundary-width

  - symbol_id: proportional-circle
    symbol_type: marker
    geometry_types: [point]
    primitive: circle
    channels:
      fill_color:
        token_ref: colors.accent
      size:
        source: expression-output
        visual_variable: symbol-area
        minimum_ref: dimensions.point-min-size
        maximum_ref: dimensions.point-max-size
```

### 8.4 Portrayal Profile

Profile 将抽象语义、表达定义的精确引用和符号使用配置组合为可检验的视觉配置；它不包含算法实现，也不因为声明了 Profile 就增加平台能力：

```yaml
portrayal_profiles:
  - profile_id: sequential-area
    expression_ref:
      id: choropleth/sequential
      version: 1.0.0
      digest: "sha256:..."
    symbol_ref: sequential-area-fill
    accepts:
      geometry_types: [polygon, multipolygon]
      semantic_types: [ordered-numeric]
    parameter_defaults:
      classification_method: quantile
      class_count: 5
    parameter_constraints:
      classification_method:
        allowed: [equal-interval, quantile, jenks, manual]
      class_count:
        minimum: 3
        maximum: 7
    missing_value:
      policy: explicit-symbol
      color_ref: colors.no_data
```

Profile 可以定义默认值并收窄表达允许的参数范围，但不能放宽表达适用条件、改变数量映射语义或保存某次数据计算出的分类断点。表达定义、Scenario、Style 和执行环境的约束必须同时满足；若 Scenario 已固定表达而 Profile 引用了不同方法，应报告不兼容。

目录规定允许的参数，Profile 选择兼容默认值，两者有不同职责；不要在 Style 再维护一套独立算法或完整表达规则。示例中列出多种分类方法是目标配置，当前固定洪涝规划仍只接受 quantile。

#### 表达设计与 Profile 的关系

Profile 提供可复用视觉配置，不要求为每次图形组合新增一份 Style。若实例采用未预先命名的组合，应在 Style 明确开放的范围内使用兼容配置，且由计划和表达规则拥有数据映射；不能绕过所选 Style 对新增 Profile 的限制及分段替换规则，把新增 Profile 伪装成参数调整。若现有 Style 不适配，按现有派生、替换或方案修订流程处理。

“行业用蓝色还是紫色”可以是外观配置；“颜色表示行业还是产值高低”改变编码含义。柱状图切换为饼图还涉及分母和比较方式，须由规划重新确定方案并验证。默认推荐与硬约束沿用既有规则语义，不因某预设常用就禁止所有兼容替代方案。

表达方案和通用组合能力仍须正式协议支持，本文不新增 Profile 字段、任意脚本或运行时组合入口。

### 8.5 注记规则

```yaml
text_styles:
  - style_id: place-name-primary
    semantic_type: place-name
    font:
      role_ref: brand.body-font
      weight: 600
    size:
      default: 12
      minimum: 10
      maximum: 14
      unit: pt
    color_token: label-primary
    halo:
      color_token: label-halo
      width:
        default: 0.5
        minimum: 0.3
        maximum: 0.8
        unit: mm
    priority: 90
```

实际字体文件由 MapBrand 解析。强制字号范围可以由制图标准进一步约束。

### 8.6 相对图层顺序

Style 应优先表达相对关系，而不是直接保存渲染器 `z_index`：

```yaml
layer_order:
  constraints:
    - {before: background, after: thematic-area}
    - {before: thematic-area, after: thematic-point}
    - {before: thematic-point, after: labels}
```

编译器在 `ResolvedCartography` 中生成具体顺序值。

### 8.7 兼容性与扩展策略

```yaml
compatibility:
  semantic_types: [ordered-numeric, nonnegative-count, category]
  geometry_types: [point, line, polygon, multipolygon]
  media: [print, screen]
  locales: [zh-CN]
  required_brand_roles: [body-font]
  required_layout_capabilities: [map-container, legend-container]
  required_renderer_capabilities: [fill-symbol, proportional-circle, text-halo]

extension_policy:
  profile_selection: subset-allowed
  parameter_overrides: constrained
  token_overrides: forbidden
  additional_profiles: derived-style-required
  renderer_specific_properties: forbidden
  missing_required_profile: reject
```

---

### 8.8 图表配置与放置

目标设计允许 Style 为通用柱状图、饼图、折线图提供颜色、字体、线条和图例外观。若场景已有独立图表定义，应复用其通用图表部分，不为地图再复制一套绘图算法。

图表核心根据数据与配置生成局部坐标图形及测量边界。地图内使用由表达与空间编译增加地理锚定、跨要素尺度协调和避让；独立辅助图使用 Layout Frame 进行页面放置，无需强制引用地图表达目录。统计范围、Top K 与单位由 Scenario/任务和数据准备决定，不能由 Style 美化过程改写。

固定柱状图或饼图图标属于符号资源；根据数据变化的柱高或扇区需要受信图表计算。这些是复用边界，不表示当前已经存在通用 chart 协议或独立图表模板类型。

图表核心可以提供成熟预设，也可以通过已支持的图形、尺度和分组能力组合方案，不需要穷举所有完整绘图函数。代码可由模型辅助开发，但 Style 只引用可用能力和配置，不携带实现。输入输出之外的语义、特殊情况及独立验证要求，见[绘图接口契约](map-expression-and-symbol-design.md#91-绘图接口不仅约定输入输出结构)；每次制图动态执行模型代码仍未开放。

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
| 机构提供的具体字体文件 | MapBrand |
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
- Style 拥有视觉配置，Brand 拥有身份资源及其使用限制，双方各自的硬约束不能互相覆盖；
- 实例只能调整明确开放的参数，并记录来源；默认值被替换后仍须通过全部适用约束；
- 外部 Style 替换 Scenario 内嵌 cartography 时，须满足可替换声明并采用完整段替换。

任一硬约束无法满足都应报告冲突，返回相应所有者修订。六种规则标签用于区分约束性质，不表示数值优先级。

---

## 10. 与其他组件的接口

### 10.1 MapScenario 接口

MapScenario 声明业务数据角色、值语义和所需 Style Profile：

```yaml
portrayal_bindings:
  - data_role: indicator-area
    value_role: indicator-value
    semantic_type: ordered-numeric
    style_profile: sequential-area
```

MapStyle 声明 Profile 可以接受的几何和语义：

```yaml
provides:
  style_profiles: [sequential-area]

accepts:
  geometry_types: [polygon, multipolygon]
  semantic_types: [ordered-numeric]
```

### 10.2 MapBrand 接口

MapStyle 使用字体或颜色角色，MapBrand 提供实际资源：

```yaml
# MapStyle
requires:
  brand_roles: [body-font, heading-font]

# MapBrand
provides:
  brand_roles: [body-font, heading-font, organization-name]
```

Style 应说明哪些专题 Token 禁止 Brand 覆盖，哪些文本 Token 允许受限替换。

### 10.3 MapLayout 接口

MapStyle 提出容器和容量需求：

```yaml
requires:
  layout_capabilities: [map-container, legend-container]
```

MapLayout 提供 Frame 和容量：

```yaml
provides:
  layout_capabilities: [map-container, legend-container]

capacity:
  legend_items: 12
```

Style 不定义纸张大小和 Frame 坐标。

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
Scenario.required_style_profiles
    ⊆ MapStyle.provided_style_profiles
```

Style 可以包含本次未使用的 Profile。编译器只选择实际需要的部分，其余定义不进入地图实例。

建议使用三种结果：

| 状态 | 含义 | 处理方式 |
|---|---|---|
| `compatible` | 完整覆盖需求 | 直接选择所需 Profile |
| `compatible_with_declared_overrides` | 差异位于允许范围内 | 应用并记录受限覆盖 |
| `incompatible` | 缺少能力或违反标准 | 更换、升级或派生 Style |

硬性检查至少包括：

- Profile 是否存在；
- 几何类型是否兼容；
- 语义类型是否兼容；
- 制图标准是否满足；
- Brand 角色是否齐全；
- Layout 容量是否足够；
- Renderer 是否支持所需能力；
- 媒介、语言和尺度范围是否适用；
- 依赖版本和摘要是否精确匹配。

只有通过硬性检查的候选才可以进一步评分或排序。

---

## 12. 覆盖、版本和派生

### 12.1 实例覆盖

实例只能修改 Style 明确允许的参数：

```yaml
allowed_overrides:
  class_count:
    minimum: 3
    maximum: 7
  opacity:
    minimum: 0.6
    maximum: 0.9
```

最终解析结果必须记录基础值和覆盖值：

```yaml
style_resolution:
  base_style_ref:
    id: technical-thematic
    version: 1.0.0
    digest: "sha256:..."
  selected_profiles: [sequential-area]
  overrides:
    sequential-area:
      class_count:
        original: 5
        resolved: 6
```

实例覆盖不能修改已发布模板文件。

### 12.2 新版本

以下变化通常要求发布新版本：

- 修改固定 Token；
- 修改 Profile 的默认行为；
- 修改允许覆盖范围；
- 修改标准依赖；
- 修正符号或注记规则；
- 增加或废弃 Profile。

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

保存允许随模板发布的非敏感视觉资产。字体是否随 Style 发布应由授权策略决定；通常 Style 引用 Brand 字体角色，而不是复制机构字体文件。

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

- Profile 引用的符号存在；
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

- Brand 提供所需资源角色；
- Layout 提供所需容器和容量；
- Renderer 提供所需能力；
- Scenario 请求的 Profile 和语义受支持。

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

建议生成 `resolved-cartography.yaml`：

```yaml
style_ref: {...}
brand_ref: {...}
scenario_ref: {...}
standard_refs: [...]

selected_profiles:
  - sequential-area
  - proportional-point

resolved_tokens: {...}
resolved_layers: [...]
resolved_labels: [...]
resolved_legend: {...}
resolved_scale_behavior: [...]
resource_refs: [...]

provenance:
  place-name-primary:
    font_size:
      value: 12
      unit: pt
      source: map-style
      constrained_by:
        standard: cn-thematic-place-name@1.0.0
        rule: province-place-name

digest: "sha256:..."
```

该文件记录本次地图最终采用的表达结果，包括实际分类断点、最终图例、符号尺寸和所有覆盖来源。

随后由 Renderer Adapter 生成 `RenderScene`，最终冻结到 MapSpecLock。MapStyle 本身不直接输出 PDF 或 PNG。

---

## 16. 匹配不到 MapStyle 时的处理

### 16.1 参数差异位于允许范围内

继续使用现有 Style，应用并记录受限实例覆盖。

### 16.2 缺少 Profile

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

当前仓库已经具备：

- MapScenario 内嵌的 `cartography` 段；
- `map-style → cartography` 的完整段所有权映射；
- 只含 `choropleth/sequential`、`proportional-symbol/count` 的轻量地图表达目录；
- Schema、依赖锁和不可变发布基础；
- 候选、RenderScene 和 MapSpecLock 管线。

但当前独立 MapStyle 业务创建路由尚未开放。现有 `cartography` Schema 主要包含：

- `visual_language`；
- `symbolization`；
- `labeling`；
- `generalization`；
- `defaults`；
- `rules`。

目前分类、比例符号、图层顺序和无数据规则主要仍位于 MapScenario 的 `portrayal` 契约；部分颜色和符号参数由候选编译器生成。因此当前 MapStyle 还是较薄的视觉摘要，而不是本文目标结构下完整、可独立发布和匹配的模板。

当前目录声明面积比例符号，但候选编译器实际按数值线性调整半径；通用符号资源实例化和图表核心也尚未贯通。具体依据与待修正事项见[设计结论文档第 10 节](map-expression-and-symbol-design.md#10-当前仓库状态与设计差距)。这些不能列为当前 Style 已经准确实现的能力。

建议演进方向：

1. 扩展 `cartography` Schema；
2. 将符号使用配置和注记视觉规则收敛到 MapStyle，表达语义继续由表达定义拥有、算法由受信代码实现；
3. 将 Scenario 的 `portrayal` 收敛为业务语义、表达/Profile 绑定及不能被外观覆盖的约束，明确旧字段迁移；
4. 增加 `resolved-cartography` 协议；
5. 增加制图标准注册和符合性检查；
6. 增加独立 MapStyle 创建、验证和发布流程；
7. 增加基于 `requires/provides` 的匹配报告；
8. 保留精确版本、摘要、完整段替换和不可变发布原则。

---

## 18. 设计原则总结

MapStyle 应遵循以下原则：

1. **表达抽象语义，不绑定业务列名。**
2. **拥有视觉规则，不拥有业务、版面和交付属性。**
3. **允许选择 Profile 子集，不要求使用全部符号。**
4. **默认值、允许范围和实例结果必须区分。**
5. **Design Spec 解释原因，机器契约定义精确行为。**
6. **制图标准约束 Style，Style 不复制或替代标准。**
7. **通过完整模板版本演进，不进行运行时字段级拼接。**
8. **所有覆盖均显式声明、校验并记录来源。**
9. **渲染器专用表达由 Adapter 生成。**
10. **最终实例表达进入 ResolvedCartography 和 MapSpecLock。**

最终职责链可以概括为：

```text
MapScenario：表达什么
地图表达规则与定义：适用条件、编码语义、常用预设和验证要求
模型规划与图面设计：选择或组合本次方案，在验证反馈中修订
MapStyle：兼容的视觉配置
受信方法：表达计算与通用绘图
符号资源：图形与可调参数边界
MapBrand：使用谁的视觉身份
MapLayout：内容放在哪里
制图标准：必须满足哪些规范
ResolvedCartography：本次实例最终采用什么
RenderScene：渲染器如何执行
```
