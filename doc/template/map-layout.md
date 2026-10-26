# MapLayout 完整说明

## 1. 文档定位

本文介绍 Carto Agent 模板体系中 MapLayout 的基本概念、作用、职责边界、内容结构、组合接口、适配方式、验证要求和输出产物。

组织方式参考 [MapStyle 完整说明](map-style.md)，设计依据为 [模板体系设计](../carto-template-dsg.md)，表达、符号与图表复用的统一边界见 [地图表达与符号设计结论](map-expression-and-symbol-design.md)。两份专题文档分别说明制图表达规范与版面组织，供模板作者、业务方案设计者、编译器开发者和审核人员使用。

本文是设计说明。除第 18 节“当前仓库状态”外，新增字段、匹配状态、编译产物和处理流程均为建议设计；示例不代表当前 CLI 已支持的输入格式。运行时协议仍以 `skills/carto-agent/schemas/`、`policies/` 和已发布模板为准。

## 2. 基本介绍

MapLayout 是可复用、版本化、可校验的地图版式模板。它规定画布以及地图、标题、图例、署名等内容在画布中的空间组织方式。

MapLayout 回答：

> 哪些区域可以承载哪些内容，各区域有多大、放在哪里，内容超出空间时如何处理？

典型内容包括纸张尺寸、版面方向、安全边距、地图框、标题框、图例框、对齐方式、容器内间距、容量约束和溢出处理顺序。

一个 `a3-landscape-sidebar` Layout 可以明确规定：画布为 420×297 mm，主地图位于左侧，图例位于右侧，标题位于顶部，来源信息位于底部。人口、经济、资源或应急等 Scenario 都可以使用这个版式，只要所需内容及其尺寸能够被容纳。

MapLayout 的固定尺寸是其合法设计内容。复用的基础是稳定的内容接口和明确的适用条件，不要求所有尺寸都变成可变参数。

## 3. MapLayout 的作用

### 3.1 复用成熟的版面结构

将可重复使用的阅读顺序、空间比例、对齐关系和留白集中管理，使不同地图使用同一套版面组织。

### 3.2 将空间组织与内容表达分开

MapStyle 决定图例的字体、色块和符号外观；MapLayout 决定图例容器的位置、宽高、列数和内边距。更换色带通常不需要修改 Layout，更换纸张方向也不应直接修改专题符号语义。

### 3.3 在渲染前发现容量问题

实际标题、图例标签、字体和 Logo 尺寸进入后，可以提前检测越界、遮挡、文字截断、必需内容缺失等问题。

### 3.4 提供受控的适配空间

模板可以允许图例换列、标题换行或选用已定义变体。编译器按固定顺序尝试这些选项，并记录最终选择及其原因。

### 3.5 形成可追溯的排版结果

最终结果能够回答：使用了哪个 Layout 版本，内容绑定到了哪个 Frame，为什么使用两列图例，以及每个元素的最终边界来自哪个约束。

## 4. 与其他组件的区别和联系

| 组件 | 定义的内容 | 提供给 Layout 的信息 |
|---|---|---|
| MapScenario | 业务内容、数据角色、地图视图、必需元素、用途限制 | 需要哪些内容角色、各角色的实例内容与必需性 |
| MapStyle | 在表达、场景与标准约束内配置符号、色带、注记和图例外观 | 文本样式、图例样式、符号样式及允许调整范围 |
| MapBrand | Logo、字体资源、机构名称和品牌限制 | 已解析资产、字体和 Logo 安全留白等约束 |
| MapLayout | 画布、Frame、位置、对齐、容量和排版策略 | 可承载内容的空间以及最终排版结果 |
| 空间规划/地图编译 | CRS、视图范围、比例尺、相机和空间适用性 | 地图视图需求、范围适配结果、比例尺与方向计算结果 |
| Delivery Target | 输出格式、分辨率、输出处理要求 | 格式和栅格化参数，以及外部要求的页面条件 |
| 图表绘制核心 | 根据准备好的数据与样式生成局部坐标图形 | 图表图形、测量边界与尺度信息，不决定页面或地理位置 |
| Renderer | 文本测量、地图绘制、页面合成和导出 | 可用能力、测量结果、渲染证据 |

边界容易混淆的属性应按下表分配：

| 属性 | 定义与处理方式 |
|---|---|
| A3、420×297 mm、横向 | MapLayout 定义；若用户要求 A3，则作为选择 Layout 的条件 |
| 标题框位置、宽度、最大行数 | MapLayout 定义 |
| 标题文本 | Scenario/项目内容提供 |
| 标题颜色、字号默认值 | MapStyle 定义，标准可以施加约束 |
| 标题所用字体文件 | 通过 MapBrand 或已批准的字体角色解析 |
| 图例项及分类断点 | 地图实例编译结果提供 |
| 图例色块外观、符号样式 | MapStyle 在表达约束内配置；数据驱动的大小与地图实例实际映射一致 |
| 图例列数、列间距、容器内边距 | MapLayout 定义 |
| 是否必须出现比例尺、指北针、声明 | Scenario 或适用标准提出要求 |
| 比例尺容器、指北针位置 | MapLayout 定义 |
| 比例尺距离与指北针实际角度 | 地图编译器根据所绑定视图计算 |
| 地理要素注记的优先级与避让 | MapStyle 规定行为，注记引擎在地图视图中执行 |
| 页面元素之间的避让与不重叠约束 | MapLayout 定义 |
| PDF/PNG、144 DPI | Delivery Target 定义 |

Delivery 可以要求成果必须为 A3，Layout 提供实际满足该条件的画布。两者冲突时返回不兼容，不能在导出时悄悄缩放为另一种版面。

## 5. MapLayout 的职责边界

### 5.1 应包含的内容

- 画布尺寸、方向、逻辑单位和页面坐标约定；
- 安全边距、可用区域和必要的印刷出血约束；
- Frame 类型、标识、边界、锚点、对齐和嵌套关系；
- 内容角色、可接受的内容类型和数量约束；
- 标题换行、图例换列、Logo 适配等容器排版规则；
- 区域最小尺寸、间距和明确允许的重叠关系；
- 空间容量提示及实例测量要求；
- 可选区域的空缺处理；
- 溢出处理顺序和允许的版式变体；
- 对 Scenario、Style、Brand 和 Renderer 的能力要求；
- 版面标准引用、参数覆盖和派生规则。

### 5.2 不拥有的内容

业务字段名、真实数据路径、风险等级含义、专题色带、实际地名、最终分类断点、实际 Logo 文件、字体文件、业务声明文本、地理范围、CRS 转换算法、输出 DPI 和交付目的地均有外部所有者。

Layout 可以引用相应角色。例如 Footer Frame 接受 `required-notice` 文本，但不把“合成数据演示”作为每个地图都必须使用的固定文案。

### 5.3 可以固定哪些值

| 值的类别 | 示例 | 推荐处理 |
|---|---|---|
| 版面身份 | A3 横向、420×297 mm | 可以固定 |
| 基准几何 | 主地图框坐标、安全边距、列间距 | 可以固定，也可以参数化 |
| 有限适配范围 | 图例允许一列或两列 | 显式声明可选项及选择顺序 |
| 外部视觉属性 | 字号、色带、Logo 比例 | 引用 Style/Brand，遵守其约束 |
| 本次内容计算结果 | 图例实际行数、标题测量宽度 | 进入实例排版结果 |

“固定版式”与“可复用版式”并不冲突。A3 固定模板可以跨业务复用，但不应宣称可以无条件缩放为 A4、海报或手机界面。

## 6. 核心结构：Canvas、Frame、Slot 与约束

### 6.1 Canvas：版面坐标基础

Canvas 定义宽高、方向、单位和页面坐标。建议打印版面使用 mm，屏幕版面使用明确声明的逻辑 px，并说明它与设备像素的关系。

打印排版建议采用：原点在左上角，x 向右、y 向下；Frame 边界为 `x、y、width、height`。尺寸必须在契约中指定单位，不能把经纬度写成页面坐标。

安全边距限制内容可用区域。出血是印刷生产选项，需要 Delivery/设备共同支持，普通页面无需默认添加。

### 6.2 Frame：承载内容的空间容器

Frame 定义空间边界，不直接携带业务内容。常见类型包括：

| Frame 类型 | 用途 | 内容来源 |
|---|---|---|
| map | 主图、对比图 | Scenario 声明的地图视图 |
| inset | 区位图、局部详图 | Scenario 声明的关联视图 |
| title | 标题、副标题 | 项目内容 |
| legend | 图例 | 实例表达结果 |
| scale-bar | 比例尺 | 对应视图的计算结果 |
| north-arrow | 指北针 | 对应视图的方向结果 |
| logo | 品牌标识 | Brand 资产 |
| text | 来源、日期、声明等 | 项目内容或外部格式化结果 |
| chart（扩展建议） | 主图区附近独立展示的柱状图、饼图、折线图等 | Scenario/任务指定的数据内容，经图表核心生成 |
| table（扩展建议） | 统计表、指标说明表等 | Scenario/任务指定的数据内容，经表格组件生成 |

`logo`、通用 `text`、`chart`、`table` 等是扩展建议，当前 Schema 的 Frame 类型不全部包含这些项。`chart_panel`、`table_panel` 可以作为目标设计中的内容角色名称，不代表已实现相应 Frame 枚举或运行接口。

辅助图表的指标、数据范围、聚合与 Top K 规则由 Scenario/任务提供，图表核心负责局部坐标绘制和测量，Layout 负责页面容器及最终放置。独立辅助图表可以直接复用图表核心，无需先登记为地图表达。

同一绘图核心也可用于地图中的小图表；此时城市代表点、地理坐标到输出坐标的转换和地图内避让由空间规划、地图编译及相应放置逻辑处理。Layout 提供主地图框，不为每个城市创建一个页面 Frame。

### 6.3 Slot：可绑定的内容接口

Slot 表示“这里接受什么内容”。建议区分三个标识：

- Frame ID：例如 `right-panel`，用于引用空间容器；
- 内容角色：例如 `main-legend`，供 Scenario 与 Layout 对接；
- 具体内容 ID：例如某次地图生成的图例对象，由实例绑定提供。

同一个图例对象可以放进不同 Layout 的不同 Frame，因此不应要求所有模板使用相同 Frame ID。

Slot 可声明内容类型与最少/最多数量。其 `min_items: 1` 表示这个 Layout 的使用前提；业务上是否必须出现该内容，仍由 Scenario 和适用标准决定。选定后的组合必须同时满足双方要求。

### 6.4 约束：表达空间关系

建议支持固定边界和经过注册的约束算子，例如对齐、位于某区域内、相对间距、最小尺寸和不重叠。

不要在契约中使用任意可执行表达式。约束之间存在循环、相互矛盾或无法满足时，编译器应返回具体冲突。初期可以只实现固定 Frame，后续按需求增加约束能力。

### 6.5 可选区域与内容缺失

可选区域应声明缺失时保留空白、折叠还是采用其他已声明变体。必需内容缺失不能通过隐藏 Frame 解决。

可选区折叠后，如果会改变邻近地图框、图例或页脚的大小，必须重新求解和验证，不能只删除一个元素后沿用旧测量结果。

## 7. 容量、测量与溢出

### 7.1 容量数字是筛选提示

`legend_items: 12` 和 `title_characters: 40` 可以帮助快速筛选，但无法保证排版一定通过。相同数量的图例项可能具有不同的符号高度、长标签、单位和多行说明；相同字符数在不同字体中也有不同宽度。

建议将静态容量声明视为预检提示，并用解析后的真实字体、字号、符号尺寸和内容进行最终测量。若“12 项”是业务上限而不是空间估算，应另行明确为硬约束。

### 7.2 可用空间由内边距和排列共同决定

```text
内容区宽度 = Frame 宽度 − 左内边距 − 右内边距
每列可用宽度 = (内容区宽度 − 列间距总和) / 列数
```

图例总高度还应包含图例标题、组标题、各项实际行高、行间距和上下内边距。不能只用“项数 × 固定行高”覆盖所有图例。

### 7.3 不同内容需要不同溢出策略

| 内容 | 合理的处理顺序示例 | 不能自动采取的措施 |
|---|---|---|
| 标题 | 换行 → 已声明版式变体 → 返回不适配 | 截断核心标题、无限减小字号 |
| 图例 | 标签换行 → 已声明列数 → 其他版式 → 报告失败 | 删除类别、减少分类数、重写单位 |
| 辅助图表 | 在可读范围内调整尺寸与标签 → 已声明版式变体 → 报告失败 | 隐藏必需类别、改变单位、破坏要求共享的数值尺度 |
| Logo | 等比缩放到容器内并核验最小尺寸 | 拉伸、裁剪标志、忽略安全留白 |
| 来源和强制声明 | 换行 → 扩大已授权区域 → 报告失败 | 隐藏、截断或改写必需文本 |
| 地图内容 | 在已批准视图内裁剪渲染到地图框 | 裁掉业务要求覆盖的区域来适配页面 |

Layout 允许的文字缩小，还必须落在 Style、Brand 和适用标准共同允许的范围内。允许 `shrink` 不能成为绕过字号下限的理由。

### 7.4 分页需要额外能力

分页只有在 Layout 提供分页规则、Scenario 允许内容拆分、Delivery 允许多页成果且 Renderer 支持时才能执行。单页地图不能在图例放不下时自动变成多页文档。

如果不支持分页，应返回可解释的容量失败，供规划步骤重新选择 Layout 或修改已允许的参数。

## 8. 地图框的特殊行为

### 8.1 地图框大小会影响视图结果

MapLayout 定义地图框宽高和内边距。空间编译器依据地图框、业务地理范围和空间规则计算适配后的相机、比例尺与可见范围。

```text
Layout 的地图框尺寸 + Scenario 的范围/比例尺约束
    → 空间适配
    → 有效比例尺与视图
    → Style 尺度规则和注记测量
    → 页面容量验证
```

要求完整显示地理范围时，可以扩展视图留白以适配宽高比，但不能未经允许删除业务范围。若还要求固定比例尺，范围和地图框之间可能不可兼得，应报告冲突。

### 8.2 比例尺与方向必须绑定具体视图

主图、插图或对比图各自可能具有不同尺度、投影和方向。每个比例尺与指北针应显式绑定所服务的视图，避免用主图比例尺解释插图。

Layout 只安排它们的位置；长度标注和方向由空间/渲染组件根据对应视图计算。Layout 不能填写一个与实际地图无关的固定“10 km”。

### 8.3 允许的重叠应明确声明

把指北针放在地图框内属于有意重叠，需要声明包含关系或允许的覆盖区域。文字框意外遮盖图例则应判定为失败。

地图内留给附属元素的区域会减少可见空间，应参与地图视图和注记避让计算。页面层级与地图图层顺序是两套关系，分别由 Layout 和 Style 管理。

### 8.4 打印与屏幕版式

响应式断点、多视口、图集和多地图框是可扩展方向。一个固定打印 Layout 不因声明了 `web` 或 `mobile` 分类就具备这些能力；每个布局模式、输入条件和变体都需要相应实现与验证。

## 9. 双层文件与 Design Spec

与 MapStyle 一致，建议采用文字说明和机器契约两层：

```text
MapLayout
├── design_spec.md
└── contracts/layout.yaml
```

`design_spec.md` 说明设计意图、阅读顺序、空间分配理由、接口和适用范围。`layout.yaml` 保存可执行的边界、绑定约束和适配规则，是运行时的权威定义。

建议保留以下十部分：

| 章节 | 应说明的内容 |
|---|---|
| 1. 身份与设计目标 | Layout ID、版本、契约引用、预期阅读方式 |
| 2. 适用的版面问题 | 单主图、侧栏图例、多图对比等；适用与不适用条件 |
| 3. 阅读顺序与空间原则 | 主次关系、留白、对齐、地图与说明区的面积关系 |
| 4. 画布与坐标约定 | 页面规格、方向、单位、安全边距和已支持的变体 |
| 5. Frame 与内容接口 | 各区域用途、角色、内容类型、必需与可选条件 |
| 6. 排版与溢出策略 | 换行、换列、空缺处理、容量限制和有意重叠 |
| 7. 外部组件接口 | 对 Scenario、Style、Brand、空间编译和 Renderer 的要求 |
| 8. 标准与兼容性 | 版面约束来源、已验证组合及验证证据 |
| 9. 覆盖、变体与派生 | 可调参数、边界和何时需要另一个模板 |
| 10. 验证、限制与追溯 | 版面验证条件、已知限制与机器契约路径 |

不同于 Style 的 Design Spec，Layout 的 Design Spec 可以明确写“本版式为 A3 横向”。它拥有这个设计值，但文档中的尺寸表仍需与 `layout.yaml` 保持一致，最好由契约生成。

下面是一段设计说明示例：

```markdown
# A3 单主图侧栏版式

## 身份与目标

Layout ID：a3-landscape-sidebar；契约：contracts/layout.yaml。
用于一张主要地图和一组集中图例的横向阅读，主图位于左侧，解释信息位于右侧。

## 空间原则

标题横跨主图与侧栏，形成统一阅读入口。地图框与图例框分离，减少说明元素对地图的遮挡。
页脚分别承载来源与可选声明。缺少可选 Logo 时保留该区域空白。

## 接口与适配

接受主地图视图、标题和主图例；其他内容角色见机器契约。
图例尝试已声明的列数，并按实际字体和标签测量；无法容纳时返回不适配。

## 限制

当前版式为单页固定画布，不提供双主图和图例续页。
```

## 10. 机器契约建议与完整示例

### 10.1 顶层组成

推荐围绕以下结构设计：

```text
canvas → frames → content_slots
                  + constraints
                  + capacity_hints
                  + compatibility / extension_policy
```

固定版式可以只依赖明确的 Frame 边界。栅格、自动求解、分页和响应式变体可以按实际复用需求增加，不必一次引入。

### 10.2 A3 单主图侧栏版式示例

以下为拟议的下一版机器契约示例，`schema_version: 2` 仅用于与当前 v1 区分；它不是已注册协议，不能直接提交给现有 CLI。全部长度使用 `canvas.unit`，`content_slots` 中的 role 通过实例绑定获得具体内容。

```yaml
schema_version: 2
layout_id: a3-landscape-sidebar
version: 1.0.0
category: report

canvas:
  width: 420
  height: 297
  unit: mm
  orientation: landscape
  origin: top-left
  x_direction: right
  y_direction: down
  safe_margin:
    top: 10
    right: 10
    bottom: 10
    left: 10

content_slots:
  - {role: map-title, accepts: text, min_items: 1, max_items: 1}
  - {role: main-map, accepts: map-view, min_items: 1, max_items: 1}
  - {role: main-legend, accepts: legend, min_items: 1, max_items: 1}
  - {role: main-scale, accepts: scale-bar, min_items: 0, max_items: 1}
  - {role: main-north, accepts: north-arrow, min_items: 0, max_items: 1}
  - {role: organization-logo, accepts: image-asset, min_items: 0, max_items: 1}
  - {role: source-note, accepts: text, min_items: 0, max_items: 1}
  - {role: required-notice, accepts: text, min_items: 0, max_items: 1}

frames:
  - id: title-frame
    type: title
    coordinate_space: page
    slot: map-title
    bounds: {x: 15, y: 10, width: 390, height: 18}
    padding: {top: 1, right: 1, bottom: 1, left: 1}
    text_flow: {wrap: true, max_lines: 2}
    overflow: {actions: [reject]}

  - id: map-frame
    type: map
    coordinate_space: page
    slot: main-map
    bounds: {x: 15, y: 35, width: 300, height: 235}
    viewport_clip: true
    overflow: {actions: [reject]}

  - id: legend-frame
    type: legend
    coordinate_space: page
    slot: main-legend
    bounds: {x: 325, y: 35, width: 80, height: 170}
    padding: {top: 3, right: 3, bottom: 3, left: 3}
    arrangement:
      column_candidates: [1, 2]
      column_gap: 4
      row_gap: 2
      preserve_item_order: true
    text_flow: {wrap: true}
    overflow: {actions: [next-column-candidate, reject]}

  - id: scale-frame
    type: scale-bar
    coordinate_space: page
    slot: main-scale
    bounds: {x: 325, y: 215, width: 80, height: 15}
    linked_view_slot: main-map
    on_empty: keep-space
    overflow: {actions: [reject]}

  - id: north-frame
    type: north-arrow
    coordinate_space: page
    slot: main-north
    bounds: {x: 325, y: 240, width: 20, height: 25}
    linked_view_slot: main-map
    on_empty: keep-space
    overflow: {actions: [reject]}

  - id: logo-frame
    type: logo
    coordinate_space: page
    slot: organization-logo
    bounds: {x: 360, y: 240, width: 45, height: 25}
    asset_fit: contain-preserve-aspect
    on_empty: keep-space
    overflow: {actions: [reject]}

  - id: source-frame
    type: text
    coordinate_space: page
    slot: source-note
    bounds: {x: 15, y: 277, width: 285, height: 10}
    text_flow: {wrap: true}
    on_empty: keep-space
    overflow: {actions: [reject]}

  - id: notice-frame
    type: text
    coordinate_space: page
    slot: required-notice
    bounds: {x: 310, y: 277, width: 95, height: 10}
    text_flow: {wrap: true}
    on_empty: keep-space
    overflow: {actions: [reject]}

constraints:
  all_frames_inside_safe_area: true
  overlap_policy: explicit-only
  allowed_overlaps: []
  preserve_required_content: true
  preserve_map_coverage: true

capacity_hints:
  title_characters: 40
  legend_items: 12
  usage: prefilter-only
  final_check: measured-content-bounds

compatibility:
  media: [print]
  page_count: {minimum: 1, maximum: 1}
  provides:
    layout_capabilities: [map-container, title-container, legend-container]
  requires:
    renderer_capabilities:
      - measured-text-layout
      - positioned-frames
      - map-viewport-clipping

extension_policy:
  canvas_override: forbidden
  frame_bounds_override: forbidden
  optional_slots: omit-if-not-required-by-scenario
  parameter_overrides:
    legend-frame.arrangement.column_candidates:
      allowed_choices: [[1], [2], [1, 2]]
  add_frames: derived-layout-required
  pagination: forbidden
```

示例中，`viewport_clip` 只限制绘制发生在地图框内；`preserve_map_coverage` 要求空间适配仍完整满足业务范围，二者含义不同。`required-notice` 的模板数量下限为零表示 Layout 可用于没有声明的场景；Scenario 一旦要求该角色，其绑定在本次地图中即为必需。

该例没有规定字体、图例色块、实际标题、实际声明和 DPI。排版需接收外部内容及已解析视觉样式，完成测量后才能确认能否容纳。

## 11. 外部接口与内容绑定

### 11.1 MapScenario：要求与绑定

Scenario 通过内容角色提出需求，再由实例绑定到 Layout 的 Slot。建议同时检查角色、类型、数量、必需性和视图关联，不能仅比较 Frame 名称。

```yaml
layout_binding:
  layout_id: a3-landscape-sidebar
  contents:
    map-title: {content_id: project-title, type: text}
    main-map: {content_id: overview-view, type: map-view}
    main-legend: {content_id: overview-legend, type: legend, view_id: overview-view}
    main-scale: {content_id: overview-scale, type: scale-bar, view_id: overview-view}
    required-notice: {content_id: project-notice, type: text}
  required_roles: [map-title, main-map, main-legend, required-notice]
```

这是接口示意，实际引用需绑定版本和摘要。Slot 中的文本按文本数据处理；旧式 `{{MAP_TITLE}}` 等占位符也应映射到受控内容角色，不能当成任意表达式执行。

### 11.2 MapStyle：外观与测量

Style 提供文字样式、行高约束、符号尺寸、图例标签格式和允许的字号调整。Layout 提供排列方式和空间。双方可行范围取交集；没有交集就不兼容。

如果图例放不下，Layout 可以请求已允许的换列，不能通过减少专题分类数自动改变地图语义。分类数变更应回到规划阶段，并重新检查相关内容及审批绑定。

### 11.3 MapBrand：资产与空间限制

Brand 提供字体和 Logo 资产、长宽比、最小展示尺寸和安全留白。Layout 提供放置区域并保持比例。若容器无法满足 Logo 的约束，应更换 Layout 或已批准的品牌变体。

### 11.4 Delivery 与 Renderer：转换与输出

Layout 的物理尺寸通过 Delivery 的 DPI 转换为像素：

```text
像素长度 = round(毫米长度 / 25.4 × DPI)
```

Renderer Adapter 应固定舍入规则，优先共享边界坐标以避免相邻 Frame 的累计误差。屏幕逻辑 px、浏览器 CSS px 和设备像素需要明确转换，不能直接假定它们等价。

Layout 的毫米值不随导出 DPI 改变。Renderer 如果不能实现所需页面大小、文字测量或裁剪能力，应在预检时返回不兼容。

### 11.5 外部标准：约束共同满足

版面标准可以规定页边距、边框、安全留白、必需元素和最小可读尺寸。Layout 保存标准引用，并提供符合标准的空间方案。

强制约束不能通过简单的“后加载者覆盖”解决。Scenario、Brand、Style、Layout 与标准各自保留所有权，组合时同时验证所有硬约束；冲突需反馈到选择或规划阶段。

## 12. 匹配与组合流程

推荐流程：

1. 从用户要求、Scenario 和 Delivery 提取页面、地图数量、内容角色、媒介和页数限制。
2. 在权威索引中筛选可用的已发布 Layout；检查 Scenario 是否允许替换内嵌 layout 段。
3. 检查 Slot 的类型与数量、地图框数量、标准和 Renderer 能力。
4. 使用静态容量提示减少候选，保留有待测量确认的候选。
5. 绑定实际内容，解析 Style 和 Brand，并逐一执行允许的适配策略。
6. 对通过真实测量和约束检查的候选排序，输出选择结果、调整记录和拒绝原因。
7. 把精确 Layout 版本、摘要和最终排版结果纳入实例冻结。

建议区分：

| 状态 | 含义 |
|---|---|
| `candidate-needs-measurement` | 静态条件满足，尚待实际排版 |
| `compatible` | 本次内容直接满足版式约束 |
| `compatible-with-declared-adaptation` | 通过已声明换列、变体或参数调整后满足 |
| `incompatible` | 角色缺失、容量不足、标准冲突或能力不支持 |

例如，用户要求 A3 单页，而一个 A4 模板仅能通过缩小整张地图容纳内容，就不能作为 A3 合格候选。图例项数为 8、模板提示可容纳 12 项，也仍需真实测量，不能据此直接冻结。

## 13. 覆盖、变体、版本与派生

### 13.1 允许的实例调整

常见可调项包括图例列数、有限范围的列间距、明确声明的 Frame 宽度参数，以及可选区域是否保留空白。调整的默认值、范围和关联约束必须写入契约。

调整后要重新验证相邻区域、地图视图和内容测量，且不得改写已发布模板。

### 13.2 版式变体

同一模板可以声明有限变体，例如左侧图例和右侧图例，但必须完整描述每个变体、选择条件和适用范围。

早期更适合采用若干明确的固定模板，例如 A3 横向单主图、A4 纵向单主图、A3 双图对比。避免只定义一个“任意尺寸”模板却没有相应排版能力。

### 13.3 新版本与派生

调整固定边界、变更 Slot 语义、增加必需内容、改变画布或增加分页规则，均需发布新版本或新模板。破坏原内容接口兼容性的变化应按版本策略处理。

派生 Layout 可记录父模板来源，但发布物仍须为完整、自洽的 layout 段。多个 Layout 的 Frame 不能在运行时任意拼接；有这种需求时，应先形成新的完整模板。

当前所有权代码已经规定 `map-layout → layout` 整段替换。建议继续保留这个边界，并在替换之后执行组合检查。

### 13.4 超出模板规则的参考使用

如果只借鉴某模板的阅读顺序，却新增地图框、改变画布和排版机制，可以记录设计来源，但不能声明生成结果完全符合原模板。

## 14. 编译流程与实例输出

### 14.1 编译流程

```text
精确模板 + 内容绑定 + Style/Brand + 标准 + Target
    → 结构与引用检查
    → 确定 Frame 几何
    → 地图视图适配
    → 计算尺度相关样式与内容尺寸
    → 换行、换列和允许的版式调整
    → 空间覆盖、重叠、溢出和内容完整性检查
    → ResolvedLayout + 排版报告
    → 与实例表达和视图合成 RenderScene
    → 预览验证后冻结
```

地图框变化可能影响比例尺和注记数量，进而影响图例或其他内容。如果需要重复求解，必须有固定的候选顺序、预算和稳定终止条件；不收敛时报告失败，不无限自动调整。

### 14.2 `ResolvedLayout` 的职责

建议增加 `resolved-layout` 实例协议，记录本次排版的确定结果：

- Layout、内容、Style、Brand、标准和环境的引用与摘要；
- 选定版式变体与实际画布；
- 每个 Frame 的最终边界、内边距、内容绑定和可见性；
- 实际行数、列数、分页、测量边界和裁剪区域；
- 比例尺、指北针与地图视图的绑定；
- 已应用的调整、来源和验证结论。

与 `ResolvedCartography` 分工时，后者提供实际符号、图例与注记表达，`ResolvedLayout` 持有最终页面几何。标题等页级文本的换行和放置归排版结果，地图内要素注记位置归地图表达/渲染结果。适配过程中如调整了 Style 允许的字号，两个结果必须引用同一份最终值和调整记录。

```yaml
# 拟议的实例结果片段；省略了完整引用和摘要字段
layout_id: a3-landscape-sidebar
selected_variant: default
canvas: {width: 420, height: 297, unit: mm}
resolved_frames:
  - id: legend-frame
    content_id: overview-legend
    bounds: {x: 325, y: 35, width: 80, height: 170}
    content_box: {x: 328, y: 38, width: 74, height: 164}
    columns: 2
    item_count: 10
    measured_height: 126
    overflow: false
adaptations:
  - frame_id: legend-frame
    property: columns
    original: 1
    resolved: 2
    reason: one-column-height-exceeded
validation:
  required_content_complete: true
  frames_within_safe_area: true
  unauthorized_overlap: false
```

实例结果应纳入 ResolvedMap 的引用闭包，并在 G2 冻结时由 MapSpecLock 绑定其摘要。冻结后的正式渲染不得再次自由排版；字体、测量环境或内容发生漂移时应报告异常。

### 14.3 发布输出与地图输出

| 输出 | 归属与用途 |
|---|---|
| Layout 模板包 | 可复用、不可变的版式定义 |
| 发布回执、索引条目 | 仓库的发布与发现证据，位于模板包之外 |
| `ResolvedLayout` | 一次地图的最终排版结果 |
| 排版校验报告、预览证据 | 本次组合是否满足约束的证据 |
| RenderScene | 页面与地图合成后的渲染器输入 |
| PDF/PNG 等 | Renderer 和 Delivery 根据 Target 生成的地图成果 |

## 15. 模板包与项目组织

建议的独立 Layout 包结构如下。目录名称是组织约定，必须由 Manifest 显式列出；设计说明也可以沿用现有包的 `templates/design_spec.md` 路径。

```text
<map-layout-package>/
├── manifest.yaml
├── design_spec.md
├── contracts/
│   └── layout.yaml
├── dependencies.lock.yaml
├── assets/                 # 可选的版式专属资产
├── fixtures/               # 用于模板验证的合成内容
├── quality-gates.yaml
└── checksums.sha256
```

Manifest 管理身份和文件闭包；契约管理版面规则；依赖锁固定引用的标准、检查器和资源；Fixture 用于验证空间行为，不复制业务数据。

现有 `skills/carto-agent/templates/` 是内置示例区域。将 MapLayout 示例放入此目录不等于已经发布，正式发现仍应读取 TemplateRepository 权威索引。

后续实现应继续位于 `skills/carto-agent/`，例如扩展现有 `schemas/layout.schema.json`、增加实例排版 Schema，以及在 `scripts/carto_core/compiler/` 和 `validation/` 中实现布局解析和校验。本文不建立新运行入口。

## 16. 验证与兼容性证据

验证分为模板本身和带真实内容的组合两个层次：

| 层次 | 需要验证的内容 |
|---|---|
| 结构 | Schema、唯一 ID、Slot/Frame 引用、单位、默认值与范围 |
| 几何 | 正尺寸、安全区、边界、约束无环、合法嵌套与显式重叠 |
| 语义 | 内容类型、必需角色、视图关联、可选区规则 |
| 内容排版 | 文字真实尺寸、图例组标题与项顺序、无意截断、Logo 比例 |
| 空间适配 | 业务范围覆盖、比例尺条件、指北针与比例尺绑定 |
| 组合 | Style 最小字号、Brand 留白、标准、Renderer 能力、Target 页数 |
| 冻结与复现 | 依赖摘要、测量环境和实际渲染位置一致 |

模板验证建议覆盖短标题与长标题、单行与多行图例、不同大小的比例符号图例、缺少可选 Logo、很长的必需声明、多语言换行和边界容量。一个没有任何必需内容的空页面不能代表版式已验证。

“已与某 Style/Brand/Renderer 验证”应绑定精确版本、字体资产和测试条件。它只能证明被测组合与范围；新的内容或字体仍需实例校验。

Layout 校验可以验证“必需声明被完整放置”，但声明是否法定、文字是否正确由 Scenario/业务标准负责。实际导出文件尺寸和媒体签名由成品检查负责。

## 17. 不匹配时如何处理与创建

| 不匹配原因 | 建议处理 |
|---|---|
| 仅可选内容缺少 | 执行已声明空缺策略 |
| 图例可通过换列容纳 | 应用已允许策略，重新测量并记录 |
| 字体或 Logo 不满足约束 | 选择兼容 Brand/Style 或其他 Layout |
| 缺少双图、插图等必需 Frame | 选择对应 Layout，或创建完整派生 Layout |
| 用户要求 A4，当前模板固定 A3 | 选择或创建 A4 模板，不能任意缩放 |
| 单页无法容纳全部必需内容 | 返回容量缺口；经新的规划决定更换版式或页数 |
| Renderer 不支持所需排版能力 | 返回能力缺口；创建模板文件不能补足渲染能力 |

建议的模板创建流程为：需求与版面用途分析 → Layout Brief → 设计说明和机器契约编写 → 几何/内容约束验证 → 合成内容预览 → 发布检查与审批 → 不可变仓库和索引。

该独立创建流程是目标设计。可复用现有模板工作流的隔离运行、回执和审批机制，但不得假定当前 CLI 已能创建 MapLayout。新版本发布后，地图生成以精确引用使用它；已冻结运行不能原地改写 Layout 引用。

## 18. 当前仓库状态与演进建议

截至本文编写时，现有实现提供的是固定洪涝演示闭环中的内嵌 Layout，主要事实如下：

| 当前事实 | 实现依据 |
|---|---|
| Layout v1 已有画布、Frame、占位符、容量和规则 | [layout.schema.json](../../skills/carto-agent/schemas/layout.schema.json) |
| Frame 为 page 坐标，类型含 map、title、legend、scale-bar、north-arrow、inset、marginalia | 同上 |
| 尚无通用 chart/table Frame 接口，也未贯通通用图表载荷及两类放置链路 | 本文辅助图表部分为目标设计；现有边界见 [表达与符号设计结论第 10 节](map-expression-and-symbol-design.md#10-当前仓库状态与设计差距) |
| Canvas 使用 mm/px；Frame bounds 为四元素数组；容量主要是图例项数和标题字符数 | 同上及 [common.schema.json](../../skills/carto-agent/schemas/common.schema.json) |
| Scenario 必须内嵌 identity、cartography、layout，可声明可替换段 | [scenario.schema.json](../../skills/carto-agent/schemas/scenario.schema.json) |
| 所有权组件支持外部 MapLayout 整段替换 layout | [ownership.py](../../skills/carto-agent/scripts/carto_core/compiler/ownership.py) |
| 模板作者生成固定 A3 横向及主图、图例、标题 Frame | [template_author.py](../../skills/carto-agent/scripts/carto_core/workflow/template_author.py) |
| 候选编译器仍固定 viewport、camera padding 和多处页面元素像素位置 | [map_candidate.py](../../skills/carto-agent/scripts/carto_core/compiler/map_candidate.py) |
| 成品检查验证必需元素与估算边界，尚非通用字体测量和排版引擎 | [map_final_check.py](../../skills/carto-agent/scripts/carto_core/workflow/map_final_check.py) |
| Delivery v1 同时保存固定 A3 页面条件和 DPI，尚存在页面属性重复声明 | [delivery.schema.json](../../skills/carto-agent/schemas/delivery.schema.json) |
| 独立 MapLayout 业务创建路由尚未开放 | [SKILL.md](../../skills/carto-agent/SKILL.md) |

Schema 中存在 `web`、`mobile`、`paginate` 等枚举，不等于响应式或分页运行能力已经实现。`OwnershipResolver` 支持完整段组合，也不等于当前地图生成流程已经支持独立 Layout 的匹配、安装和排版。

建议按以下顺序演进：

1. 明确页面属性的唯一所有者，Delivery 保留目标要求并与 Layout 核对；对旧协议进行明确版本升级。
2. 明确页面坐标与单位，扩展 Slot、内容绑定和可选区规则。
3. 先实现固定 Frame 的通用排版，使 Renderer 消费 Layout 求解结果，移除对应位置硬编码。
4. 引入字体测量、图例尺寸测量和溢出报告。
5. 增加 `ResolvedLayout` 并将其摘要纳入候选、预览和锁链路。
6. 开放独立 MapLayout 创建、验证、发布和匹配。
7. 根据实际需求再增加变体求解、多视图、图集和响应式能力。

实现协议升级时，应同步提供合法、非法样例与自动验证，并保持完整段所有权、精确版本引用和不可变发布规则。
