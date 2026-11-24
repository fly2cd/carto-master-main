# 参考图 → Style / Layout 模板入库实施计划

| 项目 | 内容 |
|---|---|
| 日期 | 2026-11-23（Asia/Shanghai） |
| 状态 | 设计方向已批准；裁决 1–7 及 P2-1/P2-2 均已拍板；阶段一地基已交付段作者/段协议/类型化编排/CLI（验证见实施进度节），验证宿主渲染待实施；不表示能力已开放或验收完成 |
| 调查基线 | 2026-11-23 工作区代码，包含未提交修改；各阶段开工前重新核对源码、Schema、策略和测试基线 |
| 目标样本 | `doc/sample/Athi_River_LULC_map-2023.png` |
| 实施阶段 | 3 个：段模板正式闭环 → 参考图提取接入 → 样本能力补齐与完整验收 |
| 唯一实现根 | `skills/carto-agent/`；继续使用现有 `carto create-template` 与模板仓库 |
| 文档性质 | 设计与排期依据，不是运行时协议、业务授权或模板发布审批 |

**决策状态（最终实施版）**：设计方向已获用户批准。**已拍板**：创建侧颜色权威走路径 A（准备前显式配色、preparation 冻结）；平台验证宿主解决搭档自举与渲染入口；逐元素准入与数据来源矩阵前置到阶段一；红线冲突无豁免、显式改色记 deviation；版本规则“加法不升版/语义升版”（P2-1）；置信度语义纠偏（P2-2）；生成侧“预览后换配色”走设计修订回路（裁决 4），色带键复用 `color_scheme`、局部修订顶层键合并 + 强制 diff 守卫；**前置裁决 5/6/7（类别码键与优先级代数、共用图例组作用域、审批色带可见）已于 2026-11-23 用户拍板，裁决 4 开工限制解除**。本文 file:line 锚点与样本配色定量结论均经 2026-11-23 一手复核。实施起点：阶段一地基（类型化编排+段作者+验证宿主）。

## 实施进度（2026-11-23，阶段一地基）

**已交付并验证（加法演进，scenario 路径零改动）**：

| 增量 | 内容 | 验证 |
|---|---|---|
| 段作者与打包 | `repository/segment_authoring.py`：确认设计→闭合 map-style/map-layout 段包（无 business_contracts/prototype，lock 钉身份摘要）；`staging_package._verify_closed_package` 按 business_contracts 存在性分支（scenario 逐字保留） | test_segment_authoring 7 项 |
| 段协议 | 新增 `segment-create-request`/`segment-analysis`/`segment-brief` 三 schema（段无 sources/CRS/data_roles，复用 evidenceRecord）；fixture 正反例 | test_schemas 覆盖 |
| 类型化编排 | `workflow/segment_workflow.py`：`SegmentCreationWorkflow` 子类重写 analyze/brief/author/validate/_expected_validation/_resume_request/_verify_for_publish，复用父类状态机与 publish 链（无第二套状态机）；`create_template_workflow`/`create_workflow_for_request` 封闭 kind 分派 | test_segment_workflow 9 项 |
| CLI | `create-template` 按请求 kind 分派；validate 补 `--repository-root/--repository-scope` | test_ide_integration 9 项 |
| 段验证宿主与发布全链 | `validation-host`/`segment-validation-evidence` schema；`workflow/segment_validation.py` 静态检查+证据组装；宿主构建移入场景注册组件 `segment_validation_host`，内核经 `ScenarioRegistry.for_segment_validation_host().component()` 钩子复用 validation_scene 与通用渲染器（不静态导入场景）；父类 `_verify_for_publish`/`_evidence_schema` hook 小重构（行为保持）；空库 style/layout 验证+TP+发布+重验全链跑通 | test_segment_workflow 空库发布 2 项 |
| Path A 颜色权威（解析契约） | 离散分类请求加 optional `category_colors`（值→大写 hex 单一权威）；`resolve_classes` style 模式消费权威色、palette/CSV 色列冲突拒绝、答案不得覆盖绑定色、准备期红线；无 category_colors 时 legacy 路径逐字不变；失效链经 request_digest 继承 | test_path_a_colors 7 项 |
| 裁决5 角色色抬升 + Path A 宿主接色 | `compiler/style_colors.py` 纯解析器：Style 离散角色色经角色↔类别码绑定抬升为值→色 category_colors（缺角色/冲突拒绝、大写归一、按值排序）；validation_scene/宿主/组件协议/内核贯通 category_colors，段验证宿主用待验 Style 色渲染；不同样式色→不同样张 receipt | test_style_colors 7 项 + 样式驱动渲染验收 |
| 裁决4/6/7 换色修订回路 | color_scheme 升顶层闭合修订键（scope+值→hex），rules 仅失效编译节点、bundle_input_keys 不变（数据包复用）；apply_color_scheme/overlay_legend_colors 编译期生效色映射（未知类别/重复拒绝、红线、组级图例同源）；compile_page_request/候选编译器/request_contract 贯通 revised_color_scheme；map-brief design_changes 加法字段 + refresh_brief 改色条件必填色带表 | test_color_scheme_revision 12 项 |
| 阶段二参考图纯模块 | P2-2 置信度纠偏（field_sources 区分 user/backend 与测量置信度，人工补充不再虚高为 1.0）；reference-intake schema + 安全 intake（PathGuard/字节像素格式限制/冻结源摘要尺寸DPI许可）；提案→段设计闭合装配（未完成必需项拒绝）；reference_comparison round-trip 三分（恢复误差/授权偏离/实现误差）+ 红线偏离证据（MCP-ready 纯函数） | test_reference_intake 9 + test_reference_comparison 5 + P2-2 同步 |
| 阶段二工作流编排闭环 | reference_segment 编排：prepare_reference_segment_request（intake→extract→装配→草稿 segment-create-request，intake/proposal 冻结为证据、摘要与恢复误差经 decisions 绑定流向 analyze→brief→TP）；compare_reference_render（验证后 round-trip 三分 + 红线偏离，调用者绑定 TP）；草稿请求贯通段工作流 analyze→brief→author（零第二状态机） | test_reference_segment 5 项 |
| 阶段二收尾（对比自动布线 + CLI） | prepare 冻结参考图副本（受控证据目录，不入库）；段验证器 validate 样张渲染后自动计算 round-trip 三分 + 红线偏离，经 results→evidence_digest 绑定 TP（偏离 blocker 失败关闭；无参考证据的普通段零影响）；CLI `create-template reference-prepare`（配置 YAML→非权威草稿请求） | test_reference_segment validate 2 + CLI 1 |
| 阶段三比例尺机械计算核心 | `compiler/scale_bar.py` 纯函数：由目标空间配置（地图地面宽 m×像素宽×比例尺框宽）机械选 1/2/5×10^n 整数距离、适配框宽、m/km 标签；不猜 EPSG、不固化 90km、不派生几何；渲染器已消费 scale_bar，待页编译器接线 | test_scale_bar 8 项 |
| 阶段三 inset 声明机械校验核心 | `compiler/inset.py` 纯函数：inset 须为真实次级地图视图（独立 extent + 主图关联 + 可选高亮 id），严格包含于 map 帧（声明 inside_frame + 完全 enclosed）；拒绝贴图冒充（无 view extent）、非法 extent、缺主图关联；不猜 EPSG、不派生几何；待 layout 解析器准入 + 次级视图渲染接线 | test_inset 9 项 |
| 阶段三 inset layout 准入 | layout.schema/resolved-layout.schema 加 inset 类型与 view/main_map_ref/highlight_id 字段（加法）；layout.py 准入 inset（overflow clip、强制 inside_frame、调用 inset 校验、携带 view_extent/main_map_ref/highlight_id 元数据、place_overlays 跳过 inset 视为次级地图帧）；resolver_version 不变（加法）；既有 layout/grid/段引用零回归 | test_inset layout 准入 5 项 |
| 准入登记 | capability-roadmap `segment-validation-host` 升 delivered（v1.0.3） | test_capability_roadmap |

**修复**：① staging 分支初版误读 `manifest["package"]["kind"]` 致最小 mock manifest KeyError（test_framework_contracts），改以 business_contracts 存在性判据修复。② 段验证初版内核静态导入场景模块触发边界棘轮（test_scenario_boundary），改为经注册组件钩子获取场景行为（宿主构建移入场景侧 `segment_validation_host` 组件）。③ 文件字节摘要误用 JSON 规范化 `sha256_digest`，改 `file_digest`。④ 5 个 CliMatchTests 错误（`template match` 命令被误操作移除、argparse SystemExit）：新建 `cli/match_cmd.py` 恢复只读咨询匹配命令（暴露存活的 rank_segment_candidates/segment_candidates 算法）并注册到 CLI 装配壳，test_template_matching 31 项绿。⑤ 首轮全量回归暴露 1 失败 + 2 错误：style.new_value 被过度闭合为仅 typography（拒绝完整 style 合同修订）→ 放开为顶层键合并（闭合校验 downstream 于 style schema）；test_override_keys 旧断言补 revised_color_scheme。重跑确认清零。

**尚未交付**：阶段三剩余逐元素能力（见下方开工核对）。阶段一颜色链 + 阶段二参考图闭环已经全量回归确认（809/809 failures=0 errors=0）。注：样式段未绑定离散角色时，样张用宿主 canonical 色，round-trip 实现误差会如实偏大（Path A 颜色权威需角色↔类别码绑定才驱动样张色）——对比报告作为人审证据如实呈现，不静默豁免。

**阶段三开工核对（2026-11-23 一手核验）**：
- **比例尺/指北针**：渲染器（static_page_renderer/page_renderer/svg_compositor）已完整消费 scale_bar/grid_north；但页编译器（raster.py:193/988、vector_page.py:106）硬编码 None。比例尺机械计算核心已交付（scale_bar.py），**待页编译器从目标空间配置接线**；指北针方向（grid convergence）计算待补。
- **inset 定位图**：**声明校验核心 + layout 准入已交付**（inset.py 校验；layout.schema/resolved-layout.schema 加 inset 字段；layout.py 准入 inset、携带 view_extent/main_map_ref/highlight_id 元数据、place_overlays 跳过 inset 视为次级地图帧；加法不升 resolver_version）。**待次级视图渲染接线**（raster 编译器/渲染器在 inset 帧渲染独立地图视图，合成视图验证，不裁原图冒充）；roadmap composition-inset 待渲染交付后升档。
- **混合图例/外观效果**：线面分组图例、阴影/背景弱化/文字描边待逐项接入。
- **阻塞于真实数据准入**（计划启动条件未满足）：分类栅格、河网、流域边界、县界、淡化底图、真实 LULC 类别码——需许可数据、责任人、格式/CRS/范围/摘要到位；无数据必需项保持阻塞，不临时派生几何凑数据。合成数据只证明消费者功能，不证明真实地理分布恢复。

**并行修改说明**：实施期间检测到工作区有并行修改——`segment-validation-evidence.schema.json` 被重构为更贴近 template-validation-evidence 的形状（namespace/package_ref/manifest_digest/dependency_lock_digest/checker_set_digest/status/counts/results/renderer/render_receipt_ref…），`segment_validation.py` 已同步一致（test_segment_workflow 10 项绿）；style typography 字段、general_thematic 导出亦有调整，本计划新增代码已适配当前状态。

**回归基线（已确认）**：全量 **809/809** 例，29.19 分钟，**failures=0、errors=0、skipped=9**（环境依赖：独立 GIS 服务解释器/符号链接创建受限）。首轮发现的 1 失败 + 2 错误（style.new_value 过度闭合、test_override_keys 旧断言）已修复并重跑确认；5 个 CliMatchTests 错误经恢复 `template match` 命令清零。阶段一颜色链 + 阶段二参考图闭环经全量回归验证。

## 一、目标、范围与实施约束

### 1.1 完成定义

把参考图中经确认的版面组织和视觉规则转换为可复用的 `map-layout`、`map-style` 包，经过真实样张验证、精确 TP 审批和现有仓库发布后，能在新运行中按精确引用取出并实际影响渲染结果。

完整链路为：

> 受控参考图 → 冻结分析证据与提案 → 人工确认设计 → 完整段合同 → 暂存包 → 静态检查与真实渲染 → 冻结发布对象 → TP → 入库 → 新运行引用复用。

以下不算完成：仅输出 YAML；直接复制文件到模板库；使用开发种子脚本写入索引；通过 Schema 但没有渲染消费者；把整幅参考图作为背景贴图来代替可编辑模板。

### 1.2 固定范围

1. **先半自动、后提高自动化。** 允许人工标注图例区域、确认元素角色、补充布局与字体；不以训练专用模型或部署 MCP 服务作为闭环前提。
2. **保留独立段。** Layout 管位置、尺寸、内容接口和容量；Style 管可复用外观。地点、年份、地理范围、真实数据类别码及实例统计不固化进通用段模板。
3. **首版采用单包发布。** 同一份已冻结分析成果可以服务两个创建运行；Style、Layout 分别验证、分别绑定 TP。不宣称两包原子发布。
4. **不增加假业务场景。** 模板类型分派与业务场景分派分离；MapScenario 继续使用现有场景组件，不为 Style/Layout 创建虚构业务场景。
5. **不增加发布旁路。** 提取器只生成候选和证据，不读写模板仓库、不签发审批；人工确认设计不等于 TP。正式地图生成仍遵守 G1/G2/G3。
6. **不扩大生产准入。** 本计划完成不自动开启 `production_enabled`，不代表真实业务数据或地图交付已获批准。
7. **不承诺恢复原始地理数据。** 无原始工程和数据时，验收 Layout/Style 的恢复与复用，不宣称重建了原始 CRS、类别编码或全部土地覆盖像素。
8. **预览后换配色是设计迭代，不是数据变更。** 用户在 preview 后更换配色必须能走设计修订回路：只重编译/重渲染，复用已冻结数据证据与 GIS 统计，不重新澄清数据语义。该回路不豁免任何审批（G1 重签修订简报、G2 重签新候选），不绕过配色红线。

### 1.3 与现有计划的关系

本计划是[模板生命周期实施计划](template-lifecycle-implementation-plan.md)中“来源提取、独立段创建、验证发布与复用”的专项细化，不另建模板平台。该历史计划中的 T1、品牌段等旧边界不作为本次实施依据；以当前代码、Schema、Skill 和经评审的能力策略为准，不恢复已移除的审批或模板类型。

遵守[设计原则](../design-principles.md)：CV 测量可见事实，LLM/作者提出语义和设计，程序执行形式验证与机械推导，人工确认不能替代安全门禁。

## 二、现状与关键缺口

下文缩写：`C/` = `skills/carto-agent/scripts/carto_core/`；`S/` = `skills/carto-agent/schemas/`；`T/` = `skills/carto-agent/scripts/tests/`；`P/` = `skills/carto-agent/policies/`。

| 当前基础 | 尚未完成的连接 |
|---|---|
| `C/compiler/reference_extraction.py` 已独立为纯函数，支持人工 Layout/typography 及注入后端 | 没有接入正式创建工作流；全图聚类丢失类别语义；同图同算法颜色比较不是真正的渲染闭环 |
| 已有 `template-proposal`、`style`、`layout` Schema | 提案内部 `recovered` / `change_set` 不够严格；部分声明字段尚无消费链 |
| 现有创建工作流、状态锁、回执、TP、仓库事务可复用 | 分析器仅允许 MapScenario；Brief 固定场景类型；暂存校验、作者和验证器仍依赖场景六合同 |
| 段模板可按精确引用取出并物化进 Scenario | 读取能力不等于独立段已具备正式创建与渲染验证入口 |
| `style` 命名已进入合同和页面链路 | 分类栅格颜色仍主要来自已确认分类合同；仅写入 `ramps` 不会自动改变地图 |
| Layout 有包含关系声明；矢量页已有部分底图、层序和 halo 支持 | `inset` 尚未进入 LayoutResolver 的执行类型；不能将矢量页能力推定为栅格组合全链支持 |
| 工作流 `validate()` 已能接收仓库参数 | 当前 CLI 未完整暴露并传递对应参数，段引用验证入口需要补齐 |
| 设计修订回路已存在：样式类变更只失效编译节点（`revision.py:19-25`），`bundle_input_keys` 不含颜色（:27-28），数据包可复用（`map_generation.py:1090-1114`） | 修订词表 `color_scheme`（`design-revision-proposal.schema.json:61-63`）仅有形状测试（`test_design_revision.py:167`），**零渲染消费者**；分类颜色冻结在 prepared report 内，`prepared_raster_bindings.prepared_ref` 钉住整份报告摘要（`general-generate-request.schema.json:399-417`），今天换色使 `bundle_input_digest` 失配、GIS 证据被连带作废 |
| 连续分支色带在准备阶段消费（`raster_preparation.py:169`），红线在冻结前执行（离散 `raster_portrayal.py:215-218`、连续 `raster_preparation.py:176-177`） | 离散分支无设计层换色入口；`request_contract.apply_overrides` 对 style 是整段替换（`request_contract.py:96-98`）而对 `output_profile` 是字段级合并（:102-105），两条 override 路语义不一致；修订词表允许的 `legend_style`/`scale_bar_style` 在 style 闭合 Schema 中无对应字段（实测零匹配）。合并语义已裁决，见裁决 4 |

本次调查已完成 CLI 帮助和 93 个 Schema 自检，但未执行完整回归。已确认的 `.venv` 缺少图像分析及静态渲染依赖；环境准备须使用真实 Python 3.11+、显式可选依赖和授权安装，不能把缺依赖造成的跳过作为验收通过。

## 三、三阶段总览

| 阶段 | 核心目标 | 输入 | 主要交付 | 退出条件 |
|---|---|---|---|---|
| 阶段一：段模板正式闭环 | 先让确认后的 Style/Layout 有正规作者、验证和发布路径 | 人工确认的严格提案、合成验证内容 | 类型化创建流程、段包、样张证据、发布及取用测试 | 两类段均能独立验证、经 TP 发布并在新运行中实际消费 |
| 阶段二：参考图提取接入 | 用真实图像证据生成第一阶段可消费的提案 | 受控 PNG、标注及人工补充 | 冻结分析成果、提取提案、对比报告、限定范围样本包 | 已选能力从原图到入库贯通，来源与修改全程可追溯 |
| 阶段三：样本能力补齐与完整验收 | 补齐 Athi River 约定范围内的制图能力并验证复用 | 前两阶段成果、完整样本验收清单 | 必要渲染扩展、样本段包、完整验收及复用报告 | 必需元素无静默遗漏，完整发布链及新任务复用通过 |

顺序为 **一 → 二 → 三**。开工核对、协议评审和环境准备纳入第一阶段，不额外设置“阶段零”。第二阶段可达成有限范围的真实闭环；若第三阶段仍有必需能力未完成，不能将其描述为完整参考图恢复。

## 四、阶段一：打通独立段模板的正式创建、验证与发布

### 核心目标

暂不依赖自动 CV，以人工确认提案证明“设计值能进入合同、合同能控制样张、样张证据能绑定发布、发布段能被新运行使用”。

### 主要改动

| 工作项 | 实施内容 |
|---|---|
| 协议与范围冻结 | 按模板 kind 明确必需字段；段模板不强迫填写无关的业务数据角色/CRS。提案允许显式未知项，但 Author 必须拒绝所选段的未完成必需项；内部未知字段默认拒绝。冻结首版实际消费字段及适用范围 |
| 类型化编排 | 复用 `analyze → brief → author → validate → prepare-publish → publish`；通过封闭注册分派 Scenario、Style、Layout，不只是删除入口 kind 拒绝。补 CLI 的 validate 仓库参数 |
| 段作者与打包 | 将确认的设计组装成完整合同；复用闭合包、校验和、依赖锁、不可变版本。暂存检查拆为公共文件完整性与按 kind 的合同检查 |
| 段验证样张 | 平台版本化 validation host 提供互补 Style/Layout 和合成内容，不依赖已有发布段。类型化验证计划替代场景专用样张构造，下游复用现有页面编译、正式渲染和回执验证；宿主及资源精确绑定 |
| 最小消费链 | 先贯通版面框、字号和六类离散颜色。选择路径 A：准备前解析样式并传入显式类别配色与映射，在 preparation 内冻结颜色；portrayal/page 默认只验证和消费基线色，不做未声明的晚绑定替换。同步分类请求、澄清答案、prepared report、图例和失效链。生成侧换色迭代另走裁决 4 的声明式设计修订回路，与 A 共用同一映射/红线/图例机制 |
| 换色设计修订回路 | 复用修订词表 `color_scheme` 键并接真实消费者：编译期按类别码（数据值）映射生效色（键空间见裁决 5），只失效编译节点、复用数据包；红线对生效色执行并持久化 findings；图例与地图同用生效色；映射与来源摘要冻结进候选并绑定 G2。局部 style 修订采用顶层键合并语义 + 强制 diff 守卫。详见裁决 4 |
| 发布与复用 | 单段复用现有 TP 与仓库事务。包/证据摘要必须闭合绑定确认后的设计。增加发布后新运行取用测试，不让场景内置默认值替换已发布设计 |

**包内路径约束：** 当前 `SEGMENT_CONTRACTS` 将 map-style 映射到 `contracts/cartography.yaml`，Schema 名为 `style`。本计划首版保留该文件路径约定，不顺手进行全仓更名，也不增加双路径兼容读取。

**版本约束：** 编排重构与能力协议演进分开评审。重构不得改请求/提案形状或策略语义；确需新字段的能力按显式新版本设计并评审，不原位改写冻结对象、不增加旧格式 wrapper。能力策略语义变更由 steward 评审，受影响运行重新准备/冻结，不自动迁移。**版本规则裁决（P2-1）：** 与既有加法演进先例（`style.schema` 在 v2 内新增可选 `ramps/symbol_roles` 等、旧字段标 deprecated、不升版）调和——**加法可选字段不升版**（沿用先例，配合法/非法样例与棘轮守卫）；**语义、必填集或形状变更显式升版**（如生效色映射改变图例一致性 invariant 与确认含义，属语义变更）。不得以“新增字段”为由对纯加法制造版本 churn，也不得借“加法”之名偷改语义。

### 阶段一必须落实的设计裁决（1–4）

#### 1. 颜色权威采用路径 A，保留准备阶段冻结时序（P0-1）

**裁决：选择 A，不采用 B。** 场景规划/创建编排在调用分类准备前解析已确认 Style，传入显式类别配色。连续分支的 `color_ramp` 可借鉴其前置传参机制，但离散类别必须使用稳定语义键和数据值映射，不能照搬顺序色带、插值或按图例序号猜类别码。

> 已确认 Style（已发布段或待验证草稿）→ 冻结显式类别配色与数据值映射 → 分类请求 → preparation/clarification → ready report → resolved portrayal → 地图与图例。

- **来源绑定：** 请求携带解析后的值及可核验的样式/映射来源摘要；准备服务不检索“最新 Style”。已发布 Style 使用精确包引用并校验取出的合同；首次段验证使用暂存合同的不可变 artifact 引用，不伪装成已发布 templateRef，不产生验证自举依赖。
- **单一权威：** 新版本请求显式选择 Style 映射、CSV 色列或登记 palette 中的一种。Style 模式不把 CSV 颜色和 `carto-categorical-v1` 当第二权威，冲突配置拒绝；CSV 仍可提供类别码/标签。缺少必需色值或映射进入澄清/拒绝，不自动补色。
- **澄清边界：** 现有答案能覆盖 `color`，必须补来源一致性检查。在 Style 模式下，答案不得任意替换已绑定色值；改色先形成新设计决策和分类请求，再生成基线及答案。类别语义、隐藏/显示等修改仍须明确声明和复验。
- **失效链：** request、request_digest、report rows/来源、algorithm_digest 和答案 `based_on_digest` 覆盖新配色输入。`based_on_digest` 继续绑定精确基线分析，不退化为只绑定 TIFF。本次设计改选/修改被绑定的 Style 或映射后，旧报告/答案不得用于新设计，下游 portrayal/page/scene 重新准备、验证，不原地改 rows。仅向仓库发布 Style v2 不自动使仍精确引用 v1 的独立旧运行失效；代码/策略漂移另按现行治理规则处理。创建侧改绑 Style 触发重准备时，安全复用 GIS 统计不作为本期前提，禁止伪造统计回执（生成侧换色修订的数据包复用另见裁决 4，两者不矛盾）。
- **协议横切：** 显式评审 `raster-classification-request`、`raster-classification-answers`、`raster-prepared-data` 及相关引用/版本解析。答案即使保留字段形状，其语义检查和回归也必须更新；不机械增加字段，不原位改变冻结对象的含义。
- **门禁时点：** 现有离散 `_resolve` 冻结颜色、portrayal 执行红线，连续准备分支已有红线。新增离散路径在准备/澄清形成最终颜色时执行同一策略并保存 findings，portrayal 保留复验；页面编译不得成为**未声明的**改色入口——仅允许裁决 4/5 定义的、带来源摘要且经 G2 批准的生效色映射，不得引入默认色或静默改色。

**不选 B 的理由：** 后移颜色将改变 ready report、澄清答案和冻结图例的职责，要求拆分数据就绪/显示就绪并调整更多摘要链。A 的代价是被绑定的样式配色变化触发重新准备，本次接受该成本。**该成本仅指创建侧权威来源变更；生成侧“预览后换配色”的迭代成本由裁决 4 的修订回路单独解决，不以 A 的重新准备为满足。**

**必测：** Style v1 的答案不能用于 v2；类别映射变色/换序；CSV/Style 冲突；用答案覆盖 Style 颜色；只换页面 Style 却沿用旧准备报告。不得出现地图/图例各用一套颜色。

#### 2. 平台验证宿主同时解决搭档自举与渲染入口（P0-2 / P1-1）

**裁决：使用平台 validation host，不要求先有已发布业务段；宿主只组装验证输入，不新增页面引擎、不注册合成业务场景。**

1. **平台资源：** 建议新增 Skill 内 `resources/validation-hosts/<id>/<version>/`，含严格清单、互补 Layout/Style、案例、合成输入/生成器引用。资源不进入业务索引、不取得 `published` 身份；运行时不读 `scripts/tests/` 或 `doc/`，不增加第二个 CLI。
2. **空库自举：** Style 验证注入待验证 Style，取宿主固定 Layout；Layout 验证反之。待验证合同按 artifact 摘要绑定，无须先发布。首个 Style、首个 Layout 必须均能在空模板库验证并经正常 TP 发布。
3. **复用渲染链：** `segment_validation` 校验并产生类型化案例，在受信工作区构造合成输入，调用现有准备服务和授权 ToolGateway 取得数据证据；再经已有 portrayal、LayoutResolver、page/bundle 与 Raster/VectorSceneCompiler 形成 RenderScene；使用 `create_render_backend → FormalRenderer → PageRenderer/MeasuredPageRenderer` 出图和签发/核验 RenderReceipt。不直接画图冒充回执，不伪造 bundle 或 GIS 统计。
4. **拆分场景耦合：** `_check_schemas`、身份/所有权检查、`_validation_cases`、`_scene`、`_check_semantics`、`_check_targets`、`_verify_grid_cases` 的场景逻辑留在 MapScenario 策略；上下文/预期校验也不再强迫段请求提供业务 CRS。公共验证器通过类型化接口获得案例集合、输入、目标及复核规则；段分支不直读 `docs["scenario"]`。validate 和 publish 重验均走同一分派，不能只接首次渲染。
5. **准入与端口：** 复用已有后端注册表和契约，必要时抽取公共输入组装端口/纯函数，不让通用 workflow import 具体场景。宿主能力、输出目标、案例和资源须封闭声明；不制造假 business_scene，也不借宿主放开未登记 inset/图层或生产能力。
6. **业务锁与验证绑定分离：** 段的 `manifest.dependencies` / `dependency-lock.dependencies` 只记录真实业务模板依赖，精确一致且可解析；首版没有段间组合/继承时两者为空。宿主、互补合同、数据、字体、生成器、种子、代码/后端及策略摘要单独纳入 validation-host 绑定，由 evidence/RenderScene 资源集闭合覆盖，不冒充 templateRef。`OwnershipResolver.validate_segment_lock()` 继续用于 Scenario；段包另定义严格锁检查，不传空 Scenario 复用。
7. **版本治理：** ID/version 与内容摘要同时固定；案例、互补合同和合成资源改变须发新宿主版本，代码/环境变化按现有指纹失效规则处理。工作区物化受控快照，发布证据保存可复验引用，不依赖 latest 或失效临时路径。旧运行不自动切换宿主，资源漂移使旧验证失效。新增宿主仍需代码/协议/正反例评审，业务 TP 不给平台代码授权。

**必测：** 空库首次发布两种段；宿主/字体/合成资源漂移；案例缺失或交换回执；宿主伪装业务依赖；首次 validate 成功但 publish 重验走错场景分支。分别证明自举成立或失败关闭。

#### 3. 阶段一产出逐元素准入与数据来源矩阵（P1-3）

下表是开工矩阵，不代表数据已经授权。阶段一评审须补齐每项的必需/可排除、明确提供方或合成方案、许可状态、格式/CRS、输入摘要计划、消费者、责任人及验证方式；第二阶段只补检测证据，不把范围决策拖到第三阶段。

| 元素 | 图中可恢复 / 不可恢复 | 当前消费者 | 归属阶段 | 数据/资源计划与前置条件 |
|---|---|---|---|---|
| 页面、标题、普通文本 | 位置/层级可测；锚定规则和字体文件须确认 | Layout/typography 部分可用 | 一：消费；二：提取 | 原图、有许可字体、合成标题；不固化地名/年份 |
| 六类 LULC 与主图 | 标签/颜色可提取；真实类别码、空间分布不能恢复 | 栅格链已有，缺 Style 前置接入 | 一：路径 A；二：提取；三：组合 | 合成分类 TIFF 做验证；地理实例另需获准的现成分类栅格及显式类别映射 |
| 河流 | 线外观可测；真实几何需输入 | 独立矢量能力不等于栅格叠加已贯通 | 三 | 有许可现成河网及范围属性；预审合成线验证，不从栅格追踪河流 |
| 流域边界与外缘效果 | 外观可测；真实边界不唯一 | 面符号基础，叠加/阴影待补 | 三 | 授权或许可明确的现成流域数据；不据 DEM 划分流域，不 buffer/dissolve；阴影只改显示 |
| 县界与地名 | 线型/文字可测；行政几何和属性需来源 | 矢量/label 基础，组合待验 | 三 | 同期许可行政数据与名称；按属性/ID 筛选，不生成行政边界 |
| Kenya 定位图 | 版面/高亮可测；地理视图和对象须确认 | inset 尚未执行 | 三 | 有许可现成国家/行政要素与高亮 ID；合成例验证独立视图，不裁原图冒充可复用地图 |
| 淡化底图 | 外观可见；服务/版本/原始透明度不确定 | 矢量页有部分入口，栅格组合待补 | 三 | 许可明确的离线底图或用户授权资源，声明范围/CRS；无来源阻断必需项，不自动抓瓦片 |
| 混合图例 | 标签、顺序和符号可提取 | 现有基础不代表全部分组已支持 | 二：提取；三：混排 | 同一冻结类别/图层合同派生，不维护另一套颜色或语义 |
| 指北针、比例尺 | 外观可测；方向/距离须目标视图计算 | 固定图元存在，原图外观未全参数化 | 三 | 用户确认视图/单位/CRS；机械计算，不猜 EPSG、不固化 90 km |
| 标识等可选装饰 | 外观可见；再分发许可不能由 PNG 证明 | 依资源及页面能力核对 | 三（确认后） | 有许可原始资源，或明确批准不保留；不恢复品牌段、不默认复用 QGIS 标识 |

**操作硬边界：** 业务输入仅 read/filter/符号化；筛选指按显式属性/ID 选择既有要素，不包括 buffer、dissolve、空间 clip/intersection、重投影、栅格转面、DEM 派生或其他几何派生。视口显示裁切、毫米换算、比例尺和方向计算不回写/生成 GIS 几何。平台合成数据使用预审样本或完全人工确定性生成器，不从真实数据派生，不冒充 Athi River 真实输入。

**范围门槛：** 阶段一退出前，每个必需元素有具名责任人、可执行的数据取得/合成方案及许可确认路径；无方案则保留阻塞或经用户批准缩小范围，不能无条件承诺第三阶段。第三阶段启动前输入须实际到位并通过路径、许可、格式、CRS、摘要检查。合成数据只证明消费者功能，不证明真实上下文层或原图地理分布已经恢复。

#### 4. 换色设计修订回路：预览后换色复用数据证据（用户确认需求）

**裁决：生成侧接通换色修订回路；创建侧颜色权威保持路径 A。两者共用同一“类别码 → 生效色”映射（Style 经角色↔类别码绑定抬升，见裁决 5）、红线与图例机制，不构成第二颜色权威，也不在准备阶段开换色旁路。**

需求与现状差距（一手核验）：用户看 preview 后换配色是设计偏好，但今天颜色住在数据层（prepared report rows），换色使 `prepared_raster_bindings.prepared_ref` 摘要变化 → `bundle_input_digest` 失配（`map_generation.py:1109`）→ GIS 统计被连带重跑；而本应承载此场景的修订词表 `color_scheme` 零消费者。修订回路本身（只失效编译节点、数据包复用、G1 重签修订简报）已经存在，缺的是把颜色接进去。

**机制（编译期生效色映射，加法演进）：**

1. **备菜不变：** prepared report 继续冻结类别语义与基线色（由 A/澄清确认）。未声明设计层色带时，行为与今天逐字节一致（零回归基线）。
2. **修订词表（定名：复用 `color_scheme`）：** 不新增 `palette` 键。`color_scheme` 值从裸对象收紧为闭合结构：显式“类别码（数据值）→ 大写 hex”映射（hex 遵循已收敛的 `^#[0-9A-F]{6}$`，非空、未知键拒绝；与 Style 角色键的关系见裁决 5），不得按图例序号猜类别码。该键现零消费者、仅形状测试，收紧不破坏任何存量运行；配合法/非法样例并更新 `test_design_revision.py`。`revision.rules()` 登记为仅失效编译节点（candidate/preview/preflight/scene），不加入 `bundle_input_keys`。
3. **编译期消费：** portrayal/page 编译时对冻结 rows 确定性应用映射产生生效色；生效色、映射与来源摘要（修订提案 ref 或 style ref）冻结进 resolved 候选，G2 签署该候选。映射是机械推导，不引入设计偏好。操作键与优先级代数见裁决 5。
4. **图例 invariant 改写：** 从“图例 = 备菜行颜色”（`raster_legends.py:76`）改为“图例 = 生效色，且可经映射回溯基线行”；地图与图例必须同源，不得两套颜色。此属语义变更，按 P2-1 裁决显式升版。色带作用域与共享图例规则见裁决 6。
5. **红线挪位：** 对生效色执行同一 `color-redlines-policy` 并持久化 findings（现行门禁在映射前查色，`raster_portrayal.py:215-218`）；blocker 处理沿用阶段二裁决，无豁免。
6. **确认语义：** 基线色由数据澄清/A 确认；生效色带是设计决策，由 G1（修订简报）/G2（新候选）确认，创建侧经 TP 绑定。两层均有人审，不存在静默换色；旧 G2 签名对新候选无效。简报色带可见见裁决 7。
7. **局部修订合并语义（已裁决，修复整段替换）：** `apply_overrides` 现状对 style 整段替换（`request_contract.py:96-98`），改为以下合并规则：
   - **合并基线：** 本运行精确安装/钉住的 style 合同（不可变 artifact），不检索“最新”；合并是确定性纯函数，重放重算比对。
   - **粒度：顶层键替换（首版）。** `new_value` 的每个顶层键整体替换基线 style 的对应顶层子树；被替换子树须独立满足 style Schema 对该字段的约束（如 `typography` 必填五字段齐全）。**首版不实现递归深合并**，但须澄清一个曾被说过头的理由：深合并给定 (基线,补丁) 本是确定性纯函数，摘要/重放并不固有不稳定；真正的坑是数组无良定义合并、删除语义含糊、意图不可见。要守的不变量是“**冻结物完整 + 闭合可验 + 血缘可溯**”，而非“输入必须完整子树”。顶层替换是满足该不变量的最小首版；叶子级输入见下方“按需升级终态”。
   - **闭合重验：** 合并结果必须通过完整 style 闭合校验（必填齐全、未知字段拒绝）；校验失败明确拒绝，不静默放行局部值，也不回退为要求完整段。
   - **`color_scheme` 路由：** 它不是 style 合同字段（闭合 Schema 无此属性），**不得合并进 `embedded.style`**；作为修订层色带载体路由到编译期生效色映射（机制 3），映射与来源摘要冻结进候选。`new_value` 同时含 `typography` 与 `color_scheme` 时：前者合并进 style，后者驱动换色映射，分别记录。
   - **词表对齐：** 修订词表现允许的 `legend_style`/`scale_bar_style` 在 style Schema 无对应字段（实测零匹配）——从修订词表移除或显式映射到真实 style 字段；`new_value` 允许键收敛为“style Schema 顶层字段 ∪ {color_scheme}”的子集，不得向闭合 Schema 合并不存在的字段。
   - **来源与审批：** `revised_cartography` 记录合并基线摘要 + `new_value`；G1 签署含合并来源的修订简报，候选绑定合并结果。`output_profile` 已是字段级合并（:102-105），实施时只对齐 style 路，不顺手改 `output_profile` 行为。
   - **diff 必配守卫（与粒度无关，必做）：** 每次局部修订强制展示“基线子树 → 新子树”diff，高亮新增/修改/**被删的可选字段**，并闭合重验。必填字段丢失由闭合校验直接拒（失败关闭已兜底）；**可选字段**（如 `labeling.hierarchy`）整替时易被无意丢弃且校验仍过，必须经 diff 显式告警/确认。此守卫杀掉“重交整件衣服”背后的真实风险（静默丢声明），不需要动合并粒度。
   - **按需升级终态（叶子合并，非首版）：** 若出现真实人手 CLI 编辑或“最小 diff”审计需求，升级为“叶子意图 → 机械合并 → 完整冻结”：LLM/用户只交语义意图（如 `{typography:{title_pt:20}}`，`design-principles.md:41` 范例），程序按机械推导层（:60 零偏好、可重算）确定性补全为完整子树，冻结完整结果 + 基线摘要 + 补丁来源。规则：标量叶子可合并、**数组一律整替**（style 含多处数组字段，如 rules/ramps/symbol_roles/hierarchy/accepts，不做下标/key 合并）、删除显式（重交不含该字段的父对象，不用 null 哨兵）、来源必录。此属语义新增，按 P2-1 显式升版。**首版不建**：模板主笔为 LLM，重供完整子树由 LLM 廉价承担，无真实痛点不投机建合并语言（非必要勿增实体）。
8. **不动连续分支：** `color_ramp` 仍在准备阶段消费（`raster_preparation.py:169`），本裁决只针对离散类别，不顺手重构连续路径。

**可证伪验收：** 换色修订后 `prepared-data-bundle` 摘要不变、GIS 统计不重跑、不重新澄清，仅重编译/重渲染；新 preview 地图与图例同用生效色；候选含映射与来源摘要；生效色触发 blocker 被拒且 findings 持久化；未声明色带时全量输出与基线逐字节一致；旧修订/旧候选不能冒用新色，nonce/漂移门禁不放松。

**必测：** 换色修订的数据包复用（摘要断言）；地图/图例生效色一致；红线对生效色执行；G1/G2 重签与旧签拒绝；局部 style 修订端到端（仅 `typography` 局部值合并后闭合校验通过且渲染变化；局部子树缺必填被拒；未知键被拒；`legend_style`/`scale_bar_style` 无目标字段被拒或已映射）；局部修订强制 diff 预览（可选字段被删高亮告警、必填丢失闭合拒绝）；`color_scheme` 不混入 style 合同而驱动生效色映射；混合修订（typography+color_scheme）分别记录；合并基线漂移被拒、重放重算一致；未声明色带零回归；用答案/CSV 旁路换色被拒。

### 裁决 4 的前置补充裁决（5–7，已拍板）

裁决 4 的机制要成立，须先闭合三个设计洞：颜色键空间与优先级（5）、色带作用域与共享图例（6）、审批对象色带可见（7）。三者与裁决 4 共用同一“类别码键”，是一套自洽设计；均已于 2026-11-23 用户拍板，裁决 4 开工限制解除。

#### 5. 颜色键空间与优先级代数（闭合“谁的颜色说了算”）

**裁决：编译期唯一操作键 = 数据值（类别码）；模板按语义角色存色，运行绑定角色↔类别码；逐值“修订覆盖基线”。**

- **唯一操作键：** 编译期所有颜色落到数据值（类别码）。【源码事实】冻结备菜行按 `value` 索引（`raster_legends.py:33`）；`color_scheme` 按类别码写，不按图例序号猜。
- **模板可复用：** Style 存“语义角色 → 色”，复用 IR 层 `role_id` 词表（`style.schema` symbol_roles）；模板不含实例类别码（守 §1.2.2）。运行提供“角色 ↔ 类别码”绑定表（实例事实，住分类合同，不进模板）；编译期经绑定把 Style 色抬成“值 → 色”，与 `color_scheme` 同键对齐。
- **优先级总序（逐值）：** 生效色[值] = `color_scheme` 含该值 ? 修订色 : 备菜基线色（A 冻结）。修订与基线均经人审，修订是更晚明确意图，“后者覆盖前者”与 `revised_cartography` 覆盖安装样式一致。由此“第二权威”消解为有全序的覆盖，而非两个平级权威。
- **失败关闭：** `color_scheme` 写了备菜没有的类别码 → 拒绝（未知类别）；角色绑定缺失/冲突在准备期澄清/拒绝（A 管辖）。
- **双层来源记录：** 候选逐值记 `{基线色, 基线来源, 生效色, 覆盖来源 ref}`；图例经生效色回溯基线。
- **诚实成本：** 离散备菜行现仅粗粒度 `semantic="class"`，无逐类别角色键——“角色↔类别码绑定表”是新增协议（角色词表复用 `role_id`），此为保模板可复用的代价。若接受“编码专用样式”可退化为模板直接按值存色，但弯曲 §1.2.2，不推荐。

**可证伪验收：** Style-only / 修订-only / 两者并存（修订逐值覆盖）/ 部分覆盖（其余保留基线）/ 未知值拒绝五例成立；候选含双层来源；图例 = 生效色且可回溯基线；模板不含实例类别码。

**必测：** 优先级代数五例；角色绑定缺失/漂移拒绝并使旧候选失效；模板实例码棘轮；绑定表与分类合同摘要一致。

#### 6. 色带作用域 = 共用图例组（闭合“共用图例怎么换”）

**裁决：`color_scheme` 作用域声明为类别合同 id（即共用图例组）；组内整组换色，组内分歧拒绝，独立组互不干涉。**

- **作用域：** 单图运行默认唯一类别合同；多面板页 `color_scheme` 绑定类别合同 id，该合同名下所有面板一起换色。
- **组内一致：** 【源码事实】共享图例要求跨面板定义（含颜色）完全一致（`raster_legends.py:44-48`，“no recoloring”）。组内同值不同色 → 拒绝（扩展 `SHARED_LEGEND_DEFINITION_MISMATCH` 家族）。
- **双校验：** 基线定义相等校验保留（查备菜行，保语义共享）；新增生效色一致校验（组内各面板生效色相同）。渲染共享图例用生效色。
- **独立组：** 不同类别合同的独立图例组各自换色合法。

**可证伪验收：** 共享组整组换色通过；组内分歧拒绝；两独立组异色通过；基线语义仍强制；多面板换色后图例/地图同色。

**必测：** 上述四例；作用域 id 缺失/未知拒绝；生效色一致校验在 publish 重验同样执行。

#### 7. 审批对象色带可见（闭合“审批人看不见颜色”）

**裁决：简报加加法可选“设计变更摘要”含色带表；改色时条件必填；refresh_brief 机械填充；G2/TP 复用同一展示。**

- **加法字段：** 【源码事实】现行 `map-brief.schema` 无颜色栏，颜色仅经 `request_ref`（:173）间接绑定。新增可选“设计变更摘要”，色带表逐行展示“类别码(标签) → 生效色”，并排基线色与来源。按 P2-1 加法不升版，配样例 + 棘轮。
- **条件必填（核心）：** 修订含 `color_scheme` ⇒ 简报 MUST 印出色带表，否则拒绝。杜绝“签了个看不见颜色的字”。
- **机械填充：** 扩展 `refresh_brief`（`revision.py:44-60` 现仅刷新矢量字段绑定）从冻结生效映射确定性推导色带表，栅格也填；不引入设计偏好（机械推导层）。
- **三处同表：** G2 靠 preview 肉眼 + 候选摘要已覆盖；TP 材料复用同一色带表组件；G1/G2/TP 看到同一张表。
- **零回归：** 无改色旧简报不带该字段，逐字节不变。

**可证伪验收：** 改色修订简报色带表 = 生效映射；缺色带拒绝；G1 摘要覆盖色带；色带表与候选映射、preview 渲染三者一致；旧简报零回归。

**必测：** 上述各项；色带表来源标注正确（基线/修订）；条件必填在 revise 与 publish 重验均执行。

### 主要文件范围

- 修改编排：`C/cli/template_cmd.py`、`C/workflow/template_analysis.py`、`template_brief.py`、`template_author.py`、`template_workflow.py`。
- 修改打包与验证：`C/repository/staging_package.py`、`C/compiler/dependencies.py`、`C/workflow/template_validation.py`。
- 建议新增：`C/workflow/template_kinds.py`、`C/compiler/segment_authoring.py`、`C/workflow/segment_validation.py`；名称可在设计评审时收敛，不创建第二套状态机。
- 颜色时序：`C/workflow/raster_preparation.py`、`C/compiler/raster_portrayal.py`、`appearance.py`、`color_checks.py` 及 `C/scenarios/general_thematic/` 的准备前请求构造组件；检查 `C/cli/data_cmd.py` 请求转发/澄清入口，场景词汇仍留在场景包。
- 换色修订回路：`C/scenarios/general_thematic/revision.py`（rules/apply_changes/refresh_brief 色带表）、`request_contract.py`（style 顶层键合并 + 闭合重验 + color_scheme 路由）、`C/compiler/raster_portrayal.py`、`raster_legends.py`（基线 + 生效色双校验、组级作用域）、`raster_page_contract.py`、`C/compiler/map_candidate.py`（重算绑定）；`S/design-revision-proposal.schema.json`（`color_scheme` 闭合收紧 + 作用域 id、`new_value` 允许键与 style Schema 对齐）、`map-brief.schema.json`（设计变更摘要加法字段 + 改色条件必填）、角色↔类别码绑定协议（分类合同侧）、`resolved-portrayal`/`page-request`/`resolved-map`（生效色映射与双层来源绑定，语义变更显式升版）；`T/test_design_revision.py` 及新增换色修订/合并语义/优先级代数/组级作用域/简报可见测试。
- 横切协议：`S/raster-classification-request.schema.json`、`raster-classification-answers.schema.json`、`raster-prepared-data.schema.json`；审计 preparation bundle、resolved portrayal、页面图例/源引用与版本绑定，仅按实际变化改协议。
- 宿主与锁：新增平台验证资源与严格 `validation-host` Schema；`segment_validation`、`dependencies.py` 实现段锁和宿主证据绑定。`compiler/ownership.py` 的 Scenario 锁语义不挪作通用段规则；若重构只抽公共检查，不放松原规则。
- 渲染接点：审计/按需调整 `C/compiler/page_bindings.py`、`raster_page_contract.py`、`raster_scene.py`、`vector_scene.py`、`C/workflow/preparation_bundle.py`、`C/adapters/render_backend.py`、`formal_renderer.py`，补共享组装端口，不复制页面绘制实现。
- 协议：`S/template-create-request`、`template-proposal`、`template-analysis`、`template-brief`、`style`、`template-validation-evidence` 等相关 `.schema.json`；manifest/依赖锁仅按已确认包契约调整。
- `C/repository/template_repository.py` 以复用为主；不为两类段重写审批算法、nonce、事务或索引。

### 交付物与验收

**交付物：** 首版字段/能力清单、逐元素准入及数据来源矩阵、路径 A 协议/失效规则、换色修订回路协议与零回归基线、平台宿主清单与锁规则、类型化协议及合法/非法样例、两类段作者、验证样张与回执、单包发布和引用复用集成测试。

**退出条件：**

- Style 和 Layout 分别通过真实创建、验证、TP、发布路径；发布后能取出并组成新运行。
- 修改 Layout 框位置，渲染位置随之变化；修改字号和类别颜色，样张及图例同步变化。
- 不完整合同、未知字段、错误类型、溢出或不支持能力明确拒绝；不能用缺省值制造“通过”。
- 包漂移、错 TP 对象、错目标库、审批重放被拒绝；发布幂等和中断恢复通过。
- 空库可验证并经 TP 发布首个 Style 和 Layout，宿主不是隐藏的业务模板依赖。
- 路径 A 的旧答案拒绝、重复澄清、Style/CSV 冲突、漂移重准备和图例一致性测试通过；宿主资源漂移、案例缺失/交换均被 validate/publish 拒绝。
- 换色修订回路验收通过：换色后数据包/GIS 证据摘要不变、仅重编译渲染；地图/图例同用生效色；红线查生效色；G1/G2 重签、旧签拒绝；未声明色带时输出与基线逐字节一致。
- 前置裁决 5/6/7 验收通过：逐值优先级代数与双层来源、角色绑定缺失/漂移拒绝；共享图例组整组换色/组内分歧拒绝；改色简报强制印色带且与候选/preview 一致。
- 原有 MapScenario 回归与四项边界守护通过，不扩大允许清单；新增准备/宿主代码及 Schema 纳入算法、渲染和验证指纹。

**本阶段不做：** 自动识别地图全部元素、完整定位图、多包原子发布、模型训练和服务部署。

## 五、阶段二：接入受控参考图、半自动提取及真实对比

### 核心目标

把 Athi River 等参考图转为有证据、可修订、能进入第一阶段工作流的提案。先支持已明确的元素和字段，不把自动化率作为完成标准。

### 主要改动

| 工作项 | 实施内容 |
|---|---|
| 安全输入与冻结 | PathGuard 校验后读取；限制文件字节、解码像素和格式，拒绝异常图像。冻结源摘要、尺寸、DPI、色彩解释、许可声明及配置。原图默认留在受控证据目录，不自动发布到模板包 |
| 坐标与测量证据 | 同时记录原图像素、分析缩放/裁切坐标和页面毫米；保存变换关系。源图约 500 DPI 与目标渲染 DPI 分开，比较时对齐物理尺寸；缺失/矛盾元数据须澄清 |
| 图例锚定提取 | 优先从图例 ROI 检测色块/线符号并关联标签，保留类别语义和顺序；全图聚类只作辅助。离散类别不伪装成连续渐变；背景、阴影和标识不能混入专题颜色 |
| 布局、文字与人工补充 | 复用现有 `user_layout`、`user_typography` 和后端注入；CV/OCR 可选，缺后端有明确提示。可见证据、候选解释、作者决策分别保存；人工确认不是算法置信度 1.0 |
| 确认与版本冻结 | 只对当前所选段和声明用途要求补全未知项。确认后保存不可变提案和输入摘要；author/publish 不重新执行 OCR。修改分析或设计后采用明确新 revision/新运行，不覆盖已验证结果 |
| 置信度语义纠偏（P2-2） | 现行 `reference_extraction.py:119,128` 对用户补充赋 confidence=1.0，与“人工确认不是算法置信度 1.0”矛盾。改为区分来源（user/backend）与测量置信度，人工确认记为责任转移而非测量结果；同步更新 `test_template_proposal` 断言。此为显式行为变更工作项，不是仅改文档 |
| 红线冲突 | 忠实提取不是红线豁免。blocker 必须显式改色并记录 deviation 后重走路径 A，或停止发布；warning 按策略披露，不自动升降级或换色 |
| 真正 round-trip | 将完整合同渲染结果与独立标注/确认的参考证据比较，分别记录恢复误差、授权偏离和渲染实现误差；同图同算法聚类比较不是发布质量证明 |
| 审批证据绑定 | 提案、源摘要、确认结果、比较报告与渲染证据通过包或 evidence 摘要闭合绑定到 TP；设计确认和质量阈值设定均不能代替发布审批 |

### 红线冲突与偏离裁决（P1-2，进入阶段二前冻结）

**保留现行门禁语义，不提供请求级豁免。** 按冻结的 `color-redlines-policy` 版本/摘要执行；不能为复刻参考图把 blocker 改 warning、置 off、调低阈值或重排图例绕过检查。

| 结果 | 必须采取的处理 |
|---|---|
| 无 finding | 可保留原色继续验证，仍不证明数据语义或整张地图的全部可读性 |
| 只有 warning | 结构化证据、预览和 TP 材料披露类别对、指标、策略版本；可保留原色或主动修订。按现行策略继续不是豁免，不宣称“全部色觉安全” |
| blocker | 阻断可发布验证；作者/用户明确提交新配色，重新检查和渲染。拒绝改色则停止该范围发布，人工接受风险不能消除 blocker |

- `provenance/deviation` 严格记录源图/提取提案摘要、类别键、原色、新色、触发 finding、改色理由及作者确认来源；具体结构纳入版本化 Schema，不向旧对象塞任意扩展字段。
- 提取证据不可改写，采用色作为新设计保存并重走路径 A；旧答案、旧样张、旧对比证据和旧 TP 不批准新色。
- 报告分别展示“原图 → 提取”的恢复误差、“原图 → 已确认设计”的授权偏离和“已确认设计 → 渲染”的实现误差。保留相对原图的真实差异，不把改色伪装为精确复刻，也不事后放宽相似度阈值掩盖偏离。
- 提案侧可预检，但最终有效配色在验证/发布仍复用同一活门禁，并持久化 findings，不只输出 `warnings.warn`。离散类别不套顺序/分歧亮度单调性要求；本计划不改现行策略数值或 enforcement。

**样本定量核对（范围有限）：** 对此前图例采样六色 `#F9F915 / #1F611F / #8F452C / #3C2FD5 / #6B6B6B / #E16ED0`，按该顺序调用当前 `check_color_sequence` 与策略 0.1.0，普通相邻 ΔE76 最小约 64.48（blocker 阈值 10）；森林/农田在 deuteranopia 模拟下约 7.12（阈值 12），产生 1 项 `COLOR_CVD_UNSAFE` **warning**，没有 blocker。策略仍标记 `pending-business-review`。因此需要冲突流程，但不能断言本图已被阻断；序列相邻检查不证明所有空间邻接类别、文字/底图都安全，也不替代最终样张验收。

**必测：** 合规原色；warning 披露；人工接受风险后 blocker 仍阻断；显式改色/旧证据失效；缺失 deviation、换序规避和策略漂移被拒绝。

### 主要文件范围

- 修改：`C/compiler/reference_extraction.py`，保持纯函数、无工作流/仓库依赖；新增后端适配器由组合入口注入；置信度语义纠偏同步修改 `T/test_template_proposal.py` 断言。
- 建议新增：`C/adapters/reference_image.py`、`C/workflow/reference_intake.py`、`C/validation/reference_roundtrip.py`，接入已有 analyze/validate，不另建发布路径。
- 复用并扩展第一阶段的分析、Brief、段作者和验证组件；不重复建立新的提案类型体系。
- 新增严格的参考分析/对比报告 Schema，定义 findings、deviation 和确认记录的闭合结构，绑定到提案及证据。`C/compiler/color_checks.py` 以算法复用和证据接口补齐为主，不改现行门禁数值或等级。
- 在 `pyproject.toml` 与 Skill 内依赖说明中声明图像分析可选依赖；重型 OCR/CV 懒加载，基础 CLI 和 Schema 自检不强制依赖它们。

### 交付物与验收

**交付物：** 原图输入记录、元素/图例证据表、确认后的 Style/Layout 提案、未知项与未支持能力清单、真实对比报告、限定范围样本模板包及发布证据。

**退出条件：**

- 经授权的真实 PNG 可通过唯一 CLI 完成已选字段的“分析 → 确认 → author → 验证 → TP → 入库”，并在新运行复用。
- Athi River 六类土地覆盖的标签—颜色对应经确认；不得猜测真实数据类别编码。
- 原图/裁切/提案/人工修改可追溯；改变任一绑定后旧证据或 TP 不再适用。
- 错配类别、遗漏关键图例、未知字段及非法图像均有自动拒绝测试。
- 对比报告显式列出未测项；整页 SSIM 或全图颜色相似不能替代关键元素验证。
- blocker 无豁免、warning 按等级披露；授权改色有 deviation 及新准备/渲染/审批绑定，忠实性和实施误差分别验收。
- 对比阈值由独立基准标注和误差实验确定，经评审冻结并绑定到证据；不能用待验收输出反过来调阈值直至通过。

**本阶段不做：** 用截图恢复真实地理数据；静默删除定位图等未支持元素；把一次提取的猜测推广为全库通用规则。

## 六、阶段三：补齐样本制图能力并完成发布后复用验收

### 核心目标

以第一阶段确认、第二阶段补充证据的逐元素准入与数据来源矩阵为准，补齐约定能力，不是无原始数据条件下的像素级地理重建。

**启动条件：** 即将实施的每个必需上下文层，实际输入、许可、责任人、格式/CRS/范围和摘要已到位；真实输入与平台合成验证数据分别标识。无数据的必需项保持阻塞，或在发布前明确批准修改范围，不临时派生几何凑数据。只允许 read/filter/符号化，禁项和显示裁切边界沿用阶段一矩阵。

### 主要改动

| 工作项 | 实施内容与边界 |
|---|---|
| 独立定位图 | 打通 inset 类型、独立视图/范围、主图关联和资源绑定；保留严格包含及碰撞校验。不能把 Kenya 截图贴入 Layout 代替地图视图 |
| 栅格与上下文图层 | 按矩阵使用现成许可数据，接入分类栅格、河流、流域边界、县界和底图；明确层序、CRS、资源摘要及各层验证。只读/筛选/符号化，不派生几何；矢量页能力不能视为栅格链已支持 |
| 混合图例与整饰 | 为已确认的线/面符号分组图例、指北针、比例尺提供真实消费者；比例尺数值由目标空间配置计算，不能把原图数字固定进模板 |
| 必需外观效果 | 阴影、背景弱化、文字颜色/描边等逐项按验收清单接入。标识是可替换资源，许可与是否保留需确认，不恢复已移除的品牌段 |
| 证据与发布复核 | 新渲染字段、资源、编译器和算法纳入代码/产物指纹及重放验证；所有必要组合须真实渲染，不以第一幅图或默认组合代替 |
| 复用与文档同步 | 更换标题、年份、图例文本、研究区域和定位内容进行复用；同步 Skill、创建/生成工作流与已评审的能力声明，不自动开启生产准入 |

### 主要文件范围

- 布局/视图：`C/compiler/layout.py`、`page_bindings.py`、`raster_page_contract.py`、`vector_page.py` 及相关 scene 编译器。
- 渲染：`C/adapters/page_renderer.py`、`static_page_renderer.py`、`formal_renderer.py`；复用现有渲染框架，不新建平行页面引擎。
- 图例/样式：相关 portrayal、legend 编译模块、appearance 与场景组件；Schema 涉及 `layout`、`page-bindings`、`page-request`、`style` 及相应解析产物。
- 准入与治理：仅修改必要的场景能力/路线图项，由策略 steward 评审；通用内核不读取 Athi River 或具体业务词汇。
- 摘要和测试：更新相关指纹覆盖及现有边界守护、页面、段引用、渲染和恢复回归。

### 交付物与验收

**交付物：** 约定能力的协议及实现、Athi River 样本段包和预览、真实 TP/发布回执、新运行复用成果、能力覆盖矩阵和完整验收报告。

**退出条件：**

- 验收清单中的必需元素全部有声明、消费和验证；未支持项必须阻断，或在发布前由用户明确批准修改范围，不能静默降级。
- 测试样张和第二次使用均无关键文字丢失、图例错配、非法遮挡或容量超限；超限时按合同明确拒绝，不自动缩字删项。
- 按精确 Style/Layout 引用的新运行不残留 Athi River/2023 等实例内容，比例尺与定位内容按新输入计算。
- CLI 完整链、包与资源篡改、错误审批、重复请求、索引中断恢复测试通过；四项边界守护只紧不松。
- 完整回归和目标能力真实渲染均有记录；目标能力的缺依赖/缺字体跳过项必须清零，其他跳过项单独披露，不计为通过。
- 工程合成审批测试与真实 TP 验收分别记录；没有有效业务审批时停在 `waiting_approval`，不得宣称正式入库完成。

## 七、统一变更控制与依赖

### 7.1 实施前置条件

- 固定当前工作区基线，保留既有未提交修改；记录实施前错误/跳过，不以删测试或弱化门禁消除它们。
- 确认真实解释器、可选依赖、字体及其许可、受控输入/输出根、验证和发布角色。安装依赖、联网和业务审批分别授权。
- 本机存在参考图不等于获得再分发许可；发布范围和资源许可需确认。真实样本默认在受控验收项目使用，自动 Fixture 使用合成输入，不复制业务数据或密钥。
- 新协议均提供合法/非法样例与测试；运行时只读 Skill 内协议、策略及项目产物，不读取本文或测试目录生成合同。

### 7.2 每阶段统一交付记录

每阶段提交：文件变更清单、协议/能力版本说明、合法/非法样例、测试与真实渲染报告、未支持项、冻结执行影响及恢复说明。功能未通过本阶段退出条件时，不更新为“已开放”。

原“运行代码 18～25 个、Schema 8～12 个、测试模块 8～12 个”的前两阶段粗估未充分计入颜色时序和宿主分派，不再作为预算上限。阶段一按横切协议、平台资源、真实渲染/发布复核和新增测试重新给出文件清单、工作量及责任分配，跨阶段文件不重复计数。第三阶段是独立的大型消费者扩展，按逐元素矩阵分别估算/排期/验收，不作为前两阶段的小尾项。

最低回归集合：分类请求/澄清/重放/图例一致性；换色修订（数据包复用/生效色一致/红线/重签/零回归）；空库宿主自举/漂移；段锁、案例集合与发布重验；blocker/warning/deviation；逐层数据来源及禁止几何派生。复用 `T/test_raster_classification.py`、`test_raster_portrayal.py`、`test_color_redlines.py`、`test_template_proposal.py`、`test_segment_refs.py`、`test_design_revision.py` 等，并新增必要的宿主/段验证/换色修订测试。

### 7.3 明确不纳入本计划的扩张

- 一次 TP 原子发布两个段包：如确需此体验，另评审包集合发布对象、事务/恢复和 nonce 语义；不能循环调用两次单包发布冒充原子事务。
- 全自动模板市场、自动模板选择、专用大模型训练、独立 MCP 服务部署、品牌段恢复和生产准入。
- 本次无必要的旧路径改名、历史包自动迁移或旧协议并行兼容实现。

## 八、最终完成检查表

- [ ] Style/Layout 有正式类型化作者、严格协议和独立验证路径。
- [ ] 路径 A 在 preparation 前绑定显式配色，请求、答案基线、prepared report 和图例版本/摘要一致；页面阶段不做未声明换色（仅裁决 4 声明式映射）。
- [ ] 换色修订回路：预览后换色仅重编译/重渲染，数据包与 GIS 证据摘要不变；地图/图例同用生效色，红线查生效色，G1/G2 重签；局部修订强制 diff 与可选字段删除告警；未声明色带时零回归。
- [ ] 裁决 5：编译期按类别码键、修订逐值覆盖基线，候选含双层来源；模板不含实例类别码，角色↔值绑定缺失/漂移拒绝。
- [ ] 裁决 6：色带按共用图例组整组换色，组内分歧拒绝，独立组互不干涉；基线与生效色双校验。
- [ ] 裁决 7：改色简报强制印色带表，与候选映射/preview 一致；G1/G2/TP 同表；无改色旧简报零回归。
- [ ] 平台宿主在空库自举；段业务依赖锁和验证资源绑定分离，复用正式渲染及发布重验。
- [ ] 参考图及提案冻结可追溯，人工确认与 TP 职责分离。
- [ ] 已声明提取字段均有真实消费者；类别颜色、布局及文字不是“只存不生效”。
- [ ] round-trip 来自合同正向渲染与独立证据比较，而不是提取器自比较。
- [ ] 两类段各自经有效 TP 发布，精确引用、完整性验证和中断恢复正常。
- [ ] blocker 不可豁免，warning 按策略披露；授权改色有 deviation，忠实性与实现误差分别验证。
- [ ] 逐元素矩阵及具名来源/许可齐备；仅 read/filter/符号化，未实现项和缺数据项无静默遗漏。
- [ ] 新运行真实复用通过，实例内容不污染模板，地图生成审批未被绕过。
- [ ] Schema、自动回归、目标能力真实渲染及边界守护均提供验收记录。

**实施主线：先证明段合同可以安全发布和使用，再接参考图证据，最后完成样本设计能力与跨实例复用。**
