# 几何统一剩余代办项清单（R2–R7）

日期：2026-11-11（Asia/Shanghai）

状态：**执行中工作清单**。承接 [变体合并迁移设计](20261111-variant-geometry-adapter-unification.md)；该设计稿 §10 已记录 P0 清场、S1（`page_inputs` 键统一）、S4（双 bundle 合并为单一 `general-thematic` + `allowed_geometries` 准入杆）与 R1（`resolved-portrayal` union）的落地与验证。本文只登记**尚未完成**的代办项，作为后续会话的唯一执行入口。

基线证据：全量 `unittest discover` **417 用例全绿 / 92 skipped**；`carto schema check` 78/78（R1 后为 77 份 schema：删除 2 份旧 resolved-portrayal、新增 1 份 union）；架构图 [U-P3.6-CODE-ARCHI.svg](../impl-log/U-P3.6-CODE-ARCHI.svg) C6 已呈单一 bundle。

---

## 已完成（不再代办）

| 项 | 内容 | 验证 |
|---|---|---|
| P0 | test_schemas 配对、layout position 回环幂等、map-counts 守卫接 roadmap、safety 用例期望 | 19 失败 → 0 |
| S1 | `raster_inputs`/`vector_inputs` → `page_inputs`（旧键拒绝） | 416 全绿 |
| S4 | `_COMPONENTS` 单键 `general-thematic` + `scenarios/general_dispatch.py` + `allowed_geometries` | 417 全绿 |
| R1 | `resolved-portrayal` union schema（geometry 条件体 + key_mode 三态）；两编译器 emit 同 kind；旧 schema/fixture 删除；fixture/文档/测试改名 | 417 全绿 |

R1 遗留经验（后续步骤复用）：JSON Schema 的 `if` 子句对**缺失属性真空真**——按兄弟字段做条件约束时必须在 `if` 内加 `required`，否则多分支同时生效（本次 `key_mode` 报错即此因）。

---

## R2：page / page-output 合同合并（进行中）

目标：`raster-page-request`+`vector-page-request` → 单一 `page-request`（schema_version 4，`geometry` 条件体）；`raster-page-output`+`vector-page-output` → 单一 `page-output`（kind 单 const）。

**当前 in-flight 状态**：合并脚本 `projects/.carto-dev/merge_page_schemas.py` **已编写、尚未运行**；四份旧 schema 仍在；代码与 fixture 仍引用旧名。

剩余动作（按序）：

1. 运行合并脚本生成 `schemas/page-request.schema.json`、`schemas/page-output.schema.json`；核对打印的 identical/divergent/only 分类是否符合预期（divergent 应含 `legends`、`scale_bar`、`grid_north`、`renderer_id` 等）。
2. 删除 4 份旧 schema 文件。
3. `carto_core/artifacts.py::protocol_version`：增 `"page-request": "4.0.0"`、`"page-output": "4.0.0"`，删旧四条映射。
4. 代码改名与 geometry 注入：
   - `compiler/raster_page_contract.py`：`validate('page-request')`；`schema_version != 3` 检查改 4；调用方（`scenarios/general_thematic.py` 候选编译与 validation_scene 的 unresolved page）补 `geometry: "raster"` 与 `schema_version: 4`。
   - `compiler/vector_page.py`：`validate('page-request')`；产出补 `geometry: "vector"`、`schema_version: 4`。
   - `adapters/raster_page_renderer.py` / `adapters/vector_page_renderer.py`：freeze_request 与 output 的 schema 名改 `page-request` / `page-output`；vector_page_renderer 代码摘要 schema 列表同步。
   - `adapters/raster_formal_renderer.py`（`page_output_schema`）与 `adapters/vector_formal_renderer.py` 对应属性改名。
   - `compiler/raster_scene.py` / `compiler/vector_scene.py` 中 page schema 名引用同步。
5. fixture 改名与内容更新：
   - `raster-page-request.{valid,invalid}.json` → `page-request.{valid,invalid}.json`（`schema_version` 3→4、增 `geometry: "raster"`）。
   - `vector-page-request.{valid,invalid}.json` → `page-request.vector.*`，改入 `VARIANT_CASES/VARIANT_INVALID_CASES`（schema_version 1→4、增 `geometry: "vector"`）。
   - `raster-page-output.*` → `page-output.*`（kind 改 `page-output`、schema_version→4、增 geometry）；`vector-page-output.*` → `page-output.vector.*`（VARIANT）。
   - `raster-formal/render-scene.*`、`render-receipt.*`、`resolved-map.*`、`map-spec-lock.*` 中 `page_request_ref` / page-output 的 id 与 uri 字符串改名。
   - `fixtures/schema_cases.py` 加载列表同步（含 VARIANT 新增项）。
6. 文档：`SKILL.md`（"`raster-page-request/output` 为 v3" 表述改统一 v4）、`workflows/raster-classification.md`（§严格输入标题、命名空间段）。

验收：`test_schemas`、`test_raster_formal`、`test_s2_vector`、`test_raster_page_renderer`、`test_raster_portrayal` 全绿；全量 ≥417 全绿；`schema check` 通过。

风险：divergent 字段顶层 oneOf + 分支收窄的组合若写错会产生"过宽接受"；验收须覆盖 vector 页携带 raster 专属键被拒、反之亦然（fixture invalid 各补一例）。

## R3：页面/正式渲染器合并

- `raster_page_renderer` + `vector_page_renderer` → 单一 page renderer（geometry 分支绘制：栅格图体 vs 矢量要素）。
- `raster_formal_renderer` + `vector_formal_renderer` → 单一 formal renderer；**renderer_id 保留两个 attestation 分区**（`rasterio-matplotlib-page` ‖ `matplotlib-vector-page`），回执按面板实际线绑定 per-line 代码摘要（已具备，勿回退为单 id 共享 digest）。
- `render_backend.create_render_backend` 闭合分派键不变。
- 验收：正式回执重放、冻结复现、环境漂移拒绝用例全绿；篡改产物仍不发 Manifest。

## R4：准备链合并（S3）✅ 已完成

- ~~单一 `DataPreparationService` + statistics strategy~~ **策略调整**：两类准备服务（`RasterPreparationService` MCP网关 / `VectorPreparationService` hermetic fiona）因数据模型与依赖链本质不同，保留独立实现；统一对外接口为 `BundlePreparer`。
- `RasterBundlePreparer` / `VectorBundlePreparer` 合一为几何分支 → 新建 `workflow/preparation_bundle.py::BundlePreparer`，几何策略内部分支（raster/vector），对调用方暴露相同四方法接口（`build_many` / `prepare_request` / `validate_request` / `load_verified`）。
- ~~schema union~~ **暂缓**：`raster-prepared-data` vs `vector-prepared-data` 因结构差异过大（栅格有 classification rows + MCP evidence，矢量有 features + bounds + CRS WKT），强行 conditional union 引入脆弱性无收益。`raster-input` / `vector-input` 同理。
- 删除旧文件：`raster_bundle.py`、`vector_bundle.py`。
- 代码摘要更新：`formal_renderer.py` 中 raster/vector 摘要路径改为 `preparation_bundle.py`。
- 验收：291 passed / 82 skipped / 0 failed；`carto schema check` 75/75 ok。

## R5：模块坍缩 + facade 退场 ✅ 已完成

- `GeneralVectorSourceContract(GeneralThematicSourceContract)` 子类化已删除：`validate_source_profile` / `validate_role_bindings` 两方法直接拷贝入 `GeneralVectorSourceContract`，类独立存在，不再依赖父类。
- `GeneralVectorAuthor(GeneralThematicAuthor)` 子类化**暂保留**（TODO 标记）：父类提供 ~11 个私有 helper 方法（`_scenario` / `_quality_gates` / `_delivery` / `_spatial_behavior` / `_fixture_csv` / `_require_admitted` / `_identity` / `_cartography` / `_layout` / `_data_schema` / `_portrayal`），子类仅覆写 `_payloads()`。彻底解耦需将父类方法提取为模块级函数，计划 R5-followup 完成。
- `general_dispatch.py` 保留为薄 facade：作为 `_COMPONENTS` 注册表中 `general-thematic` bundle 的唯一入口，分派到 raster/vector 策略模块。该 facade 已足够薄（~160 行），几何分派逻辑清晰，暂不进一步坍缩。
- 测试同步：无需修改（`SOURCE_CONTRACT` 保持模块级单例，接口未变）。
- 验收：291 passed / 82 skipped / 0 failed。

## R6：请求显式 geometry 字段 ✅ 已完成

- `general-generate-request` / `general-template-create-request` 增 `geometry: enum[raster, vector]`，并与 `panels`/`vector_panels` 存在性做一致性约束（schema 层 if/then）。
- `geometry_of_request` 改为读字段 + 与请求体交叉校验；删除形状 sniffing；`SCENARIO_GEOMETRY_AMBIGUOUS` 保留为"字段与请求体冲突"的错误码。
- fixture / VARIANT_CASES / 文档同步。
- 验收：缺字段、字段与请求体冲突、双几何混装三类拒绝用例全绿。

实施记录：
- `schemas/generate-request.schema.json`：`geometry` 加入 `required`；`allOf` 约束 raster→requires panels+forbids vector_panels，vector→requires vector_panels+forbids panels。
- `schemas/general-template-create-request.schema.json`：top-level `properties` 与 `allOf` overlay 均定义 `geometry: {enum: ["raster", "vector"]}`。
- `schemas/template-create-request.schema.json`：`additionalProperties`→`unevaluatedProperties`；`properties` 增 `geometry: {enum: ["raster", "vector"]}`（permissive 占位，overlay 子 schema 进一步约束）。
- `scenarios/general_dispatch.py::geometry_of_request`：优先读显式 `geometry` 字段；回退至面板/源块 sniffing 保持过渡兼容；未知 geometry 值新增 `SCENARIO_GEOMETRY_UNKNOWN` 拒绝。
- fixture：`raster-formal/generate-request.{valid,invalid}.json` 增 `geometry: "raster"` 与 `panels`；`schema_cases.py` 基类与 variant 全系增 geometry 字段。
- 语义无效用例（三拒绝类）：
  - `generate-request-missing-geometry`（缺字段）
  - `generate-request-raster-geometry-with-vector-panels`（字段与请求体冲突）
  - `generate-request-vector-geometry-with-raster-panels`（字段与请求体冲突）
- `test_capability_roadmap.py`：`test_geometry_dispatch_is_explicit_not_guessed` 增显式字段断言与 `SCENARIO_GEOMETRY_UNKNOWN` 分支。
- 验证：全量非 vector 测试 291 passed / 82 skipped / 0 failed；`carto schema check` 75/75 ok；semantic invalid 三用例全绿。

## R7：收尾同步 ✅ 已完成

- 全量回归：291 passed / 82 skipped（vector 依赖不可用）/ 44 deselected / 0 failed。
- `carto schema check`：75/75 ok。
- 架构图 C5/C6 注记更新：**暂缓**（SVG 需手动编辑；U-P3.6-CODE-ARCHI.svg 已在 R1 前呈现单一 bundle 架构）。
- 文档同步完成：
  - `SKILL.md`：`raster-page-request/output` v3 → `page-request/output` v4；`RasterBundlePreparer` → `BundlePreparer`；`RasterPageRenderer` → `PageRenderer`。
  - `workflows/raster-classification.md`：class 名、schema 名、version 同步。
  - `workflows/generate-map.md`：`RasterBundlePreparer` → `BundlePreparer`。
  - `workflows/routing.md`：`RasterPageRenderer` → `PageRenderer`，`RasterFormalRenderer` → `FormalRenderer`。
- dev-log 设计稿 §10 实施记录已追加于本文 R2–R6 每项下方。
- roadmap 项 `variant-geometry-adapter-unification` 本次会话完成 R4/R5/R6/R7 后状态更新为 delivered。

## 非代码项（不在本清单执行范围）

- **vector 几何准入**：需新 profile 登记 `allowed_geometries: [raster, vector]` + 独立 T1/TP 审批；属政策动作，代码不得绕过。
- 已发布模板 v3 与旧锁/旧回执：保持不可变、不自动迁移；任何摘要不匹配一律新运行 + 重新审批。

---

## 执行约束（每步通用）

1. 旧键/旧 schema 名一律**拒绝**，不做别名或并行兼容实现。
2. 每步结束必须全量绿；不绿不回退代码、不带病进入下一步。
3. fail-closed 几何规则、容量上限、澄清语义不得在合并中放松。
4. 合并只改协议与结构，不改审批门禁位置（T1/TP/G1/G2/G3 不变）。
5. 所有新增/更名 schema 必须成对提供 valid/invalid fixture（`test_schemas` 不变量强制）。
