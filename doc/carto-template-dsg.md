# 地图制图智能体模板体系设计

## 结论

不要把“地图模板”设计成一个同时包含配色、图层、版式、数据字段和业务场景的万能文件。更合理的方案是复用本项目的“分段所有权”思想，建立：

> 4 类模板工作区 + 交付形态 + 地图表达/符号目录 + 数据空间契约 + 项目实例锁

这样既能实现复用，又不会让模板绑死具体地区、数据集或渲染引擎。

本文统一使用以下面向中文用户的领域名称：`MapStyle` 称为“制图表达规范”，强调其同时覆盖视觉层级、符号化、标注和概化等表达规则，而不是操作步骤或单纯视觉风格；`MapScenario` 称为“制图场景方案”，表示面向一类可重复业务场景的集成方案，不再使用地图侧的 `MapDeck`、`Map Product` 或“产品族”命名。PPT Master 的 `Style`、`Deck` 仅在来源对照中保留原名。

## 一、PPT Master 模板系统可提供的参考

### 1. 按“稳定复用的规则”划分模板

PPT Master 把 Brand、Style、Layout、Deck 定义为拥有不同职责的可组合模板类型，而不是同一继承层级中的不同阶段，参见 [模板资源说明](../../skills/ppt-master/templates/README.md)。其中 Deck 是集成应用模板，会同时携带应用、身份和结构，因此这里更准确的概念是“分段所有权”，而不是各维度完全独立。

| PPT Master 类型 | 地图智能体中的对应物 | 负责内容 |
|---|---|---|
| Brand | 地图身份模板（Identity） | 机构颜色、字体、Logo、品牌符号和署名规范 |
| Style | 制图表达规范（MapStyle） | 信息层级、符号语言、标注原则、色彩语义和概化方法 |
| Layout | 地图版式模板（Map Layout） | 图框、标题、图例、比例尺、指北针、插图和来源区的位置与容量 |
| Deck | 制图场景方案（MapScenario） | 面向某类可重复业务场景的集成制图方案，例如应急态势、规划专题和自然资源图集 |
| Chart/Table Catalog | 地图表达目录（Map Encoding Catalog） | 分级设色、比例符号、流向图、点密度和等值线等具体表达方法 |
| — | 交付形态（Delivery Profile） | 报告、图册、海报、Web 和移动端的媒介约束 |
| — | 数据空间契约（Data/Spatial Contract） | 字段、单位、几何、CRS、时间、范围和数据质量 |
| — | 符号与标准目录 | 通用点线面文字资源，以及测绘、地质、规划等权威符号 |

核心判断标准不是“源文件有多完整”，而是“哪些规则值得跨项目稳定复用”。这与 [Create Template 工作流](../../skills/ppt-master/workflows/create-template.md) 的分类原则一致。

### 2. 模板是“语义规范 + 可执行原型”，不是最终作品

项目中的 Layout 模板同时具有以下内容：

- `design_spec.md`：供人和智能体阅读的规则。
- SVG 原型：可以直接预览、编译和编辑。
- 机器元数据：Master、Layout、Placeholder 和 Bounds。
- JSON 索引：负责模板发现与选择。
- 校验器：验证规范、原型和资产之间的一致性。

例如，`presentation_core` 在 [Design Spec](../../skills/ppt-master/templates/layouts/presentation_core/templates/design_spec.md) 中声明页面类型和占位槽；具体的 [图表洞察 SVG](../../skills/ppt-master/templates/layouts/presentation_core/templates/19_chart_insight.svg) 又声明结构身份、槽位、边界和原生数据对象。

地图模板也应采用相同的双重表达：

- 人类可读层说明为什么这样制图、适用什么数据以及何时不能使用。
- 机器可执行层声明字段绑定、图层顺序、比例尺范围、分类方式、符号映射和布局区域。

### 3. 选择模板不等于复制模板

PPT Master 中的图表 SVG 只是灵活参考，项目数据与当前设计规范仍拥有最终语义，参见 [图表模板运行边界](../../skills/ppt-master/templates/charts/README.md#runtime-boundary)。

对应到地图系统：

- 选择 `choropleth/sequential` 不代表固定使用五级蓝色。
- 模板定义“数值如何映射为区域颜色”。
- 当前项目决定实际字段、分类断点、颜色、行政区范围和输出介质。
- 示例数据只用于验证容量，不能成为最终业务数据。

### 4. 明确事实、决策、建议和推导结果

PPT Master 在模板创建过程中区分四类来源：

- `[fact]`：由数据或文件直接观测到的事实。
- `[decision]`：用户明确作出的决定。
- `[suggested]`：模型给出的建议。
- `[derived]`：运行时根据其他信息推导出的值。

这一做法对地图制图尤其重要。例如：

- `EPSG:4490` 可能是数据事实。
- 最终采用 Albers 投影可能是系统推导结果。
- 使用七级分级可能只是模型建议。
- 输出 A3 横版是用户决定。

### 5. 每个分段只有一个所有者

PPT Master 不合并多个模板规范正文，而是在消费时确定每个分段的唯一所有者；例如存在 Layout 时由 Layout 拥有结构，参见 [模板应用与优先级规则](../../skills/ppt-master/workflows/stages/apply-template-workspace.md#5-segment-precedence-is-resolved-while-reading)。

地图侧建议采用类似的所有权关系：

| 分段 | 所有者 |
|---|---|
| 数据含义、单位、时间和空间参考 | 数据契约 |
| 业务所需图层及成果要求 | MapScenario |
| 数值到视觉变量的映射 | Map Encoding |
| 图层视觉层级、标注和概化 | MapStyle |
| 页面或屏幕空间结构 | Map Layout |
| Logo、机构字体和品牌色 | Identity |
| 当前范围、时间、数据快照和分类断点 | 项目实例锁 |

不要通过“平均”“混搭”处理冲突。两个模板竞争同一分段时，应根据显式优先级选择唯一决策所有者；其他分段仍可提出兼容性约束，无法兼容时直接报告冲突。

### 6. 使用统一生命周期管理模板

PPT Master 的模板生命周期是：参考材料分析、基于事实的方案、用户确认、创建、验证、预览、注册和应用，参见 [Create Template 流程概览](../../skills/ppt-master/workflows/create-template.md#process-overview)。

地图模板也应经过类似流程，避免未经验证的文件直接进入模板库：

1. 分析参考地图、样式文件、数据和业务说明。
2. 区分事实、决策、建议和推导值。
3. 确认模板类型、用途、输出媒介和约束。
4. 创建规范、原型、数据绑定和资源。
5. 执行语义、空间、视觉和技术校验。
6. 生成预览和测试报告。
7. 注册到该类型唯一的发现索引。
8. 在项目中安装并生成实例锁。

## 二、建议的地图模板体系

### 1. 地图身份模板

地图身份模板只拥有机构身份，建议包含：

- 品牌主色和辅助色，但不得覆盖具有固定语义的警戒色、风险色。
- 字体栈及多语言字体回退。
- Logo、署名、版权和保密标记。
- 机构自有图标与品牌资产；不包括通用专题符号和行业标准符号。
- 品牌资源的使用范围、净空和尺寸限制。

它不应包含投影、图层结构、具体地图范围和业务字段。

### 2. 制图表达规范

制图表达规范描述可跨地域、跨项目复用的制图判断，建议包含：

- 底图、主题层、标注、注记和强调对象之间的视觉层级。
- 点、线、面和栅格数据的默认符号语言。
- 标签优先级、避让、缩写、多语言和最小字号规则。
- 比例尺分级显示与几何概化规则。
- 缺失值、不确定性、预测值和敏感数据的表达方式。
- 色盲安全、灰度打印和对比度策略。
- 图例组织、数值格式、单位和来源表达。
- 推荐表达及明确的禁用条件。

它不应包含固定地区、固定字段名或固定纸张布局。

### 3. 地图版式模板

地图版式应设计为带语义槽位的约束系统，而不是一张绝对坐标截图。典型槽位包括：

- `map_frame`
- `title`、`subtitle`
- `legend`
- `scale_bar`
- `north_arrow`
- `locator_map`、`detail_inset`
- `source_note`
- `timestamp`
- `projection_note`
- `disclaimer`
- `chart_panel`、`table_panel`

每个槽位应声明：

- 边界和安全区。
- 最小与最大尺寸。
- 是否可省略。
- 容量，例如最大图例项数。
- 锚点、对齐和内容溢出策略。
- 与其他槽位的排斥、缩放或重排关系。

这相当于 PPT Master 中的 `data-pptx-bounds`：边界代表完整设计区域，而不是示例内容的紧包围盒，参见 [PPTX 结构接口](../../skills/ppt-master/references/pptx-structure-interface.md#2-explicit-pptx-master--layout--placeholder-metadata)。

### 4. 制图场景方案

制图场景方案适合封装可重复使用的稳定业务场景，例如：

- 城市规划现状图。
- 洪涝风险研判图。
- 应急资源态势图。
- 国土空间用途管制图。
- 区域经济统计图。
- 导航或物流运营地图。

它应包含：

- 使用场景、受众和决策目标。
- 所需的数据角色，而不是具体文件路径。
- 推荐的地图表达组合。
- 标准图层图谱。
- 输出介质和更新频率。
- 典型构图原型。
- 质量、审图和合规要求。

场景说明保持描述性；真正强制的字段、类型和单位应放入独立的数据 Schema，避免把自然语言当作机器校验规则。

MapScenario 可以像 PPT Master 的 Deck 一样成为集成式工作区，拥有场景合同、配套身份、版面结构和完整原型。若同时选择外部 MapBrand、MapStyle 或 MapLayout，应按完整分段覆盖内部对应分段，不能逐字段混合。当前数据文件、实际范围、时间快照和分类断点始终不属于 MapScenario。

### 5. 地图表达目录

地图表达目录最接近 PPT Master 的 Chart/Table Catalog。每一种表达应按信息关系注册，而不是按颜色或视觉外观命名。

| 编码模板 | 适用场景 | 禁止或谨慎使用 |
|---|---|---|
| `choropleth/sequential` | 行政区比率、密度和标准化指标 | 未标准化的绝对数量 |
| `graduated-symbol/count` | 点或区域上的绝对数量 | 符号重叠严重且无法聚合 |
| `dot-density/distribution` | 展示空间分布密度 | 点位置可能被误解为真实个体位置 |
| `flow/od-weighted` | 起讫关系和流量 | 无方向或无权重的关系 |
| `surface/isoline` | 连续空间场 | 离散类别数据 |
| `change/diverging` | 具有明确零点的增减变化 | 没有语义中点的数据 |
| `uncertainty/bivariate` | 同时表达数值和可信度 | 面向低认知容量的公众快速阅读 |
| `network/route` | 道路、管线和路径连通性 | 普通空间邻近关系 |

每个目录项至少需要：

- `best_for` 和 `skip_if`。
- 所需的数据角色和字段类型。
- 数据到视觉变量的映射。
- 图例、单位、缺失值和异常值规则。
- 小型合成示例数据。
- 不带项目品牌的中性预览。
- 可自动执行的语义与渲染测试。

## 三、推荐的目录组织

```text
map-template-library/
├─ identities/
│  └─ <identity_id>/
│     ├─ manifest.yaml
│     ├─ identity.yaml
│     └─ assets/
├─ styles/
│  └─ <style_id>/
│     ├─ manifest.yaml
│     └─ cartography.yaml
├─ layouts/
│  └─ <layout_id>/
│     ├─ manifest.yaml
│     ├─ layout.yaml
│     ├─ prototypes/
│     └─ previews/
├─ scenarios/
│  └─ <scenario_id>/
│     ├─ manifest.yaml
│     ├─ scenario.yaml
│     ├─ bindings/
│     │  ├─ data.schema.yaml
│     │  └─ layer-graph.yaml
│     ├─ prototypes/
│     └─ assets/
├─ visualizations/
│  ├─ index.json
│  └─ <family>/<key>/
│     ├─ encoding.yaml
│     ├─ fixture.geojson
│     ├─ neutral-preview.svg
│     └─ tests.yaml
├─ schemas/
└─ adapters/
   ├─ mapbox/
   ├─ qgis/
   └─ arcgis/
```

每种模板维护唯一索引。智能体只从索引发现模板，不通过扫描目录或模糊名称猜测模板路径。这与 PPT Master 的索引设计一致，参见 [模板工具说明](../../skills/ppt-master/scripts/docs/template-tools.md#register_templatepy)。

单个模板工作区可采用以下内部结构：

```text
<template_workspace>/
├─ manifest.yaml              # ID、类型、版本、摘要、标签和兼容性
├─ spec/                      # 人类可读的可复用规则
├─ contracts/                 # 数据、图层、比例尺和标注机器契约
├─ prototypes/                # 可执行地图原型
├─ assets/                    # 符号、纹理、字体声明和精灵图
├─ fixtures/                  # 小型合成测试数据
├─ previews/                  # 派生预览，不作为生成输入
└─ tests/                     # 语义、空间、视觉和性能测试
```

可选目录只在确实存在资产时创建，预览文件不能成为模板运行时输入。

## 四、地图模板必须增加的专有契约

PPT 模板体系没有覆盖、但地图模板必须拥有以下契约。

### 1. 数据契约

定义几何类型、字段类型、单位、连接键、空值策略、时间字段、数据新鲜度、来源和许可。例如：

```yaml
roles:
  thematic_regions:
    geometry: [Polygon, MultiPolygon]
    required_fields:
      region_id: string
      risk_rate: number
      population: number
    join_key: region_id
    measure_kind: rate
    null_policy: explicit-no-data
```

### 2. 空间契约

定义：

- 输入 CRS 与输出 CRS。
- 适用地理范围和投影选择策略。
- 允许的比例尺或缩放级别。
- 反经线、极区和投影畸变处理。
- 几何有效性和拓扑要求。

投影不应被简单当作视觉风格；它会改变空间测量和形状含义。

### 3. 图层图谱

定义：

- 图层顺序和父子关系。
- 遮罩、裁剪和混合关系。
- 最小与最大可见比例尺。
- 标注、选择、高亮和禁用状态。
- 图层之间的数据依赖和 Join 关系。

### 4. 数据到符号映射

定义：

- 分类算法、级数和断点来源。
- 标准化字段或分母。
- 连续、分级、发散和类别色阶。
- 异常值、缺失值和不确定性。
- 图例与地图编码的同步规则。

### 5. 多尺度行为

定义不同缩放级别下的：

- 数据筛选与聚合。
- 几何简化。
- 线宽和符号尺寸。
- 标签显示与优先级。
- 聚类、抽稀和细节加载策略。

### 6. 多输出适配

定义：

- 印刷 DPI、出血、安全区和颜色模式。
- Web 地图的 hover、click、filter、time 和 layer toggle。
- 瓦片大小、资源预算和首屏性能。
- 移动端布局和交互安全区。
- SVG、PDF、PNG 和交互式地图的回退关系。

### 7. 地图质量门禁

至少应覆盖：

- CRS 一致性和几何有效性。
- Join 覆盖率和字段类型。
- 分类方法与数据分布是否匹配。
- 原始数量是否被错误用于分级设色。
- 单位、图例、数据来源和时间是否完整。
- 标签冲突、遮挡和最小可读尺寸。
- 色盲可读性、灰度打印和对比度。
- 数据许可、署名和敏感信息合规。
- 不同渲染引擎之间的输出一致性。
- 大数据量、瓦片和交互性能。

## 五、增加项目实例锁

模板只表达可复用规则。每次制图应生成一份 `map_lock.yaml`，冻结本次项目的具体决定：

```yaml
crs: EPSG:4490
extent: [xmin, ymin, xmax, ymax]
output: a3-landscape
data_snapshot: 2026-09-10
scenario: emergency-situation
style: operational-clear
layout: print-map-a3
encoding: choropleth/sequential
value_field: risk_rate
normalization: population
classification:
  method: jenks
  classes: 5
layer_order: []
label_policy: {}
resolved_assets: []
```

实例锁还应保存：

- 所选模板的 ID 和版本。
- 数据源版本、时间戳和文件哈希。
- 解析后的优先级和冲突处理结果。
- 最终范围、投影、分级断点、调色板和图层顺序。
- 渲染目标及其适配器版本。

这样模板更新不会悄悄改变已经生成的地图，也能够完整复现一次制图决策。

## 六、建议的运行流程

```text
数据与参考材料接入
→ 数据、空间和业务事实分析
→ 基于事实的地图任务简报
→ 用户确认关键决策
→ 选择并安装模板分段
→ 生成可修改的 MapPlan
→ 绑定数据角色和字段
→ 生成地图
→ 语义、空间、视觉和性能校验
→ 预览与必要修复
→ 冻结 MapSpecLock
→ 导出并登记产物
```

关键确认项应包括地图目的、受众、输出媒介、地理范围、数据时间、投影策略、核心指标和表达方式。能够从数据可靠推导的值不必让用户选择，但必须记录为推导结果。

## 七、最小可行落地顺序

第一阶段不宜追求海量模板，建议依次完成：

1. 建立统一的 `manifest.yaml`、Schema、索引和实例锁格式。
2. 实现 8～10 个地图表达模板。
3. 实现两个 Layout：A4/A3 打印地图和 Web Dashboard。
4. 实现一个通用分析制图 Style。
5. 实现一个真实业务 MapScenario，例如“城市统计专题图”。
6. 建立数据、空间、制图语义和视觉回归校验器。
7. 先实现 Mapbox 或 QGIS 中的一个编译适配器，再扩展到其他引擎。

最关键的设计原则是：

> 模板保存稳定的制图判断，实例锁保存当前项目决定；渲染适配器不得改变制图语义，但必须报告能力差异，并按显式降级策略实现等价或近似输出。

## 八、外部方案比较与吸收结论

本节比较另一份《地图模版系统》方案与本文初始方案，并给出合并取舍。外部方案的优势是模板种类、规格章节、索引、原型和符号库更加具体；本文初始方案的优势是数据空间契约、交付形态、实例锁、质量门禁和引擎边界更符合地图领域。

| 外部方案内容 | 评价 | 合并决定 |
|---|---|---|
| MapBrand / MapStyle / MapLayout / MapScenario 四类工作区 | 有利于分段选择与组合 | 采纳，但称为“分段所有权”，不称完全正交 |
| 容器以 kind + id 消歧 | 能避免同名模板和裸目录猜测 | 采纳，并要求 Manifest 与唯一索引 |
| Brand/Style 只有规格，Layout/MapScenario 带原型 | 边界清楚，接近可执行模板 | 采纳 |
| 中性 SVG 预览 | 便于脱离项目审查结构 | 采纳，但语义色和行业标准符号不得中性化 |
| `map_type/<key>` 灵活引用 | 适合规划阶段进行表达召回 | 采纳，但数据角色和视觉变量映射不能任意改变 |
| MapDesignSpec + MapSpecLock | 人类判断与机器执行分离 | 采纳，并增加可修改的 MapPlan 中间态 |
| 确认合同后读取模板 | 可避免模板反向塑造用户意图 | 修正为确认前只读索引/Manifest，确认后读完整内容 |
| `standard / fidelity / mirror` | 适合记录模板创建来源 | 采纳为创建溯源，不作为用户使用模式 |
| Layout 中 `2970 × 2100 mm` | 物理尺寸和 SVG 坐标混淆 | 不采纳；拆成 `297 × 210 mm` 与独立 viewBox |
| `page_count` 表示 Layout SVG 数量 | 容易误认为成果页数 | 改为 `prototype_count` |
| Base frame、Legend、Inset 分别作为 Layout 页面 | 把组件碎片和完整原型混为一谈 | 不采纳；原型必须完整，碎片进入 `components/` |
| Web/Mobile 仅用固定比例 SVG 表达 | 无法覆盖响应式和交互状态 | 不采纳；必须增加交互与断点合同 |
| `flat / structured` 与 Master/Layout 映射 | 属于 PowerPoint 编译模型 | 不直接迁移；地图改用 static / responsive / atlas-series 等组合模式 |
| 底图快照作为普通模板输入 | 有许可、过期、投影和体积风险 | 默认不采纳；保存版本化来源描述，快照只用于测试或离线许可场景 |

### 1. 组合后的核心架构

```text
制图沟通合同
      │
      ▼
MapBrand + MapStyle + MapLayout + MapScenario
      │             │
      │             ├─ Delivery Profile
      │             ├─ Map Encoding Catalog
      │             ├─ Symbol Catalog / Standard Profile
      │             └─ Data / Spatial Contract
      ▼
MapPlan → 数据绑定与预检 → 预览与修复 → MapSpecLock
      ▼
QGIS / Mapbox / ArcGIS 等渲染适配器
```

分段优先级建议为：

| 分段 | 决策所有者 |
|---|---|
| 场景合同 | MapScenario |
| 组织身份 | 显式 MapBrand，否则 MapScenario 内置身份 |
| 制图表达规范 | 显式 MapStyle，否则 MapScenario 内置表达规范 |
| 版面结构 | 显式 MapLayout，否则 MapScenario 内置结构 |
| 交付约束 | Delivery Profile；可以限制版面和字号，但不改写数据语义 |
| 数据编码 | Map Encoding 与当前数据共同决定 |
| 法定符号 | Standard Profile，优先于 Brand 和 Style |
| 最终实例值 | MapSpecLock |

覆盖以完整分段为单位。外部 MapLayout 覆盖 MapScenario 结构时，不能保留一半内部图例区再混入一半外部地图框。

## 九、四类模板的具体契约

### 1. MapBrand：制图机构身份

| 项目 | 合同 |
|---|---|
| 拥有 | 组织色板、字体身份、Logo、机构署名、版权与保密标识、品牌自有资产 |
| 不拥有 | 地图版面结构、地图类型、数据符号化、CRS、范围和行业标准符号 |
| 文件 | `templates/design_spec.md`，以及可选 `assets/logos/`、`assets/fonts/`、`assets/icons/` |
| 原型 roster | 无 |

建议六节结构：

```text
I. Brand Overview
II. Brand Color Tokens
III. Brand Typography
IV. Logo and Organization Marks
V. Attribution and Legal Identity
VI. Brand Assets and Usage Constraints
```

MapBrand 的颜色只定义身份 token，例如 Primary、Secondary、Accent、Surface、Ink。水体、陆地、行政边界、风险等级等颜色属于 MapStyle、Map Encoding 或行业标准。颜色必须记录 `official / approximate / inferred` 来源，并声明是否允许参与数据编码。

Logo 规格拥有文件、变体、净空、最小尺寸、禁用方式和允许锚区；具体页面坐标由 MapLayout 决定。数据来源引用格式通常属于制图或合规合同，MapBrand 只拥有机构署名和法定身份字符串。

### 2. MapStyle：制图表达规范

| 项目 | 合同 |
|---|---|
| 拥有 | 可复用的制图表达原则、视觉层级、标注与综合化原则、非约束视觉默认 |
| 不拥有 | 当前项目合同、组织身份、地图版面几何、具体数据与最终分类断点 |
| 文件 | `templates/design_spec.md`；不携带资产和 SVG roster |

建议七节结构：

```text
I. Style Overview
II. Cartographic Communication Method
III. Map Role Vocabulary
IV. Data and Symbolization Discipline
V. Visual System Defaults
VI. Basemap, Symbol and Legend Direction
VII. Review Focus
```

外部方案中的 `topological / thematic / statistical / narrative` 混合了空间关系、地图用途、数据表达和沟通方法，不应作为单一枚举。建议拆成：

```yaml
communication_method: explanatory | exploratory | operational | navigational | narrative
spatial_emphasis: context | distribution | topology | movement | comparison | change
```

Map Role Vocabulary 描述一张地图承担的任务，如 context、thematic-evidence、comparison、route、suitability；正式的 choropleth、flow 等编码仍由 Map Encoding Catalog 拥有。Style 可以规定分类选择逻辑，但最终方法、级数和断点由数据分析确定并写入 MapSpecLock。

Style 的 Review Focus 只承载风格性复查。CRS、Join、分类正确性、图例一致性和敏感信息检查属于始终运行的质量门禁。

### 3. MapLayout：品牌中性版面

| 项目 | 合同 |
|---|---|
| 拥有 | 画布、地图框、标题块、图例区、比例尺槽、指北针槽、inset 槽、页边信息区及其空间约束 |
| 不拥有 | 组织身份、制图表达规范、业务应用、实际数据、CRS、地理范围和专题符号 |
| 文件 | `templates/design_spec.md` + 完整 SVG 原型；交互布局另带机器状态合同 |

MapLayout 拥有输出画布，不拥有地理范围。印刷画布必须分离物理尺寸与 SVG 逻辑坐标：

```yaml
---
layout_id: report_a4_landscape
kind: map-layout
category: report
summary: A4 横向报告嵌入式地图版面
delivery_profile: print
canvas:
  format: A4-landscape
  physical_width_mm: 297
  physical_height_mm: 210
  viewbox: "0 0 2970 2100"
  safe_margin_mm: 12
  bleed_mm: 0
creation_mode: standard
prototype_count: 6
layout_types:
  - cover_map
  - thematic_full
  - map_legend_right
  - comparison_dual
  - inset_detail
  - map_chart_split
---
```

`prototype_count` 只表示可用原型数量，不限制最终地图页数。每个 SVG 必须是包含完整结构上下文的版面原型；Legend、Inset、Scale Bar 等可复用碎片若要单独维护，应进入 `components/`。

槽位不能只是可见 `{{...}}` 文本，还应具有机器类型、边界、容量和条件：

```yaml
slots:
  map_frame:
    type: map
    required: true
    bounds: [120, 220, 2080, 1600]
  legend:
    type: generated-legend
    required: conditional
    max_items: 9
  scale_bar:
    type: generated-scale-bar
    required: conditional
  north_arrow:
    type: generated-north-arrow
    required: conditional
```

双图共享图例要求相同指标、分类域、断点和符号映射；共享比例尺要求两图具有相同比例尺与兼容 CRS。否则必须使用独立槽位。

首批 Layout 可采用：

| Layout | 画布 | 原型数 | 定位 | 额外要求 |
|---|---|---:|---|---|
| `report_a4_landscape` | A4 横向 | 6 | 报告嵌入式地图 | 无出血或由报告系统控制 |
| `atlas_a3_portrait` | A3 纵向 | 8 | 图册页 | 奇偶页装订边、图幅号、接图表、共享图例 |
| `poster_a1_portrait` | A1 纵向 | 4 | 展板地图 | 远距离可读性、多 inset 容量 |
| `web_16x9` | 16:9 视口 | 5 | Web 展示 | 响应式断点和交互状态合同 |
| `mobile_9x16` | 9:16 参考视口 | 4 | 移动端 | 安全区、触控目标、横竖屏和弱网策略 |

Web 与 Mobile 的比例只是参考视口，不能代替响应式布局合同。

### 4. MapScenario：制图场景方案

MapScenario 是面向一类可重复制图场景的集成方案，拥有场景合同、配套身份、版面结构和实际原型；它不是当前项目实例或一次性制图执行计划。

| 项目 | 合同 |
|---|---|
| 拥有 | 循环应用、受众与结果、数据角色、图层角色、集成身份、集成结构、原型和质量要求 |
| 不拥有 | 当前数据路径、实际范围、时间快照、最终分类断点和渲染器运行状态 |
| 文件 | `templates/design_spec.md` + 完整 SVG/交互原型 + 实际使用的资产与数据角色 Schema |

建议章节为 Template Overview、Color Scheme、Typography、Signature Design Elements、Page/Map Roster、Assets、Placeholder Overrides。其 `page_count` 同样应改为 `prototype_count`。例如：

- `monthly-territory-map`：月度销售区域分析制图场景方案。
- `annual-urban-atlas`：年度城市规划图册制图场景方案。

## 十、地图表达与符号目录

### 1. Map Encoding Catalog

地图类型目录应按信息关系注册，并使用唯一索引与规划词汇表：

```text
map_types/
├─ map_types_index.json
├─ map_type_vocabulary.md
└─ <key>/
   ├─ encoding.yaml
   ├─ fixture.geojson
   ├─ neutral-preview.svg
   └─ tests.yaml
```

外部方案提出的 key 可以吸收，但应进一步分类：

| 家族 | key | 说明 |
|---|---|---|
| 区域编码 | `choropleth` | 标准化区域指标的分级或连续着色 |
| 点与数量 | `dot_density`、`proportional_symbol` | 密度分布或数量大小映射 |
| 运动与关系 | `flow_map` | 起讫方向与流量宽度编码 |
| 连续表面 | `isarithmic`、`heatmap` | 等值线或连续密度表面 |
| 变形表达 | `cartogram` | 面积变形编码非空间变量 |
| 分析结果 | `buffer_zone`、`suitability_overlay` | 距离或多因子分析产物，不只是视觉样式 |
| 系列协调 | `time_series_map` | 多时相地图的范围、分类和图例一致性合同 |

每个 key 的索引摘要采用 `Pick for ... Skip if ...` 诊断句式。选择一个 key 不锁死最终几何，但必须保留其数据角色、视觉变量和单调映射。例如 flow map 可以调整线宽范围，却不能把权重关系改成无权线网。

地图表达不应只保存一张 SVG。SVG 是中性预览；真正的执行权威应是 `encoding.yaml` 和测试数据，因为地图几何来自地理数据、投影和当前范围。

### 2. Symbol Catalog 与 Standard Profile

| 目录 | 内容 | 边界 |
|---|---|---|
| `point-markers` | 圆、方、三角、星和自定义标记 | 定义锚点、尺寸、旋转和状态通道 |
| `line-styles` | 实线、虚线、点划、套线 | 流箭头和等高线还需要语义合同，不能只当线型 |
| `fill-patterns` | 实色、纹理、点纹、网格和晕线 | 渐变只有在表达连续量或方向时才承担语义 |
| `cartographic-annotations` | 文字角色、字形和字位参考 | 具体避让和比例尺行为仍由 MapStyle/Lock 决定 |
| `standard-symbols` | 测绘、地质、规划等行业符号 | 必须记录发布机构、版本、辖区、比例尺和许可 |

项目只同步实际选中的符号资源，但索引不是执行白名单。法定或行业标准符号不得被 Brand 任意重着色，也不得用外观相似的普通图标替换。

## 十一、工作区、索引与渐进式读取

推荐在现有通用目录上增加明确 kind 目录与唯一索引：

```text
map-templates/
├─ brands/<id>/templates/design_spec.md
├─ styles/<id>/templates/design_spec.md
├─ layouts/<id>/templates/{design_spec.md, *.svg}
├─ scenarios/<id>/templates/{design_spec.md, *.svg}
├─ delivery-profiles/
├─ map_types/
├─ symbols/
├─ standards/
├─ schemas/
├─ scaffolds/
└─ adapters/
```

库内通过 `<kind>/<id>/` 容器确定类型和 ID，统一使用 `templates/design_spec.md`；项目内安装后使用 `design_spec.<kind>.<id>.md`，从而允许不同 kind 共存。每类模板只从自己的 `*_index.json` 发现，不扫描目录补全注册表，也不根据裸名称猜测路径。

模板读取分两级：

1. 合同确认前只读取索引和 Manifest，包括 ID、摘要、数据前提、输出媒介、CRS/比例尺适用范围、引擎兼容性、依赖、冲突和许可。
2. 合同确认并选定模板后，才读取完整 Design Spec、原型、符号和绑定合同，并安装到项目本地；大型底图可使用版本化 URI 与内容哈希，不强制复制。

创建策略只记录模板来源：

| 策略 | 含义 |
|---|---|
| `standard` | 从规则和参考材料新建紧凑、可复用模板 |
| `fidelity` | 基于完整参考材料设计更广的原型范围 |
| `mirror` | 仅在源 GIS 工程可完整解析时保留其受支持结构和语义 |

该策略不要求未来项目保持源页面数、图层顺序或具体数据。

## 十二、MapDesignSpec、MapPlan 与 MapSpecLock

### 1. MapDesignSpec

外部方案的十节设计规范可以吸收为项目级人读文档：

1. 制图项目信息与沟通合同。
2. 空间规范。
3. 视觉主题与底图策略。
4. 字体和地图文字角色。
5. 版面原则与跨图连续性。
6. 符号与行业标准。
7. 地图表达引用。
8. 数据资源和处理策略。
9. 地图/图幅大纲。
10. 来源、不确定性与制图说明。

### 2. MapPlan

MapPlan 是可以修改的执行计划，记录模板选择、数据角色绑定候选、地图 roster、版面选择和待决问题。它允许在数据预检和预览后调整。

### 3. MapSpecLock

MapSpecLock 使用有 Schema 的 YAML，而不是 Markdown 中的半结构化键值行。它在数据绑定、预览和能力协商完成后冻结，至少包含：

```yaml
templates:
  brand: {id: null, version: null}
  style: {id: null, version: null}
  layout: {id: null, version: null}
  scenario: {id: null, version: null}

spatial:
  source_crs: null
  working_crs: null
  display_crs: null
  measurement_crs: null
  extent: null
  scale_or_zoom: null

data:
  sources: []
  hashes: []
  joins: []
  transformations: []

encoding:
  map_type: null
  field: null
  normalization: null
  classification_method: null
  breaks: []
  palette: []
  null_symbol: null

layers: []
labels: []
pages_or_views: []
resolved_assets: []
forbidden_rules: []

renderer:
  adapter: null
  version: null
  capability_fallbacks: []
```

MapSpecLock 中不使用 PPT 特有的 `masters`、`layouts`、`page_layouts` 映射。地图组合模式可以另行声明为 `static`、`responsive`、`atlas-series` 或其他地图原生模式。

## 十三、补充质量门禁

除本文前述质量检查外，模板系统还应验证：

- MapBrand 不得包含 Water、Land、Border 等底图语义 token，除非它本身是 MapScenario 的集成身份/表达规范分段。
- MapStyle 不得包含固定画布、Logo、具体数据路径或最终断点。
- MapLayout 的物理尺寸、viewBox、槽位和 roster 必须相互一致。
- MapScenario 内部各分段必须完整；外部同 kind 覆盖时必须整段替换。
- MapType 的索引、词汇表、执行合同和 fixture 数据集合必须一致。
- 中性预览不得抹掉风险色、行业标准色、顺序关系或不确定性编码。
- 地理概化允许改变节点和位置，但必须满足拓扑、最大位移、最小保留面积及比例尺误差约束。
- Web/Mobile 原型必须具有响应式、交互和性能合同，不能仅以固定 SVG 通过验证。

---

## 常见问题

### Q1: 什么叫分段所有权，如何执行？

**分段所有权**是指：把一份完整的地图设计拆成几段（身份、方法、版面、产品、数据→符号映射），每段只有一个模板说了算，不能两个模板同时拥有同一段。

用装修房子打比方：

| 段 | 谁说了算 | 举个例子 |
|---|---|---|
| 户型怎么改 | 结构设计师 | 这面墙能不能拆 |
| 风格长什么样 | 业主 | 要北欧风还是中式 |
| 水电怎么走 | 水电工程师 | 管线走顶还是走地 |
| 预算花多少 | 业主 | 总共花 20 万还是 50 万 |

结构设计师只管户型，不插手业主选什么颜色的墙；水电工程师只管管线，不管最终摆什么家具。如果出现冲突（业主要好看、水电工程师要方便维修），不是两个人投票"平均一下"，而是按优先级规则判定谁说了算，判定不了就直接报告冲突让业主拍板。

映射到地图模板系统：

| 段 | 谁拥有 | 举个例子 |
|---|---|---|
| 机构身份 | Identity | 测绘局的蓝色、黑体字、机构 Logo |
| 制图表达规范 | MapStyle | 极简表达、标注避让规则、概化策略 |
| 版面骨架 | Map Layout | A3 横版、图框在左、图例在右 |
| 制图场景方案 | MapScenario | 应急态势图的图层组合和业务场景 |
| 数据→符号映射 | Map Encoding | 行政区按风险率着色、五级蓝色渐变 |

Identity 不插手地图框放哪里；MapStyle 不插手用什么品牌色；MapLayout 不插手图层顺序怎么排。如果 MapStyle 说"底图用灰色"而 Identity 说"底图用白色"——Identity 赢，因为颜色身份归 Identity，MapStyle 的颜色只是"没选 Identity 时的默认回退"。

核心三条规矩：

1. **每段只有一个说了算的人**——不能两个人同时拥有同一段
2. **冲突不混搭，按优先级判定**——判不了就报冲突，不能各退一步搞折中
3. **没选模板的段，用自由设计**——不是每段都必须选模板，可以什么都不选自己做

#### 决策流程

分段所有权**不是每一段依次决策**的。很多人会以为流程是"先选品牌 → 再选风格 → 再选版面 → 最后选产品"，像流水线一样一段一段来。实际不是这样。

用装修继续打比方，装修的真实流程是：

1. 业主跟设计师坐下来聊——"我要装修一套房，给三口人住，预算 30 万，喜欢北欧风"。这是定"做什么"，不是定"每段谁来做"。
2. 设计师拿出几个方案：北欧风全包 / 极简半包 / 自由发挥。业主选一个，或说"我都不选，自己来"。
3. 选了"北欧风全包"后自动带入了风格方案、施工队、材料供应商。此时"水电归水电工程师""风格归业主"这些分段所有权是在安装时自动生效的，不是业主逐个去指定。
4. 施工时按规则执行——水电工程师看自己的合同做水电，设计师看自己的合同做设计，业主看自己的合同做风格决策。如果冲突，按优先级判，判不了就报回来问业主。

关键点：**业主不需要走完"水电选择""瓦工选择""木工选择"的逐项菜单。业主只说"我要什么"，系统自动把对应的分段所有权安装到位。**

映射到模板系统的真实决策流程：

**第一步：确认制图合同（定"做什么"）**
→ 地图主题是什么、给谁看、输出什么媒介、核心信息是什么
→ 此时还没有选任何模板

**第二步：选择模板（定"用不用预制方案"）**
→ 系统从索引中展示候选模板
→ 用户可以选一个或多个，也可以选"自由设计"（什么都不选）
→ 所有分段的选择是同时确认的，不是依次的

**第三步：安装 + 所有权自动解析**
→ 系统把选中的模板安装到项目本地
→ 安装时自动确定每段的所有者
→ 如果两个模板竞争同一段，按优先级判；判不了报冲突

**第四步：生成实例锁（冻结决策快照）**
→ 把"这次制图用了哪些模板、数据源是什么、CRS 是什么、分级方法是什么"全部冻结成一份锁文件

**第五步：制图执行**
→ 执行器读实例锁，按锁定的规则制图
→ 每段读对应所有者的规则，不越界

#### 一个具体例子

假设要制一张"城市洪涝风险研判图"：

| 步骤 | 发生了什么 | 用户做了什么 |
|---|---|---|
| 第一步 | 确认制图合同：面向应急指挥中心、A3 印刷、核心信息是高风险区域分布 | 用户回答几个问题 |
| 第二步 | 系统展示候选：有 `emergency-situation` 产品模板、`operational-clear` 风格、`print-map-a3` 版面 | 用户说"用这套" |
| 第三步 | 系统自动安装三个模板，解析出：颜色归 Identity、制图表达规范归 MapStyle、版面归 MapLayout、图层组合归 MapScenario | 用户什么都不用做 |
| 第四步 | 生成实例锁：CRS=EPSG:4490、encoding=choropleth/sequential、classification=jenks/5 | 用户确认数据源和关键参数 |
| 第五步 | 执行器按锁制图 | 自动完成 |

用户从头到尾没有逐个"选品牌 → 选风格 → 选版面 → 选产品"。用户只做了两件事：说清楚要做什么 + 选一套预制方案（或自由设计）。后面全是系统自动解析的。

核心理解：

| 误区 | 实际 |
|---|---|
| 每段依次决策，像点菜单一样逐项选 | 先定整体需求，再一次性选模板包，系统自动分配所有权 |
| 用户需要理解"分段"概念 | 用户不需要理解分段，分段是系统内部的冲突解决机制 |
| 每段都要选一个模板 | 可以全选、可以部分选、可以都不选（自由设计） |
| 所有权是用户指定的 | 所有权是安装时根据优先级规则自动解析的 |

> 一句话总结：**用户只管"我要什么"和"用不用预制方案"，分段所有权是系统在安装时自动解析的内部机制，对用户透明。**
