---
name: carto-agent
description: 地图制图智能体的创建模板与生成地图工作流入口。
version: 0.5.0
---

# Carto Agent Skill

本目录是地图制图智能体的唯一运行实现。当前已落地 U-P0 安全底座、U-P1 内核协议骨架、U-P2.0～U-P2.7 的 MapScenario 创建发布与地图候选冻结闭环，以及 U-P3.1～U-P3.3 的锁驱动正式渲染、成品检查、精确 G3 和原子本地交付；不得在仓库其他位置建立并行实现。

## 必读顺序

1. 阅读本文件。
2. 阅读 `workflows/routing.md`，选择且只选择一个顶层路由。
3. 读取所选路由拥有的工作流文件；尚未实现的路由必须返回明确的能力未开放错误。
4. 机器执行只读取 `schemas/`、`policies/`、注册表和项目产物，不读取 `doc/` 设计稿或 `scripts/tests/` 作为运行协议。`scripts/tests/` 仅供开发与验收阶段使用，正式发布阶段不依赖。

## 当前阶段边界

- 保留通用框架：Schema 与安全底座、状态与回执、审批协调、ToolGateway、知识服务、模板创建发布编排、候选编译与冻结、锁驱动渲染、成品检查和原子本地交付。
- **当前只注册了一个业务场景**：`general_thematic_mapping`（标准专题图编制；`policies/scenario-capabilities.yaml` v1.3.0 的 `general-thematic-mapping` 档案，代码实现白名单 `general-thematic-raster`，模板 `map-scenario/general-thematic-map@1.0.0`）。它只接受用户提供的已分类栅格（`data_nature: user-provided`、禁敏感坐标、禁生产数据），A4 横版 300dpi 输出 PDF+PNG，`production_enabled: false`，成果强制携带场景 NOTICE 与用户声明的源许可。其余一切能力仍默认拒绝：结构合法且意图就绪后，创建和生成入口对未注册能力返回 `CAPABILITY_NOT_AVAILABLE`；生成入口的缺项或歧义先返回意图错误，不能用通用 Schema 通过代替能力准入。
- 该场景的分类栅格模板样张渲染分支尚未注册：`validate` 的 fixture-render 检查失败关闭（`RASTER_FIXTURE_RENDER_UNREGISTERED`），在框架补齐并消费精确 TP 之前不得发布该模板，也不得伪造渲染证据绕过。
- 仓库不附带业务示例数据、示例模板包或默认测试项目。后续由用户提供真实数据和场景需求，完成对应实现、注册和验收后才能启用。
- 模板发布仍必须验证闭合包、依赖锁、场景验证输入、检查器集合、RenderReceipt 和环境绑定，并消费精确 TP。验证数据是否适合进入模板包由场景安全检查明确判定，不能把原始敏感业务数据打包。
- 工作流严格保留 T1 / TP / G1 / G2 / G3、运行级单写锁、revision/CAS、不可变步骤回执、受限重试及恢复证明；不得伪造审批或放松门禁以继续。
- `render` 只消费锁与摘要绑定输入；`check` 验证冻结的输出规格、布局、图例、场景声明链、字体、环境和敏感内容；`deliver` 重新验证全部绑定后，按精确 G3 进行同文件系统原子提交。
- 交付包白名单为 `map.pdf`、`map.png`、`README.md`、`delivery-manifest.yaml`、`checksums.sha256`；不包含原始数据、内部锁、审批密钥或内部回执。
- 不声明生产制图、地图工作流中的真实 CRS 转换、任意输入格式、三场景覆盖、共享服务或公网发布；`production_tasks` 为空。`map-brand`、`map-style`、`map-layout` 的业务创建路由仍未开放。
- CLI 入口：`python skills/carto-agent/scripts/carto.py --help`。
- 开发测试仅在用户允许时执行；不作为正式运行协议或真实场景验收证据。

## 基础 GIS 数据接入（第一批）

- 先阅读 `workflows/geospatial-data.md`，再通过唯一 CLI 的 `data inspect-raster` 检查显式配置的 GeoTIFF 元数据/精确类别统计；这不是新业务路由，也不生成地图。
- 可选 MCP SDK 以 stdio 接入独立 `geospatial-mcp 0.3.0`。必须显式配置可信解释器、项目/租户、数据根、catalog 和限制；不自动安装，不接受业务请求指定的服务命令/URL。
- `raster-input` 是 `generate-request.source_bindings` 的结构分支；正式共享链路见下文第三批 C。结构合法不等于业务场景或模板准入。
- 重投影已实现为 ToolGateway 适配能力（仅 nearest、显式目标 CRS）；只读 CLI 必须拒绝变换。尚未接入获批场景，不得绕过业务门禁直接调用。
- MCP 只负责基础读取/分析；类别含义、颜色、图例、排版、渲染和导出继续由 Carto 实现，不自行关联 CSV 推断类别名。

## 分类栅格准备与静态图体（第二批）

- 使用前阅读 `workflows/raster-classification.md`。`data analyze-classification` 经 MCP 统计匹配显式 CSV 列；`data clarify-classification` 接收摘要/身份绑定的回答，产生新的不可变报告。
- 未定义类别（含 0/255）或缺名称/颜色均生成动态澄清；回答不等于 G1/G2/G3，绝不改写源 NoData。
- 内部 `RasterMapBodyRenderer` 用 Rasterio + Matplotlib 从冻结数据生成图体 PNG，分类图例共用颜色合同，复用现有 SVG/布局组件；不需要 QGIS 或 MapLibre。
- 图体本身不开放独立地图导出 CLI，不注册场景，不替代 MapSpecLock/正式 RenderReceipt/成品检查；由下文第三批 C 的适配器接入正式链路。A4 横版的合成测试不等于用户地图交付或实体打印验收。
- 第三批 A 增加内部 `RasterPageRenderer`：复用冻结图体/布局，输出真实毫米 PDF、整页 PNG、字形路径 SVG，验证固定 pt 字号、字体嵌入标记/字形覆盖、文字换行和溢出；支持显式投影距离比例尺与格网北。详见同一工作流。页面报告不是正式 RenderReceipt，仍不开放导出 CLI 或业务场景。

## 共享分类着色表达（第三批 B1）

- 分类栅格是数据类型，`raster/categorical` 是表达，Rasterio + Matplotlib 是后端；三者都不是业务用途，不新建“分类栅格业务场景”。
- `compiler/raster_portrayal.py`（原 `raster_classification.py`）保留 Carto 的显示定义匹配和澄清，新增 `RasterPortrayalCompiler`，不实现 GIS 重分类/重投影。
- 共享 `portrayal` 新增 raster 图层；目录引用需精确 ID/版本/摘要。模板只声明角色和策略，项目类别表冻结到 `resolved-raster-portrayal`，图例从同一表派生。
- 图体和整页渲染改为消费 `portrayal_ref`，重验类别合同、源快照、目录与上下文；单层、nearest、保留源掩膜，未实现的多层/规则明确拒绝。
- 共享表达继续由独立的准备/显示合同冻结，第三批 C 将其接入正式链路，场景策略保持为空。旧内部快照须重新准备/编译，不保留旧模块别名或旧请求字段。

## 共享栅格正式链路（第三批 C）

- `workflow/raster_bundle.py` 将同上下文的 ready 准备报告封装为正式 PreparedDataBundle；`generate-request.prepared_raster_bindings` 显式绑定已澄清报告，不根据文件名寻找结果或默认处理 0/255。
- `compiler/raster_scene.py` 生成 `renderer_id=rasterio-matplotlib-page` 的 RenderScene，冻结 bundle、显示合同、物理版面和字体引用；向既有业务 execution 绑定 `raster_inputs` 和真实环境，不选择业务用途或执行 GIS 重投影。
- RenderScene / RenderReceipt / execution 环境按后端严格区分。预览、G2 冻结、锁驱动正式渲染与重放只按冻结 ID 分派；保留 `maplibre-web`，未知后端拒绝，栅格不探测 Chromium、不伪造浏览器版本。
- 正式栅格 RenderReceipt 由 `RasterFormalRenderer` 签发，包含 HMAC、代码/依赖环境、精确会话、资源集、页面报告和输出摘要；内部 `raster-page-output` 仍不是回执。当前是受项目路径约束的进程内后端，**不提供 OS/网络沙箱**，HMAC 不等于远程或硬件环境证明。
- 复用既有 MapSpecLock、RenderAttempt、FormalRenderEvidence、11 项成品检查、精确 G3 和原子本地交付。图例共性检查不替代业务检查；篡改产物不生成 Manifest。
- 已有从测试候选边界开始的临时合成数据 G2/G3 链路与恢复测试。**不表示 T1/TP/G1、真实模板发布或用户地图已验收**；场景组件须在独立准入后调用上述共享准备/编译器，注册策略和实现白名单仍为空，不新增审批旁路 CLI。

## 通用内核与场景扩展

- `scripts/carto_core/workflow/` 与 `compiler/map_candidate.py` 负责通用编排、协议、摘要、审批和分派，不内嵌业务模板身份、列名、纸张规格或特定业务表达规则。
- 新场景实现仅放在 `scripts/carto_core/scenarios/`，按 `scenarios/README.md` 的组件边界接入；受信注册表只使用代码内白名单，不接受请求或配置给出任意 Python 导入路径。
- 来源数据声明不等于安全认证。场景须实现来源准入和验证数据安全检查；缺少检查组件必须拒绝，不能借删除示例约束而默认接纳未知数据。
- MapIntent 同时绑定意图目录、用户意图输入与模板能力策略摘要；候选/锁固定目录及能力策略引用，渲染、检查及交付重新核验。缺失或漂移的旧绑定不自动迁移，不新增旧格式兼容分支。
- 新场景需补充严格协议、合法/非法协议用例及自动测试，再用用户授权的真实数据验收；仅修改注册策略或生产标志不能开放能力。

## 业务场景、主题与模板身份

- 只使用 `business_scene` 表达业务用途分类，不增加业务域层级。场景 ID、用途词、任务和必需信息由 `policies/intent-profiles.yaml` 统一声明；共享 Schema 检查 ID 形状，解析器检查目录成员资格。
- 主题统一使用 `theme_tags`（可多值的机器 ID）；中文显示名在目录的 `themes[].label`，不得混用为协议 ID。主题词识别内容，用途词识别业务场景；不以“洪涝”等主题词或通用“专题”一词直接决定业务场景。
- `intent resolve` 使用 `intent-request` 的 `text + selection`；`generate-request` 使用 `goal + intent`，二者复用同一个 `intentSelection` 和解析器。`tasks` 缺失必须澄清，不取任务列表第一项作为默认值。
- 生成时先解析用户意图，再验证用户明确选择的模板是否兼容；模板能力的 `intent_constraints` 只能限制可接受的场景、主题和任务，不得替用户补写或改写意图。当前不实现自动模板检索/选择。
- `MapScenario.scenario_id` 是模板方案身份，`RenderScene.scene_id` 是渲染实例身份，二者不是业务分类。Brief、Plan 与 execution 保留同一业务场景、主题标签和任务，并绑定原意图摘要。
- 不接纳旧 `scene_hint`、单值 `theme` 或 `fields.theme`；不自动迁移旧输入、候选或锁。详见 `workflows/intent-contract.md`。
- 识别词表不等于可执行能力：现有分类保留为目录词汇；业务能力注册表和代码实现白名单当前只登记 `general-thematic-mapping`（实现 `general-thematic-raster`），其余场景与组件一律默认拒绝。

## 布局契约消费（第一阶段）

- `scenario.embedded.layout.frames[].content_id` 显式绑定 view/overlay，公共 `compiler/layout.py` 将毫米 frame 解析为像素位置；场景构建器不再硬编码模块的页面位置。
- 类型化 `resolved_layout` 同时进入 RenderScene 和 execution，预览、锁驱动渲染及终检重新验证同一布局快照；缺少快照的旧候选/锁不得自动补齐。
- 当前仅支持毫米画布、DPR=1、单地图与互不重叠的页面框；地图使用 `clip`，叠加内容使用 `reject`。其他溢出策略、多地图和 inset 明确拒绝。
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
