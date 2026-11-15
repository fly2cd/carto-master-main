# ADR-001：引入后端无关的 encoding IR，解绑 geometry ↔ 表达 ↔ 后端三重耦合

- 日期：2026-11-13（Asia/Shanghai）
- 状态：**Partially Implemented**（阶段1 backend_registry + 阶段2 encoding IR + 阶段2.3 数据/准备/表达/渲染链 + 真实 geospatial-mcp continuous 改造 + 跨仓联调 + continuous 端到端均已实施，见 §8.5；阶段2.3(b) 模板/profile 准入、(d) 渲染层出图测试、阶段3 合并待续）
- 决策类型：架构 / 协议边界
- 上游依据（一手决策文档，非二手转述）：
  - [design-principles.md](../design-principles.md)：四层决策模型（§2）、当前违规清单（§5）
  - [design-convergence-20261109.md](../design-convergence-20261109.md)：Encoding/Appearance/Composition/Renderer 领域模型（§1）、正交定义（L19）、C01/C10、采纳未实现项（§6）、待定细节（§7）、P3.6 Schema 合并（§10）
- 断言标注约定：【源码事实】附文件:行号；【既有决策】附上游文档条目；【领域理论】附权威来源；【设计推断】为本 ADR 提出、尚未验证的设计。

---

## 1. 上下文与问题

### 1.1 源码事实：一根 geometry 轴绑定三个维度【源码事实】

| 被绑定维度 | 证据（文件:行号） | raster | vector |
|---|---|---|---|
| ②数据结构 | `schemas/general-generate-request.schema.json` `oneOf` L10-131（靠 `geometry` const 分流）| `source_bindings`+`prepared_raster_bindings`+`panels`（L25-29），role `classified-surface`（L46），`geometry:raster`（L71-73）| `vector_sources`+`vector_panels`（L94-95），`source_bindings` maxItems:0（L100-101），role `thematic-features`（L115），`geometry:vector`（L123-125）|
| ③表达方法 | `schemas/thematic-design.schema.json` `oneOf`；`schemas/vector-encoding.schema.json` `oneOf` | 仅 `geometry:raster`→`kind:categorical`+`measurement:nominal`+`palette_source:prepared`（thematic-design L727-738）| choropleth→`geometry` const `polygon`（vector-encoding L320-322）；proportional→const `point`（L510-512）|
| ③表达机制 | portrayal 生成 | `category_mapping: unique-values`（`scenarios/general_thematic.py` L544-546）| `expression_options:[categorical,choropleth,proportional]`+`encoding_policy:explicit-per-panel`（`scenarios/general_vector.py` L241-243）|
| ④渲染后端 | profile 写死 renderer_id | `rasterio-matplotlib-page`（`policies/scenario-capabilities.yaml` L70）| `matplotlib-vector-page`（同文件 L136）；后端按 `renderer_id` 分派（`adapters/render_backend.py` L22/L40-41）|

散弹式后端判断（同一 `renderer_id` 字符串比较散落多处）【源码事实】：`workflow/map_generation.py` L1118/1276/1285、`compiler/map_candidate.py` L146/166、`workflow/template_validation.py` L33-41。

IR 候选层已被几何污染【源码事实】：`schemas/resolved-portrayal.schema.json` `geometry` enum[raster,vector]（L24-29）、`legend_items` oneOf[rasterLegendItems,vectorLegendItems]（L139-146），其 description（L5）自承 *"the rendering table stays geometry-specific **until the renderer merge**"*。

唯一正交的轴是 ①业务语义【源码事实】：两个 profile 共享 `business_scene: general_thematic_mapping`（scenario-capabilities.yaml L22 与 L88）、`tasks:[thematic-map]`。

### 1.2 这不是新发现——上游决策已认定为违规/已采纳【既有决策】

- design-principles.md §5 违规清单已明列本 ADR 关注的耦合：#2（`general_thematic.py` classification/renderer_id 硬编码）、#4（`general_vector.py` expression_ref 硬编码）、#5（同文件 classification/renderer_id 硬编码）、**#6/#7（`raster_scene.py` L12 / `vector_scene.py` L10 的 RENDERER_ID 常量，应"从能力匹配结果读取，后端选择应在候选阶段按整页能力匹配"）**、#10（`layout.py` L68 unit/DPR 硬拒绝，应"改为能力声明"）。
- design-convergence §1（L13-16）已确立 **Encoding（数据→视觉变量映射）/ Appearance / Composition / Renderer（独立执行层）** 四层领域模型。
- design-convergence L19 已定义正交语义：**"正交指职责与决定可分别表达，不代表互不影响或所有组合都能执行"**。
- design-convergence C10 已决策：**"候选阶段按整页能力匹配并测量，首期一页一后端；冻结后无静默回退"**。
- design-convergence §6.4 已采纳（未实现）：**"接入后端能力匹配与分后端探测，按整页组合验收"**；§7 标记 **"后端能力矩阵的存储/版本形式、偏好选择的确定性规则"** 尚待确定。

### 1.3 当前 version→geometry 分叉的由来【既有决策】

design-convergence §10（L120）：P3.6 将 4 份按数据类型分叉的请求 Schema 合并为 2 份统一 Schema，"通过 `oneOf`/`if-then` 按 `version`（3.0.0/4.0.0）区分 raster/vector 变体"。这是**Schema 去重的有意权衡**，副作用是把 `version ↔ geometry ↔ 数据结构 ↔ 后端` 焊在一处分叉里。

### 1.4 缺口（本 ADR 的必要性）

上游决策停留在**领域模型 + 原则 + 违规清单 + "采纳未实现"**层面，尚无一份聚焦 **encoding-IR 的具体 schema 结构 + 合法组合矩阵 + 几何解绑方式** 的可执行决策。本 ADR 填补该缺口，**承接而非重造**上游方向。

---

## 2. 决策

### 2.1 引入后端无关的 `encoding-ir.schema.json`【设计推断，骨架有源码依据】

将 `compiler/vector_portrayal.py` L23-24 已存在的归约【源码事实】：

```python
_KEY_MODE = {'single':'discrete','categorical':'discrete','choropleth':'interval','proportional':'scaling'}
```

提升为 IR 的一等公民。IR 结构（不含任何渲染指令）：

```
encoding-ir:
  domain:          { field, measurement(nominal|ordinal|interval|ratio), unit, normalization }   # ②数据语义
  key_mode:        discrete | interval | scaling                                                  # ③表达本质（源自 _KEY_MODE）
  geometry_role:   point | line | polygon | raster-cell                                           # ②位置载体（降为属性，不再决定 key_mode）
  scale:           discrete{categories} | interval{edges,labels} | scaling{domain_max,range_mm}   # 数据→键
  channels:        { color(scheme+values|palette_ref), size(range_mm), shape, stroke }            # ③Bertin 视觉变量
  missing / legend
```

`measurement` 沿用现有字段（thematic-design.schema.json L462-469 choropleth 的 rate/ratio/density/normalized-index、L710-714 proportional 的 count）【源码事实】；`channels` 从现有 `symbol{color,stroke,stroke_width_pt,radius_mm}`（vector-encoding 各变体）抽象而来【源码事实】。

### 2.2 合法组合矩阵（以 schema `allOf` 取代 kind↔geometry 硬绑）【设计推断】

| measurement | 合法 key_mode | 允许的 geometry_role | 必需 channel | 说明 |
|---|---|---|---|---|
| nominal | discrete | point/line/polygon/**raster-cell** | color | 类别着色 |
| ordinal | discrete / interval | point/line/polygon/**raster-cell** | color | 有序可分级 |
| interval / ratio | interval | polygon/**raster-cell** | color | **分级着色——含栅格，打破当前 raster-only-nominal** |
| ratio（count）| scaling | **仅 point** | color+size | 比例符号需可定位载体 |

- **解绑点**：`interval` × `raster-cell` 合法化（当前被 thematic-design L727-738 拒绝）。
- **保留的物理约束**【领域理论：Bertin 视觉变量】：`scaling`（size 变量）需点载体；`raster-cell` 只能用 fill/hue，禁 size channel、shape 固定 auto。
- 与 design-convergence L19 一致：**正交不等于所有组合可执行**；矩阵把"隐式硬绑"变为"显式声明的合法组合"。

### 2.3 四层职责归属（严格对齐 design-principles §2）【既有决策约束】

| IR 决策点 | 归属层 | 依据 |
|---|---|---|
| 选 key_mode / measurement / color scheme / class_count | 创意设计层（LLM）| design-principles §2.1、总则 L11 |
| 组合矩阵校验、schema 合规、能力一致性 | 形式验证层（程序）| §2.2 L51「能力一致性」、§2.4 |
| edges 计算、颜色插值、radius、metric_value 归一化 | 机械推导层（程序）| §2.3 L64-65（颜色插值/分类断点）；现有 `thematic.py` resolve_design/metric_value L44-75 |
| 后端能力匹配与选择 | 形式验证层 + C10 | design-principles #6/#7/#10、design-convergence C10 |

### 2.4 后端选择改为能力协商【设计推断，落地上游决策】

`renderer_id` 从 profile 写死（scenario-capabilities.yaml L70/L136）改为 `backend_registry` 能力匹配结果；散弹判断（map_generation L1118/1276/1285、map_candidate L146/166、template_validation L33-41）收敛为单点 `registry.resolve(scene).supports(...)`。此项落地 design-principles #6/#7/#10 与 design-convergence C10/§6.4，并回答 §7「后端能力矩阵存储/版本形式」的待定项。

---

## 3. 备选方案与否决理由

| 方案 | 描述 | 裁决 | 理由 |
|---|---|---|---|
| A. Big-bang 完全重构 | 推倒现有 scenario/compiler/schema 重写 | **否决** | 耦合是分散字符串比较+成对文件（无中心可推倒）【源码事实 §1.1】；丢弃 test_a31_thematic 25 项+端到端回归网【源码事实】；big-bang 高失败率【领域理论：Netscape 教训 / Fowler 重构论 / Strangler Fig】|
| B. 维持现状 | 不动 | **否决** | design-principles §5 已将 #2/#4/#5/#6/#7/#10 列为违规；散弹 renderer_id 使"加一个后端改 8 处" |
| C. 渐进解耦（Strangler Fig）| 后端注册表→IR→去分叉→协商，分阶段可回滚 | **采纳** | 匹配耦合的分散形态；每阶段独立可验证；直击 §5 违规根因 |
| D. 继续沿 P3.6 version 分叉扩展 | 新几何/新后端继续加 oneOf 分支 | **否决** | 强化三重耦合，与 §5 修正方向、C10 背离 |

---

## 4. 后果与代价

### 4.1 正面
- 落地 design-convergence §1 的 Encoding 领域模型（从文档走向 schema）。
- 消除 design-principles §5 违规 #6/#7（后端硬编码），为 #2/#4/#5 铺路。
- 表达轴可脱离几何：栅格分级、矢量分级共享同一 IR。
- 后端可插拔：maplibre/canvas/QGIS 作为 IR 消费者接入（adapters 已存在 webmap_renderer/static_page_renderer/svg_compositor 等物质基础【源码事实：Glob adapters/】）。

### 4.2 负面 / 代价【设计推断，须诚实标注】
1. **破坏性协议变更**：`vector-encoding` + `thematic-design` + `resolved-portrayal` 三个 schema 改动，触及 test_a31_thematic 25 项与已发布模板 3.0.0/4.0.0。
2. **栅格 interval 需新执行器**：当前 raster 仅 `unique-values`（discrete，general_thematic.py L544-546）；支持栅格分级要补像元级 classification 渲染——真实工作量，非仅改 schema。
3. **非完全正交**：scaling×raster-cell 等组合物理不可行，须由矩阵显式禁止（见 §2.2）。
4. **line geometry_role 为预留**：当前无 line 数据路径，先占位（对齐"纵向打通优先、横向预留接口"）。

### 4.3 迁移策略
- 分阶段（Strangler）：**阶段1** 后端注册表（不改协议，纯收敛，低风险）→ **阶段2** IR schema + 解除 kind↔geometry 硬绑 → **阶段3** portrayal/scene 去几何分叉、合并成对文件 → **阶段4** 后端能力协商。
- 版本共存但**不留兼容旁路**（对齐 design-convergence §6.5「不为旧格式增加兼容旁路」）；每阶段以全量测试 + digest/像素等价对照护航。

---

## 5. 验证计划（可证伪）

- **判据**：若存在需求，业务语义与表达意图相同，仅因数据是 raster 还是 vector 而无法用同一表达方法，则几何轴错误耦合了表达轴。
- **静态反例（已成立）**【源码事实】：栅格分级着色被 thematic-design.schema.json L727-738 拒绝，矢量 choropleth 允许（vector-encoding L320-322）——判据成立。
- **动态原型**：同一份 encoding IR（`interval` + `sequential` color）分别以 `geometry_role: raster-cell` 与 `polygon` lowering 到 matplotlib，并以 `polygon` lowering 到第二后端（maplibre/canvas）出图一致 → 证伪"必须按几何分模板"。
- **三类独立证据**：① 源码实证（本 ADR §1 文件:行号）；② 可运行原型/反例；③ 领域权威（Bertin《Semiology of Graphics》视觉变量、Stevens 测量尺度、Vega-Lite `encoding.type`=measurement、Mapbox Style Spec source/layer/paint 分离、ISO 19117 Symbology）。

---

## 6. 溯源修正声明【诚实】

本 ADR 起草前的初步判断为"git 层无 ADR = 决策溯源缺失"。经核查修正：**git commit 层确无解释性 message**（`general_dispatch.py`/`resolved-portrayal.schema.json` 仅见于批量 commit `c0abd1e`「暂存当前工作分支修改」，`thematic-design.schema.json` 无提交记录），**但文档层存在两份一手决策/原则记录**（design-principles.md、design-convergence-20261109.md），已确立 Encoding 领域模型、正交语义、后端能力匹配方向与违规清单。故"为什么是几何变体"的**领域层决策可考**（§1.2/§1.3），仅**schema 落地层的具体取舍无专门记录**——本 ADR 即补此记录。

---

## 7. 合规性

- 符合 AGENTS.md：本 ADR 的职责归属严格对齐 design-principles.md 四层决策边界。
- 本 ADR 起草时为设计指导；阶段 1+2 已按 §8 落地代码 / Schema / Fixture，均经全量回归验证（470 tests OK）。后续阶段仍遵循"协议定义 → 实现 → 测试"同步演进。
- 运行时只消费 `skills/carto-agent/` 下的 Schema、策略与代码；本文不作为机器协议或审批回执读取。
- 落地需经"协议定义 → 实现 → 测试"同步演进（design-principles §7）。

---

## 8. 实施进展（截至 2026-11-14）

### 8.1 阶段 1：backend_registry 收敛【已实施 · 全量 460 OK】
- 新增 `adapters/backend_registry.py`（零内部依赖叶子）：`BackendDescriptor` + `resolve`/`is_static`/`is_browser`，三后端（RASTER_PAGE/VECTOR_PAGE/MAPLIBRE_WEB）单点登记。
- 收敛散弹：`create_render_backend` 硬编码 if 链 → registry 驱动；`template_validation._is_static_backend` + `map_generation` L1118/L1276 的重复 `renderer_id in {...}` → `is_static`；`map_candidate` L146/L166 字面量 → registry 常量。
- 行为等价：`is_static` 未知 id→False（与历史 `in {...}` 逐字等价）；`resolve` 未知→RENDER_BACKEND_NOT_AVAILABLE。scene 自我 id 常量未改（规避 compiler→adapters 循环），由 test_backend_registry 锚定一致。

### 8.2 阶段 2：encoding IR 迁移【已实施 · 全量 470 OK】
- 新增 `schemas/encoding-ir.schema.json`：key_mode 一等公民、geometry_role 解耦、channels 保留 per-key symbol（无损承载 explicit-per-panel）、组合矩阵（allOf）只拒物理不可行。
- 执行链：`thematic.resolve_design` 产 IR（新增 `_design_to_ir`）；`vector_portrayal` 重写为 key_mode 分支 + 新增 `ir_to_kind` 桥接。
- Schema：`resolved-portrayal`/`map-plan` 的 encoding `$ref`→encoding-ir；删 resolved-portrayal 中 72 行 kind→key_mode 派生。
- 消费者：`template_validation`/`general_vector`/`vector_page` 的 `encoding["kind"]`→`ir_to_kind()`；`formal_renderer`/`page_renderer` digest 依赖 vector-encoding→encoding-ir。
- 测试：test_encoding_ir 10（无损承载 + raster-cell+interval 解绑证明 + 组合矩阵）；test_a31 25 端到端行为等价。vector-encoding.schema.json 暂留 legacy（执行链已不引用），删除为独立清理项。

### 8.3 遗漏教训【诚实】
初始迁移清单遗漏 3 处 `encoding['kind']` 访问（`general_vector.make_bindings` L97、`validation_scene`、`vector_page` L61），由 test_a31 的 `KeyError` 逐个暴露后补齐。**印证：静态清单会漏，端到端测试是行为等价的唯一可靠闸门。**

### 8.4 阶段 2.3 进展：数据层 + 准备层已实施【已实施 · 端到端待续】
- **① wire 契约**：`geospatial-wire` statistics → `oneOf(classes | continuous{min,max,mean,stddev,histogram})`（categorical 分支字节不变）。
- **④ result 契约**：`geospatial-result` statistics → oneOf；公共字段提取到 $defs。
- **② dtype**：`geospatial_mcp` 新增 `FLOAT_DTYPES`/`SUPPORTED_DTYPES`；`_metadata` 放宽 integer-only。
- **③ MCP 提取/校验**：`_execute` 按 dtype 提取 classes/continuous；`_statistics` 分支校验（float→histogram 一致性）。
- **⑤ 准备**：`raster-classification-request` 加 continuous 变体（classification+color_ramp）；`raster-prepared-data` 加 `raster-continuous-preparation` 变体（携带 interval IR）；`raster_preparation` 新增 `_analyze_continuous`/`_check_continuous_result`/`_continuous_encoding`；提取 `thematic.equal_interval_edges` 供 raster/vector 共享（IR 复用兑现）。
- **验证**：test_schemas 20 + raster_formal/classification 33 + classification/a31-data 29 全绿，categorical 路径字节等价。
- **⑥⑦ + ⑧schema 已实施**：⑥ `resolved-portrayal` raster 分支支持 `key_mode=interval`（allOf discrete/interval）+ `raster_portrayal._build_continuous`（复用 prepared 的 interval IR）；⑦ `raster_renderer._continuous_indices`（float→edges 分箱→级别索引，复用 resize+ListedColormap 后半段，out_of_range 拒绝 + 值域完整性校验）+ render 双路径；⑧ `portrayal.schema` 新增 `rasterContinuousLayer`（graduated-color + classification）。验证：schema/portrayal/classification 57 OK + raster_formal/a31 41 OK，categorical/vector 零回归。
- **测试基础设施已实施**：`_fixture_gateway.statistics`（general_thematic L705）+ `set_raster`（helpers L85）加 float→continuous 统计桩（min/max/mean/stddev/histogram）。验证 raster_formal/classification 33 OK，categorical 桩/fixture 零回归。
- **待续**：⑧尾——(a) continuous 端到端测试【已完成，见 §8.5】；(b) 栅格 continuous 模板/profile 准入（scenario-capabilities + author + validation_scene），若要跑完整 generate【未启动】；(c) 真实 geospatial-mcp 改造【已完成，见 §8.5】。
- **阶段3（合并）未启动**：依赖 2.3 端到端落地（§9.6 顺序不可反）。

### 8.5 阶段 2.3 收尾：真实 MCP 改造 + 跨仓联调 + continuous 端到端【已实施 · 2026-11-13】
- **真实 geospatial-mcp 改造（4 文件，categorical 路径零改动）**：`schemas.py` 加 `Histogram`/`ContinuousStatistics` + `RasterStatistics` 改 `classes`/`continuous` 二选一（`model_validator` XOR + `model_serializer` 排除 None，输出 classes XOR continuous，精确匹配 carto wire oneOf）；`services/raster.py` 加 `FLOAT_DTYPES` + `continuous_raster`（float 单波段准入）+ `continuous_statistics`（两遍精确扫描 min/max/mean/stddev + 固定桶 histogram，sum(counts)==valid_pixels）；`raster_operations.py` `statistics` 先 `inspect_raster` 取 dtype 再分支（float→continuous，integer→classes 原路不变）；`tools/analysis.py` docstring 更新。
- **MCP 自证**：新增 `make_continuous`/`make_continuous_fixture`（float32 + 内部 mask）+ continuous service 层测试 + MCP 边界测试（structured_content 有 continuous 无 classes）。**完整套件 107 tests OK**，categorical 不回退；唯一行为变更测试 `test_float_int64_multiband_rejected` 拆为 float32→continuous（statistics 接受）+ 仍拒 reproject。
- **跨仓活体联调（最强证据）**：真实 MCP 对 float32 surface 产 continuous 输出（min0.5/max11.5/mean5.6/stddev3.6455/histogram 256桶，sum(counts)==10==valid_pixels，classes XOR continuous），逐门喂 carto 契约 **4 门全 PASS**：wire:statistics → wire:metadata + dtype∈SUPPORTED → adapter `_statistics` 一致性 → geospatial-result。
- **修复 2.3 遗留 KeyError（真实 bug）**：`geospatial_mcp._statistics` 对 float 波段直接索引 `stats["continuous"]`，若响应 dtype/家族不一致（float 却带 classes）会 `KeyError` 而非干净报错（由 test_geospatial_mcp mutation case=7 暴露）。改为 `.get()` + 缺失抛 `MCP_STATISTICS_INCONSISTENT`（float⇒continuous / integer⇒classes）。新增 2 adapter 回归测试（正向流转 + 负向 fail-closed），test_geospatial_mcp **39 OK**。
- **修复 graduated-color 几何缺口（真实 bug，`_build_continuous` 曾不可达）**：`rasterContinuousLayer` schema 绑定 `graduated-color/2.0.0`，但该表达式 `applicable_geometry` 仅 `[polygon]`，`MapExpressionCatalog.validate_portrayal` 对 raster 层抛 `MAP_EXPRESSION_GEOMETRY_MISMATCH` → continuous 表达层永远走不到 `_build_continuous`。补 `raster` 几何（map-expression schema enum 已允许 raster；catalog (id,version) 集合不变；105 目标测试无 digest 涟漪）。
- **continuous 端到端测试（新增 `test_raster_continuous`，5 OK）**：`ContinuousFixture`（真实 float32 TIFF 4x3/2 masked→10 valid + 无 legend 的 continuous request + gateway continuous 桩）驱动 analyze→`_analyze_continuous`→`_continuous_encoding`（interval IR，equal-interval 5 类→6 edges）→`raster-continuous-preparation`→`_build_continuous`→resolved-portrayal(key_mode=interval, 5 图例项)；负向：ramp/class 数不匹配、整数波段误用 continuous 请求均 fail-closed。**首次覆盖 `_analyze_continuous`/`_continuous_encoding`/`_build_continuous`（此前无任何测试触达）。**
- **仍待续**：(b) 栅格 continuous 模板/profile 准入（scenario-capabilities raster-continuous profile + general_thematic author 产 rasterContinuousLayer + validation_scene），跑完整 generate 准入；(d) continuous 渲染层（`_continuous_indices`）端到端出图测试（需 RasterFormalTests 级 scene/bundle/formal-render 脚手架）。

### 8.6 阶段 3 项①：portrayal IR 解析层去几何分叉【已实施 · 2026-11-13 · Strangler Fig】
- **前置门**：2.3 全量回归 **477 tests / failures=1 / errors=0**，唯一失败为先于本次、与 continuous 无关的 `test_ide_integration`（`.vscode/tasks.json` 被另一条工作流改成分层运行器 `run_tests.py --tier`，但测试期望未同步）。以此为项① 的对照基线。
- **项①-1 抽取（零行为变更）**：新增中性命名 `compiler/portrayal_resolver.py`，把几何无关的 IR 解析原语（`ir_to_kind`/`validate_ir`/`radius`/`_size_symbol`/`_number`/`_key`）从 `vector_portrayal.py` **逐字迁入**——兑现 §9.5 项① "消除 vector_portrayal 命名误解"（这些函数操作几何无关 IR，却曾住在 vector_ 文件）。`vector_portrayal.compiler_digest` + `page_renderer`(vector extra) + `formal_renderer`(vector paths) 三处 digest 清单同步纳入 `portrayal_resolver.py`，杜绝溯源盲区。门禁 101 tests OK。
- **项①-2 迁移消费方**：`thematic.vector_views`、`general_vector`、`vector_page`、`template_validation`、`test_a31` 的 `ir_to_kind`/`radius` 导入改指 `portrayal_resolver`；`vector_portrayal` 仅保留**内部实际使用**的原语导入（不再重导出 `ir_to_kind`）。vector-specific 的 `resolve_features`/`VectorPortrayalCompiler`/`shared_legend` 仍留 `vector_portrayal`。门禁 129 tests OK。
- **项①-3 编译器骨架判定【设计推断，对齐 §9.3】**：`VectorPortrayalCompiler.compile(prepared_ref, ir, ctx)` 走 `preparation.load_verified(ref, ctx)`+`.save()`；`RasterPortrayalCompiler.compile(portrayal, layer_id, prepared_ref, ctx)` 走 `preparation.load_verified(ref)`+`.save_document()`——**签名与 preparation 服务 API 各异**，resolve 逻辑本质不同（要素遍历+metric_value vs CSV 类别表/continuous 编码）。二者属**执行层**，按 §9.3「执行层保留 raster/vector 分离」不强合并（否则造巨型分支）。故 §9.5 项① 的"统一 portrayal_resolver"落在 **IR 解析层（已单源化）**，几何专属编译器/scene 作为执行层适配器保留分离。
- **项① 结论**：IR 解析层去几何分叉完成（几何无关代码单源于 portrayal_resolver，消费方直指，digest 溯源完整）；编译器/scene 按执行层原则保留分离并记录理由。**全量回归门禁 477 tests / failures=1 / errors=0，与 2.3 基线逐字一致（唯一失败为无关的 test_ide_integration）→ 零回归确认。**
- **项②/④ 未启动（本会话于项① 收口，留待新会话专注做）**：
  - **项②（模板契约层合并）**：入口 = `general_vector.py` L220-229 的 `TODO(R5-followup)`。Strangler Fig 4 步：(1) 把 `GeneralThematicAuthor` 被继承的 ~11 个私有 helper（`author`/`verify_existing`/`_scenario`/`_quality_gates`/`_delivery`/`_spatial_behavior`/`_fixture_csv`/`_require_admitted`/`_identity`/`_cartography`/`_layout`/`_data_schema`/`_portrayal`）抽成 `general_thematic.py` 模块级函数；(2) `GeneralVectorAuthor` 直接加 `author`/`verify_existing`；(3) 两者 `_payloads()` 改调模块级 helper（raster/vector 只传几何数据适配参数：data_role、geometry_types、portrayal layer、delivery.composition）；(4) 去掉 `(GeneralThematicAuthor)` 父类。**安全敏感（模板创作/质量门/交付），须先通读 general_thematic 894 行，每步全量门禁。**【已实施，见 §8.7】
  - **项④（scenario-capabilities 两 profile 收敛）**：会打破多个结构断言——`test_raster_portrayal` L102（断言恰好 `["general-thematic-mapping","general-thematic-vector"]`）、`test_scenario_registry`、`general_dispatch.geometry_of_profile`、`test_a31` L516。几何降为数据适配属性前须同步改这些闸门。【已实施，见 §8.8；实测 4 处预估只有 2 处真被打破】
  - **顺序**：项② 与项④ 相互关联（模板契约 ↔ profile），建议同一专注会话内先②后④，各自门禁。

### 8.7 阶段 3 项②：模板契约层合并【已实施 · 2026-11-13 · Strangler Fig】
- **前置门**：全量回归 **477 tests / failures=1 / errors=0 / skipped=9**，唯一失败仍是与本项无关的 `test_ide_integration`（同 §8.6 基线）。以此为项② 的对照基线。
- **项②-1 抽取（契约单源化）**：`general_thematic.py` 新增 19 个几何无关模块级函数——契约声明 `package_identity`/`identity_contract`/`cartography_contract`/`layout_contract`/`scenario_contract`/`data_schema_contract`/`spatial_behavior_contract`/`raster_portrayal_contract`/`delivery_contract`/`quality_gates_contract`/`fixture_csv`/`prototype_contract`/`dependency_lock`/`package_manifest`，准入 `require_admitted`，写包胶水 `author_context`/`write_package`/`verify_package`，另加 `GATE_PROTOCOL`/`GATE_LEGEND`/`GATE_RASTER_CLASSIFICATION`/`RASTER_DATA_FIELDS`/`RASTER_LIMITATIONS` 常量。`GeneralThematicAuthor` 的 13 个 helper **逐字迁出后删除**（不留兼容转发，遵 AGENTS.md「不为旧命名新增并行兼容实现」），类只剩 `__init__`/`author`/`verify_existing`/`_payloads`。
- **项②-1 散弹点（§8.6 清单未列，实测补齐）**：`tests/helpers.py` L294/L313 与 `tests/test_s1cd_grid.py` L26/L140 曾以**类名直调** `GeneralThematicAuthor._layout()`/`._cartography()`，同步改指模块函数（`layout_contract()`/`cartography_contract()`）。
- **项②-2/3/4（vector 侧独立）**：`GeneralVectorAuthor` 去掉 `(GeneralThematicAuthor)` 父类（实测 `__bases__ == (object,)`），自带 `__init__`/`author`/`verify_existing`；`_payloads` 全量改调共享契约函数，只传几何数据适配参数：`version=4.0.0`、`data_role=thematic-features`、`geometry_types=(point,polygon)`、`fields=()`、vector portrayal 层、`delivery(composition=vector-map, vector_claim=whole-map)`、`checks=(protocol,legend)`、`baseline_digest`、`lock_id=general-vector-lock`、`resources=3 个表达引用`、`prototype_id/layer_ids/limitations`。**旧实现 7 处事后覆写（version×3、gates×2、delivery×2）全部消失**；顺带清理 `DependencyResolver` 死导入与 L220-229 的 TODO。
- **与 §8.6 四步的偏差（记录理由）**：步骤(1) 与 (2)(3)(4) **必须同一门禁落地**——一旦把被继承的 helper 从类上移走，子类立刻 `AttributeError`；而 AGENTS.md 禁止并行兼容实现，故不存在"抽取后仍绿"的中间态。四步作为检查项全部兑现，只是合并为一个门禁（先跑 66 tests 聚焦门，再跑全量）。
- **参数化补漏（§8.6 步骤(3) 未列 `version`）**：实测 raster `VERSION=3.0.0` / vector `4.0.0`，而共享声明内嵌 VERSION 共 6 处（`scenario`/`identity`×2/`cartography`/`layout`/`quality_gates`×2）；不参数化 version，vector 只能继续事后覆写。已按 `version` 关键字参数化，默认取 raster 值以保持 raster 字节等价。
- **行为变更（3 项，均为收紧/自洽，非回归）**：
  1. **vector 准入对齐 raster 四道门**（用户决策）：`require_admitted(request, brief, version=4.0.0, profile=general-vector-authoring)` **先于** schema 校验执行。**探针证明这是真实堵漏而非纸面加固**（`projects/.carto-dev/_r5_item2_falsify.py`）：把该门 monkeypatch 成 no-op 后，`display_crs=EPSG:3857`（≠source_crs）与 `version=3.0.0` 的 vector 请求**都能成功出包**——后者会产出 `scenario.version=4.0.0` 而请求声明 3.0.0 的身份不一致模板；请求 schema 的 `version` enum 同时允许 3.0.0/4.0.0，故 schema 拦不住。门开启时分别报 `SOURCE_CRS_UNSUPPORTED` / `CAPABILITY_NOT_AVAILABLE`。
  2. **vector identity provenance 自洽**：旧实现把继承来的 `_identity()` 顶层 `version` 覆写为 4.0.0，却漏改嵌套的 `colors[0].provenance.source_ref`，vector 包内长期写着 `template:general-thematic-map@3.0.0`；现为 `@4.0.0`。**这会改变 vector 模板包摘要**（摘要运行时计算，仓库无冻结常量依赖；test_a31 vector 全链路含真实渲染全绿）。
  3. **错误码优先级/文案统一**：vector 的 `TEMPLATE_BRIEF_MISMATCH` 文案由 `Brief identity differs` 变为 `Brief does not describe this template`（**code 不变**，无测试断言文案）；门禁前置使 targets/profile 缺陷在两几何报同一 code，而非 vector 侧退化为 schema 错误。
- **测试**：新增 `test_a31_thematic.TemplateContractMergeTests` **4 例 / 0.4s**（无 GIS、无渲染、无审批缝）：① 两 Author 互不继承 + `author`/`verify_existing` 幂等；② vector 包各契约只体现几何适配参数（含 provenance `@4.0.0`、gates 2 项、delivery 双 target、data.schema、portrayal），且 **`scenario_contract` 归一化 version/data_role/provenance 后与 raster 声明逐字相等——契约单源的可证伪证明**；③ 四道门 + brief 门 fail-closed（版本降级、raster profile 越权、3 targets、CRS 漂移、brief 不符，均 subTest 参数化）；④ 两模块 `VERSION`/`AUTHORING_PROFILE` 与 `policies/scenario-capabilities.yaml` 注册 profile 锚定一致（消除双写漂移）。
- **门禁**：聚焦门 `test_general_thematic + test_s1cd_grid + test_a31_thematic` **66 tests / failures=0 / errors=0 / skipped=0**；收口全量 **480 tests / failures=1 / errors=0 / skipped=9**（480 = 477 基线 + 新增 3 例；第 4 例在全量启动后加入，已单独跑绿）。唯一失败仍为与本项无关的 `test_ide_integration` → **零回归确认**。
- **未采纳（记录理由）**：`require_admitted` 未加"geometry 与 author 匹配"第 5 道门——`general_dispatch.GeneralAuthor._impl` 已按 `geometry_of_request` 分派，`scenario_registry.for_create` L224 另有 `TEMPLATE_GEOMETRY_MISMATCH` 闸，新增属独立加固决策，留待项④ 一并考虑（项④ 实测：该闸在新协议下恒不可达，已删除并附证明，见 §8.8）。另记：vector 的 `cartography.symbol_catalogs` 仍为 `["ramps/categorical-raster@1.0.0"]`、`spatial_behavior.scale_bands[0].id` 仍为 `native-raster`（ raster 味命名被 vector 逐字继承）——改动会动 vector 模板摘要，超出项② 范围，列为后续清理候选。【后续处理见 §8.9：`scale_bands.id` 已按几何参数化修正；`symbol_catalogs` 经查证是无资源支撑的纯声明，明确不改并附理由】
- **项④ 于本项收口时未启动**：其依赖的 4 处结构断言（`test_raster_portrayal` L102、`test_scenario_registry`、`general_dispatch.geometry_of_profile`、`test_a31` L516）未被本项触碰。【随后已实施，见 §8.8】

### 8.8 阶段 3 项④：scenario-capabilities 两 profile 收敛【已实施 · 2026-11-14 · Strangler Fig】
- **前置门**：以 §8.7 收口的 **480 tests / failures=1（无关的 `test_ide_integration`）/ errors=0 / skipped=9** 为对照基线。
- **协议变更（schema）**：`scenario-capabilities.schema.json` 删除 profile 级 `template`/`authoring_profile`/`template_geometry`/`renderer_id`/`allowed_geometries`，改为必填 `geometry_variants`（minItems 1 / maxItems 2，item = `$defs/geometryVariant`：`geometry` + `template` + `authoring_profile` + `renderer_id`，`additionalProperties:false`）；抽出 `$defs`：`geometry`/`rendererId`/`templateIdentity`/`geometryVariant`。**清洁切换**：旧形状被 `additionalProperties:false` 直接拒绝，不留并行兼容（AGENTS.md）。
- **策略变更（policy）**：`scenario-capabilities.yaml` v1.6.0 → **v1.7.0**；两个 profile（`general-thematic-mapping@3.0.0` + `general-thematic-vector@4.0.0`）收敛为**一个** `general-thematic-mapping@5.0.0` + 两个几何变体。共享段（routes、request_schemas、含 11 个主题标签的 intent_constraints、data_nature、production_enabled、notice、licenses、output_profile、output_constraints、layout_constraints、internal_field_names）由**声明两遍变为一遍**，文件 **137 → 80 行（-42%）**。几何准入杆未丢失：撤销某几何 = 删除对应变体。
- **实现（registry）**：新增 `effective_definitions(profiles)`，把每个变体展平成一份"有效定义"= 共享段 + 变体四字段 + 派生 `template_geometry` 与 `allowed_geometries=[geometry]`。**消费方契约不变**：`for_template`/`for_create`/`resolve_generate`/`require_geometry`/`component`/`ref`/`notice` 以及下游读取（`renderer_id`、`output_profile.dpi`、`authoring_profile`）零改动。注册唯一性身份由 `(id, version)` 扩为 `(id, version, geometry)`——同一 profile 的两个变体不再互判重复，而重复几何、重复 authoring_profile、重复模板键仍报 `SCENARIO_PROFILE_DUPLICATE`。实测展平结果：`(...,3.0.0)→raster/rasterio-matplotlib-page/general-thematic-authoring`、`(...,4.0.0)→vector/matplotlib-vector-page/general-vector-authoring`，同 id/version、异 digest。
- **删除一段可证死代码（诚实记录）**：`for_create`/`resolve_generate` 中 `require_geometry(...)` 之后的 `geometry != geometry_of_profile(...)` → `TEMPLATE_GEOMETRY_MISMATCH` 分支被删。理由：**旧** schema 允许 `allowed_geometries` 与 `template_geometry` 独立声明（如 `[raster,vector]` + `raster`），该分支才有触发路径；**新** schema 下 `allowed_geometries` 由变体派生为 `[template_geometry]`，两检查恒等价，第一道门（`require_geometry` → `CAPABILITY_NOT_AVAILABLE`）已完全覆盖。全仓无任何测试断言 `TEMPLATE_GEOMETRY_MISMATCH`；`geometry_of_profile` 仍被 `UnifiedSourceContract.suggestions` 与测试使用，未变成死函数。
- **闸门改动（§8.6 预估 4 处，实测只需改 2 处）**：
  - **改**：① `test_raster_portrayal` L101-108——原断言"恰好两个 profile id"改为"一个 profile + 两个变体几何 `["raster","vector"]`"，保留该用例原意（表达本身不授权业务场景，准入只来自版本化策略 + 闭合代码白名单）；② `test_capability_roadmap.SemanticDigestTest`——原以**原始 policy profile** 当能力定义并改 `allowed_geometries`，改为用 `effective_definitions(...)` 的展平定义，并把"语义敏感"扩到 `allowed_geometries`/`template_geometry`/`renderer_id`/`authoring_profile` 四字段（披露字段仍不改 ref）。
  - **未破（预估偏大）**：`test_scenario_registry` L38（`_templates` 仍是 `{...@3.0.0, ...@4.0.0}` 两键，展平后逐字不变）、`general_dispatch.geometry_of_profile`（`template_geometry` 仍在展平定义中）、`test_a31` L143（同上）、`test_capability_roadmap.test_vector_geometry_withheld_by_policy`（派生 `allowed_geometries == ["raster"]`，`require_geometry` 仍拒 vector）。
- **新增测试**：`test_scenario_registry.GeometryVariantPolicyTests` **4 例**——① 打包策略共享段只声明一遍：**文本级**断言 `administrative-division`/`land-cover`/`max_width_mm`/`allowed_shapes`/`user-declared-source-license` 各出现 **1 次**（收敛前为 2 次），且 profile 级不含 5 个几何字段；② 展平后每几何一份能力、共享段一致、四个适配字段各异、`ref` 同 id/version 异 digest、两几何各自仍是准入杆；③ 同一几何两个变体 → `SCENARIO_PROFILE_DUPLICATE`；④ 两 profile 共用一个 authoring_profile → `SCENARIO_PROFILE_DUPLICATE`。协议样例（AGENTS.md「合法样例 + 非法样例 + 自动测试」）：`schema_cases.VARIANT_CAPABILITIES_POLICY`（合成合法样例）+ **5 个非法样例**（未知几何 `point-cloud`、变体缺 `renderer_id`、变体内塞旧 `template_geometry`、profile 级塞回 5 个旧字段、空 `geometry_variants`），由 `test_schemas.test_semantic_invalid_fixtures_are_rejected` 自动执行。
- **行为变更（3 项）**：
  1. **`profile.ref` 变化**：id 由 `general-thematic-vector`/`general-thematic-mapping` 统一为 `general-thematic-mapping`，version 由 3.0.0/4.0.0 统一为 **5.0.0**，digest 因定义形状变化而改变（两几何 digest 仍互异）。**此前冻结的 execution / 意图绑定在重放时会 `SCENARIO_PROFILE_DRIFT` 失败关闭**——这是版本化策略的设计意图，不是回归；仓库内无冻结的 profile ref 常量（测试全部运行时计算）。
  2. 错误码 `TEMPLATE_GEOMETRY_MISMATCH` 从代码中消失（见上，附证明）。
  3. 策略文件摘要变化 → 把该文件纳入指纹的宿主报告（`tests/manual/real_raster_acceptance.py` 的 `profile_count`）由 2 变 1，语义仍正确。
- **门禁**：聚焦门 `test_scenario_registry + test_capability_roadmap + test_schemas + test_raster_portrayal` **64 tests OK**（含新增 4 例与 5 个非法样例）；收口全量 **485 tests / failures=1 / errors=0 / skipped=9**（485 = 480 + 项② 后补的第 4 例 + 本项 4 例，逐条可对账）。唯一失败仍是与本项无关、先于本轮存在的 `test_ide_integration`（`.vscode/tasks.json` 换成 `run_tests.py --tier` 后测试期望未同步）→ **零回归确认**。
- **文档同步**：`SKILL.md`（当前阶段边界 + 成品检查段）、`workflows/routing.md`（能力声明）、`workflows/generate-map.md`（能力/模板资产说明）、`general_dispatch.py` 模块 docstring（准入杆改指 `geometry_variants`）。`doc/dev-log`、`doc/impl-log` 内的历史快照与 SVG 未改（它们是 dated 存档，不是运行时协议）。
- **未做（记录）**：① `scenarios/README.md` 仍写"profiles 与代码白名单均为空"，属早于 A3.1 的陈旧描述，与本项无关，未改；② `policies/capability-roadmap.yaml` 的 `variant-geometry-adapter-unification` 仍是 `planned`——它的剩余范围是**适配层** S3（准备链 statistics strategy、渲染表 renderer merge），与本项的策略层收敛不是同一件事，故未翻状态；③ 项② 遗留的 vector 侧 raster 味命名（`symbol_catalogs: ramps/categorical-raster@1.0.0`、`scale_bands.id: native-raster`）仍未动，改动会动 vector 模板摘要，留作独立清理项。【已于 §8.9 处理】
- **阶段 3 收尾**：§9.5 四项（①IR 解析层去几何分叉、②模板契约层合并、③执行层保留分离、④profile 收敛）全部落地；执行层按 §9.3 保留 raster/vector 分离并已记录理由。

### 8.9 收尾：唯一红灯归零 + vector 契约命名清理【已实施 · 2026-11-14 · 全量首次全绿】
- **`test_ide_integration` 归零（§8.6 起一路携带的唯一失败）**：根因确认为**测试期望过时**，不是配置错误——`.vscode/tasks.json` 已由另一条工作流换成 `tests/run_tests.py` 分层运行器（8 个任务：CLI help / schema check / probe renderer / IDE 自检 / fast tier / slow tier / full tier / re-measure baseline），而 `test_ide_integration.py` 仍期望 5 个任务且 `Carto: Run tests` 的 args 为 `['-m','unittest','discover','-s',TESTS,'-v']`。修法按该用例自身意图（"命令通用 + 只引用真实存在的入口"）：期望改为分层运行器的 8 条 args，并**补上 `run_tests.py` 的存在性断言**——否则新增入口不被校验，用例会退化为纯字面量比对。`test_ide_integration` **8 tests OK**；**未改 `tasks.json`**（配置是新且正确的一方）。
- **vector 契约命名清理（兑现 §8.7 遗留候选之一）**：`spatial_behavior_contract` 增加关键字参数 `scale_band_id`（默认 `RASTER_SCALE_BAND_ID="native-raster"`，raster 调用点不变 → **@3.0.0 资产字节不动**）；`general_vector` 传 `SCALE_BAND_ID='native-vector'`，矢量模板不再声明栅格味的比例尺带标识。测试同时钉住两侧：vector 包内 `scale_bands[0].id == 'native-vector'`，且 `spatial_behavior_contract(raster_request)` 默认仍为 `'native-raster'`。
- **不为该改动 bump 矢量模板版本（记录理由与反方条件）**：此改动会改变 vector 模板包摘要，严格按"版本号标识资产身份"应把 `@4.0.0` 升为 `@4.1.0`。**未升版**，依据三条源码事实：① `projects/template-repo/packages/local/map-scenario/general-thematic-map/` 下只有 `1.0.0`，仓库内**不存在已发布的 @4.0.0 矢量资产**；② 该场景 `production_enabled: false`；③ 本轮 §8.8 已变更 `profile.ref`（id/version/digest），任何外部冻结 execution 重放本来就会 `SCENARIO_PROFILE_DRIFT` 失败关闭，故本次**未引入新的漂移类别**。**反方条件成立时**（例如已有外部工作区冻结了 @4.0.0 矢量模板摘要）应执行升版清单：policy 变体 `template.version`、`general_vector.VERSION`、`general-template-create-request.schema.json` 的 version enum、`schema_cases._vector_tc` 与 `VARIANT_CASES`、`test_a31` 两处 `version='4.0.0'`、文档中 @4.0.0 表述（约 8 处，纯机械改动）。
- **`symbol_catalogs` 调查结论：不改，且这是有证据的决定（诚实记录）**：§8.7 曾把 vector 侧 `symbolization.symbol_catalogs: ["ramps/categorical-raster@1.0.0"]` 列为命名异味。实证：① 全仓 grep 表明该 id **不对应任何已注册资源**（`policies/map-expression-catalog.yaml` 的 `catalog_id` 为 `carto-map-expressions`，无 `ramps/*` 条目），且 `symbol_catalogs`/`color_system` 在 `carto_core` 运行时**没有任何读取点**（只有 `cartography.schema.json` 校验其形状与 `^<ns>/<name>@<x.y.z>$` 模式），即两个键是纯声明、不影响任何像素；② 因此"改成 vector 味"等于**再发明一个不存在的目录 id**（如 `ramps/categorical-vector@1.0.0`），属硬塞字段；③ 更真实的缺口是：共享 `cartography_contract` 声明 `color_system: "qualitative"`，对只支持 unique-values 的 raster 模板准确，却**低报**了 vector 模板的三种表达（categorical=qualitative、choropleth=sequential、proportional=尺寸而非色序）。**结论**：这不是重命名问题，而是"符号/色带目录"在本架构中尚无真实资源与校验闭环的能力缺口；应作为独立能力项处理（引入受校验的 symbol/ramp 目录资源，或让 cartography 声明由 `expression_options` 派生 `color_system`），不以改字符串的方式伪装完成。
- **门禁（收口）**：全量 **485 tests / failures=0 / errors=0 / skipped=9（16.66 min）→ 本轮工作首次全量全绿**。对账：477（§8.6 基线）+ 4（§8.7 `TemplateContractMergeTests`）+ 4（§8.8 `GeometryVariantPolicyTests`）= 485；9 项 skip 全部为外部环境依赖（符号链接权限、可选 MCP SDK、独立 GIS 服务解释器），**skip ≠ 通过**。
- **仍未做**：`tests/regression-baseline.json` 未用 `--measure` 刷新（新增 8 例不在计时基线内，runner 每次都会把它们放进所有 tier 并打印 WARNING，覆盖不受影响）；`tasks.json` 三个 `detail` 文案里的用例数（438/32/470）已过时，属另一条工作流的展示文案，未改；`scenarios/README.md` 的陈旧描述同 §8.8。

### 8.10 阶段1 收敛的补完：backend_registry 提为包根叶子 + renderer_id 字面量归零【已实施 · 2026-11-15 · P0-1】
- **§8.1 留下的权宜在此补完，且实测代价比当时记录的更大**。§8.1 写"scene 自我 id 常量未改（规避 compiler→adapters 循环 import）"；本轮 AST 扫描测得 renderer_id 字面量在 `carto_core` 内共 **26 处**（`rasterio-matplotlib-page` 9 / `matplotlib-vector-page` 10 / `maplibre-web` 7），真实代码副本分布在 **10 个文件**（`compiler/{raster_scene, vector_scene, layout}`、`validation/map_checks`、`adapters/{page_renderer, renderer_probe, webmap_renderer}`、`workflow/{map_final_check, map_render, template_validation}`），而 `backend_registry` 当时只有 4 个引用方——"单点登记"实际只在 `create_render_backend` 一处成立。
- **规避理由已消失**：Tier-2 去环后 `compiler→workflow` 引用为 0，且 `backend_registry` 本就是零内部依赖叶子（仅 import `carto_core.errors`）。故 `git mv adapters/backend_registry.py → carto_core/backend_registry.py`（血缘保留），`compiler` / `validation` 现可模块级安全导入，不触发 `adapters/__init__` 级联。
- **10 个文件的副本全部改为派生**：scene 与 `page_renderer` 的 id 常量改为 `RASTER_PAGE.renderer_id` 等；`compiler/layout.py` 的 `renderer_id in {两个字面量}` 改为 `is_static(...)`（对 `None` 与未知 id 同为 False，与历史行为逐字等价，已新增测试锚定该等价性）；`renderer_probe`/`webmap_renderer` 的 `DEFAULT_RENDERER`、`map_render` 的默认参数、`template_validation` 的 profile 构造同样改用描述符字段。
- **不变量固化为守卫**：`test_backend_registry` 新增 AST 扫描——renderer_id 字面量出现在 `backend_registry.py` 之外即失败（跳过 docstring 与裸字符串表达式）；并以 `assertIs`（非 `assertEqual`）断言派生常量与 registry 为**同一对象**，等值断言挡不住重新硬编码。证伪实验：向 `compiler/layout.py` 注入 `PROBE_DUPLICATE_ID = "rasterio-matplotlib-page"` → 守卫变红且点名文件与字面量；字节级还原后复绿、注入痕迹为零。§8.1 中"由测试锚定两处字面量不漂移"的断言随之删除——它锚定的是"副本存在"，而副本已不存在。
- **摘要影响（打点法实测：插桩 `Path.read_bytes` 后与 git 改动文件集求交，同树内比对）**：`raster.renderer_digest`、`raster/vector.page_renderer_digest`、`raster/vector.formal_renderer_digest` 变化（`layout.py` / `page_renderer.py` / `*_scene.py` / `render_backend.py` 在其清单内）；`raster.algorithm_digest`、`raster.portrayal_compiler_digest`、`vector.reader_digest`、`vector.compiler_digest` **不变** → 数据准备与 portrayal 产物不受影响，仅渲染侧按既定 fail-closed 语义需重渲染。
- **门禁**：fast **554/586** · failures=0 · errors=0 · skipped=9；`compiler→adapters` 边 6→5（剩 `PageRenderer` ×3 + `RendererProfile` ×2，根因与处置见 P1 清单）。
- **方法学更正（诚实记录）**：本轮曾尝试用"另开 worktree 检出旧提交"做摘要前后比对，得到大量假变化——根因是 `core.autocrlf=true` 且无 `.gitattributes`，同一提交在不同检出下字节不同（实测 227 个受版本文本源文件中 26 个在本工作树为 LF、新检出为 CRLF，其中 `workflow/material_extraction.py` 正是 `reader_digest` 的输入）。凡按字节哈希的量必须在同一工作树内比对，或先做 EOL 一致性核查。
- **详细度量、P0-2/P0-3 与后续 P1/P2 清单**：[U-P3.7-p0-architecture-hardening.md](../dev-log/U-P3.7-p0-architecture-hardening.md)。

---

## 9. 模板层架构判断：契约合并 / 执行分离 / 先补能力再合并

### 9.1 归因修正：死板 ≠ 两套模板【源码事实】
raster 死板的根源是**栅格执行链只实现 unique-values**，非"维护两套模板"：
- `portrayal.schema.json` rasterLayer（L288-374）required 仅 `category_mapping`（method const `unique-values`，L353-355），**无 classification/scaling**；而 vectorLayer（L144-196）有 classification(equal-interval/quantile/jenks/manual)+scaling。
- `raster_portrayal.py` L198 `key_mode:"discrete"` 硬编码；L67-69 像元值须为整数类别码。
→ **合并模板治"重复"，补栅格 interval 能力（2.3）才治"死板"；二者是不同的病，顺序不可反。**

### 9.2 两套模板差异解剖【源码事实】
GeneralVectorAuthor 继承 GeneralThematicAuthor：identity/cartography/layout/spatial-behavior/business_scene **完全共享**（仅改 version 号），约 60-70% 重复；本质差异仅 data.schema（像元 category_value vs 要素 point/polygon+任意字段）、portrayal（category_mapping vs explicit-per-panel）、delivery.composition。

### 9.3 该分该合的第一性判断【设计推断】
| 层 | 处置 | 理由 |
|---|---|---|
| 契约层（业务语义+版式+表达方法声明）| **合** | 60-70% 重复，纯维护负担；表达已由 IR 统一 |
| 执行层（数据准备+渲染，像元 vs 要素）| **分** | 像元网格与矢量要素的读取/join/渲染本质不同，强合并会造巨型分支 |
| 表达（portrayal）| IR 统一 | rasterLayer 缺 classification 是能力缺失，非几何宿命 |

### 9.4 阶段 2.3 计划：栅格分级能力（先补能力，治死板）
1. `portrayal.schema` rasterLayer 增加 classification 分支（对齐 IR interval）。
2. `raster_portrayal.py` 支持 `key_mode=interval`（连续值像元→按 edges 分箱→sequential 着色），保留 discrete。
3. 数据准备支持连续值像元（当前仅整数类别码）。
4. 栅格模板 portrayal 的允许表达扩展至 interval。
5. 验收判据（承 §5）：同一 IR（interval+sequential）分别以 raster-cell / polygon lowering 出图一致。

### 9.5 阶段 3 计划：契约层合并（再合并，治重复）
1. portrayal/scene 去几何分叉：合并 raster_portrayal + vector_portrayal → 统一 `portrayal_resolver`（顺带消除 vector_portrayal 命名误解）。
2. 模板契约层合并为「专题基座（业务语义+版式+表达方法声明）+ 几何数据适配参数」，消除 60-70% 重复。
3. **执行层保留 raster/vector 分离**（数据本质差异，不强合并）。
4. scenario-capabilities：两 profile 重复段收敛，几何降为数据适配属性。

### 9.6 顺序不可反【设计推断】
先 2.3（补能力）→ 再阶段 3（合并契约）。若先合并而栅格仍只 unique-values，只会得到"一套同样死板的模板"——重复消除了，死板仍在。
