# 领导调研迁移验收包（对应实际代码快照）

| 项目 | 内容 |
|---|---|
| 日期 | 2026-11-25 |
| 代码快照 | HEAD `dbae41a49aeff837b98a18cd4c2865e361427190` + 未提交工作区（本验收包覆盖工作区改动） |
| 环境 | geo313 / Python 3.13.18 / pyproj 3.8.0 / PROJ 9.7.1 / rasterio 1.5.2 / Shapely 2.2.0 / Matplotlib 3.11.2 / Pillow 13.0.0 / jsonschema 4.26.0 |
| Schema 总数 | 130（新增 11：symbol-measurement / measurement-rule / component-definition / card-parameters / route-parameters / linked-label-parameters / double-outline-parameters / role-appearance / annotation-placement / basemap-display / design-instances） |
| 关联 | [实施状态](composable-template-implementation-status.md)、[46 字段映射](leadership-visit-style-contract-field-mapping.md)、[所有权裁决](leadership-visit-ownership-contract-boundaries.md)、[单位验证](p6-unit-geometry-technical-validation.md) |

> 本验收包以实际测试证据为准，不宣称生产准入。合成数据 + 合成审批签名；真实渲染路径执行。完成标志：可准确说清"哪些能力已验收、在哪个版本/环境验收、还有哪些限制"。

## 1. 全量回归结果

命令：`python -m pytest skills/carto-agent/scripts/tests/ -q -rs`（geo313）

**结果：1126 passed, 9 skipped, 968 subtests passed, 0 failed, 0 errors**（2147.99s / 35:47，PYTEST_EXIT=0）。

- 通过：1126 项测试 + 968 子测试。
- 失败：0。
- 跳过：9 项（均环境门控，明细如下，不计为通过）。

跳过项分类（环境门控，非代码回归）：
- Windows 符号链接权限：test_geospatial_mcp / test_host_probe / test_security
- 可选 MCP SDK 未安装：test_geospatial_mcp
- 独立 GIS 服务解释器未配置：test_geospatial_stdio

**纪律**：跳过项不计为通过；环境未就绪不据此断言代码回归。

## 2. 46 字段 + 隐式决定消费者覆盖

### 2.1 字段→消费者→验收测试映射

| 字段族 | 逻辑去向 | 运行消费者 | 验收证据 |
|---|---|---|---|
| M02/M03 groups id/label | S.group_definitions + I.legend_labels | style.py group()/legend | NonBaselineEffectiveness.test_nonbaseline_group_color_role_changes_only_that_group；test_unknown_group_refused |
| M04 groups color | A[group-*].color + I.group_bindings | style.py color → 图形/图例 | test_nonbaseline_group_color_role_changes_only_that_group |
| M05/M09 route offset | A[route-*].display_offset（归一） | style.py route_style | S4Migration.test_m05_m09_per_group_offset_normalized |
| M06 default_group | I.group_resolution（拆分图例色） | style.py group() 回退 | S4Migration.test_m06_fallback_split_from_legend_color |
| M07/M08 route width/halo | A[route/route-halo].stroke | style.py ×scale → 渲染器 | S4Migration.test_migration_preserves_source_values；图形等价 |
| M10/M11 arrows | J[route].arrows | style.py arrows ×scale | S4Migration（route-parameters 校验） |
| M12/M13 pin radius/font | A[numbered-stop-marker/visit-order-text] | style.py pin → 渲染器 | 图形等价 + X07 颜色角色 |
| M14/M26 callout width/mode | J[card].sizing.width | style.py fit_content → callout_text | S4Migration.test_m26_m24_card_width_mode_and_wrap |
| M15/M16/M23/M27/M28 callout fonts/colors | A[card-title/card-body] | style.py → callout_text/渲染器 | 图形等价 |
| M17 callout padding | J[card].inset | callout_text | S4Migration（card-parameters 校验） |
| M18 line_gap | J[card].sections.gap（=2×旧） | callout_text 高度 | S4Migration.test_m18_section_gap_is_double_old_line_gap |
| M19/M20 callout opacity/leader | A[card-background/card-leader] | 渲染器 | 图形等价 |
| M21/M22 callout offset | N[card].preferred_offset | style.py _place | NonBaseline.test_fixed_annotation_offset_honored |
| M24 title_wrap | J[card].title.wrap_mode | callout_text | S4Migration.test_m26_m24 |
| M25 show_arrival_time | I.content.card.fields | style.py lines | NonBaseline.test_content_selection_arrival_time_effective |
| M29–M38 support_label | A[support-*] + J[support-label] + N[support-label] | style.py support → 渲染器 | 图形等价 + X02 脱钩 |
| M39 numbering | I.content.numbering | style.py display_order | S4Migration.test_m39_numbering_display_order |
| M40 white_threshold | V.basemap_display.crop | candidate_compiler display 网关 | S4Migration.test_m40_white_threshold_to_basemap_display |
| M41/M42 page fonts | A[page-title/source-notice].font（PT） | candidate_compiler texts → furniture_font_pt | S4Migration.test_m41_m42_page_furniture_physical_pt |
| M43–M46 frame_border | A[map-border].color + J[map-border]（MM） | frame_border_rects | S4Migration.test_m44_m46_border_physical_mm |
| M01 schema_version | 各合同自身版本（退出私有版本） | schema 注册 | schema check 130 OK |

### 2.2 隐式决定 X01–X12 覆盖

| X | 合同化 | 验收证据 |
|---|---|---|
| X01 图例顺序 | I.legend_labels | 迁移 group_definitions 顺序 |
| X02 角色脱钩 | 缺辅助角色拒绝 | StyleTests.test_x02_role_classification_decoupled |
| X03 参考尺寸/floor | measurement-rule U | S1.test_baseline_preset_validates；NonBaseline.test_nonbaseline_measurement_rule_changes_symbol_scale |
| X04 行高乘数 | callout_text 显式参数 | 渲染等价（142 项） |
| X05 卡片结构 | card-parameters.structure preset | S6.test_x05_card_structure_preset_declared |
| X06 边框围绕 | frame_border_rects surrounds | S6（placed-map-content 拒绝 view-frame） |
| X07 颜色默认 | Style 角色→图形→渲染器 | 142 项真实渲染；render-scene text_color/edge_color |
| X08 业务文本 | content_contract.py | S6.test_x08_business_text_is_declared_content_contract |
| X09 preferred/fixed | annotation-placement.mode | NonBaseline.test_fixed_annotation_offset_honored |
| X10 字体适配 | furniture_font_pt fit_mode | S6.test_x10_font_fit_mode_explicit |
| X11 双编号 | I.content.numbering + visit_order | S4Migration.test_m39 |
| X12 frame_id/坐标 | 真实 frame_id 绑定 | StyleTests.test_p6_graphics_bind_resolved_frame |

## 3. 非基线正反例（不止基线往返）

| 用例 | 类型 | 证据 |
|---|---|---|
| 改 morning 角色色 → 仅 morning 图形变，default 不变 | 正例 | test_nonbaseline_group_color_role_changes_only_that_group |
| 改度量规则参考画布 → scale 1.0→2.0 | 正例 | test_nonbaseline_measurement_rule_changes_symbol_scale |
| show_arrival_time true/false → 到达时间行有/无 | 正例双向 | test_content_selection_arrival_time_effective |
| 未知非空分组 → 拒绝（不默认） | 反例 | test_unknown_group_refused_not_defaulted |
| reference-design 度量缺 rule_ref → 拒绝 | 反例 | test_invalid_measurement_representation_refused |
| 缺 design_instances → 拒绝（无 image_itinerary 回退） | 反例 | test_missing_design_instances_refused_at_compile |
| 卡片结构 section_order 非基线 → 拒绝 | 反例 | test_x05_card_structure_preset_declared |
| 字体 reject-overflow 溢出 → 拒绝 | 反例 | test_x10_font_fit_mode_explicit |
| 夹带/漂移组件引用 → 拒绝（P4 一致性门） | 反例 | test_general_thematic P4 反例 |

## 4. 单位/规则、fixed 注记、内容选择、分组绑定实际生效

- **单位/规则引用生效**：不同 U 规则参考画布产生不同 scale（test_nonbaseline_measurement_rule_changes_symbol_scale）；物理 pt/mm 跨 DPI 不变（S1 PhysicalUnitDomainTests）。
- **fixed 注记生效**：explicit/fixed 偏移被求解器保留，不移动（test_fixed_annotation_offset_honored）。
- **内容选择生效**：arrival-time 内容选择实际控制到达时间行（test_content_selection_arrival_time_effective）。
- **分组绑定生效**：group 角色色变化仅影响绑定组图形（test_nonbaseline_group_color_role_changes_only_that_group）。

### 4.1 事项1 — 新合同实际消费收口（ContractConsumptionTests）

消除"字段接受了但运行仍按固定名称/默认规则"：

| 收口项 | 实现 | 验收证据 |
|---|---|---|
| 1.1 度量判别解析 | `_ref_px`（要求 reference-design-px + 钉住 rule_ref）/`_physical`（要求 pt/mm）；不支持单位组合拒绝；mm/pt 不当参考像素 | test_physical_unit_in_symbol_field_refused（MEASUREMENT_UNIT_MISMATCH）；test_reference_px_missing_rule_ref_refused |
| 1.2 显式角色绑定 | resolve 经 `_binding_map` 从 group_bindings 找 visual_role/route_role，不拼接业务组名；重复/缺失/悬挂拒绝 | test_binding_drives_color_not_name_concatenation（重绑定→色随绑定）；test_duplicate_missing_dangling_binding_refused |
| 1.3 组件定义校验 | `compiler/component_registry.py` 受信定义注册表；compile 入口 `validate_design_components` 按定义校验参数（闭合 schema）/结构模式/类型；未知参数拒绝不丢弃 | test_unknown_component_parameter_refused_not_dropped（COMPONENT_DEFINITION_UNKNOWN / 闭合参数拒绝） |
| 1.4 内容/放置生效 | apply_grouped_style 消费 annotations；fixed 模式进入 _place 真实约束（求解器不移动） | test_fixed_annotation_mode_enters_layout_constraint |

**目标达成**：修改一个合法新合同选择（重绑定角色/改度量单位/改组件参数/改放置模式），输出或拒绝结果符合其语义；不存在"接受但按固定名称/默认执行"。

## 5. 新实例修订不丢失无关选择

| 用例 | 证据 |
|---|---|
| override morning 色 → default 色/卡片参数/内容/底图/注记不变 | RevisionPreservation.test_override_one_group_preserves_other_selections |
| override callout 宽 → 角色/内容/分组绑定不变 | RevisionPreservation.test_override_callout_width_preserves_groups_and_content |

## 6. 请求/计划/执行实例/锁一致性

| 用例 | 证据 |
|---|---|
| compile execution_digest 绑定 execution；图形色与采纳角色一致；ownership 记录场景权威 | InstanceConsistency.test_compile_execution_binds_design_instances_consistently |
| 缺 design_instances 拒绝 | InstanceConsistency.test_missing_design_instances_refused_at_compile |
| 夹带未选/漂移组件引用拒绝（预检/预览/冻结/锁重验共用门） | test_general_thematic test_p4_smuggled/drifted_component_ref |
| G1 后改选择 → JOB_INPUT_DRIFT | test_general_thematic test_p4_a20 |
| 全链 freeze→render→check→review→G3→deliver（锁绑定） | test_leadership_visit full_generation / full_loop_to_delivery（8 项） |

## 7. 模板与协议版本切换规则

- **新增 11 schema 均加性**：既有实例形状不变；旧 plan/portrayal 仍校验通过（S3 test_legacy_plan_still_validates）。
- **portrayal 条件**：design_instances 与 image_itinerary 同等视为图片行程 portrayal（无需 layers）；design_instances 存在时运行权威为其。
- **旧模板切换**：S8 后 compiler 强制 design_instances；**旧 image_itinerary-only 已发布模板须重新作者化+重新验证发布**（映射 §9.3：不原地改写、无自动迁移器）。
- **旧锁/回执**：不原地改写；需新设计的运行重新准备/审批/编译/冻结。
- **协议治理待补**：正式版本决定/生产者—消费者清单/摘要影响报告（映射 §9.2）尚未形式化（见 §8 限制）。

### 7.1 候选策略边界（2026-11-26 设计决策）

- **领导调研：单候选**。`design_variants` 被显式拒绝（`LEADERSHIP_VARIANTS_UNSUPPORTED`，forbidden 边界）；风格/版式调整走 `style_overrides` 对当前合同直接覆盖（单候选）。证据：test_leadership_single_candidate_boundary。
- **多候选（开放设计/对比风格版式）：保留给政务制图（通用专题）**。当前通用专题 `_compile_variant_set` 共享一份 plan、逐候选 apply_overrides；改 plan 影响字段（如 output_profile 画布）的 variant 与共享 plan 不一致是潜在点。修复方向"逐候选 plan"登记 roadmap `general-multi-variant-per-candidate-plan`（P5），落地后再开放受 plan 影响的多候选差异。
- 领导调研当前从**逐候选 contracts**（非共享 plan）读实例，故无"接受但不生效"问题；单候选边界是设计选择，非缺陷修复。

## 8. 已验收能力 / 版本 / 环境 / 限制

### 已验收（geo313 / HEAD dbae41a + 工作区 / 合成数据+合成审批+真实渲染）

1. 领导调研生成链在 design_instances 框架下端到端跑通（publish→generate→preview→G2→freeze→render→check→review→G3→deliver，含在线底图/修订）。
2. 私有 image_itinerary 设计权威退出运行链；后端绘图函数消费解析派生副本。
3. 46 字段迁移 + 12 个 X 隐式决定合同化，消费者覆盖见 §2。
4. 非基线正反例、实际生效、修订保持、一致性证据见 §3–§6。
5. 等价性：resolve(migrate(基线))==基线；新实例图形与基线字节相同；A17/A18 通过。

### 限制（未验收 / 未开放）

1. **生产准入未开放**：production_enabled=false；真实行程敏感数据准入、真实 G1/G2/G3/TP 审批身份未验收（合成签名不授予生产准入）。
2. **旧已发布模板向后兼容断裂**：image_itinerary-only 旧模板在新代码下生成失败，须重新作者化/发布（doctrine 内预期，无自动迁移）。
3. **协议治理文档未形式化**：新增 schema 为加性工程验证态；正式版本决定/生产者—消费者清单/摘要影响报告待补（映射 §9.2）。
4. **环境跳过项**：符号链接权限/MCP SDK/独立 GIS 解释器相关测试跳过，未验证（非代码回归）。
5. **X05/X08 声明级**：卡片结构 preset 与业务文本内容合同已声明，但渲染器结构顺序仍为基线代码（声明与消费完全打通需后续）。
6. **跨场景 A18 为接口级**：证明 Layout 经共享 LayoutResolver 双方消费；非同一 Layout 段在两个完整生成链实跑。