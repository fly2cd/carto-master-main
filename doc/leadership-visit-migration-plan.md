# 领导调研用图场景迁移方案（v2.0 · 重基修正版）

日期：2026-11-18
版本：2.0
状态：重基到 Part I 后代码，合并 Part II map_json 成果本体路线

> **修正说明**：v1.0 写于 Part I 重构前，存在三类问题：① 拒绝了图片底图渲染管线（应保留并重构）；② 将 frontend JSON 定位为预览附加产物（应升格为成果本体）；③ 使用了独立 Schema 模式（应为 allOf 信封/信纸拆分）。v2.0 以[重基合并版](./leadership-visit-rebase-merged.md)和实际 Part I 代码为唯一事实依据，逐项修正。

---

## 一、Part I 后的代码真实状态

### 1.1 当前内核结构（`scenario_registry.py` L20-22）

```python
_IMPLEMENTATIONS: dict[str, str] = {
    "general-thematic": ".scenarios.general_thematic.manifest",
}
```

仅注册一个实现。新场景只需在此字典加一行——这是整个迁移中**唯一必须改动的内核行**。

### 1.2 当前后端注册表（`backend_registry.py` L43-56）

```python
RASTER_PAGE  = BackendDescriptor("rasterio-matplotlib-page", ...)
VECTOR_PAGE  = BackendDescriptor("matplotlib-vector-page", ...)
MAPLIBRE_WEB = BackendDescriptor("maplibre-web", ...)
```

三个后端。领导图需要第 4 个：`image-itinerary-page`（Matplotlib + PIL，图片底图 + 点线叠置）。

### 1.2.1 渲染器分发架构约束（防止误判）

**关键事实**：当前 `FormalRenderer`（[formal_renderer.py:154](skills/carto-agent/scripts/carto_core/adapters/formal_renderer.py#L154)）内部是一个 raster/vector 二元开关——`is_vector = self.renderer_id == PAGE_VECTOR_ID`——控制 `RendererProfile.current()`、`__init__`（选 `RasterSceneCompiler` 或 `VectorSceneCompiler`）、`controls`、`composition` 等全部路径。`create_render_backend` 目前仅两条分派：

```
IMPL_BROWSER → BrowserRenderBackend
IMPL_FORMAL  → FormalRenderer（内部分 raster/vector）
```

**领导图的 `image-itinerary-page` 不能走 `IMPL_FORMAL`**——落入 `FormalRenderer` 会实例化 `RasterSceneCompiler`（非 is_vector 分支），但其 `validate_scene` 不理解 `image_graphics`，必崩溃。

**正确做法**：`backend_registry.py` 新增独立 `impl` 常量，`create_render_backend` 新增第三条分派，直接构造 `ImagePageRenderer`（绕过 `FormalRenderer` 的 raster/vector 二元假设）：

```python
# backend_registry.py —— 新增 impl 常量
IMPL_IMAGE_ITINERARY = "image-itinerary"

IMAGE_ITINERARY_PAGE = BackendDescriptor(
    renderer_id="image-itinerary-page", family=STATIC_PAGE, geometry="vector",
    export_formats=frozenset({"pdf", "png"}), impl=IMPL_IMAGE_ITINERARY)
```

```python
# render_backend.py —— create_render_backend 新增第三条分派
def create_render_backend(renderer_id, **kwargs):
    backend = resolve(renderer_id)
    if backend.impl == IMPL_BROWSER:
        return BrowserRenderBackend(**kwargs)
    if backend.impl == IMPL_IMAGE_ITINERARY:      # 新增
        from .image_page_renderer import ImagePageRenderer
        kwargs.pop("browser", None); kwargs.pop("limits", None)
        return ImagePageRenderer(renderer_id=renderer_id, **kwargs)
    from .formal_renderer import FormalRenderer
    kwargs.pop("browser", None); kwargs.pop("limits", None)
    return FormalRenderer(renderer_id=renderer_id, **kwargs)
```

`ImagePageRenderer` 是独立类——自己实现 `render(session_id, scene)`、签发 `RenderReceipt`、`validate_scene` 等接口，不通过 `FormalRenderer` 也不通过 `PageRenderer`（`page_renderer.py` 的 raster/vector 二分 `render()` / `render_vector()` 同样不适用）。`test_backend_registry.py` 的 AST 守卫要求 `renderer_id` 字面量只出现在 `backend_registry.py`；代码文件中一律通过 `resolve("image-itinerary-page")` 或 `IMAGE_ITINERARY_PAGE.renderer_id` 派生，不得硬编码字符串。

### 1.2.2 geometry: "vector" 的分发机制（防止误判）

**易误判点**：看到 `geometry: "vector"` 容易认为内核会触发 `VectorPreparationService` / `VectorSceneCompiler` 等矢量工作流，与图片底图的需求不匹配。

**实际机制**：`geometry` 字段仅作为**信封级准入字段**（[scenario_registry.py:74-81](skills/carto-agent/scripts/carto_core/scenario_registry.py#L74-L81) 的 `_request_geometry`），用于将请求与策略中正确的 `geometry_variants` 条目匹配。后续管线的每一步都通过**场景组件钩子**分派，不由 geometry 值决定：

| 管线步骤 | 谁执行 | 领导图路径 |
|---|---|---|
| 数据准备 | `workflow/map_data_preparation.py` → `scenario.data_preparer.prepare()` | `RouteDataPreparer`（场景组件） |
| 规划 | `workflow/map_planning.py` → `scenario.planner.build()` | `RoutePlanner`（场景组件） |
| 编译 | `compiler/map_candidate.py` → `scenario.candidate_compiler.compile()` | `RouteCandidateCompiler`（场景组件） |
| 渲染 | `map_preview.py` → `create_render_backend(scene["renderer_id"])` | `ImagePageRenderer`（通过 `renderer_id` 分派，不由 geometry 决定） |

`VectorPreparationService` / `VectorSceneCompiler` 仅由 `general_thematic` 场景组件内部使用——它们不是内核根据 `geometry` 值的自动化分支，不会因 `geometry: "vector"` 而被意外触发。领导图场景包拥有自己完整的 10 个组件，管线每一步都走领导图自己的组件实现。

**设计决策依据**：领导图的主题数据（route-stops 的 Point + route-line 的 LineString）是矢量类型，图片底图是背景资源（`basemap.image_ref`），非主题几何。因此 `geometry: "vector"` 语义正确——它描述的是主题数据几何类型，不是渲染管线选择。`GEOMETRIES = ("raster", "vector")` 保持不变，不引入第三几何。

### 1.3 当前几何类型枚举（`general-generate-request.schema.json` L275-280）

```json
"geometry_types": {"items": {"enum": ["point", "multipoint", "polygon", "multipolygon"]}}
```

**不含 linestring**。领导图的路线数据需要补入——这是共享数据类型演进，不是场景特化。

### 1.4 当前场景包结构（`scenarios/general_thematic/`）

```
general_thematic/
  __init__.py          轻 import
  manifest.py          COMPONENTS + DEFAULTS（纯常量）
  dispatch.py          几何分派（raster/vector → 策略模块）
  raster.py            栅格策略
  vector.py            矢量策略
  request_contract.py  请求体理解（I-3）
  request_binding.py   数据准备请求体（I-4b）
  revision.py          修订语义（I-5）
```

领导图包参照此结构，但不需 `dispatch.py`（无几何变体）。

### 1.5 10 个组件钩子（`component_protocols.py`）

```
source_contract / request_contract / revision_contract /
data_preparer / planner / candidate_compiler /
legend_checker / author / validation_data_checker / validation_scene
```

领导图需实现全部 10 个。初期未实现的（author / validation_*）显式抛 `CAPABILITY_NOT_AVAILABLE`（不跳过校验）。

---

## 二、五个方向性修正

### 修正 1：渲染后端——从排除到保留重构

| | v1.0（错误） | v2.0（修正） |
|---|---|---|
| 后端 | `matplotlib-vector-page`（复用） | `image-itinerary-page`（新建，Matplotlib + PIL） |
| 图片底图管线 | 排除 | **保留核心算法，接口重构** |
| 理由 | "新框架矢量后端直接渲染" | 领导图的底图是图片资源（配准扫描图），不是矢量图层；需像素级配准和叠置 |

保留并重构的旧框架算法（核心逻辑保留，接口改为读 portrayal 合同）：

| 算法 | 原位置 | 新接口 |
|---|---|---|
| `geo_to_image_pixels` | 旧 `adapters/geo_to_image_pixels.py` | ToolGateway 能力：EPSG:4326 → 原图像素（确定性仿射） |
| `image_display` | 旧 `adapters/image_display.py` | ToolGateway 能力：透明/白边检测 → display_window |
| `image_layout` | 旧 `adapters/image_layout.py` | 像素 → 页面布局参数 |
| `apply_grouped_style` | 旧 `compiler/image_itinerary_style.py` | 读 `resolved-portrayal + page-request` → graphics 列表 |
| `annotation_solver` | 旧 `adapters/annotation_solver.py` | ToolGateway 能力：空间索引 + 模拟退火（固定 seed 确定性） |

### 修正 2：map_json——从附加产物到成果本体

| | v1.0 | v2.0 |
|---|---|---|
| 定位 | preview 阶段附加产物 | **成果本体**（Part II 双回路中心） |
| 结构 | 单层 canvasData | 三分层：facts / design / resolved |
| 生成时机 | 预览渲染后（依赖 PNG） | compile 阶段（纯数据产物，不依赖渲染） |
| 与 PDF 关系 | 嵌入 PNG 的独立文件 | 同一 graphics 的两路消费，像素一致 |

```
graphics 列表（结构化 line/point/callout/label/arrow）
  ├─→ ImagePageRenderer.render()       → PDF + PNG          → deliveries/<dest>/
  └─→ FrontendDocumentBuilder.build()  → map-document.json  → work/preview/（前端消费，暂不入交付包）
```

### 修正 3：Schema 模式——从独立到信封/信纸

| | v1.0 | v2.0 |
|---|---|---|
| 模式 | 独立 `leadership-generate-request.schema.json` | `allOf[$ref generate-request, leadership 体, unevaluatedProperties: false]` |
| geometry | 在场景 Schema 中 const | 在信封中声明（`geometry: "vector"`） |
| template.id | 在场景 Schema 中 const | 在场景体 Schema 中 const |

依据：[scenarios/README.md:60-62](skills/carto-agent/scripts/carto_core/scenarios/README.md) 规定的信封/信纸拆分模式。

### 修正 4：linestring 隶属——从场景特化到共享演进

| | v1.0 | v2.0 |
|---|---|---|
| 位置 | 场景专属 Schema | `general-generate-request.schema.json` 的 `geometry_types` enum |
| 性质 | 场景特化字段 | **共享数据类型演进**（路线是通用矢量类型） |

`general-generate-request.schema.json` L275 的 enum 从 `["point","multipoint","polygon","multipolygon"]` 扩展为 `["point","multipoint","linestring","multilinestring","polygon","multipolygon"]`。

### 修正 5：组件拆分——从 3 个合并文件到 9 个单一职责文件

| | v1.0 | v2.0（参照 general_thematic） |
|---|---|---|
| 合约层 | `route_contract.py`（2 个类合并） | `source_contract.py` + `request_contract.py` |
| 数据层 | `route_preparation.py` | `data_preparer.py` + `request_binding.py` |
| 编译层 | `route_scene.py`（4 个类合并） | `planner.py` + `candidate_compiler.py` + `revision.py` |
| 样式层 | 无 | `style.py`（apply_grouped_style） |
| 检查层 | 内嵌于 compiler | `legend_checker.py` |

---

## 三、编排权转移：从场景操作手册到代码组件

### 3.1 旧框架的编排模式

旧框架用一份 658 行的 `workflows/generate-map/leadership-visit.md` 场景操作手册来编排制图过程：

```
宿主 Agent 读 SKILL.md → routing.md → leadership-visit.md（658 行）
  → 逐段理解 prose 指令
  → 手动调用 carto capability invoke ...
  → 手动组装 generate-request.yaml
  → 手动进入 carto generate-map intake
```

手册中的每一段 prose 都在**弥补框架缺失的抽象**：

| 手册章节 | 行数 | 实际在做什么 | 框架缺失的抽象 |
|---|---|---|---|
| §0 路径展开规则 | ~20 | 教 Agent 怎么找文件 | 无 PathGuard |
| §0.1 读写映射表 | ~30 | 教 Agent 哪些文件可读、哪些必须 SHA256 验证 | 无 ImmutableArtifactStore |
| §2.3-2.4 目录结构 | ~40 | 教 Agent 项目目录该长什么样 | 无项目模板 |
| §2.5 image basemap | ~50 | 教 Agent 图片配准的 CLI 调用顺序 | 无 ToolGateway 自动化 |
| §2.6 分组配色 | ~40 | 教 Agent 分组颜色/路线偏移/水滴符号的参数 | 无 portrayal 合同 |
| §2.7 annotation layout | ~30 | 教 Agent 注记放置工具的参数 | 无 ToolGateway 自动化 |
| §2.8 MCP 行程准备 | ~60 | 教 Agent 四工具调用链和 revision_ref 传递 | MCP 服务独立但编排在手册 |
| §4 审批规则 | ~40 | 教 Agent G1/G2/G3 的审批对象和签名命令 | 无 ApprovalGateCoordinator |
| §5 CLI 参考 | ~100 | 教 Agent 每条命令的参数格式 | CLI 无场景感知 |
| §6 错误恢复 | ~30 | 教 Agent 中断后怎么恢复 | 无 WorkflowStateStore |
| §7 工具边界 | ~20 | 教 Agent 哪些能做哪些不能做 | 无 deny-by-default |
| §9 与洪水场景差异 | ~20 | 教 Agent 这个场景跟另一个有什么不同 | 场景未隔离 |

### 3.2 新框架的编排模式

新框架把这 658 行 prose **拆解为三层**，各归其位：

```
第一层：请求 Schema（机器协议）
  └─ leadership-visit-generate-request.schema.json（~60 行 JSON）
     作用：声明所有必填字段和合法值。Agent 组装请求时，Schema 验证自动拒绝
     非法输入。不需要 prose 告诉 Agent "别忘了填 itinerary_structure"。

第二层：场景组件（代码自动执行）
  └─ scenarios/leadership_visit/ 包（~1500 行 Python）
     内核在标准管线的每一步自动调用场景组件。Agent 不需要知道这些步骤的
     存在——它只需进入 carto generate-map intake，后续步骤由内核自动编排。

第三层：使用说明（人类可读的操作入口）
  └─ ~50 行 markdown
     只告诉用户：数据怎么准备、请求怎么组装、入口命令是什么。
     不再包含编排逻辑。
```

### 3.3 编排权逐项转移对照

```
旧框架                                      新框架
════════                                    ════════
场景手册 §0 路径展开规则                →   PathGuard（内核安全层，对所有场景生效）
                                              文件位置: security/paths.py
                                              触发: 所有路径操作自动校验

场景手册 §0.1 读写映射表                →   ImmutableArtifactStore + file_digest
                                              文件位置: repository/immutable_store.py
                                              触发: atomic_yaml/atomic_json 自动校验 digest

场景手册 §2.3-2.4 目录结构              →   不需要 prose——项目目录由 workflow
                                              文件位置: workflow/state_machine.py
                                              触发: WorkflowStateStore 自动创建/校验

场景手册 §2.5 图片配准                  →   ToolGateway 能力（声明+授权+执行+证据三段齐全）
                                              文件位置: request_contract.required_capabilities()（intake 授权门禁）
                                                        adapters/image_tools.py（handler 注册 + 网关工厂）
                                              触发: kernel intake 校验能力授权
                                              执行: candidate_compiler.compile() 经 gateway.invoke 调用
                                                    （类型化 I/O Schema、ToolResult 证据、预算扣减；
                                                      证据 artifact 以 contract 资源随 scene 冻结）

场景手册 §2.6 分组配色                  →   style.py apply_grouped_style()
                                              文件位置: scenarios/leadership_visit/style.py
                                              触发: candidate_compiler.compile() 内部调用
                                              参数来源: 模板 portrayal.yaml 合同

场景手册 §2.7 注记放置                  →   ToolGateway 能力（annotation-layout）+ candidate_compiler
                                              文件位置: adapters/annotation_solver.py（算法）
                                                        adapters/image_tools.py（能力绑定）
                                              触发: candidate_compiler.compile() 经 gateway.invoke 调用
                                              参数来源: request.annotation_layout（请求声明时才要求授权）

场景手册 §2.8 MCP 行程准备              →   独立 MCP 服务（不并入制图内核）
                                              编排缩减为: "MCP 准备行程 → 产出 GeoJSON → 放入 data/"
                                              request_contract.validate_body() 校验产出存在

场景手册 §4 审批规则                    →   ApprovalGateCoordinator（内核通用）
                                              文件位置: workflow/approvals.py
                                              触发: 内核在 G1/G2/G3 步自动编排
                                              场景差异: quality-gates.yaml 声明检查器清单

场景手册 §5 CLI 参考                    →   carto generate-map --help（内核通用）
                                              文件位置: cli/generate_cmd.py
                                              触发: 所有场景共用同一 CLI 面

场景手册 §6 错误恢复                    →   WorkflowStateStore（内置恢复协议）
                                              文件位置: workflow/state_machine.py
                                              触发: retry/receipts/delivery-status 子命令

场景手册 §7 工具边界                    →   ToolGateway.deny_by_default
                                              文件位置: adapters/tool_gateway.py
                                              触发: 所有工具调用自动授权校验

场景手册 §9 场景差异                    →   不需要——独立场景包，不存在交叉依赖
                                              文件位置: scenarios/leadership_visit/（完整隔离）
```

### 3.4 迁移后编排只需要三样东西

**1. 请求 Schema（机器读，~60 行 JSON）**

[leadership-visit-generate-request.schema.json](skills/carto-agent/schemas/leadership-visit-generate-request.schema.json)——`allOf[$ref generate-request, leadership 体, unevaluatedProperties: false]`。声明 `itinerary_structure`、`basemap`、`page_layout`、`annotation_layout` 等场景专有字段。Agent 组装请求时 Schema 自动校验，不需要 prose 做参数检查。

**2. 场景组件（内核自动调用，~1500 行 Python）**

内核在标准管线的每一步自动调用对应组件：

```
intake  → request_contract.validate_body()        校验 itinerary_structure + basemap 存在
           request_contract.required_capabilities() 校验 geo-to-image-pixels 等能力已授权
brief   → source_contract.suggestions()            建议数据角色和字段绑定
           source_contract.brief_roles()            列明 route-stops/route-line 角色清单
           request_contract.source_plan()           构建源计划
compile → data_preparer.prepare()                  normalize_itinerary + export_geojson
           planner.build()                          MapPlan v4（保留 intent 语义）
           candidate_compiler.compile()             geo_to_image_pixels → apply_grouped_style → RenderScene
           candidate_compiler.verify_request()      渲染重验证（request ↔ scene 一致性）
preview → ImagePageRenderer.render()               graphics → PDF+PNG + RenderReceipt
           FrontendDocumentBuilder.build()          graphics → map_json（成果本体）
check   → legend_checker()                         visit_order 连续性 + route_mode 合法性 + 分组颜色一致性
```

Agent 不需要知道任何一步的细节——它只需 `carto generate-map intake` 进入管线入口。

**3. 使用说明（人类读，~50 行）**

```
# 领导调研用图 — 使用说明

## 前置准备
1. 行程数据通过 MCP 行程服务准备：
   itinerary.check → geocoding.resolve → routing.plan → itinerary.finalize
   产出：data/itinerary.json + data/stops.geojson + data/route.geojson
2. 底图图片放入 data/basemap.png，配准参数写入 data/registration.yaml

## 进入制图
1. 组装 data/generate-request.yaml
   （字段参考: schemas/leadership-visit-generate-request.schema.json）
2. carto generate-map intake data/generate-request.yaml --project-root . --workdir work ...
3. carto generate-map brief data/generate-request.yaml
4. [签署 G1] carto generate-map compile ...
5. [签署 G2] carto generate-map freeze ...
6. carto generate-map render ...
7. carto generate-map check ...
8. [签署 G3] carto generate-map deliver ...

## 审批
G1/G2/G3 审批流程同通用制图。领导图特有检查器见模板 quality-gates.yaml。

## 输出
deliveries/<dest>/
  map.pdf + map.png + README.md + delivery-manifest.yaml + checksums.sha256

  工作目录（preview 阶段产出，不进入正式交付包）：
  work/preview/map-document.json（供前端消费；正式交付延后到 Part II 产品回路统一解禁）
```

**为什么 658 → 50 行**：编排逻辑从 "prose → Agent 阅读 → Agent 手动执行" 变为 "场景组件 → 内核自动调用 → Agent 只需进入入口"。剩下的 50 行只是告诉用户数据怎么准备、请求怎么组装、入口命令是什么——不再包含任何编排逻辑。

---

## 四、修正后的实施阶段

### L0：前置基础设施（阻塞性）

**目标**：让领导图的数据类型和后端在框架中合法存在。

**改动清单**：

| # | 文件 | 操作 | 内容 |
|---|---|---|---|
| L0-1 | `schemas/general-generate-request.schema.json` L275-280 | 修改 | `geometry_types` enum 追加 `"linestring"`, `"multilinestring"` |
| L0-1a | `schemas/data-role.schema.json` L34-38 | 验证/修改 | `geometry_types` enum 含独立枚举，需同步扩展（与 generate-request 保持一致） |
| L0-1b | `schemas/prepared-data-bundle.schema.json` L146-149, L306-309 | 验证/修改 | 两处 `geometry_types` enum（raster/vector 分支各自独立枚举），vector 分支需扩展 |
| L0-1c | `schemas/map-expression.schema.json` L48-54 | 验证/修改 | `geometry_types` enum 需同步扩展 |
| L0-1d | `schemas/template-analysis.schema.json` L83-87 | 验证/修改 | `geometry_types` enum 需同步扩展 |
| L0-1e | `schemas/template-brief.schema.json` L166-169 | 验证/修改 | `geometry_types` enum 需同步扩展 |
| L0-2 | `schemas/vector-input.schema.json` | 验证 | 确认 linestring 兼容（当前不含 geometry_types 枚举，由 generate-request 约束） |
| L0-3 | `carto_core/backend_registry.py` L43-56 | 新增 | `IMPL_IMAGE_ITINERARY` 常量 + `IMAGE_ITINERARY_PAGE` BackendDescriptor（`impl` 必须为新常量，不能复用 `IMPL_FORMAL`；详见 §1.2.1） |
| L0-3a | `carto_core/adapters/render_backend.py` L75-84 | 修改 | `create_render_backend` 新增 `IMPL_IMAGE_ITINERARY` 分派分支，直接构造 `ImagePageRenderer` |
| L0-4 | `schemas/render-scene.schema.json` L225-427 | 修改 | ① `renderer_id` enum（L312-316）追加 `"image-itinerary-page"`；② 静态页 oneOf 变体新增 `image_graphics` 字段（`apply_grouped_style` 的产出载体，当前 Schema 无此字段） |
| L0-5 | `schemas/page-request.schema.json` | 验证/修改 | 确认支持 image-native 像素页面参数 |
| L0-6 | 回归测试 | 运行 | 现有测试零新增失败；新增 `test_backend_registry.py` 确认新后端注册 |

**验证**：
```bash
python -m pytest skills/carto-agent/scripts/tests/test_backend_registry.py -v
python -m pytest skills/carto-agent/scripts/tests/ -v --ignore=tests/manual -k "not render"
```

### L1：数据合约 + Schema

**目标**：定义领导图的数据角色、请求体理解和请求 Schema。

**新建文件**：

```
scenarios/leadership_visit/
  __init__.py              ← 轻 import（3 行）
  manifest.py              ← COMPONENTS + DEFAULTS（30 行）
  source_contract.py       ← RouteSourceContract（~80 行）
  request_contract.py      ← RouteRequestContract（~100 行）
```

**修改文件**：

| # | 文件 | 操作 |
|---|---|---|
| L1-1 | `scenario_registry.py` L21 | `_IMPLEMENTATIONS` 加一行：`"leadership-visit": ".scenarios.leadership_visit.manifest"` |
| L1-2 | `policies/scenario-capabilities.yaml` | 新增 `leadership-visit-mapping@1.0.0` profile |
| L1-3 | `schemas/leadership-visit-generate-request.schema.json` | 新建：`allOf[$ref generate-request, 领导体, unevaluatedProperties: false]` |

**`scenario-capabilities.yaml` profile 核心字段**：
```yaml
- id: leadership-visit-mapping
  version: 1.0.0
  implementation: leadership-visit
  routes:
  - generate-map              # P5 加 create-template
  request_schemas:
    generate-map: leadership-visit-generate-request
  intent_constraints:
    business_scene: leadership_visit
    allowed_tasks: [visit-route-map]
    allowed_theme_tags: []
    required_theme_tags: []
  data_nature: user-provided
  production_enabled: false
  notice: 领导调研路线图：行程路线为示意参考，不用于实际导航
  output_profile:
    width_mm: 420
    height_mm: 297
    dpi: 300
    width_px: 4961
    height_px: 3508
  output_constraints:
    max_width_mm: 420
    max_height_mm: 297
    min_dpi: 144
    max_dpi: 300
    allowed_formats: [pdf, png]
  layout_constraints:
    allowed_models: [image-native, fixed-page]
  geometry_variants:
  - geometry: vector           # 点+线主题数据，非 image 几何
    template:
      kind: map-scenario
      id: leadership-visit-map
      version: 1.0.0
    authoring_profile: leadership-visit-authoring
    renderer_id: image-itinerary-page
```

**`source_contract.py` 核心职责**：

- `suggestions()` → 返回 route-stops（必填 Point）+ route-line（可选 LineString）+ basemap 资源建议
- `validate_role_bindings()` → 校验 route-stops 存在且 geometry_types 含 point
- `validate_source_profile()` → 行程敏感声明检查（不含坐标入日志）
- `brief_roles()` → 返回角色清单供 MapBrief 使用

**`request_contract.py` 核心职责**：

- `geometry()` → `"vector"`（点+线，非 image 几何）
- `required_fields()` → frozenset 含 `itinerary_structure`、`basemap`
- `required_capabilities()` → `{"read", "render-preview", "geo-to-image-pixels", "image-display-bounds"}`
- `validate_body()` → 校验 `itinerary_structure.source_ref` 与 `basemap` 存在
- `source_plan()` → 从请求体构建 brief 的源计划

**Schema（`leadership-visit-generate-request.schema.json`）**：
```json
{
  "$id": ".../leadership-visit-generate-request.schema.json",
  "allOf": [
    {"$ref": "generate-request.schema.json"},
    {
      "required": ["geometry", "itinerary_structure", "basemap"],
      "properties": {
        "geometry": {"const": "vector"},
        "itinerary_structure": {
          "source_ref": {"$ref": "common.schema.json#/$defs/artifactRef"},
          "normalized_ref": {"$ref": "common.schema.json#/$defs/artifactRef"}
        },
        "basemap": {
          "mode": {"const": "registered-transform"},
          "image_ref": {"$ref": "common.schema.json#/$defs/artifactRef"},
          "parameters_ref": {"$ref": "common.schema.json#/$defs/artifactRef"}
        },
        "page_layout": {
          "oneOf": [
            {"$ref": "image-native-layout.schema.json"},
            {"$ref": "fixed-page-layout.schema.json"}
          ]
        },
        "annotation_layout": {
          "seed": {"type": "integer"},
          "iterations": {"type": "integer", "minimum": 1},
          "gap_px": {"type": "integer", "minimum": 1}
        }
      }
    }
  ],
  "unevaluatedProperties": false
}
```

**验证**：
```bash
python skills/carto-agent/scripts/carto.py schema check
# 确认 leadership-visit-mapping profile 加载成功（manifest 尚未有实现 → 预期 CAPABILITY_NOT_AVAILABLE，非崩溃）
```

### L2：数据准备 + 意图接入

**目标**：实现行程数据标准化、GeoJSON 导出、意图解析集成。

**新建文件**：

```
scenarios/leadership_visit/
  data_preparer.py         ← RouteDataPreparer（~150 行）
  request_binding.py       ← prepare/validate（~80 行）
  planner.py               ← RoutePlanner（~100 行）
  revision.py              ← RouteRevisionContract（~40 行）
```

**`data_preparer.py` 核心逻辑**（继承旧框架 `itinerary_structure.py` 的算法）：

```python
class RouteDataPreparer:
    def prepare(self, request, request_ref) -> dict:
        # 1. normalize_itinerary(): 验证 places/stops/legs/activities，
        #    合并连续停留，分配 map_role (origin/visit/waypoint/destination)
        # 2. export_geojson(): 导出 route-stops（Point + 元数据属性和 route-line（LineString）
        # 3. 冻结为 PreparedDataBundle，绑定 source_ref + normalized_ref
```

**`planner.py` 核心逻辑**：

```python
class RoutePlanner:
    def build(self, request, intent, brief, bundle, installation, contracts) -> dict:
        # 从模板 portrayal 合同读取 image_itinerary 表达参数
        # 从模板 layout 合同读取画布/页面参数
        # 构建 MapPlan v4：保留 intent 的 business_scene/theme_tags/tasks
        # 决策：extent（从底图配准参数计算）+ cartography_ref + layout_ref
```

**注意**：planner 不执行像素投影或渲染——只声明语义决策供 compiler 机械执行。

**验证**：
```bash
python -c "from carto_core.scenarios.leadership_visit.data_preparer import RouteDataPreparer; print('OK')"
python -c "from carto_core.scenarios.leadership_visit.planner import RoutePlanner; print('OK')"
```

### L3：渲染管线核心

**目标**：实现图片底图配准、分组样式应用、RenderScene 编译、两路 graphics 消费。

**新建文件**：

```
scenarios/leadership_visit/
  candidate_compiler.py    ← RouteCandidateCompiler（~200 行）
  style.py                 ← apply_grouped_style（~250 行，从旧 image_itinerary_style 重构）

carto_core/adapters/
  image_page_renderer.py   ← ImagePageRenderer（~300 行，新建）
```

**重构文件**（从旧框架迁移，接口改为读 contract）：

```
carto_core/adapters/
  geo_to_image_pixels.py   ← 从旧 geo_to_image_pixels 迁移（~80 行）
  image_display.py         ← 从旧 image_display 迁移（~60 行）
  image_layout.py          ← 从旧 image_layout 迁移（~100 行，重构接口）
```

**`style.py` 核心逻辑**（从旧 `image_itinerary_style.py` 重构）：

```python
def apply_grouped_style(resolved_portrayal, page_request, itinerary_data) -> list[dict]:
    """从 portrayal 合同 + 页面参数 + 行程数据 → 结构化 graphics 列表。
    
    输入：resolved-portrayal（含 image_itinerary 分组配色/路由/标记/信息框/编号定义）
          page-request（物理页面 mm/pixel 映射）
          itinerary_data（标准化后的 stops + legs）
    输出：graphics 列表 [{type: line/point/callout/label/arrow, ...}, ...]
    
    核心算法（保留旧框架逻辑，接口重构）：
    - 分组配色（morning/afternoon/default → hex）
    - 路线右偏（相邻方向相同 → 偏移避免重叠）
    - 箭头（按间距放置 → 方向角计算）
    - 信息框候选搜索（空间索引 + 贪心 + 模拟退火，固定 seed）
    - 引线（信息框 → 停靠点，含弯折点）
    - 水滴符号（pin marker + 编号 + 支持标签）
    """
```

**`candidate_compiler.py` 核心逻辑**：

```python
class RouteCandidateCompiler:
    def compile(self, request, intent, plan, bundle, installation, contracts, font_path) -> dict:
        # 1. geo_to_image_pixels(basemap_params) → 像素投影变换
        # 2. image_display(basemap_image) → display_window
        # 3. image_layout(params) → 页面布局参数
        # 4. apply_grouped_style(portrayal, page, itinerary) → graphics 列表
        # 5. 构建 RenderScene（renderer_id=image-itinerary-page，viewport 含 image_frame）
        #     graphics 作为 scene.image_graphics 嵌入
        # 6. 构建 resolved-map candidate（execution 含 profile_refs/intent_ref/data_nature）
        # 返回 {candidate, scene, preflight}
    
    def verify_request(self, request, scene, inputs) -> None:
        # 校验 scene.renderer_id == "image-itinerary-page"
        # 校验 basemap image_ref digest 与 request 一致
```

**`ImagePageRenderer`（`adapters/image_page_renderer.py`）**：

```python
class ImagePageRenderer:
    """Matplotlib + PIL 图片底图渲染器。
    
    消费 RenderScene.image_graphics → 在配准底图上绘制点/线/标注 → 导出 PDF/PNG。
    不经过 Chromium/SVG DOM。graphics 与 FrontendDocumentBuilder 共享，保证像素一致。
    """
    def render(self, session_id, scene) -> dict:
        # 1. 加载底图图片（PIL）
        # 2. 创建 Matplotlib Figure（尺寸 = scene.viewport）
        # 3. 遍历 graphics 列表：
        #    - line → Line2D
        #    - point → scatter / Ellipse
        #    - callout → FancyBboxPatch + Text
        #    - label → Text（含 halo）
        #    - arrow → FancyArrowPatch
        # 4. 导出 PDF + PNG
        # 5. 签发 RenderReceipt（HMAC 签名）
```

**两路消费**：

```
apply_grouped_style() → graphics
  ├─→ ImagePageRenderer.render()       → PDF + PNG + RenderReceipt
  └─→ FrontendDocumentBuilder.build()  → map_json（canvasData + mapData）
```

**验证**：
```bash
# 确认新后端注册
python -c "from carto_core.backend_registry import resolve; print(resolve('image-itinerary-page'))"
# 单元测试
python -m pytest skills/carto-agent/scripts/tests/ -v -k "image"
```

### L4：map_json 成果本体 + 前端文档构建器

**目标**：实现三分层 map_json 产出和前端文档构建。

> **交付约束**：`map-document.json` 在 preview 阶段产出到工作目录（`work/preview/`）供前端消费，**不进入正式交付包**。当前内核有三道防线阻止 json 进入交付链：
> - [delivery-manifest.schema.json](skills/carto-agent/schemas/delivery-manifest.schema.json) L81-85：`artifacts[].format` enum 仅 `["pdf", "png"]`
> - [map_delivery.py:159](skills/carto-agent/scripts/carto_core/workflow/map_delivery.py#L159)：运行时集合检查 `== {"pdf", "png"}`
> - [scenario-capabilities.schema.json](skills/carto-agent/schemas/scenario-capabilities.schema.json) L172-177：`allowed_formats` enum 仅 `["pdf", "png", "svg"]`（不包含 `json`）
>
> 正式交付延后到 Part II 产品回路统一解禁。`allowed_formats` 在 profile 中保持 `[pdf, png]`。

**新建文件**：

```
scenarios/leadership_visit/
  frontend_document.py     ← FrontendDocumentBuilder（~250 行）
```

**`frontend_document.py` 核心逻辑**：

```python
class FrontendDocumentBuilder:
    """从 graphics 列表构建 map_json（Part II 三分层成果本体）。
    
    不依赖渲染产物 PNG——与 ImagePageRenderer 消费同一 graphics 列表。
    canvasData 的坐标变换与 ImagePageRenderer 使用相同 scale，保证像素一致。
    """
    
    def build(self, graphics: list[dict], page_request: dict, *,
              facts: dict, design: dict, identifier: str) -> dict:
        """构建 map_json = {product_id, revision, facts, design, resolved, provenance}。
        
        facts:     {itinerary_bundle_ref, basemap_ref, sources, crs, sensitivity}
        design:    {image_itinerary 分组样式, layout_params, cartography, title}
        resolved:  {render_scene_ref, canvasData, mapData, resolve_inputs_ref(digest)}
        provenance:{session_id, parent_revision, version_history_ref}
        """
        # 1. canvasData 构建（从 graphics 列表转换，mm 坐标）
        #    - line → MultiLineString feature
        #    - point → MultiPoint feature（含 icon SVG inline）
        #    - callout → Rect + Text features
        #    - label → Text feature
        #    - arrow → MultiLineString feature (leader line)
        # 2. mapData 构建（结构化图层元数据：图层 ID、类型、字段、交互配置）
        # 3. resolved 封装（render_scene_ref + canvasData + mapData + resolve_inputs_digest）
        # 4. 全量 digest 绑定（facts/design/template/catalog/policy 摘要）
        # 5. Schema 验证（frontend-map-document）
```

**关键设计点**：

- `FrontendDocumentBuilder` **不从 SVG 遍历**（旧 `_walk()` 方法废弃）。它直接从 `graphics` 列表构建——graphics 是 `apply_grouped_style` 的结构化输出，包含所有需要的坐标/颜色/文本。
- canvasData 使用 mm 坐标（与 ImagePageRenderer 同一个 `mm = px × page.width_mm / viewport.width_px` 变换），保证前端渲染与 PDF 像素一致（误差 < 0.01mm）。
- map_json 不嵌入 base64 PNG（不依赖渲染产物）。前端从独立文件加载底图图片。

**验证**：
```bash
python -c "from carto_core.scenarios.leadership_visit.frontend_document import FrontendDocumentBuilder; print('OK')"
# 合成数据端到端：compile → graphics → FrontendDocumentBuilder.build() → 验证 Schema
```

### L5：注记求解器 + 交付闭环

**目标**：迁移 annotation_solver 为 ToolGateway 能力，实现检查器，跑通端到端交付。

**新建/迁移文件**：

```
carto_core/adapters/
  annotation_solver.py     ← 从旧 annotation_solver 迁移（~300 行）

scenarios/leadership_visit/
  legend_checker.py        ← RouteLegendChecker（~60 行）
  route_author.py          ← 模板授权桩（~20 行）
  route_validation.py      ← 模板验证桩（~20 行）
```

**工具注册**：

`policies/tool-bindings.yaml` 新增：
```yaml
- capability_id: geo-to-image-pixels
  version: 1.0.0
  adapter: local
  effect: transform
  authorization_policy: image-basemap-approved
  credential_mode: none
  snapshot_policy: required

- capability_id: image-display-bounds
  version: 1.0.0
  adapter: local
  effect: read
  authorization_policy: image-basemap-approved
  credential_mode: none
  snapshot_policy: required

- capability_id: annotation-layout
  version: 1.0.0
  adapter: local
  effect: transform
  authorization_policy: annotation-approved
  credential_mode: none
  snapshot_policy: required
```

**`legend_checker.py`**：
```python
def route_legend_checker(context: dict) -> tuple[bool, dict, None]:
    # 1. visit_order 连续性（从 bundle 获取）
    # 2. route_mode 合法性（road_network/provided_geometry/schematic/straight_line）
    # 3. 分组颜色一致性（morning/afternoon labels 不冲突）
    # 4. 信息框内容与停靠点匹配
```

**模板合同包**：`templates/map-scenario/leadership-visit-map/1.0.0/`

参照旧框架 1.2.0 版本的 image_itinerary 分组样式，转换为标准 portrayal 合同格式：

```yaml
# portrayal.yaml 核心
image_itinerary:
  groups:
    morning:  {color: '#1769D2', label: 上午}
    afternoon: {color: '#E43D96', label: 下午}
    default:   {color: '#403B96', label: 行程}
  route:
    width_px: 6
    arrow_size_px: 8
    arrow_spacing_px: 200
    offset_px: 12       # 同向偏移量
  pin:
    radius_px: 12
    stroke_width_px: 2
    numbering: per-date-group
  callout:
    width_px: 500
    title_font_size_pt: 22
    body_font_size_pt: 14
    opacity: 0.88
  support_label:
    color: '#E65C6C'
```

**正式交付包**（map.pdf + map.png + README.md + delivery-manifest.yaml + checksums.sha256）。

`map-document.json` 在 preview 阶段产出到工作目录（不进入交付包；见 L4 交付约束）。

**验证**：
```bash
# 合成数据端到端（图片底图用合成像素）：
# compile → preview → freeze → render → check → review → deliver
# 预期：全绿，产 PDF+PNG+map_json
```

### L6：模板路由（后续）

`author` / `validation_data_checker` / `validation_scene` 组件从桩实现改为真实实现。`scenario-capabilities.yaml` 的 `routes` 加 `create-template`。`capability-roadmap.yaml` 登记 `image-itinerary` 表达。依赖 L4 完成。

### 独立轨道：敏感准入 + MCP 行程服务

- **敏感领导能力准入**：作为独立安全能力送审（策略 + 安全检查组件 + 真实数据验收），不夹带进本实施
- **MCP 行程服务**：复用旧框架 `services/itinerary-mcp/` 作为独立 MCP 服务，不并入制图内核

---

## 五、不迁移清单（v2.0 修正）

| 组件 | 理由 |
|---|---|
| `scene_hint` 字符串分发 | 违反 `test_scenario_boundary.py` Guard B |
| `general_dispatch` 加 image 分支 | 开倒车——Part I 已拆掉此耦合 |
| `_walk()` SVG 遍历（`frontend_json.py`） | 由 FrontendDocumentBuilder 从 graphics 列表直接构建替代 |
| `SvgCompositor` | Chromium poster 管线，领导图不用 |
| `poster-templates/` SVG | 同上 |
| `compile-decisions` LLM 运行时设计 | LLM 选表达进入模板合同，编译期纯机械推导 |
| `_approve_leadership()` 特殊审批路径 | 统一 ApprovalGateCoordinator |
| `map_generation.py` 中 15+ 处 if/else | Part I 已通过插槽地基消除 |
| 旧模板版本 1.0.0/1.1.0（A3 海报/源原生图片） | 新模板从 1.0.0 重新开始，使用标准 portrayal 合同 |
| `prepare-request` CLI 子命令 | 数据准备由 DataPreparer + MCP 服务完成 |
| `data_summary.py` DOCX 解析 | 不保留独立 CLI 入口；引擎 `file_parser.py` 收编为 data-summary ToolGateway 能力，经唯一 CLI `carto data summarize` 只读执行（PathGuard + 证据回执） |
| 658 行 Agent 操作规程 | 缩减为约 50 行使用说明（核心：MCP 准备行程 → carto generate-map intake） |

### 保留并重构的旧框架算法

| 算法 | 保留原因 | 重构方式 |
|---|---|---|
| `normalize_itinerary` | 行程标准化是业务核心 | 迁入 `data_preparer.py`，作为 RouteDataPreparer 的内部方法 |
| `geo_to_image_pixels` | 图片配准的数学核心（确定性仿射） | 迁入 `adapters/`，作为 ToolGateway 能力 |
| `image_display` | 透明/白边检测 | 同上 |
| `image_layout` | 像素→页面布局 | 接口改为读 page-request 合同 |
| `apply_grouped_style` | 分组配色/路线右偏/箭头/水滴符号 | 接口改为读 resolved-portrayal，输出 graphics 列表 |
| `annotation_solver` | 空间索引 + 模拟退火注记避让 | ToolGateway 能力，固定 seed 确定性 |
| MCP 行程服务 | 地理编码/路径规划的完整实现 | 独立服务，不并入制图内核 |

---

## 六、实施总结

| 阶段 | 内容 | 新建文件 | 修改文件 | 预估代码量 |
|---|---|---|---|---|
| L0 前置 | linestring 多 Schema 扩展 + image-itinerary-page 后端注册（含 `IMPL_IMAGE_ITINERARY` 常量）+ render_backend 三路分派 + render-scene `image_graphics` 字段 | 0 | 3 代码 + 7 Schema | ~60 行 Py + ~30 行 JSON |
| L1 数据 | source_contract + request_contract + Schema + manifest + 策略 | 6 | 2 | ~250 行 Py + ~100 行 YAML + ~60 行 JSON |
| L2 准备 | data_preparer + request_binding + planner + revision + intent 集成 | 4 | 0 | ~370 行 Py |
| L3 渲染 | candidate_compiler + style + ImagePageRenderer + geo_to_image_pixels + image_display + image_layout | 6 | 1 | ~990 行 Py |
| L4 成果 | FrontendDocumentBuilder + map_json Schema | 1 | 0 | ~250 行 Py |
| L5 交付 | annotation_solver + legend_checker + author/validation 桩 + tool-bindings（3 能力）+ checker-registry（itinerary.*）+ 模板合同 + 端到端测试 | 10 | 2 | ~460 行 Py + ~200 行 YAML |
| L6 模板 | author/validation 真实实现 + create-template 路由 | 0 | 3 | ~300 行 Py |

总计：**新建 27 个文件，修改 10 个核文件 + 7 个 Schema 文件，约 2620 行 Python + 300 行 YAML + 90 行 JSON Schema**。

**关键原则**：
- 内核改动仅限于 L0（共享数据类型演进 + 新后端注册）+ `_IMPLEMENTATIONS` 一行
- 保留旧框架业务算法精华（normalize_itinerary、geo_to_image_pixels、apply_grouped_style、annotation_solver），接口重构到新框架的 portrayal/layout 合同体系
- map_json 是成果本体（不是附加产物），与 PDF/PNG 同为 graphics 的消费端
- 不引入第三几何 image（用 vector + basemap 资源 + 独立 renderer）
- 敏感准入剥离独立送审，不夹带

---

## 附录 A：目标目录对照表

以下列出迁移涉及的所有文件，标注状态（不变 / 修改 / 新建）及操作说明。以 `D:\workspace\project_1\IGSA_1118\Intelligent_Geo-Spatiotemporal_Agent\` 为仓库根。

### A.1 内核文件 —— 几乎全部不变

```
skills/carto-agent/scripts/carto_core/

  __init__.py                         不变
  artifacts.py                        不变
  canonical.py                        不变
  errors.py                           不变
  geospatial_deps.py                  不变
  roadmap.py                          不变
  schema_registry.py                  不变

  scenario_registry.py                修改  L1-1: _IMPLEMENTATIONS 加一行
                                        "leadership-visit": ".scenarios.leadership_visit.manifest"

  backend_registry.py                 修改  L0-3: 新增 IMPL_IMAGE_ITINERARY 常量 + IMAGE_ITINERARY_PAGE BackendDescriptor（impl=IMPL_IMAGE_ITINERARY，非 IMPL_FORMAL）

  cli/__init__.py                     不变
  cli/_shared.py                      不变
  cli/data_cmd.py                     不变
  cli/environment_cmd.py              不变
  cli/generate_cmd.py                 不变
  cli/intent_cmd.py                   不变
  cli/schema_cmd.py                   不变
  cli/security_cmd.py                 不变
  cli/template_cmd.py                 不变

  compiler/__init__.py                不变
  compiler/appearance.py              不变
  compiler/chart_core.py              不变
  compiler/component_protocols.py     不变（FrontendDocumentBuilder 非组件钩子，由 candidate_compiler 内部调用，不通过 ScenarioCapability.component() 加载）
  compiler/dependencies.py            不变
  compiler/expression_validator.py    不变
  compiler/grid_layout.py             不变
  compiler/layout.py                  不变
  compiler/map_candidate.py           不变  ← 关键：compile 步骤只调 candidate_compiler 组件，不读场景体
  compiler/map_lock.py                不变
  compiler/ownership.py               不变
  compiler/page_bindings.py           不变
  compiler/portrayal_resolver.py      不变
  compiler/protocol.py                不变
  compiler/raster_legends.py          不变
  compiler/raster_page_contract.py    不变
  compiler/raster_portrayal.py        不变
  compiler/raster_scene.py            不变
  compiler/thematic_design.py         不变
  compiler/vector_page.py             不变
  compiler/vector_portrayal.py        不变
  compiler/vector_scene.py            不变

  contracts/__init__.py               不变
  contracts/bundle.py                 不变
  contracts/execution.py              不变
  contracts/protocols.py              不变

  repository/__init__.py              不变
  repository/catalog.py               不变
  repository/delivery_repository.py   不变
  repository/immutable_store.py       不变
  repository/knowledge.py             不变
  repository/map_expression_catalog.py 不变
  repository/staging_package.py       不变
  repository/template_installer.py    不变
  repository/template_repository.py   不变

  security/__init__.py                不变
  security/approval.py                不变
  security/nonce_store.py             不变
  security/paths.py                   不变
  security/sensitive.py               不变

  validation/__init__.py              不变
  validation/map_checks.py            不变
  validation/models.py                不变
  validation/registry.py              不变

  workflow/__init__.py                不变
  workflow/agent_runtime.py           不变
  workflow/approvals.py               不变
  workflow/attribute_join.py          不变
  workflow/budget_store.py            不变
  workflow/data_adoption.py           不变
  workflow/data_preparation.py        不变
  workflow/intent.py                  不变
  workflow/map_data_preparation.py    不变
  workflow/map_delivery.py            不变
  workflow/map_final_check.py         不变
  workflow/map_generation.py          不变  ← 关键：已通过插槽地基解耦，不读场景体
  workflow/map_planning.py            不变
  workflow/map_preview.py             不变（backend() 通过 create_render_backend(scene["renderer_id"], ...) 自动分派，ImagePageRenderer 由 backend.impl 命中 IMAGE_IMAGE_ITINERARY 分支，无需额外处理）
  workflow/map_render.py              不变
  workflow/material_evidence.py       不变
  workflow/material_extraction.py     不变
  workflow/preparation_bundle.py      不变
  workflow/preparation_services.py    不变
  workflow/raster_preparation.py      不变
  workflow/revision_graph.py          不变
  workflow/state_machine.py           不变
  workflow/static_assets.py           不变
  workflow/template_analysis.py       不变
  workflow/template_author.py         不变
  workflow/template_brief.py          不变
  workflow/template_validation.py     不变
  workflow/template_workflow.py       不变
  workflow/vector_preparation.py      不变

  adapters/__init__.py                不变
  adapters/contracts.py               不变
  adapters/controlled_renderer.py     不变
  adapters/formal_renderer.py         不变
  adapters/geospatial_mcp.py          不变
  adapters/hermes_probe_worker.py     不变
  adapters/host_probe.py              不变
  adapters/mcp.py                     不变
  adapters/mcp_stdio.py               不变
  adapters/page_renderer.py           不变（延后 Part II 解耦）
  adapters/raster_renderer.py         不变
  adapters/renderer_probe.py          不变
  adapters/render_backend.py          修改  L0-3a: create_render_backend 新增 IMPL_IMAGE_ITINERARY 分派分支，直接构造 ImagePageRenderer
  adapters/formal_renderer.py         不变（ImagePageRenderer 不经过 FormalRenderer；见 §1.2.1）
  adapters/static_page_renderer.py    不变（延后 Part II 解耦）
  adapters/svg_compositor.py          不变
  adapters/tool_gateway.py            不变
  adapters/webmap_renderer.py         不变

  adapters/image_page_renderer.py     新建  L3: Matplotlib + PIL 图片底图渲染器（~300 行）
  adapters/geo_to_image_pixels.py     新建  L3: EPSG:4326→原图像素（从旧框架迁移，~80 行）
  adapters/image_display.py           新建  L3: 透明/白边检测→display_window（从旧框架迁移，~60 行）
  adapters/image_layout.py            新建  L3: 像素→页面布局（从旧框架迁移+重构接口，~100 行）
  adapters/annotation_solver.py       新建  L5: 空间索引+模拟退火注记避让（从旧框架迁移，~300 行）

  scenarios/__init__.py               不变
  scenarios/README.md                 不变
  scenarios/general_thematic/         不变（领导图不碰此目录）
    __init__.py                       不变
    manifest.py                       不变
    dispatch.py                       不变
    raster.py                         不变
    vector.py                         不变
    request_contract.py               不变
    request_binding.py                不变
    revision.py                       不变
```

### A.2 场景包 —— 全部新建

```
skills/carto-agent/scripts/carto_core/scenarios/leadership_visit/

  __init__.py                         新建  L1: 轻 import 包声明（3 行）
                                         """leadership-visit scenario package.
                                         The registry loads manifest at import time.
                                         Keep this import-light."""
  
  manifest.py                         新建  L1: COMPONENTS + DEFAULTS 纯常量（~35 行）
                                         声明 10 个组件钩子的(模块, 属性)映射，DEFAULTS=()
  
  source_contract.py                  新建  L1: RouteSourceContract（~80 行）
                                         suggestions() / validate_role_bindings() /
                                         validate_source_profile() / brief_roles()
  
  request_contract.py                 新建  L1: RouteRequestContract（~100 行）
                                         geometry()→"vector" / required_fields() /
                                         required_capabilities() / validate_body() /
                                         source_plan() / override_keys() / apply_overrides()
  
  request_binding.py                  新建  L2: prepare/validate（~80 行）
                                         数据准备请求体绑定（itinerary→bundle）
  
  data_preparer.py                    新建  L2: RouteDataPreparer（~150 行）
                                         normalize_itinerary() + export_geojson()
                                         → PreparedDataBundle
                                         构造函数: (path_guard, project_root, output_root, registry)
  
  planner.py                          新建  L2: RoutePlanner（~100 行）
                                         build() → MapPlan v4
                                         构造函数: (registry, *, project_root)
  
  revision.py                         新建  L2: RouteRevisionContract（~40 行）
                                         rules() / bundle_input_keys() /
                                         apply_changes() / refresh_brief()
  
  candidate_compiler.py               新建  L3: RouteCandidateCompiler（~200 行）
                                         compile() + verify_request()
                                         构造函数: (path_guard, registry, *, project_root, context)
  
  style.py                            新建  L3: apply_grouped_style()（~250 行）
                                         输入: resolved-portrayal + page-request + itinerary_data
                                         输出: graphics 列表 [{type, coordinates, style, ...}, ...]
  
  frontend_document.py                新建  L4: FrontendDocumentBuilder（~250 行）
                                         build() → map_json {facts, design, resolved, provenance}
                                         与 ImagePageRenderer 消费同一 graphics 列表
  
  legend_checker.py                   新建  L5: route_legend_checker()（~60 行）
                                         visit_order 连续性 + route_mode 合法性 + 分组颜色一致性
  
  route_author.py                     新建  L5: RouteAuthor（~20 行，桩实现）
                                         author() / verify_existing() → CAPABILITY_NOT_AVAILABLE
  
  route_validation.py                 新建  L5: 验证桩（~20 行）
                                         route_validation_data_checker() /
                                         route_validation_scene() → CAPABILITY_NOT_AVAILABLE
```

### A.3 Schema —— 修改 7 个 + 新建 4 个

```
skills/carto-agent/schemas/

  general-generate-request.schema.json  修改  L0-1: geometry_types enum 追加
                                          "linestring", "multilinestring"
                                          位置: properties.source_bindings.items
                                                .properties.geometry_types.items.enum

  data-role.schema.json                 修改  L0-1a: geometry_types enum 同步扩展
                                          （独立枚举，与 generate-request 保持一致）

  prepared-data-bundle.schema.json      修改  L0-1b: vector 分支 geometry_types enum
                                          同步扩展（L146-149, L306-309 两处）

  map-expression.schema.json            修改  L0-1c: geometry_types enum 同步扩展

  template-analysis.schema.json         修改  L0-1d: geometry_types enum 同步扩展

  template-brief.schema.json            修改  L0-1e: geometry_types enum 同步扩展

  render-scene.schema.json              修改  L0-4: ① renderer_id enum 追加
                                          "image-itinerary-page"（L312-316）；
                                          ② 静态页 oneOf 变体新增 image_graphics
                                          字段（apply_grouped_style 的产出载体）

  page-request.schema.json              修改  L0-5: 确认支持 image-native 像素页面参数
                                          （如已支持则不变）
  
  leadership-visit-generate-request.schema.json  新建  L1-3
    allOf[$ref generate-request, {required: [itinerary_structure, basemap], ...},
          unevaluatedProperties: false]

  image-itinerary-style.schema.json     新建  L3
    分组配色/路线/标记/信息框/编号的表达参数 Schema

  frontend-map-document.schema.json     新建  L4
    从旧框架迁移，category 从 const:"leadership_visit" 改为 enum

  frontend-export-record.schema.json    新建  L5
    从旧框架迁移

  # 以下 79 个 Schema 全部不变
  approval-receipt / budget-state / bundle-inputs / candidate-set / capability-roadmap /
  cartography / category-counts / chart / common / data-facts / data-preparation-task /
  data-role / delivery / delivery-manifest / delivery-receipt / delivery-transaction /
  dependency-lock / design-review-record / design-revision-proposal / encoding-ir /
  environment-fingerprint / extraction-result / formal-render-evidence /
  general-template-create-request / generate-request / geospatial-* (4) /
  grid-parameters / host-preflight / identity / intent-profiles / intent-request /
  job-state / knowledge-evidence / layout / manifest / map-brief / map-expression /
  map-expression-catalog / map-intent / map-plan / map-preview-evidence /
  map-spec-lock / material-source / page-bindings / page-output / portrayal /
  prepared-data-bundle / product-review / prototype-description / publication-receipt /
  quality-gates / raster-* (5) / render-attempt / render-receipt /
  resolved-appearance / resolved-layout / resolved-map / resolved-portrayal /
  revision-dependency-graph / scenario / scenario-capabilities / source-manifest /
  spatial-behavior / state-transition / step-receipt / template-* (4) /
  thematic-attribute-join / thematic-design / tool-binding / tool-result /
  validation-report / vector-encoding / vector-input / vector-prepared-data
```

### A.4 策略 —— 修改 2 个

```
skills/carto-agent/policies/

  scenario-capabilities.yaml            修改  L1-2: profiles 列表追加
                                         leadership-visit-mapping@1.0.0
                                         （implementation=leadership-visit,
                                          renderer_id=image-itinerary-page,
                                          geometry_variants: [{geometry: vector, ...}）

  tool-bindings.yaml                    修改  L5: 新增 3 个能力绑定
                                         geo-to-image-pixels@1.0.0
                                         image-display-bounds@1.0.0
                                         annotation-layout@1.0.0

  # 以下 8 个策略全部不变
  baselines/carto-core-1.0.0.yaml      不变
  capability-roadmap.yaml              不变（L6 后登记 image-itinerary 表达）
  checker-registry.yaml                修改  L5: 追加 itinerary.* 检查器（visit_order 连续性 / route_mode 合法性）
  data-preparation-policy.yaml         不变
  intent-profiles.yaml                 不变（leadership_visit 词条已存在）
  knowledge-sources.yaml               不变
  map-expression-catalog.yaml          不变（L6 后登记 image-itinerary）
  scope-baseline.yaml                  不变
  security-policy.yaml                 不变
```

### A.5 模板包 —— 全部新建

```
skills/carto-agent/templates/map-scenario/leadership-visit-map/1.0.0/

  manifest.yaml                         新建  L5: 包元数据 + 文件清单 + checksums
  checksums.sha256                      新建  L5: sha256sum 校验
  dependencies.lock.yaml                新建  L5: 依赖快照

  contracts/
    scenario.yaml                       新建  L5: 场景合同
                                          identity + cartography + layout + image_presentation
    data.schema.yaml                    新建  L5: route-stops + route-line 字段定义
    spatial-behavior.yaml               新建  L5: EPSG:4326，配准参数引用
    portrayal.yaml                      新建  L5: image_itinerary 分组样式
                                          groups(morning/afternoon/default) +
                                          route(offset/arrow/spacing) +
                                          pin(radius/numbering) +
                                          callout(width/font/opacity) +
                                          support_label
    delivery.yaml                       新建  L5: PDF+PNG A3 300dpi
    quality-gates.yaml                  新建  L5: 10 个通用检查器 + 2 个行程检查器

  fixtures/
    visit-route.synthetic.geojson       新建  L5: 3 个合成停靠点（含 visit_order + stop_name）

  prototypes/
    route-overview.yaml                 新建  L5: 原型定义（标题 + 图例占位符）
```

### A.6 测试 —— 新建 1 个

```
skills/carto-agent/scripts/tests/

  test_leadership_visit.py              新建  L5: 场景测试（~200 行，12 个用例）
                                         test_source_contract_suggestions
                                         test_source_contract_rejects_missing_stops
                                         test_request_contract_geometry
                                         test_request_contract_validate_body
                                         test_data_preparer_stops_only
                                         test_data_preparer_rejects_gap
                                         test_planner_build
                                         test_candidate_compiler_scene
                                         test_legend_checker_valid
                                         test_legend_checker_straight_line
                                         test_frontend_document_build
                                         test_scenario_registry_admission

  test_scenario_boundary.py             不变（但需确认零新增 violations）
  test_component_protocols.py           不变（但需确认新增组件通过 Protocol 校验）
  test_backend_registry.py              不变（但需确认 image-itinerary-page 在后端表中）

  # 所有其他 45 个测试文件不变
```

### A.7 汇总

| 类别 | 不变 | 修改 | 新建 | 说明 |
|---|---|---|---|---|
| 内核 Python | 97 | 3 | 5 | scenario_registry + backend_registry（含 IMPL_IMAGE_ITINERARY 常量）+ render_backend（三路分派）+ 5 个新 adapters |
| 场景包 Python | 0 | 0 | 14 | 完整 leadership_visit 包 |
| Schema JSON | 79 | 7 | 4 | 6 个 geometry_types 同步扩展 + render-scene（renderer_id + image_graphics）+ 4 个新 Schema |
| 策略 YAML | 8 | 3 | 0 | scenario-capabilities + tool-bindings + checker-registry |
| 模板 YAML | 0 | 0 | 10 | 完整模板包 |
| 测试 Python | 46 | 0 | 1 | test_leadership_visit.py |

**总计：230 个文件不变，13 个修改，34 个新建。**

内核改动仅限于已规定的扩展点（注册表白名单 + 后端注册表含 IMPL_IMAGE_ITINERARY 常量 + 渲染器三路分派 + 共享数据类型枚举 6 个 Schema 同步扩展 + render-scene image_graphics 字段），场景包完全隔离。`formal_renderer.py` 不改动——`ImagePageRenderer` 通过独立 `impl` 常量和 `create_render_backend` 第三分派路径绕过其 raster/vector 二元假设。