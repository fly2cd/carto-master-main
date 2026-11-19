---
name: carto-agent
description: 地图制图智能体的创建模板与生成地图工作流入口。
version: 0.8.0
---

# Carto Agent Skill

本目录是地图制图智能体的唯一运行实现。当前已落地 U-P0 安全底座、U-P1 内核协议骨架、U-P2.0～U-P2.7 的 MapScenario 创建发布与地图候选冻结闭环，U-P3.1～U-P3.3 的锁驱动正式渲染、成品检查、精确 G3 和原子本地交付，以及 U-P3.6 的协议层统一（请求/模板创建 schema 合并、bundle-inputs 统一、应急制图并入标准专题制图）。不得在仓库其他位置建立并行实现。

## 必读顺序

1. 阅读本文件。
2. 阅读 `workflows/routing.md`，选择且只选择一个顶层路由。
3. 读取所选路由拥有的工作流文件；尚未实现的路由必须返回明确的能力未开放错误。
4. 机器执行只读取 `schemas/`、`policies/`、注册表和项目产物，不读取 `doc/` 设计稿或 `scripts/tests/` 作为运行协议。`scripts/tests/` 仅供开发与验收阶段使用，正式发布阶段不依赖。

## 当前阶段边界

- 保留通用框架：Schema 与安全底座、状态与回执、审批协调、ToolGateway、知识服务、模板创建发布编排、候选编译与冻结、锁驱动渲染、成品检查和原子本地交付。
- **当前只注册一个业务场景**：`general_thematic_mapping`。`scenario-capabilities.yaml` v1.7.0 为 `general-thematic` 实现登记**一个**能力档案 `general-thematic-mapping@5.0.0`；栅格与矢量是该档案下的 `geometry_variants` 数据适配变体，各自只声明几何、模板资产（`general-thematic-map@3.0.0` / `@4.0.0`）、作者 profile 与渲染后端，业务语义/意图约束/输出与版式上限只声明一遍。按显式 `geometry` 与变体 `template_geometry` 分派，撤销某几何即删除对应变体。支持已分类栅格、点/面矢量及显式一对一 CSV 属性连接；网格 1×1 / 1×2 / 2×2，独立/共享图例，A4 横版 PDF+PNG。均为 `production_enabled: false`，禁止敏感坐标和生产数据，强制 NOTICE 与源许可；其余能力仍默认拒绝。
- 该场景的分类栅格模板样张渲染分支已注册：`validate` 在静态检查全部通过后，于受信验证上下文内由包内图例样本派生确定性合成栅格，经授权 MCP 网关测量统计，并用 `rasterio-matplotlib-page` 后端渲染 PDF+PNG 样张、冻结渲染场景与带签名 RenderReceipt；`publish` 按冻结场景重新核验证据（不依赖作者宿主字体）并消费精确 TP。宿主缺少栅格渲染依赖、无可嵌入字体或展示 CRS 为地理坐标系时仍失败关闭，不得伪造渲染证据绕过。
- 仓库不附带业务示例数据、示例模板包或默认测试项目。后续由用户提供真实数据和场景需求，完成对应实现、注册和验收后才能启用。
- 模板发布仍必须验证闭合包、依赖锁、场景验证输入、检查器集合、RenderReceipt、冻结样张场景（`render_scene_ref`）和环境绑定，并消费精确 TP。验证数据是否适合进入模板包由场景安全检查明确判定，不能把原始敏感业务数据打包。
- 工作流严格保留 T1 / TP / G1 / G2 / G3、运行级单写锁、revision/CAS、不可变步骤回执、受限重试及恢复证明；不得伪造审批或放松门禁以继续。
- `render` 只消费锁与摘要绑定输入；`check` 验证冻结输出；`review` 签署独立成品审查并冻结含 `review_ref` 的交付清单；`deliver` 重新验证全部绑定后，按精确 G3 进行同文件系统原子提交。
- 交付包白名单为 `map.pdf`、`map.png`、`README.md`、`delivery-manifest.yaml`、`checksums.sha256`；不包含原始数据、内部锁、审批密钥或内部回执。
- 不声明生产制图、地图工作流中的真实 CRS 转换、任意输入格式、三场景覆盖、共享服务或公网发布；`production_tasks` 为空。`map-brand`、`map-style`、`map-layout` 的业务创建路由仍未开放。
- CLI 入口：`python skills/carto-agent/scripts/carto.py --help`。
- 开发测试仅在用户允许时执行；不作为正式运行协议或真实场景验收证据。

## S1：合同归一与有限参数化多图

- 栅格/矢量模板分别使用一个参数化网格资产，不按每种布局复制模板。Layout 声明合法形状、区域与间距；请求的 `design`、`map_title`、`layout_parameters` 表示本次设计。自动模板检索/生成、任意网格仍未开放。
- 模板升级须重新验证发布，旧页面/候选/锁不能自动迁移，也不能沿用旧审批。`map-plan`、`page-request/output` 为 v4；`cartography`、`page-bindings`、`resolved-appearance`、`resolved-layout`、`raster-map-body` 为 v2；准备报告与分类 portrayal 版本不变。
- `source_id`、view、layer、panel、legend 显式关联。同源可复用，多源可同角色；每个视图保留对应数据范围。源 CRS 必须一致且匹配模板，不做隐式重投影或范围并集。
- 独立图例使用对应面板的已确认类别；共享图例要求完整类别定义（编码、语义、显示、名称、颜色、顺序）及 legend_policy 一致。observed 使用已确认图例项并集；all 还要求逐类纳入标志一致。冲突拒绝，不改色、不重新分类、不降级。
- 字号/行距唯一来自 cartography，内边距来自 Layout，类别颜色来自已确认 portrayal；最终 appearance、模板布局、参数与全部关系随页面冻结并重验。类别统计与模板图例容量分开。
- 模板 `validate/publish` 覆盖声明的六种参数组合，每种都有冻结场景和真实渲染回执；不能用单图样张证明多图能力。正式渲染、终检和交付验证每个面板，不只检查第一幅图。
- 本期一页一个静态后端，每面板一层分类栅格；普通单图也走同一内核。浏览器多图、任意共享组、多图比例尺/指北针、矢量、mosaic/inset 与自由编排（层级/裁剪/任意覆盖区域）、内容策划、独立 Style/Layout 创建及生产能力仍未开放。

## S2 工程候选：合成回归通过，尚未正式准入

- 已新增有界 GeoJSON/成组 Shapefile、点/面单符号与类别、显式面分级、点圆面积比例，以及共享物理页面、矢量场景/正式适配器和测试代码。
- A3.1 矢量能力已登记为受限工程能力；`design` 显式选择类别、等距/手工分级或总量比例符号，MapPlan v4 保存实际执行表达。旧 `vector_panels[].encoding` 请求不接受；不根据模板版本决定几何，不把工程准入当生产验收。
- 2026-11-10 已在现有 geo313（Python 3.13.18、Fiona/Shapely）完成修复和统一回归：81 个 Schema 有效，420 项测试中 407 通过、13 项外部环境测试跳过，零失败/错误；S2 单元 15 项及工作流 2 项全部通过。本次未安装依赖、未执行真实制图；不把跳过项或合成审批等同于真实场景验收。
- 真实输入指定为 `projects/dataset/shp`，目前只核对文件清单；不得据目录名推断指标、生成业务数据 Fixture 或签发审批。

## P3.6 协议层统一

- **请求 Schema**：统一 `general-generate-request` 和 `general-template-create-request`，按显式 `geometry` 分支；版本只识别已登记模板资产，不提供旧请求兼容 wrapper。
- **Bundle-inputs 统一**：`raster-bundle-inputs` 与 `vector-bundle-inputs`（字节级相同）合并为单一 `bundle-inputs`。
- **Render-scene 收敛**：三个 `oneOf` 变体（maplibre-web / raster-page / vector-page）收敛为两个，后两者因结构相同合并为一个 unified static page scene（`page-request`），通过 `renderer_id` 枚举区分。
- **应急制图并入标准专题**：`emergency_mapping` 不再作为独立业务场景，洪涝/滑坡/森林火灾作为 `general_thematic_mapping` 的主题标签（`theme_tags`）。`intent-profiles.yaml` 中删除 `emergency_mapping` profile，`[应急,灾情,救援]` 并入 `general_thematic_mapping` 的 `purpose_terms`。
- 以上变更均为直接替换，不保留旧名称 wrapper、旧 schema 文件或向后兼容旁路。

## 基础 GIS 数据接入（第一批）

- 先阅读 `workflows/geospatial-data.md`，再通过唯一 CLI 的 `data inspect-raster` 检查显式配置的 GeoTIFF 元数据/精确类别统计；这不是新业务路由，也不生成地图。
- 可选 MCP SDK 以 stdio 接入独立 `geospatial-mcp 0.3.0`。必须显式配置可信解释器、项目/租户、数据根、catalog 和限制；不自动安装，不接受业务请求指定的服务命令/URL。
- `raster-input` 是 `generate-request.source_bindings` 的结构分支；正式共享链路见下文第三批 C。结构合法不等于业务场景或模板准入。
- 重投影已实现为 ToolGateway 适配能力（仅 nearest、显式目标 CRS）；只读 CLI 必须拒绝变换。尚未接入获批场景，不得绕过业务门禁直接调用。
- MCP 只负责基础读取/分析；类别含义、颜色、图例、排版、渲染和导出继续由 Carto 实现，不自行关联 CSV 推断类别名。

## 分类栅格准备与静态图体（第二批）

- 仅在需要类别码栅格 + CSV 准备时阅读 [分类栅格准备与澄清](workflows/raster-classification.md)。`data analyze-classification` 经 MCP 统计匹配显式 CSV 列；`data clarify-classification` 接收摘要/身份绑定的回答，产生新的不可变报告。continuous 请求不是这条 CSV 澄清流程；底层 Schema 分支存在不等于业务或端到端交付准入。
- 未定义类别（含 0/255）或缺名称/颜色均生成动态澄清；回答不等于 G1/G2/G3，绝不改写源 NoData。
- 内部 `RasterMapBodyRenderer` 用 Rasterio + Matplotlib 从冻结数据生成图体 PNG，分类图例共用颜色合同，复用现有 SVG/布局组件；不需要 QGIS 或 MapLibre。
- 图体本身不开放独立地图导出 CLI，不注册场景，不替代 MapSpecLock/正式 RenderReceipt/成品检查；由下文第三批 C 的适配器接入正式链路。A4 横版的合成测试不等于用户地图交付或实体打印验收。
- 内部 `PageRenderer` 复用冻结图体/布局，检查字体、字形与内容溢出；页面报告不是正式 RenderReceipt。宿主不直接调用内部渲染 API，准备就绪后按 [generate-map](workflows/generate-map.md) 进入已准入场景的预览、冻结、正式渲染和交付；内部输出不新增导出 CLI 或业务场景。

## 共享分类着色表达（第三批 B1）

- 分类栅格是数据类型，`raster/categorical` 是表达，Rasterio + Matplotlib 是后端；三者都不是业务用途，不新建“分类栅格业务场景”。
- `compiler/raster_portrayal.py`（原 `raster_classification.py`）保留 Carto 的显示定义匹配和澄清，新增 `RasterPortrayalCompiler`，不实现 GIS 重分类/重投影。
- 共享 `portrayal` 新增 raster 图层；目录引用需精确 ID/版本/摘要。模板只声明角色和策略，项目类别表冻结到 `resolved-portrayal`（geometry=raster 分支），图例从同一表派生。
- 图体和整页渲染改为消费 `portrayal_ref`，重验类别合同、源快照、目录与上下文；单层、nearest、保留源掩膜，未实现的多层/规则明确拒绝。
- 共享表达继续由独立的准备/显示合同冻结，第三批 C 将其接入正式链路，场景策略仅准入 general 的受限单图/有限网格能力。旧内部快照须重新准备/编译，不保留旧模块别名或旧请求字段。

## 共享栅格正式链路（第三批 C）

- `workflow/preparation_bundle.py` 将同上下文的 ready 准备报告封装为正式 PreparedDataBundle（几何内部分支：raster / vector）；`generate-request.prepared_raster_bindings` 显式绑定已澄清报告，不根据文件名寻找结果或默认处理 0/255。
- `compiler/raster_scene.py` 生成 `renderer_id=rasterio-matplotlib-page` 的 RenderScene，冻结 bundle、显示合同、物理版面和字体引用；向既有业务 execution 绑定 `page_inputs` 和真实环境，不选择业务用途或执行 GIS 重投影。
- RenderScene / RenderReceipt / execution 环境按后端严格区分。预览、G2 冻结、锁驱动正式渲染与重放只按冻结 ID 分派；保留 `maplibre-web`，未知后端拒绝，栅格不探测 Chromium、不伪造浏览器版本。
- 正式栅格 RenderReceipt 由 `FormalRenderer`（几何分派）签发，包含 HMAC、代码/依赖环境、精确会话、资源集、页面报告和输出摘要；内部 `page-output` 仍不是回执。当前是受项目路径约束的进程内后端，**不提供 OS/网络沙箱**，HMAC 不等于远程或硬件环境证明。
- 复用既有 MapSpecLock、RenderAttempt、FormalRenderEvidence、11 项成品检查、精确 G3 和原子本地交付。图例共性检查不替代业务检查；篡改产物不生成 Manifest。
- 已有从测试候选边界开始的临时合成数据 G2/G3 链路与恢复测试，以及合成数据/合成审批的模板 T1 → validate（合成样张渲染）→ TP → 发布闭环测试。均**不表示真实用户数据、真实审批身份或用户地图已验收**；注册策略和实现白名单当前仅登记 `general-thematic-mapping`（实现 `general-thematic`，栅格变体 `template_geometry: raster`，含模板样张渲染组件），不新增审批旁路 CLI。

## 通用内核与场景扩展

- `scripts/carto_core/workflow/` 与 `compiler/map_candidate.py` 负责通用编排、协议、摘要、审批和分派，不内嵌业务模板身份、列名、纸张规格或特定业务表达规则。
- 新场景实现仅放在 `scripts/carto_core/scenarios/`，按 `scenarios/README.md` 的组件边界接入；受信注册表只使用代码内白名单，不接受请求或配置给出任意 Python 导入路径。
- 来源数据声明不等于安全认证。场景须实现来源准入和验证数据安全检查；缺少检查组件必须拒绝，不能借删除示例约束而默认接纳未知数据。
- MapIntent 同时绑定意图目录、用户意图输入与模板能力策略摘要；候选/锁固定目录及能力策略引用，渲染、检查及交付重新核验。缺失或漂移的旧绑定不自动迁移，不新增旧格式兼容分支。
- 新场景需补充严格协议、合法/非法协议用例及自动测试，再用用户授权的真实数据验收；仅修改注册策略或生产标志不能开放能力。
- 准入拒绝分两类：安全禁止（forbidden，永久）与路线图未实现（not_implemented，须在 `policies/capability-roadmap.yaml` 声明且未 delivered，错误带 `details.admission_class/feature/status`）；未声明或已 delivered 的特征不得返回 not_implemented。profile 摘要语义化：`notice`/`licenses` 等披露字段不计入 digest，改披露不废冻结执行。场景列可经 `_COMPONENTS` 的 `__defaults__` 声明共享其他列组件，完整性按 own+defaults 校验，消除 re-export 样板列。

## 业务场景、主题与模板身份

- 只使用 `business_scene` 表达业务用途分类，不增加业务域层级。场景 ID、用途词、任务和必需信息由 `policies/intent-profiles.yaml` 统一声明；共享 Schema 检查 ID 形状，解析器检查目录成员资格。
- 主题统一使用 `theme_tags`（可多值的机器 ID）；中文显示名在目录的 `themes[].label`，不得混用为协议 ID。主题词识别内容，用途词识别业务场景；不以“洪涝”等主题词或通用“专题”一词直接决定业务场景。
- `intent resolve` 使用 `intent-request` 的 `text + selection`；`generate-request` 使用 `goal + intent`，二者复用同一个 `intentSelection` 和解析器。`tasks` 缺失必须澄清，不取任务列表第一项作为默认值。
- 生成时先解析用户意图，再验证用户明确选择的模板是否兼容；模板能力的 `intent_constraints` 只能限制可接受的场景、主题和任务，不得替用户补写或改写意图。当前不实现自动模板检索/选择；只读辅助命令 `template match`（S0）仅对已发布段契约做相似度评分，不选择模板、不写仓库状态、不替代显式模板选择；其全部数值阈值在 `policies/template-matching-policy.yaml` 声明，`confirmation_status: pending-business-review`，尚无业务依据；色差容差自策略 0.2.0 起以 CIELAB CIE76 ΔE 为单位（sRGB 按 CIE 15 转换）。
- **品牌段（map-brand/identity）已整体移除**（2026-11-18 用户授权）：它在渲染链中无任何消费者（署名来自场景策略 notice、字体来自 generate 请求），移除不改变成图外观。identity Schema、品牌评分器、品牌资产与 map-brand.md 设计文档均已删除；旧包含 identity 的包不被新协议接纳，不自动迁移。若未来需要品牌影响成图，须以带真实消费者的新协议重建，不恢复旧形状。
- `MapScenario.scenario_id` 是模板方案身份，`RenderScene.scene_id` 是渲染实例身份，二者不是业务分类。Brief、Plan 与 execution 保留同一业务场景、主题标签和任务，并绑定原意图摘要。
- 段引用协议（S1 定义、S2 接入）：`scenario.segment_refs` 允许 cartography/layout 逐段以已发布段模板引用（cartography→map-style、layout→map-layout）替代内嵌，每段恰好一个来源（embedded 与 segment_refs 互斥），引用段必须在 `replaceable_segments` 内、精确钉住 `{kind,id,version,digest}` 并与 `manifest.dependencies`/`dependency-lock.dependencies` 逐条一致，所有权随段转移。create-template 请求可用可选 `segment_refs` 声明；validate/publish 与 generate 在准入/装载边界从已发布仓库按摘要拉取并复验完整性后物化为完整场景，包本体不改写；无仓库或引用漂移一律失败关闭。全内嵌旧路径零改动；段模板的自动检索/选择仍未开放（`template match` 仅只读评分）。
- 迁移段资产（2026-11-17 用户授权）：`template-assets/` 存放从 2026Oct 项目迁入的 13 项段资产（6 风格/7 版式；原品牌资产已随品牌段移除删除），每项含逐字节原件与适配主仓 Schema 的契约，`MIGRATION.yaml` 记录源摘要与适配规则，守卫测试防漂移。它们是库参考资产：仅供只读匹配与段引用消费，未过 T1/TP 与验证渲染门禁，不是生产可用模板；入库走真实 publish 路径（开发种子脚本见 `template-assets/README.md`）。
- 配色红线（map-style.md §8.2 目标设计的可校验部分）：generate 链在色值冻结前执行三条检查——顺序/分歧色带须与声明的感知结构一致（sequential 的 L* 单调、diverging 的亮心中点，CIE 15 CIELAB）、相邻类 ΔE76 可区分、二色觉模拟（Machado 2009）后仍可区分；离散类别色查后两条，不查单调性。参数与执行级别全部在 `policies/color-redlines-policy.yaml`（`pending-business-review`；R1/R2 阻断、色觉安全首期警告）；blocker 失败关闭，warning 不阻断。模板包不含实例颜色，故 template validate/publish 零改动；WCAG 对比度公式已就绪但未接线（契约尚未声明文字/背景色对）；不自动选色、不改写通过检查的色值。
- 不接纳旧 `scene_hint`、单值 `theme` 或 `fields.theme`；不自动迁移旧输入、候选或锁。详见 `workflows/intent-contract.md`。
- 识别词表不等于可执行能力：现有分类保留为目录词汇；业务能力注册表和代码实现白名单当前只登记 `general-thematic-mapping`（实现 `general-thematic`），其余场景与组件一律默认拒绝。

## 布局契约消费（第一阶段）

- `scenario.embedded.layout.frames[].content_id` 显式绑定 view/overlay，公共 `compiler/layout.py` 将毫米 frame 解析为像素位置；场景构建器不再硬编码模块的页面位置。
- 类型化 `resolved_layout` 同时保存模板源合同、显式参数及实例框，并进入 RenderScene 和 execution，预览、锁驱动渲染及终检重新验证同一布局快照；缺少快照的旧候选/锁不得自动补齐。
- 当前支持毫米画布、DPR=1、单图及模板声明的有限网格，页面框默认互不重叠；地图使用 `clip`，其他内容使用 `reject`。多图由静态后端消费；浏览器仍只接受单图，其他溢出策略和 inset 明确拒绝。
- **有意重叠只接受显式声明的完整包含**：`layout.frames[].inside_frame` 声明某个非地图框完全位于某个地图框内（如地图内置指北针/图例）。声明是语义，包含是机械核验：程序检查引用存在、非自引用、非链式、容器为 `map`、被包含者非 `map`，并验证几何完整包含；解析快照携带该声明，重验时重新推导同一豁免。未声明的重叠、部分重叠、被包含框之间互相遮盖仍报 `LAYOUT_FRAME_OVERLAP`（永久禁止，不是可排期缺口）；声明不合法分别报 `LAYOUT_CONTAINMENT_REFERENCE`、`LAYOUT_CONTAINMENT_TYPE`、`LAYOUT_CONTAINMENT_NOT_ENCLOSED`。有限网格的多图基座不接受该声明（`GRID_BASE_INVALID`），因为网格会重建地图框。包含不放宽内容适配门禁：被包含框仍按自身边界拒绝溢出。任意覆盖区域、层级声明与裁剪仍未开放。
- 浏览器后端先按地图框视口截图再合成整页；静态栅格后端直接消费同一物理版面。纸张与 DPI 均受场景策略限制。
- 浏览器/SVG 路径仍使用固定图元保守包络；静态栅格整页使用实际字体测量、显式换行和溢出拒绝。两者均未实现自动布局候选搜索或复合布局求解。
- 不可覆盖已发布模板或冻结锁；采用新版契约须重新验证、发布、编译、预览并获取相应精确审批。

## IDE 宿主最小接入

Codex / Claude Code 在 VS Code 中以“读取仓库指令 + 宿主终端调用 CLI”使用同一份 Skill。此入口不依赖 Hermes，不要求新增 MCP 服务、模型 API 客户端或全局 Skill 副本；IDE 配置只提供执行便利，不是业务协议或授权证据。

1. 从仓库根目录执行。确认 Python 3.11+ 的真实解释器和依赖；先执行 `python skills/carto-agent/scripts/carto.py --help`、`python skills/carto-agent/scripts/carto.py schema check`。`python` 指本次确认可用的解释器。缺依赖时报告缺项，获得用户同意后再安装，不读取凭据文件或输出完整环境变量。
2. 需要渲染时，再显式执行 `python skills/carto-agent/scripts/carto.py environment probe-renderer`。它会进行本机工具/字体和无头浏览器探测；退出码为 0 只表示报告生成成功，还要核对 `environment.status` 与能力项。此结果不证明 IDE 会话的 GIS 工具可用或生产能力已开放。
3. 按 `workflows/routing.md` 选择唯一路由，读取对应工作流和 CLI 子命令帮助。只使用用户明确授权的输入、项目目录和允许根；缺少路径、语义或权限时先询问，不把测试 Fixture 当作用户数据，不自动选择业务场景，也不自动跑 `tools/host/` 的 bootstrap。
4. 使用参数化终端调用现有 CLI；各步骤继续核对退出码和实际 JSON 结果，失败即停，按既有恢复协议查询状态。遇到不支持的场景、TIFF/CRS 等能力，明确报告未开放，不通过改策略、改锁或直接调用其他工具绕过主链。
5. 宿主的命令确认和聊天中的“同意”不能替代有效业务审批回执；到 T1 / TP / G1 / G2 / G3 必须继续由现有程序验证精确授权。测试中的模拟审批不能用于真实执行。

仓库 `.vscode/tasks.json` 仅提供帮助、Schema 自检、显式渲染探测及开发测试；不提供自动生成或自动交付任务。VS Code Python 选择与 Agent 终端解释器须分别确认。此阶段不宣称原生 Skill 选择器注册、宿主工具结果可信回传或 IDE 会话端到端验收已完成。

## 宿主接入预检

用户要求检查 Hermes、Skill 装载或现有工具时，阅读 `workflows/host-preflight.md`，使用唯一 CLI 的 `environment probe-host`。这是辅助检查，不放宽地图生成的现有边界。安装/链接、本机资源读取、实际会话工具、生产能力应分别验证；预检报告不能替代 ToolResult 或审批。不要因没有 GIS 工具而自动安装软件或上传业务数据。

## 固定术语

- `map-brand`：地图身份模板。
- `map-style`：制图表达规范。
- `map-layout`：地图版式模板。
- `business_scene`：业务场景（业务用途分类）。
- `theme_tags`：主题标签（内容机器 ID 列表）。
- `map-scenario`：制图场景方案模板，不是业务场景分类。
- `RenderScene`：一次渲染的实例描述，不是业务场景分类。
- 规则语义：`hard_rule`、`forbidden`、`mandatory`、`binding`、`default`、`reference`。
- 结果严重度：`blocker`、`error`、`warning`、`info`。

## A3.1 设计修订与证据

- `revision-brief` 生成完整修订 MapBrief；`revise` 验证新 G1 后提交不可变 `revisions/rN/` 并返回新的 `request_path`。旧候选、预览和回执不覆盖，旧 G2 不批准新版本。
- 冻结后设计变更走新运行，不修改旧锁。累计预算和状态事务约束修订及中断恢复。
- 成品审查动作是 `approve-product-review / validation-report`，不是 G2。ProductReview 先持久化，再生成绑定它的 Manifest 和 G3 对象。
- 属性 CSV 和普通文本/CSV 素材冻结字节与处理证据。栅格配色仍来自就绪分类合同；OCR、图片解析、项目内任意设计尚未开放。
- 当前执行步骤以 `workflows/generate-map.md` 和 CLI `--help` 为准；合成数据与测试签名不是实际业务审批。
