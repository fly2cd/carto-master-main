# MapLayout 完整说明

> **状态公告（2026-11-18）**：品牌段（map-brand/identity）已经用户授权整体移除——它在渲染链中无消费者，移除不改变成图外观。本文已同步清理品牌遗留描述；当前协议以 `skills/carto-agent/schemas/` 与 SKILL.md 为准。

> 2026-11-09 设计收敛：采用 Encoding / Appearance / Composition 三个设计维度及独立 Renderer 执行层；模板是组合载体，不与维度一一映射。统一定义见[模板体系设计](../carto-template-dsg.md)。**所有权与词表的现行权威见[表达与符号设计结论 §11 单表](map-expression-and-symbol-design.md#11-所有权与权威源单表)与 §15 单源规范；历次修订记录见该文档 §14**（原收敛记录文件已不存在，不再作为依据）。完整模型、引用与作用域调整仍是目标设计；S1 后续已落实有限参数化网格，当前边界见第 18 节，不代表其他组合已开放。


> **讨论整理（2026-11-19）**：补充最小字段边界、Style 的角色化使用、文字/图文/图表的拆框标准，以及同一种 Frame 的父子组合目标。当前 `inside_frame` 仅是受限包含验证，不是通用嵌套、富文本或图文混排能力；详见 §6.7–§6.8、§18。本文不修改 Schema、代码、能力策略或审批。

## 1. 文档定位

本文介绍 Carto Agent 模板体系中 MapLayout 的基本概念、作用、职责边界、内容结构、组合接口、适配方式、验证要求和输出产物。

组织方式参考 [MapStyle 完整说明](map-style.md)，设计依据为 [模板体系设计](../carto-template-dsg.md)，表达、符号与图表复用的统一边界见 [地图表达与符号设计结论](map-expression-and-symbol-design.md)。两份专题文档分别说明制图表达规范与版面组织，供模板作者、业务方案设计者、编译器开发者和审核人员使用。

本文是设计说明。除第 18 节“当前仓库状态”外，新增字段、匹配状态、编译产物和处理流程均为建议设计；示例不代表当前 CLI 已支持的输入格式。运行时协议仍以 `skills/carto-agent/schemas/`、`policies/` 和已发布模板为准。

## 2. 基本介绍

MapLayout 是可复用、版本化、可校验的地图版式模板。它规定画布以及地图、标题、图例、署名等内容在画布中的空间组织方式。

MapLayout 回答：

> 哪些区域可以承载哪些内容，各区域有多大、放在哪里，内容超出空间时如何处理？

典型内容包括纸张尺寸、版面方向、安全边距、地图框、标题框、图例框、对齐方式、容器内间距、内容测量要求和溢出处理顺序。

一个 `a3-landscape-sidebar` Layout 可以明确规定：画布为 420×297 mm，主地图位于左侧，图例位于右侧，标题位于顶部，来源信息位于底部。人口、经济、资源或应急等 Scenario 都可以使用这个版式，只要所需内容及其尺寸能够被容纳。

MapLayout 的固定尺寸是其合法设计内容。复用的基础是稳定的内容接口和明确的适用条件，不要求所有尺寸都变成可变参数。

## 3. MapLayout 的作用

### 3.1 复用成熟的版面结构

将可重复使用的阅读顺序、空间比例、对齐关系和留白集中管理，使不同地图使用同一套版面组织。

### 3.2 将空间组织与内容表达分开

MapStyle 决定图例的字体、色块和符号外观；MapLayout 决定图例容器的位置、宽高、列数和内边距。更换色带通常不需要修改 Layout，更换纸张方向也不应直接修改专题符号语义。

### 3.3 在渲染前发现容量问题

实际标题、图例标签和字体尺寸进入后，可以提前检测越界、遮挡、文字截断、必需内容缺失等问题。

### 3.4 提供受控的适配空间

模板可以允许图例换列、标题换行或选用已定义变体。编译器按固定顺序尝试这些选项，并记录最终选择及其原因。

### 3.5 形成可追溯的排版结果

最终结果能够回答：使用了哪个 Layout 版本，内容绑定到了哪个 Frame，为什么使用两列图例，以及每个元素的最终边界来自哪个约束。

## 4. 与其他组件的区别和联系

| 组件 | 定义的内容 | 提供给 Layout 的信息 |
|---|---|---|
| MapScenario | 业务内容、数据角色、地图视图、必需元素、用途限制 | 需要哪些内容角色、各角色的实例内容与必需性 |
| MapStyle | 在表达、场景与标准约束内配置符号、色带、注记和图例外观 | 文本样式、图例样式、符号样式及允许调整范围 |
| MapLayout | 画布、Frame、位置、对齐、内容接口和排版策略 | 可承载内容的空间；实际容纳结果由组合测量得出 |
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
| 标题所用字体文件 | 由 generate 请求的显式字体声明提供（品牌段移除后无其他解析途径） |
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
- 标题换行、图例换列等容器排版规则；
- 区域最小尺寸、间距和明确允许的重叠关系；
- 内容测量要求与测量结果的来源绑定，不手写空间容量；
- 可选区域的空缺处理；
- 溢出处理顺序和允许的版式变体；
- 对 Scenario、Style 和 Renderer 的能力要求；
- 版面标准引用、参数覆盖和派生规则。

### 5.2 不拥有的内容

业务字段名、真实数据路径、风险等级含义、专题色带、实际地名、最终分类断点、字体文件、业务声明文本、地理范围、CRS 转换算法、输出 DPI 和交付目的地均有外部所有者。

Layout 可以引用相应角色。例如 Footer Frame 接受 `required-notice` 文本，但不把“合成数据演示”作为每个地图都必须使用的固定文案。

### 5.3 可以固定哪些值

| 值的类别 | 示例 | 推荐处理 |
|---|---|---|
| 版面身份 | A3 横向、420×297 mm | 可以固定 |
| 基准几何 | 主地图框坐标、安全边距、列间距 | 可以固定，也可以参数化 |
| 有限适配范围 | 图例允许一列或两列 | 显式声明可选项及选择顺序 |
| 外部视觉属性 | 字号、色带 | 引用 Style，遵守其约束 |
| 本次内容计算结果 | 图例实际行数、标题测量宽度 | 进入实例排版结果 |

“固定版式”与“可复用版式”并不冲突。A3 固定模板可以跨业务复用，但不应宣称可以无条件缩放为 A4、海报或手机界面。

### 5.4 最小字段边界与几何权威

下表是目标字段职责，不是新增的运行 Schema；字段词表与状态仍由共同单表 §15 拥有。

| 字段组 | 保存的设计决定 | 不保存的实例事实/推导结果 |
|---|---|---|
| 身份与版本 | `layout_id`、`version` 及已登记的协议版本；发布包摘要绑定 | 不使用虚构版本或摘要 |
| `canvas` | 画布、单位、原点、轴方向、安全边距 | DPI 与输出格式归 Delivery |
| `content_slots` | 内容角色、接受类型、数量与必需性条件 | 不写死业务文字、数据路径 |
| `frames` | 容器类型、几何、Slot 绑定、明确的视图关联和溢出行为 | 不以 Frame 名称替代内容语义 |
| `content_padding_mm` 与容器排版 | 内边距、对齐、换行、图例列数等选择 | 不手写“可放 42 字 / 12 项” |
| `grid`（按需） | 区域、行列、间距和允许组合 | 展开后的 cell 坐标由程序产生 |
| 受控约束、兼容与扩展策略 | 允许的包含/覆盖、可改字段、所需能力与标准 | 不承载任意求解脚本或解除业务硬约束 |

同一组几何只能有一个作者权威：固定布局直接给毫米边界；参数化网格给区域、行列与间距，展开坐标是派生结果。不能把网格参数和其展开 Frame 都当成可独立修改的来源。固定模板不因不能直接换纸张而失去复用性；变体和适用条件需显式声明。

未来通用父子组合沿用 Frame/Slot 和现有实例产物，不另建 SubFrame 协议或页面引擎。其字段与版本必须单独完成迁移设计，见 §6.7；在此之前不能向现有合同直接添加 `children`、父坐标或自动伸缩字段。

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
| text | 来源、日期、声明等 | 项目内容或外部格式化结果 |
| chart（具体能力依注册实现） | 主图区附近独立展示的柱状图、饼图、折线图等 | Scenario/任务指定的数据内容，经图表核心生成 |
| table（扩展建议） | 统计表、指标说明表等 | Scenario/任务指定的数据内容，经表格组件生成 |

`text` 在此是内容类别说明，不能据此新增运行时枚举；当前通用页面文字使用已注册的 title/marginalia。Schema 已列出 chart，并有受限图表绘制消费点，但不代表任意图表、富文本、图片、表格或组合容器都已准入。`chart_panel`、`table_panel` 是示意内容角色，实际字段与端到端边界以 §18 的证据和注册策略为准。

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

### 6.6 基础布局模型、附加结构与内容组织

| 基础模型 | 如何形成空间结构 |
|---|---|
| single | 一个主要地图面板及附属区域 |
| grid | 按声明的行列、间距和尺寸规则展开面板 |
| mosaic | 按明确的跨行跨列关系展开面板 |
| freeform | 直接声明各 Frame 的边界与受控空间关系 |

inset 是依附具体视图的附加结构，可与基础模型组合，不是互斥的第五种布局。海报是用途/媒介，不等于 freeform；自由编排先支持固定构图，再扩展锚定和有限求解，须声明层级、允许重叠、裁剪和最小可读尺寸。

这些模型共用 Canvas/Frame/内容接口，解析到同一 ResolvedLayout，不新建 subplot 或海报专用执行器。固定模板、有限变体和受控参数化均合法；模型能力不等于每个模板默认允许任意行列或任意尺寸。

显式组合和分面归 Scenario/项目规划。规划先产生稳定 ID 的视图和内容，Layout 只验证接口、数量与空间并绑定。地理视图共享、编码共享和图例共享分开，可按组设置；Layout 只安排已获语义许可的图例，不自行合并尺度、筛选年份或减少分类。

### 6.7 复合内容与 Frame 嵌套（目标设计）

**支持父子层级，但不把 Frame 与 SubFrame 做成两套对象。** 子 Frame 只是处在另一 Frame 内的同一种容器；是否拆框由“是否需要独立布局/绑定”决定，而不是看内容是否混有文字、图片或图形。

#### 6.7.1 页面容器与组件内部结构分开

| 内容情形 | 建议边界 |
|---|---|
| 一段文字中的加粗、颜色和段落 | 一个文字组件；文字运行、段落不是页面 Frame |
| 跟随正文流动的小图标 | 若已注册的富文本组件支持，仍在该组件内；不因此开放任意图片混排 |
| 左插图、右说明，需要分别调整位置或宽度 | 父容器下的图片内容 Frame 与文字内容 Frame |
| 一张图表的标题、坐标轴、柱子、刻度和数值标签 | 通常一个图表内容 Frame；内部由图表核心绘制、测量 |
| 图表之外的独立业务解读或需跨组件对齐的标题 | 独立文字 Frame；需整体移动时放入共同父容器 |
| 地图上按城市位置放置的小图表 | 地图表达/地理锚定处理，不为每个城市建立页面 Frame |

相同外观的图文组合也可以由已注册的单一复合内容组件承载，前提是其内部布局完全由该组件拥有；不能同时让 Layout 和组件独立控制同一内部位置。需要独立布局时拆成子 Frame，组件内部自足时不继续拆。图表标题拆出后，图表组件不得重复绘制它。

“插图”若指区位小地图或局部放大地图，应绑定独立地图视图及其地理关系，不应降格为无比例尺/投影语义的普通图片。该视图能力仍需单独准入。

#### 6.7.2 同一种 Frame 的两种职责

首期目标采用排他的结构角色，避免既绑定整份内容、又重复绑定其子内容：

- **容器 Frame：** 组织子 Frame，拥有自身几何、内边距、排列、间距及溢出要求；背景和边框可作为容器装饰，不重复承载业务正文。
- **内容 Frame：** 通过 Slot 绑定一个类型化内容对象，例如文字、图片、图表、地图或图例；内容对象可以有组件内部结构，但不是第二棵页面布局树。

作者协议只保留一种父子关系来源；本目标采用概念上的子节点树，父引用由树推导，不再保存一套可独立修改的 `parent_id` 关系。具体字段拼写、受支持深度/数量和版本需在实现时正式定义，本文树形图不是当前 Schema 输入。

每个子节点只有一个父容器，节点身份唯一，无循环。重复使用内容资源不等于一个布局节点有多个父亲；页面中重复出现时须有独立放置身份。

#### 6.7.3 坐标、测量与溢出

1. 根级 Frame 使用页面坐标。父子组合的目标约定为：子坐标原点在父容器**扣除内边距后的内容区左上角**，单位和轴方向继承明确的画布合同；不能混用父边框原点和内容区原点。
2. 子布局仍可选择固定局部毫米几何或已支持的网格/流式规则，但每组几何只保留一个作者来源。父容器平移不意味着文字字号自动缩放；旋转、缩放、自动高度与分页必须另行声明能力和约束。
3. 父框只负责给空间，内容组件根据实际宽度、内容、样式和字体测量自己的占用。测量结果向上传递并验证整体容纳；父框边界合法不能代替子内容溢出检查。
4. 内容、字体、字号、内边距、可用宽度、排列或相关环境变化后，重算受影响的节点及依赖；可选内容折叠不能沿用旧的兄弟节点位置和测量。固定/自适应尺寸的依赖须无循环，不隐含通用自动求解器。
5. 父子包含属于明确结构，仍要校验几何与裁剪；兄弟节点意外重叠不能借“同属父容器”获得豁免。允许覆盖须显式声明并验证，且不得裁掉强制内容或业务要求的地图范围。
6. 放不下时只采用已声明、已实现且获准的适配动作；无法满足就返回具体节点和原因，不自动删除内容、改分类数或无限缩字。

编译时可以把局部几何机械转换为最终页面几何，但须在现有 `resolved-layout` 的版本演进及测量证据中保留源节点、祖先路径、转换输入和内容绑定；**展平坐标不等于把整组内容栅格化成一张图片**。不创建第二种布局锁或 SubFrame 渲染器。

结构参考：[Vega Group Mark](https://vega.github.io/vega/docs/marks/group/) 以组提供局部坐标与嵌套元素；该一手实现支持“同一种容器可嵌套”的思路，不证明 Carto 已具备这些能力，也不要求引入 Vega 后端。项目职责依据为本节 §6.2 及[图表核心/页面放置边界](map-expression-and-symbol-design.md#5-通用图表如何同时用于地图和辅助区域)。

#### 6.7.4 与当前 inside_frame 的区别

当前 [layout.schema.json](../../skills/carto-agent/schemas/layout.schema.json) 的 `coordinate_space` 仍固定为 page；[layout.py](../../skills/carto-agent/scripts/carto_core/compiler/layout.py) 只允许非地图 Frame 完整落在未被包含的地图 Frame 内，且禁止这一包含关系递归。它是受限的有意覆盖校验，不提供通用父容器、局部坐标、富文本、子布局或自动伸缩。不能用 `inside_frame` 冒充本节目标。

新增嵌套能力必须在同一实现根中同步版本化协议、编译、测量、渲染、能力准入和合法/非法测试；未知字段继续拒绝。已存在的 chart 枚举和局部绘制代码也不能替代上述组合能力验收。

### 6.8 示例：地图与右侧图文信息区

以下是结构提案，不是可运行合同；未提供业务数据、图片授权或渲染验收，不自动获得生产准入。

```text
Page
├── 页面标题 Frame                 → 标题内容
├── 主地图 Frame                   → 地图视图
├── 右侧信息区 Frame               → 容器
│   ├── 区域简介 Frame             → 文字组件
│   ├── 图文介绍 Frame             → 容器
│   │   ├── 插图 Frame             → 图片组件
│   │   └── 图片说明 Frame         → 文字组件
│   └── 指标图表 Frame             → 图表组件
│       └── 标题、轴、柱子、标签    → 组件内部，不是页面子 Frame
└── 来源说明 Frame                 → 来源内容
```

整体移动右侧信息区时，子节点相对关系保持；调整插图宽度可能改变说明文字换行和信息区总占用，必须重测。图片为可选时，保留空位或折叠由模板明确选择；必需图片缺失应拒绝，不能擅自隐藏。

页面只选择一套基础 Style，标题、正文、图片说明与图表按内容角色使用所需规则。父容器有装饰也不复制完整 Style。子 Frame 换位置不自动改变其内容角色；确需局部样式覆盖时须另行定义作用域和来源，不依赖父子树隐式级联。映射关系以 [MapStyle §10.3](map-style.md#103-maplayout-接口) 为准。

## 7. 容量、测量与溢出

### 7.1 空间容量是推导量，不得手写

**本节已按[表达与符号设计结论 §15.2](map-expression-and-symbol-design.md#152-概念删除登记) 删除手写容量概念**（原 `capacity` / `capacity_hints`）。理由与证据：

1. [design-principles §2.3](../design-principles.md) 已将「字体度量 → glyph 宽度（用于溢出检测）」列为**机械推导层**职责。既然有算式（§7.2），就不应再让人手写一个数字放进契约。
2. 实测：7 项迁移资产中 **4 项的手写容量物理上不可实现**（如承诺 54 字需 342.9mm，框只有 266mm）；1 项为**不存在的标题框**声明了 30 字容量。
3. 实测：将 `title_characters` 声明为 200 放进 277×10mm 框，**计数门禁放行且渲染成功**。证明当前实现只校数字、不校物理尺寸。
4. **乐观的预检提示比没有提示更糟**：它会放行本该被筛掉的候选。原文只说“无法保证通过”，未规定方向性，这是规范缺口。

因此：

- **Layout 不存空间容量**。程序从 `frame × typography × 已解析字体度量` 推导，结果写入 `resolved-layout`（实例产物，可摘要、可重验）。
- 若需搜索期的廉价预检，那必须是**派生并缓存的保守下界**，携带 `derived_from: {font_ref, typography_ref, frame_digest}` 与 `verified_at`——是计算结果，不是作者愿望。
- **业务硬上限**（如“图例不得超过 12 项”）另立 `business_limits`，所有权归 **Scenario 与适用标准**（§4 归属表已如此规定），不得与空间估算混用同一字段。

相同数量的图例项可能具有不同的符号高度、长标签、单位和多行说明；相同字符数在不同字体中也有不同宽度。这正是容量必须推导而非声明的原因。

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
| 来源和强制声明 | 换行 → 扩大已授权区域 → 报告失败 | 隐藏、截断或改写必需文本 |
| 地图内容 | 在已批准视图内裁剪渲染到地图框 | 裁掉业务要求覆盖的区域来适配页面 |

Layout 允许的文字缩小，还必须落在 Style 和适用标准共同允许的范围内。允许 `shrink` 不能成为绕过字号下限的理由。

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

地图内留给附属元素的区域会减少可见空间，应参与地图视图和注记避让计算。页面层级与地图图层顺序是两套关系，分别由 Layout 和 portrayal 管理；Style 不另存一份图层顺序。

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
| 7. 外部组件接口 | 对 Scenario、Style、空间编译和 Renderer 的要求 |
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
页脚分别承载来源与可选声明。

## 接口与适配

接受主地图视图、标题和主图例；其他内容角色见机器契约。
图例尝试已声明的列数，并按实际字体和标签测量；无法容纳时返回不适配。

## 限制

该示例版式为单页固定画布，不提供双主图和图例续页；当前 general 的有限网格能力见第 18 节。
```

## 10. 机器契约建议与完整示例

### 10.1 顶层组成

推荐围绕以下结构设计：

```text
canvas → frames → content_slots
                  + constraints
                  + compatibility / extension_policy
# 空间容量不在契约中：由程序推导并写入 resolved-layout（§7.1）
```

固定版式可以只依赖明确的 Frame 边界。栅格、自动求解、分页和响应式变体可以按实际复用需求增加，不必一次引入。

### 10.2 A3 单主图侧栏版式示例

以下为拟议的下一版机器契约示例，`schema_version: 2` 仅用于与当前 v1 区分；它不是已注册协议，不能直接提交给现有 CLI。全部长度使用 `canvas.unit`，`content_slots` 中的 role 通过实例绑定获得具体内容。

```yaml
schema_version: 2
layout_id: a3-landscape-sidebar
version: 1.0.0
# category 已删除：0 渲染消费点，且 §8.4 自认“声明 web/mobile 分类不等于具备能力”。
# 媒介归 compatibility.media；输出格式与 DPI 归 Delivery Target。
# placeholders 已删除：无替换引擎，content_slots + 实例绑定覆盖同一需求。
# capacity / capacity_hints 已删除：空间容量由程序推导，见 §7.1。

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
  # 本例指北针位于侧栏，所有框互不重叠，不能虚构它被地图包含。
  allowed_overlaps: []
  # 若另一个版本把附属元素放入地图，须声明并核验完整包含；
  # 通用父子容器见 §6.7，不能用当前 inside_frame 代替。
  preserve_required_content: true
  preserve_map_coverage: true

# 空间容量不在此声明：由程序从 frame × typography × 字体度量推导，
# 结果写入 resolved-layout；业务硬上限归 Scenario（business_limits）。

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

### 10.3 联合示例：A4 人口密度概览

与 [MapStyle §8.9](map-style.md#89-联合示例某市各区人口密度概览) 共用一个需求示例。此处只拥有空间设计，不复制 Style 的字号、色带或本次数据映射。全部尺寸为作者提出的设计值，**不是已通过内容测量的模板或地图**。

画布为 297 × 210 mm，横向，原点左上、x 向右/y 向下；四边安全边距 10 mm，内容内边距 2 mm。采用固定毫米几何，不另外保存一套可独立修改的网格。

| Frame ID | Slot/内容角色 | 类型化内容 | [x, y, width, height] mm |
|---|---|---|---|
| title-frame | map-title | 标题文字 | [10, 10, 277, 16] |
| map-frame | main-map | 地图视图 | [10, 32, 205, 144] |
| legend-frame | main-legend | 已解析图例 | [223, 32, 64, 112] |
| scale-frame | main-scale | 主图比例尺 | [223, 150, 64, 14] |
| source-frame | source-note | 来源说明 | [10, 182, 277, 18] |

标题、主图、图例、来源各接受一个必需内容；比例尺 Slot 接受零或一个，但 Scenario/标准要求时必须绑定。比例尺缺省时本固定版式保留空间。图例和比例尺在模板层关联 main-map 角色，实例编译再解析为准确 view ID；角色关联字段的正式拼写与版本仍待定义，不把目标名称直接塞入现有 Schema。

图例单列、保持已确认项目顺序。文字按已声明且已实现的换行规则排版；超出容器时拒绝本次组合，不删图例项目、不改密度分级、不静默缩字。地图只在已批准视图中裁剪绘制，并须满足业务覆盖范围。实际比例尺数值、换行结果、图例高度和像素坐标均由程序计算。

联合编译顺序是：绑定内容与准确字体 → 解析唯一 Style/表达来源 → 派生地图与图例 → 实测容纳 → 记录调整与来源 → 冻结。字体、内容、字号、列数或框尺寸变化均会使相关测量失效；固定画布也不保证任意长度文字都能放下。页级外观与实际能力证据见 §18。

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

Style 与 Layout 不固定配对，兼容的资产可多对多组合。本次页面选择基础 Style，Frame 中的内容按角色使用其中的规则；不是每个 Frame 或子 Frame 绑定一套完整 Style。完整样式作用域约定由 [MapStyle §10.3](map-style.md#103-maplayout-接口) 拥有，Layout 仅负责空间和内容接口。

Style 提供文字、符号和图表的外观；Layout 提供可用宽高、内边距、排列和适配选择。实际标签与数值格式属于本次表达，图例项目/颜色/大小从同一解析映射派生。双方范围还须与标准、业务和后端共同满足；不能各自通过静态检查就认定组合一定可用。

图例放不下时可在已声明且已实现的动作内换列或选择变体，不能减少专题分类数。共享图例、共享数值编码、相同地图比例尺是三个不同条件，由任务/表达要求其必要关系，Layout 不能凭“三栏”强制等同。空间相邻也不能替代视图绑定。

内容组件负责自身内部排版与测量；父子 Frame 只组织组件空间，测量与失效按 §6.7 传播。Style 的字号发生变化也可能导致 Layout 不再适配，必须重新测量，不得改变字号来掩盖空间失败。

### 11.3 品牌接口（已移除）

品牌段（map-brand/identity）已于 2026-11-18 经用户授权整体移除（渲染链无消费者）；原字体/Logo 资产接口不再存在。字体由 generate 请求显式提供，署名文本来自场景策略 notice。

### 11.4 Delivery 与 Renderer：转换与输出

Layout 的物理尺寸通过 Delivery 的 DPI 转换为像素：

```text
像素长度 = round(毫米长度 / 25.4 × DPI)
```

Renderer Adapter 应固定舍入规则，优先共享边界坐标以避免相邻 Frame 的累计误差。屏幕逻辑 px、浏览器 CSS px 和设备像素需要明确转换，不能直接假定它们等价。

Layout 的毫米值不随导出 DPI 改变。Renderer 如果不能实现所需页面大小、文字测量或裁剪能力，应在预检时返回不兼容。

### 11.5 外部标准：约束共同满足

版面标准可以规定页边距、边框、安全留白、必需元素和最小可读尺寸。Layout 保存标准引用，并提供符合标准的空间方案。

强制约束不能通过简单的“后加载者覆盖”解决。Scenario、Style、Layout 与标准各自保留所有权，组合时同时验证所有硬约束；冲突需反馈到选择或规划阶段。

## 12. 匹配与组合流程

推荐流程：

1. 从用户要求、Scenario 和 Delivery 提取页面、地图数量、内容角色、媒介和页数限制。
2. 在权威索引中筛选可用的已发布 Layout；检查 Scenario 是否允许替换内嵌 layout 段。
3. 检查 Slot 的类型与数量、地图框数量、标准和 Renderer 能力。
4. 用**派生的保守容量下界**减少候选（携带字体/字号/框摘要来源），保留有待测量确认的候选；不得使用作者手写的乐观提示。
5. 绑定实际内容，解析 Style，并逐一执行允许的适配策略。
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

当前代码对 `map-layout → layout` 采用整段替换。目标保留它用于结构性更换，同时允许契约声明的参数绑定和限定作用域的调整；必须共同验证约束和记录来源，不允许任意深层合并。参数产生新的实例结果，不改写已发布模板。

### 13.4 超出模板规则的参考使用

如果只借鉴某模板的阅读顺序，却新增地图框、改变画布和排版机制，可以记录设计来源，但不能声明生成结果完全符合原模板。

## 14. 编译流程与实例输出

### 14.1 编译流程

```text
精确模板 + 内容绑定 + Style + 标准 + Target
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

沿用已有 `resolved-layout` 实例产物；下列扩展信息须通过现有协议的版本演进或绑定测量证据承载，不另建第二套实例协议/锁，也不表示当前字段已经齐全：

- Layout、内容、Style、标准和环境的引用与摘要；
- 选定版式变体与实际画布；
- 每个 Frame 的最终边界、内边距、内容绑定和可见性；
- 实际行数、列数、分页、测量边界和裁剪区域；
- 比例尺、指北针与地图视图的绑定；
- 已应用的调整、来源和验证结论。

与 `resolved-appearance` / `resolved-portrayal` 分工时，后者提供实际符号、图例与注记表达，`resolved-layout` 持有最终页面几何。标题等页级文本的换行和放置归排版结果，地图内要素注记位置归地图表达/渲染结果。适配过程中如调整了 Style 允许的字号，两个结果必须引用同一份最终值和调整记录。

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
| 内容排版 | 文字真实尺寸、图例组标题与项顺序、无意截断 |
| 空间适配 | 业务范围覆盖、比例尺条件、指北针与比例尺绑定 |
| 组合 | Style 最小字号、标准、Renderer 能力、Target 页数 |
| 冻结与复现 | 依赖摘要、测量环境和实际渲染位置一致 |

模板验证建议覆盖短标题与长标题、单行与多行图例、不同大小的比例符号图例、很长的必需声明、多语言换行和边界容量。一个没有任何必需内容的空页面不能代表版式已验证。

“已与某 Style/Renderer 验证”应绑定精确版本、字体资产和测试条件。它只能证明被测组合与范围；新的内容或字体仍需实例校验。

Layout 校验可以验证“必需声明被完整放置”，但声明是否法定、文字是否正确由 Scenario/业务标准负责。实际导出文件尺寸和媒体签名由成品检查负责。

### 16.1 组合与父子布局的目标验收

下列是新增能力时必须提供的合法/非法用例，不是本轮已执行的测试报告：

- 合法：移动父容器只改变子节点最终位置，不改变字体大小和内容绑定；同一内容资源的两处放置有不同 Frame 身份。
- 合法：图表内部轴和标签由图表组件测量，不被复制成另一套页面 Frame；拆出的标题不重复绘制。
- 非法：多父节点、循环、重复身份、悬挂 Slot/视图、同时绑定容器整份业务内容与其重复子内容。
- 非法：父框在页面内但子内容溢出，兄弟节点未声明遮挡，裁剪强制声明或必需地图覆盖。
- 失效检查：改变文字、字体、字号、内边距或可用宽度后，旧测量不能被作为当前通过证明；可选区折叠后验证相关兄弟节点。
- 语义检查：共享图例必须通过真实映射等价性核验，不能仅凭容器数量/位置通过；比例尺和地图插图明确绑定视图。
- 当前能力检查：向现有 Schema 传入通用 children/父坐标等未定义字段仍应拒绝；新协议发布前不得把文档示例作为旁路输入。

验证几何、测量和数据/样式来源，不以“输出文件生成成功”代替验收。新增字段都要说明消费者、触发条件、失败原因和冻结依赖，且不放松现有审批。

## 17. 不匹配时如何处理与创建

| 不匹配原因 | 建议处理 |
|---|---|
| 仅可选内容缺少 | 执行已声明空缺策略 |
| 图例可通过换列容纳 | 应用已允许策略，重新测量并记录 |
| 字体不满足约束 | 选择兼容 Style 或其他 Layout |
| 缺少双图、插图等必需 Frame | 选择对应 Layout，或创建完整派生 Layout |
| 用户要求 A4，当前模板固定 A3 | 选择或创建 A4 模板，不能任意缩放 |
| 单页无法容纳全部必需内容 | 返回容量缺口；经新的规划决定更换版式或页数 |
| Renderer 不支持所需排版能力 | 返回能力缺口；创建模板文件不能补足渲染能力 |

建议的模板创建流程为：需求与版面用途分析 → Layout Brief → 设计说明和机器契约编写 → 几何/内容约束验证 → 合成内容预览 → 发布检查与审批 → 不可变仓库和索引。

该独立创建流程是目标设计。可复用现有模板工作流的隔离运行、回执和审批机制，但不得假定当前 CLI 已能创建 MapLayout。新版本发布后，地图生成以精确引用使用它；已冻结运行不能原地改写 Layout 引用。

## 18. 当前仓库状态与演进建议

截至 2026-11-18 重新静态核对（上一版为 2026-11-09）；以下依据现有代码与策略，非新增能力声明。**所有权与权威源以[表达与符号设计结论 §11 单表](map-expression-and-symbol-design.md#11-所有权与权威源单表)为准，`rules` 可执行性以其 §12 为准**；本节不重复定义所有权。

| 当前事实 | 实现依据 |
|---|---|
| 唯一能力档案 `general-thematic-mapping@5.0.0`（implementation `general-thematic`）下两个几何变体：raster→`general-thematic-map@3.0.0`、vector→`@4.0.0`；以参数选择 1×1、1×2、2×2 和独立/共享图例；`output_profile` 为 A4 横向 300 dpi，`production_enabled: false` | [scenario-capabilities.yaml:9-11,40-45,66-80](../../skills/carto-agent/policies/scenario-capabilities.yaml)、[general_thematic.py](../../skills/carto-agent/scripts/carto_core/scenarios/general_thematic.py) |
| Layout 在 canvas/frames 基础上增加有限 grid 规则；`grid.allowed_shapes` 由模板声明，但 Schema 枚举当前仅 `[[1,1],[1,2],[2,2]]`；inset 等其他枚举不等于可执行 | [layout.schema.json:96-107,198-219](../../skills/carto-agent/schemas/layout.schema.json) |
| 解析器支持单图及模板声明网格、mm、DPR=1；页面框**默认互不重叠**，`frames[].inside_frame` 声明的**完整包含**经机械核验后豁免（`LAYOUT_CONTAINMENT_REFERENCE/TYPE/NOT_ENCLOSED`）；未声明重叠、部分重叠、被包含框互相遮盖仍报 `LAYOUT_FRAME_OVERLAP`；多图网格基座不接受包含声明（`GRID_BASE_INVALID`）。ResolvedLayout v2 保存源合同、参数、实例及全部地图框，并携带包含声明以供重验 | [layout.py:149-203](../../skills/carto-agent/scripts/carto_core/compiler/layout.py)、[grid_layout.py:37-42](../../skills/carto-agent/scripts/carto_core/compiler/grid_layout.py)、[resolved-layout.schema.json](../../skills/carto-agent/schemas/resolved-layout.schema.json) |
| px 画布被拒（`LAYOUT_COORDINATE_UNSUPPORTED`）；shrink/paginate 被拒（`LAYOUT_OVERFLOW_UNSUPPORTED`，已登记 roadmap `layout-overflow-strategies`）；地图仅 clip、其他仅 reject | [layout.py:129-135,184-187](../../skills/carto-agent/scripts/carto_core/compiler/layout.py)、[capability-roadmap.yaml](../../skills/carto-agent/policies/capability-roadmap.yaml) |
| `capacity` 当前是**手写计数上限**并被强制（图例项数、标题字符数），**不从 frame×typography×字体度量推导**；实测可声明物理上放不下的值并通过计数门禁。**本文已删除手写容量概念（§7.1）**，目标为程序推导值入 `resolved-layout`；Schema 侧的 `capacity` required 字段属待迁移项 | [raster_page_contract.py:74-76](../../skills/carto-agent/scripts/carto_core/compiler/raster_page_contract.py)、[page_renderer.py:150-151](../../skills/carto-agent/scripts/carto_core/adapters/page_renderer.py) |
| 静态栅格页面已有真实字体测量和物理尺寸检查（`measurements` 逐 artist 实测边界）；浏览器/SVG 路径仍用保守包络。SVG 与静态页均**先画地图体、后画附属元素**，因此被包含的指北针/图例天然压在地图之上 | [static_page_renderer.py:283-293](../../skills/carto-agent/scripts/carto_core/adapters/static_page_renderer.py)、[svg_compositor.py:100-111](../../skills/carto-agent/scripts/carto_core/adapters/svg_compositor.py) |
| 比例尺长度由所绑定视图计算（需投影 CRS）；**指北针当前为固定向上箭头，未按视图真北旋转**；多图时 `view_ids` 绑定尚未强制（迁移资产 7/7 未绑） | [static_page_renderer.py:69,261,274-277](../../skills/carto-agent/scripts/carto_core/adapters/static_page_renderer.py) |
| `placeholders` 为 Schema required，但**无替换引擎**；渲染文本来自请求 `texts[].text`，占位符仅被只读匹配器与兼容声明消费。本文 §10.2 的 `content_slots` 为目标设计，尚未落地 | [template_matching.py:338-340](../../skills/carto-agent/scripts/carto_core/repository/template_matching.py)、[ownership.py:146-164](../../skills/carto-agent/scripts/carto_core/compiler/ownership.py) |
| 段引用协议（S2）已接入 validate/publish/generate 三个边界，全内嵌旧路径零改动；但**独立 MapLayout 创建路由与自动检索/选择仍未开放**（`template match` 仅只读评分） | [ownership.py](../../skills/carto-agent/scripts/carto_core/compiler/ownership.py)、[template_validation.py:416-422](../../skills/carto-agent/scripts/carto_core/workflow/template_validation.py)、[SKILL.md](../../skills/carto-agent/SKILL.md) |

**2026-11-19 补充核对：** 页面请求只有一个 `appearance`，并通过 `style_ref` 绑定基础外观；这与“页面选 Style、内容使用相关规则”一致，不代表所有目标角色字段已实现。当前 Frame 仍为平面列表、`coordinate_space: page`；`inside_frame` 只允许非地图附属框位于未被包含的地图框内，不能递归，故不是 §6.7 的通用父子布局。`chart` 已有 Schema 枚举及静态页的局部图表绘制消费，但该事实不证明任意图表、富文本、图片/表格组件或嵌套布局可端到端交付。核对点：[page-request](../../skills/carto-agent/schemas/page-request.schema.json)、[layout Schema](../../skills/carto-agent/schemas/layout.schema.json)、[LayoutResolver](../../skills/carto-agent/scripts/carto_core/compiler/layout.py)、[静态页渲染](../../skills/carto-agent/scripts/carto_core/adapters/static_page_renderer.py)。本次仅更新设计文档，未注册通用嵌套能力。

S1 已通过共享面板/view/Frame 绑定和有限参数规则，复用 MapScenario 发布路径贯通单图、双图、四图；模板验证覆盖声明的六种参数组合。没有另建 subplot 引擎，也没有按组合复制固定模板。独立 Layout 组合、其他模型、自动检索/生成模板仍待按需求实施，不能绕过模板发布或 G1/G2/G3。可核对锚点：[grid_layout.py](../../skills/carto-agent/scripts/carto_core/compiler/grid_layout.py)、[test_s1cd_grid.py](../../skills/carto-agent/scripts/tests/test_s1cd_grid.py)、[test_layout_contract.py](../../skills/carto-agent/scripts/tests/test_layout_contract.py)。

页面构成由 Layout 提供，用户和 Delivery 只提出兼容条件；输出实例记录最终共同满足的规格。新协议须版本化、提供合法/非法样例和自动测试；旧模板、旧锁不就地补字段或静默迁移。固定自由编排、mosaic/inset 和更复杂约束须分别验收后开放。
