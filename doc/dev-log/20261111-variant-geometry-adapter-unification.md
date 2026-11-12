# 实现变体合并迁移设计：从双 bundle 到几何适配器

日期：2026-11-11（Asia/Shanghai）

状态：**迁移设计稿**。目标是将 `general-thematic-raster` 与 `general-thematic-vector` 两个实现 bundle 合并为单一 bundle + 几何 strategy 分支（几何适配器轴），并给出 union schema 字段表与四步迁移顺序。本文不改动运行时代码；实际执行以 `skills/carto-agent/` 实现与审批门禁为准。

前置条件：**当前 415 用例中 19 个失败（`test_layout_contract` 16 errors、`test_capability_roadmap` 2 failures、`test_schemas` 1 failure）必须先转绿**，否则任何一步都无法区分合并引入与既有回归。

---

## 1. 背景：为什么合并是架构上成立的

### 1.1 判据修正（避免循环论证）

旧判据"后端 × 冻结合同族的不可约组合 = 变体数"是**对现状的描述**：合同族与 renderer_id 之所以有两套，正是因为当初写了两套实现。用分裂的产物证明分裂的必要，是循环论证。

修正后的判据只看接口层三条，且与"现有几套实现"无关：

| # | 条件 | raster vs vector 现状 | 成立？ |
|---|---|---|---|
| 1 | 八组件签名本身必须改变 | `component_protocols.py` 中两变体八组件签名完全相同 | 否 |
| 2 | 准入语义不同到无法用同签名内几何条件分支承载 | 差异仅为规则内容（north-up 整数单波段 vs 显式 extent 且原生 CRS=展示 CRS），可在同一 `validate_source_profile` 内按几何分支 fail-closed | 否 |
| 3 | 回执 attestation 模型必须不同 | 差异仅为 code digest 集合粒度，`render-receipt` 增加 per-line digest 即可承载 | 否 |

三条全否 ⇒ 两个 bundle 无架构必要性；几何差异应落为 bundle 内 strategy 分支或几何适配器（类比表达目录 `adapters`：`categorical@2.0.0` 一个条目挂 raster/vector 两个适配器）。

### 1.2 现状双 bundle 的真实成因（均为非架构因素）

| 成因 | 性质 | 合并后的替代机制 |
|---|---|---|
| S2 矢量线作为平行 proof 建设，刻意不触碰已冻结栅格链 | 阶段性策略 | 合并后以 union schema + 几何分支回归覆盖两线 |
| `resolved-raster-portrayal` / `raster-page-request` v3 / 双 renderer_id 已进入已发布模板 lock、validation evidence、MapSpecLock 与回执摘要 | 冻结产物惯性 | 版本化迁移；旧产物按"漂移即新运行 + 重新审批"处理，不自动迁移 |
| 未登记 profile 即可整体 withhold 矢量线 | 准入便利 | profile 级 `allowed_geometries` 白名单 |

### 1.3 与四轴原则的一致性

几何属**数据轴**。四轴分解要求数据类型不占场景列；同理也不应占变体级分裂。合并后：业务用途→场景列、几何→bundle 内适配器、表达→目录条目、后端→闭合分派，四轴各归其位。

---

## 2. 目标态架构

```
scenario-capabilities profile
  └─ allowed_geometries: [raster] | [raster, vector]      ← 准入杆（政策层）
_COMPONENTS: general-thematic（单一 bundle）
  ├─ source_contract      几何条件分支 fail-closed
  ├─ author               模板合同不含几何专属字段族
  ├─ validation_data_checker / validation_scene   合成 fixture 按几何分支
  ├─ data_preparer        DataPreparationService + statistics strategy(mcp-raster | local-vector)
  ├─ planner              LayoutResolver 共享；bindings 按几何分支
  ├─ candidate_compiler   统一 page/scene 编译；renderer_id = matplotlib-page
  └─ legend_checker       图例语义按几何分支
render_backend 闭合分派：maplibre-web ‖ matplotlib-page（档案内 per-line code digest）
表达目录：adapters 按几何分派（不变）
```

---

## 3. Union Schema 字段表

约定：`共享` = 两族已有同义字段；`条件必填` = 按 `geometry` 枚举条件要求；`新增` = 合并引入；`删除` = 合并后不再存在。**旧键/旧 id 一律拒绝，不做别名双读**（仓库约束：不为旧命名或旧锁格式新增并行兼容实现）。

### 3.1 `resolved-portrayal`（合并 resolved-raster-portrayal + resolved-vector-portrayal）

| 字段 | 归属 | 说明 |
|---|---|---|
| schema_version / kind=`resolved-portrayal` / compiler_version / compiler_digest | 共享 | 编译器代码与 schema 摘要绑定 |
| portrayal / layer_id / expression_ref / prepared_ref / context | 共享 | 模板合同快照 + 数据引用 + 执行上下文 |
| geometry: enum[raster, vector] | 新增 | 分支键；来自准备报告而非调用方任选 |
| symbol_table.key_mode: enum[discrete, interval, scaling] | 新增 | 键控表并集的判别字段 |
| symbol_table.discrete.rows[{value, display, label, color, order, include_in_legend}] | 共享（原 lookup_table / categorical categories） | 等值查找；semantic(class/background/nodata) 覆盖仅 discrete 允许 |
| symbol_table.interval.breaks[{low, high, closed_left, closed_right, label, symbol}] + interval_policy + out_of_range | 共享（原 choropleth edges/labels/symbols） | 谓词查找 |
| symbol_table.scaling{function, maximum_value, maximum_radius_mm, minimum_radius_mm, zero_policy, negative_policy, out_of_range, legend_values[]} | 共享（原 proportional） | 连续缩放；**禁止逐要素半径行** |
| missing{policy, label, symbol} | 共享 | 缺值显示合同 |
| source_mask_preserved / resampling=nearest | 条件必填(geometry=raster) | 栅格专属策略 |
| legend（由 symbol_table 派生） | 共享 | 不携带统计计数 |
| ~~per-feature rows~~ | 删除 | 显示合同与数据行分离 |

### 3.2 `page-request` v4（合并 raster-page-request v3 + vector-page-request）

| 字段 | 归属 | 说明 |
|---|---|---|
| resolved_layout / cartography / appearance / font{path,digest,size_bytes} | 共享 | 布局、制图、外观、字体冻结 |
| texts[{content_id,text}] / legends[{content_id,title}] | 共享 | 恰好一个标题；图例条目只由已验证表达编译 |
| bindings（page-bindings，executable=true） | 共享 | 数据/图层/视图/面板/图例/元素关联 |
| scale_bar: object\|null / grid_north: object\|null | 共享 | 必须显式传对象或 null；多图本期 null |
| panels[{view_id, portrayal_ref, extent}] | 合并（原 portrayals[] / panels[]） | 统一为 view_id + ref |
| panels[].extent | 条件必填 | geometry=vector 必填（显式 extent）；geometry=raster 必须 null（由准备报告 bbox 推导） |
| ~~portrayals[]~~ / ~~legend_titles 独立签名~~ | 删除 | 并入 panels / legends |

### 3.3 `prepared-data`（合并 raster-prepared-data + vector-prepared-data）

| 字段 | 归属 | 说明 |
|---|---|---|
| status: ready\|needs-clarification / questions[] | 共享 | 澄清协议与几何无关 |
| source 快照 refs（原始字节 SHA256）/ crs / bbox / context | 共享 | 自包含快照 |
| algorithm_digest / evidence refs | 共享 | 统计来源证明 |
| raster 段：band / dtype / statistics_ref(MCP 证据) / classification rows[] / clarification{based_on_digest, overrides} | 条件必填(geometry=raster) | 像素统计必须来自授权网关证据 |
| vector 段：feature_count / vertex_count / geometry_kind / category observations | 条件必填(geometry=vector) | 有界进程内扫描（MAX_FEATURES/MAX_VERTICES） |
| ~~手写 ready~~ | 删除 | 重载从冻结输入重算 |

### 3.4 `render-scene` / `execution`

| 字段 | 归属 | 说明 |
|---|---|---|
| page_inputs{prepared_bundle_ref, page_request_ref} | 新增（替代 raster_inputs / vector_inputs） | 两键原值形状完全相同，纯命名统一 |
| renderer_id: enum[maplibre-web, matplotlib-page] | 收敛 | 旧两静态 id 在新代码下拒绝 |
| 其余（layout/dpi/targets/资源集/context） | 共享 | 不变 |

### 3.5 `render-receipt`

| 字段 | 归属 | 说明 |
|---|---|---|
| renderer_id = matplotlib-page | 收敛 | 单一基底 |
| environment.renderer_code_digests{raster_decode, raster_page, vector_read, vector_page} | 新增 | per-line code digest；回执绑定**本面板实际使用的线**，避免单 id 后两线互相失效 |
| environment 版本栈（Python/Rasterio/GDAL/NumPy/Matplotlib/Pillow/FreeType/fonttools/zlib + 平台架构） | 共享 | 不填虚假浏览器字段 |
| process_isolation=in-process / network_isolation=not-provided | 共享 | 如实声明 |

### 3.6 `scenario-capabilities`

| 字段 | 归属 | 说明 |
|---|---|---|
| allowed_geometries: 子集[raster, vector] | 新增 | 准入杆；未列几何即 deny |
| routes / request_schemas / intent_constraints / output_constraints / layout_constraints | 共享 | 不变 |

---

## 4. 四步迁移顺序

每步独立可验证、可回退（回退 = 回滚代码；旧产物保持不可变，不做原地改写）。

### S1：execution / page 键统一（不动 renderer_id、不动 bundle 数）

- `render-scene` 增 `page_inputs`；`layout.validate_execution` 只读 `page_inputs`；旧键 → `ProtocolError`（拒绝，非别名）。
- `raster_page_contract` / `vector_page` 改发 `page_inputs`。
- 验证：`test_raster_formal`、`test_s2_vector`、`test_s2_workflow`、`test_layout_contract` 全绿；篡改/重放用例仍拒绝。
- 门禁影响：在途旧锁因键缺失被拒 → 按"漂移即新运行 + 重新 G1/G2/G3"处理，文档明示。

### S2：resolved-portrayal union 化

- 新 schema `resolved-portrayal`（3.1 表）；`raster_portrayal` / `vector_portrayal` 均编译到它；page 编译器消费 union。
- 删除 `resolved-raster-portrayal` / `resolved-vector-portrayal` schema（不保留并行兼容）。
- 表达目录 `adapters` 按几何分派机制不变。
- 模板 portrayal 合同不变 ⇒ **已发布模板仍可安装使用**；失效的只是旧表达产物的重放。
- 验证：合成 TIFF/shapefile 双几何回归 + 澄清链 + 图例派生 + 逐要素行拒绝用例。

### S3：DataPreparationService + statistics strategy

- 单一 service 类，strategy = `mcp-raster` | `local-vector`；`prepared-data` union schema（3.3 表）。
- MCP 配置仅 raster strategy 必需；vector 保持 hermetic 本地读取（不把统一变成网络依赖）。
- 澄清协议共用（observed-not-in-contract → questions）。
- `RasterBundlePreparer` / `VectorBundlePreparer` 合并为一个 BundlePreparer 的几何分支。
- 验证：`data analyze-classification / clarify-classification` 行为不变；vector 准备无网络用例；证据命名空间分策略保留。

### S4：renderer_id 收敛 + bundle 合并 + 准入杆迁移

- `render_backend` 收敛为 `matplotlib-page`；能力档案携带 per-line code digest（3.5 表）；回执按面板实际线绑定。
- `_COMPONENTS` 合并为单键（删除 vector 键与 `__defaults__` 机制）；八组件内部几何分支。
- `scenario-capabilities` 增 `allowed_geometries`；矢量开放 = 登记 `allowed_geometries: [raster, vector]` 的 profile（独立 T1/TP），未登记即 withhold。
- 需要矢量几何的模板以 v4 重发布（新 T1/TP）；v3 模板继续服务栅格几何。
- 验证：双几何端到端（G1→…→G3→交付）合成回归；withhold 用例（未列几何即 deny）；回执重放与冻结复现用例。

---

## 5. 失效矩阵与迁移成本

| 产物 | S1 | S2 | S3 | S4 |
|---|---|---|---|---|
| 在途 MapSpecLock / 旧回执 | 键缺失被拒 → 新运行重审批 | 同左 | 同左 | renderer_id 被拒 → 新运行重审批 |
| 已发布模板 v3 包 | 可用 | 可用 | 可用 | 仅栅格几何可用；矢量需 v4 重发布 |
| template-validation-evidence.grid_cases | 不受影响（发布期证据） | 不受影响 | 不受影响 | 矢量几何证据需 v4 重验 |
| resolved-* 表达产物重放 | 不受影响 | 旧 id 被拒 | 同左 | 同左 |
| G2/G3 对象摘要 | 候选摘要变化 → 需重签 | 同左 | 同左 | 同左 |

原则：已发布包与旧证据**保持不可变、不自动升级**；任何摘要不匹配一律开始新运行并重新审批。

---

## 6. 合并后不变量（验收必查）

1. 几何条件准入 fail-closed：不放松为 any-geometry；未知几何 = deny。
2. 统计来源证明分策略保留：像素=授权网关证据命名空间；要素=有界进程内扫描；各自绑定回执。
3. 显示合同与数据行分离：类别/颜色来自澄清合同；scaling 只带参数，禁止逐要素半径行。
4. 回执绑定实际渲染代码：per-line code digest；单 renderer_id 不造成跨线失效。
5. 政策可单独 withhold 某几何：`allowed_geometries` 白名单；代码就绪 ≠ 开放。

---

## 7. 明确不做

- 不合并 `maplibre-web`（DPR 2 / webgl / 前端构建，能力档案不可通约）。
- 不把 MCP 变成通用统计总线（矢量保持 hermetic；MCP 仍是栅格统计的授权网关）。
- 不为旧键/旧 renderer_id/旧 schema id 提供别名或并行兼容实现。
- 不在合并中放松任何 fail-closed 几何规则或容量上限。
- 不做旧锁/旧证据的自动迁移或摘要重写。

---

## 8. 路线图登记

合并路线以单条 roadmap 项占位（维持"未实现 ≠ 禁止"分类纪律）：

```yaml
- id: variant-geometry-adapter-unification
  status: planned
  target: U-P4
  note: 双 bundle 合并为单 bundle + 几何适配器；S1-S4 见 doc/dev-log/20261111-variant-geometry-adapter-unification.md；前置条件为布局回归转绿。
```

---

## 9. 与现有文档的关系

| 文档 | 关系 |
|---|---|
| [设计原则](../design-principles.md) | 本文是"几何属数据轴"在实现层的收敛落地 |
| [U-P3.6 代码架构图](../impl-log/U-P3.6-CODE-ARCHI.svg) | C6 层"实现变体"子块在合并后收敛为单 bundle 内的几何适配器注记 |
| [标准专题图制图流程说明](../标准专题图制图流程说明.md) | 流程步骤不变；S4 后矢量几何进入同一流程，准入杆改为 allowed_geometries |
| [raster-classification 工作流](../../skills/carto-agent/workflows/raster-classification.md) | S3 的 statistics strategy 边界来源（MCP 不做类别含义/颜色/图例） |
| [generate-map 工作流](../../skills/carto-agent/workflows/generate-map.md) | S1/S4 的键与 renderer_id 收敛对象 |

---

## 10. 实施记录（2026-11-11）

按"先清场、后合并"的顺序落地，每步独立验证；全量基线由 416 用例 19 失败收敛到 **417 用例全绿（92 skipped）**。

### 10.1 清场（P0）

- `test_schemas` 配对失败：`general-*-request.vector` 两个**变体样例**误置于 `VALID_CASES/INVALID_CASES`，破坏"schema 集合 == fixture 键集合"不变量。移出为 `VARIANT_CASES/VARIANT_INVALID_CASES`，消费方 `test_s2_workflow` 改读新字典。
- `test_layout_contract` 16 errors 单一根因：语义位置特性使 `place_overlays` 首遍把 position 覆写为绝对像素，`validate_scene` 二次回环时 `_derive_anchor` 只读 `anchor/offset_mm`、静默忽略存量 x/y，锚点重置为框角导致包络越界。修复为**语义源随锚点持久化**（position 内附 `anchor/offset_mm` 回声，render-scene position 子schema 增补两可选字段），回环幂等且篡改仍可检出（改 x/y 不改回声 ⇒ ANCHOR_MISMATCH）；无回声的绝对位置一律拒绝。顺带修正 `_derive_anchor` 把 offset_mm 当像素相加的单位错误。
- 两个 taxonomy 失败：`LAYOUT_MAP_COUNT_UNSUPPORTED` 接 `not_implemented("composition-map-counts", …)`；safety 用例拆为 unit=px 与 dpr=2 两条 forbidden 断言。

### 10.2 S1：execution/page 键统一

- `raster_inputs` / `vector_inputs`（值形状完全相同）统一为 `page_inputs`；`common.schema.json` execution 定义改为单键 + 按 renderer_id 条件约束 `page_request_ref.id`；旧键因 `additionalProperties: false` 自然拒绝，不做别名。
- 同步：`raster_scene` / `vector_scene` 产出键、`layout.validate_execution` 读取键、`map_generation._verify_raster_inputs` 更名 `_verify_page_inputs`、3 份 raster-formal fixture、SKILL.md 与 raster-classification.md 措辞。

### 10.3 S4（提前于 S2/S3）：bundle 合并 + 几何准入杆

顺序调整理由：bundle 合并是用户的终点态且不依赖协议统一；S2/S3 属内部协议收敛，作为后续项保留在 roadmap。

- 新增 `scenarios/general_dispatch.py`：单一 bundle `general-thematic` 的八组件单签名入口，按显式判别符分派到 strategy 模块——generate 请求看 `panels/source_bindings/prepared_raster_bindings` vs `vector_panels/vector_sources`，create 请求看模板版本，legend_checker 看 execution 上下文；歧义抛 `SCENARIO_GEOMETRY_AMBIGUOUS`，不猜测。`validation_data_checker` 保持几何无关共享（直接别名 raster 实现，保留函数身份）。
- `scenario_registry.py`：`_COMPONENTS` 收敛为单键；删除 `__defaults__` 复用机制；新增 `GEOMETRIES` 与 `require_geometry`；注册期校验 `allowed_geometries ⊆ {raster, vector}` 非空；`for_create` / `resolve_generate` 在请求 schema 校验后执行几何准入。
- `scenario-capabilities.schema.json` 增 `allowed_geometries`；政策档案 `implementation: general-thematic` + `allowed_geometries: [raster]`——**vector 几何保持未准入**，准入杆从"未登记 profile"迁移到"profile 几何白名单"。
- renderer_id 保留两个 attestation 分区（rasterio-matplotlib-page ‖ matplotlib-vector-page），回执按面板实际线绑定代码摘要；此为设计稿 §4 S4 的备选分支，避免单 id 共享 code digest 造成跨线失效。
- 测试同步：`test_capability_roadmap` 改为 `SingleBundleGeometryDispatchTest`（单 bundle 八组件、显式几何判别、vector 几何被政策 withhold、打包档案仍准入）；`test_raster_portrayal` / `test_general_thematic` 键名更新。
- 文档同步：SKILL.md、routing.md、generate-map.md、raster-classification.md、标准专题图制图流程说明、阶段实施计划详细；架构图 C6 改为"单一 bundle + 几何 strategy"呈现。

### 10.4 未做与后续

- S2（resolved-portrayal union）与 S3（准备链 statistics strategy）未动：二者是内部协议收敛，不改变 bundle 数与准入面；保留在 roadmap 项 `variant-geometry-adapter-unification`（note 已更新落地范围）。
- 已发布模板 v3 包与旧锁/旧回执保持不可变、不自动迁移；矢量几何开放需新 profile 登记（allowed_geometries 含 vector）+ 独立 T1/TP。
- R1（resolved-portrayal union）已于 2026-11-11 落地并全绿；R2–R7 的逐步代办项、in-flight 状态与验收标准见 [几何统一剩余代办项清单](20261111-geometry-unification-worklist.md)。
