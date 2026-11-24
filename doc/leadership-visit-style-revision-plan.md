# 领导调研用图 — 样式参数级修订实施计划（颜色 / 字号 / 图框边线）

> 日期：2026-11-20。本文是 `style_overrides`（设计层样式覆盖）+ 修订通道修复的分阶段实施计划，
> 供确认后实施。所有结论均经一手源码核验（引用格式 `文件:行`），无二手推断。
> 机器协议以 `skills/carto-agent/schemas/` 与 CLI `--help` 为准；本文不承载编排逻辑。

## 一、问题与目标

**用户诉求**：G2 确认阶段提出符号颜色修改时，应是一次"参数级修订"——只改参数、复用已冻结的数据证据，
而不是重跑整个流程。

**结论**（详见讨论记录）：架构已具备全部机制——内核有增量修订（`revise`）、数据证据复用
（`_reusable_bundle`）、请求级覆盖插槽（`request_contract.override_keys/apply_overrides`）；
缺的是 leadership_visit 场景没有认领颜色修订词汇，外加两个阻断性 bug。

**目标**：

1. 首轮请求即可携带 `style_overrides` 覆盖模板配色（intake 即设计）；
2. G2 前的改色走 `revise` 修订闭环（新 G1 → revise → 复用 bundle 重编译 → 新 preview → 新 G2）；
3. **迁移补齐**（方案 A）：恢复旧框架 1.2.0 已有的 `image_presentation` 合同能力——
   标题/正文字号、图框边线进 `image_itinerary` 样式合同，成为可参数化、可覆盖、可修订的
   样式参数（属恢复语义，非新增能力）；
4. 修复两个阻断 bug，使 leadership_visit 的修订通道整体通车；
5. 内核 Python 零改动，治理边界（策略 digest、场景边界棘轮、审批门禁）零触碰。

**非目标（明确不做）**：

- 不走"前端直接改 map_json / 免审批重绘"捷径（破坏 map_json 与 PDF 像素一致承诺、
  图例/信息框派生一致性、审计摘要绑定）；
- 不改 general 场景（联合词汇只做加法，场景契约仍是裁决者）；
- 不改内核 `map_generation.py` / `revision_graph.py` / 状态机；
- 不加审批旁路：颜色修订仍需新 G1 + 新 G2（分组色携带政务分组语义，属审批对象）；
- 不改既有模板合同字段的语义（Phase 1/1.5 增补均为**可选字段**，缺省不出现时行为与
  基线逐字节一致；模板继续是缺省样式权威，符合 `doc/design-principles.md` §2.4
  "缺失值由模板合同提供"）；
- 底图更换与线路修改维持新运行（数据安全面，不进轻量修订通道）。

## 二、一手证据基线（实施前提，已核验）

| # | 事实 | 源码位置 |
|---|---|---|
| 1 | compile 前内核已应用请求级覆盖；freeze/重放时 `check_candidate` 再次应用（覆盖重验免费） | `workflow/map_generation.py:207`；`compiler/map_candidate.py:158-159` |
| 2 | leadership request_contract 已有 override 插槽，当前仅 `map_title` | `scenarios/leadership_visit/request_contract.py:144-152` |
| 3 | 场景编译器从 `contracts["portrayal"]["image_itinerary"]` 读样式（覆盖合并后自动生效，零改动） | `scenarios/leadership_visit/candidate_compiler.py:137-138` |
| 4 | 修订仅允许 `state.step ∈ {compile, preview, freeze}` 且锁未落盘；锁存在即新运行 | `workflow/map_generation.py:981-983` |
| 5 | 修订词汇由场景契约限定：`map_title / annotation_layout / page_layout`；数据层字段一律不进修订 | `scenarios/leadership_visit/revision.py:26-29`；`workflow/revision_graph.py:34-35` |
| 6 | 共享提案 Schema 的 `changes` 缺 leadership 键（`annotation_layout/page_layout` 过不了 Schema 校验）——**阻断 bug 1** | `schemas/design-revision-proposal.schema.json:28-105` |
| 7 | 权威 map_json 按 `map-{run_id}.json` 命名且 create-once，修订重编译字节变化即 `IMMUTABLE_ARTIFACT_CONFLICT`——**阻断 bug 2**；page-request 已是内容寻址（对照） | `scenarios/leadership_visit/candidate_compiler.py:244-246`、`:200-201`；`artifacts.py:96-104` |
| 8 | bundle 复用门禁：bundle-input digest 相等 → 冻结数据包直接复用（含防篡改校验） | `workflow/map_generation.py:1088-1114` |
| 9 | 修订 e2e 测试模板已存在（revise → bundle 复用 → 旧 G2 拒 → 新 G2 过） | `scripts/tests/test_a31_thematic.py:466-484、750-770` |
| 10 | SchemaRegistry 自动装载 `schemas/*.schema.json`，新 Schema 落盘即注册 | `schema_registry.py:67` |
| 11 | 颜色是模板合同冻结值：路线/停靠点/callout/图例共用 `style["groups"]` 派生链 | `scenarios/leadership_visit/style.py:124、154、222-223、233-237` |
| 12 | 旧框架 1.2.0 已把标题/正文字号入合同（`scenario.layout.image_presentation`：`title_font_px: 48` / `body_font_px: 18` + `frame_border` 参数）；新框架迁移只搬了 `embedded.layout` 的 frames，`image_presentation` 丢失，字号退化为渲染器 18/9pt 硬编码——**迁移丢失，非设计边界** | 旧 `templates/map-scenario/leadership-visit/1.2.0/contracts/scenario.yaml:145-155`（IGSA_1109 仓库）；新 `adapters/image_page_renderer.py:390` |
| 13 | `scenario.schema.json` 是跨场景共享封闭合同（`embedded` 仅允许 identity/cartography/layout 三 `$ref`，`additionalProperties: false`）——场景专属参数必须进**场景专属 Schema**，不可回 scenario/layout 共享合同（方案 B 违规的结构性依据） | `schemas/scenario.schema.json:68-87` |
| 14 | `image-itinerary-style` 的事实范围已含呈现参数：`white_threshold` 由显示窗口计算消费（不经 `apply_grouped_style`）——合同事实语义是"本场景的图像呈现参数"，description 已漂移待修 | `schemas/image-itinerary-style.schema.json:267-271`；`scenarios/leadership_visit/candidate_compiler.py:139-142` |
| 15 | page-request 冻结落点现成：可选 `appearance` 节（image 分支不强制）+ 自由 `texts` 数组 | `schemas/page-request.schema.json:19-21、49-51` |
| 16 | 新框架渲染器**完全不绘制图框边线**（adapters 目录无 frame border 实现）——`frame_border` 是"参数 + 绘制特性"双重迁移丢失项 | grep 核验 `scripts/carto_core/adapters/` 无 border 实现 |
| 17 | 页面装饰文字字号推导在两渲染器**各自实现且不同源**（PDF：标称 18pt/9pt + 框拟合；前端：自有公式），视觉一致性未经核对 | `adapters/image_page_renderer.py:379-396`；`adapters/frontend_canvas.py:159-162` |

**已知决策点（Phase 0.3 验证后定）**：scene 硬编码 `"revision": 1`（`candidate_compiler.py:232`）
与 scene_id 跨修订复用——general 场景修订 e2e 通过（事实 9）表明内核按 digest 分派容忍 id 复用；
仅当 leadership 修订 e2e 实测出重放分派问题时才为 scene_id 加请求摘要后缀，不为假设问题扩协议。

## 三、分阶段实施

### Phase 0：阻断修复——修订通道先通车（不引入新词汇）✅ 已实施（2026-11-21）

**目标**：用现有 `map_title` 词汇跑通 leadership_visit 完整 revise 闭环。独立可交付、可单独提交。

**实施结果**：原计划预估 2 个阻断 bug，实施中经 e2e 逐段验证实际发现并修复 **5 个**（全部
一手源码定位，无一项是推断）：

| # | 文件 | 改动 |
|---|---|---|
| 0.1 | `schemas/design-revision-proposal.schema.json` | `changes` 补 `annotation_layout`、`page_layout` 两键；`new_value` 形状镜像 `schemas/leadership-visit-generate-request.schema.json:58-102` 的约束。联合词汇模式（先例：`map_title` 两场景共用；场景契约仍是最终裁决者） |
| 0.2 | `scenarios/leadership_visit/candidate_compiler.py:244-245` | 权威文档路径改为 `map-{run_id}-{sha256(request)[7:23]}.json`（请求摘要前缀，与 page-request 内容寻址同思想）。**不改**文档内部 `identifier`：保持 compile 原件与 preview 副本字节一致（`adapters/image_page_renderer.py:240-242` 的既有承诺） |
| 0.3 | （验证项） | scene revision/scene_id 语义：修订 e2e 通过（锁/重放按 digest 分派容忍 id 复用），**不改** |

实施中发现并同步修复的额外 bug：

| # | 缺陷 | 修复 |
|---|---|---|
| 0.4（bug 3） | leadership 封闭请求 profile 未声明 `map_title`：`_revision_documents:994` 经 `resolve_generate` 做封闭校验，修订词汇连请求校验都过不了 | `schemas/leadership-visit-generate-request.schema.json` 补可选 `map_title`（镜像 general 的 1–60 字符约束） |
| 0.5（bug 4） | `RouteRevisionContract.refresh_brief` 写入 `metadata` 字段，而共享 `map-brief` 封闭 Schema 不允许该字段 → `revision-brief` 在 Schema 校验处失败 | 场景组件修复（不动共享 Schema）：标题变更经内核新增的 `request_ref` 摘要绑定进入 G1 审批对象，`refresh_brief` 不再写 brief 本地字段 |
| 0.6（bug 5） | 场景 `data_preparer` 产出**场景私有** bundle 形状（`request_ref/prepared_at/shared_semantics`），不符合共享 `prepared-data-bundle` 协议（vector 分支要求 `task_ref/datasets/quality_evidence/digest` 等）——首轮 compile 不校验、修订复用门禁（`map_generation.py:1111`）才暴露 | `data_preparer.py` 重写 bundle 构造为协议形状（vector 变体绑定 + preparer 内自校验），`prepared_ref` 统一为 `vector-prepared-data` + POSIX uri；测试 fixture 同步对齐 |
| 0.7（bug 6） | `map_title` 是**死字段**：`apply_overrides` 写入 `embedded.map_title` 但场景无任何消费者；实际标题链是 `planner.py:49 → request.goal`，修订后摘要全变、标题纹丝不动 | 标题链修复：planner 与 candidate_compiler 优先 `request.map_title`、回落 `goal`（无标题请求行为不变） |

**测试（退出条件，全部达成）**：

1. `test_leadership_visit.py` 新增 `DesignRevisionTests`（修订 e2e，移植 a31:750-770 骨架）：
   intake → brief → G1 → compile → preview → proposal(`map_title`) → `revision-brief`（revision=2）
   → 新 G1 → `revise`（artifacts 落 `revisions/r2/request/`，旧件不覆盖）→ `compile`
   （**断言数据准备零调用**：`MapDataPreparer.prepare` spy 计数为 0）→ 新 preview →
   **旧 G2 被拒（`APPROVAL_OBJECT_MISMATCH`，SecurityError）** → 新 G2 → freeze 成功。
   断言权威 map_json 修订前后两份并存、旧件字节不变、新文档含新标题（同时验证 0.2/0.3/0.7）。
2. 新增 `annotation_layout`/`page_layout` 提案 Schema 合法/非法用例
   （`test_leadership_visit.py` + `test_a12_revision.py`：`iterations=0`、非法 model、
   未知字段拒绝）。
3. 测试基建修复：`EndToEndWorkflowTests` 的 `template-work`（create-once）与 `work`
   （状态日志）改为按测试唯一目录——此前子类多测试共享固定目录会撞
   `STAGING_PACKAGE_EXISTS`/状态残留。
4. `test_leadership_visit.py` 55 用例全绿；`carto.py schema check` 100 Schema 全绿；
   全量回归 **691 passed + 722 subtests passed，7 skipped（既有环境跳过项），0 失败**
   （1075s，2026-11-21）。

### Phase 1：`style_overrides` 请求侧——首轮设计自由 ✅ 已实施（2026-11-21）

**目标**：首轮请求即可覆盖模板配色；此阶段尚不涉及修订。

| # | 文件 | 改动 |
|---|---|---|
| 1.1 | 新建 `schemas/image-itinerary-style-override.schema.json` | 补丁子集 Schema：全字段可选、`minProperties: 1`；`groups[]` 按 `id` 补丁（只需 `id`，`color/label/right_offset_px` 可选，约束与 `schemas/image-itinerary-style.schema.json:24-52` 逐字段一致）；`route/pin/callout/support_label` 为键级部分对象；`numbering/white_threshold` 标量替换。落盘即自动注册 |
| 1.2 | `schemas/leadership-visit-generate-request.schema.json` | 加可选 `style_overrides` 字段（`$ref` 新 Schema）。封闭轮廓不变：缺省仍合法 |
| 1.3 | `scenarios/leadership_visit/request_contract.py` | `override_keys()` → `("map_title", "style_overrides")`；`apply_overrides` 把补丁合并进 `contracts["portrayal"]["image_itinerary"]`（模块级 `_merge_style_override`：groups 按 id patch、节键级合并、标量替换、深拷贝不污染模板）；模板无 `image_itinerary` → `LEADERSHIP_STYLE_CONTRACT_MISSING`；未知 group id / 未知 `default_group` → `LEADERSHIP_STYLE_GROUP_UNKNOWN`。**合并后校验复用 compile 既有形式门禁**（`candidate_compiler.py:138` 对合并结果做 `image-itinerary-style` 完整校验；`default_group` 成员资格另由 `style.py:99-100` 编译期把关）——request_contract 无 registry 依赖，形式验证职责留在有校验权的层 |
| 1.4 | `scenarios/leadership_visit/candidate_compiler.py` | **零改动**（137 行自动取到合并后样式——方案杠杆点，已验证） |

Fixture：`schema_cases.py` 增 `VALID_CASES["image-itinerary-style-override"]`
（非法用例由通用 unknown-field 变异自动生成）；schema 覆盖不变量（`test_schemas.py`）保持绿。

**测试（全部达成）**：

1. `StyleOverrideTests`（4 用例，`test_leadership_visit.py`）：
   - 封闭 profile 合法/非法（坏颜色、`opacity` 越界、未知节）；
   - 合并语义：补丁生效 + 未提及字段逐字节保留 + 合并结果过完整 style Schema +
     未知 group/`default_group` 拒绝（错误码断言）；
   - `apply_overrides` 合并进 portrayal 合同 + 模板 fixture 不被污染 + 无合同拒绝；
   - compile 集成：**hook 惰性锚**（无 `style_overrides` 时经 hook 与绕过 hook 编译
     产物 digest 相等）→ 带补丁时 scene digest 变化、morning 组 pin/callout 颜色与
     线宽进入冻结 `image_graphics`、图例颜色同步（`legend-item-1`）、未提及组保持
     模板色（`#403B96`）。
2. `test_leadership_visit.py` 59 用例全绿；边界/契约/修订/schema 套件
   （scenario_boundary / request_contract / a12 / a31 / schemas）104 passed；
   `carto.py schema check` **101** Schema 全绿（100→101）；全量回归见 Phase 0 报告
   基线（Phase 1 改动全部落在场景目录 + schemas/，无内核 diff）。

### Phase 1.5：迁移补齐——标题/正文字号与图框边线入合同（方案 A，已确认含 frame_border）✅ 已实施（2026-11-21）

**性质**：恢复旧框架 1.2.0 已有的 `image_presentation` 合同能力（证据基线 #12），属
**迁移补齐**——恢复用户可见语义（字号/边线是合同参数、可参数化、可修订），不恢复旧结构
（迁移既定原则"恢复语义、不恢复结构"，`doc/leadership-visit-migration-plan.md` 的
route_scene → planner+candidate_compiler+revision 重构先例）。

**方案 A 合规性依据**（证据基线 #13–#17 的推论）：场景专属参数必须进场景专属 Schema
（image-itinerary-style），共享 scenario/layout 合同封闭不可污染；字号/边线是表达参数
归 portrayal 侧（新框架几何/表达切分）；`white_threshold` 先例证明合同事实范围已是
"图像呈现参数"；冻结落点与 override/修订链路全部现成。方案 B（回 scenario 合同）在新框架
无任何规范背书，仅有旧结构的历史惯性。

**设计决策**：新字段以**页面域物理单位**表达（字号 pt、边线 mm），不参与 graphics 的
style scale（144-DPI 参考设计 px、随显示窗口缩放）——页面装饰属版面域，随幅面/DPI 机械
换算，两类参数的单位语义保持分离。

| # | 文件 | 改动 |
|---|---|---|
| 1.5.1 | `schemas/image-itinerary-style.schema.json` | 加可选 `page_furniture` 节：`title_font_pt` / `body_font_pt`（4–72pt）、`frame_border`（`color` #hex、`inner_width_mm` 0.1–5、`gap_mm` 0–10、`outer_width_mm` 0.1–5）。description 已修正（含 `white_threshold` 既有范围漂移）。override Schema 同步补丁字段（`frame_border` 在补丁层全字段可选） |
| 1.5.2 | `schemas/page-request.schema.json` | **实施发现**：page-request 的几何分支实际是单条 allOf 的 if(raster)→then / else→if(image)→then(完整 image 塑形) / else(vector) 链——`font_pt` 加进**既有** image 分支的 `texts[]` items（content_id/text/font_pt 封闭）；`furniture` 节在根级声明（封闭、可选）。避免新增冗余分支 |
| 1.5.3 | `scenarios/leadership_visit/candidate_compiler.py` | 从合并后 style 读取 `page_furniture`，冻结进 page_request（`texts[].font_pt` + `furniture.frame_border`）；合同无值时不写——渲染器走回落 |
| 1.5.4 | `adapters/image_layout.py` + 两渲染器（**同一提交**） | 新增**共享推导函数**（"同步消费"的字面实现）：`furniture_font_pt`（合同冻结值优先、18/9pt 历史回落、frame 拟合封顶、4pt 下限）与 `frame_border_rects`（内线骑 map frame 路径、外线 gap+半线宽外移）。PDF 侧（`image_page_renderer.py`）字体走共享函数、边线以 matplotlib 描边路径绘制；前端侧（`frontend_canvas.py`）字体走共享函数、边线为两个 `fillColor:"none"` + `strokeColor/strokeWidth` 的 Rect 特征。溢出门禁保留：显式字号是标称值，frame 容量拟合仍然生效（72pt 超容被裁剪，有测试） |
| 1.5.5 | 模板合同（模板管理员操作，非代码） | 发布时写入换算后的实测值（旧 `title_font_px: 48` @1680px 画布 → 新 pt 值）；测试内经 `style_overrides.page_furniture` 全链路驱动 |

**实施中的两项发现**（一手核验）：

1. **前端家具字号存在 mm/px 混用 bug（证据基线 #17 的真实形态）**：`_text` 的 font 参数是
   px 域（内部 × mm_x 转 mm），而前端家具代码传入的是 mm 值——map_json 标题 `fontSize`
   实际为 0.81mm（≈2.3pt），PDF 同页渲染 18pt，**双渲染器分叉以 8 倍量级存在**。修复：前端
   改走共享 `furniture_font_pt` 并正确换算 pt→viewport px。这是**有意的前端行为变更**——
   map_json 家具字号从 2.3pt 级修正为与 PDF 一致的 18pt 级；PDF 侧行为不变。
2. **图例字号仍有同类 mm/px 混用**（前端图例 ~1pt vs PDF ~8.5pt 上限）：不在 Phase 1.5
   范围（旧 `image_presentation` 亦不含图例字号），**列为后续待办**，未顺手改。

**测试（PageFurnitureTests，5 用例，全部达成）**：

1. Schema/合并：style 与 override 层 `page_furniture` 合法/非法（越界字号、坏颜色、
   inner=0）；`_merge_style_override` 键级合并（含嵌套 frame_border，未提及字段保留，
   合并结果过完整 style Schema）；
2. 冻结：`style_overrides.page_furniture` 经真实请求路径 → page_request
   `texts[].font_pt` + `furniture` 冻结；缺省时两者均不出现；
3. 前端一致性：map_json 标题 `fontSize` == 共享推导（26pt 全额）；72pt 超容被拟合裁剪
   （**溢出门禁不绕过**）；边线两个描边 Rect 的几何与共享 `frame_border_rects` 逐点一致
   （x/y 分别按 mm_x/mm_y 换算）；
4. PDF：带边线与无边线渲染 PNG 字节不同（视觉变化）；无边线重渲染字节稳定
   （**PDF 侧缺省行为不变的回归锚**——注意：前端侧缺省行为因 bug 修复而有意变化，
   见发现 1）；
5. 数字：leadership 套件 64 用例全绿；受影响套件（schemas/boundary/request_contract/
   a12/raster_formal/leadership）145 passed + 306 subtests；`schema check` 101 全绿；
   **最终干净全量回归 700 passed + 724 subtests，7 skipped（既有环境跳过项），0 失败**
   （1086s，2026-11-21；此前一次回归运行中遭遇本阶段编辑，其 3 个 raster_formal 失败
   为换文件假阳性，定向复跑证实全绿）。

### Phase 2：修订词汇认领——G2 阶段改色走 revise ✅ 已实施（2026-11-21）

**前置**：Phase 1（`revise` 的 apply_changes 后要在 `map_generation.py:993` 过
generate-request 校验，字段必须先存在）。

| # | 文件 | 改动 |
|---|---|---|
| 2.1 | `scenarios/leadership_visit/revision.py` | `rules()` 加 `"style_overrides": _COMPILATION_NODES`（与 `map_title` 同档——仅重编译+重预览，bundle 输入不动）；`apply_changes` 加分支 |
| 2.2 | `schemas/design-revision-proposal.schema.json` | `changes` 加 `style_overrides` 键（`new_value` `$ref` override Schema，形状校验委托给场景专属 Schema） |
| 2.3 | （确认项，无改动） | `refresh_brief` 不动：Phase 0 已改为经 `request_ref` 摘要绑定（bug 4 修复顺带解决了标题入 brief 的问题）；设计变更经修订请求摘要进入 G1 审批对象 |

**测试（全部达成）**：

1. `test_revision_graph.py` 新增 `LeadershipInvalidationTests`（3 用例）：
   `style_overrides` → `invalidated_nodes = [candidate, preflight, preview, scene]`、
   `data_evidence_reusable = True`、`earliest_step = compile`；样式补丁不改变
   bundle-input digest（运行时摘要门禁的静态镜像）；`page_layout` 仍失效 plan；
2. `test_a12_revision.py`：`style_overrides` 提案合法样例 + 非法补丁（坏颜色）拒绝；
3. `test_leadership_visit.py` 新增**改色修订 e2e**（本计划的落点验证）：首轮
   compile+preview → proposal（morning 组 `#1769D2 → #228833`）→ `revision-brief`
   （revision=2）→ 新 G1 → `revise` → dependency-graph 断言（仅编译节点失效、
   evidence 可复用、plan 不失效）→ **`MapDataPreparer.prepare` 零调用**（MCP 数据链
   整个跳过）→ 新冻结 scene 的 morning pin/callout 色 `#228833`、default 组保持模板色
   → 新 preview → 旧 G2 拒绝（`APPROVAL_OBJECT_MISMATCH`）→ 新 G2 → freeze 成功。
4. 数字：受影响六套件（leadership/revision_graph/a12/a31/schemas/boundary）
   **162 passed + 324 subtests 全绿**；`schema check` 101 全绿；**全量回归
   706 passed + 724 subtests，7 skipped（既有环境跳过项），0 失败**（1089s，2026-11-21）。

### Phase 3：端到端闭环 + 治理收尾 ✅ 已实施（2026-11-21）

**测试（核心交付物）**：

1. 完整链路 e2e（`DesignRevisionTests::test_style_revision_full_loop_to_delivery`，
   一次通过）：首轮 compile+preview → G2 前改 morning 组颜色 → proposal → 新 G1 →
   `revise` → **数据证据复用重编译** → 新 preview → 新 G2 → freeze → render →
   check（passed）→ review → 新 G3 → **deliver 成功**。断言：
   - 交付包 5 个标准文件齐全、`map-document.json` 不入交付包；
   - **同 seed 确定性**：修订前后 callout 的位置/偏移/尺寸逐字段不变，只有补丁组的颜色
     变化（`#1769D2 → #228833`）；
   - **旧设计不可变**：首轮冻结 scene 在原路径逐字节不变；
   - **预算计数**：`BudgetStore` 修订计数恰为 1。
2. 治理核对：
   - `policies/` **本计划五阶段零编辑**（工作区中 scenario-capabilities / tool-bindings
     的改动为会话开始前已存在的迁移遗留，非本计划引入）——策略 digest 不因本计划漂移；
   - 边界守护四套棘轮（`test_scenario_boundary` / `test_layer_ports` /
     `test_encapsulation` / `test_digest_coverage`）与 leadership 套件合计
     **101 passed 全绿**，允许清单未新增条目；
   - AGENTS 要求的"新增协议必须同时提供合法样例、非法样例和自动测试"已在
     1.1 / 1.2 / 1.5.1 / 1.5.2 / 2.2 落实（fixture + 用例）。
3. 文档同步：
   - `doc/leadership-visit-usage.md`：§二 组装请求加 `style_overrides`；§三 新增
     "G2 确认阶段的样式修订"命令序列（含数据层边界提示）；§四/§五 样式与边界更新；
   - `SKILL.md`：`leadership_visit` 场景条目补样式修订通道一句话（`style_overrides`
     语义 + 修订键 + 数据层边界）；
   - `workflows/generate-map/leadership-visit-data-prep.md`：新增 §六"数据变更重跑"
     （宿主级复用三招：geocode confirmations 复用 / 变更腿重跑 / scaffold 机械重建）。
4. 全量回归：**707 passed + 724 subtests，7 skipped（既有环境跳过项），0 失败**
   （1112s，2026-11-21）；`schema check` 101 全绿。

---

## 收口记录（2026-11-21）

**计划全部完成**（Phase 0 / 1 / 1.5 / 2 / 3，五阶段全绿交付）：

| 阶段 | 全量回归 | 关键交付 |
|---|---|---|
| 0 阻断修复 | 691+722 | 修订通道通车（实际修复 5 个 bug，超出预估 2 个） |
| 1 `style_overrides` 请求侧 | （并入 1.5 验证） | 样式补丁 Schema + 合并语义，candidate_compiler 零改动 |
| 1.5 迁移补齐 | 700+724 | `page_furniture` 入合同 + 双渲染器共享推导 + 前端字号 mm/px bug 修复 |
| 2 修订词汇认领 | 706+724 | `style_overrides` 入修订词汇 + 改色 e2e（数据链零调用） |
| 3 e2e 收口 | **707+724** | G1→G3 完整闭环 + 治理核对（policies 零触碰、棘轮全绿）+ 三份文档同步 |

**遗留待办**（2026-11-21 追记：①②已修复，修复后全量回归 **709 passed + 724
subtests，0 失败**；leadership 套件 68 用例）：

1. ~~前端图例字号 mm/px 混用未修~~ → **已修复（2026-11-21）**：确诊为图例整块单位错乱
   （字号塌缩至 ~1.1pt、行距 0.6mm 近乎重叠，PDF 同位 8.5pt——7.8 倍分叉）。修复：
   共享推导函数 `image_layout.legend_font_pt`（与 `furniture_font_pt` 同模式），
   PDF 侧收编（行为零变化）、前端侧字号与位置全部统一走 `font_px`。
   新增 `LegendConsistencyTests` 断言双渲染器一致；
2. ~~旧 `title_font_px: 48` @1680px 画布 → pt 换算由模板管理员发布时写入~~ →
   **已修复（2026-11-21）**：`route_author.py` TEMPLATE_STYLE 补 `page_furniture`
   authored 常量（换算 4px/mm：title 34pt / body 12.76pt / frame_border
   0.25-1.0-0.5mm），RouteAuthor 生成合同即含 furniture；**既有已发布模板不受影响
   （继续走 18/9pt 回落），新值须重新 create-template 发布生效**（治理规则如此要求）。
   新增模板值断言 + 编译冻结测试；
3. 真实数据敏感准入与 Part II 前端消费回路为独立轨道，见场景边界声明；
4. CLI stdout UTF-8 化（Windows GBK 混编根因已登记 data-prep 手册 §七.1）。

## 四、修订闭环的预期成本（用户视角）

| 环节 | 颜色修订时 | 依据 |
|---|---|---|
| 数据摘要→草稿→check→scaffold | 跳过 | 请求不动数据字段 |
| intake / brief 重建 | 跳过 | `revision_brief` 从既有 brief 派生（`map_generation.py:995-1000`） |
| MCP 链（geocode 歧义确认→plan_route→assemble） | 跳过 | bundle-input digest 不变 → 冻结数据包复用（`map_generation.py:1088-1114`） |
| compile / preview | 重跑（确定性，秒—分钟级） | 投影/开窗重演、样式重编译、注记求解（有界、固定 seed） |
| G1 / G2 | 各一张回执 | HMAC 签名；买"审批摘要 = 交付物摘要" |

## 五、顺序理由与风险

- **顺序**：Phase 0 独立先行（先证明通道本身能通车，用已合法的 `map_title` 词汇）；
  Phase 1 → 1.5（1.5 依赖 Phase 1 的 override Schema 存在）→ Phase 2 → Phase 3 收口。
  每阶段结束全绿、可独立提交、可回滚。
- **量化边界**：Schema 4 处（image-itinerary-style / image-itinerary-style-override /
  page-request / design-revision-proposal，3 改 1 新）+ 场景组件 2 处
  （request_contract、revision）+ candidate_compiler 2 处（样式合并零改动之外：
  `page_furniture` 冻结 + map-document 路径修复）+ 2 个渲染器（字号回落 +
  frame_border 双侧新增绘制）。内核 Python（map_generation / revision_graph / 状态机）零 diff。
- **风险与守卫**：
  - `apply_overrides` 原地修改 contracts——与 general 先例一致，且 `check_candidate`
    每次重载重放，漂移即拒绝；
  - 修订预算/恢复已有 `REVISION_BUDGET_DRIFT` / `REVISION_STAGING_CONFLICT` 处理，e2e 覆盖；
  - 场景边界棘轮只紧不松：全部改动落在场景目录 + schemas/ + 2 个既有适配器，不新增允许清单条目；
  - Phase 1.5 渲染器改动风险最高（双渲染器同步）——守卫是"缺省回落字节级回归锚" +
    "同参数一致性断言"两条测试，且 1.5.4 要求两文件同一提交。

## 六、数据层变更的处理边界（路线修改 / 换底图）

本计划只把**样式参数**（符号颜色、注记/标题字号、图框边线——均属 Phase 1/1.5 的
`style_overrides` 词汇）纳入修订通道，不是遗漏，而是三层边界的自然结果：

| 需求 | 层归属 | 依据 |
|---|---|---|
| 样式参数（颜色/字号/边线） | 设计层（创意表达参数） | 不在 `revision.py:35-37` 的 bundle_input_keys（`source_bindings/sources/itinerary_structure/basemap`）中，不碰任何数据摘要 |
| 路线修改 | 数据层 | 行程数据经 MCP 链 → prepared bundle 冻结；改路线 = bundle-input digest 变化 |
| 换底图 | 数据层 | `basemap.image_ref` 是请求数据字段且为 bundle input key；brief 的 source_plan 绑定底图摘要（`request_contract.py:128-137`） |

**数据层不纳入修订通道的论证**（净收益 ≈ 零，非偷懒）：

1. 新 G1 省不掉：G1 审批对象是 MapBrief，brief 的 source_plan 绑定数据事实摘要
   （行程文件、底图 `path_digest`）。数据变了审批对象就变了——"审批人签的摘要 =
   实际使用的数据"是审计等式，不是流程洁癖。
2. 受影响数据的 MCP 重跑省不掉：变更腿的路径规划必须真跑，外发授权又在 G1 面上。
3. 内核侧要付代价：`revision_graph.py:34-35` 的不变式是"所有可修订键均为设计层字段、
   `data_evidence_reusable` 恒真"；纳入数据层需改内核语义、在 revise 内嵌套数据重备
   与外发再授权。换来只是保留 run_id，而新运行中 intake/brief 本就是机械秒级步骤。

**新运行 ≠ 从零开始——宿主级复用**（依据 `workflows/generate-map/leadership-visit-data-prep.md`
已文档化的工具 I/O，零代码、不破审计链）：

- 地理编码不重新盘问用户：geocode 的 `confirmations` 机制使上一轮确认结论对未变更地点
  直接可复用；新地点才需要新的歧义确认；
- 路径规划只跑变更腿：`plan_route` 按腿输入，未变更腿沿用上一轮 `results`，与新结果
  合并后传给 `itinerary_assemble`（其校验"每条 travel 腿有道路折线"，合并结果满足）；
- 请求重建是机械步骤：`request_scaffold` 自动重算全部摘要绑定。

路线修改的真实新增成本 = 变更部分的 MCP 调用 + 一张新 G1 + 一张新 G2，与颜色修订的
审批成本同量级；差距只在变更数据的计算本身，而这部分本来就该跑。

**在线底图**（PNG → 瓦片/URL）不是修改路径问题，是能力特性，当前架构三处硬阻断：

1. 请求 Schema `basemap.mode` 为 `const "registered-transform"`（`schemas/leadership-visit-generate-request.schema.json:47-49`）；
2. 资源模型是摘要绑定的字节流（scene `resources` 带 digest；map_json 底图图层仅
   `image_digest`，`frontend_canvas.py:179-180`），在线瓦片流无法确定性冻结重放；
3. 配准仿射模型（`origin_m` + 2×3 矩阵 + `source_size`）定义在固定栅格上，瓦片没有
   `source_size`。

属 roadmap 级特性，`workflows/generate-map.md:92` 明示不开放；不在本计划范围内。

> **2026-11-21 重判补注**（依据底图双绑定实施计划的源码核验，用户确认需求）：
> 换底图分类由"数据层/新运行"重判为**compile 资源层/revise 修订回路**——内核零场景
> 词汇（revision_graph.py：rules/keys 来自场景组件），bundle 复用由运行时
> bundle_input_digest 比对守卫，而 basemap 从不进 prepared bundle（compile 直读请求
> 引用）。`basemap` 已移出 bundle_input_keys 并进入修订词汇；行程数据三键
> （source_bindings/sources/itinerary_structure）保留，"数据层不纳入修订通道"的结论
> **对行程数据继续成立**。本节"在线底图"三处硬阻断的破法也已落地：请求加法声明
> `online_basemap`（外发进 G1 面）、map-document 地理段（extent 显示窗口反推）、
> 快照固化（瓦片 → 冻结 PNG + 相机反推配准）绕开瓦片流不可冻结问题。

## 七、已确认与待确认事项

**已确认（讨论过程收敛）**：

- 修订通道方案：颜色走 `revise`，不走前端重绘捷径（三轮讨论 + 源码论证）；
- 数据层边界：路线/换底图维持新运行 + 宿主级复用指引（§六）；
- 迁移补齐采用**方案 A**（`page_furniture` 入 `image_itinerary` 合同），
  合规性论证见 §三 Phase 1.5 与证据基线 #13–#17；
- `frame_border` **一并补齐**（含两侧渲染器新增绘制）；
- 新字段单位决策：页面域物理单位（字号 pt / 边线 mm），不参与 style scale。

**待确认**：

1. 是否按 Phase 0 → 1 → 1.5 → 2 → 3 顺序实施（每阶段完成给出测试证据后再进入下一阶段）？
2. Phase 0.3 的 scene 语义决策：接受"仅实测出问题时才改"的保守路线？
3. 文档同步范围（usage 文档 + SKILL.md + data-prep 手册"数据变更重跑"小节）是否足够？
4. Phase 1.5.1 的字段取值边界（字号 4–72pt、边线 mm 上界）由实施时按渲染器物理约束
   定稿，是否接受？
