# 土地覆盖栅格专题图场景实现计划（land-cover-raster-v1）

状态：草案（待用户确认决策点 D1～D6 后排期）
分支基线：U-P3.5
目标里程碑命名建议：U-P4.0「真实栅格土地覆盖专题图工程闭环」

## 1. 背景与目标

用户请求：基于 `projects/dataset/landCover_reclassified.tif`（重分类栅格，类值 1～10，ordinal 适宜性语义）与 `projects/dataset/reclass_legend.csv`（类值 → NLCD 源类别 → 推断语义标签映射），通过 carto-agent 主链生成土地覆盖专题图。

当前能力检查结论：**不支持**。`policies/scenario-capabilities.yaml` 为 `default: deny`，仅注册 `synthetic-flood-demo`；SKILL.md 明确"尚未实现：真实 CRS 转换、生产数据制图"，且 IDE 接入条款要求对 TIFF/CRS 能力报告未开放、不得绕过主链。

本计划的目标：按 SKILL.md 的合法扩展路径（"添加其他场景需实现策略、注册协议和能力、补合法/非法样例及回归验收"）新增一个土地覆盖栅格场景，走通 `create-template`（模板发布）与 `generate-map`（intake → brief → compile → preview → freeze → render → check → G3 → deliver）两条既有路由，**不新建第三条路由、不绕过审批链**。

产出物（成功后）：
- 新场景实现 `scripts/carto_core/scenarios/land_cover_raster/`（7 个组件）；
- 新模板包 `land-cover-classified/1.0.0`（经真实 TP 发布进权威仓库）；
- 协议 Schema / 策略的最小必要扩展（含洪涝场景的收紧回归保护）；
- 合法/非法样例 + 单元/集成测试 + 回归验收；
- 一张 A3 横向 144 DPI 的土地覆盖专题图 PDF/PNG，经 G1/G2/G3 真实审批后原子交付。

## 2. 现状差距盘点（代码级证据）

以下每一处都是硬阻塞，缺一项请求即被拒：

| # | 阻塞点 | 位置 | 现状 |
|---|---|---|---|
| G1 | 场景能力白名单 | `scenario_registry.py::_COMPONENTS` | 仅 `synthetic-flood-v1`；未注册实现抛 `CAPABILITY_NOT_AVAILABLE` |
| G2 | 能力策略 | `policies/scenario-capabilities.yaml` | 仅 flood profile，`default: deny` |
| G3 | 数据性质常量 | `schemas/scenario-capabilities.schema.json` | `data_nature: const "synthetic"`、`production_enabled: const false`——真实用户数据无法注册 |
| G4 | 请求源格式常量 | `schemas/generate-request.schema.json` | `source_bindings[].format: const "geojson"`、`synthetic: const true`——TIFF/CSV 无法声明 |
| G5 | 数据包性质常量 | `schemas/prepared-data-bundle.schema.json` | `summary.data_nature: const "synthetic"` |
| G6 | 表达目录 | `policies/map-expression-catalog.yaml` + `schemas/portrayal.schema.json` | 仅 `choropleth/sequential`（equal-interval/quantile/jenks/manual）与 `proportional-symbol/count`；无分类（categorical/unique-value）表达 |
| G7 | 意图任务目录 | `policies/intent-profiles.yaml` | `government_thematic` 的 task_ids 无土地覆盖类任务 |
| G8 | 栅格读取依赖 | 根 `pyproject.toml` / skill `requirements.txt` | 仅 jsonschema + PyYAML；无 rasterio/GDAL、无 shapely |
| G9 | 真实 CRS 转换 | 全链 | 未实现；显示 CRS 固定 EPSG:4326（scene `spatial_context`），源 TIFF 的 CRS 需探测（NLCD 派生数据常见 EPSG:5070 Albers） |
| G10 | 渲染器输入类型 | `webmap_renderer.py` / `controlled_renderer.py` | 渲染 scene 只消费 geojson source；栅格无法直接入 scene |
| G11 | 模板 | `templates/`、权威模板仓库 | 无 land-cover 模板包（含 contracts、prototypes、验证 fixture、dependencies.lock） |
| G12 | 允许根 | CLI `--allowed-root`（运行参数） | `projects/dataset` 需在运行时显式纳入允许根，属调用参数而非代码缺口 |

## 3. 关键设计决策

### D1（推荐）数据性质扩展方式
- `scenario-capabilities.schema.json` 与 `prepared-data-bundle.schema.json` 的 `data_nature` 由 `const "synthetic"` 放宽为 `enum ["synthetic", "user-provided"]`；`production_enabled` **保持 `const false`**，`formal_capability_boundary.production_tasks` 保持为空——本场景仍是本地工程闭环，不声明生产制图能力。
- `generate-request.schema.json` 的 `source_bindings[].synthetic` 由 `const true` 放宽为 `boolean`，`format` 由 `const "geojson"` 放宽为 `enum ["geojson", "geotiff", "csv"]`。
- **同步收紧洪涝 overlay**：`synthetic-flood-generate-request.schema.json` 增加 `synthetic: {"const": true}`、`format: {"const": "geojson"}`，保证通用层放宽后 flood 场景零回归。
- 新增 overlay：`land-cover-generate-request.schema.json`（`format` 限 `geotiff`/`csv`、`synthetic: const false`、角色枚举、模板 id/version 常量）与 `land-cover-template-request.schema.json`。
- 备选（不推荐）：把用户 TIFF 转成 GeoJSON 后仍按 `synthetic` 走 flood 式协议——伪造数据性质声明，违反"不得伪造绑定"。

### D2（推荐）栅格入图路线：数据准备阶段矢量化
- `data_preparer` 内完成：读 TIFF → （必要时）CRS 重投影至 EPSG:4326 → 尺度控制 → `rasterio.features.shapes` 按类值面化 → 合并同类多边形/简化 → 输出 prepared GeoJSON（`properties: {carto_role, class_value, class_label}`）。
- 此后 compile/preview/render/check/deliver **完全复用现有 maplibre-web 矢量链**（fill layer + `step` 表达式按 `class_value` 上色），渲染器、锁、正式渲染、检查器均无需新适配器。
- 备选：新增 raster 渲染适配器（image source / PNG overlay）——改动面大（scene schema、controlled_renderer、renderer probe、RenderReceipt 环境指纹），留作后续独立里程碑，不在本次范围。

### D3 新依赖（需用户同意安装）
- `rasterio`（自带 GDAL/GEOS/pyproj wheel，Windows 可用）：栅格读取、CRS、重投影、面化。
- `shapely`：面合并（unary_union/dissolve）与简化。
- 声明位置：根 `pyproject.toml` + skill `requirements.txt`；`dependencies.lock` 同步。CI/测试环境同样需要。

### D4 尺度控制（工程可行性）
- 30 m 级全国/区域栅格直接面化可能产生数十万～百万级多边形，超出 maplibre geojson source 与 A3 图面的合理负载。
- 策略：先探测栅格行列数与类值直方图（Phase 0），若估算多边形数超阈值（建议 ≤ 20 000 面），采用"块统计多数重采样（majority resample）到目标网格 + 面化 + Douglas-Peucker 简化（容差按图幅像素反推）"。
- 每一步作为确定性 transformation 写入 bundle `transformations`/`tool_receipts` 回执（含参数与摘要），保证可审计；重采样意味着成图是**概览级综合**，不是逐像元精度表达——需在 notice/README 中声明。

### D5 CRS
- Phase 0 探测 TIFF 实际 CRS。若非 EPSG:4326，由 `pyproj`（rasterio 依赖内）做确定性重投影（栅格重投影后再面化，或面化后矢量重投影——优先后者，避免重采样引入类值混合）；转换参数与源/目标 CRS 写入回执。
- 若 CRS 缺失/不可识别：拒绝并报 `SOURCE_CRS_UNSUPPORTED`，不猜测。

### D6 图例语义与免责链
- CSV 所有标签 `semantic_source = 推断（非官方）`：图例逐项保留推断语义标签，notice 固定为「土地覆盖分类语义为推断结果，非官方土地覆盖产品；概览级综合，非逐像元精度」类似措辞（最终文案 Phase 3 定稿），经 scenario profile `notice` → scene 声明 overlay → check 声明链 → DeliveryManifest `limitations`（`require_manifest` 已强制一致）。
- 类值 5（空缺 unused）：默认**不渲染、不入图例**，在 quality_evidence 中记录"若栅格中出现类值 5 即拒绝"（`SOURCE_DATA_EMPTY`/新增 `LEGEND_CLASS_UNMAPPED`）；备选取舍见 §7 决策问题。
- 类值 10 含 NoData/255 合并语义：渲染为「水体/无数据」灰阶符号，与 flood 场景「无数据」检查语义对齐（`legend_checker` 强制存在）。

### D7 场景与意图归属
- `business_scene: government_thematic`（scene_hint 枚举已存在）；`theme: land-cover`；新 task id `land-cover-map`，加入 `intent-profiles.yaml` 的 `government_thematic.task_ids`。
- 新表达目录条目 `choropleth/categorical@1.0.0`（field_requirements: `class-value` integer；legend: `classed-color`、`label_source: legend-table`），`portrayal.schema.json` classification `method` 枚举增加 `categorical`，并补 allOf 条件分支（categorical 表达 → polygon + classification，无 scaling）。

### D8 输出 profile
- 沿用 A3 横向 420×297 mm、144 DPI、2381×1684 px（与 flood profile 一致，`require_scene`/`require_execution`/`require_manifest` 无需改动）。

## 4. 实施阶段

### Phase 0：探测与前置确认（约 0.5 天）
1. 确认真实 Python 3.11+ 解释器；`carto.py --help`、`schema check` 通过。
2. 征得同意后安装 rasterio/shapely；探测 `landCover_reclassified.tif`：CRS、行列数、像元大小、bbox、band 数、dtype、类值直方图（确认 1～10 实际出现值、255/nodata 处理）、与 CSV 的一致性。
3. 估算面化规模，敲定 D4 重采样参数；探测记录写入 `doc/dev-log/`。
4. 用户确认 §7 全部决策问题后冻结本计划。

### Phase 1：协议层最小扩展（约 1 天）
- Schema：`generate-request`（format/synthetic 放宽）、`scenario-capabilities`（data_nature enum）、`prepared-data-bundle`（data_nature enum）、`portrayal`（categorical）、新增两个 land-cover overlay schema。
- 策略：`intent-profiles.yaml`（+land-cover-map）、`map-expression-catalog.yaml`（+choropleth/categorical）。
- 洪涝 overlay 收紧（D1）+ `fixtures/schema_cases.py` 补合法/非法样例（未知字段拒绝、format/data_nature 非法组合拒绝、flood 回归样例）。
- 验收：`carto.py schema check` 绿；`test_schemas.py`、`test_scenario_registry.py` 绿。

### Phase 2：场景实现（约 2～3 天）
新增 `scripts/carto_core/scenarios/land_cover_raster/`，对齐 flood 的 7 组件契约：
- `source_contract.py`：TIFF/CSV 源语义、角色绑定建议与校验（raster 角色 `class-raster` + legend 角色 `class-legend`）。
- `data_preparation.py::LandCoverRasterDataPreparer`：路径守卫/摘要校验/新鲜度 → rasterio 读取 → CRS 校验与矢量重投影 → 尺度控制 → 面化 → CSV 图例解析与域校验（target_value 唯一、覆盖栅格全部出现值、类 5 未映射即拒） → prepared GeoJSON + bundle（transformations/quality_evidence 回执：类直方图、像元/面计数、nodata 计数）。
- `planning.py`：categorical 计划（类序、色彩方案引用、extent、标题、legend_source=legend-table）。
- `candidate.py`：`step`/`match` 表达式按 `class_value` 上色；10 类色板（色觉障碍友好、适宜性 ordinal 语义用顺序色带，水体/无数据固定灰）；overlays：标题、图例（含推断标签）、指北针、比例尺、来源注记（真实数据出处）、notice 声明；scene/candidate/preflight 编译，绑定 profile 摘要。
- `final_checks.py::validate_legend`：图例类别齐全且顺序一致、无数据符号存在、推断/概览声明存在。
- `validation.py::build_validation_scene`：基于模板包内**合成小栅格 fixture**（不含用户真实数据）构建验证 scene。
- `author.py`：确定性生成模板包文档（contracts 六件、prototype、fixture、dependencies.lock、checksums）。
- `scenario_registry.py::_COMPONENTS` 注册 `land-cover-raster-v1`。
- 通用 workflow/compiler 代码**不改**（`map_data_preparation.py` 等已按 profile 分派）；若发现通用层残留 flood 假设，按"通用内核与演示场景隔离"原则单独修正。

### Phase 3：模板创建与发布（约 1 天）
- `templates/map-scenario/land-cover-classified/1.0.0/` draft 合成示例包（对齐 urban-flood-risk 结构）。
- 走 create-template 闭环：`analyze → brief → author → validate`（合成 fixture 验证 scene + RenderReceipt）→ 精确 TP → `publish` 入权威仓库与索引。
- 验收：`test_template_library_examples.py` 模式的新模板用例；发布前重验证（依赖锁、fixture、检查器集合、环境绑定）。

### Phase 4：能力注册（约 0.5 天）
- `scenario-capabilities.yaml` 新增 profile：`id: land-cover-classified-demo`、`implementation: land-cover-raster-v1`、模板三元组绑定、`request_schemas` 指向两个新 overlay、`intent: {government_thematic, land-cover, [land-cover-map]}`、`data_nature: user-provided`、`production_enabled: false`、notice（D6 文案）、licenses（如 `user-data-local-only`）、output_profile（D8）、`internal_field_names: [class_value, class_label]`。
- 验收：registry 加载去重校验（identity/authoring/template 键唯一）通过；flood profile 不受影响。

### Phase 5：generate-map 端到端联调（约 1 天）
- 运行时把仓库根与 `projects/`（或 `projects/dataset`）显式纳入 `--allowed-root`；请求 JSON 按新 overlay 构造（source_bindings 两条：geotiff + csv，摘要、freshness、字段绑定齐全）。
- 依次执行 intake → brief → compile → preview（真实浏览器人工确认后 G2）→ freeze → render → check → G3 → deliver → delivery-status。
- 审批注意：G1/G2/G3 必须走程序验证的精确审批回执；IDE 终端"同意"不构成审批（SKILL.md 第 5 条）。
- 交付包白名单不变：`map.pdf`、`map.png`、`README.md`、`delivery-manifest.yaml`、`checksums.sha256`。

### Phase 6：测试与回归验收（约 1 天）
- 新增 `test_land_cover_scenario.py`：data preparer 合法/非法（摘要不符、CRS 缺失、类值越域、图例缺行、类 5 出现、超尺度上限、非 geotiff 伪装）、planner/candidate 确定性（同输入同摘要）、legend checker、manifest/notice 链。
- schema_cases 非法样例覆盖 D1 全部放宽点 + flood 收紧点。
- 端到端：合成小栅格 fixture 全自动；真实 TIFF 一次人工审批联调（Phase 5 即验收）。
- 全量回归：`python -m unittest discover -s skills/carto-agent/scripts/tests -v` 绿。

### Phase 7：文档同步（约 0.5 天）
- `SKILL.md`：当前阶段边界（新增土地覆盖场景、真实 CRS 转换的有限实现声明——仅注册场景内确定性重投影，不声明通用生产制图）、内置模板示例说明。
- `workflows/routing.md`：能力声明段更新。
- `workflows/generate-map.md`、`create-template.md`：场景清单与请求示例。
- `doc/dev-log/`：Phase 0 探测记录、联调记录。
- README/AGENTS.md 如引用阶段边界则同步。

**总量估算：约 7～8.5 个工作日**（不含审批等待）。

## 5. 风险

| 风险 | 影响 | 缓解 |
|---|---|---|
| 面化规模失控（百万级多边形） | preview/render 超时、内存溢出 | D4 阈值 + 重采样 + 简化，Phase 0 先测算 |
| rasterio Windows wheel / GDAL 环境问题 | 依赖装不上 | Phase 0 先装先验；失败则评估纯 Python TIFF 解析降级方案（工作量大，最后手段） |
| 通用 Schema 放宽引入 flood 回归 | 既有闭环被破坏 | overlay 收紧 + 回归样例 + 全量测试（Phase 1/6 双卡点） |
| data_nature 扩展被误读为"生产开放" | 能力边界声明失真 | production_enabled 保持 const false；SKILL.md/routing.md 同步改写边界；notice 全链强制 |
| 重采样综合造成语义误读 | 用户拿概览图当精确分类图 | notice + README + 图例注记三重声明 |
| 真实数据泄入 fixture/日志 | 违反敏感数据约束 | 模板 fixture 只用合成小栅格；测试不读 projects/dataset；日志不打印数据行 |

## 6. 明确不做（本里程碑边界）

- 不新增 raster 原生渲染适配器（image source/PNG overlay）；
- 不开放 `edit-native-map`、`curate-catalog` 路由；
- 不声明生产制图、共享服务、外部/公网发布能力；`production_tasks` 保持为空；
- 不做多期对比、变化检测、栅格代数等分析能力；
- 不修改 `skills/ppt-master/`；不在仓库根新建第二套 src/schemas/tests。

## 7. 待用户确认的决策问题

1. **依赖**：同意安装 `rasterio` + `shapely`（含 GDAL/pyproj wheel）吗？
2. **数据性质**：接受 D1 方案（`data_nature: user-provided`，`production_enabled` 仍为 false，仍属本地工程闭环）吗？
3. **尺度综合**：接受 D4"必要时多数重采样 + 简化"的概览级综合（丢失逐像元精度，图上声明）吗？
4. **类值 5（空缺）**：按 D6 默认"栅格中出现即拒绝"，还是渲染为灰色"未分类"？
5. **图面文案**：标题/图例用 CSV 中的中文推断标签（如"最适宜（针叶/常绿林…）"）直接上图，还是简化为短标签 + 附图例说明表？
6. **输出**：维持 A3 横向 144 DPI、PDF+PNG 双目标吗？

## 8. 验收清单（DoD）

- [ ] Phase 0 探测记录入 dev-log，决策问题全部有用户书面确认
- [ ] `carto.py schema check` 通过；全量 unittest 绿（含新增合法/非法样例）
- [ ] flood 场景端到端回归通过（协议零回归）
- [ ] land-cover-classified/1.0.0 经真实 TP 发布入权威模板仓库
- [ ] 真实 TIFF 请求走通 intake → … → deliver，交付包含五件白名单产物，checksums 校验通过
- [ ] notice/推断声明出现在 PDF/PNG 图面、DeliveryManifest limitations、交付 README 三处且一致
- [ ] SKILL.md / routing.md / workflows 文档与实际能力一致
