# U-P1：内核骨架与协议层 — 实施说明文档

## 文档信息

| 项目 | 内容 |
|---|---|
| 阶段 | U-P1：内核骨架与协议层 |
| 对应架构 | A（后半） |
| 对应 TRD | P1 / GM-P1 |
| 实施日期 | 2026-09-15 |
| 依据 | [实施计划 v2.1](../implement-plan.md) 第三章 |
| 前置阶段 | [U-P0：规范收敛与安全底座](U-P0说明文档.md) |
| 状态 | 退出标准 9 项已完成，1 项生产 MapLibre Web/SVG 渲染适配器显式延期 |

---

## 术语速查（写给开发小白）

> 以下用前端 / 后端开发者熟悉的概念来解释 U-P1 新引入的专业词汇。U-P0 的术语（安全原语、路径穿越、防重放等）请参见 U-P0 说明文档，此处不重复。

### 架构类

#### 五模块骨架（Five Module Skeleton）

**一句话**：把整个系统拆成五个各管一摊的"部门"，每个部门有明确职责和接口边界。

**类比**：就像一家公司分了五个部门——运营部（workflow）负责调度协调、技术部（compiler）负责把需求编译成可执行的方案、质检部（validation）负责检查质量、采购部（adapters）负责对接外部工具和资源、档案部（repository）负责存储和版本管理。骨架阶段就是"部门成立、岗位到人、流程跑通"，但还没接真实业务。

**在本项目中**：`workflow/`、`compiler/`、`validation/`、`adapters/`、`repository/` 五个目录就是五个部门，各自有 `__init__.py` 声明导出接口。

---

#### 状态机（State Machine）

**一句话**：一个作业从开始到结束，经历多个固定步骤，每步有明确状态，不能跳步。

**类比**：就像快递物流跟踪——"已下单 → 已揽收 → 运输中 → 派送中 → 已签收"。你不能从"已下单"直接跳到"已签收"，每一步都有记录。如果中途断了（程序崩溃），重启后从上一步继续，不从头来。

**在本项目中**：`WorkflowStateStore` 管理作业的 `pending → running → waiting_approval → succeeded/failed` 状态流转。状态持久化到 JSON 文件，崩溃后可以恢复。

---

#### 步骤回执（Step Receipt）

**一句话**：每完成一个步骤，生成一张"收据"记录这步做了什么、输入是什么、输出是什么、用了什么工具。

**类比**：就像快递的每个中转节点都有签收记录——"到达北京分拣中心，时间 X，操作员 Y，包裹状态 Z"。回执的作用是可追溯：出了问题能定位到哪一步、谁操作的、输入对不对。

**在本项目中**：`StepReceipt` 是 frozen dataclass，记录 `step`、`attempt`、`input_fingerprint`、`prerequisite_fingerprints`、`tool_versions`、`output_refs`、`started_at`、`completed_at`。回执存为 JSON 文件，有 Schema 校验。

---

#### 输入指纹与前提漂移检测（Input Fingerprint & Prerequisite Drift）

**一句话**：用哈希值给输入数据"盖章"，恢复时重新算一遍，指纹变了说明输入被改过，拒绝继续。

**类比**：就像你寄快递时拍了包裹的照片留底。收到包裹时再拍一张对比——如果照片不一致，说明包裹被调包了，拒收。

**在本项目中**：`initialize` 时算 `input_fingerprint`；`resume` 时重算对比。如果指纹不一致，报错 `JOB_INPUT_DRIFT`。前提条件也同理检测漂移。

---

### 工具与适配器类

#### 工具网关（ToolGateway）

**一句话**：所有外部工具调用都必须经过的一个"收费站"，先查权限、再查预算、再调用、最后固定输出。

**类比**：就像公司的采购审批系统——你想买什么东西，先查采购目录里有没有（能力注册）、再查你的预算够不够（预算检查）、然后下单（调用工具）、最后入库登记（固定产物）。不能绕过系统直接找供应商。

**在本项目中**：`ToolGateway.invoke()` 的调用链：能力查表 → 项目范围校验 → 授权能力检查 → 预算消耗 → 输入校验 → 调用 → 输出校验 → 不可变存储 → 回执生成。默认拒绝（`default: deny`），未注册能力直接拒绝。

---

#### 能力注册表（Capability Registry）

**一句话**：一个"白名单"，只有预先登记过的工具能力才能被调用。

**类比**：就像小区的门禁卡系统——物业预先录入哪些卡能开哪些门。你没录入的卡，门禁不开。

**在本项目中**：`tool-bindings.yaml` 策略文件定义了六个能力：`local-file-read`、`schema-validate`、`renderer-capability-register`、`web-map-preview`、`web-map-export` 和 `svg-compose`。`ToolGateway` 构造时加载策略，运行时只认白名单内的能力。

---

#### 授权边界（Authorization Boundary）

**一句话**：即使工具在白名单里，还得看你这个用户有没有权限调用它。

**类比**：就像公司门禁系统有两层——工牌能进大楼（已注册能力），但机房只有 IT 部的工牌能进（授权范围）。你有工牌不代表什么门都能开。

**在本项目中**：`ExecutionContext.authorized_capabilities` 是用户被授权的能力集合。`ToolGateway.invoke()` 先查能力是否注册，再查用户是否被授权调用这个能力。两层都过了才执行。

---

#### MCP 适配（MCP Adapter）

**一句话**：一个"发现门面"——能发现 MCP 服务器上有哪些能力，但发现不等于授权。

**类比**：就像 App Store——你能浏览到很多 App（发现），但不代表你都能用（需要购买/授权）。发现是信息层面的，授权是安全层面的。

**在本项目中**：`McpAdapter` 只做发现（`discover()`）和绑定转发（`bind()`）。如果发现的能力不在 `ToolGateway` 白名单里，`bind()` 直接报错 `CAPABILITY_UNREGISTERED`。MCP 发现的能力必须经过注册和授权才能调用。

---

#### 环境指纹（Environment Fingerprint）

**一句话**：探测当前 Web 地图渲染环境（受控浏览器、Node、WebGL、离线能力、导出格式和中文字体）的状态，生成一个哈希“指纹”，用于检测环境变化。

**类比**：就像给电脑做体检——检查浏览器、Node、字体和渲染能力，生成一份报告。下次运行前再体检一次对比指纹，如果环境变化，需要重新验证。

**在本项目中**：`RendererCapabilityProbe.run()` 检查浏览器和 Node 命令、中文字体及静态能力配置，生成 capabilities 和 fingerprint。除非后续受控浏览器/WebGL 握手真正建立生产能力，否则它按 fail-closed 返回 `status=unavailable`、`webgl_available=false`、`headless_export=false`。

---

### 编译器与校验类

#### 协议编译器（ProtocolCompiler）

**一句话**：把多份"契约"文件按依赖顺序排列、逐一校验、生成快照——不是运行代码，只是数据层面的"组装"。

**类比**：就像把合同附件按依赖关系排序——先基础条款、再扩展条款、最后补充协议——然后检查每份附件格式对不对，最后生成一份"合同摘要"。

**在本项目中**：`ProtocolCompiler.compile()` 接收契约列表和依赖图，用 `DependencyResolver` 做拓扑排序，逐一 Schema 校验，生成带摘要的快照。不做参数求解或业务逻辑。

---

#### 依赖解析（DependencyResolver）

**一句话**：按依赖关系排出先后顺序，检测循环依赖。

**类比**：就像安装软件时的依赖处理——先装 Node.js 才能装 npm 包。如果 A 依赖 B、B 又依赖 A，就死锁了，直接报错。

**在本项目中**：`DependencyResolver.resolve()` 做拓扑排序（DFS），发现循环依赖报错 `DEPENDENCY_CYCLE`，发现未固定依赖报错 `DEPENDENCY_NOT_PINNED`。

---

#### 所有权解析（OwnershipResolver）

**一句话**：把不同"所有者"提供的配置段合并，检测冲突——同一个字段不能被两个所有者赋予不同的值。

**类比**：就像拼图——每块拼图属于一个人，拼的时候发现两块形状一样的拼图颜色不同，说明有人放错了，报冲突。

**在本项目中**：`OwnershipResolver.merge()` 合并各段配置，如果同一字段被不同所有者赋了不同的值，报错 `OWNERSHIP_CONFLICT`。

---

#### 校验器注册表（CheckerRegistry）

**一句话**：一个"质检员花名册"——注册了哪些检查项、每个检查项在什么阶段执行、失败严重度是什么。

**类比**：就像工厂的质检流程——注册了"尺寸检查""外观检查""功能测试"三个质检员，分别在"成型""抛光""组装"三个阶段执行。每个质检员独立出报告。

**在本项目中**：`CheckerRegistry` 从 `checker-registry.yaml` 加载检查项定义，按 `phase` 过滤执行，生成 `ValidationReport`（含每项 `CheckResult`）。blocker 级别的失败会导致整份报告状态为 failed。

---

### 存储类

#### 不可变存储（ImmutableArtifactStore）

**一句话**：写入后不可修改的文件存储——同一内容写两次返回同一文件，尝试写入不同内容到同一位置会被拒绝。

**类比**：就像区块链——每个区块有哈希值，相同内容生成相同哈希。如果你试图用相同哈希存不同内容，系统检测到冲突就拒绝。

**在本项目中**：`ImmutableArtifactStore.put()` 用 `sha256_digest` 做内容寻址（content-addressed），相同内容写到同一路径直接返回（幂等），不同内容同一路径报错 `IMMUTABLE_ARTIFACT_CONFLICT`。写入用原子操作（临时文件 + `os.replace`）。

---

#### 内容寻址（Content-Addressed）

**一句话**：用内容的哈希值当文件名，内容相同就是同一个文件。

**类比**：就像用身份证号找人——两个人身份证号一样就是同一个人。内容寻址用哈希值找文件，哈希一样就是同一份文件。

---

#### 版本化目录（VersionedCatalog）

**一句话**：按"ID + 版本号"查找条目的内存索引，同一 ID 可以有多个版本。

**类比**：就像 NuGet/npm 包仓库——同一个包名有多个版本（1.0.0、1.1.0、2.0.0），精确到版本号才能找到对应的包。

---

### 智能体运行类

#### 类型化候选（Typed Candidate）

**一句话**：AI 模型提交的方案必须符合预定义的 Schema，不接受任意格式的输出。

**类比**：就像提交表单——前端必须按表单字段填写，不能自己加个 textarea 随便写。后端拿到数据先做表单校验，不合法的直接打回。

**在本项目中**：`BoundedAgentRuntime.submit()` 接收 `AgentSubmission`，包含 `role`（planner/composer）、`schema_name`（map-plan/resolved-map）、`candidate`（数据）。先检查角色和 Schema 是否匹配，再检查内容不含可执行代码，最后做 Schema 校验。

---

#### 可执行内容拒绝（Executable Content Rejection）

**一句话**：AI 模型提交的数据里如果藏着 SQL、Shell 命令、Python 代码等可执行内容，直接拒绝。

**类比**：就像快递安检——包裹里不能有危险品。即使寄件人说"这是合法的"，安检机检测到违禁品就退回。

**在本项目中**：`_reject_executable_content()` 递归检查提交数据，发现 `sql`、`shell`、`python_code`、`gis_expression` 等字段名或 `select `、`subprocess`、`eval(` 等代码片段，报错 `MODEL_EXECUTABLE_CONTENT_DENIED`。

---

#### 预算耗尽阻断（Budget Exhaustion）

**一句话**：给 AI 模型运行设定资源上限（调用次数、耗时、成本、上下文大小等），超出就强制停止。

**类比**：就像手机流量套餐——用了 10GB 之后自动断网。不是"建议你别用了"，而是物理上无法继续。

**在本项目中**：`ExecutionBudget` 有 6 个资源维度（tool_calls、model_calls、revisions、elapsed_seconds、cost_units、context_bytes）。每次调用 `consume()` 累加，超出上限抛出 `EXECUTION_BUDGET_EXCEEDED`。还包括"修复次数"限制——同一修订下只允许有限次修复。

---

#### 角色上下文隔离（Role Context Isolation）

**一句话**：不同角色（planner/composer）只能看到自己该看的材料，不该看的自动过滤。

**类比**：就像公司会议室的投影——给销售部开会时只投影销售数据，不会把财务报表也放上去。信息按需展示，最小化暴露。

**在本项目中**：`BoundedAgentRuntime.stage_context()` 按角色过滤上下文字段。planner 只能看到 `intent/brief/templates/evidence/data_summary`，composer 只能看到 `plan/prepared_data/templates/validation`。过滤后还会调用 `redact_for_log` 脱敏敏感字段。

---

#### 审批门禁协调器（ApprovalGateCoordinator）

**一句话**：统一管理 G1/G2/G3 三个门禁的审批回执验证，确保每个门禁检查的内容和上下文都正确。

**类比**：就像机场的三道安检——值机柜台查票（G1）、安检通道查行李（G2）、登机口查身份（G3）。每道检查的内容不同，不能混用。

**在本项目中**：`ApprovalGateCoordinator.require()` 接收门禁 ID（G1/G2/G3），查找对应的 `GateDefinition`（action + object_type），调用 U-P0 的 `verify_receipt()` 验证回执的签名、上下文绑定和防重放。G1 检查的是 `approve-map-brief` + `map-brief`，G2 是 `approve-freeze` + `resolved-map`，G3 是 `approve-delivery` + `delivery-manifest`。

---

#### 固定数据准备（Deterministic DataPreparer）

**一句话**：按固定流程处理数据，不走 AI、不执行动态代码，只做预定义的安全操作。

**类比**：就像流水线加工——零件按固定工序依次经过切割、打磨、组装，每一步都是预定义的操作。不需要"智能"决定怎么加工，按 SOP 来就行。

**在本项目中**：`DeterministicDataPreparer.prepare_data()` 只执行 `allowed_operations`（read/filter/join/reproject/aggregate/classify）内的操作，拒绝 `forbidden_operations`（dynamic-python/shell/arbitrary-sql/unapproved-download）。输出 `PreparedDataBundle` 含数据集、变换链、质量证据和摘要。

---

#### 意图解析（IntentResolver）

**一句话**：从用户的自然语言描述中识别出属于哪个业务场景、需要什么任务、还缺什么信息。

**类比**：就像医院的分诊台——你说"肚子疼"，分诊护士判断你去内科还是外科、需要做什么检查、还缺什么信息（比如有没有发烧）。如果说不清是哪个科，就让你等澄清。

**在本项目中**：`IntentResolver.resolve()` 通过关键词匹配识别三场景（政务/应急/调研），检查必填信息是否齐全，检测不支持的请求动作，区分四种状态：`resolved`（清楚）、`ambiguous`（歧义）、`missing_information`（缺项）、`missing_capability`（缺能力）。输出符合 `map-intent` Schema 的结果。

---

#### 任务分派（TaskDispatcher）

**一句话**：意图解析通过后，根据场景和任务查固定策略表，生成具体的任务列表。

**类比**：分诊完成后，系统自动给你排好要做的检查项目清单——抽血、B超、心电图。

**在本项目中**：`TaskDispatcher.dispatch()` 检查意图状态是 `resolved` 且 `ready`，然后为每个任务生成 `{scene_id, task_id, handler}` 三元组。handler 格式为 `scene:{场景}:{任务}`，用于后续路由到具体处理逻辑。

---

## 一、阶段目标

建立五模块骨架、状态推进、回执、工具网关、知识服务和审批协调，形成可运行的协议层。本阶段不包含业务候选渲染流程，仅保留适配器接口、授权边界和结构化环境探测骨架。

---

## 二、U-P1 新增代码结构

```
skills/carto-agent/scripts/carto_core/
├── workflow/                    # [新] 工作流模块（编排）
│   ├── __init__.py              # 导出 JobState, StepReceipt, ExecutionContext, ExecutionBudget
│   ├── router.py                # 路由注册与分发（RouteRegistry）
│   ├── models.py                # 作业状态、步骤回执、执行上下文、预算（4 个 dataclass）
│   ├── state_machine.py         # 状态存储、初始化、恢复、完成步骤、重试（WorkflowStateStore）
│   ├── intent.py                # 意图解析与任务分派（IntentResolver + TaskDispatcher）
│   ├── approvals.py             # G1/G2/G3 门禁协调（ApprovalGateCoordinator）
│   ├── agent_runtime.py         # 类型化提交、可执行内容拒绝、预算、角色上下文隔离（BoundedAgentRuntime）
│   └── data_preparation.py      # 固定流程数据准备（DeterministicDataPreparer）
│
├── compiler/                    # [新] 编译器模块
│   ├── __init__.py              # 导出 CompileRequest, ProtocolCompiler, DependencyResolver, OwnershipResolver
│   ├── protocol.py              # 协议编译器：校验、排序、快照（ProtocolCompiler）
│   ├── dependencies.py          # 依赖拓扑排序与循环检测（DependencyResolver）
│   └── ownership.py             # 所有权段合并与冲突检测（OwnershipResolver）
│
├── validation/                  # [新] 校验模块
│   ├── __init__.py              # 导出 CheckResult, ValidationReport, CheckerRegistry
│   ├── models.py                # 检查结果与校验报告（2 个 frozen dataclass）
│   └── registry.py              # 检查器注册表：按阶段执行、生成报告（CheckerRegistry）
│
├── adapters/                    # [新] 适配器模块
│   ├── __init__.py              # 导出 ToolGateway、McpAdapter、RendererCapabilityProbe、WebMapRendererAdapter、SvgCompositor
│   ├── contracts.py             # 能力处理器与地图适配器协议接口（Protocol 类型）
│   ├── tool_gateway.py          # 工具网关：注册、授权、预算、调用、固定产物（ToolGateway）
│   ├── mcp.py                   # MCP 发现门面：发现不等于授权（McpAdapter）
│   ├── renderer_probe.py        # Web 渲染环境能力探测（RendererCapabilityProbe）
│   ├── webmap_renderer.py       # RenderScene 编译、语义校验、会话和回执验证
│   └── svg_compositor.py        # 地图截图与 SVG overlay 安全合成
│
├── repository/                  # [新] 存储模块
│   ├── __init__.py              # 导出 ImmutableArtifactStore, VersionedCatalog, DomainKnowledgeService
│   ├── immutable_store.py       # 内容寻址不可变存储（ImmutableArtifactStore）
│   ├── catalog.py               # 版本化目录索引（VersionedCatalog）
│   └── knowledge.py             # 领域知识服务（DomainKnowledgeService）
│
├── cli.py                       # [更新] 新增 intent resolve、environment probe-renderer、data prepare 子命令
├── canonical.py                 # [U-P0] 规范化 JSON 与摘要
├── errors.py                    # [U-P0] 统一错误类型
├── schema_registry.py           # [U-P0] Schema 注册表
└── security/                    # [U-P0] 安全原语（无变更）
    ├── __init__.py
    ├── approval.py
    ├── authorization.py
    ├── paths.py
    └── sensitive.py
```

**新增 Schema（6 个）**：

| Schema 文件 | 用途 |
|---|---|
| `step-receipt.schema.json` | 步骤回执数据结构 |
| `tool-result.schema.json` | 工具调用结果数据结构 |
| `validation-report.schema.json` | 校验报告数据结构 |
| `environment-fingerprint.schema.json` | 环境探测指纹数据结构 |
| `render-scene.schema.json` | 后端到前端的渲染场景、资源、图层和 overlay 协议 |
| `render-receipt.schema.json` | 绑定场景、渲染器版本、资源证据和输出产物的 HMAC 回执 |

**新增测试**：

| 测试文件 | 行数 | 测试用例数 |
|---|---|---|
| `test_up1.py` | 504 | 31 |

---

## 三、五模块骨架详解

### 3.1 workflow 模块（编排）

#### 3.1.1 路由分发 — RouteRegistry

**文件**：[workflow/router.py](../../skills/carto-agent/scripts/carto_core/workflow/router.py)

`RouteRegistry` 提供路由注册和分发。注册时检测重复路由名（`ROUTE_DUPLICATE`），分发时未实现路由返回 `ROUTE_NOT_IMPLEMENTED`。

#### 3.1.2 作业状态与步骤回执 — JobState / StepReceipt / WorkflowStateStore

**文件**：[workflow/models.py](../../skills/carto-agent/scripts/carto_core/workflow/models.py) + [workflow/state_machine.py](../../skills/carto-agent/scripts/carto_core/workflow/state_machine.py)

| 数据结构 | 字段 | 说明 |
|---|---|---|
| `JobState` | status, step, attempt, run_id, input_fingerprint, last_receipt | 作业当前状态 |
| `StepReceipt` | receipt_id, run_id, step, attempt, status, input_fingerprint, prerequisite_fingerprints, tool_versions, output_refs, started_at, completed_at, error | 单步执行凭证 |
| `ExecutionContext` | run_id, tenant_id, project_id, subject_id, roles, namespaces, authorized_capabilities, classification, environment, budget | 运行时上下文 |
| `ExecutionBudget` | 6 个资源维度 + 6 个已用量 | 预算追踪 |

`WorkflowStateStore` 的核心方法：

| 方法 | 功能 | 防护 |
|---|---|---|
| `initialize` | 创建新作业，写入初始状态 | 检测 `JOB_ALREADY_EXISTS` |
| `load` | 加载现有作业状态 | Schema 校验 `job-state` |
| `resume` | 恢复作业，检查输入和前提指纹 | 检测 `JOB_INPUT_DRIFT` 和 `JOB_PREREQUISITE_DRIFT` |
| `complete_step` | 完成当前步骤，生成回执，推进状态 | 回执 Schema 校验，检测 `STEP_RECEIPT_ALREADY_EXISTS` |
| `retry` | 重试当前步骤，增加 attempt 计数 | — |

状态文件使用原子写入（临时文件 + `os.replace` + `os.fsync`），防止崩溃导致状态文件损坏。

#### 3.1.3 意图解析与任务分派 — IntentResolver / TaskDispatcher

**文件**：[workflow/intent.py](../../skills/carto-agent/scripts/carto_core/workflow/intent.py)

`IntentResolver.resolve()` 的处理流程：

```
1. 关键词匹配三场景（政务/应急/调研）
2. 如果用户指定了场景但与匹配结果冲突 → ambiguous（歧义）
3. 如果多个场景同时匹配 → ambiguous（歧义）
4. 如果没有匹配 → unsupported（不支持）
5. 检查 unsupported_actions → 如果有越界请求 → unsupported
6. 检查 required_information → 如果缺项 → missing_information
7. 检查 required_capabilities → 如果缺能力 → missing_capability
8. 全部通过 → resolved + ready
```

输出结果符合 `map-intent` Schema，包含 `intent_status` 和 `readiness_status` 两个独立状态字段。

`TaskDispatcher.dispatch()` 只在意图状态为 `resolved` 且 `readiness_status` 为 `ready` 时才分派任务，否则抛出 `INTENT_NOT_RESOLVED` 或 `INTENT_NOT_READY`。

#### 3.1.4 审批门禁协调 — ApprovalGateCoordinator

**文件**：[workflow/approvals.py](../../skills/carto-agent/scripts/carto_core/workflow/approvals.py)

| 门禁 | action | object_type |
|---|---|---|
| G1 | approve-map-brief | map-brief |
| G2 | approve-freeze | resolved-map |
| G3 | approve-delivery | delivery-manifest |

`ApprovalGateCoordinator.require()` 复用 U-P0 的 `verify_receipt()`，额外绑定 `gate.action` 和 `gate.object_type`，确保 G1 的审批不能用于 G2，反之亦然。

#### 3.1.5 智能体运行 — BoundedAgentRuntime

**文件**：[workflow/agent_runtime.py](../../skills/carto-agent/scripts/carto_core/workflow/agent_runtime.py)

| 方法 | 功能 | 防护 |
|---|---|---|
| `submit` | 接收类型化候选 | 角色与 Schema 匹配检查 + 可执行内容拒绝 + Schema 校验 + 预算消耗 |
| `repair` | 消耗修复次数配额 | 超出 `max_revisions` 报 `EXECUTION_BUDGET_EXCEEDED` |
| `stage_context` | 按角色过滤上下文 | 只暴露该角色允许的字段 + `redact_for_log` 脱敏 |

可执行内容拒绝检查两层：
1. 字段名：`sql/shell/command/python/python_code/gis_expression`
2. 字符串内容：`select/insert/delete/subprocess/os.system/eval(/exec(`

#### 3.1.6 固定数据准备 — DeterministicDataPreparer

**文件**：[workflow/data_preparation.py](../../skills/carto-agent/scripts/carto_core/workflow/data_preparation.py)

检查策略文件确保 `default_mode` 是 `deterministic` 且 `data_agent.enabled` 是 `false`。准备时检查操作是否在允许集合内且不在禁止集合内，输出符合 `prepared-data-bundle` Schema 的数据包。

### 3.2 compiler 模块

**文件**：[compiler/](../../skills/carto-agent/scripts/carto_core/compiler/)

| 组件 | 功能 |
|---|---|
| `ProtocolCompiler` | 校验契约 → 排序 → 检查完整性 → 生成带摘要的快照 |
| `DependencyResolver` | 拓扑排序（DFS），检测循环依赖和未固定依赖 |
| `OwnershipResolver` | 合并各段配置，检测同字段冲突 |

### 3.3 validation 模块

**文件**：[validation/](../../skills/carto-agent/scripts/carto_core/validation/)

`CheckerRegistry` 从 `checker-registry.yaml` 加载检查项定义，按 `phase` 过滤执行。每个检查项有独立的 handler 函数，返回 `(passed: bool, details: dict)`。生成 `ValidationReport` 符合 `validation-report` Schema，blocker 级失败会导致报告状态为 failed。

### 3.4 adapters 模块

**文件**：[adapters/](../../skills/carto-agent/scripts/carto_core/adapters/)

| 组件 | 功能 |
|---|---|
| `ToolGateway` | 能力查表 → 项目范围 → 授权检查 → 预算 → 输入校验 → 调用 → 输出校验 → 不可变存储 → 回执 |
| `McpAdapter` | MCP 能力发现门面，发现不等于授权，`bind()` 时走 ToolGateway 注册 |
| `RendererCapabilityProbe` | 探测浏览器、Node、中文字体和声明能力；未完成真实 WebGL 握手时按 fail-closed 返回不可用 |
| `WebMapRendererAdapter` | 编译并校验 `RenderScene`，绑定 Renderer Profile 和受控渲染会话 |
| `RenderReceiptValidator` | 验证回执 HMAC、场景/版本/资源/输出和时间证据 |
| `SvgCompositor` | 在允许根内将地图截图和 overlay 合成为可编辑 SVG |
| `contracts` | `CapabilityHandler` 和 `MapAdapter` 协议接口定义 |

### 3.5 repository 模块

**文件**：[repository/](../../skills/carto-agent/scripts/carto_core/repository/)

| 组件 | 功能 |
|---|---|
| `ImmutableArtifactStore` | 内容寻址存储，SHA256 做文件名，写入后不可改，相同内容幂等 |
| `VersionedCatalog` | 内存索引，按 (id, version) 查找，支持多版本 |
| `DomainKnowledgeService` | 只查已注册的本地知识源，未注册源报错，返回带版本和摘要的 `KnowledgeEvidence` |

---

## 四、CLI 扩展

**文件**：[cli.py](../../skills/carto-agent/scripts/carto_core/cli.py)（96 → 151 行）

新增三组子命令：

```
carto intent resolve <request>           # 意图解析
  --allowed-root <dir> (required)

carto environment probe-renderer          # Web 渲染环境能力探测

carto data prepare <task>                 # 固定数据准备
  --allowed-root <dir> (required)
  --run-id --tenant-id --project-id --subject-id (required)
```

所有新增命令的输出都经过 Schema 校验后才返回。

---

## 五、测试体系

**文件**：[test_up1.py](../../skills/carto-agent/scripts/tests/test_up1.py)（223 行，10 个测试用例）

| 测试类 | 测试用例 | 验证内容 |
|---|---|---|
| StateAndRepositoryTests | 状态回执不可变且恢复检测漂移 | initialize → complete_step → resume → 检测 JOB_INPUT_DRIFT |
| | 不可变存储内容寻址 | 相同内容写到同一路径返回同一文件 |
| ToolAndKnowledgeTests | 网关拒绝未注册和未授权能力 | CAPABILITY_UNREGISTERED + CAPABILITY_SCOPE_DENIED |
| | 网关固定类型化输出并执行预算 | 预算耗尽后 EXECUTION_BUDGET_EXCEEDED |
| | MCP 发现不等于授权 | discovered 能力 bind 时被拒绝 |
| | 知识服务返回版本化证据并拒绝未注册源 | 查询通过 + 未注册源报错 |
| IntentAndRuntimeTests | 三场景可解析并分派 | 政务/应急/调研各一例 |
| | 歧义/缺项/缺能力/拒识四种状态区分 | 4 种 intent_status/readiness_status 各一例 |
| | 智能体运行只接受类型化非可执行候选 | 可执行内容被拒绝 + 修复次数有限 |
| | 敏感值不跨角色上下文 | itinerary 被脱敏，raw_credentials 被过滤 |
| ProtocolAndGateTests | 依赖和所有权冲突阻断 | 循环依赖 + 所有权冲突 |
| | 编译器和校验器返回结构化结果 | 快照含摘要 + 报告通过 Schema 校验 |
| | G1/G2/G3 验证精确上下文 | 三门禁各自通过 + 错误回执被拒绝 |
| | 固定数据准备返回合法包 | bundle 通过 Schema 校验 |
| | 渲染器探测始终返回合法可重放指纹 | 指纹以 sha256 开头 + Schema 校验通过；未握手时能力为 unavailable |
| WebMapRendererAdapterTests | RenderScene、Renderer Profile、会话与 RenderReceipt | 引用/能力/版本/HMAC/资源证据不一致均被拒绝 |
| SvgCompositorTests | 截图与 overlay 安全合成 | 路径越界、覆盖、未解析坐标和不支持类型均被拒绝 |
| | 环境 CLI 返回结构化结果 | subprocess 调用返回码 0 |

---

## 六、退出标准对照

| 退出标准 | 状态 | 证据 |
|---|---|---|
| 五模块骨架可接收类型化输入并返回结构化结果 | 已完成 | workflow/compiler/validation/adapters/repository 五模块均有 dataclass 输入和 Schema 校验输出 |
| 状态推进和步骤回执可追踪 | 已完成 | WorkflowStateStore 的 initialize/complete_step/resume/retry + StepReceipt Schema 校验 |
| 工具网关可拒绝未注册能力和越权调用 | 已完成 | test_gateway_rejects_unknown_and_unauthorized_capabilities |
| 知识服务可查询获准术语并返回带版本证据 | 已完成 | test_knowledge_returns_versioned_evidence_and_denies_unregistered_source |
| 意图解析可识别三场景并区分意图歧义与缺数据 | 已完成 | test_three_business_scenes_resolve_and_dispatch + test_ambiguity_missing_information_capability_and_rejection |
| G1/G2/G3 审批可验证回执并阻断不满足条件的请求 | 已完成 | test_g1_g2_g3_verify_exact_context |
| 固定流程数据准备可交付带验收报告的 PreparedDataBundle | 已完成 | test_deterministic_data_preparation_returns_valid_bundle |
| Planner/Composer 类型化输出、有限修复、预算终止、配置版本和敏感信息边界可验证 | 已完成 | test_agent_runtime_accepts_only_typed_non_executable_candidates + test_sensitive_values_do_not_cross_role_context |
| 三场景最小评测集能够区分正确识别、缺项、歧义、拒识和越权提案 | 已完成 | test_ambiguity_missing_information_capability_and_rejection 中 4 种状态各一例 |
| 延期：生产 MapLibre Web/SVG 适配器、受控浏览器/WebGL 握手及真实 CRS/A3 PDF/PNG/中文字体冒烟 | 显式延期 | RendererCapabilityProbe 只提供结构化、fail-closed 探测；当前明确不声明生产能力 |

---

## 七、与 U-P0 的衔接

| U-P0 交付物 | U-P1 消费方式 |
|---|---|
| PathGuard | ToolGateway 调用链中的路径安全、CLI 所有文件操作 |
| ApprovalReceipt + verify_receipt | ApprovalGateCoordinator 的 G1/G2/G3 门禁验证 |
| authorize + SubjectContext | ExecutionContext 携带 roles/namespaces，ToolGateway 检查 authorized_capabilities |
| ExternalAccessPolicy + redact_for_log | BoundedAgentRuntime.stage_context 调用 redact_for_log 脱敏 |
| SchemaRegistry + load_document | 所有模块的输入输出都经过 Schema 校验 |
| canonical_json_bytes + sha256_digest | 步骤回执指纹、不可变存储寻址、编译器快照摘要 |
| security-policy.yaml | ToolGateway 构造时检查 default:deny |
| tool-bindings.yaml | ToolGateway 加载能力白名单 |
| checker-registry.yaml | CheckerRegistry 加载检查项定义 |
| intent-profiles.yaml | IntentResolver 加载三场景配置 |
| data-preparation-policy.yaml | DeterministicDataPreparer 加载操作白名单 |
| knowledge-sources.yaml | DomainKnowledgeService 加载知识来源 |

---

## 八、与后续阶段（U-P2）的衔接

| U-P1 交付物 | U-P2 消费方式 |
|---|---|
| WorkflowStateStore | 模板创建和地图生成的步骤状态推进 |
| IntentResolver | 地图生成路由的意图解析入口 |
| ToolGateway | Web 地图预览/导出、SVG 合成、数据读取等能力调用 |
| ProtocolCompiler | 六契约编译为候选快照 |
| CheckerRegistry | 候选预览和冻结的校验检查 |
| ImmutableArtifactStore | 模板包不可变版本存储 |
| ApprovalGateCoordinator | G1/G2/G3 门禁验证 |
| BoundedAgentRuntime | MapPlanner/MapComposer 类型化提交 |
| DeterministicDataPreparer | 地图生成的固定流程数据准备 |
| DomainKnowledgeService | 规划阶段的知识查询 |

---

*本文档基于 2026-09-15 代码快照编写，反映 U-P1 阶段的实际实现状态。*
