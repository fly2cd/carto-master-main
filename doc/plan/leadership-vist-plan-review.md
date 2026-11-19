
计划书已通读（1580 行）。评估前必须核验它引用的关键事实——计划书的可靠性取决于它对**源端**（旧框架文件清单）和**目标端**（main 框架机制）的描述是否属实。我分批取证。
核验完成。以下评估全部基于可复核的一手证据：main 仓源码/Schema、merge 仓源码、以及计划书自身文本。先给总判定，再分项列证据。

---

## 总判定

**战略方向正确，工程执行不可就绪。** 计划书在"独立能力档案 + 算法叶子复用 + 行程服务外置 + 语义合同 + 分阶段回归"这几个顶层决策上是对的；但它对**源端文件清单**和**目标端框架机制**的两端事实描述都存在可证伪的错误，且包含两处会破坏 main 失败关闭准入的红线设计。按现状执行，会在 P2 阶段撞上一连串 Schema 拒绝和治理缺口。建议**修订后再执行**，不是推翻重来。

---

## 一、站得住的部分（先给公道）

| 决策 | 证据 | 判定 |
|---|---|---|
| 独立业务场景，不并入 general | main [intent-profiles.yaml L10-14](file:///d:/IdeaProjects/github/code-reviewer/carto-master-main/skills/carto-agent/policies/intent-profiles.yaml#L10-L14) 已平级登记 `leadership_visit` | ✅ 正确 |
| 行程准备（地理编码/求路）外置 MCP，不入制图内核 | 符合 main 边界（geospatial MCP 独立服务先例）与"制图不做空间分析"分工 | ✅ 正确 |
| 复用纯算法叶子（仿射转换/白边检测/注记求解） | merge 这些模块确为确定性算法（`routing_limits.py` 硬上限、固定种子求解） | ✅ 符合 Strangler Fig 叶子提取 |
| DataPreparer 重规范化 + 精确比对防漂移 | 与 main `RASTER_CANDIDATE_BUNDLE_MISMATCH` 同文化 | ✅ 正确 |
| ToolGateway 注册三个能力 | main [tool_gateway.py L48-79](file:///d:/IdeaProjects/github/code-reviewer/carto-master-main/skills/carto-agent/scripts/carto_core/adapters/tool_gateway.py#L48-L79) 支持进程内 CapabilityHandler + 策略绑定 + scope 校验，机制可行 | ✅ 可行 |
| 语义 layout 参数替代像素 frame | 符合 design-principles §2.1/2.3 | ✅ 正确 |
| `backend_registry.py`、`roadmap.py` 存在 | glob 证实（88 行 / 72 行） | ✅ 引用属实 |

---

## 二、阻塞级问题（五项，按严重度排序）

### A. 源端清单与可访问源码脱节 —— 迁移映射的地基不实

【源码事实】计划书附录 A 引用的多个"旧文件"在 carto-master-merge 中**不存在**（glob 零命中）：

- `adapters/frontend_json.py` ❌
- `compiler/image_page_layout.py` ❌
- `packages/itinerary-contracts/` ❌
- `services/itinerary-mcp/` ❌

merge 的实际形态是：行程逻辑在**内核里**（`workflow/itinerary_structure.py` + `itinerary_import.py`），地理编码/求路是 `carto capability invoke geocoding-resolve/route-planning`，CLI 是 `normalize-itinerary` / `import-itinerary-results`——**没有独立 MCP 服务，没有"itinerary.check → geocoding.resolve → routing.plan → itinerary.finalize"四步链**。计划书 §1.3 描述的 MCP 四步链、"15 个行程 Schema"、"纯函数 normalize_itinerary 独立包"均无法在 merge 中证实。旁证：计划书称旧手册 658 行，merge 实际 704 行。

【设计推断】计划书的"IGSA_1109"应是另一个我无权访问的演化版本。**这不证明它错，但证明它未经对源核验**——迁移计划的第一义务是源清单逐文件可定位。执行前必须拿真实源仓重对附录 A，否则"整体迁移"可能迁的是不存在的文件。

### B. 目标端根本前提错误 —— 全书约束建立在一个假命题上

计划书 §1.2 断言："新框架……LLM 仅在 template authoring 阶段向 catalog 注册表达方法；运行时……不在运行时做任何设计选择"，并由此推出根本约束"所有旧版 LLM 运行时设计决策必须转化为模板合同静态声明"（§14.11 重申）。

【源码事实】两条直接证伪（前几轮已取证）：
- [design-principles.md L108](file:///d:/IdeaProjects/github/code-reviewer/carto-master-main/doc/design-principles.md#L108)："**T1 尚未开放**"——LLM 向 catalog 注册表达的能力不存在。
- [generate-request.schema.json L540-545](file:///d:/IdeaProjects/github/code-reviewer/carto-master-main/skills/carto-agent/schemas/generate-request.schema.json#L540-L545)：每个面板 `design` 是 **required**；[thematic-design.schema.json](file:///d:/IdeaProjects/github/code-reviewer/carto-master-main/skills/carto-agent/schemas/thematic-design.schema.json) 里 kind/字段/分级方法/符号颜色全是运行时选择。第一原则 L11 原文："让 LLM 选表达方法与参数，然后程序验证合法性"。

同段还把"LLM 编写 overlay SVG"安在 leadership_visit 头上——那是 government_thematic（[merge poster_compiler.py L209](file:///D:/IdeaProjects/github/code-reviewer/carto-master-merge/skills/carto-agent/scripts/carto_core/compiler/poster_compiler.py#L209) 类注释）。

【设计推断】把样式固化为模板合同**本身合法**（模板合同正是设计参数的合法来源之一），但"运行时零设计选择"是对框架的误读。危害在于：§14.11 作为禁令会误导实施者拒绝一切运行时参数，而领导调研恰恰需要运行时声明（标题、分组字段绑定、度量来源、逐点偏移）——这些在 merge 里就是请求级字段，不是模板常量。正确表述应为"运行时设计必须以闭合 Schema 参数表达"，而非"禁止运行时设计"。

### C. 四处"[不变]"被闭合 Schema 直接证伪 —— 真实改动面远大于宣称的 15 个文件

【源码事实】逐项对照：

| 计划书声称 | 源码事实 | 后果 |
|---|---|---|
| `map-plan.schema.json` [不变]，Planner 输出 `decisions.route_mode / itinerary_groups` | [map-plan.schema.json L80-104](file:///d:/IdeaProjects/github/code-reviewer/carto-master-main/skills/carto-agent/schemas/map-plan.schema.json#L80-L104)：`decisions` `additionalProperties:false`，required 五键固定，`renderer_id` enum 仅三个值（**无 image-itinerary-page**） | Planner 输出三重拒绝：未知键、缺必填、renderer 非法 |
| `portrayal.yaml` 用 `geometry: image / linestring`、`map_expression_ref: image-itinerary@1.0.0`，basemap 层无 expression_ref；portrayal schema 未列改动 | [portrayal.schema.json L88-93](file:///d:/IdeaProjects/github/code-reviewer/carto-master-main/skills/carto-agent/schemas/portrayal.schema.json#L88-L93)：geometry enum 仅 `[point, polygon]`；`map_expression_ref` 是每层 required 且 id 限定已知 catalog 条目 | 合同无法通过校验；且 template_validation 对每层跑 ExpressionValidator→catalog.require，未注册的 image-itinerary 直接失败 |
| `scenario-capabilities.yaml` 新档案 `output_profile` 无 width_px/height_px；`allowed_models: [image-native, fixed-page]`；schema 未列改动 | [scenario-capabilities.schema.json L109-114](file:///d:/IdeaProjects/github/code-reviewer/carto-master-main/skills/carto-agent/schemas/scenario-capabilities.schema.json#L109-L114)：output_profile **required width_px/height_px**；L194-197：allowed_models enum 仅 `[grid, freeform]` | 能力档案注册即被 Schema 拒绝 |
| bundle "符合 prepared-data-bundle.schema.json"（含 image 引用、route_mode 元数据），schema 未列改动 | [prepared-data-bundle.schema.json](file:///d:/IdeaProjects/github/code-reviewer/carto-master-main/schemas/prepared-data-bundle.schema.json)：全局 `additionalProperties:false`，role_bindings 是闭合 oneOf（矢量型/栅格型），无 image 引用位置 | 大概率需新增 oneOf 变体，"符合"声明不成立 |

【设计推断】这不是细节疏漏，是**改动面估算系统性偏低**。计划书"15 个修改文件"的统计至少漏掉 map-plan、portrayal、scenario-capabilities、prepared-data-bundle 四个 Schema 的演进——而 Schema 演进正是 main 里最重的协议工作（连带合法/非法用例、守卫测试、digest 棘轮）。工期与风险评估因此失真。

### D. 两处准入红线违规 —— 会破坏 main 的失败关闭底座

**D1. 放宽 REQUIRED_COMPONENTS（任务 2.2）**：计划书要在 P2 注册档案但只装 3 个组件，"REQUIRED_COMPONENTS 的 generate-map 元组暂不包含 candidate_compiler 和 legend_checker（用条件判断跳过）"。

【源码事实】[scenario_registry.py L224-226](file:///d:/IdeaProjects/github/code-reviewer/carto-master-main/skills/carto-agent/scripts/carto_core/scenario_registry.py#L224-L226)：缺组件 → `CAPABILITY_NOT_AVAILABLE`；[scenarios/README.md L31](file:///d:/IdeaProjects/github/code-reviewer/carto-master-main/skills/carto-agent/scripts/carto_core/scenarios/README.md#L31)："缺少……组件不是'跳过检查'，而是能力不可用"。

【设计推断】为分阶段交付而修改框架完整性不变量，是**把安全机制当进度障碍拆掉**。正确做法是框架自带的：**策略注册时机就是准入杠杆**——组件不齐就不把档案写进 scenario-capabilities.yaml，P1-P3 在测试态验证，P4 齐套后一次性登记。零框架改动即可实现同样的分阶段。

**D2. 模板绕过发布门禁（§4.6 + 任务 2.1）**：开发者手写 draft 模板 + 直接写 template-index，author/validation 组件推迟到 P5。

【源码事实】SKILL.md L24：发布必须验证闭合包、依赖锁、验证输入、检查器集合、**RenderReceipt、冻结样张场景**并消费精确 TP；而 validate 步骤必调 `validation_data_checker` 与 `validation_scene` 组件（[template_validation.py L491](file:///d:/IdeaProjects/github/code-reviewer/carto-master-main/skills/carto-agent/scripts/carto_core/workflow/template_validation.py#L491)）。

【设计推断】没有这两个组件，模板**无法合法发布**；generate 消费的是已发布模板。计划书 P2 就要用模板跑 brief，却把发布所需组件放到 P5，中间没有交代合法入口（main 的 dev-seed 路径也仍走 publish）。这是时序死锁，不是"后期补"能掩盖的。要么把 validation 组件提前到 P2，要么显式声明并守卫一条开发种子路径。

### E. `geometry: image` 混淆了三个轴 —— 架构上最该重议的决策

【源码事实】main 已经把图片底图建模为**参考资源而非专题数据**：
- [generate-request.schema.json L465-473](file:///d:/IdeaProjects/github/code-reviewer/carto-master-main/skills/carto-agent/schemas/generate-request.schema.json#L465-L473)：`basemap` 字段描述原文 "a reference resource (**not thematic data**)…static image with explicit georeferencing"。
- [general_vector.py L172-184](file:///d:/IdeaProjects/github/code-reviewer/carto-master-main/skills/carto-agent/scripts/carto_core/scenarios/general_vector.py#L172-L184)：矢量路径已消费底图（CRS 精确匹配 + 摘要绑定）。

领导调研的**专题数据是点+线（矢量）**，图片是底图介质，image-native 是版式模型。计划书把三者压成一个"第三几何类型"，且自相矛盾——§8.3 的专题图层自己写的是 `geometry: point / linestring`。另外 §3.3/§10 要在 `general_dispatch.py`（general-thematic bundle 的分派器）里加 image 分支委托到 leadership_visit 组件——**跨 bundle 接线**：leadership 是独立 implementation，不应出现在 general 的统一类里；给 general_dispatch.GEOMETRIES 加 image 等于让 general 能力接受 image 请求，违反"一个 bundle 一个业务purpose"的注册注释（scenario_registry.py L14-15）。

【设计推断】更贴合 main 四轴分解的方案：**geometry 仍走 vector（点/线专题）+ basemap 参考资源 + 新 layout 模型 + 新 renderer_id**。策略 Schema 的 allowed_models 已预留 `freeform` 枚举（见 C 表证据），说明非 grid 版式在框架预期内。这样 GEOMETRIES 不用动、general_dispatch 不用动、encoding IR（geometry_role 无 image）不用动，改动面显著收缩。若坚持 image 几何，则必须论证它相对"矢量+底图资源"的不可替代性，并补齐 IR/portrayal/bundle 全链枚举——计划书目前两者都没做。

---

## 三、非阻塞但必须修正（六项）

1. **终检上下文接错**：任务 4.3 的 legend_checker 读 `context["raster"]["page"]["legends"]`，但 [map_checks.py L44-55](file:///d:/IdeaProjects/github/code-reviewer/carto-master-main/skills/carto-agent/scripts/carto_core/validation/map_checks.py#L44-L55) 的 raster/vector 布尔由 renderer_id 判定，image 后端两者皆否——`context["raster"]` 不会被填充，且 legend-consistency 不会被选入必检集。selection()/inspect() 需要 image 分支，计划书只写了"注册检查器"，漏了这层。
2. **allowed_capabilities 未扩展**：ToolGateway.invoke 强制 `capability_id ∈ execution_context.authorized_capabilities`（tool_gateway.py L60-61）。新请求必须显式携带 geo-to-image-pixels / image-display-bounds / annotation-layout，计划书 §5.1 未提。
3. **风险缓解违反失败关闭**：§十二"超限时降 DPI 并记录警告"——静默降级违反 design-principles §2.2（"不允许静默降级或自动修正"）且破坏冻结输出合同。应改为拒绝。
4. **引用卫生问题**：§13 引用的 "design-principles.md §5.1 违规清单"**不存在**（该文件 134 行，仅一至四节）；"general_thematic 硬编码 EXPRESSION_ID 属 catalog 违规"定性错误——代码经 `MapExpressionCatalog.reference()` 正常引用 catalog 条目（general_thematic.py L96-97），常量只是条目名；任务 4.5 把 main 的 S2 基线"420 项 407 过 13 跳过"（SKILL.md L46）说成"旧项目回归"；§1.1 称新管线"10 步"却只列 9 步。这些与用户已知的"二手材料会说谎"模式一致，合规审查章节的可信度需整体重验。
5. **50 行 workflow 文档过于乐观**：方向对（机械编排入代码、文档瘦身），但计划书自己承认行程准备仍需 Agent 编排 MCP，加上请求构造（artifact ref/摘要/字段绑定）与 G1 行程核对简报展示，都是文档必须承载的 Agent 行为。main 入口纪律（SKILL.md L12-15）也要求场景工作流文档。应按"剩余 Agent 职责"定篇幅，而非预设 50 行。
6. **统计自相矛盾**：§十"[修改] 15"实列 16 项。小事，但佐证清单未经逐项核对。

---

## 四、修订建议（按优先级）

1. **重对源端**：拿真实 IGSA 源仓逐文件核验附录 A；若源实为 merge 形态，MCP 四步链/独立包叙事整体重写。
2. **改前提**：把"运行时零设计"改为"运行时设计=闭合 Schema 参数"；据此恢复标题/分组绑定/度量来源/偏移等请求级字段。
3. **重议几何轴**：优先评估"vector + basemap 资源 + freeform/新 layout 模型 + image-itinerary-page renderer"方案，撤销 general_dispatch 跨 bundle 接线。
4. **补全真实改动面**：map-plan（decisions 键 + renderer enum）、portrayal（geometry/expression 分支）、scenario-capabilities（models/output px）、prepared-data-bundle（oneOf 变体）四个 Schema 演进纳入计划与工期。
5. **撤两处红线**：删除 REQUIRED_COMPONENTS 放宽，改用"档案注册时机"分阶段；模板入口要么提前 validation 组件，要么显式 dev-seed 走 publish。
6. **catalog 前置**：image-itinerary 注册必须在模板 validate 之前（P2），不能拖到 P5——否则 ExpressionValidator 必拒。
7. 修正终检分派、allowed_capabilities、DPI 拒绝策略、全部失效引用。

---

## 一句话结论

这份计划书**懂迁移的战略（复用算法叶子、外置行程服务、独立档案、语义合同），但没做足迁移的尽职调查**：源端清单对不上可访问代码，目标端前提与四处闭合 Schema 相矛盾，还有两处拆安全底座的设计。它的顶层决策值得保留，执行细节需要一轮以源码为准的系统修订——尤其是把"新框架禁止运行时设计"这个错误前提，和"为进度放宽组件完整性"这个危险动作纠正过来。