# 领导调研用图场景合并迁移与页面契约重构方案

日期：2026-11-24（Asia/Shanghai）
状态：待实施。本文取代同名旧稿的「恢复旧 image 分支」折衷路线。
性质：开发迁移与协议重构方案，不是机器协议；运行时不得把本文当作协议或审批依据读取。
前序：merge commit `2f4391d`（合入远端 `18d7ce6`「模板创建与复用闭环」）。

---

## 一、基线与根因（一手运行结果）

解释器 `D:\software\anaconda\python.exe`（Python 3.13.15），仓库根目录执行：

```
python skills/carto-agent/scripts/tests/run_tests.py --module test_leadership_visit
→ 87 tests, errors=50, failures=0
```

50 个错误闭合为四类（26+19+3+2=50，无未知根因）：

| 类 | 数量 | 根断点 | 证据 |
|---|---|---|---|
| A | 26 | scenario 文档旧词汇 `embedded:{identity,cartography,layout}` 被新 scenario schema 拒绝 | `scenarios/leadership_visit/route_author.py:151-152`；`schemas/scenario.schema.json:69-80`（`embedded` 仅允许 `style`/`layout`）、`:99-108`（`replaceable_segments` 枚举仅 `style`/`layout`） |
| B | 19 | page-request 的 `document` 键被拒 | `scenarios/leadership_visit/candidate_compiler.py:212-235`；`schemas/page-request.schema.json:182-187`（geometry 枚举仅 raster/vector）、`:8-19`（顶层强制 appearance/bindings） |
| C | 3 | page-request 的 `document`+`furniture` 双键被拒 | `candidate_compiler.py:225-226` |
| D | 2 | 模板生命周期改为单一 TP 审批 | `workflow/template_workflow.py:88-119`（`brief()` 不再返回 `approval`、`author()` 不收审批回执）；远端 `test_template_single_approval.py::test_old_t1_receipt_is_not_a_publication_approval` |

另有 **不在 50 之内** 的全量回归项：`compiler/component_protocols.py:126-132` 的 `ValidationScene` 声明了 `category_colors` 形参，`scenarios/leadership_visit/route_validation.py:140-145` 未跟上，`test_component_protocols.py` 的签名比对失败。

涉及测试分布：A 类含 BasemapRevisionLoopTests 4 / DataRevisionTests 6 / DesignRevisionTests 5 / OnlineBasemapDocumentTests 4 / OnlineSnapshotExportTests 2 / EndToEndWorkflowTests 1 等（凡经模板装载路径者先在此断裂）；B 类含 CompilerTests 3 / LegendCheckerTests 5 / RendererTests 6 / StyleOverrideTests 1；C 类 PageFurnitureTests 3；D 类 TemplateLifecycleTests 2。

---

## 二、设计裁决：为什么不是「给 image 加一个 geometry 值」

折衷路线（保留 geometry 单轴、新增第三值 `image`、仅改语义描述）有两处实质错误：污染数据形态维度；把旧设计的一个真实缺陷原样搬回。以下五条硬证据决定正确设计。

### 证据 1：两种 basemap 是同一个数学对象的两种参数化，代码已在互算

- `adapters/frontend_geo.py:88-106` `window_extent()` 把 leadership 的 `affine + display_window` **反算为 WGS84 extent bbox + center**——正是 general basemap 使用的 `crs + extent` 表示。
- `adapters/frontend_geo.py:52-74` `_validated_affine` 要求在线回放的配准必须**轴对齐等向**（`LEADERSHIP_ONLINE_BASEMAP_AFFINE_UNSUPPORTED`）。
- `adapters/geo_to_image_pixels.py:33-66` `PixelConverter` 的配准就是 2×3 仿射矩阵 + `origin_m` + `work_crs`（投影米制）。

结论：「配准」是一个 geo↔pixel 仿射；`crs+extent` 是其轴对齐等向参数化，`affine matrix` 是一般参数化。当前 schema 把同一概念写成两个不兼容形状（`page-request.schema.json:288-294` 与旧 image 分支的 `{image,source_size,display_window}`），是建模缺陷。**「image 需要独立数据形态」的最后一块支撑由此消除。**

### 证据 2：旧 image 分支禁 `layer_stack`，违反 schema 自述原则

`git show 2f4391d^1:skills/carto-agent/schemas/page-request.schema.json` 的 image 分支 `not.anyOf` 禁止 `appearance / bindings / portrayals / panels / cartography / coordinate_mode / layer_stack`。而当前 schema 对 layer_stack 的自述（`page-request.schema.json:277`）是：

> Frozen paint order: who covers whom is cartographic semantics, **not convention**.

image 页有确定绘制序（底图→路线/停靠→图例→文字），却被禁止声明，绘制序退化为渲染器硬编码约定。原样恢复即重新引入该违规。

### 证据 3：组件的既有范式是独立 schema + `$ref`，basemap 内联重复是欠账

`charts` 在两分支各 `$ref` 同一 `schemas/chart.schema.json`（`:370`、`:639`）；`basemap` 却在两分支各内联一份完整定义（`:288`、`:557`）。`chart.schema.json:5` 自述组件契约形态：placement-agnostic、经 `content_id` 绑 layout frame。basemap 应照此抽取——按仓库自身先例去重。

### 证据 4：`document.category` 硬编码单一场景名

旧 image 分支 `document.category` 枚举写死 `["leadership_visit"]`。内核 schema 枚举具体场景名，与「内核不得认识场景词汇」的边界方向相悖（`test_scenario_boundary.py` 守护）。应改用 `businessSceneId` + 目录成员资格校验（与 intent 同一模式）。

### 证据 5：装饰图/插画的接入点在 frame 类型，不在 geometry

`schemas/layout.schema.json:101-112` frame `type` 枚举 = `map/title/legend/scale-bar/north-arrow/inset/marginalia/chart`；`:93-96` `content_id` 仅绑 view/overlay。装饰图的正确接入是新增 frame 类型 + 绑定冻结 image material；**当前未实现，只能 roadmap 登记**（design-principles §2.1）。

### 补充范围事实（实施期更正）

初稿曾据「两份 schema 共用同一 description 与 geometry 条件体」推断 `page-output` 必须成对重构。**实施期核实推翻了这个推断**：`page-output` 只由 `adapters/page_renderer.py:202`（raster）与 `:253`（vector）产出，image 渲染器不产出页面报告，因此它**不需要 canvas 分支**——给无人产出的文档加分支属于为不存在的能力预写协议。它唯一需要的改动是 `request_ref.version` 的版本钉（4.0.0 → 5.0.0）。判别轴重构只落在 `page-request`。

---

## 三、目标契约设计

### 3.1 三个正交轴（顶层判别，不搬动既有字段位置）

`schemas/page-request.schema.json` 与 `schemas/page-output.schema.json`，`schema_version` 4 → 5：

```
geometry:        raster | vector                      # 语义收窄：纯专题数据形态，永不含 image
expression:      portrayal | canvas-overlay           # 新增：表达机器
coordinate_mode: native-no-reprojection
               | image-pixel-registration             # 由 const 扩为 enum：图体坐标空间
layer_stack:     必填（所有 expression）               # 修证据 2
```

条件体（各自封闭世界，全局 `additionalProperties: false` 不变）：

| | `expression: portrayal` | `expression: canvas-overlay` |
|---|---|---|
| geometry | raster 或 vector | 仅 vector（raster+canvas 未实现，schema 拒绝） |
| coordinate_mode | `native-no-reprojection` | `image-pixel-registration` |
| 必填 | `appearance` `bindings` `portrayals` `panels` `style` | `basemap` `overlay` |
| basemap | 可选 | 必填 |
| 禁止 | — | `appearance` `bindings` `portrayals` `panels` `style` |

**leadership-visit 如实声明 `geometry: "vector"`**——停靠点/路线本就是矢量要素；差异表达为「表达机器 = canvas-overlay，坐标空间 = 图片像素」，而非谎称数据是 image 形态。

`overlay` 携带画布叠绘内容声明（图形或其摘要引用），与 `render-scene` 的 `image_graphics` 同源冻结。这同时修正现存不对称：portrayal 页在 page-request 声明内容（portrayals/panels），canvas 页此前只把图形放在 render-scene。

**绘制序词汇不新增**：`layer_stack` 沿用既有枚举 `basemap/thematic/legends/charts/furniture`；canvas 页的 `overlay` 在绘制序中即 `thematic`（schema description 写明该对应关系）。典型 canvas 页 `layer_stack = ["basemap","thematic","legends","furniture"]`。

### 3.2 basemap 抽为统一组件 schema（修证据 1、3）

新增 `schemas/basemap.schema.json`，被 page-request/page-output 两分支共同 `$ref`：

```
image:            {path, digest, size_bytes}          # 冻结字节
registration:     oneOf[
                    {kind: "extent", crs:{authority,code}, extent:[4]},   # 轴对齐等向参数化
                    {kind: "affine", parameters_ref: artifactRef}         # 显式 2×3 仿射文档
                  ]
source_size?:     {width_px, height_px}
display_window?:  {x, y, width, height}
white_threshold?: 0..255                              # 测窗的声明参数（非程序默认值）
style?:           {desaturate, lighten}
```

`registration` 两变体互斥且各自 `additionalProperties: false`。

### 3.3 程序侧一致性规则（schema 表达不了的跨文档约束）

| 规则 | 错误码 | 现状 |
|---|---|---|
| affine 参数文档的 `source_size` 必须等于组件 `source_size` | `REGISTRATION_IMAGE_MISMATCH` | **复用既有门禁**（`geo_to_image_pixels.py:158-160` 已在投影能力内强制，不新增重复校验） |
| `display_window` 必须完整落在 `source_size` 内 | `BASEMAP_WINDOW_OUT_OF_BOUNDS` | 新增（落在渲染器复验边界，防篡改冻结合同） |
| `layer_stack` 必须等于该渲染器实际绘制序 | `LAYER_STACK_DRIFT` | **复用既有约定**（`static_page_renderer.py:99-102` 已如此；canvas 序为 basemap→thematic→furniture→legends） |
| canvas 页 `overlay.graphics_digest` 必须等于 scene 图形摘要 | `PAGE_OVERLAY_DRIFT` | 新增 |
| `expression: portrayal` + basemap ⇒ `basemap.crs == display_crs` | `BASEMAP_CRS_MISMATCH` | 保留（`general_thematic/vector.py:209-210`） |
| portrayal 页的底图必须是 extent 配准 | `BASEMAP_REGISTRATION_UNSUPPORTED` | 新增（`vector_page.py` / `page_renderer.py`） |
| 在线回放配准须 EPSG:3857 + 轴对齐等向 | `LEADERSHIP_ONLINE_BASEMAP_CRS_UNSUPPORTED` / `..._AFFINE_UNSUPPORTED` | 保留（`frontend_geo.py:52-74`） |
| 前端 geo 段需要 `display_window` | `FRONTEND_GEO_WINDOW_REQUIRED` | 保留（`frontend_geo.py:154-166`） |
| 工具输入字节漂移 | `IMAGE_TOOL_INPUT_DRIFT` | 保留（`image_tools.py:48-62`） |

初稿的 `BASEMAP_SOURCE_SIZE_MISMATCH` 与 `PAGE_LAYER_STACK_INCONSISTENT` 两个新码在实施期被撤销：前者与既有投影门禁重复，后者与既有绘制序约定（固定符号序，非「仅在场组件」）冲突。复用既有门禁优于新增竞争规则。

### 3.4 其他归位

- `document`：`{category: businessSceneId, name, geo?}`，`geo` 引用 `frontend-map-document.schema.json` 的 baseMap/mapData 段；仅在线底图声明时出现。去掉场景名硬编码（证据 4）。
- `furniture.frame_border` 与 `texts[].font_pt`：提升为**共享骨架**的可选字段（不再是 image 分支专有），两者都是通用的冻结版式事实。
- `document.category` 的目录成员资格由解析器校验，schema 只校验 ID 形状（与 `business_scene` 既有分工一致）。

### 3.5 不变量（实施全程必须保持）

1. `geometry` 永不出现 `image` 值；任何页面模式都不新增 geometry 取值。
2. 每个 expression 条件体封闭世界：未声明字段拒绝，不通过放宽既有 required 来容纳新模式。
3. 画布像素永不被改写：`geo-to-image-pixels` 只评估 lon/lat→源像素映射（`geo_to_image_pixels.py:1-11` 自述），`display_bounds` 只测量。
4. 内核不 import 场景模块；image 能力仍只经 ToolGateway 调用（`test_image_tool_boundary.py` 棘轮）。
5. 用户请求/提案协议形状不变；policies 语义字段不变。

---

## 四、分阶段实施与测试

测试入口统一为 `python skills/carto-agent/scripts/tests/run_tests.py`，真实可用参数：`--module NAME`（可重复）、`--test ID`（可重复）、`--tier fast|slow|full`（默认 full）、`--list`、`--strict-skips`、`--measure`。以下命令均在仓库根目录执行。

### 阶段 0：基线留档与 steward 对齐（不改代码）

**动作**
1. 确认解释器与 Schema 自检：`python skills/carto-agent/scripts/carto.py schema check`。
2. 留档基线：`run_tests.py --module test_leadership_visit`（记录 50 errors 的四类账目）。
3. 与 steward（`.github/CODEOWNERS`）对齐三项：
   - 本方案的 page-request/page-output 三轴重构 + 新增 basemap schema 属共享协议变更，送评审；
   - 远端 `18d7ce6` 加了 `grid.legend_placements` 但漏改 schema，本地已在 `scenario-capabilities.schema.json` 补声明（enum outside/inside，与 `compiler/parameter_domain.py:72` 消费一致）——若远端自行修复方式不同，合并前核对；
   - 确认「页面契约继续收敛于统一 page-request + 正交判别轴」仍是双方认可的方向（P3.6 收敛 doctrine 的延续）。

**测试**：`carto.py schema check`；`run_tests.py --module test_leadership_visit`；`run_tests.py --list --module test_leadership_visit`（确认选择集）。
**验收**：基线数字与四类账目留档；steward 对重构方向有明确答复。若 steward 裁定页面契约应按种类拆分，本方案阶段 4 需整体改写，不得先实施。

### 阶段 1：scenario 文档词汇迁移（修 A 类 26）

**改动点**（全部在场景包内，零内核改动）
1. `scenarios/leadership_visit/route_author.py:151`：`embedded` 改为 `{"style": CARTOGRAPHY, "layout": LAYOUT_CONTRACT}`。CARTOGRAPHY 常量内容不动——与 v2 `style.schema.json` 逐字段兼容（symbolization 含 color_system+symbol_catalogs、typography 各值在界内、catalogs 模式合法）。
2. `route_author.py:152`：`replaceable_segments` 改 `["layout"]`。**实施期更正**：初稿写 `["style","layout"]`（理由「identity 的语义继承者是 style」）是错的——旧列表是 `["identity","layout"]`，**`cartography` 当年就不可替换**（样式钉在实测 1.2.0 值上）。identity 段消亡 + cartography→style 改名后，忠实迁移就是 `["layout"]`。佐证：`leadership-visit-template-create-request.schema.json` 不支持 `segment_refs`，声明 style 可替换会是没有创作路径的权限；远端 `general_thematic/raster.py:491` 的惯例亦为 `replaceable_segments = sorted(refs)`。
3. `route_author.py:99-110` 的 IDENTITY 常量是**包身份引用**（namespace/kind/id/version，L145/L255 另有正当用途）——保留，只删 embedded 段。
4. 排查 `scenarios/leadership_visit/request_contract.py:222-223` 写入的 `embedded["map_title"]`：`map_title` 不在 scenario schema 的 `embedded` 属性表内。若该文档经 schema 重验会被拒——把实例标题移回 brief/plan 层（`compatibility.placeholders` 已有 `{{MAP_TITLE}}` 合同），不新增 schema 字段。
5. 场景其余代码只读 `embedded["layout"]`（`candidate_compiler.py:150`、`route_validation.py:236`、`planner.py:41`），零改动。测试以 `route_author.template_documents()` 为唯一内容源，无独立冻结 fixture 需改。

**测试**
```
run_tests.py --module test_leadership_visit --module test_scenario_boundary \
             --module test_scenario_registry --module test_schemas --module test_segment_refs
```
**验收**：A 类 26 errors 归零；剩余错误只应属 B/C/D 三类（逐条核对，不得有新增未归类错误）；`test_scenario_boundary` 绿；`git diff --stat` 证明改动仅在 `scenarios/leadership_visit/`。

### 阶段 2：组件协议签名对齐（修全量回归项）

**改动点**：`scenarios/leadership_visit/route_validation.py:140-145` 的 `route_validation_scene` 增加 `category_colors: Any = None` 形参，对齐 `compiler/component_protocols.py:126-132` 声明。内核调用方不传该参（`workflow/template_validation.py:627-632`），canvas 场景不消费它——默认 None 保证运行时零行为变化。

**测试**
```
run_tests.py --module test_component_protocols --module test_leadership_visit
```
**验收**：`test_component_signatures_match_the_declared_contract` 绿；leadership 错误数不因本阶段变化（除签名相关项）。

### 阶段 3：模板生命周期迁到单一 TP 审批（修 D 类 2）

**改动点**（测试侧迁移，不改审批语义）
1. `tests/test_leadership_visit.py:1784` 一带：删去 `briefed["approval"]["object_digest"]`，改按新协议取 `prepare_publication()` 的 `object_digest` 签 TP。
2. `workflow.author(create_path, t1, approval_key=...)` 改为新签名 `author(create_path)`（`workflow/template_workflow.py:115-119`）。
3. 参照远端 `tests/test_template_single_approval.py:75-105` 的迁移模式，改 `test_template_creation_publishes_real_repository` 与 `test_published_template_feeds_the_generate_route_without_seams`。

**测试**
```
run_tests.py --module test_leadership_visit --module test_template_single_approval \
             --module test_creation_orchestration --module test_template_proposal
```
**验收**：D 类 2 errors 归零；远端 `test_brief_no_longer_requests_approval` 与 `test_old_t1_receipt_is_not_a_publication_approval` 保持绿（证明未改审批语义）。合成审批仍不等于业务审批。

### 阶段 4：页面契约三轴重构 + basemap 组件统一（修 B 类 19 + C 类 3）

**一次做完，不得先恢复旧 image 分支再重构**——后者会先固化错误语义、再二次漂移全部内部产物摘要，等于把同一批冻结产物重编译两遍。

#### 4.1 新增 basemap 组件 schema

**改动**：新增 `schemas/basemap.schema.json`（§3.2 形状）。

**测试义务（硬门禁）**：`tests/test_schemas.py:33-42` 的 `test_every_instance_schema_has_valid_and_invalid_fixture` 要求**每个已注册 schema（除 common）都有合法与非法样例**。因此必须同步：
- `tests/fixtures/basemap.valid.json`（`registration.kind = "extent"`）
- `tests/fixtures/basemap.invalid.json`（未知字段 / 缺 `image.digest` / 两 registration 变体字段混用）
- 在 `tests/fixtures/schema_cases.py` 注册 `VALID_CASES["basemap"]` / `INVALID_CASES["basemap"]`（照 `:952-954` 的成对加载写法）
- 追加 affine 变体合法样例（`VARIANT_CASES["basemap.affine"]`）与跨文档语义非法样例（`SEMANTIC_INVALID_CASES`，§3.3 前三条）

```
run_tests.py --module test_schemas
```
**验收**：`test_every_schema_is_structurally_valid` 与 `test_every_instance_schema_has_valid_and_invalid_fixture` 绿（新 schema 无样例即红）。

#### 4.2 page-request / page-output 三轴重构

**改动**：两份 schema 同步施加 §3.1 判别轴与条件体、§3.4 归位；`schema_version` 4→5；`basemap` 改为 `$ref`（消除两处内联重复）；`layer_stack` 提为全模式必填；`coordinate_mode` 由 const 扩 enum 并按 expression 约束。

**测试义务**：
- 既有 `page-request` / `page-output`（portrayal-raster）与 `page-request.vector` / `page-output.vector` 样例**保持有效**——这是「没动远端契约本体语义」的证明；仅按新判别字段补 `expression`/`coordinate_mode`/`layer_stack`。
- 新增 canvas 变体样例：`page-request.canvas.valid.json` / `.invalid.json`、`page-output.canvas.valid.json` / `.invalid.json`，注册进 `VARIANT_CASES` / `VARIANT_INVALID_CASES`（照 `schema_cases.py:1027-1030`）。
- canvas 非法样例至少覆盖：出现 `appearance`/`bindings`/`portrayals`/`panels`/`style`；缺 `basemap`；缺 `overlay`；`geometry: "image"`；`geometry: "raster"` + canvas；`coordinate_mode` 与 expression 不匹配；缺 `layer_stack`；未知字段。

```
run_tests.py --module test_schemas --module test_page_bindings \
             --module test_layout_contract --module test_chart_protocol
```
**验收**：全部 portrayal 既有样例零语义改动通过；canvas 合法样例通过、上述每条非法样例被拒；`test_layer_ports` / `test_encapsulation` 不得新增允许清单条目。

#### 4.3 内核产出、校验与消费改造

**改动**
- 产出：`compiler/raster_page_contract.py`、`compiler/vector_page.py`、`compiler/raster_scene.py` 输出新判别字段与 `$ref` 形态的 basemap。
- 校验：`workflow/template_validation.py` 恢复 `IMAGE_ITINERARY_PAGE` import（descriptor 一直在 `backend_registry.py:53`），`_validation_cases` 恢复 canvas 单默认 case，`_verify_grid_cases` 按 `expression` 分派（读 `embedded["style"]`，新词汇），`_check_semantics` 恢复 portrayal 的 layers/layer_ids 二分（canvas portrayal 无 layers，靠 `PORTRAYAL_LAYERS_UNDECLARED` 校验声明 layer_ids）。
- 消费：`workflow/map_final_check.py`、`adapters/page_renderer.py`、`adapters/frontend_canvas.py` 按 expression 取图体字段；`adapters/frontend_geo.py` 的 `display_window` 门禁保留。
- 新增 §3.3 前三条一致性校验与错误码。

**测试**
```
run_tests.py --module test_general_thematic --module test_a31_thematic \
             --module test_raster_formal --module test_candidate_set \
             --module test_backend_registry --module test_webmap_renderer \
             --module test_grid_layout --module test_grid_inside_legend
```
**验收**：general 侧（raster + vector 变体）全部绿，含带 basemap 与不带 basemap 两条路径；新增一致性规则各有专属拒绝测试（`BASEMAP_SOURCE_SIZE_MISMATCH` / `BASEMAP_WINDOW_OUT_OF_BOUNDS` / `PAGE_LAYER_STACK_INCONSISTENT`）。

#### 4.4 场景产出端改造（leadership-visit）

**改动**：`scenarios/leadership_visit/candidate_compiler.py:209-227` 与 `route_validation.py:257-264` 产出 `geometry:"vector"` + `expression:"canvas-overlay"` + `coordinate_mode:"image-pixel-registration"` + `layer_stack` + `overlay` + `$ref` 形态 basemap（`registration.kind="affine"`，`parameters_ref` 指向已冻结配准参数文档）+ `document.category` 用 business_scene ID。

**消费端零改动**：`adapters/image_page_renderer.py`、`scenarios/leadership_visit/frontend_document.py`、`frontend_geo.py`、`style.py` 的字段消费路径不变（它们本来正确，只是供给方 schema 被换掉）；仅 basemap 取值路径随组件形状调整。

**测试**
```
run_tests.py --module test_leadership_visit --module test_image_tool_boundary
```
**验收**：B 类 19 + C 类 3 归零；RendererTests 6、LegendCheckerTests 5、PageFurnitureTests 3、CompilerTests 3、StyleOverrideTests 1 全绿；`test_image_tool_boundary` 绿（场景仍只经 ToolGateway 调用图像算法，未直连函数）。

#### 4.5 画布链路端到端与边界棘轮

**测试**
```
run_tests.py --module test_leadership_visit --module test_scenario_boundary \
             --module test_layer_ports --module test_encapsulation \
             --module test_digest_coverage --module test_image_tool_boundary
```
**验收**：
- 在线底图链路转绿：OnlineBasemapDocumentTests 4、OnlineSnapshotExportTests 2、BasemapRevisionLoopTests 4；
- 数据/设计修订链路转绿：DataRevisionTests 6、DesignRevisionTests 5、EndToEndWorkflowTests 1；
- 四个边界棘轮 + image 工具边界棘轮**只紧不松**：无新增允许清单条目；若本阶段修掉某处旧违规，同步删除其允许清单条目（AGENTS.md 明文要求）。

### 阶段 5：能力缺口登记与文档同步

**改动**
1. `policies/capability-roadmap.yaml` 登记「image material 的 frame 绑定（装饰图/插画/海报背景图）」为未交付特征，拒绝走 `admission_class=not_implemented`（design-principles §2.1）。**本次不实现**——不给未注册场景预写协议。
2. `SKILL.md` 同步：第 36 行「`page-request/output` 为 v4」改 v5；leadership_visit 段的词汇 `style`、单一 TP 审批下的 create-template 描述；「沿用旧框架 1.2.0 实测样式值」语义不变（变的是键名）。补一句页面契约三轴与 basemap 统一组件的边界陈述。
3. `tests/regression-baseline.json`：仅在全量绿之后，用 `run_tests.py --measure` 显式重写（该参数会改写基线，属 deliberate 动作，不得顺手执行）。

**测试**
```
run_tests.py --module test_capability_roadmap --module test_schemas
```
**验收**：新登记特征的拒绝分类测试绿（未声明或已 delivered 的特征不得返回 not_implemented）；文档与代码陈述一致。

### 阶段 6：全量回归与收口

本方案触及**公共协议**（page-request/page-output 重构 + 新增 basemap schema），按 AGENTS.md 开发回归约定**必须升级全量回归**，局部结果不得表述为全量通过。

**测试**
```
run_tests.py                      # 默认 --tier full
run_tests.py --strict-skips       # 可选：确认跳过项清单与已知环境项一致
```
**验收**
1. 零 fail / 零 error；7 个环境相关 skip 逐项核对为已知项（缺 fiona/rasterio/浏览器等），跳过项不得计为通过。
2. 全部边界守卫绿：`test_scenario_boundary` / `test_layer_ports` / `test_encapsulation` / `test_digest_coverage` / `test_image_tool_boundary` / `test_component_protocols`。
3. `test_digest_coverage` 证明新字段全部进入摘要绑定（新增 `expression`/`coordinate_mode`/`overlay`/`registration` 不得成为摘要盲区）。
4. 治理收口：阶段 0 三项 steward 对齐闭环；`policies/scenario-capabilities.yaml` 语义字段零改动复核（`max_revisions=3` 保留本地值，勿回退远端的 2）；既有冻结模板/候选/锁按现行 doctrine 重新准备/编译，**不自动迁移**、不新增迁移工具。

---

## 五、明确不做的事

- 不给 `geometry` 增加 `image` 或任何新取值；不建 `cartography` 兼容键、旧 schema wrapper 或向后兼容旁路（P3.6 直接替换）。
- 不为容纳 canvas 模式而放宽 portrayal 分支的 required 语义（顶层 required 下沉是结构性重组，每分支仍封闭世界）。
- 不实现装饰图/插画/海报背景图的 frame 绑定（未注册场景，只登记 roadmap）。
- 不改 `render-scene` 的 `renderer_id` 判别轴（它已是正确的轴，`image-itinerary-page` 分支完好）。
- 不改用户请求/提案协议形状（AGENTS.md 产物摘要稳定约束）；不改 policies 语义字段（避免触发既有冻结执行的漂移与重评审义务）。
- 不通过改策略、改锁、伪造回执放行任何门禁；`production_enabled: false` 等边界陈述不动。
- 不把本迁移与重构表述为真实业务验收：测试全部基于合成 fixture 与合成审批。

---

## 六、成本、依赖与顺序

**真实代价（不掩盖）**：page-request/page-output 是 general-thematic 与 leadership-visit 共用的契约，重构后**两个场景的既有冻结模板、候选、预览与锁全部需按现行 doctrine 重新准备/编译**。AGENTS.md 明文允许内部快照重编译且不自动迁移；用户请求形状不变，故对外产物摘要稳定性不受影响。

**改动面清单**
- schemas：`page-request` / `page-output` 重构（两份近重复分支去重后文件反而变短）、新增 `basemap`。
- 内核：`compiler/raster_page_contract.py`、`compiler/vector_page.py`、`compiler/raster_scene.py`、`workflow/template_validation.py`、`workflow/map_final_check.py`、`adapters/page_renderer.py`、`adapters/frontend_canvas.py`。
- 场景：`general_thematic/{raster,vector}.py`、`leadership_visit/{route_author,request_contract,candidate_compiler,route_validation}.py`。
- 测试与 fixture：`fixtures/schema_cases.py`、basemap 与 canvas 变体样例、一致性规则拒绝测试、`regression-baseline.json`。
- 文档与策略：`SKILL.md`、`policies/capability-roadmap.yaml`（仅登记，不改语义字段）。

**顺序与依赖**
```
阶段0 ──► 阶段1 ──┐
      ├─► 阶段2 ──┼──► 阶段4（4.1→4.2→4.3→4.4→4.5）──► 阶段5 ──► 阶段6
      └─► 阶段3 ──┘
```
阶段 1/2/3 相互独立、可并行，且与阶段 4 无耦合——先做以缩小失败归因噪声。阶段 4 依赖阶段 0 的 steward 答复。阶段 6 依赖全部前序。

**工作量定性**：阶段 1 约半天量级（纯机械键名迁移）；阶段 2/3 各为小项；阶段 4 是本方案主体（协议设计 + 双场景产出端 + 内核校验消费 + 三件套）；阶段 5/6 为收口。

---

## 七、实施记录（2026-11-24）

解释器 `D:\software\anaconda\python.exe`（Python 3.13.15）。逐阶段实测结果：

| 阶段 | 结果 | 关键事实 |
|---|---|---|
| 0 | `schema check` 118 ok；基线 87 tests / **50 errors** / 7.5s | 四类账目 26+19+3+2 全部对上 |
| 1 | A 类 **26 → 0** | 改动仅 `route_author.py` + `request_contract.py` 两个场景文件；另删除已无引用的 `IDENTITY` 常量与 `embedded.map_title` 死写入（无人读取、不入摘要） |
| 2 | `test_component_protocols` 7 项绿 | `shape()` 只比对 (名称, 种类, 有无默认值)，末位补 `category_colors=None` 即精确对齐 |
| 3 | `KeyError: 'approval'` 消除 | 两个生命周期测试前进到 `template_validation.py` 的 `KeyError: 'layers'`（属 4.3 范围） |
| 4.1 | `test_schemas` 28 项绿 | 新增 `basemap.schema.json` + 4 份样例；样例覆盖门禁（`test_schemas.py:33-42`）强制新 schema 必须配样例 |
| 4.2 | `test_schemas` 29 项绿 | page-request 重构为 910 行；canvas 合法样例通过、10 项变异 + portrayal/raster 禁用节点全部被拒 |
| 4.3 | general 侧 + 四棘轮 201 项 **0 errors** | 见下方「实施期更正」 |
| 4.4/4.5 | **leadership 125 项全绿（50 → 0）** | 含在线底图、数据/设计修订、渲染器、图例、page_furniture 全链路 |
| 5 | roadmap 与 registry 守卫 51 项绿 | 登记 `image-material-frame-binding`（backlog），roadmap 版本 1.0.3 → 1.0.4 |
| 6 | 全量 **1032 项：0 errors，7 skip，1 既有失败** | 37.1 min。唯一失败 `test_webmap_renderer.test_temporary_disk_limit_is_enforced` 经 pristine 检出归因为**既有环境失败**，非本次引入（见下） |

### 全量回归归因（阶段 6）

```
python skills/carto-agent/scripts/tests/run_tests.py
→ ran 1032/1032 in 2227.7s | failures=1 errors=0 skipped=7
```

- **0 errors**：50 个 leadership 错误与 general 侧连带全部清零。
- **7 skip**：环境相关（symlink 创建权限 ×3、独立 GIS 服务解释器 ×2 等），逐项为已知项，**不计为通过**。
- **1 failure 的归因证据**：`tests.test_webmap_renderer.DeterministicRendererTests.test_temporary_disk_limit_is_enforced`（`AssertionError: SecurityError not raised`）。用 `git worktree add --detach /tmp/carto-pristine HEAD` 在**不含本次任何改动**的 merge 提交 2f4391d 上单跑该模块，得到**同一测试、同一断言**的失败（10 tests / 1 failure）。结论：本机浏览器临时数据未达该测试设定的 16MB 阈值，属既有环境相关失败，与页面契约重构无交集（本次未改动 webmap/controlled renderer 及其磁盘限额）。验证后已 `git worktree remove` 清理。
- **未重写 `regression-baseline.json`**：全量并非全绿（存在上述既有失败），且 `--measure` 会改写基线计时，属需显式决定的动作，本次不执行。

### 实施期更正（一手事实推翻初稿判断）

1. **`replaceable_segments` 应为 `["layout"]`**，不是初稿的 `["style","layout"]`——旧列表里 `cartography` 本就不可替换。详见阶段 1 第 2 项。
2. **`page-output` 不需要 canvas 分支**，只需版本钉更新——它只由 raster/vector 静态渲染器产出。详见「补充范围事实」。
3. **撤销两个新错误码**：`BASEMAP_SOURCE_SIZE_MISMATCH` 与既有 `REGISTRATION_IMAGE_MISMATCH`（`geo_to_image_pixels.py:158-160`）重复；`PAGE_LAYER_STACK_INCONSISTENT`（「仅在场组件」）与既有绘制序约定（固定符号序，含 charts/furniture）冲突。改为复用 `LAYER_STACK_DRIFT`。
4. **basemap 字节上限取 64MB**（`67108864`），不是 general 旧 schema 的 256MB——依据 `image_page_renderer.py:41 MAX_BASEMAP_BYTES` 与 `static_assets.py:45` 的图片资产限额。这是把 schema 对齐渲染器真实门禁（收紧），不是放宽。
5. **顺带修正 raster 分支 `not` 的 AND 语义缺陷**：远端原写法 `not: {required: [style, coordinate_mode, panels]}` 只在三者**同时**出现时拒绝；改为 `anyOf` 逐项独立拒绝。属收紧，符合「只紧不松」。
6. **`texts[].font_pt` 保留在 canvas 条件体**，未提升为全模式共享——portrayal 模式无消费者，提升即为无消费者的预写协议。`furniture` 则按旧本地设计保留在顶层。
7. **`document` 在 portrayal 模式被禁用**（旧本地设计亦只在 image 分支声明），避免为无消费者的模式开放节点。
8. 版本钉连带面比初稿预估更广：`render-scene.schema.json` 4 处 + `page-output.schema.json` 1 处 + `artifacts.py protocol_version` + 9 份 fixture 的 `page-request` 引用，全部 4.0.0 → 5.0.0。

### 未同步项（需用户确认）

`AGENTS.md` 仍有「IDE 命令执行许可不等于 T1 / TP / G1 / G2 / G3」的陈述，而 T1 门已被远端单一 TP 模型移除。该文件是项目指令唯一来源，本次未改动，留待确认。
