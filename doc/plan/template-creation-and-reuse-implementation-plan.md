# 自然语言与参考图驱动的模板复用、草稿创建及按需入库：阶段实施计划

| 项目 | 内容 |
|---|---|
| 日期 | 2026-11-23（Asia/Shanghai） |
| 状态 | 待评审、待实施；不表示目标能力已经开放或验收通过 |
| 设计依据 | [模板检索、创建及按需入库设计（修订版）](../template/template-creation-and-reuse-design.md)，含专家评审后的 §5.4、§6.5–6.7、§8.4、§10.3、§11.3、§12.1、§15.3 |
| 代码调查基线 | HEAD `e5119a3` 加当前未提交工作区；仅 commit 不能复现本文快照，开工须冻结具体工作区变更清单 |
| 调查方式 | 静态阅读源码、Schema、策略和已有测试定义；本轮未执行 CLI、测试、渲染或业务验收 |
| 实施结构 | 3 个阶段；项目草稿直接制图 GD 作为独立可选工作包，不增加第四阶段、不作为主流程 MVP 的隐含依赖 |
| 唯一实现根 | `skills/carto-agent/`；共用现有 CLI、状态机、作者、验证器、审批和仓库 |

## 实施进度（2026-11-23，阶段一首批）

| 增量 | 内容 | 验证 |
|---|---|---|
| 需求协议 + 纯谓词求值器 | `design-requirement.schema`（条件外壳 id/strength/predicate/source_ref + measure/enum/count/relation 闭合谓词，§6.5 最小词汇）；`compiler/design_requirements.py` 三态求值 satisfied/violated/unknown + hard AND 聚合（空 hard→browse）；count 按 distinct content_id、角色清单不完整→unknown、contained-legend 零主图→violated（不空集合真）、非法谓词/非有限事实失败关闭 | test_design_requirements 16 项（N02/N03/F01–F05） |
| 内容角色事实视图 | `layout.schema`/`resolved-layout.schema` 加 content_role（页面内容角色唯一权威，加法，与 Style symbol_roles 不混用）；layout.py 传播 content_role；`layout_fact_view` 从 resolved layout 构建事实视图（roles_complete 判定，旧合同无角色→unknown 不自动补 main-map）；inset 关联保留已实现 main_map_ref，不叠加 parent_view_id 成第二权威（化解 §4.2 标记冲突） | FactView 2 项 + layout/grid/inset/page_bindings 零回归 |

| 有限参数域 + 候选报告 | `compiler/parameter_domain.py`：识别 legacy grid_cases 域（placement outside）、全元组成员检查（p 精确等于一个 allowed_case，非字段级）、case 执行准入（inside 未实现→not-implemented）；`assess_candidate` 结构/参数/execution_admission/validation_coverage 四维分开，usable 需全满足（结构 satisfied 但 not-implemented 仍不可用） | test_parameter_domain 13 项（N05/F06/F07） |
| resolution 决策 + 只读 resolve CLI | `resolve_requirement` 七分支（reuse/instantiate/derive/create/clarify/unsupported/search-incomplete），结构 satisfied+准入 unknown→clarify 不冒认 reuse；`design-resolution-result.schema`；`template resolve` CLI 检索候选→事实视图→评估→分支（阶段一准入保守 unknown，能力策略接入为后续） | resolution 7 + CLI resolve 3（空库 create/已发布候选评估/scope 拒绝） |
| 能力 admission + grid 角色传播 | `instantiate_grid` 生成帧传播 content_role（map→main-map、legend→legend-group）使 N04 可达；`layout_execution_admission` 策略驱动（超 output_constraints→forbidden、inside 图例→not-implemented、非 output_profile 尺寸→not-implemented（A3 上限≠全链准入）、否则 allowed）；resolve CLI 接入 admission + 已发布可解析候选 coverage covered，reuse 分支可达 | admission 5 + N04 1 + CLI reuse 1；grid 渲染零回归 |

**阶段一退出条件达成**：N02/N03/N04/N05/F01–F07 均有自动验证；只读检索索引不变；非法谓词拒绝、unknown 不进入精确复用、能力未开放明确报告；合法参数化不回退。
**后续（阶段二）**：NLP 适配与四分支创作、默认草稿终点、显式发布意图、A→B 发布转换；参考图证据加固（§5.3）。
**回归**：定向批 90 项绿（parameter_domain + grid_layout + design_requirements + schemas）；全量回归已执行（见阶段二进度节，885 项 OK）。

## 实施进度（阶段二首批：参考图/验证完整性加固）

| 增量 | 内容 | 验证 |
|---|---|---|
| §5.3.1 intake 限制前置 | `intake_reference` 先 stat 尺寸检查再读取（避免大文件全读入内存）；格式/像素头检查在完整解码前；TOCTOU 校验（len(raw)==stat）；摘要从同一冻结 bytes 计算（hashlib.sha256(raw)，不再二次读路径） | test_reference_intake 10 项（含摘要一致性） |
| §5.3.7 发布重验对称 | `verify_evidence` 捕获重渲染新回执，输出内容摘要与冻结预览逐项比对（VALIDATION_RERENDER_DRIFT），不再丢弃返回值；渲染器/代码漂移改变同场景输出被抓住 | 漂移拒绝反例（mock 重渲染→publish 失败关闭）+ 空库发布重验绿 |
| 默认草稿终点 + publication-request | `publication-request.schema`（intent-only/ready，ready 须绑定 target，绑定 request_id/kind）；`SegmentCreationWorkflow.validate` 默认止于 validated-draft（succeeded/validate，不写索引），仅受信 ready publication-request 才进 prepare-publish；intent-only 仍停留；绑定 mismatch 拒绝；CLI validate 加 --publication-request（条件 kwargs，场景流不受影响） | 草稿终点索引不变/intent-only 停留/绑定 mismatch 3 新测试 + 3 发布测试传 ready；场景段引用零回归 |
| §5.3.3/§5.3.4 对比加固 | `_expected_validation` 加 reference_declared（从请求 /reference/ decisions 推导）；`_reference_comparison` 改为声明驱动（声明则缺证据 REFERENCE_EVIDENCE_MISSING 失败关闭，删文件不能取消检查；普通段不受影响）；effective 色从设计离散角色取（style_discrete_colors），无绑定标 user_color_bound=False（宿主 canonical 色只证明验证搭档） | 声明缺证据失败关闭反例 + 普通段无对比 + 参考绑定对比绿 |
| 四分支创作编排（§5.2/设计 §7/§7.1） | `derive_draft`（加法，不动现有 derive）：受限 change-set→项目草稿，身份键 namespace/id/version 恒禁改（即使在 allowed_keys），不递增业务 patch、不预占库身份；草稿身份 draft-<id>/0.0.0-draft.r<rev>；base_ref（包引用）与 base_contract_digest 分离记录。`orchestrate_creation`：reuse/instantiate 返回 published_ref 不产包；derive/create 需显式受信输入（缺则 ORCHESTRATION_INPUT_MISSING 失败关闭）产项目草稿；clarify/unsupported/search-incomplete 停止；requirement_id/revision 绑定校验。`design-resolution-result` 加法可选 action/published_ref/draft_ref（只读 resolve 实例不受影响，ProjectDraft 入该分支不另起 Schema）。CLI `template orchestrate` 复用 _resolve 检索判定再执行分支，绝不写索引/发布/审批 | derive_draft 6 + orchestrate 10 + CLI 3；定向批 104 绿（creation_orchestration+parameter_domain+design_requirements+template_proposal+schemas）；schema check 102 ok |
| A→B 发布转换（§5.2/设计 §8.4） | `segment-create-request` 加法可选 source_import（绑定 A.run_id/workdir/draft摘要/evidence摘要+uri，使 B 输入指纹覆盖来源）；`SegmentCreationWorkflow.import_draft`：A 只读且须已成功终结（succeeded/validate），逐项校验 evidence_digest/status/design_digest 与 B.design==A 草稿内容（IMPORT_EVIDENCE_DRIFT/IMPORT_DRAFT_DRIFT/IMPORT_DESIGN_DRIFT/IMPORT_SOURCE_NOT_FINISHED/RUN_MISMATCH 失败关闭）；折叠 analyze+brief（抽取 _build_analysis/_build_brief 纯helper，analyze/brief 行为不变）衡接 author 前置指纹；B 复用同一状态机与 author→validate→prepare-publish→publish 链按最终身份重验/重渲染，不改签 A 回执。新增 draft-import-record schema + CLI import-draft | 6 测试绿（含真实发布链 + A job-state/evidence 字节不可变断言 + 5 失败关闭反例）；segment_workflow/segment_refs 零回归 |
| NLP 适配（§5.4） | 新增 `nlp-requirement-candidate` schema（未受信候选，additionalProperties:false 拒 publish/审批/库路径/工具字段；claims≤64 复用 §6.5 闭谓词；source_locator 半开区间；origin 仅 user-stated/author-proposed/image-observed）。`nlp_adapter`：validate_candidate（闭合+原文跨度真实存在+ID唯一+问题引用校验）；normalize_candidate 双层接纳（受信规则复核原文跨度↔值：数量词/枚举/测量；复杂语义与不匹配保持 tentative→soft+待确认 open_question；author-proposed 永不成为已确认 hard）；adapt_with_retry 有限修复（最多 2 次，耗尽 NLP_ADAPTATION_FAILED 不无限生成）。NLP 词汇仅在输入适配层，不进几何/渲染/安全内核，不授权 | 12 测试绿（确认/越界/倒置/publish拒绝/author-proposed降级/复杂tentative/不匹配/重复ID/未知条件/修复成功/耗尽） |

**阶段二后续（待实施）**：无大型编排剩余。四分支创作编排、A→B 发布转换（import-draft）、NLP 适配（§5.4）均已交付。可选后续：草稿接段工作流作者链的 CLI 端到端编排（orchestrate draft→create-template）、GD 项目草稿制图独立子计划（设计 §11.3，单独评审）、阶段三 A3 双主图内置图例能力。
**回归**：定向批 33 项绿（reference_segment + segment_workflow + reference_intake）。**全量回归（2026-11-24）**：`unittest discover -s tests` 885 项，1872s，OK（skipped=9，均为既有环境守卫：可选 MCP SDK/Fiona/符号链接权限/独立 GIS 解释器等，与本计划改动无关）；阶段一全量 + 阶段二已交付增量（intake 前置/重验对称/草稿终点/对比加固）基线干净，日志 `projects/.carto-dev/_full_regression_20261124.txt`。**A→B/NLP 增量后定向批 135 项绿**（schemas+nlp_adapter+creation_orchestration+design_requirements+segment_refs+draft_import+segment_workflow+parameter_domain）；schema check 104 ok（新增 draft-import-record/nlp-requirement-candidate）。

## 实施进度（阶段三首批：inside-legend 通用生成机制 + 参数域准入）

| 增量 | 内容 | 验证 |
|---|---|---|
| 有限参数域单权威（§6.2） | `grid-parameters` 加法可选 legend_placement（outside/inside，缺省 outside 保旧行为）；`layout.grid` 加法 allowed_cases（全元组，存在时为唯一权威）+ inside_legend 声明（anchor/offset/width/height/padding）；grid required 改 anyOf（allowed_cases 或 allowed_shapes+legend_modes 择一），消除重复权威 | schema check ok；allowed_cases 单权威反例（域外组合拒绝） |
| inside-legend 机械生成（§6.2/设计 §2.3） | `grid_layout.instantiate_grid` independent+inside：主图保留整 cell 宽（不扣外侧图例栏）；`_inside_legend_bounds` 从作者声明 anchor/offset/padding 机械推导图例 bounds 并验证完全包含（不合则 GRID_CAPACITY_INVALID 失败关闭，不偷缩/外移）；传播 content_role=legend-group/view_ids=[本视图]/inside_frame=本主图。shared+inside 未开放拒绝；缺 inside_legend 声明拒绝。`case_key` 全元组单源（parameter_domain 复用） | 生成几何/包含/角色/谓词 satisfied + 全宽 + 越界失败 + shared拒绝 + 缺声明拒绝 + outside 零回归 |
| 策略驱动准入（§6.3） | `parameter_domain.layout_execution_admission` inside 不再 blanket not-implemented，改由能力策略 layout_constraints.grid.legend_placements 声明驱动（缺省 outside-only 保旧行为）；`scenario-capabilities.yaml` 加法 legend_placements [outside, inside]。A3 尺寸全链准入仍待后续（非 profile 尺寸仍 not-implemented） | 准入策略驱动正反例 + 默认保旧；第一阶段 contained-legend 谓词对生成事实求值 satisfied |
| 真实渲染验收（§6.2/§6.4） | inside-legend 机制流经真实渲染链：GridPageTests.page 加法 placement 参数，`compile_page_request` + `PageRenderer.render` 真实产出 PNG；验证每个 independent 图例 bounds_px 完全包含于本主图 bounds_px、输出 2 body_refs、PNG 尺寸与图例色存在（不是仅几何/mock） | test_real_inside_legend_renders_within_each_map 真实渲染绿；grid 全量 57 项零回归 |

**阶段三首批边界（诚实披露）**：已交付**维度无关的通用 inside-legend 生成机制 + 参数域/准入 + 真实渲染验收**（A4 尺寸证明机制与尺寸无关，真实 PNG 图例位于主图内）。**尚未交付**：A3 output_profile（420×297）全链一致（验证宿主/RenderScene/正式渲染/终检，需 steward 审核冻结运行影响）、案例集合重放、**多图 grid 候选的检索再集成**（当前 resolve CLI 无参数解析候选，多图 grid 候选仍 unknown；需让 resolve 实例化声明的 allowed_cases 才能评估多图 inside 候选，属§6.2 项6后续）；不宣称 A3 目标用例已全链可用。
**回归**：首批定向批 127 项绿；真实渲染增量后 grid 批 57 项绿（grid_layout 含真实渲染 + grid_inside_legend + parameter_domain），零回归。

## 一、目标与实施边界

### 1.1 最终主流程

> 用户描述或参考图 → 需求规范化与必要澄清 → 只读检索 → 硬约束满足性/能力检查 → 原样复用、参数化复用、派生草稿或新建草稿 → 验证并返回 → 用户明确要求入库时才准备发布对象、验证 TP 并发布。

必须区分三个交付层次：

1. **检索可信：** “相似”“满足”“能执行”“已经验证”分别有依据，不把一个相似度分数当通行证。
2. **默认不入库的创作闭环：** 对已准入能力，从输入返回可复用引用或项目草稿；用户未要求入库时，模板索引不变。
3. **目标示例能力：** A3 横版、双主图、各自主图内置图例可以实际实例化、验证和按需发布；不只生成结构合法的文件。

GD 交付后才能进一步声明“未入库草稿可直接用于正式地图任务”。GD 未交付不阻碍前述主流程上线，但产品必须清楚说明草稿的实际使用限制，不能自动替用户发布。

### 1.2 不变约束

- 不新增业务场景来伪装模板类型，不新建另一套模板库、页面引擎、状态机或宿主专用实现。
- 创建、项目文件保存、用于本次地图、发布入库是不同动作。默认不生成发布对象、不消费 TP、不写业务索引；项目内必要草稿/证据可在授权根内保存。
- NLP/图像输出不产生权限。明确结构化用户动作授权发起发布，精确 TP 才批准具体发布对象；不恢复 T1，不让 Agent 自签回执。
- 参数化使用不修改库合同；派生/新建产生草稿 revision，不预占业务版本；发布时按最终身份重新验证。
- 对协议新增能力显式版本演进；纯重构不改请求/提案形状或策略语义，不静默迁移冻结运行、不新增旧格式兼容 wrapper。
- 任何能力、安全、颜色或几何门禁失败不通过“用户同意忽略”绕过。业务数据只按已准入能力读取、筛选和符号化，不为补图派生几何。
- 不自动安装依赖、开通公网服务、注册全局 Skill 或开启生产准入。真实数据、字体、模板与参考图资源许可分别核对。

### 1.3 与既有计划的关系

[参考图到段模板实施计划](reference-image-template-implementation-plan.md)承担图像提取、颜色权威、段宿主和样本渲染专项；本计划复用其已经存在的代码，补齐统一需求、检索判定、默认草稿终点及按需发布，不重复建设。

两份计划共享同一组代码与协议变更。应在开工清单中将同一任务只登记一次：本计划关注“输入与用户意图如何驱动复用/创建/发布”，参考图专项关注“图像证据如何正确恢复并驱动制图”。Athi River 全元素渲染扩展不是 NLP 主流程的必需前提，不与 A3 双主图示例捆绑估算。

运行权威仍是 Skill 内 Schema、策略和代码。本文及其他设计文档不作为机器协议读取；旧开发日志中的测试结果和阶段完成标签只作线索，不代替本次验收。

## 二、当前代码基线：复用什么、补齐什么

缩写：`C/` = `skills/carto-agent/scripts/carto_core/`；`S/` = `skills/carto-agent/schemas/`；`T/` = `skills/carto-agent/scripts/tests/`；`P/` = `skills/carto-agent/policies/`。下文“已有”均指静态可见，不表示本轮运行通过。

| 能力 | 本次静态核对结果 | 后续处置与依据 |
|---|---|---|
| 只读模板匹配 | `template match` 已注册，读取仓库候选并评分；请求仍要求完整 Style/Layout segment | 复用 CLI/仓库；新增部分需求入口及硬约束评估，不重做匹配命令。[match_cmd.py](../../skills/carto-agent/scripts/carto_core/cli/match_cmd.py) |
| 段作者和打包 | 已有独立请求、分析、Brief、作者、闭合包和类型分派 | 复用，增加 requirement/proposal/draft 来源及终点控制。[segment_workflow.py](../../skills/carto-agent/scripts/carto_core/workflow/segment_workflow.py)、[segment_authoring.py](../../skills/carto-agent/scripts/carto_core/repository/segment_authoring.py) |
| 段验证与发布适配 | 当前已覆盖 `_resume_request`、`_expected_validation`、`_verify_for_publish`；存在宿主、样张渲染和重验代码 | 不再按旧快照列为“完全未实现”；先补关键不变量测试，再作为共同底座。[segment_validation.py](../../skills/carto-agent/scripts/carto_core/workflow/segment_validation.py) |
| 验证后终点 | 段 validate 成功仍设置 `next_step="prepare-publish"` | 缺少 validated-draft 终结和显式 publication-request 分支；目前准备下一步骤不等于已自动发布，也不满足设计的明确草稿终点 |
| 参考图接入 | 已有 `reference-prepare` CLI，intake→proposal→design 草稿请求，保存图像和来源记录 | 接入统一需求/确认模型并加固输入与证据，不再另写一套图片入口。[reference_segment.py](../../skills/carto-agent/scripts/carto_core/workflow/reference_segment.py)、[reference_intake.py](../../skills/carto-agent/scripts/carto_core/workflow/reference_intake.py) |
| 参考提案到设计 | Style 分支当前主要应用 typography；Layout 应用 recovered layout 或 base；提取色角色映射仍需明确步骤 | 不能把输出的全图色板等同已形成可执行 Style；加入类别语义、人工确认和实际合同变更证明 |
| 参考对比 | 有 `reference_comparison.py`，段验证调用对比；当前主要为颜色距离，正常返回即记 comparison passed，参考文件缺失时可返回空结果 | 将声明来源、文件摘要、覆盖/阈值、授权偏离和发布复核闭合绑定；“有数值报告”不等于“达到恢复验收标准” |
| Style 离散色 | `style_colors.py` 与 `category_colors` 已接入，宿主有条件使用 Style 色；另有实例 effective color_scheme | 复用现行 baseline/effective 机制并测试一致性，不恢复旧“颜色完全未接入”的结论。[style_colors.py](../../skills/carto-agent/scripts/carto_core/compiler/style_colors.py) |
| 需求与满足性 | 未发现设计中的 design-requirement、design-resolution-result、publication-request，也未发现 content_role/allowed_cases 的正式消费者 | 新增最小协议和纯求值器；先支持有限词汇，不引入任意 DSL |
| 参数域 | 已有 `allowed_shapes × legend_modes`，实例化器做成员校验；多图基座仍拒绝 inside_frame | 保留现有有限域语义，新增版本的 allowed_cases 与图内图例实例化属于本计划增量。[grid_layout.py](../../skills/carto-agent/scripts/carto_core/compiler/grid_layout.py) |
| inset 与整饰 | 已出现 inset 声明校验、LayoutResolver 准入及比例尺纯计算模块 | 与旧文档快照不同；声明/布局准入不等于次级视图渲染已完成，不将 inset 当双主图。[layout.py](../../skills/carto-agent/scripts/carto_core/compiler/layout.py)、[inset.py](../../skills/carto-agent/scripts/carto_core/compiler/inset.py) |
| A3 目标 | 策略仍有 A4 output_profile、A3 尺寸上限；不能据上限宣称 A3 已全链开放 | 阶段三明确联动宿主、场景、输出和像素上限，不能只改 canvas。[场景策略](../../skills/carto-agent/policies/scenario-capabilities.yaml) |
| 草稿直接制图 | 正式安装校验仍要求 published 模板 | 作为 GD 独立工作包；不删除或跳过旧入口检查。[map_generation.py](../../skills/carto-agent/scripts/carto_core/workflow/map_generation.py) |

**共同底座必须补验的重点：** 段锁/身份一致性、宿主及案例覆盖、字体/资源漂移、参考图声明与文件缺失、真实对比中的有效色来源、重新渲染产物与冻结回执输出是否确实逐项比对。不得因函数名叫 verify 或文档写了“闭环”就跳过这些检查。

## 三、阶段总览与依赖

| 阶段 | 核心目标 | 主要输入 | 核心交付 | 用户可感知结果 |
|---|---|---|---|---|
| 阶段一：需求形式化与只读复用 | 把用户要求变成可确定检查的条件，可靠地区分满足/近似/未知 | 结构化需求、已发布候选、人工确认样例 | 严格需求与结果协议、角色事实视图、有限域检查、满足性报告、只读检索 | 能找到真正满足的候选并说明原因；不满足/能力未开放不会假命中 |
| 阶段二：统一创作与按需发布闭环 | 接入 NLP/参考图，打通四分支、默认草稿终点、显式保存与发布 | 阶段一结果、提案、确认记录、现有段作者/宿主 | 经验证项目草稿、结构化发布请求、A→B 发布转换、闭合证据 | 在已准入能力范围内先复用、无匹配再创建；不说入库就不入库 |
| 阶段三：目标布局能力与复用验收 | 实现 A3 双主图各自内置图例并证明全链可执行 | 前两阶段、已评审的新参数组合和输出能力 | 新版有限 grid、绑定/渲染/终检、全部声明案例证据 | 示例从“理解正确但不支持”升级为可渲染、可验证、可按需发布 |

依赖关系：阶段一协议与事实视图 → 阶段二交互与生命周期；阶段三消费能力可以在前两阶段接口稳定后施工，但完成后必须回到同一检索/草稿/发布链验收。没有阶段三时，阶段二对 A3 双主图内置图例仍须诚实报告 not-implemented。

**MVP 边界：** 阶段二结束可发布一个基于现有已准入能力的完整产品闭环；不包含尚未交付的新布局组合、全量参考图自动识别或项目草稿正式制图。GD 是否启动独立决策，见第七节。

## 四、阶段一：建立可确定求值的需求、角色和只读检索

### 4.1 核心目标

先解决“什么算满足”，再连接 LLM。以人工确认的需求对象和真实合同为输入，完成纯求值和只读检索；避免模型解释、评分、模板选择与权限混成一个黑箱。

### 4.2 主要改动

| 工作项 | 内容与决策 |
|---|---|
| 协议基线和版本表 | 固定修订设计的最小谓词范围；定义新 design-requirement、design-resolution-result 及现有 match 协议下一版本的关系。严格嵌套闭合、ID 唯一、数值有限、单位一致、预算有界 |
| 需求候选与确认 | 表达 hard/soft、来源片段、author-proposed、未知项和阻断范围；不把模型置信度当用户确认。先允许人工结构化需求走通，NLP 在阶段二接入 |
| 谓词求值 | 实现 measure/enum/count/contained-legend；对候选实例事实确定输出 satisfied/violated/unknown。必要条件 AND 聚合，非法协议先拒绝，不用 unknown 吞错误；无主图时 contained-legend 不能空集合真 |
| 内容角色与事实视图 | 在受评审版本 Layout 增加内容角色并通过解析产物传播；main-map/inset-map/legend-group 与 type/content_id/view_ids/inside_frame 一致。地图匹配一对一，不与 Style 类别颜色 role 混用 |
| 有限参数域 | 第一阶段完整识别现行 `grid_cases()` 域并按实际实例检查；完成下一版 allowed_cases 的协议/求值接口设计，消费者只接纳已实现案例。inside 组合直到阶段三真正执行前均明确未支持，不凭新枚举开放 |
| 授权只读检索 | 结构筛选+受信标签匹配，小库优先有界枚举。候选缺信息保留 unknown；库不可读/预算耗尽返回 search-incomplete。评分仅排序，不以阈值掩盖硬条件不满足 |
| 统一结果 | 原样/参数化命中返回 scope、namespace、精确包引用、参数及证据；近似项给不满足理由和派生建议，不在本阶段自动创建或发布 |

角色协议落地前需核对设计的目标字段与新代码：当前 inset 已有 `main_map_ref`、独立 view 等声明，不能再不加区分地叠加 `parent_view_id` 成为第二权威。评审应选择唯一关联表示并明确 frame/view 标识映射；若收敛到现有字段，先同步设计裁决，不以双字段兼容解决冲突。旧合同无 content_role 的候选不自动补成 main-map，相关条件保持 unknown。

结构满足性、执行准入、验证覆盖必须分别输出。一个 A3 合同可以结构满足而执行不支持；没有真实图例内容时仅证明已声明容量，不承诺业务数据遮挡检查通过。

### 4.3 代码与协议范围

**复用/修改：**

- `C/cli/match_cmd.py`：保留已存在的 full-segment 只读语义，为受评审新请求版本接入 requirement_ref；不直接把原 score 重新解释为合格概率。
- `C/repository/template_matching.py`、`template_repository.py`：复用读取/完整性/排序；按需补 scope/namespace 和快照证据，不引入写副作用。
- `C/compiler/layout.py`、`grid_layout.py`、相关 `page_bindings.py`：提供已验证实例事实与角色传播；不为返回命中而动态修改模板。
- 建议新增 `C/compiler/design_requirements.py`（或等价纯验证模块）与 `C/workflow/template_resolution.py`（组合根）：纯模块不访问仓库或导入工作流，编排注入受信读取端口。
- Schema：新增 `design-requirement`、`design-resolution-result`；按版本演进 `template-match-request/result`、`layout`、必要的 `resolved-layout/page-bindings`。复用 common 的引用/身份类型，不另建字段体系。

以上新增模块名为建议，实施前以职责边界审查收敛。NLP 专有词汇只在输入适配层，不进入几何、渲染或通用安全内核。

### 4.4 交付与退出条件

**交付物：** 协议变更表、最小谓词求值器、角色与参数事实规范、可解释检索入口、合法/非法 Fixture、逐条件报告、能力覆盖说明。

**退出条件：**

- N02/N03/N04/N05/N07/N08 及 F01–F08/F15/F16 对应行为有自动验证；可复核不同 frame 与同一 view 的映射，不出现“双主图匹配到同一张图”。
- 两次同输入/同快照检索结果稳定；检索前后业务索引和模板包不变。
- 非法谓词拒绝、必要 unknown 不进入精确复用、能力未开放明确报告；没有用当前阈值替代需求验证。
- 现行合法参数化能力不回退；旧合同缺新角色时不静默迁移。
- 新角色协议若影响共同编译链，必须完成相应消费者、摘要覆盖与完整回归后才验收，不能只修改 Schema。

**本阶段不做：** 训练语义检索模型、自由约束求解器、完整 NLP 自动设计、模板入库或 GD。

## 五、阶段二：统一输入、四分支创作、草稿终点与显式发布

### 5.1 核心目标

在已有可执行能力范围内，从自然语言或参考图到“引用/经验证项目草稿”完整返回；只有明确受信保存动作才进入发布。复用已经出现的 reference-prepare、段作者和宿主，重点补实际缺口与证据绑定。

### 5.2 主要改动

| 工作项 | 内容与决策 |
|---|---|
| NLP 输入边界 | 按设计 §5.4 校验 source_ref、原文跨度、有限 claims、未知项；host 提供来源，模型不能伪造确认身份。确定数值/枚举用受信规则复核，复杂语义待确认；有限修复重试，不无限重生成 |
| 参考图接入收敛 | 复用 reference-prepare，但先产需求/提案再做检索；只有派生/新建分支才组装完整 design，避免先自动建模板再查库。图例颜色需角色化确认，不把全图颜色中心直接当用户 Style |
| 四分支决策 | 原样/合法参数化直接返回，不产生新包；仅在确认的条件、能力和检索范围允许时派生/新建。只创建所需段；基础模板和验证搭档不能无记录地补成用户硬要求 |
| 草稿与正式版本分离 | 将受限 change-set 应用和正式发布版本分离；内部 draft_id/revision/digest 可带项目内合同身份。禁止派生时自动预占正式版本，也不调用旧 derive 后回改版本伪造旧证据 |
| 默认草稿终点 | validate passed 且无有效发布请求：succeeded/validate，输出 validated-draft 和证据后结束，不自动 next_step=prepare-publish。步骤同时检查 step/status，已结束运行不重开 |
| 明确发布动作 | 实现 publication-request 的 intent-only/ready 闭合分支；宿主用户动作与目标、所选段、草稿 revision 绑定。NLP 只提出候选，不能自行设置 save=true。TP 继续绑定最终包/目标/证据 |
| 延后保存 A→B | 已完成创建运行 A 不改写；新发布运行 B import-draft→author→validate→prepare-publish→publish。首版 B 按正式身份重新验证/渲染，不改签 A 的 run/context 回执 |
| 证据与恢复加固 | 需求、提案、确认、有效配色、宿主、参数、资源、对比报告闭合绑定；发布重验和中断恢复覆盖所有相关产物，状态回执与幂等机制复用，不造第二套状态机 |

### 5.3 现有参考图与验证实现的具体补齐项

这些是本轮静态发现后应纳入实施的检查点，不等于已复现失败，也不否定已经有的函数和调用链。

1. **输入限制在昂贵操作前生效。** 当前 intake 先 `read_bytes`、`img.load`，再检查字节/像素限制；目标实现先做受控大小/头信息与格式检查，再有界读取/解码。摘要从实际冻结的同一份 bytes 计算，避免再次读取变化中的路径形成不一致证据；异常信息不泄露业务路径/内容。
2. **快照不可覆盖且版本可追溯。** 图像、intake、proposal 按不可变 artifact 规则保存，同一 run 路径不能写入另一份图片覆盖旧来源；源许可与源摘要一起绑定。
3. **声明决定检查是否必需，不以文件存在性决定。** 当前 `_reference_comparison` 在 proposal 文件不存在时返回空检查。新链请求如果声明 reference 来源，所需图像/提案缺失、损坏或摘要不符必须失败；普通无参考段不受影响。禁止“删参考文件即可取消本次对比”。
4. **最终有效设计进入比较。** 当前 assembler 不会自动把 recovered 色板变成 Style 离散角色；必须显式确认类别语义/映射，比较器从本次有效合同及受信样张取色，不用 proposed_colors 默认冒充 effective_colors。无绑定的 canonical 宿主色只证明该验证搭档，不证明用户色已生效。
5. **测量报告和验收结论分开。** 当前颜色距离函数和 comparison passed 不能证明框/文字/图例语义都已恢复。增加需求驱动的覆盖项、独立标注基准与版本化阈值；未实现测量标记未覆盖，不泛称 round-trip 通过。提取误差、授权偏离、实现误差分别报告；不能为过关事后调阈值。
6. **blocker 不可由授权豁免。** `requires_authorization` 只能引导显式改色，不得解释为签一个“接受风险”就让原违规色发布；修改后的有效颜色再次走活门禁。warning 按现行等级披露并保存 findings/deviation。
7. **验证和发布重验对称。** 宿主身份/版本、案例集合、checker_set、字体/资源、参考证据均重验；重新渲染须明确对比所需输出摘要与原冻结目标，不只调用 render 而忽略新返回结果。按计划检查多 case，而非默认一幅样张替代全部允许组合。

### 5.4 状态转换必须落地的最小增量

| 输入/状态 | 行为 | 结果 |
|---|---|---|
| 用户只创建/保存项目文件；validate 通过 | 结束创建运行，保存项目草稿和证据 | 不生成 publication、不写索引、不消费 nonce |
| 创建开始前有受信 intent-only，最终已形成精确 ready 请求 | 按最终发布身份验证并继续现有 prepare/publish | 仍需有效 TP，缺审批保持等待 |
| A 已完成，用户之后要求入库指定 revision | 新建 B，绑定 A 的 draft/evidence，不修改 A | 新身份新证据；旧 TP 不能批准 B |
| 任一步失败、输入没变 | 原有受限 retry/recovery | 不覆盖已成功产物，不重复消费审批 |
| 用户改需求/设计/目标 | 新 revision 或运行、重新计算影响和发布对象 | 不通过失败重试偷换输入 |

PublicationRequest 是受信动作记录，不是模型接口字段。若当前宿主不能提供可验证的用户动作来源，CLI 明确请求/人工签署路径必须有定义；没有该接入时停在待确认，不捏造 user_action_ref。

### 5.5 代码与协议范围

- 输入/编排：`C/cli/template_cmd.py`、`match_cmd.py`、现有 `reference_segment.py`、`reference_intake.py`，第一阶段的 resolution 编排；按职责增加 NLP 适配/确认模块，不增加另一套生成引擎。
- 作者/草稿：`C/compiler/template_derivation.py`、`C/repository/segment_authoring.py`、`staging_package.py`、`C/workflow/segment_workflow.py`。
- 验证/发布：`C/workflow/segment_validation.py`、`template_workflow.py`、`C/compiler/reference_comparison.py`；必要时增加严格 evidence 子结构。状态机、审批和仓库事务原则上复用，仅按已评审扩展接点修改。
- 协议：复用并版本化 `template-proposal`，增加 NLP create 来源/确认绑定；扩展 `segment-create-request`、分析/Brief、段验证证据；新增 `publication-request`。ProjectDraft/ResolutionDecision 放在 design-resolution-result 分支，不另起九个 Schema。
- 现有 `template-publication`、`approval-receipt`、`step-receipt` 优先保持形状，通过精确输入/产物引用绑定新信息；确需改变时单独评审，不往旧对象塞未知字段。
- 依赖与文档：按需调整 `pyproject.toml`/Skill requirements 的可选依赖和懒加载，基础 CLI 不因 OCR 缺失失效；同步 SKILL、路由和创建说明的实际能力及默认不发布行为。

### 5.6 交付与退出条件

**交付物：** NLP/参考图统一入口、四分支结果、已确认提案与项目草稿、显式发布请求、A→B 审计链、有效比较/偏离报告、真实单包 TP 发布与引用回取证据。

**退出条件：**

- 对已准入能力，有精确候选时不创建；参数化命中不改包；派生/新建保留来源并产生可验证草稿。
- 未要求入库时，业务库索引和包集合字节不变；允许项目草稿/回执落盘，不把两者混为一谈。
- “保存项目文件”不能触发入库；自然语言或图像里的 publish 指令不能产生受信动作/TP。
- 指定保存 Layout 不连带发布 Style；先前草稿 revision、目标库或最终身份改变后旧对象/TP 拒绝。
- A 已成功结束后启动 B，A 不变；B 使用自己的上下文和验证回执，发布/索引中断可以幂等恢复。
- 自定义颜色有明确角色映射和实际消费证据；基线色与 effective color_scheme 不冲突，图体/独立与共享图例一致；无映射不能声明样式色通过。
- 声明参考来源后删改图像/提案不能跳过检查；未经明确批准的偏离不能当忠实提取，未实现指标不算通过。
- 既有渲染/段发布底座完成上述验收修复；目标路径必须真实渲染，不能仅依赖 mock 或源码中存在函数。
- 工程测试的合成签名与用户真实审批分开记录；正式用户入库无有效 TP 时停在 waiting_approval，不宣称任务已发布完成。

**本阶段不做：** 自动创建任意不支持的 Layout、自动升级执行策略、双包原子发布、GD 正式制图或完整 Athi River 地理重建。

## 六、阶段三：A3 双主图内置图例能力与复用验收

### 6.1 核心目标

将用户示例从“需求理解与检索判断正确，但执行不支持”推进为实际可用。先限定 **A3 横版、1×2 双主图、independent+inside**，不连带承诺 shared+inside、任意网格或自由布局求解。

### 6.2 主要改动

| 工作项 | 实施内容 |
|---|---|
| 合法组合准入 | 落地受评审新版本 `grid.allowed_cases`；没有消费者的组合保持未开放。删除重复权威来源，不能 allowed_shapes 与 allowed_cases 相互覆盖 |
| 正确生成包含关系 | 先生成每个 map 的 frame_id/content_id/几何，再根据作者声明的锚点、偏移、图例宽高/内边距生成 legend；同步 content_role、view_ids、inside_frame。不得复制旧基座中的悬空 ID |
| 图内几何/容量 | 内置图例不扣外侧图例栏宽；验证图例完全包含、与其他整饰无非法遮挡、文字实际测量和容量。保留旧版本多图基座拒绝和全局非法重叠门禁 |
| A3 全链一致 | 页面合同、输出 profile/constraints、验证宿主、场景、DPI/像素/内存上限、RenderScene、正式渲染和终检共同接入。不能只把 297 改成 420 或放宽检查以假装支持 |
| 案例集合与重放 | 每个模板声明的有限 case 都有对应验证、资源/代码指纹和重放记录；选择/交换/漏掉案例回执被拒绝 |
| 检索/生成再集成 | 同一需求在能力升级后由 unsupported 转为满足/可验证；已有模板参数化复用，不建立一份布局组合一个重复模板 |
| 发布后跨内容验证 | 替换标题、图例长标签/数量和两个视图内容，验证绑定与容量；只对本次有证据的范围作可用性声明 |

语义“图例位于图内”和“不会遮住真实地图重要区域”不是同一件事。阶段三需检查样张几何与内容容量；具体业务空间遮挡仍在真实地图任务中审查，不由单个 Layout 模板永久保证。

### 6.3 代码与协议范围

- `C/compiler/grid_layout.py`、`layout.py`、`page_bindings.py`、`raster_page_contract.py`、`vector_page.py` 及必要的 scene 编译器：只按目标注册后端范围接线，不一次开放所有 geometry/backend。
- `C/adapters/page_renderer.py`、`static_page_renderer.py`、`formal_renderer.py`：图内图例、页面测量、输出上限及摘要覆盖。已有绘制实现能复用的部分不重写。
- `C/scenarios/general_thematic/` 的 output/validation host/candidate 组件通过既有端口适配；通用内核不写入业务请求词汇或 import 具体场景。
- `S/layout`、`grid-parameters`、`resolved-layout`、`page-bindings`、`page-request`、相关验证证据协议按需要显式版本演进；`P/scenario-capabilities` 和 capability-roadmap 的语义修改由 steward 审核并评估冻结运行影响。
- 第一阶段的需求满足性组件：只更新可用能力和候选实例事实；不得把 A3/inside 判定硬编码为“特殊成功”。

### 6.4 交付与退出条件

**交付物：** 新版合法参数组合、A3 双主图内置图例 Layout、全部声明案例的真实预览/回执、精确引用复用结果、正式发布证据及能力范围说明。

**退出条件：**

- 用户示例在确认“各自主图一个内置图例”后，从需求→只读检索→合法复用或草稿→真实验证→默认返回的全链通过。
- 两幅主图角色和 ID 明确；每个图例只绑定自己的视图，contained-legend 求值与实际图面一致。
- A3 实际 PDF/PNG 页面尺寸和所选 DPI 符合登记输出；长文本/图例超限时明确拒绝，不偷偷缩字、删项或改图外图例。
- 相同合同/参数能在新运行按精确引用再用；更新库中版本不自动修改已冻结引用。
- 原有 A4、单图和已有合法网格回归保持，shared+inside 等未开放组合继续拒绝。
- 目标能力无缺依赖/缺字体跳过；最终复用、审批、篡改与恢复集成测试有明确记录。

**本阶段不强制包含：** inset 次级地图渲染、Athi River 全部上下文图层、任意地图表达或完整未发布 Scenario 直接制图。此类范围各自按专项计划登记，不借示例实现顺带开放。

## 七、GD 独立工作包：未入库段草稿用于正式地图

GD 是设计 §11.3 的独立子计划，不是第四实施阶段。可在前三阶段相关协议稳定后另行启动，必须独立估算、评审和验收；未启动时主计划的结果说明清楚保留此限制。

**前置条件：** 阶段二已能产生作用域清晰、不可变、真实验证的 ProjectDraftRef；目标场景/后端已经支持该合同；必要需求、来源和验证证据协议稳定。

| 横切面 | 主要落点与要求 |
|---|---|
| 生成请求/段来源 | `generate-request`、场景请求 overlay 与来源解析端口；published XOR project-draft，明确 project/tenant、revision、摘要、证据 |
| S2 所有权 | 复用 `segment_refs / replaceable_segments` 的约束；只对允许替换的段增加草稿来源，不允许任意替换 |
| 仓库与草稿解析 | published 继续原 discover/fetch 门禁；草稿走受控项目解析器，物化共同合同视图。不得让 repository 假认草稿为 published |
| 数据准备/候选/锁 | `map_candidate`、准备与 portrayal、MapSpecLock/相关解析产物；绑定有效合同及 baseline/effective 色、资源、参数和证据 |
| 正式渲染/终检/恢复 | 只消费冻结引用；保持 G1/G2/G3、成品检查及交付恢复，不把没有 TP 理解为没有审批 |

**GD 完成标准：** 相同合同分别来自合法 published ref 与 project draft 时，在相同设计参数下图面/形式检查一致，差异仅在来源和授权链；跨作用域、非 replaceable 段、证据缺失、锁后改草稿/资源均拒绝。必须证明整个过程没有暗中发布草稿。

不扩展到未发布完整 Scenario、不支持双包原子发布，不以删除 `_verify_installed_template()` 中的 published 检查作为实现。无 GD 时用户可得到设计文件和预览，但正式地图使用必须明确走当前支持的来源，不可由系统代替用户入库。

## 八、协议变更、共享依赖与实施顺序

### 8.1 协议复用矩阵

| 协议/对象 | 本计划处理 | 主阶段 |
|---|---|---|
| DesignRequirement + predicate | 新最小协议，含候选/确认分支与受信事实求值 | 一 |
| CandidateAssessment/SearchContext | 放入受评审 match 请求/结果版本或闭合子结构 | 一 |
| ResolutionDecision/ProjectDraftRef | design-resolution-result 的分支，不建第二模板库 | 一定义、二消费 |
| DesignProposal | 复用 template-proposal，新增 NLP create 来源及严格 recovered/change_set/确认 | 二 |
| 确认后的作者输入 | 复用 segment-create-request，新版本绑定需求/提案/发布控制 | 二 |
| PublicationRequest | 新 intent-only/ready 动作记录；非 TP | 二 |
| 验证证据 | 复用 segment/template validation evidence，补覆盖/需求/来源/对比及新案例绑定 | 二、三 |
| 发布对象、回执 | 尽量复用 template-publication、publication-receipt 与现有 TP | 二 |
| Layout 内容角色/参数域 | 第一阶段完成最小角色与求值，新组合实际实例化在三交付 | 一、三 |
| 草稿正式制图来源 | GD 单独版本化请求/来源/锁等，不提前混入主计划验收 | GD |

### 8.2 开工时必须冻结的决策

这些工作归入阶段一，不新增“阶段零”：

1. 工作区快照、未提交变更归属和上游并行开发接口；已有成果按复用清单认领，不覆盖用户修改。
2. 需求谓词/角色最小版本、现有 inset 字段与目标角色的唯一权威表示。
3. 协议版本清单及生产者—消费者配套；没有消费者的新字段不得以“Schema 通过”宣布功能完成。
4. 检索候选预算、标签来源/排序、unknown/不完整搜索的返回规则。
5. validated-draft 结果和 publication-request 与现有步骤的映射；B 重新验证的明确成本。
6. 基于已准入单图/网格能力选择 MVP 正反例；A3/inside 正例放到阶段三，之前保留未开放反例。
7. 阶段二真实参考样本的授权、元素/指标覆盖和人工确认方案；角色、数据值、字体、资源不明时的阻断规则。

**建议首个代码批次：** 需求协议与纯求值器 → 内容角色事实视图 → 参数域/候选报告 → 只读 match 接入。先从结构化需求和合成合同证明 N02/N03/N04/N05，再接 NLP，不一开始就同时修改审批和渲染器。

### 8.3 工作量与变更边界

不复用旧“多少文件即可完成”的粗估作为预算。按四类规模分别认领：

- 阶段一主要是协议、纯求值、结构化检索；难点是确定性语义与旧能力不回退。
- 阶段二主要是状态/来源/证据/审批横切；已有 reference 与 segment 代码能复用，但安全绑定和真实验证不可省略，是主闭环高风险部分。
- 阶段三是编译/渲染/策略组合能力；按允许 case 与实际后端估算，不按“多一个参数”估算。
- GD 独立影响生成请求、解析、候选、锁和恢复，单独资源预算与责任人；不塞进“草稿保存”小任务。

阶段一评审输出逐文件清单、接口负责人、前后版本和回归影响表后，再作工期估算。跨阶段修改同一文件只登记一次基线归属，不允许两个分支互相覆盖协议语义。

## 九、验证计划与完成判定

### 9.1 按 AGENTS.md 执行回归

开发迭代执行受影响测试及必要边界守卫，不因局部改动无条件全量；涉及共同协议、安全、审批、摘要、策略语义、共享基础设施或影响范围不清时升级全量。本计划多处涉及这些高影响项，阶段退出应按实际合并范围安排完整回归，但不把每次小修都变成全量运行。

- 工程测试仅在用户允许后执行；本次文档任务不执行项目测试。
- 局部通过、全量通过、真实渲染通过、业务 TP 验收分别表述。
- 跳过不算通过；目标能力的环境缺项必须补齐后实际验证。依赖和字体安装须单独授权，不为验证自动改变环境。
- 四项 `test_layer_ports / test_encapsulation / test_digest_coverage / test_scenario_boundary` 棘轮只紧不松；新增改变产物的代码/Schema/策略纳入指纹。
- 对既有错误先记录基线及归属，不删测试、不放宽门禁以换取绿色结果。

### 9.2 与设计验收编号的映射

| 阶段/工作包 | 主要验收编号 | 新增重点 |
|---|---|---|
| 阶段一 | N02/N03/N04/N05/N07/N08；F01–F08/F15/F16 | 逐谓词、角色、参数域、授权检索、只读索引不变、合法实例与未知信息 |
| 阶段二 | N01/N06/N09–N14/N17/N18；F09–F13 | NLP 不造硬条件、不自动发布、草稿终点、A→B、角色色与偏离、证据漂移 |
| 阶段三 | N04/N05/N16；F04/F06/F07/F14 | 新组合成功与旧边界拒绝、页面尺寸、图内绑定、所有声明案例 |
| GD | N15，加来源/锁/恢复专用反例 | 未发布草稿真实制图、跨作用域拒绝、无暗中入库、G1/G2/G3 保留 |

编号来自修订设计，N16/F06 随准入版本分别保留“未实现时拒绝”和“已登记组合成功”的例子，不能简单删除旧边界守卫。N13 按现行颜色修订协议区分基线改变和有效色覆盖，不机械强制所有换色都重做 GIS 统计。

**代码测试落点：** 复用现有 `test_template_matching`、`test_template_proposal`、`test_reference_intake`、`test_reference_comparison`、`test_reference_segment`、`test_segment_authoring`、`test_segment_workflow`、`test_segment_refs`、`test_grid_layout`、`test_layout_contract`、`test_schemas`、颜色/准备/正式渲染及恢复测试；按功能新增需求求值、resolution、草稿生命周期与发布动作测试，不以开发阶段编号命名新测试。

### 9.3 每阶段验收包

每阶段提供：

- 文件/协议/策略变更清单及摘要失效说明；
- 合法/非法样例、测试命令与通过/失败/跳过实数；
- 真实预览与 RenderReceipt，发布阶段另附有效 TP/发布回执；
- 已验证参数/字段/来源范围，以及未支持项、数据/许可阻塞；
- 来源、需求、草稿、验证、发布对象的可追溯引用；
- 失败恢复与版本冲突说明，不给出“手改锁/回执”的修复步骤。

## 十、上线与范围控制

| 风险/依赖 | 控制办法 |
|---|---|
| 当前工作区快速演进，设计快照容易过时 | 每阶段开工重新核对源码；存在函数不等于通过验收，已有工作也不从零重做 |
| 模型误读用户要求 | 候选/确认分离，明确来源和确定转换；复杂歧义不能直接成为 hard 门禁 |
| 引入新的角色/参数字段导致半接线 | 协议、作者、编译、验证、重放、正反例同批配套；unknown/未开放不当通过 |
| 参考对比只报数值却判成功 | 覆盖、有效色、独立基准和阈值治理；缺证据失败，不按文件存在性取消检查 |
| 草稿保存变成自动发布 | 显式 PublicationRequest、默认终点、索引不变测试、TP 精确对象检查 |
| A3/inside 和 GD 范围膨胀 | 阶段三限定单个可执行组合；GD 单独立项，不借主流程放开所有场景和后端 |
| 真实数据、字体或许可不足 | 受控合成输入证明组件；真实场景另行补输入/许可，不假造原图地理数据或审批 |
| 改政策或协议导致冻结执行漂移 | 由唯一 steward 评审必要语义变更；精确引用和新运行重验，不静默迁移 |

**完成口径：** 阶段二交付的是“已有能力范围内的检索复用、项目草稿及按需入库闭环”；阶段三再交付“A3 双主图内置图例”的实际能力；GD 只有独立验收后才宣称支持“不入库而直接正式制图”。三者不能互相代替或合并成一句“全流程已完成”。
