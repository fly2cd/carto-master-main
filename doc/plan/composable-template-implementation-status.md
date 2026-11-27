# 可组合模板架构 — 首期实施状态记录

| 项目 | 内容 |
|---|---|
| 日期 | 2026-11-24 初版；2026-11-25 评估后修订；2026-11-25 映射实施完成验收 |
| 关联计划 | [composable-template-architecture-implementation-plan.md](composable-template-architecture-implementation-plan.md) |
| 关联 ADR | [ADR-001-composable-template-architecture.md](ADR-001-composable-template-architecture.md) |
| 协议治理 | [protocol-evolution-segment-refs.md](protocol-evolution-segment-refs.md) |
| **验收包** | [leadership-visit-acceptance-package.md](leadership-visit-acceptance-package.md)（对应代码快照的正式验收证据） |
| 范围 | 首期 P0–P4（P3a）+ P6 领导调研迁移（S1–S8）；P3b / P5 / P7 / GD 未启动，须单独评审 |
| 环境 | geo313（Python 3.13.18 / pyproj 3.8.0 / PROJ 9.7.1），合成数据 + 合成审批 + 真实渲染，非生产准入 |
| **总体判定** | **首期 P0–P4 与 P6 领导调研迁移主体完成并按验收包验收**；阻断缺陷已修复，46 字段+12 隐式决定合同化，私有权威退出运行链。限制（生产准入/旧模板兼容/协议治理文档）如实保留，见验收包 §8 |

> 本记录如实区分"已验收"与"未开放/限制"。局部回归不表述为全量通过；跳过项不视为通过。验收以 [验收包](leadership-visit-acceptance-package.md) 的实际测试证据为准。

## 评估结论与修复（2026-11-25，已闭合）

2026-11-25 客观评估的四项发现均已修复并经测试验证；后续 P6 迁移（S1–S8）补齐了组合专属正反例与消费者覆盖。正式验收证据见 [验收包](leadership-visit-acceptance-package.md)。

| 发现 | 级别 | 状态 | 处置 |
|---|---|---|---|
| 1. 请求↔候选↔锁组件引用一致性缺失（夹带未选引用可过预检/冻结） | 阻断 | **已修复+验收** | `MapCandidateCompiler._require_selection_binding` 于 check_candidate 严格比对 execution.template_refs/ownership 与请求选择+受信安装身份；预检/预览/冻结/锁重验共用。真实工作流反例（夹带/漂移引用）拒绝 |
| 2. P3a 适用性校验名不副实 | P2 | **已修复+验收** | validate_suitability 核验上下文自洽（id/version/digest/business_scene/implementation/renderer_id）、几何准入、场景身份、段引用种类+钉住；compile 传实际引用。方法级反例 6 项 |
| 3. 公共协议扩展未完成显式版本治理 | P2 | **segment_refs 已闭合；领导调研新 schema 治理待形式化** | [protocol-evolution-segment-refs.md](protocol-evolution-segment-refs.md) 闭合 segment_refs；领导调研 11 新 schema 为加性工程验证态，正式版本决定/摘要影响报告待补（验收包 §8 限制） |
| 4. 测试证明范围窄于退出要求 | P2 | **已补齐** | P0 真实工作流反例；P4 组合专属正反例（A09/A10/A20/矢量/所有权/漂移）；P6 非基线正反例+实际生效+修订保持+一致性（验收包 §3–§6） |

**剩余限制**（非阻断，如实保留）：生产准入未开放、旧 image_itinerary-only 模板需重新作者化、协议治理文档待形式化、环境跳过项未验证。详见 [验收包 §8](leadership-visit-acceptance-package.md)。

## 评估后继续执行进度（2026-11-25，已完成）

P4 验收补齐与 P6 领导调研迁移均已完成，统一由下方"映射驱动的主体迁移（S1–S8）"表与 [验收包](leadership-visit-acceptance-package.md) 记录。早期"步骤 3/5/6 未做"的描述已被 S5（消费者接通）/S7（A17/A18）/S8（权威切换）的完成证据取代，不再保留。

- P4 验收矩阵：A09（容量冲突）/A10（Style 视觉生效）/A20（G1 后改选择）/矢量组合/A01/A02 P0 真实工作流/A07 全链/A08 所有权/A26 新段零代码/A03/A21 漂移 + 阻断反例均建立。A11/A12/A22/A23/A27/A28 由既有共享测试覆盖。
- §13.5 单位/几何验证：[报告](p6-unit-geometry-technical-validation.md)，几何/物理单位不变量成立。
- 跨场景 A17/A18、删除 image_itinerary 私有权威：见 S7/S8（完成）。

**代码稳定性（权威全量回归）**：含事项1收口 + design-instances 样例修复的最终全量回归 **1126 passed / 9 skipped（环境门控）/ 968 subtests / 0 失败 / exit 0**（geo313，35:47）。早期 test_raster_formal 7 项失败（选择一致性门冗余场景比对）与 design-instances 缺样例 1 项失败均已修复。注意：回归通过证明被测行为无已覆盖回归，单位测试证明几何/单位条件成立；合同职责拆清以验收包逐项证据为准。

## 映射驱动的主体迁移（2026-11-25，按 46 字段映射实施）

依据已确认裁决 D1–D7（[ownership-contract-boundaries](leadership-visit-ownership-contract-boundaries.md)）与 [46 字段映射](leadership-visit-style-contract-field-mapping.md)（M01–M46 + X01–X12）。映射 §9.1 指出当前 Style schema 不足，须先落地类型化合同根基。分阶段：

| 阶段 | 范围 | 状态 |
|---|---|---|
| **S1 度量合同根基** | `symbol-measurement`（判别式 Q/PT/MM）+ `measurement-rule`（U）schema；`image_symbols` 消费显式 U 规则，基线 2381×1684/floor1.0 为登记预设非隐式常量 | **完成**：对应 X03/§2.2/§5.4 |
| S2 角色外观 + 组件定义合同 | C[type] 受信组件定义 + J[card/route/linked-label/double-outline] 参数 schema + A[role] 类型化外观（role-appearance，含 stroke.color） | **完成**：component-definition + card/route/linked-label/double-outline-parameters + role-appearance schema + 样例 + 反例；消费者经 S5 接通 |
| S3 MapPlan 实例扩展 | I.components[J]/annotations[N]/content/group_bindings/legend_labels/group_resolution/basemap_display[V]；新增 `annotation-placement`/`basemap-display` 闭合 schema；map-plan v4 加性可选 | **完成**：实例合法/旧 plan 加性不变/闭合反例通过；生产者（作者迁移）与消费者（S5）已接通 |
| S4 字段族迁移 | `contract_migration.migrate_image_itinerary` 按 M01–M46 精确变换产出新实例；新增 `role-appearance`/`route-parameters`/`linked-label-parameters`/`double-outline-parameters` schema | **作者迁移完成**：129 schemas，M18 gap=2×、M05/M09 归一、M25 基线 False、M30/M32 归并、M41–M46 物理单位等逐项验证 + 产物闭合校验（74 项/471 subtests） |
| S5 消费者接通 | `design-instances` schema + portrayal.design_instances（作者发射）；compiler 从新实例解析有效样式供 PDF+前端；apply_overrides 从新实例解析→补丁→再生 | **完成**：领导调研全套真实渲染/发布/生成通过；前端 geo_sections 与 PDF 家具消费同一解析实例。image_itinerary 已由 S8 移除（不再作 override 基底/验证源） |
| S6 隐式决定 | X01–X12 显式合同化 | **全部 12 项完成**：X01 图例顺序入 I.legend_labels；X02 角色分类脱钩（缺辅助角色拒绝）；X03 度量规则 U；X04 行高乘数显式；X05 卡片结构 preset（card-parameters.structure：body-divider-title/gap-midpoint/center）；X06 边框围绕显式绑定；X07 颜色角色链 Style→图形→渲染器；X08 业务文本入 content_contract.py（场景内容合同，共享组件无业务文本）；X09 preferred/fixed；X10 字体适配显式模式；X11 双编号角色；X12 frame_id/坐标空间 |
| S7 跨场景验收 | A17（换组件事实不变）/A18（同份兼容 Layout 双方消费），显式引用，不必等 P5 | **A17+A18 通过**：A17 换 Style 角色色保持停靠/顺序/路线几何/图例文字不变；A18 Layout 经共享 LayoutResolver+layout schema 被双方消费（场景无关，无并行解析权威） |
| S8 权威切换 | 作者仅发射 design_instances（移除 image_itinerary）；compiler/override/route_validation 全从 design_instances 解析；portrayal 条件接纳 design_instances | **完成**：image_itinerary 私有权威退出运行链；领导调研 137 项（真实渲染/发布/生成/修订/在线底图）通过；后端绘图函数保留，消费解析派生副本。image-itinerary-style schema 仅用于校验解析后有效形状；TEMPLATE_STYLE 留作离线作者基线 |

**纪律**：每阶段验证等价/反例；回归通过≠合同职责已拆清；旧已发布模板/锁不原地改写；不静默接受旧输入猜测转换；字重/测量算法变更与基线一致性分开验收（映射 §5.3）。

### 事项1 — 新合同实际消费收口（2026-11-25，完成）

消除"字段接受了但运行仍按固定名称/默认规则"（验收包 §4.1）：
- **度量判别解析**：`_ref_px`/`_physical` 按声明 kind 解析，校验 rule_ref，拒绝不支持单位组合（mm/pt 不当参考像素）。
- **显式角色绑定**：resolve 经 `_binding_map` 从 group_bindings 取 visual_role/route_role（不拼接业务组名）；重复/缺失/悬挂绑定拒绝。group_bindings schema 加 route_role。
- **组件定义校验**：新增 `compiler/component_registry.py` 受信定义注册表；compile 入口 `validate_design_components` 按定义闭合参数 schema/结构模式/类型校验，未知参数拒绝不丢弃。
- **内容/放置生效**：apply_grouped_style 消费 annotations，fixed 模式进入 _place 真实布局约束。
- 证据：`test_p6_acceptance.py::ContractConsumptionTests`（6 项）+ 领导调研 92 passed。

### 候选策略边界（2026-11-26 设计决策，完成）

- **领导调研单候选**：`validate_body` 显式拒绝 `design_variants`（`LEADERSHIP_VARIANTS_UNSUPPORTED`）；风格版式走 `style_overrides` 直接覆盖。修正了过时的 image_itinerary 权威注释。
- **多候选保留给政务制图（通用专题）**：roadmap 登记 `general-multi-variant-per-candidate-plan`（P5）——共享 plan 下改 plan 影响字段（output_profile）的 variant 不一致是潜在点，逐候选 plan 落地后再开放。
- 证据：test_leadership_single_candidate_boundary + test_capability_roadmap；领导调研 92 passed。

### P5 检索接入生成（2026-11-27，完成，全量回归确认）

按确认方案实施 6 工作包（P5-1/2→P5-5→P5-3/4→P5-6）：

| 工作包 | 实现 | 证据 |
|---|---|---|
| P5-1 受信上下文 | design-requirement 加 `context{business_scene,geometry}`；resolve 按上下文经 effective_definitions 选能力，无上下文→clarify 不默认 general | test_p5_resolution ContextSelectionTests |
| P5-2 类型化事实 | 新增 `style_fact_view` + style-enum/style-measure 谓词；resolve 按 kind 选事实视图（Style 不走 LayoutResolver）；dpi 取自能力 output_profile | StyleFactAdaptationTests |
| P5-3 联合检查 | `compiler/composition_check.py`：style+layout 跨组件检查（主图/标题/图例槽、字号×容量、图例容量、后端），冲突带来源+责任组件 | CompositionCheckTests |
| P5-4 搜索完整性 | resolve 记录 search_metadata（source_scope/budget/examined/truncated）；预算耗尽→search-incomplete；design-resolution-result 加 search_metadata | SearchCompletenessTests |
| P5-5 生成连接 | `compiler/generation_connection.py`：assemble_segment_refs（闭合、拒重复/未钉住）+ attach_resolution_evidence（选中须在被检索集内，否则拒绝；解释作证据非权威） | GenerationConnectionTests |
| P5-6 逐候选 plan | compile_variants 接受注入 plan_factory，每候选独立 plan（修共享 plan）；workflow 注入 MapPlanner；领导调研保持单候选 | test_candidate_set test_per_candidate_plan_factory |

协议变更：design-requirement（context+style 谓词）、design-resolution-result（search_metadata）加性扩展，配样例+测试。

**全量回归**：1153 passed / 9 skipped（环境门控）/ 1012 subtests；唯一失败为 orchestrate 旧测试 req 缺 context（P5-1 预期行为变化），补 context 后 19 passed，回归干净。

### 默认方案预设机制（2026-11-27，完成）

回应"仅说目标如何带默认模板"：补**显式默认预设 + 经确认展开**，不硬编码。
- `policies/default-presets.yaml` + `default-presets` schema：按 business_scene+geometry 登记默认**场景模板**（其内嵌 style/layout 即声明的视觉默认）；独立 policy，不漂移能力摘要。
- `compiler/default_presets.py`：propose_default（advisory）+ expand_default_request（无显式模板时才提议；**必须 confirmed** 否则 DEFAULT_EXPANSION_UNCONFIRMED；显式模板永远优先；展开生成**新请求**带 default_provenance，不改已 intake 请求）。
- CLI `template expand-default --confirm [--out]`：intake 前展开。
- 内核 intake 仍复验模板 published+admitted。
- 证据：test_default_presets 6 项（确认门槛/显式优先/未知拒绝/不 mutate）。

### P6 剩余：跨场景真实复用（2026-11-27，完成，待全量回归确认）

迁移主体已由 S1–S8 完成；本轮补"跨场景真实复用"：
- **领导调研消费通用 Layout**：segment_refs 放宽为 layout-only（style 段仍拒绝，design_instances  owns style）；scenario 已声明 replaceable layout。
- **A18 real**：领导调研真实 compile 消费通用 `general-single-map-a3-landscape`（resolved_layout.template_contract == 通用合同，width 420），与通用专题复用同一 Layout 合同。独立测试类避免共享 root  artifact 冲突。
- **新增组件零改编译器**：通用 Layout 无需改领导调研候选编译器即可消费（A18 测试证明）。
- 证据：test_p6_a18_leadership_consumes_general_shared_layout + test_p6_layout_segment_admitted_style_refused；领导调研+P6 验收 111 passed。
- 共享表达组件定义（component_registry：information-card/classified-route/linked-label/double-outline/numbered-stop-marker）已登记，领导调研 design_instances.components 引用它们。

### 地理锚点图表注记（双专题叠加缺口，2026-11-27，完成+重构防爆炸，待最终回归确认）

回应收入图"面分级设色 + 每市锚定柱状图"双专题缺口：
- **重构（消除组件爆炸缺陷）**：初版 `anchored-bar-chart`+`bar-chart-parameters` 把 chart 的一个 kind 提升为独立组件，偏离既有 chart 单组件+kind 判别设计，打开爆炸路径。已重构为**单一 C[chart] 组件**：`chart-parameters` schema 以 `kind`(bar-vertical/bar-horizontal/pie/line) 判别变体；锚定（地理 vs frame）为正交放置维度(N)，不进组件名。新增 kind = 扩枚举+渲染分支，零新组件。
- `compiler/anchored_charts.py::build_anchored_charts`：数据锚点(I)+chart 参数(J)+放置(N) → 冻结 chart 图形；preferred 夹窗/fixed 不动；bar kinds 渲染，pie/line 声明但未实现→fail closed。
- render-scene image_graphics `chart` 类型 + kind 字段；image_page_renderer chart 分派（kind 判别）。
- 证据：test_anchored_charts 8 项（单组件无爆炸/新 kind 零新组件/pie fail-closed/fixed/preferred/闭合校验/graphic schema）。
- 双专题叠加：canvas-overlay 页区域面 + 锚定 chart 组合；portrayal+overlay 混合为后续扩展。

## 已完成

### P0 — 单候选段引用入口回归修复（独立紧急包）
- **修复**：`workflow/map_generation.py::_compile_approved_candidate` 的 `load_contracts(installation)` 补齐 `repository=self._repository_optional()`。
- **核验**：全部 5 个生产 `load_contracts` 调用点（单候选、多候选、preview、freeze、_locked_render_inputs）一致传递 repository。
- **测试**：`test_segment_refs.py::P0WorkflowSegmentRefRegressionTests`（段引用解析 + 完全嵌入基线不变）。
- **退出证据**：segment_refs 11 项、general_thematic 26 项、leadership_visit 87 项、segment workflow/authoring 21 项、边界守卫 25 项、digest_coverage 10 项均通过。

### P1 — 架构 ADR 与协议清单
- 产出 `ADR-001-composable-template-architecture.md`：提取边界、组件选择协议、所有权规则、三类绑定、P3a/P3b 分步、联合检查、摘要矩阵、审批失效规则、单写矩阵。

### P2 — 共享编译能力核验（纯重构边界）
- 核验共享 `compiler/` 层**不 import 任何 scenario 模块**；scenario 层正确消费共享端口。
- 组件协议（`component_protocols.py`）已定义并由 `test_component_protocols` 强制。
- 边界棘轮 `test_encapsulation` / `test_layer_ports` / `test_scenario_boundary` / `test_digest_coverage` 通过。
- 结论：首期所需共享端口已存在，P2 以核验+棘轮确认为主，未做整文件搬迁。

### P3a — 能力上下文与适用性校验（窄增量）
- 新增 `CapabilityContext`（不可变受信上下文快照）+ `ScenarioCapability.build_context()` + `validate_suitability()` + `ScenarioRegistry.capability_context()`。
- 接入 `workflow.compile`：构建上下文并校验组合适用性。
- **保留已登记 Scenario 身份集合**；未扩大身份准入（P3b 未做）。
- 下游 preview/freeze/render/check/review/deliver/recovery 沿用既有同一身份门（`require_request_intent` / `for_execution` / `for_template`）。
- 测试：registry + 边界守卫 48 项、真实工作流 GenerationTests 通过。

### P4 — 已发布组件的项目级组合纵向闭环（核心）
- **协议**：`generate-request.segment_refs`（可选，style→map-style / layout→map-layout，精确钉住）；`design-revision-proposal.changes.segment_refs`（组件修订键）。合法/非法样例 + 自动测试齐备。
- **解析**：`load_contracts(..., segment_refs=)` 在作者引用解析后应用请求级替换，经同一受信仓库 `fetch_segment`（身份+摘要+包完整性）；`OwnershipResolver.validate_request_segment_refs` 校验可替换权限/种类绑定/精确钉住。安装包装不被改写。
- **所有权**：请求引用取代作者基线，单一有效来源；`segment_selection`（refs/ownership/superseded）记录来源。`revised_cartography`+style 替换、`output_profile`+layout 替换、`design_variants`+段选择 → 拒绝（重复所有权 / P5 未开放）。leadership_visit 显式拒绝段替换（P6 未迁移）。
- **执行绑定**：`for_execution` 接受 1 个 map-scenario + 可选唯一 map-style/map-layout 引用；raster/vector 编译器将精确替换引用写入 `execution.template_refs` 与 `ownership`。无选择时 execution 形状与基线字节一致。
- **修订**：`segment_refs` 修订键失效 plan+compilation，数据证据可复用（bundle 输入未变）。
- **测试**：
  - 编译器边界 9 项（A07 独立选择、A02 单段、A26 新段零代码改动、A03 缺仓库、A08 非可替换/种类/未钉住/未知段、A21 摘要漂移/损坏、所有权冲突、execution 绑定/重复拒绝）。
  - 工作流真实入口全链 1 项（A07：compile→preview→G2→freeze→render→check→review→G3→deliver，替换段进入冻结场景与锁）。
  - 修订键合法/非法 + 失效分析测试。

## 未承诺 / 未完成（须后续单独评审）

- **P3b**：完全解除固定 Scenario 身份分派、多身份适配（A05）。未做；不得宣称"能力与模板身份已完全解耦"。
- **P5**：检索接入生成、类型化事实适配、多组合候选比较预览（A13–A16）。`match_cmd._resolve` 仍固定 general 档案（B08 未改）。
- **P6**：领导调研迁移、单位/几何技术验证（A17–A19、A32）。leadership_visit 仍用私有 `image_itinerary` 权威，显式拒绝段替换。
- **P7**：L2 整体验收与发布支持矩阵。
- **GD**：项目段草稿直接正式制图（A24/A25）。未做；草稿不能直接正式生成。
- **P4 剩余验收项**：A09（字号下限×容量冲突定位）、A10/A11（颜色/字号/线宽/纸张/网格修改的逐项视觉证据）、A12（多 DPI 物理单位）、A20（G1 后未修订改选择）、A22（跨租户/路径/nonce 全矩阵）、A23（多候选恢复）、A27/A28（角色缺失/可读性审查）尚未逐项建立专用工程用例；现有共享安全/漂移/恢复门未被放松，但上述组合专属正反例需补齐。
- **联合检查增强**：语义/接口/物理/执行四类联合检查目前复用既有 `check_candidate` + `MapQualityChecks`；组合专属的"冲突来源+责任组件"定位报告尚未独立建立。

## 全量回归证据（P4 共享变更退出门）

- 命令：`python -m pytest skills/carto-agent/scripts/tests/`（geo313 / Python 3.13.18）
- 结果：**1041 passed, 9 skipped, 876 subtests passed, 0 failed / 0 errors**（1993s）。
- 9 项跳过均为环境未就绪，非代码回归，与 P0–P4 改动无关：
  - 3 项 Windows 符号链接权限（test_geospatial_mcp:283、test_host_probe:173、test_security:42）
  - 2 项可选 MCP SDK 未安装（test_geospatial_mcp:512/535）
  - 4 项独立 GIS 服务解释器未配置（test_geospatial_stdio:84/96/110/118）
- 四项边界棘轮（test_layer_ports / test_encapsulation / test_digest_coverage / test_scenario_boundary）通过，未扩大豁免。
- 跳过项不计为通过；Chromium/字体/栅格渲染 extras 本机可用，相关渲染测试实跑通过。

## 治理说明

- 未修改任何策略语义字段（`scenario-capabilities.yaml` 等）；无 steward 评审触发。
- 协议新增均为**可选字段**（additive），既有请求/提案/冻结产物形状不变；无旧别名、无兼容旁路、无自动迁移。
- 代码指纹随被改源文件变化；旧内部快照按现行 doctrine 重新准备/编译。
- 所有测试使用合成数据与合成审批签名，不授予生产准入，不开放敏感领导行程。