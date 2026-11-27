# 领导调研自由组合与需求入口：可执行实施方案

| 项目 | 内容 |
|---|---|
| 日期 | 初稿：2026-11-25；评审修订：2026-11-26（Asia/Shanghai） |
| 状态 | **已按评审建议修订，实施仍待授权**；本次授权仅为修改本文，不表示代码已完成，不替代 steward 评审、运行授权或审批凭证 |
| 工作清单依据 | [后续具体事项与目标](../plan/leadership-visit-composition-entry-next-actions.md)（事项 1–6 / M1–M3） |
| 边界依据 | [所有权与合同边界裁决 D1–D7](../plan/leadership-visit-ownership-contract-boundaries.md)、[46 字段映射 M01–M46 / X01–X12](../plan/leadership-visit-style-contract-field-mapping.md) |
| 框架规范依据 | [设计原则四层模型](../design-principles.md)、`AGENTS.md`、[协议演进记录范例](../plan/protocol-evolution-segment-refs.md) |
| 历史基线 | 初稿作者记录 HEAD `7e3ebb9`、工作区干净；领导调研 92 passed（130s）、P6 验收 10 passed（8.8s），Python 3.13.15。**这是历史报告，不是本次复跑结果** |
| 本次静态核对 | HEAD `7e3ebb988889faad4c1a74bc1c431b8680321b4e`；工作区有未提交改动，含 F1–F3 部分修复，见 §2.2。本次未运行测试 |
| 首批范围 | **G-A0 → B1（含 B1.9）→ B2 → G-A**；B3/B4 保留待批设计，验证宿主须先闭合；M2/M3 只给骨架与前置条件 |
| 不包含 | 不新增并列 owner 或模板种类；不改写已发布包/锁/回执；不自动迁移旧运行；不开放生产准入或敏感数据 |

> 运行时不读取本文。新增协议必须配套合法/非法样例与自动测试，未知字段默认拒绝。I1–I8 遵守 D1–D7，不新增并列所有权权威；**Q1 的源偏移解释、受信机制边界与宿主准入等新增语义选择须显式确认**，不能当作已批准的机械改造。

---

## 一、总体判断与路线

上一轮（`8553277`）完成的是**合同形状与权威来源的切换**。本轮要完成的是：合法设计选择实际生效或被明确拒绝；局部及连续修订不丢失其他已采用设计。首批不宣称完整自由组合或需求入口已经开放。

```text
G-A0 前置规格与分支治理：基线重钉 + 机制/单位/补丁边界 + roadmap 配套登记
   ↓
B1 合同实际消费收口（事项1）＋ B1.9 规划生产者（事项4 第4点提前）
   ↓
B2 新合同无损修订（事项2）
   ↓
G-A 发布与版本切换门：协议证据 + 缺口复核 + 1.0.0 → 1.1.0（steward）
   ↓
B3 兼容验证宿主 + 独立 Style/Layout（事项3） ┐ 默认待批
B4 请求级组合全链 M1（事项4 其余）           ┘
   ↓
G-B 第二次治理门：1.1.0 → 1.2.0
   ↓
M2 需求入口（事项5） → M3 类型化检索（事项6）：单独评审
```

**B1.9 提前的原因**：planner 产出实例不依赖独立资产；若只做 B1.7 落盘而没有 MapPlan 的真实生产者，设计来源链仍不完整。保留既有状态机与审批链，不另建工作流。

### 1.1 G-A0：实施前置规格与分支治理

1. 重钉 HEAD、工作区差异、文件归属与关键摘要；核验 F1–F3 已有修复，不覆盖并行工作。确认真实 Python 3.11+ 解释器及 `pyproj` 等依赖，记录路径/版本；既有 geo313 环境可核验使用，不猜路径、不自动安装。
2. 在编写消费者前确定受信机制注册、单位输出接口、闭合补丁路径、连续修订基准、摘要模式与 Q1 偏移语义；前置形成版本及指纹覆盖影响清单，G-A 收口实际证据。
3. **新 `roadmap.not_implemented` 调用与策略条目成套评审和交付**（清单见 G-A.2）。B1 相关测试前分支必须完成登记，不能等 B1/B2 后再补；未知 feature 会返回 `ROADMAP_FEATURE_UNDECLARED`。不得用 mock 或测试专用策略掩盖真实登记缺失。
4. 按治理流程取得所需 steward 评审后，可在隔离实施分支和合成验证仓库使用配套策略；不等于主线合并、正式发布或生产准入。G-A 之前不激活正式版本切换，`production_enabled` 限制不变。

---

## 二、一手代码事实核对

> F1–F22 保留为初稿对 `7e3ebb9` 的调查记录，行号为当时位置。**不能逐条当作当前工作区仍未修复的结论**；现状增量见 §2.2，实施状态须用重新钉定的代码与测试证据确认。

| # | 事实 | 位置 | 后果 |
|---|---|---|---|
| F1 | `_value()` 只取 `measurement["value"]`，不看 `kind`、不校验 `rule_ref` | `leadership_visit/contract_migration.py:177` | 判别式度量在运行侧退化为裸数字 |
| F2 | 视觉角色按 `f"group-{gid}"` / `f"route-{gid}"` 拼名取 | 消费侧 `contract_migration.py:204-205`；作者侧 `:62,70,73` | `group_bindings` 是死字段 |
| F3 | `components[].parameters` 只校验"非空 object" | `schemas/design-instances.schema.json`；`candidate_compiler.py:146` | 4 份组件参数 Schema 运行代码零引用 |
| F4 | 缩放按 `k.endswith("_px")` 判定 | `leadership_visit/style.py:242` | 单位靠后缀推断 |
| F5 | 前端自算一套 U 缩放 | `frontend_document.py:37-39,166,184` | 两个度量权威，换规则即分叉 |
| F6 | 前端硬编码业务词汇与源字段名 | `frontend_document.py:34,150-155` | X08 只完成一半 |
| F7 | 图例"行程点"取 `groups[default_group]["color"]` | `style.py:253-254` | M06 后半未落地 |
| F8 | `show_arrival_time` 缺省 True；卡片文字色缺省 `#FFFFFF` | `style.py:223,240-241` | 后端补内容/外观默认 |
| F9 | 渲染器/前端多处 `graphic.get(..., 默认)` | `image_page_renderer.py:378-388`；`frontend_canvas.py:140,165,192-194` | 缺字段即自定半径/字号/颜色/偏移 |
| F10 | 行高、字体适配模式、边框围绕对象只有参数与默认，调用点不传 | `adapters/image_layout.py:30,77,160,178-181` | X04/X06/X10 接口已留、值仍默认 |
| F11 | `N[id].placement.mode` 无人消费；fixed 只来自数据偏移 | `style.py:146-154`；`candidate_compiler.py:419-469` | 实例声明 fixed 无效 |
| F12 | 修订走"新实例 → 旧形状 → 合并 → 再迁移" | `request_contract.py:243-246` | 旧形状表达不了的选择在往返中丢失；`rule_ref` 硬取自 `route.stroke.width` |
| F13 | 作者迁移给缺省通道发明值 | `contract_migration.py:83,87` | "未声明"变成"已声明的白" |
| F14 | 领导调研 planner 不产出任何实例字段 | `leadership_visit/planner.py` 全文 | MapPlan 新字段无生产者 |
| F15 | 有效设计实例不落盘、不进 execution | `candidate_compiler.py:301-322`；`map_generation.py:228-235` | 渲染期无法复验用的是哪份设计 |
| F16 | 显式拒绝 `segment_refs`；`replaceable_segments: [layout]` | `request_contract.py:113-115`；`route_author.py:151` | M1 未通 |
| F17 | `embedded.style` 是通用 `CARTOGRAPHY`，领导调研编译器完全不消费 | `route_author.py:99-110,150` | 今天"换 Style 段"换的是没人读的合同 |
| F18 | 段验证宿主只允许唯一 raster 场景 | `scenario_registry.py:423-436` | 领导调研外观无法由现有宿主证明 |
| F19 | 同 id+version 不同 digest → `VERSION_CONFLICT` | `template_repository.py:195-197` | 改作者产物必须升版本 |
| F20 | 能力策略钉死模板版本 1.0.0 | `policies/scenario-capabilities.yaml:126-133` | 升版本必须改策略语义 → steward |
| F21 | 图例检查要求"不同组不得同色" | `legend_checker.py:44-58` | 独立 Style 的兼容硬条件 |
| F22 | 多候选只构建**一份共享 plan**，但每个 variant 单独 `apply_overrides` | `map_generation.py:264-270`；`map_candidate.py:336` | 若编译器改为从 plan 读实例，多候选会忽略各 variant 的设计（B1.9 必须处理） |

### 2.1 框架侧硬约束（本次核对新增，直接约束方案形状）

| # | 约束 | 位置 | 对方案的影响 |
|---|---|---|---|
| C1 | 内核不得 import `scenarios`，不得直读场景请求体词汇 | `tests/test_scenario_boundary.py` Guard A/B | 组件定义/度量规则**不能**做成内核内置的场景专用常量目录 |
| C2 | `compiler/contracts/validation/repository/security` 不得 import `workflow` 或 `adapters` | `tests/test_layer_ports.py:44-47` | 组件的后端能力校验不能读 `adapters` 的 renderer profile；须用根模块 `backend_registry` |
| C3 | manifest 现有 6 个 business_contracts 槽位（断言 `len == 6`） | `tests/test_schemas.py:356-361`；`manifest.schema.json` | 不新增第 7 个业务合同槽位，**不等于包只能有 6 个文件**；本批选择 `portrayal` 承载，不是唯一合法架构 |
| C4 | 每个 Schema 必须有合法+非法 fixture | `tests/test_schemas.py:33-42` | 新增 Schema 必须同步 `tests/fixtures/schema_cases.py` |
| C5 | 未实现能力必须在 roadmap 登记并以 `admission_class=not_implemented` 拒绝 | `design-principles.md` §2.1；`carto_core/roadmap.py`；`policies/capability-roadmap.yaml` | 本方案的所有"设计已定但未建"拒绝必须登记，不能用裸 ProtocolError |
| C6 | 代码硬编码默认值不应存在；缺失由合同提供，两者都缺则报缺口 | `design-principles.md` §2.4 | 支持 I7；也要求把 `BASELINE_MEASUREMENT_RULE` 这类**设计预设**移出内核 |
| C7 | 原图像渲染器指纹列举 `image_layout.py` 等 6 文件 + 4 Schema | `adapters/image_page_renderer.py:44-57` | 修改会导致环境漂移；新增消费/校验代码与 Schema 须另做指纹覆盖核验，不能假定自动纳入 |
| C8 | 公共协议扩展须有显式版本决定 + 生产者消费者清单 + 摘要影响 + 旧运行规则 | `protocol-evolution-segment-refs.md` | G-A 必须产出同规格记录，"Schema 通过"不算治理完成 |
| C9 | 策略语义字段进摘要绑定，唯一 steward 评审 | `AGENTS.md`；`.github/CODEOWNERS` | 模板版本 bump 触发 steward |

---

### 2.2 当前工作区增量与评审补充证据（2026-11-26）

- HEAD 未变，但 `contract_migration.py`、`candidate_compiler.py`、`style.py`、MapPlan Schema 与相关测试等已有未提交改动，另有未跟踪 `compiler/component_registry.py`。`_ref_px` / `_physical` / `_binding_map` 与 `validate_design_components` 表明 F1–F3 已有部分修复；**应审查补齐，而非重复建设或直接认定验收完成**。
- 以下 `C/` 指 `skills/carto-agent/scripts/carto_core/`，`S/` 指 `skills/carto-agent/schemas/`。

| 证据 | 修订结论 |
|---|---|
| `S/component-definition.schema.json` 允许字符串 parameter_schema；`C/schema_registry.py` 按名校验；`S/common.schema.json` 根只有 `$defs` | 模板可自选宽泛 Schema 会绕过参数约束；B1.3 必须绑定受信类型→验证器 |
| `C/backend_registry.py` descriptor 仅 renderer_id/family/geometry/export_formats/impl | 不是箭头、卡片、字体适配的完整特性词表；需类型化能力或明确支持矩阵 |
| `C/roadmap.py` 拒绝未登记 feature，也拒绝 delivered feature 的未实现守卫 | 登记与守卫前置成套交付，正式收口留在 G-A |
| `C/workflow/revision_graph.py` 只合并明列节点；场景 `revision.py` 有整值替换 | 必须显式失效 plan、累计补丁，不能依赖隐含传递或任意深合并 |
| `C/artifacts.py` 的 file_digest/atomic_yaml/artifact_ref 与 `C/canonical.py` | 文件字节摘要与 canonical JSON 摘要不同，不能要求二者相等 |
| 字段映射 X09、M10/M11、M44–M46 | 历史偏移不能自动当 fixed；箭头和边框外观仍由 A 权威决定 |
| `C/scenarios/leadership_visit/style.py`、`legend_checker.py` | 图上点按组色表达，通用图例样点角色不能暗中重定义组色 |
| `C/workflow/segment_validation.py`、`C/scenario_registry.py` | 不消费领导调研角色外观的宿主不能提供该能力的发布前证据 |
| `S/leadership-visit-template-create-request.schema.json` version 为 const 1.0.0 | 升级必须同步身份生产者、校验器及 fixture，不只作者 VERSION/策略 |

## 三、实施裁决

| 编号 | 裁决 | 依据 |
|---|---|---|
| **I1** | 共享度量解析位于 `compiler/image_symbols.py`。首批符号域只支持 `reference-design-px` 和单一显式 U；物理值保持 pt/mm 到声明的页面家具换算点。多个明确 U 属未实现能力，不自动当作歧义。 | D6 / §2.2 / §5.4 |
| **I2** | 语义组 → 视觉角色只经 `I.group_bindings`；禁止名字拼接、相似匹配、"找不到就用默认组"。 | D1 / D7 |
| **I3** | 模板携带组件声明/设计预设与度量规则，精确引用 `{id,version,digest}`；**实现/类型→参数 Schema、结构、单位域与后端要求由受信机制限定**。模板只能选择/收窄，不能放宽验证。内核可登记通用机制，不内置场景设计默认。 | D3 / C1 / C2 / C3 / C6 |
| **I4** | 有效设计实例落盘为不可变产物，进 `scene.resources` + `execution.resolved_assets`（现有 Schema 已允许），渲染期按 digest 复验。 | D7 / §7.1 |
| **I5** | 修订按闭合路径作用于当前已采用选择，归一为累计补丁；连续修订不回退到模板初始值。旧 `image_itinerary` 形状只保留为单向后端派生副本。 | D7 / §9.3 |
| **I6** | 外观值唯一来源是 Style（B1 阶段在 `design_instances.style_roles`，B3 后在 Style 段 `role_appearance`）；场景只声明角色需求与业务绑定。 | D1 / D2 |
| **I7** | 后端零独立默认：图形缺任一必需外观/排版值即拒绝。 | D7 / §5.2 / C6 |
| **I8** | **MapPlan 承载已采用 I/J/N/V，planner 为唯一生产者**；A 来自采用的外观合同。完整校验归一化选择、来源与引用，plan 摘要进 execution；解析快照仅为不可变派生记录，不能成为第二个可修订 plan。 | 事项4 第4点 / D7 |

### 3.1 四层归属自检（design-principles §2）

| 决策点 | 归层 | 说明 |
|---|---|---|
| 角色外观值、卡片结构模式、宽度模式、行高、字体适配模式、边框围绕对象、注记 preferred/fixed | **创意设计层** | 全部由合同/预设声明并被显式采用；程序不得自选 |
| Schema 闭合、参数范围、引用完整性、角色覆盖、后端能力、组色互异 | **形式验证层** | 程序排他；拒绝须点名缺什么 |
| 参考像素→有效像素、mm/pt→像素、字体测量、换行、高度、避让坐标、摘要 | **机械推导层** | 确定性；不得在推导中"优化" |
| 数据自带卡片偏移的语义（Q1）、图例取色角色 | **灰色地带** | 语义部分显式登记为设计选择，机械部分由程序执行 |
| 未建能力（物理符号单位、view-frame 边框、显式子内容布局…） | 创意设计层缺口 | 按 C5 登记 roadmap，`not_implemented` 拒绝 |

---

## 四、批次 B1：合同实际消费收口（事项 1）

> 退出判据：**修改任一合法的新合同选择，输出或拒绝结果必须符合其语义；不存在"字段接受了，但运行仍按固定名称或默认规则执行"。**

### B1.1 度量解析单点（F1 / F4 / F5 / I1 / I3）

1. `portrayal.schema.json` **加性**新增可选 `measurement_rules`（数组，元素 `$ref` measurement-rule）。作者发射基线规则；`BASELINE_MEASUREMENT_RULE` 常量从 `compiler/image_symbols.py` **移到 `leadership_visit/route_author.py`**（它是设计预设，不是内核机制，C6）。
2. `compiler/image_symbols.py` 只保留机制：
   - `scale_for_rule(window, rule)`（已有）；
   - `resolve_rule(rules, rule_ref)`：查合同内规则表 + 校验 `sha256_digest`；未登记 → `MEASUREMENT_RULE_UNKNOWN`，摘要不符 → `MEASUREMENT_RULE_REF_DRIFT`；
   - `resolve_symbol_px(measurement, *, rule, scale)`：非 `reference-design-px` → roadmap `not_implemented`（清单见 G-A.2，登记前置到 G-A0）；`rule_ref` 不一致 → `MEASUREMENT_RULE_REF_DRIFT`；
   - `physical_px(measurement, *, dpi)`：只接受 pt/mm；
   - **删除 `symbol_scale(window)` 的隐式默认规则**（无规则即拒绝，不再默认基线）。
3. `resolve_effective_style` → `resolve_effective_design(instances, *, rules, window, dpi)`，输出**按单位域标记的解析结果**：
   - Q 类符号完成参考设计像素 × U 的一次换算，输出有效图像像素；后续只允许图像→页面 contain 缩放。
   - 页面家具名义字号、物理线宽保留 pt/mm，到声明的页面消费点通过 `physical_px` 或共享等价函数换算一次；不可先转 px 又被家具函数当 pt/mm 重算。
   - G-A0 逐通道列“输入域→输出域→唯一换算点→消费者”。若某物理通道选择在解析阶段换算，须同步两端接口并标记页面 px，禁止两种约定并存。
4. `candidate_compiler.compile` 顺序调整（display 只需 `image_ref` + `white_threshold`，可行）：
   ```text
   读 instances → 校验 → white_threshold → display 工具 → window
   → resolve_rule + scale_for_rule → resolve_effective_design → apply_grouped_style
   ```
5. `style.py` 删除全部 `* scale` 与 `endswith("_px")`；数据 `callout-offset-*` 按 Q1 在同一入口换算。
6. `frontend_document.py` 删除 `_display_scale`，消费同一解析结果；U/scale 可保留作来源信息，不得对已换算值再乘一次。
7. **保留** `frontend_canvas` 的 `placement["scale"]`：那是"图像像素→页面像素"的 contain 缩放，与 U 缩放是两个域，不得合并。
8. 单次编译采用多个明确有效 U → roadmap `symbol-multiple-measurement-rules`；未知引用/摘要漂移仍属协议错误，缺少必需选择则要求补齐，不把显式多规则选择误判为歧义。

**测试**（新增 `tests/test_p6_consumption.py`）：换 U → 符号尺寸变化而 pt/mm 家具不变、PDF 与前端一致；反例：未登记规则 / digest 漂移 / 符号域出现 mm / 混用两个 U / 无规则；**基线 U 下改造前后 graphics 与 map_json 逐字节相同**。

### B1.2 角色绑定显式化（F2 / I2）

- 由 `group_bindings` 建 `semantic_group → visual_role` 表：重复 → `GROUP_BINDING_DUPLICATE`；组无绑定 → `GROUP_BINDING_MISSING`；指向不存在角色 → `APPEARANCE_ROLE_MISSING`；指向未声明组 → `GROUP_BINDING_UNKNOWN`。
- `apply_grouped_style` 改收**已解析的角色视图**，不再接收原始 `style_roles`，不再拼名。
- 未被引用的 Style 角色允许存在；被引用而缺失必须拒绝。

**测试**：改绑定指向另一角色 → 颜色随之变化而业务分组不变；角色名改成任意字符串仍生效；删绑定 → 拒绝。

### B1.3 受信组件机制与模板声明接通（F3 / I3 / C1 / C2 / C3）

1. `portrayal.schema.json` 加性新增可选 `component_definitions`（数组，元素引用 component-definition），承载模板声明/预设。本批保持 6 个业务合同槽位，不据此限制全部包文件数量。
2. 审查并补齐在研 `compiler/component_registry.py`，**不并列建立第二套注册权威**。受信注册确定通用 type/implementation → 允许的严格参数 Schema、已实现结构模式、单位域与必需后端能力；场景词汇、配色、字号等设计预设不进入该注册。
3. 模板引用已登记机制；精确解析组件 id/version/digest（未知 → `COMPONENT_REF_UNKNOWN`，漂移 → `COMPONENT_REF_DRIFT`）。模板自报 `parameter_schema` 必须符合受信绑定，结构/单位只能收窄，后端声明不能省略机制必需项；禁止任意 Schema 注入或动态 import。
4. 实例按**受信注册决定的 Schema**校验，再验证模板收窄约束及 type/structure/unit 一致性；不得直接信任 `definition["parameter_schema"]` 选择验证器。`numbered-stop-marker` 等类型须有正确的严格参数协议，不能误用卡片 Schema 换取表面通过。
5. 后端支持使用类型化判定：`backend_registry` 的 renderer_id / family / geometry / export_formats 分属不同语义，不混成任意字符串集合。首批可登记明确 renderer ID 与组件模式支持矩阵；如需箭头/卡片/字体适配等特性，先定义受信能力词表并绑定实际实现。模板只提出要求，不能自证后端支持；不 import `adapters`（C2）。不支持 → `COMPONENT_BACKEND_UNSUPPORTED`。
6. `component-definition.type` 加性新增 `page-furniture` 并提供受信实现与严格参数协议；`design-instances.components` 复用 map-plan 组件形状，要求 `component_ref` + `structure_mode`。作者发射 information-card / linked-label / double-outline / classified-route / numbered-stop-marker / page-furniture 的声明与精确引用。

**测试**：未知参数、错配 Schema（尤其选择 `common` 绕过严格校验）、缺引用、摘要漂移、类型不一致、声明放宽结构/单位、删掉必需能力、虚报后端能力全部拒绝；支持的合法实例通过。受信机制规范已登记但尚未实现的模式先按 roadmap 分类；模板自创未登记模式或放宽验证仍属 forbidden，不能把二者混同。新增 Schema 同步合法/非法 fixture（C4）。

### B1.4 内容选择与放置选择真正生效（F11 / F8）

- `content.card.fields` 成为卡片行构造的唯一开关；删除 `show_arrival_time` 缺省 True。缺失数据策略显式登记：**可选字段缺值即省略该行**，必需字段由场景内容合同校验，不得编造。
- `annotations[id].placement`：`preferred` 进候选；`fixed` → `_place(explicit=True)`，且 `_solve_annotations` **把 fixed 项移出可动 items、作为 hard_boxes 参与避让**，结果不得改写 fixed。
- 数据 `callout-offset-x/y` 不自动解释成 fixed（映射 X09）。**Q1 推荐**：允许显式采用场景/项目的“源偏移解释策略”，限定数据来源、版本、单位与适用范围，并进入 plan/来源记录；已声明 fixed 的来源可批量机械转换，无须逐点重问。历史语义不明则澄清或经显式作者迁移决定，不能因数据存在就推定 fixed。
- 实例 placement 与源偏移声明冲突时明确拒绝并请求选择；不得暗中确定优先级。源策略不得改变路线或锚点事实。

**测试**：preferred 可移动、fixed 不移动且参与避让；已声明源策略可复现，语义不明/作用域不符/冲突不得自动 fixed；去掉 `arrival-time`/`distance-km` → 对应行消失；缺失可选数据省略，缺必需数据拒绝。

### B1.5 后端零默认（F8 / F9 / F10 / F13 / I7）

| 位置 | 改法 |
|---|---|
| `image_page_renderer.py:378-388` | `radius_px`/`font_size_px`/`edge_color`/`text_color` 缺失 → `IMAGE_GRAPHIC_APPEARANCE_MISSING` |
| `frontend_canvas.py:140,165,192-194` | `width_px`/`leader_width_px`/`offset_*_px`/`font_size_px` 同上 |
| `image_layout.callout_text:178-181` | 行高由实例提供，缺失即拒绝 |
| `image_layout.furniture_font_pt:30` | `fit_mode`/`min_pt` 由 `page-furniture` 组件参数提供；**名义字号兜底（title 18pt / 其他 9pt）一并删除**，名义值必须来自 `page-title`/`source-notice` 角色 |
| `image_layout.legend_font_pt:59-75` | 图例名义上限 3mm 与下限 3pt 也是硬编码设计值 → 由 `page-furniture` 参数声明（X07 图例名义字号） |
| `image_layout.frame_border_rects:77` | `surrounds` 由 `double-outline` 参数提供 |
| `style.py:240-241` | 删除卡片文字色 `#FFFFFF` 缺省 |
| `contract_migration.py:83,87` | 删除"发明默认值" |

配套加性 Schema 扩展（闭合）：`role-appearance.font.line_height`；`double-outline-parameters.surrounds`（当前仅 `placed-map-content`，`view-frame` 走 roadmap）；新增 `page-furniture-parameters.schema.json`（`title.fit_mode` / `source.fit_mode` / `min_pt` / `legend.max_pt` / `legend.min_pt`）。

**补齐 A/J 的具体归属（不是重做 46 字段映射）**：

| 字段组 | 规范权威 | 实现要求与反例 |
|---|---|---|
| M10/M11 箭头尺寸、间距 | A / Style 外观 | 核对外观合同的明确来源；J 若保留数值，只能是由 A 及 U 得出的派生副本。禁止在 `components.parameters` 再给独立可修改值 |
| M44–M46 图框线宽、间隙 | A / Style 外观 | 保持物理单位与单一 A 来源；J 负责 double-outline 结构及 surrounds，不独立覆盖同一外观值 |

逐项形成“合同字段→来源引用→确定性推导→消费者→摘要”记录；若现有 role-appearance 不能完整表达上述值，先扩闭合外观合同并做版本决定。**存放在 J 不等于 J 有权决定外观**。测试改变 A 后两端同步、伪造/改写 J 派生副本拒绝，且旧基线像素不变。

**C7 指纹核验**：除 `image_layout.py` 变更导致的 `renderer_code_digest` 漂移外，新增/修改的解析器、组件注册、Schema、场景消费者和前端验证路径逐项核对所归属的代码/协议指纹；缺覆盖须补齐并加漂移测试。不能只更新已有六文件清单中的一个文件就宣称新依赖全部冻结。

### B1.6 通用图例样点与分组点编码分离（F7 / M06 后半）

- `numbered-stop-marker` 的通用图例样点 `color` 基线为 `#403B96`（等于旧 default 组色），图例“行程点”从该角色取色，保持基线像素不变。
- **图上行程点仍由所选分组角色着色**，同组点与卡片色一致，不同组色约束不变。修改通用图例样点色不能暗中改变全部地图点。
- `group_resolution.fallback_group` 只决定缺失分组时采用哪个已声明组，不决定通用图例色。

**测试**：改 fallback_group 只影响需要回退的点，不影响明确分组点及通用图例；改样点角色色只改通用图例样点；改具体组角色色则该组点/卡片同步。若将来重设计分组编码，须单独批准，不能再宣称与旧基线字节等价。

### B1.7 有效设计快照落盘与完整一致性复验（F15 / I4）

1. 编译器写 `.carto/image/design-instances/<digest>.yaml` 不可变产物，协议区分：
   - **采用来源**：A 合同精确引用、plan 的 I/J/N/V、归一化累计请求/段选择、组件/规则引用、数据证据与显式源偏移策略；记录 scenario 预设 / 段替换 / 项目选择 / 数据来源及作用域。
   - **机械派生**：U、scale、单位域、各点 placement 与有效值；逐项可追溯到采用来源，不可被独立修订。
   - **绑定**：plan、采用合同、请求/修订、准备数据及必要派生输入的精确引用/摘要。具体形状经严格 Schema 与版本决定，不因嵌进资源就跳过协议治理。
2. 资源仍采用现有 `scene.resources` 的 `kind: contract`、`digest_mode: canonical-json`、artifactRef，并同步 `execution.resolved_assets`。文件名及 artifactRef 使用文档 canonical JSON 摘要，读取 YAML 后按同一算法复验。
3. **不比较 YAML 原始字节 SHA-256 与 canonical JSON SHA-256 是否相等**。前者是 `file_digest`，后者是 `sha256_digest(document)`，二者不同。如还要求字节身份，必须另行定义独立 byte hash 的协议位置/版本/消费者；本批不暗加不受支持的 ref 字段，也不宣称已有字节级合同资源门。
4. `verify_request` 校验资源存在、Schema 合法、canonical digest、全部来源引用及作用域，并对**完整归一化采用选择及全部派生绑定**做一致性验证；通过共享确定性解析复算或等价完备验证，不只抽查颜色/卡片/fixed。失败 → `IMAGE_SCENE_DESIGN_INSTANCE_DRIFT`。复验不执行新的设计选择或自动优化，不改冻结对象。
5. 快照是既有 plan/合同的不可变解析证明，不是第二个可修改计划。图例色、卡片行集合、fixed 偏移仅为反例测试样本，不代替完整校验。

**测试**：canonical 相同的合法序列化按声明模式处理；值漂移、任一采用字段/来源/引用/作用域/派生绑定被改均拒绝；换文件字节但未换语义不应被误称为 canonical 漂移。精确字节约束如获批准，另测其独立门。

### B1.8 前端业务词汇归位（F6 / X08）

`_PERIODS`、`"出发点"/"返程点"/"行程点 N"`、`props.get("map_role"/"stop_name")` 全部改为：业务文本走 `content_contract`；字段读取走请求 `field_bindings`；分组判定走同一 `group_bindings` + `group_resolution`。

**测试**：改文案 → PDF 与 map_json 同步；改字段绑定名 → 两端同步；加一条源码守卫断言前端不再出现独立业务常量。

### B1.9 MapPlan 成为实例选择的真实载体（F14 / I8，从事项 4 提前）

1. `RoutePlanner.build` 产出：`components` / `annotations` / `content` / `group_bindings` / `legend_labels` / `group_resolution` / `basemap_display`（键为视图 id，基线 `main-view`）。
   - **`annotations[id].anchor_ref` 语义裁决**：领导调研注记实例按组件类别（card / support-label）建立，不是逐停靠点。`anchor_ref` 指向**已准备好的 route-stops 数据集 artifactRef**（来自 bundle `role_bindings`），表示"锚点事实的来源"；逐点锚点仍在编译期由投影机械推导。此裁决写入 Schema description 与测试。
   - `component_ref` 与 portrayal 中的定义引用一致（同一 `{id,version,digest}`）。
   - plan **不携带外观值 A**：A 来自 Style 合同（B3 后是 Style 段），避免第二份外观权威。
2. `RouteCandidateCompiler.compile` 从 **plan** 读 I/J/N/V，与精确合同 + 当前累计请求选择确定性归一化的完整结果逐字段比对；同时验证来源、引用及派生关系，不一致 → `PLAN_DESIGN_INSTANCE_DRIFT`。归一化不得丢字段、重选设计或改变作用域。
3. `execution.thematic_plan_ref = artifact_ref("map-plan", plan)`（字段已存在于 `executionSnapshot`，general 场景已在用；领导调研补上即形成 plan↔candidate 摘要绑定，**无需新协议字段**）。
4. B1.7 落盘产物记录 A（合同）+ plan 实例 + 解析结果及输入引用，沿 execution/资源链核对精确摘要，采用有向无环依赖，不能要求各对象互相包含对方摘要形成循环。
5. **多候选路径必须显式拒绝**（本次核对新发现）：`map_generation._compile_variant_set` 只构建**一份共享 plan**，而 `MapCandidateCompiler.compile_variants:336` 对每个 variant 单独 `apply_overrides`。一旦编译器改为"从 plan 读实例"，多候选就会读到基线实例而忽略各 variant 的设计——这正是"字段接受了但不生效"的翻版。因此领导调研在 `validate_body` 显式拒绝 `design_variants`（roadmap `leadership-multi-candidate`，先在 G-A0 登记，逐候选 plan 留待 P5），待"逐候选 plan"落地后再开放。通用场景的同一问题属 P5，本轮不改。

**测试**：planner 产物通过 map-plan 校验；篡改 plan 任一实例字段 → 编译拒绝；篡改落盘实例 → 渲染前拒绝；`execution.thematic_plan_ref.digest == sha256_digest(plan)`；无实例字段的旧 plan 不被静默接受。

### B1 既有测试改写清单（必须改写，不得放宽）

以下按初稿记录列出旧测试，实施前与当前在研修改重新核对。断言旧机制的测试须改成断言新机制，不能删掉了事：

| 测试 | 现状断言 | 改写方向 |
|---|---|---|
| `test_p6_unit_geometry_validation.py:253` | `assertIs(style.symbol_scale, image_symbols.symbol_scale)`（场景与共享用同一函数） | 改为断言 `style.py` **不再做任何缩放**，缩放只发生在解析入口；单一权威的性质保持 |
| `:227-236` `test_shared_symbol_scale_matches_legacy_formula` | 调用无参 `symbol_scale(window)` | 显式传采用规则；等价性对基线规则仍成立 |
| `:271-287` 基线规则相关 | 从 `compiler.image_symbols` 取 `BASELINE_MEASUREMENT_RULE` | 改从作者/合同取；内核只剩机制 |
| `test_p6_acceptance.py` 多数用例 | 直接传旧 `STYLE` dict 给 `apply_grouped_style` | 改为传已解析角色视图；保留"非基线正反例"的语义 |
| `test_leadership_visit.py::StyleOverrideTests` | 旧 `style_overrides` 合并语义 | B2 改为 `design_overrides` 抽屉语义 |

若 `scale_symbol_px` / `scale_symbol_dict` 改造后无人消费，一并删除，不留死代码（同步测试）。

### B1 退出门

```bash
python -m pytest skills/carto-agent/scripts/tests/test_leadership_visit.py \
                 skills/carto-agent/scripts/tests/test_p6_acceptance.py \
                 skills/carto-agent/scripts/tests/test_p6_consumption.py \
                 skills/carto-agent/scripts/tests/test_p6_unit_geometry_validation.py \
                 skills/carto-agent/scripts/tests/test_schemas.py \
                 skills/carto-agent/scripts/tests/test_capability_roadmap.py -q
python -m pytest skills/carto-agent/scripts/tests/test_layer_ports.py \
                 skills/carto-agent/scripts/tests/test_encapsulation.py \
                 skills/carto-agent/scripts/tests/test_digest_coverage.py \
                 skills/carto-agent/scripts/tests/test_scenario_boundary.py -q
```

四项边界棘轮**只紧不松**：若任一守卫需要新增豁免，视为设计错误，回到方案讨论而不是加白名单。

---

## 五、批次 B2：新合同无损修订（事项 2）

> 退出判据：**只修改颜色，组件结构、内容选择、fixed 注记、分组绑定、底图参数和度量规则引用保持不变。**

### B2.1 新修订词汇 `design_overrides`

新增 `schemas/leadership-design-overrides.schema.json`（闭合，全部可选但至少一项）：

```text
appearance:       { <visual_role>: <role-appearance 允许通道的叶字段补丁> }
components:       { <instance_id>: { parameters: <受信组件允许的参数补丁> } }
annotations:      { <instance_id>: { placement: <完整 annotation-placement> } }
content:          { card: {fields}, numbering: {display_order} }
group_bindings:   [ ... ]        # 整体替换
legend_labels:    { <group>: <label> }
group_resolution: { fallback_group }
basemap_display:  <完整 basemap-display>
```

**补丁是闭合路径操作，不是任意 deep merge，也不是任意父对象整值替换**：

- `appearance.<role>.font.size` 只替换 size，保留同级 weight/其他已采用通道；只允许现存角色与该协议声明的可调路径，新增角色属于 Style 设计。
- `components.<id>.parameters` 按该受信组件登记的可调叶路径应用，然后整体过参数 Schema；禁止补丁独立覆盖 A 所有的派生外观副本（M10/M11、M44–M46）。
- 数组（group_bindings、fields、display_order）整体替换；placement 与 basemap_display 按完整对象替换。未知路径、未知角色/实例、缺字段的完整对象均拒绝。
- **连续修订以当前已采用选择为基准**，在新运行修订版本中保存归一化累计补丁及其来源，不以模板初值反复重建、不以第二次补丁覆盖第一次全部补丁。新请求进入既有摘要/审批链，不原地改旧请求或快照。
- 首批“恢复基线”使用显式值：从当前精确选定模板/段读取目标值，形成普通明确补丁，经相同审批/校验；不存在通过省略、null 或删除键隐含恢复。未建立专门 reset 协议前，reset 操作拒绝。
- 未提及路径在规范化选择中逐字段/规范化字节保持不变；不要求整个新文档或摘要不变。

### B2.2 请求与修订接线（含版本决定）

- `leadership-visit-generate-request.schema.json` 新增 `design_overrides`、移除 `style_overrides`；非加性变更，`$id` 升 v2（文件名/注册名不变），同步引用方与合法/非法样例。
- 共享 `design-revision-proposal.schema.json` 仅加性新增 `changes.design_overrides`；保留 deprecated 的 `style_overrides` 词汇，但领导调研规则移除该键，走 `LEADERSHIP_REVISION_UNKNOWN_KEY`。共享词表最终清理另做版本决定。
- `revision.rules()` 新增 **`design_overrides: ("plan",) + _COMPILATION_NODES`**，至少失效 plan/candidate/preview/preflight/scene。`revision_graph.compute_invalidation` 不自动推导 plan，须测试实际节点集合和重规划路径。
- 设计补丁不进 `bundle_input_keys`；数据证据是否复用由运行时 digest 门复核，不能仅凭静态分类保证。
- 场景修订器按 B2.1 累积补丁；`request_contract.apply_overrides` 在采用实例上直接作用并全量校验，不再通过 `resolve_effective_style` / `migrate_image_itinerary` 往返。
- `migrate_image_itinerary` 仅用于离线作者迁移，不在运行链调用；沿用既有修订状态机，不新建并行机制。

### B2.3 宿主侧同步

`services/itinerary-tools/request_scaffold.py` 不产旧键；宿主改样式走 `design_overrides`。提供显式可审核的离线 `migrate_style_override(old_patch) -> design_overrides`，不运行时兼容转换。

### B2.4 测试

- 保真：改颜色不改变结构、内容、fixed、组绑定、底图参数或规则引用；改 font.size 保留 font.weight；未触及子树规范化字节不变。
- 连续修订：第一次换色，第二次改字号仍保留新色；重复修订结果确定；显式恢复基线仅影响指定路径，null/未登记 reset 拒绝。
- 生效与反例：宽度/placement 模式实际生效；未知角色/组件/路径/参数、越界、悬挂绑定、只有 mode 的 placement 全拒绝。
- 失效与全链：确认 plan 重建，新 plan/解析快照/候选绑定一致；新 G1 → 重规划/编译/预览 → 新 G2 → 冻结 → 渲染 → 交付。数据证据未漂移才复用，漂移仍拒绝。

---

## 六、发布与版本切换门 G-A（工作清单第八节 + C5 / C8 / C9）

> G-A0 前置规格、分支所需登记与评审；G-A 验收实际证据并决定正式发布/版本切换。二者不能互相替代，本文不代表 steward 已批准。

### G-A.1 协议演进记录

实施时新增 `doc/plan/protocol-evolution-design-instances.md`，与 segment_refs 演进记录同规格；本次文档修订不创建该产物。至少包含：

1. **逐协议版本决定**：区分形状加性、收紧与语义变化，不以“新增字段”自动推定兼容。
   - 加性候选：portrayal 的规则/组件声明、page-furniture 类型、行高与 surrounds、共享提案 design_overrides、新参数/补丁 Schema；逐一检查旧消费者是否会接受但忽略。
   - 明确非加性：领导调研请求移除 style_overrides（`$id` v2）、components 收紧、组件验证器受信绑定、创建请求允许版本切换；确定相应 `$id`/包版本与失效边界。
   - 解析快照的来源/派生分区、Q1 源解释策略及 A 外观补齐也须严格协议；artifactRef 可复用不等于其指向内容无需版本治理。
2. **生产者—消费者清单**：每项列作者/planner/修订器、校验器、编译器、PDF/前端、回放者、一致性门、错误码；包括完整身份版本链。
3. **摘要影响清单**：请求/提案、plan、采用合同/段/组件/规则、准备数据、解析快照、scene、execution、锁及回执的有向依赖；明确 canonical 与 byte hash 各自用途。新增代码/Schema/验证依赖的指纹覆盖逐项证明。
4. **四类影响**：代码指纹变化 / 公共协议升级 / 策略语义变化 / 披露字段变化。本案模板版本策略语义变化会使依赖该策略摘要的既有冻结执行漂移，不自动迁移；不把所有变化混为一次代码重构。
5. **旧运行处置**：旧包/锁/回执不改写，不兼容的旧请求/提案 fail-closed；旧运行先完成或按 doctrine 新建/重新冻结。说明离线重新作者化和新运行路径。
6. **未闭合项**：共享 deprecated style_overrides 清理、独立组件注册发布（T1 未开放）、CapabilityContext 持久化、B3 验证宿主与 M2/M3 等。

### G-A.2 能力缺口清单与最终复核（登记前置到 G-A0）

以下为拟新增条目；实施时确认没有已存在/已交付同义项，按真实阶段登记 planned/backlog，守卫与条目在同一受评审变更交付：

| feature id | 合法但未实现的选择 | 边界 |
|---|---|---|
| `symbol-physical-units` | 符号域 pt/mm | 不包括已支持的页面家具物理单位 |
| `symbol-multiple-measurement-rules` | 一次编译采用多个明确有效 U | 未知引用/摘要漂移仍为 forbidden |
| `border-surrounds-view-frame` | 合同已定义的 view-frame 模式 | 不是把任意未知 surrounds 值也当合法缺口 |
| `card-explicit-subcontent` | 合同已定义的显式子内容布局 | D4 第二种组织方式 |
| `style-parameter-level-override` | B4 选中独立 Style 后逐参数覆盖外观 | 不禁止 B2 当前内嵌外观的已登记补丁；需明确阶段/来源边界 |
| `leadership-segment-composition` | B4 前的领导调研 segment_refs | 把当前裸拒绝转为可分类缺口 |
| `leadership-multi-candidate` | 领导调研 design_variants | 等待逐候选 plan，不能默默复用共享 plan |

已定义但未实现的合法选择须能到达对应 roadmap 守卫；Schema 与守卫层次应协调，不能前面只报泛化非法枚举、后面却宣称返回 not_implemented。未知字段/枚举、越权、非法范围、伪造引用/摘要、任意放宽验证仍属 forbidden。

交付能力时同时更新真实状态并移除未实现守卫；否则会触发 `ROADMAP_FEATURE_DELIVERED`。G-A 验证真实策略与代码配套，不用 mock 证明登记齐备。

### G-A.3 完整版本链与策略切换

首批拟 `leadership-visit-map@1.0.0 → 1.1.0`，B3/B4 后拟 `1.2.0`，版本决定及身份链统一评审：

| 生产/校验点 | 必须同步的内容 |
|---|---|
| `route_author.VERSION`、包 manifest/identity/layout 与精确引用 | 新版本及由内容变化产生的新 digest；不硬改旧已发布包 |
| `leadership-visit-template-create-request.schema.json` | 当前 version const 1.0.0 必须随已批准的新作者协议调整，并记录版本决定；否则作者升级但请求入口仍拒绝 |
| 作者 profile、场景合同检查、其他身份常量/引用消费者 | 逐点检索、确认接受范围与拒绝范围，不能只改 VERSION |
| `scenario-capabilities.yaml` 模板版本 | 策略语义变化，唯一 steward（当前 CODEOWNERS：`@liudakemgslab`）评审；生产限制不放宽 |
| 合法/非法 fixture、生命周期测试、宿主样例及相关说明 | 新版本全链通过，旧版按切换规则拒绝；历史已发布证据不改写 |

在隔离、已有旧版本的验证仓库演练：同 id/version 不同 digest → `VERSION_CONFLICT`；新版本创建请求→作者→验证→TP→发布全链成功；旧包字节不变且仍可 discover，切换后旧版编译按准入拒绝（如 `CAPABILITY_NOT_AVAILABLE` / `SCENARIO_CONTRACT_MISMATCH`）。不得只测作者生成而漏掉创建请求 const。

旧项目路径：显式重新作者化 → 验证 → 发布 → 新运行，行程数据可在宿主层依法复用；旧锁不原地升级。G-A 通过后才允许经批准的正式版本切换，不将本文当作授权。

### G-A.4 验收证据收口

- 固定实施完成时 commit、工作区差异/状态及关键文件 SHA-256；当前仅能确认 HEAD `7e3ebb9` 且工作区有改动，不能拿 HEAD 单独标识验收代码。
- 记录真实解释器、依赖、命令、通过/失败/跳过及耗时；初稿结果不充当本轮回归。
- 支持矩阵列组件类型、参数、单位、结构、Layout、后端、验证宿主及证据覆盖；未验证项不写已支持。
- 更新验收包及协议记录，环境跳过不计通过；四项棘轮不加豁免。

---

## 七、批次 B3：独立 Style/Layout 资产（事项 3，默认待批）

### B3.1 Style 段承载角色外观（I6 / F17）

- `style.schema.json` 加性新增可选 `role_appearance: { <role_id>: role-appearance }`（闭合）；
- 作者 `embedded.style` 改为携带完整 `role_appearance` 的 Style 合同；v2 必填字段给登记值，**未被消费的 `typography` 等字段不得覆盖实际参数**（写进测试）；
- `portrayal.design_instances` 去掉 `style_roles`，新增 `required_appearance_roles`；
- 有效外观唯一来源 = **经所有权解析后采用的 `Style.role_appearance`**；可以来自 embedded.style 或精确 Style 段引用，二者互斥，消费者不硬编码只读 embedded。

### B3.2 兼容验证宿主先行，再发布两份 Style + 两份 Layout

拟沿用 `segment_authoring.author_segment_package` + `SegmentCreationWorkflow` 发布 Style `leadership-visit-blue@1.0.0` / `leadership-visit-ink@1.0.0`（组色互异，F21），Layout `leadership-a3-landscape@1.0.0` / `leadership-a3-landscape-wide@1.0.0`（相同内容接口、不同几何/容量）。**发布的前置证据必须覆盖资产对外声明的能力**：

1. 当前通用 raster 宿主不消费领导调研 `role_appearance`，不能仅写 limitations 就把该外观能力当作已验证后发布；B4 后补渲染不能追溯成为此前 TP 所绑定的发布证据。
2. **首选路径**：在 B3 独立受控工作包中提供兼容图像/领导调研组件的验证宿主与准入接口，真实消费同一精确 Style/Layout、组件与合成样本，验证外观生效、角色覆盖、组色、内容接口及容量。不得把领导调研伪装成通用专题或绕开场景边界。
3. 固定样本、段 digest、宿主/环境、渲染结果、形式检查及设计审阅结论，纳入现有验证→TP→发布摘要链。必要的宿主策略/协议变更单独评审；沿用既有流程，不另建发布状态机。
4. 如选择部分验证后发布，必须先有**正式的验证覆盖范围/使用限制协议及消费者强制执行**，并限制未验证能力的使用。单纯 limitations 文本不是强制门；没有该协议则保留草稿，不发布为领导调研可用 Style。
5. 通用 Layout 可按实际声明范围使用合适宿主；宣称跨场景可用还须 B4 两条真实链的证据。宿主增量不复用已 delivered 的 `segment-validation-host` 未实现守卫，须按真实范围登记缺口。

**范围控制**：宿主工作不进入首批 B1/B2；B3 开工前确认方案，未闭合则阻断该资产发布，而不是取消验证。B4 组合验证仍单独执行，不能替代发布前验证。

### B3.3 Scenario 改为业务合同 + 默认组合来源

`segment_refs` 与 embedded 互斥（`OwnershipResolver.validate_segment_refs` 已强制）；`replaceable_segments: ["style","layout"]`；`compatibility` 声明所需容器与角色。

---

## 八、批次 B4：请求级组合全链 M1（事项 4 其余，默认待批）

1. **按证据解除拒绝**：复用 `load_contracts(segment_refs=)`，不建第二套 override 引擎。实现、`SEGMENT_SELECTION_UNSUPPORTED`/roadmap 守卫调整与状态变更在隔离实施分支成套测试；只有 B3 发布证据和本批组合验收闭合后才正式开放，不在主线提前宣称 delivered。
2. **执行绑定**：`contracts["segment_selection"].refs` 写入 `execution.template_refs` + `ownership`；内核 `_require_selection_binding` 自动生效。
3. **以前批验收为前提**：复用 B1.9 实例生产者，让 planner/编译器消费替换后的 Style 和请求实例化；A 仍来自 Style，plan 不成为第二外观权威。
4. **联合兼容性检查**（编译前拒绝，点名缺什么）：

| 检查 | 错误码 |
|---|---|
| Style 未覆盖 `required_appearance_roles` | `STYLE_ROLE_COVERAGE_MISSING` |
| Layout 缺唯一 map frame 或缺 title/legend/source | `LAYOUT_CONTENT_INTERFACE_MISSING` |
| Layout 容量不足 | `LAYOUT_CAPACITY_EXCEEDED` |
| 组色重复 | `STYLE_GROUP_COLOR_CONFLICT` |
| 组件后端能力不足 | `COMPONENT_BACKEND_UNSUPPORTED` |

5. **修订**：`revision.rules()` 增 `segment_refs: ("plan",) + _COMPILATION_NODES`。
6. **验收**：真实全链 ×4（默认 / 换 Style / 换 Layout / 同时换）；证明换 Style 不改业务事实、换 Layout 不丢必需内容、不兼容明确拒绝、**新增兼容模板无需改场景 Python**。
7. **真实跨场景验证（工作清单 §8.2）**：同一份已发布 Layout 引用**分别进入 general 与 leadership 两条真实生成链**并交付，不是重复调用 `LayoutResolver`。
8. **安全反例（§8.3）**：未选择组件、摘要漂移、**错误作用域（tenant/project/subject 不符）**、未知参数、规则引用漂移、**恢复路径（retry/recovery 后重验同一选择）**。
9. **范围收窄**：独立 Style 模式只允许“整段替换 + 非外观实例修订”；外观参数级覆盖走 roadmap。切换到该模式时不得把 B2 累计 appearance 补丁静默丢弃或带入；存在冲突就拒绝并要求显式选择/重建，重新绑定 plan 与审批。

---

## 九、M2 / M3 骨架（事项 5、6；本方案不执行）

| 里程碑 | 关键改动 | 为什么单独评审 |
|---|---|---|
| **M2 需求入口** | `_REQUIRED_FIELDS` 去掉 `template`；新增"设计选择"不可变产物与 intake 规划/澄清分支；`request_scaffold` 不再以查到固定模板为前提；`resolve_generate` 支持"先业务基线、后精确组件引用" | 触及公共请求协议 + 状态机 + 能力解析（`resolve_generate` 依赖 template 身份），属 P3b 邻域 |
| **M3 类型化检索** | `match_cmd._resolve` 传入真实能力与输出上下文（不再固定 general 档案 / 300 DPI）；事实提取扩到 `role_appearance`；区分不兼容/未知/搜索不完整/无匹配；明确采用后进入 M1 链 | 依赖 M1 已验收；检索只作建议，不得成为选择权威 |

---

## 十、与工作清单逐条对照

> 本表只表示**计划覆盖范围**，不表示实现或验收完成；首批须先通过 G-A0。实际完成状态仅由执行清单及所绑定证据确认。

| 工作清单要求 | 本方案落点 | 首批覆盖 |
|---|---|---|
| 事项1-1 完成度量解析 | B1.1 | 纳入首批 |
| 事项1-2 完成显式角色绑定 | B1.2 | 纳入首批 |
| 事项1-3 接通组件定义校验 | B1.3 | 纳入首批 |
| 事项1-4 核对内容与放置选择 | B1.4 | 纳入首批 |
| 事项2 修订按归属分别作用、旧形状仅单向派生 | B2.1–B2.3 | 纳入首批 |
| 事项3-1 Style 包承载角色化外观 | B3.1 | 待批 |
| 事项3-2 独立 Layout 包 | B3.2 | 待批 |
| 事项3-3 Scenario 改业务合同 + 默认组合 | B3.3 | 待批 |
| 事项3-4 合法版本发布（旧版本仓库演练） | G-A.3（首批即演练一次） | 纳入首批 |
| 事项4-1/2/3 受信解析 + 唯一有效设计 + 来源分清 | 第八节 1–2 + B1.7 来源标记 | 待批（来源标记纳入首批） |
| **事项4-4 实际规划生产者填写实例** | **B1.9** | 纳入首批（本次提前） |
| 事项4-5 扩展选择一致性门 | B1.7 + B1.9 + 第八节 2 | 部分纳入首批 |
| 事项4-6 segment_refs 修订与重预览冻结 | B4.5 | 待批 |
| 事项4-7 完成后才解除拒绝 | B4.1 | 待批 |
| 事项5 / 事项6 | 第九节骨架 | 单独评审 |
| §8.1 固定代码快照 | G-A.4 | 纳入首批 |
| §8.2 真实跨场景验证 | B4.7 | 待批 |
| §8.3 修订与安全反例（含作用域/恢复） | B2.4 + B4.8 | 部分纳入首批 |
| §8.4 版本切换演练 | G-A.3 | 纳入首批 |
| §8.5 更新支持矩阵 | G-A.4 | 纳入首批 |
| §9 执行顺序 1→2→3→4→5→6 | 第一节路线（4-4 提前） | 纳入首批 |

---

## 十一、测试与验收矩阵

以下为实施阶段要求，本次修订未执行这些测试；所有样本均用合成数据，不引入真实敏感行程。

| 批次 | 必跑/必核 | 退出门 |
|---|---|---|
| G-A0 | 工作区/解释器快照、接口裁决、真实 roadmap 条目与守卫配套 | 规格及治理前提齐备，不用 mock 掩盖登记缺失 |
| B1 | leadership / p6_acceptance / p6_consumption（新）/ p6_unit_geometry / schemas / capability_roadmap + 四项守卫 | 基线像素等价；非法验证器/虚报能力拒绝；单位仅转换一次；完整选择/来源/派生绑定一致；合法缺口正确分类 |
| B2 | 上述 + design_revision / request_contract | font.size 不丢 weight；连续修订保留前次选择；plan 失效并重建；全链新 G1/G2 与证据复核 |
| G-A | leadership::TemplateLifecycleTests（含旧仓库、新创建版本全链）/ doc_examples / 指纹覆盖与漂移 | 治理记录、生产消费版本链、steward 评审及全量回归齐备；旧包不改写 |
| B3 | segment_refs / reference_segment / layout_contract + 兼容宿主真实消费 | 两 Style/两 Layout 在声明范围内真实验证并绑定 TP 后发布；宿主未闭合不发布 |
| B4 | P4ProjectCompositionTests 领导调研扩例 + 四组合全链 + 真实跨场景 | 换段事实不变、不兼容拒绝、新兼容模板零场景代码；恢复与作用域反例通过 |

**必须覆盖的评审反例**：宽泛 `common` Schema 绕过、模板放宽结构/单位/后端、多个合法 U 与非法引用的分类、数据偏移擅自 fixed、图例样点色污染组色、A/J 双外观权威、canonical/byte hash 混用、漏绑来源、第二次修订丢第一次、只改作者版本不改创建 Schema、未验证外观提前发布。

**全量回归**：实施将触及共享适配器、公共 Schema、摘要绑定及策略语义，按 `AGENTS.md` 升级全量；以下 `python` 须替换为 G-A0 核实的解释器：

```bash
python -m pytest skills/carto-agent/scripts/tests/
```

局部通过不等于全量通过，跳过不计通过。初稿的 92/10 passed 仅历史参考；验收须保存本次实际命令、环境、代码快照及完整结果。

---

## 十二、风险与回退

| 风险 | 处置 |
|---|---|
| 模板自选验证器或虚报实现能力 | 受信机制固定验证边界，模板只能选择/收窄，反例测试锁定 |
| roadmap 条目后置，测试误报未登记 | G-A0 前置成套评审；G-A 复核交付状态，禁止 mock 掩盖 |
| 多次补丁丢选择、plan 未失效 | 闭合叶路径 + 累计基准 + 显式 plan/编译节点失效 |
| 度量双换算或 A/J 双权威 | 单位接口表与 A 来源链逐项证明；基线像素等价，禁止夹带新设计 |
| 旧数据偏移擅自被解释为 fixed | 显式源策略或澄清，记录范围/版本/来源；不能为兼容数据偷设语义 |
| 移除默认后缺字段 | 作者/合同显式补齐，后端不得恢复兜底 |
| 资源摘要算法混用、只抽查少数字段 | canonical 模式统一，byte hash 若需另立协议；完整绑定复验 |
| 版本升级后创建 Schema 仍拒绝 | 全身份链同步，真实创建→验证→发布演练 |
| 旧实例/请求/冻结环境失效 | 记录非加性变化和指纹影响；旧包不改写，新设计新运行，不自动迁移 |
| 宿主不消费角色外观却发布 Style | B3 兼容宿主/强制覆盖协议先行，否则保持草稿；不让 B4 倒补 TP 证据 |
| 新模块违反边界或重复在研实现 | 复用并审查现有组件注册；内核登记通用机制，场景预设随包走；棘轮不加豁免 |
| 范围过大、并行修改互相回退 | 首批仅 G-A0/B1/B2/G-A；按文件归属与独立测试拆提交，后续另批 |

**回退规则**：实施只在受控分支进行，未过退出门不合并、不正式发布。G-A0 经治理允许的分支策略修改/合成仓库演练是测试前提，不受“不改任何策略”的自相矛盾限制；未过 G-A 不激活正式版本切换，不放宽生产准入。失败回退对应子步及其配套策略，不遗留孤立守卫；不改写已发布对象，不恢复旧旁路默认。

---

## 十三、实施前待确认的裁决点

> 本次用户授权是修改文档，不自动代表以下方案、策略变更或运行审批已获批准。

| 编号 | 问题 | 修订后的推荐 | 确认与影响 |
|---|---|---|---|
| **Q1** | 数据 callout-offset 的语义 | 显式采用有范围/版本的源偏移解释策略；已声明 fixed 才机械转换，历史不明则澄清/作者迁移；与实例冲突拒绝 | 是新增语义选择，不能自动把历史偏移全部变 fixed（映射 X09） |
| **Q2** | style_overrides 去留与补丁语义 | 请求 v2 移除；共享提案保留 deprecated 词汇但领导调研拒绝；闭合路径、累计修订、显式恢复值 | 需同步请求/提案/宿主/失效规则，不能继续双通道或任意整值覆盖 |
| **Q3** | 版本与策略 | G-A 拟 1.1.0，G-B 拟 1.2.0；创建请求 const、作者、包引用、消费者、fixture 全链同步 | steward 评审和冻结漂移处置不可省；roadmap 分支登记先于 B1 测试 |
| **Q4** | 段验证宿主 | **不采纳仅写 limitations 后先发布**；优先提供兼容宿主并在 TP 前绑定真实证据，否则保持草稿 | 部分验证发布只有正式覆盖/限制协议及消费者强制门后才可选；属 B3 待批工作 |
| **Q5** | 首批承诺 | **G-A0 → B1（含 B1.9）→ B2 → G-A** | B3/B4 不作为首批已交付承诺，M2/M3 另评审 |
| **Q6** | 机制注册与模板定义位置 | 通用受信机制限定实现/验证边界；模板声明与设计预设本批放 portrayal | 不将合法的内核机制注册误判为场景默认；6 个业务槽位不等于只能有 6 文件 |

---

## 十四、执行清单

> 未勾选表示本文没有相应完成证据；不得因工作区已有部分改动直接标记整个阶段完成。

- [ ] G-A0 重钉工作区/解释器/文件归属与现有修复边界
- [ ] G-A0 确认首批相关裁决、机制/单位/补丁/摘要接口与版本影响；Q4 具体宿主方案留 B3 另批
- [ ] G-A0 roadmap 条目与守卫成套评审，在相关测试前登记
- [ ] B1.1 单一度量解析 + 明确单位输出接口 + 两端无双换算
- [ ] B1.2 显式角色绑定及任意合法角色名消费
- [ ] B1.3 受信机制/严格 Schema/模板收窄/后端支持矩阵与绕过反例
- [ ] B1.4 内容字段、preferred/fixed、显式源策略及冲突处理
- [ ] B1.5 后端零默认 + M10/M11/M44–M46 的 A 权威及派生校验
- [ ] B1.6 通用图例样点与分组点编码分别验证
- [ ] B1.7 canonical 资源快照 + 完整来源/选择/派生绑定复验
- [ ] B1.8 前端业务词汇归位
- [ ] B1.9 planner 真实生产 + plan/execution 精确绑定 + 多候选显式拒绝
- [ ] B1 退出门：受影响测试、四项棘轮、单位与基线像素等价
- [ ] B2.1 闭合补丁、累计语义、显式恢复及合法/非法 fixture
- [ ] B2.2 请求 v2、共享提案加性键、plan/编译失效与实例直改
- [ ] B2.3 宿主同步与离线转换
- [ ] B2.4 连续修订保真、生效、反例、新 G1/G2 全链
- [ ] G-A.1 协议版本、生产者消费者、摘要/指纹影响与旧运行记录
- [ ] G-A.2 roadmap 状态与守卫最终配套复核
- [ ] G-A.3 全身份链升级、steward 评审、旧仓库新版本全链演练
- [ ] G-A.4 代码/环境快照、支持矩阵与验收证据
- [ ] 全量回归，失败与跳过如实记录
- [ ] （另批）B3 宿主证据先行 → 独立资产验证/发布
- [ ] （另批）B4 四组合/跨场景/修订安全验收 → G-B

---

## 十五、本次评审修订记录（2026-11-26）

本次只修改本实施计划，不修改代码、Schema、策略或其他文档，不运行实施测试：

1. 保留 F1–F22 历史调查，补当前脏工作区与在研修复，区分历史测试报告和本次静态核对，修正相对链接。
2. 将“模板自报定义即验证权威”改为受信机制约束，明确后端能力类型与负例。
3. 前置 G-A0 解决 roadmap 登记依赖，保留 G-A 的正式发布/切换门。
4. 增加 plan 失效、闭合叶路径、累计修订与明确恢复语义。
5. 分开 canonical/byte digest，完整绑定来源与派生结果，补指纹覆盖要求。
6. 源偏移不自动 fixed；通用图例样点不擅自重定义组色；补箭头/边框 A 权威和单位转换接口。
7. 创建版本全链同步；B3 发布前补真实宿主证据，不用 B4 后验代替 TP 绑定验证。
8. 保持首批范围受控；待确认事项与勾选标准不冒充已完成/已批准。
