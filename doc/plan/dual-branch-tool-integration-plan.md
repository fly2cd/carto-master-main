# Carto 双分支工具层整合实施计划

## 摘要

两个工作副本指向同一上游仓（`liudakemgslab/Intelligent_Geo-Spatiotemporal_Agent`），但本地无共同祖先（merge 侧为单提交快照）。实测 130 个共享路径中 **54 个仅换行符差异、76 个真实分歧**，而治理/安全内核（`canonical.py`、`errors.py`、`schema_registry.py`、`security/*`、`compiler/{dependencies,ownership,protocol}.py`）**内容零差异**。结论：这是"控制核同构 + 能力面正交"，按插件化整合，不做文件级大合并。

## 主干推荐：main(U-P3.6)

从长远可扩展性看，扩展性来自**准入模型与端口抽象**，不来自已有场景数量：

1. main 已具备可扩展插槽：`ScenarioRegistry` 默认拒绝 + `capability-roadmap` 的 `forbidden` / `not_implemented` 分类 + 四轴分离（数据/表达/后端/版式）+ 受信目录。merge 的扩展方式是 if/elif 链与硬编码常量，新增场景会继续堆积。
2. main 已有书面领域收敛（`doc/design-convergence-20261109.md` 的 C01–C12 与 Encoding/Appearance/Composition/Renderer 模型；该文档已移除，可从 git 历史取回），并把"自由编排、受控锚定/求解、freeform/mosaic/inset"明确列为**已采纳未实现**——merge 的 poster 与 annotation solver 正好落入该预留位；反向不成立。
3. 安全不变量不可回退：main 的摘要绑定与重验链完整；merge 存在全零伪造 digest 与 stub geo_match，若以其为主干等于把证据链缺陷固化为基线。
4. 回归网密度：main 411 项（398 通过 / 13 外部跳过）；merge 侧测试更少且部分覆盖死代码。
5. 内核同构使该选择成本极低：不需重写内核，只需扩端口。

合并方向因此为 `merge_20261109` → 以 `U-P3.6` 为基的集成分支，共享路径冲突一律以主干为准，仅端口文件做三方归一。

## 迁移边界（本轮范围）

**迁入（工具与适配器层，37 个候选文件经 P0 三分类后确认）**
- `basemap/{__init__,metadata,fit,transform}.py`
- `adapters/geocoding/*`、`adapters/routing/*`（不含 `routing/data/`）、`adapters/amap_geocoder.py` 除外
- `adapters/{image_basemap,image_display,image_layout,geo_to_image_pixels,geo_to_original_pixels,route_display,file_parser,geo_layer_builder,annotation_solver,annotation_layout}.py`
- `workflow/annotation_layout.py`、`notices.py`、`routing_limits.py`、`config/geocoding.yaml`
- 端口文件三方归一：`adapters/tool_gateway.py`、`adapters/mcp.py`、`policies/tool-bindings.yaml`、`schemas/tool-result.schema.json`

**明确不迁**
- 场景与海报层：`poster_compiler.py`、`svg_serializer.py`、`design_serializer.py`、`style_resolver.py`、`layout_planner.py`、`layout_validator.py`、`compile_context.py`、`image_itinerary_style.py`、`image_native_layout.py`、`draft_poster.py`、`text_layout.py`、`text_metrics.py`、`canvas_*`
- 死代码：`adapters/component_renderer.py`（`COMPONENT_RENDERERS` 全仓无引用，且含数值篡改与写死比例尺）
- 数据资产：`adapters/routing/data/*`（真实路网 GeoJSON/backbone）、`basemap-library/`（31.6 MB PNG，含中文名目录）
- merge 的 16 个分歧 workflow 文件、26 个分歧 schema（端口相关除外）、6 个分歧 policy（`tool-bindings` 除外）、`SKILL.md`、`workflows/*`、`templates/`、`references/`

## P0 冻结与基线盘点（不改代码）

- 在上游仓 `git fetch` 两侧分支，确认 `merge_20261109` 上游是否有完整历史（本地仅 1 提交）；记录两侧 HEAD 与 digest 基线。
- 产出迁移清单三分类表（迁入 / 不迁 / 禁止迁），逐文件标注依赖与是否触碰分歧内核。
- 固化能力基线：`tool-bindings.yaml` 能力并集 = **15**（main 独有 `gis-raster-info`、`gis-raster-reproject`、`gis-raster-statistics`；merge 独有 `annotation-layout`、`geocoding-resolve`、`geo-to-image-pixels`、`image-basemap-prepare`、`image-display-bounds`、`route-planning`；共享 6 个）。
- 记录回归基线：main 全量测试、merge 全量测试各自结果留档。
- **红线：本轮不做全仓 EOL 规范化。** main 大量使用 `sha256(path.read_bytes())` 做代码摘要绑定（`compiler_digest`、`renderer_digest`、`algorithm_digest`、`page_renderer_digest`），改换行符会使所有已冻结候选/锁/回执 `*_CHANGED` 失效。54 个仅 EOL 差异文件一律取主干版本；迁入的新文件保持 LF，`.gitattributes` 只加针对性规则，禁止 `* text=auto`。

**验收**：清单与基线入 `doc/dev-log/`；无任何代码改动；main 回归仍为零失败。

## P1 merge 侧前置修复（先修后迁）

仅修本轮迁移清单内的文件，在 `merge_20261109` 上完成：

1. **补齐 artifact 落盘并回滚 schema 放宽**：`adapters/geocoding/handler.py` 与 `adapters/routing/handler.py` 当前无 `ImmutableArtifactStore`/`.put()`/`artifact_refs`（这正是 merge 放宽 `tool-result.schema.json` 的原因）。参照同仓 `adapters/image_basemap.py:110` 建 store 并落盘结果，随后**恢复 `artifact_refs` 的 `minItems: 1`**，删除针对 `geocoding-resolve`/`route-planning` 的 if/else 豁免。
2. **去重双高德实现**：保留 `adapters/geocoding/` 包；废弃 `adapters/amap_geocoder.py`（当前仅被场景层 `workflow/map_generation.py` 与 `tests/test_phase1_intake.py` 引用）。同步核查 `routing/router_amap.py` 与 `route_engine.py`/`router_dual_graph.py`/`dual_graph_router.py` 的职责重叠，收敛为单一入口 + 明确后端选择。
3. **参数化标注求解器**：`adapters/annotation_solver.py` 的 `quality` 权重（0.9/0.1）、边缘尺度（20）、退火温度（`0.965**step`）、交换概率（0.35）从写死改为 `config/annotation.yaml` 声明 + 校验；保留 `seed`/`fixed`/`iterations`/`gap_px` 声明入口；`check_layout` 保持不变（已是纯校验器，作为整合范本）。
4. **修 `basemap/fit.py`**：`elif scaling_factor > 1.02` 永不可达（前置 `>= 0.98` 已覆盖），`undersized` 状态形同虚设，需重排判定顺序；`_MIN_ACCEPTABLE_DPI=150`、`_MAX_SCALE_DEVIATION=0.50` 与 0.98/0.70/0.50 分档阈值移入 policy。
5. **数据资产外置**：`routing/data/*` 与 `basemap-library/` 移出代码包，改为带 `manifest` + `checksums.sha256` 的资产包，运行时经 PathGuard 允许根校验 + digest 绑定加载；中文目录名改 ASCII ID；资产包不入 skill 目录。
6. **清除静默默认**：审查 `file_parser.py`(938) 与 `geo_layer_builder.py`(404)，把 `.get(key, 常量)` 形式的表达/契约兜底改为 schema `required` + fail-closed；禁止 `freshness.observed_at = utc_now()` 这类伪造观测时间；未知类型/字段一律报错。

**验收**：merge 侧自身回归全绿；新增定向测试覆盖"tool-result 必含 artifact_refs""无静默默认""annotation 参数来自声明""fit 分档全可达"。

## P2 主干端口扩展（改接口不改业务逻辑）

1. **`tool_gateway.py` 三方归一**：采纳 merge 的 `invoke() -> (ToolResult, output)` 二元组返回；**不采纳** `artifact_store` 可选化（P1 已让全部能力落盘，保持必填更严格）。同步修改主干调用点：`adapters/mcp.py`、`adapters/geospatial_mcp.py`、`workflow/raster_preparation.py` 的 `receipt = adapter.make_gateway().invoke(...)`。
2. **`policies/tool-bindings.yaml` 取并集**：15 个 capability_id；版本 `1.5.0` → `2.0.0`。并集改变 policy digest，需同步 `policies/baselines/carto-core-*.yaml` 与所有 digest 绑定消费者。
3. **`schemas/tool-result.schema.json` 取主干严格版**，拒绝 merge 的豁免放宽。
4. **新增/收紧 schema**：`geocoding-request|result`、`route-planning-request|result`、`annotation-layout-*`、`image-basemap-*` 按主干规范落库（Draft 2020-12、`additionalProperties: false`、未知字段默认拒绝、每个协议同时提供合法与非法样例及自动测试）。
5. **`policies/security-policy.yaml` 补授权策略**：merge 侧已引用 `geocoding-approved`、`approved-annotation-layout`、`approved-image-presentation`、`approved-registration-transform`、`synthetic-image-source-read`，主干必须存在对应定义，否则默认拒绝会直接挡住新能力。
6. **联网外部 API 边界**：高德 geocoding/routing 是外网服务，须纳入主干网络纪律——凭据只经环境变量、不写普通日志/Fixture、超时与重试上限（沿用 geospatial MCP 的 60s 默认/300s 上限口径）、离线或被阻断时 **fail-closed，不得静默降级**到本地 `dual_graph_router`；`routing_limits.py` 并入统一限额。

**验收**：`python skills/carto-agent/scripts/carto.py schema check` 通过；能力清单并集为 15 且全部有授权策略；主干原 geospatial 链路与 411 项回归零失败。

## P3 能力迁入（分批，每批独立可回归）

- **批 A（无外部依赖）**：`basemap/{metadata,fit,transform}.py`、`image_display.py`、`image_layout.py`、`geo_to_image_pixels.py`、`geo_to_original_pixels.py`、`notices.py`
- **批 B（标注求解）**：`adapters/annotation_solver.py`、`adapters/annotation_layout.py`、`workflow/annotation_layout.py`
  - ⚠ merge 存在**同名不同层**的两个 `annotation_layout.py`（adapters 层是 ToolGateway handler，workflow 层是准备/快照/独立复核）。迁入时必须保留双层结构，**禁止合并为单一模块**，否则语义漂移。
- **批 C（联网能力）**：`adapters/geocoding/*`、`adapters/routing/*`（不含 data/）、`adapters/image_basemap.py`、`config/geocoding.yaml`、`routing_limits.py`
- **批 D（解析与显示）**：`adapters/file_parser.py`、`adapters/geo_layer_builder.py`、`adapters/route_display.py`

每批统一动作：注册 capability_id → 绑定 authorization_policy → 补合法/非法 fixture → 补单元测试 → 跑定向测试 → 跑全量回归 → 提交。

**验收**：四批各自回归全绿；每个新能力都有 valid/invalid 样例与测试；无任何新增静默默认。

## P4 准入与治理收敛

- 迁入能力一律经 `ScenarioRegistry` + `capability-roadmap` 管控。尚未接入任何业务场景的能力标记为 `not_implemented` / `feature`（按主干 `admission_class` 分类），**不得因代码存在即视为可用**——对齐收敛记录 C12「目录/Schema/宿主安装 ≠ 业务能力」。
- 废弃 merge 的第二套准入：`workflow/intent.py` 的 `SCENE_TERMS` 词表准入、无命中/未知场景兜底 `government_thematic`、`tasks or profile["task_ids"][:1]` 取首项默认。统一到主干 `IntentResolver`（缺失即澄清，不补写意图）。
- 单一权威：不保留 merge 的 `workflow/map_generation.py`(3178 行) 与主干同名文件(987 行) 双实现；本轮场景编排仍全部走主干。

**验收**：`environment probe-host` 与 CLI 路由不出现第二套准入；能力策略中新增条目均有 `admission_class`。

## P5 文档与验收对齐

- `SKILL.md` 新增"工具与适配器能力"章节：geocoding / routing / image-basemap / annotation-layout 的能力边界、联网纪律、离线 fail-closed 行为、资产包加载方式。
- `doc/dev-log/` 增整合记录（血缘事实、54/76 分歧测量、主干选择理由、迁移清单三分类、被拒绝的 merge 放宽项及理由）。
- 重建工具能力矩阵（原 `doc/geospatial-mcp-selective-integration-plan.md` 已移除，信息可从 git 历史取回）；按既有 SVG 规范重渲染架构图并目检文字不溢出。
- 留痕但不迁入：merge 侧 `SKILL.md` 声称「PosterLayoutPlanner 算坐标」而实际生效的是 `LayoutValidator`（缺坐标即报错）这一文档/实现矛盾，记入待办供 P6 处理。

**验收门槛（整合完成的判定）**：main 全量回归零失败；能力并集 15 且全部有授权策略与测试；`schema check` 通过；`tool-result` 无豁免；无新增静默默认；已冻结的旧候选/锁/回执摘要**未因整合失效**。

## P6 登记为后续、本轮不做

- poster/freeform 的 **Composition 端口**（承载 `poster_compiler` + `layout_validator` + `svg_serializer` + `style_resolver`），对应收敛记录 C05 与路线图第 4 项。
- `leadership_visit` / `government_thematic` / `emergency_mapping` 三场景迁入。
- 全仓 EOL 统一 + 代码摘要基线切换（须配套重跑所有项目产物，遵循"不保留旧格式兼容分支"）。
- merge 侧场景层 P0/P1 缺陷整改：伪造全零 digest 与 stub geo_match、`_compute_breaks` 忽略声明的 method（jenks/manual 实际算 quantile 却记为 jenks）、`_format_value` 改写量级而不同步单位、`_legend_semantics` 与 `_layout_elements` 硬编码业务文案与版式（"无数据"/"容纳人数"/图例须在右下象限/标题须居中+700）、对比度阈值私自放宽至 4.0 且对 3 位 hex 静默跳过、`mandatory_markers` 绕过 `policies/mandatory-markers.yaml` 导致 choropleth 缺 `scale_indicator`、合成数据缺 `synthetic_disclaimer`、未知组件类型静默丢弃。

## 主要风险与对策

| 风险 | 对策 |
|---|---|
| 代码摘要雪崩（EOL / tool-bindings 版本变更）导致旧候选与回执全部失效 | 本轮禁做全仓 EOL 规范化；`tool-bindings` 版本升级集中在 P2 一次完成，并同步 baselines 与全部 digest 消费者，升级前后各跑一次全量回归 |
| 引入联网外部 API 扩大安全面 | 凭据只经环境变量、不落日志、超时/重试上限、离线 fail-closed 且不静默降级到本地路由器 |
| 仓库膨胀（basemap 31.6 MB、merge .git 130.7 MB） | 二进制资产一律外置为 manifest+checksums 资产包，不进 skill 目录、不进 git 主线 |
| 同名不同义模块被误合（两层 `annotation_layout.py`） | 保留 adapters/workflow 双层结构，迁移清单逐文件标注层级，禁止按文件名合并 |
| unrelated histories 合并冲突面（130 共享路径） | 用真实 merge commit 取得血缘，但共享路径一律 `checkout` 主干版本，仅 4 个端口文件三方归一；onlyMerge 路径只 `add` 清单内文件 |
| 迁入代码未接场景却被误认为可用 | P4 强制 `admission_class` 标注，能力策略默认拒绝 |

## 测试计划

- 每批迁入后：先跑该能力定向测试，再跑 main 全量回归（沿用既有 conda 环境与 unittest 运行方式，不自动安装依赖）。
- 端口归一后重点回归：geospatial MCP 链路（`gis-raster-statistics` 经 ToolGateway 的证据绑定）、审批与 nonce、PathGuard 允许根、`schema check`。
- 新增测试必须覆盖：合法样例、非法样例、未知字段拒绝、离线/凭据缺失时 fail-closed、artifact 必落盘。
- 整合完成的客观判据以 P5 验收门槛为准，不以"文件已复制"为完成标志。