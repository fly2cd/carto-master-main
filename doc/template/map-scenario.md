# MapScenario 完整说明

## 1. 文档定位

本文介绍 Carto Agent 模板体系中 MapScenario 的基本概念、作用、职责边界、六份业务契约、组件装配、匹配方式、实例编译、验证要求和发布产物。

组织方式参考 [MapLayout 完整说明](map-layout.md)，并与 [MapStyle 完整说明](map-style.md) 配套。设计依据为 [模板体系设计](../carto-template-dsg.md)、[模板创建 TRD](../carto-create-template-TRD.md) 和 [地图生成 TRD](../carto-generate-map-TRD.md)。本文供模板作者、业务方案设计者、编译器开发者和审核人员使用。

本文是设计说明。第 18 节集中列出当前仓库状态；其余章节中的目标接口、匹配状态和扩展流程，除明确标注为现有实现外，均为建议设计。示例不能直接作为当前 CLI 的完整输入。运行时协议仍以 `skills/carto-agent/schemas/`、`policies/`、权威索引和已发布模板为准。

表达目录、内置方法、通用图表和符号资源的共同边界，见[地图表达目录、内置方法与符号库设计结论](map-expression-and-symbol-design.md)。本文统一使用 Map Expression Catalog；表达定义不属于新的模板类型，也不包含任意可执行代码。

## 2. 基本介绍

MapScenario 的中文名称为“制图场景方案”。它是可复用、版本化、可校验的业务制图模板，规定一类地图要表达什么、需要什么数据、遵循什么空间与表达约束，以及怎样判断成果合格。

MapScenario 回答：

> 为了完成这类业务任务，需要哪些地图内容、数据角色和表达关系，如何装配成图，并满足哪些使用与交付条件？

例如，“洪涝成果与避难设施概览”可以规定需要风险面和避难点，以有序面表达展示一个已提供的指标，以面积正比点符号展示设施容量，同时要求来源、时点、无数据说明和用途限制。换一个地区或时点时，仍可复用这些规则；本次数据文件、地图范围和实际分类断点由项目实例确定。

这里的“场景”有两个层次：

| 概念 | 示例 | 作用 |
|---|---|---|
| 业务场景 `business_scene` | `emergency_mapping` | 对业务用途分类，帮助选择规划策略 |
| 地图任务 `tasks` | `hazard-result-map` | 说明需要完成的制图任务，并核对平台能力 |
| MapScenario 模板 | `urban-flood-risk/1.0.0` | 为具体可重复任务提供版本化制图合同 |
| 地图运行 | 某项目某次生成 | 绑定数据、目标、审批、候选和最终成果 |

业务场景名称不等于模板标识。一个业务场景可以存在多个方案模板；同一个方案模板可以被多个独立运行引用。模板名称中出现“风险”，也不意味着平台具备风险预测或灾害模拟能力。

## 3. MapScenario 的作用

### 3.1 复用业务方案

把同类任务反复需要确认的数据角色、指标含义、必需图层、表达方式和质量要求集中管理，减少每次制图重新解释规则的成本。

### 3.2 连接数据语义与地图表达

通过“数据角色 → 值语义 → 表达要求”的绑定，说明哪个量用于分级设色、哪个量用于符号面积，以及哪些内容必须出现在图例中。实际字段映射需要元数据与证据，不能只按列名猜测。

### 3.3 装配可替换组件

提供完整的身份、表达和版式基线，并声明哪些段可以被独立 MapBrand、MapStyle、MapLayout 替换。业务内容可以保持稳定，同时采用符合条件的其他机构身份或版面。

### 3.4 在执行前暴露缺口

用明确的前提检查数据、空间、符号、版式、工具和交付能力。缺少必需数据、单位不一致或版式无法容纳内容时，返回缺口及责任位置。

### 3.5 保持业务依据可追溯

地图实例能够解释采用了哪个方案版本、为什么需要某个图层、某项限制来自哪个契约，以及哪些项目决定经过了审批。

## 4. 与其他组件的区别和联系

| 组件 | 拥有的内容 | 与 Scenario 的关系 |
|---|---|---|
| MapScenario | 业务任务、数据角色、语义绑定、空间条件、必需内容和成果要求 | 提供可复用业务合同，装配其他组件 |
| MapStyle | 符号使用配置、色带、注记、图例外观和尺度行为 | 提供满足 Scenario 与表达定义约束的视觉配置 |
| MapLayout | 画布、Frame、空间组织、容量和溢出策略 | 承载 Scenario 提供的内容角色 |
| MapBrand | 机构身份、Logo、字体与品牌资源 | 提供身份资源及使用约束 |
| 地图表达目录 / Map Expression Catalog | 输入语义、适用条件、参数、编码和检查要求 | 提供精确引用的表达定义，算法仍在受信代码中 |
| 符号库 / Symbol Catalog | 通用符号资源、锚点、可调通道和使用限制 | 提供表达与 Style 使用的图形资源，不负责业务映射 |
| 内置表达方法与图表核心 | 受信编码计算与可复用绘图 | 按经过验证的计划执行，不由目录名称直接产生能力 |
| 制图标准与平台策略 | 适用的强制约束、允许能力和安全边界 | 约束整个组合，不能由模板自行降低 |
| 数据准备服务 | 获准数据读取、处理、质量检查和快照 | 按项目批准的需求提供可验收输入 |
| MapPlan | 本次数据绑定、模板选择、范围和项目决定 | 将模板规则落实为当前任务的计划 |
| MapSpecLock | 已验证、已批准的不可变执行快照 | 固定本次最终选择与输入摘要 |
| Renderer / Delivery | 按固定输入渲染、检查并授权交付 | 执行本次目标，不重新解释业务方案 |

容易混淆的属性应按下表分配：

| 属性 | 定义与处理方式 |
|---|---|
| 必须展示风险面和避难点 | Scenario 定义业务要求 |
| 容量字段表示人数还是设施数量 | 数据契约定义语义，实例绑定核对实际来源 |
| 风险等级是否为权威预分类 | Scenario 与适用标准确定，数据证据证明 |
| 分位数等分类方法是否适用 | Scenario 限定业务适用性，规划选择，注册算法计算 |
| 色带色值、描边和圆形样式 | 目标设计由 Style 拥有 |
| 本次计算出的分类断点 | 实例编译结果持有，并进入候选与锁 |
| 页面必须为 A3 | Scenario/Delivery 可以提出要求，Layout 提供实际画布 |
| 标题框和图例框的坐标 | Layout 定义 |
| 必须显示来源、日期和声明 | Scenario 或适用标准要求，实例提供具体内容 |
| 实际数据路径、地域和时间 | 当前项目提供并固定快照 |
| 最终接收方与交付目录 | 当前项目与 G3 批准对象绑定 |

Scenario 是装配根，不表示它可以越过组件所有权修改所有属性。包内可以包含一个完整 Layout，但其中的页面坐标仍属于 layout 段。

## 5. MapScenario 的职责边界

### 5.1 应包含的内容

- 业务场景、任务集合、适用条件和禁止用途；
- 必需与可选数据角色、几何类型、值语义、单位和质量要求；
- 数据角色、图层、表达能力与地图内容之间的绑定；
- CRS、范围、尺度、空间精度和多尺度行为约束；
- 必需地图视图、图例、来源、时点和限制说明；
- 身份、表达与版式的内嵌基线及可替换段；
- 对组件、注册工具、标准和渲染能力的兼容要求；
- 支持的交付目标及必需成果；
- 注册检查器、验证条件、依赖引用和合成 Fixture。

### 5.2 不拥有的内容

真实业务文件、密钥、完整行程、应急敏感坐标、当前地域范围、实际观测时点、最终分类断点、接收方和本次审批回执不应被固化进可复用模板。

Scenario 可以要求数据来源获准、交付前通过审批，但不能自行签发授权，不能因为包中声明了某项工具就取得调用权限，也不能附带任意 SQL、Shell、Python 或渲染器脚本来补足能力。

### 5.3 固定规则、默认值与实例结果

| 值的类别 | 示例 | 推荐处理 |
|---|---|---|
| 稳定业务要求 | 无数据必须区别于零值 | 固定为可检查约束 |
| 标准给定阈值 | 经适用标准定义的等级区间 | 固定版本与依据，实例不得重算替代 |
| 允许的方案选择 | 可采用的分类方法或输出规格 | 列出条件和允许范围 |
| 默认值 | 默认分类数、默认内容组合 | 使用前检查适用性；覆盖须在允许范围内 |
| 数据驱动结果 | 实际分位数断点、数据范围 | 由工具计算，保存在项目候选与锁中 |
| 当前项目决定 | 使用哪一年度数据、交付给谁 | 进入项目合同与相应审批对象 |

可复用不要求所有值都可调。相反，业务语义需要固定的地方应固定；只把有明确适用边界的选择留给实例。

例如，“展示各市 Top 3 行业并支持绝对产值比较”可以是硬要求，“优先采用柱状图”可以是允许调整的建议。沿用既有六种规则语义，不把推荐图形自动升级为固定表达；若业务或标准确实指定图形，则保留其绑定要求。

## 6. 核心结构：六份业务契约

MapScenario 采用六份业务契约。它们是同一个方案的分段，不是六类模板，也不是六套独立工作流。

| 契约文件 | 回答的问题 | 主要内容 |
|---|---|---|
| `contracts/scenario.yaml` | 方案适用于什么任务，如何组合？ | 业务场景、任务、用途、内嵌组件、可替换段和兼容性 |
| `contracts/data.schema.yaml` | 需要什么数据？ | 数据角色、几何、字段语义、单位、空值和许可条件 |
| `contracts/spatial-behavior.yaml` | 空间上如何正确表达？ | CRS、量测、范围、尺度、概化与空间有效性要求 |
| `contracts/portrayal.yaml` | 哪些数据如何进入表达？ | 图层、值角色、表达绑定、分类约束和图例关系 |
| `contracts/delivery.yaml` | 合格成果应包含什么？ | 目标、格式、媒介条件、必需性与用途限制 |
| `contracts/quality-gates.yaml` | 怎样证明方案可用？ | 注册检查器、阶段、严重度、证据与通过条件 |

`data.schema.yaml` 是当前约定的业务契约文件名，内容由 Carto 的 JSON Schema 校验；它不是让模板作者嵌入任意 JSON Schema 或动态验证代码的入口。

### 6.1 Scenario 契约与内嵌段

当前 `scenario.yaml` 必须包含 `identity`、`cartography`、`layout` 三个内嵌段。它们提供可以独立理解的完整基线；如果允许外部替换，应在 `replaceable_segments` 中显式声明。

“六份契约”与“三个内嵌段”是不同计数维度。三个内嵌段位于场景契约内，不应据此再增加三份并行的 Scenario 业务契约。

### 6.2 数据契约

数据角色描述对象，值角色描述对象上的量。例如 `shelter-point` 表示避难设施点，`count-value` 表示需要通过符号面积表达的非负数量。

数据契约还应说明单位、时间口径、空值含义、几何有效性、关联键与许可条件。支持某种几何类型不代表实际坐标已正确，字段为 number 也不代表指标语义已经确认。

### 6.3 空间行为契约

区分源数据 CRS、显示 CRS 和量测要求；规定业务范围覆盖、尺度适用性、几何处理与误差条件。具体转换与量测由已注册工具执行。

声明目标 CRS 不能替代转换能力。平台不支持所需转换时，应报告能力缺口，不能只更改元数据中的 CRS 名称。

### 6.4 表达契约

目标设计中，portrayal 主要保留数据角色、值语义、图层与 Style Profile 的绑定，以及不能被视觉调整改变的业务约束。符号细节、注记行为和色带实现由 Style 提供。

当前 v1 的 portrayal 还持有 `z_order`、`symbol`、`classification`、`scaling` 和无数据策略。向独立 Style 演进时需要明确协议升级和字段迁移，不能同时维护两套相互竞争的执行定义。

Scenario 已固定表达引用时，规划解析并核对其版本、摘要、输入和执行能力，不要求每次重新发现目录。若通过 Style Profile 间接引用表达，解析后的实际表达仍须满足 Scenario 的选择和业务约束；不能用不兼容的 Profile 静默替换。

未固定表达时，Scenario 可以只规定“地理分类数值图”的输入角色、目标和业务约束，由模型选择成熟预设，或在组合能力开放后生成新方案。实际数值映射、尺度、分母及地理关联必须在候选执行前明确。组合不必先注册完整名称，但所用能力及方案结构必须受正式协议支持；当前 v1 尚无通用组合链路。

业务主题、地区、年份、单位、排序对象和 Top K 规则由 Scenario/任务提供，数据准备执行获准的统计处理。表达方法使用通用的要素、类别与数值语义，因此更换主题未必需要新方法，但需要重新检查单位、正负值和可加总性。

例如，各市 Top 3 行业产值图由 Scenario 声明城市内排序、城市间比较和所需图例；模型可以选择共享尺度柱状图，再调用通用核心与地理放置能力。选择饼图时必须另行明确整体、分母和比较方式，不能只由 Style 改图形名称。页面辅助汇总图可以复用绘图核心并交给 Layout 放置，数据范围仍由任务明确，不能把城市 Top 3 的截取结果直接当作完整省级汇总。完整设计、执行与验证案例见[浙江示例](map-expression-and-symbol-design.md#76-从任务设计到执行验证)。

### 6.5 交付契约与质量门禁

交付契约规定可复用成果条件；质量门禁引用可执行的注册检查器。模板定义“要求通过什么检查”，验证报告证明“本次检查是否通过”，两者不能相互替代。

模板中的目标要求不等于已批准的交付行为。实际文件、接收方、目的地、用途与限制仍需由项目生成 DeliveryManifest，并由 G3 精确批准。

## 7. 数据语义、表达与业务限制

### 7.1 从角色到实际字段

建议将绑定过程明确为：

```text
模板数据角色与值语义
    → 检查项目来源、元数据和许可
    → 确认实际字段与单位
    → 执行获准的关联、转换和质量检查
    → 固定准备后数据及证据
    → 供实例规划与编译消费
```

例如，两份数据都可能提供 `capacity`，但一份表示设计容纳人数，另一份表示当前剩余容量。字段名相同不能证明二者可以混用；业务用途、观测时点和数值口径都需要匹配。

### 7.2 不把统计分级当成业务等级

分位数分类表示本次数据的相对分布，不自动具有“低风险、中风险、高风险”的专业等级含义。若输入已经包含经过核验的业务等级，应保留其类别与依据，不能为了画面均衡重新分级。

跨年份或跨地区比较还需要明确断点是否共享、单位是否一致、缺失区域是否相同。分别计算分位数后使用相同颜色，不一定表示可直接比较。

### 7.3 缺失、零值与不确定性

缺失值、零值、未覆盖区域和预测值具有不同含义，应分别声明处理方式。允许空值不意味着可以把空值补成零，也不意味着可以从地图或图例中删除对应区域。

对于比例符号，应说明输入量及其单位、面积映射关系、零值行为和可读尺寸边界。点符号表示设施容量时，不应在标题或图例中被解释成实际入住人数。

### 7.4 用途限制需要贯穿输出

Scenario 可以要求保留来源、时点、数据性质和使用限制。具体文案由规则与当前项目事实形成，并在页面、成品检查和交付说明中保持一致。

当前洪涝工程演示固定使用“合成数据演示，非真实风险研判”。这个限制属于当前样例的适用边界，不应成为所有未来 Scenario 的通用固定文案。

## 8. 组件装配与分段所有权

### 8.1 内嵌基线与完整段替换

| Scenario 内嵌段 | 可替换模板 | 替换单位 |
|---|---|---|
| `identity` | MapBrand | 完整 identity 段 |
| `cartography` | MapStyle | 完整 cartography 段 |
| `layout` | MapLayout | 完整 layout 段 |

只有 Scenario 允许替换的段才可以替换。同类模板不得重复选择，不能把两个 Style 的字段或两个 Layout 的 Frame 任意拼接成一个未发布组合。

替换后仍需满足 Scenario 的全部业务硬约束。外部 Brand 不能改变法定风险色语义，外部 Layout 不能删掉必需声明，外部 Style 不能把非负数量改成按半径正比表达。

### 8.2 与 MapStyle 对接

Scenario 提出表达需求，Style 提供相应 Profile。概念上的最低覆盖条件为：

```text
Scenario 所需 Style Profile ⊆ Style 提供的 Profile
```

还必须检查每个 Profile 接受的几何、值语义、单位、尺度和允许参数。Style 可以提供本次未使用的 Profile，但额外能力不应自动增加业务图层。

### 8.3 与 MapLayout 对接

Scenario 提供内容角色、类型、数量、必需性和视图关系；Layout 通过 Slot 接受这些内容，再将它们放入自己的 Frame。

例如 `main-legend` 是内容角色，`right-panel` 是某个 Layout 的 Frame ID。二者通过实例绑定关联，不要求所有 Layout 使用同一组 Frame 名称。比例尺和指北针必须绑定具体地图视图，不能只证明页面上存在相应图形。

### 8.4 与 MapBrand、标准和工具对接

Brand 提供已解析资源及使用限制；标准提供适用约束；工具网关检查能力注册与当前授权。模板只能声明所需条件，不能凭声明扩展工具或数据访问范围。

所有权用于确定值由谁定义，强制约束需要共同满足。六种规则语义 `hard_rule`、`forbidden`、`mandatory`、`binding`、`default`、`reference` 不是可以按数值排序、相互覆盖的优先级阶梯。

## 9. 双层文件与 Design Spec

MapScenario 同时提供文字说明和机器契约：

```text
MapScenario
├── templates/design_spec.md
└── contracts/
    ├── scenario.yaml
    ├── data.schema.yaml
    ├── spatial-behavior.yaml
    ├── portrayal.yaml
    ├── delivery.yaml
    └── quality-gates.yaml
```

`design_spec.md` 解释为什么采用这个方案、适用什么问题、如何审查结果；六份契约定义可执行规则。设计说明路径由 Manifest 声明，也可以采用包根目录的 `design_spec.md`，不依赖扫描猜测。

建议 Design Spec 保留以下十部分：

| 章节 | 应说明的内容 |
|---|---|
| 1. 身份与业务目标 | Scenario ID、版本、任务及契约引用 |
| 2. 适用与禁止用途 | 服务哪些业务决定，不支持哪些推断 |
| 3. 数据角色与事实依据 | 数据、指标口径、单位、时间和来源前提 |
| 4. 地图内容与阅读逻辑 | 必需视图、图层、重点信息和说明内容 |
| 5. 空间与表达原则 | 范围、尺度、分类、比较关系和不确定性 |
| 6. 组件与组合接口 | 内嵌段、替换条件、Profile 和内容角色 |
| 7. 项目可配置项 | 默认值、允许范围、需要重新确认的业务变化 |
| 8. 交付与使用限制 | 必需目标、来源、声明与适用边界 |
| 9. 验证与失败处理 | Fixture、检查条件、常见缺口及责任方 |
| 10. 版本、来源与追溯 | 设计依据、依赖、变更影响和已知限制 |

说明中引用的字段名、分类数或页面条件应与契约一致，宜从契约生成相应表格。发现冲突时修订并复验，不能让模型临时决定以哪份文本为准。

## 10. 机器契约组织与接口示例

### 10.1 当前 v1 的结构骨架

以下摘取现有洪涝示例的场景契约字段，用于说明组织关系。它省略了必需的 `embedded`、`compatibility` 和 `rules` 等内容，不是可单独校验或提交的完整文件。

```yaml
schema_version: 1
scenario_id: urban-flood-risk
version: 1.0.0
business_scene: emergency_mapping
tasks: [hazard-result-map]
owned_segments:
  - scenario
  - data
  - spatial-behavior
  - portrayal
  - delivery
  - quality-gates
replaceable_segments: [identity, cartography, layout]
data_role_refs: [risk-area, shelter-point]
target_ids: [a3-svg, a3-pdf, a3-png]
application:
  supported_uses: [engineering-preview]
  excluded_uses: [navigation, formal-delivery]
```

完整现有示例见 [scenario.yaml](../../skills/carto-agent/templates/map-scenario/urban-flood-risk/1.0.0/contracts/scenario.yaml)。这是 draft 合成示例的声明；其中 `formal-delivery` 的禁止用途不能被解释为生产交付授权。当前 U-P3 的 PDF/PNG 交付仍仅限本地合成演示。

### 10.2 数据角色示例

当前数据契约中的一个角色如下。`capacity` 是该契约约定的字段名，`count-value` 是表达所使用的语义角色。

```yaml
id: shelter-point
required: true
geometry_types: [point]
fields:
  - name: capacity
    type: integer
    unit: people
    nullable: false
    semantic_role: count-value
license_policy: project-approved
```

模板字段约定不等于原始文件必须采用相同列名；是否允许字段映射、如何保存处理后的标准字段，应由数据准备协议明确规定，并保留源字段、单位和转换证据。

### 10.3 面向独立 Style 与 Layout 的目标接口

以下为建议的逻辑接口片段，用于与 MapStyle、MapLayout 专题文档对齐。字段尚未注册为当前 Scenario v1 协议，不能直接追加到现有契约中。

```yaml
requires:
  style_profiles: [sequential-area, proportional-point]
  brand_roles: [body-font, heading-font]

portrayal_bindings:
  - layer_id: risk-layer
    data_role: risk-area
    value_role: risk-value
    semantic_type: ordered-numeric
    style_profile: sequential-area
  - layer_id: shelter-layer
    data_role: shelter-point
    value_role: count-value
    semantic_type: nonnegative-count
    style_profile: proportional-point

views:
  - id: overview-view
    layer_ids: [risk-layer, shelter-layer]

content_requirements:
  - {role: map-title, type: text, required: true}
  - {role: main-map, type: map-view, required: true, view_id: overview-view}
  - {role: main-legend, type: legend, required: true, view_id: overview-view}
  - {role: source-note, type: text, required: true}
  - {role: required-notice, type: text, required: true}
```

这里的 `requires` 表达组合要求，`portrayal_bindings` 属于表达契约职责，`views` 和内容需求描述业务结构；它们不是新增三份业务契约。后续协议应明确字段落点和引用关系，避免在多个文件重复定义。

图例内容应从本次实际表达结果生成，来源与声明从项目事实和规则生成。这个接口不包含图例坐标、字体文件或当前数据行。

### 10.4 实例绑定与模板引用

项目选择模板时，需要精确绑定命名空间、类别、ID、版本和摘要。实际字段绑定、内容对象和被选组件同样进入项目产物，不能回写已发布 Scenario。

上面的 Profile 名称和角色名称只是接口示例，不是已发布资源引用。进入可执行候选之前，所有依赖都必须解析为完整、可验证的版本和摘要；不能用省略号、`latest` 或只含名称的引用完成冻结。

## 11. 用户需求与 MapScenario 的匹配

### 11.1 先确认任务，再筛选模板

推荐匹配顺序为：

1. 从需求与证据确认业务用途、任务、数据性质、地域、时间和交付条件。
2. 区分意图歧义、缺少数据、缺少授权与平台能力不支持。
3. 在权威索引中筛选已发布 Scenario 的摘要与 Manifest，检查用途和任务条件。
4. 检查数据角色、几何、值语义、空间要求和输出目标是否相容。
5. 形成候选及缺口，在 G1 中确认具体方案、来源和准备范围。
6. 确认后安装精确版本、解析完整契约，检查组件组合与实际数据。
7. 编译和预览通过后，才形成可供 G2 批准的确定候选。

未确认前的摘要筛选只是初步匹配，不能替代安装后的完整校验。未来如增加评分，也只能对通过相应阶段硬条件的候选排序，不能用高相似度掩盖禁止用途或缺失能力。

### 11.2 区分模板适配与执行就绪

以下为建议的诊断分类，不是当前 CLI 新增的状态枚举：

| 情况 | 含义 | 后续处理 |
|---|---|---|
| 适配且输入就绪 | 规则与项目条件相容 | 继续验证与编译 |
| 适配但缺输入或授权 | 业务方案可用，执行条件未齐 | 生成有阶段要求的缺口清单 |
| 需要已声明调整 | 差异位于允许参数或替换段内 | 记录选择并重新验证组合 |
| 模板不兼容 | 缺少业务角色、目标或违反用途限制 | 更换或创建方案 |
| 平台能力不支持 | 注册工具或运行链路不能完成任务 | 返回能力缺口 |

例如，缺少已核验风险面是数据问题；要求预测未来洪水而平台没有相应算法是能力问题。二者都不能通过换一个模板名称解决。

### 11.3 当前匹配边界

当前 `generate-map` 要求请求精确指定已发布的 `urban-flood-risk/1.0.0`，并不执行通用智能模板搜索。Schema 中出现三个业务场景枚举，不表示三个场景的任务均已开放。

## 12. 覆盖、版本与派生

### 12.1 实例调整

项目可以绑定本次数据、选择契约允许的目标，并在明确范围内调整参数。每项调整应记录基础值、最终值、依据和影响的验证项。

允许替换 Style 不代表允许更改业务指标，允许替换 Layout 不代表允许删减必需图层。分类方法、地图数量或用途发生变化时，应重新评估计划及相关审批，不能归类为普通外观调整。

### 12.2 新版本

改变数据角色、单位语义、必需内容、可替换段、允许参数、标准依赖、交付目标或质量门禁，通常需要发布新版本。破坏既有输入与行为兼容性的变化应按版本策略提升主版本。

已发布版本不可原地覆盖。同一地区下一年度换数据一般属于新地图运行；改变可复用业务规则才属于模板演进。

### 12.3 派生方案

需要新增稳定业务角色或任务时，可以基于已有方案创建派生 Scenario，并记录设计来源。发布物仍须具有完整、自洽的六份契约与依赖闭包，不在运行时临时拼接多个父方案。

一个原子地图运行最多选择一个 MapScenario。若同时需要经济专题、灾害态势和调研路线等独立成果，应在规划中明确任务拆分，各自保留计划、锁和证据。

### 12.4 仅作为设计参考

如果只是借鉴阅读逻辑，而实际业务角色或表达语义已超出原方案，应记录参考来源，不能继续宣称符合原 Scenario。

## 13. 创建、验证与发布流程

MapScenario 创建使用独立的 `create-template` 工作流：

```text
analyze → brief → T1 → author → validate → TP → publish
```

| 阶段 | 主要工作 | 产物与边界 |
|---|---|---|
| analyze | 分析获准来源和可复用规则，区分事实、决定、建议与推导 | 来源快照、分析与缺口；不把业务数据复制进模板 |
| brief | 确认方案身份、用途、角色、目标和创建范围 | TemplateBrief 与 T1 批准对象 |
| author | 在 T1 后编写完整模板包 | 六契约、Design Spec、依赖与合成 Fixture；不自报验证通过 |
| validate | 结构、语义、依赖、检查器及 Fixture 渲染验证 | 验证报告、预览、RenderReceipt 和绑定证据 |
| publish | 重验包与证据，校验并消费精确 TP | 不可变版本、发布记录和权威索引 |

T1 批准创建简报，TP 批准具体发布对象。二者都不能用作地图项目的 G1、G2 或 G3。

当前已开放这条流程中的固定洪涝作者策略，不代表可以创建任意 Scenario。新增作者策略需要相应协议、实现、合法与非法样例以及验证证据。

## 14. 地图实例编译与冻结

### 14.1 从模板到地图

```text
项目意图 + 精确 Scenario 候选 + 数据准备需求
    → MapBrief 与 G1
    → 安装模板、解析六契约和依赖
    → 数据准备与验收
    → MapPlan：实例绑定、范围、目标和决定
    → 编译组件、空间与表达结果
    → ResolvedMap + RenderScene + 预检
    → 真实预览与独立检查
    → G2 批准候选并冻结 MapSpecLock
    → render → check → DeliveryManifest → G3 → deliver
```

未来引入 `ResolvedCartography` 和 `ResolvedLayout` 时，它们应作为候选的组成或引用结果，继续纳入同一摘要闭包，不再增加一个与 MapSpecLock 竞争的“Scenario 实例锁”。

### 14.2 规划、图面实现与渲染的分工

MapPlanner 确认业务语义、数据与表达策略，选择预设或提出支持范围内的表达组合；MapComposer 在冻结前细化获准图面并依据检查反馈修订；compiler 解析成完整候选；Renderer 按已解析输入输出地图。映射、分母或比较目标变化须返回规划，不能作为普通美化调整。

Scenario 为这些阶段提供规则，不替代规划器，也不自行运行工具循环。G2 后正式渲染不再选择分类、重新查找数据或自由调整版式。

### 14.3 变化与修复

数据、模板、字体、图面参数或环境变化可能使预览证据失效，应返回相应准备、规划或验证阶段。不能改完模板后继续沿用旧锁。

暂时性渲染失败可以在输入仍符合锁的条件下创建新 attempt；业务语义或输入漂移不能通过普通重试解决。修复过程应有明确预算与终止条件。

## 15. 模板包与输出产物

### 15.1 模板包组织

建议沿用当前 Scenario 包的组织方式：

```text
<map-scenario-package>/
├── manifest.yaml
├── templates/
│   └── design_spec.md
├── contracts/
│   ├── scenario.yaml
│   ├── data.schema.yaml
│   ├── spatial-behavior.yaml
│   ├── portrayal.yaml
│   ├── delivery.yaml
│   └── quality-gates.yaml
├── dependencies.lock.yaml
├── prototypes/
├── fixtures/
├── assets/                    # 可选，须有许可与摘要
└── checksums.sha256
```

Manifest 管理身份、文件闭包和依赖入口；依赖锁固定表达、符号、检查器和其他资源；原型展示结构与容量；Fixture 验证规则与边界。原型存在不等于已经完成浏览器渲染。

质量门禁已经位于 `contracts/quality-gates.yaml`，不应在包根目录再维护一份相同职责的配置。

### 15.2 发布输出与实例输出

| 输出 | 归属与用途 |
|---|---|
| Scenario 模板包 | 可复用业务规则与组件基线 |
| 发布记录、权威索引条目 | 模板仓库管理，证明精确版本已发布 |
| MapPlan、准备后数据与候选 | 项目管理，记录本次决定与计算结果 |
| 预检、预览与 MapSpecLock | 证明候选有效并固定执行输入 |
| PDF/PNG、成品报告和 DeliveryManifest | 正式渲染与检查阶段生成 |
| DeliveryReceipt | 记录授权交付后的实际提交结果 |

模板发布回执与本次地图交付回执有不同对象和生命周期。Scenario 本身不直接生成可交付的业务地图。

当前 `skills/carto-agent/templates/` 保存内置示例，不是权威发布仓库。目录中存在一个完整包也不代表运行时可以发现它；消费前仍须完成正式验证与发布。

## 16. 验证与兼容性证据

验证需要区分模板本身、带数据的实例和最终交付：

| 层次 | 需要验证的内容 |
|---|---|
| 结构与完整性 | 六契约 Schema、未知字段、文件闭包、版本和摘要 |
| 跨契约引用 | 数据角色、图层、目标、内嵌段与检查器引用一致 |
| 业务语义 | 指标口径、单位、等级含义、支持与禁止用途 |
| 数据与空间 | 必需角色、空值、几何、CRS、关联键、范围和尺度 |
| 组件组合 | 替换许可、Style 能力、Brand 资源、Layout 内容与容量 |
| 表达与预览 | 分类、比例符号、无数据、图例、文字与必需内容 |
| 运行能力 | 注册工具、授权、渲染器能力、环境与预算 |
| 冻结与成品 | 候选、预览、锁、attempt、文件及环境摘要绑定 |
| 发布与交付 | 精确审批、不可变版本、清单、事务与恢复证据 |

推荐 Fixture 至少覆盖：

- 正常风险面和设施点、空值与零值，以及输入顺序变化；
- 缺少必需角色、错误几何、错误单位、未知 CRS 和重复关联键；
- 常量数据、重复断点、异常值，以及不可用的分类条件；
- 缺少 Style Profile、禁止替换段、缺少必需内容和图例容量超限；
- 禁止用途、未注册检查器、依赖漂移和被篡改的预览证据。

这些是目标验证矩阵，并不表示当前每项能力均已实现。Fixture 应使用合成材料，不含真实业务数据行、敏感坐标或完整行程。

合成样例通过只能证明对应算法、规则和环境下的工程行为。它不能证明某个真实风险指标有效，也不能替代生产数据质量、业务验收或必要的专业审查。

## 17. 不匹配时如何处理

| 不匹配原因 | 建议处理 |
|---|---|
| 实际字段名不同但语义一致 | 在获准数据准备中显式映射并验证 |
| 缺少必需数据或许可 | 输出缺口，补齐后继续 |
| 缺少符号或表达 Profile | 选择兼容 Style，或独立创建完整新版本 |
| 缺少页面规格或容量 | 选择兼容 Layout，重新检查空间与内容 |
| 缺少机构身份资源 | 选择兼容 Brand 或补齐获准资源 |
| 新增稳定业务角色、用途或任务 | 创建新 Scenario 或发布新版本 |
| 请求违反方案用途限制 | 选择经验证的其他方案；不得删除限制绕过 |
| 请求超出平台注册能力 | 返回能力缺口，创建模板不能补足实现 |

不应因为字体或纸张不匹配就复制整套 Scenario；先把问题交给对应组件。也不应因为外观相似就套用一个业务语义不同的模板。

需要新模板时，进入独立、可审计的 `create-template` 运行。新版本发布后，地图项目重新选择精确引用并履行相应验证与审批；生成流程不能自动取得模板发布权。

## 18. 当前仓库状态与演进建议

截至本文编写时，MapScenario 已有实际创建、验证、发布和消费流程，但业务范围限于固定洪涝合成数据演示。

| 当前事实 | 实现依据 |
|---|---|
| Scenario v1 固定六个 owned segments，必须内嵌 identity、cartography、layout | [scenario.schema.json](../../skills/carto-agent/schemas/scenario.schema.json) |
| 内置模板身份为 `urban-flood-risk/1.0.0`，状态为 draft 合成示例 | [manifest.yaml](../../skills/carto-agent/templates/map-scenario/urban-flood-risk/1.0.0/manifest.yaml) |
| `flood-risk-overview` 是作者 profile，不是另一套模板 ID | [template_author.py](../../skills/carto-agent/scripts/carto_core/workflow/template_author.py) |
| 模板流程具备 analyze、brief、author、validate、publish 和独立 T1/TP | [template_workflow.py](../../skills/carto-agent/scripts/carto_core/workflow/template_workflow.py) |
| 消费侧通过权威仓库发现并安装精确已发布版本 | [template_repository.py](../../skills/carto-agent/scripts/carto_core/repository/template_repository.py)、[template_installer.py](../../skills/carto-agent/scripts/carto_core/repository/template_installer.py) |
| 地图规划限定固定洪涝角色、quantile 分类，并要求 area-proportional 缩放；这不等于实际面积编码已正确实现 | [map_planning.py](../../skills/carto-agent/scripts/carto_core/workflow/map_planning.py) |
| portrayal v1 仍持有分类、符号、层序和无数据等具体表达规则 | [portrayal.yaml](../../skills/carto-agent/templates/map-scenario/urban-flood-risk/1.0.0/contracts/portrayal.yaml) |
| 所有权组件支持外部组件完整段替换，但独立组件业务创建与通用匹配尚未开放 | [ownership.py](../../skills/carto-agent/scripts/carto_core/compiler/ownership.py)、[SKILL.md](../../skills/carto-agent/SKILL.md) |
| 已打通候选、预览、G2、锁驱动渲染、成品检查及 G3 本地交付 | [map_generation.py](../../skills/carto-agent/scripts/carto_core/workflow/map_generation.py) |
| 当前为 A3 横向、144 DPI 的合成演示交付；生产任务列表为空 | [scope-baseline.yaml](../../skills/carto-agent/policies/scope-baseline.yaml) |

候选编译中的点半径仍按数值线性变化，与面积比例声明有差距；通用符号加载、图表及地理放置也尚未完整贯通，见[设计结论文档的实现核对](map-expression-and-symbol-design.md#10-当前仓库状态与设计差距)。现有三场景枚举、可替换段声明和协议骨架不等于通用场景理解、独立组件装配或生产制图已经完成。`ResolvedCartography`、`ResolvedLayout` 和本文所示的 Profile/Slot 通用绑定也仍是演进设计。

建议按以下顺序完善：

1. 明确数据语义、空间条件、表达实现和页面条件的唯一所有者，先收敛重复字段。
2. 扩展数据角色与值角色的绑定、单位和时点验证，使实例输入不依赖固定洪涝字段约定。
3. 将可替换的视觉配置迁入完整 MapStyle，让 portrayal 聚焦业务语义、表达绑定与业务约束；表达定义拥有映射语义，受信方法执行算法，迁移时明确各字段的唯一来源。
4. 增加内容角色、视图关系和 Layout Slot 对接，并将实际表达与排版结果纳入现有候选和锁。
5. 完善独立 Brand、Style、Layout 的创建发布与组合验证，再开放通用模板匹配。
6. 按已注册任务逐项扩展 Scenario 作者和规划策略，补齐真实数据、空间工具及生产验收证据。
7. 根据实际需求再增加多视图、批次成果与其他媒介，保持单次运行的计划、审批和交付边界。

后续实现继续位于 `skills/carto-agent/`。协议升级应同步提供合法、非法样例与自动验证，沿用唯一 CLI、完整段所有权、精确版本引用和不可变发布机制。
