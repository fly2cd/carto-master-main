# Carto Agent

> 地图制图智能体——用协议驱动、安全可控的方式，从意图到成图全链路打通。

Carto Agent 是一个**协议先行**的地图制图智能体。它不是"一个会画图的 LLM 插件"，而是一套有 Schema 把关、有审批门禁、有崩溃恢复、有审计链的确定性工程管线。模型负责提建议，程序负责执行——每一份输入、产物、审批都要过 Schema 校验，不合规当场拒，绝不"将就着通过"。

## 这是什么

这是一个保留了模板创建发布、地图编译预览、锁驱动渲染和受控交付流程的制图框架。

**当前没有启用业务场景，也不附带业务示例数据或模板。** 场景策略和代码实现白名单均为空；真实数据需配套实现、注册及验收对应场景后才能进入工作流，未注册请求返回 `CAPABILITY_NOT_AVAILABLE`。

## 基础 GIS 数据接入

新增 Carto 侧可选 MCP stdio 适配器和分类栅格输入契约，对接独立 `geospatial-mcp 0.3.0`：

- `carto data inspect-raster`：显式项目配置下读取 GeoTIFF 元数据和精确类别计数，输出摘要绑定的 ToolResult。
- 重投影：已实现 ToolGateway 适配能力及任务/二进制校验，仅 nearest；未开放变换 CLI 或业务场景。
- MCP 不推断类别名或生成地图，排版和渲染仍在 Carto。
- Carto 第二批新增 `data analyze-classification` / `data clarify-classification`、不可变 TIFF/CSV 快照、类别名称/颜色合同，以及可选 Rasterio + Matplotlib 静态图体与共享 SVG 图例。
- 第三批 A 的内部 `RasterPageRenderer` 已支持 A4 横版等毫米布局的 PDF/整页 PNG/SVG、固定物理字号、中文字体/图例溢出检查，以及显式投影距离比例尺和格网北；已做合成 PDF 整页视觉检查。
- 第三批 B1 接入共享 `raster/categorical` 表达及 `resolved-raster-portrayal` 冻结合同；图体/整页共用 `portrayal_ref`，显式区分数据类型、表达、后端与业务用途。显示编译模块更名为 `compiler/raster_portrayal.py`，不做 GIS 重分类。
- 第三批 C 已接入共享 PreparedDataBundle / MapSpecLock / RenderScene、闭合后端分派和真实栅格 RenderReceipt，复用 G2、锁驱动渲染、11 项终检、G3 和原子本地交付；临时合成数据已覆盖工作流及中断恢复。
- 未知像元值动态澄清，不默认隐藏 0/255。**业务场景/模板准入与真实用户地图验收仍未完成**；策略与实现白名单仍为空。内部页面报告不是 RenderReceipt，没有新增绕过审批的地图导出 CLI；静态后端是进程内实现，不提供 OS/网络沙箱。

配置、输入合同、命令和边界见 `skills/carto-agent/workflows/geospatial-data.md`、`skills/carto-agent/workflows/raster-classification.md`。基础安装不强制引入 MCP/GIS 依赖，不自动安装独立服务。

## 业务场景与主题

只使用 `business_scene` 作为业务用途分类，不新增业务域。内容主题使用 `theme_tags`（机器 ID 列表），显示名由版本化意图目录维护；MapScenario 是模板方案，RenderScene 是渲染实例，不是额外的业务分类。

独立意图解析与地图生成复用同一个解析器：`intent resolve` 输入 `text + selection`，生成请求输入 `goal + intent`。先明确实际用户意图，再检查所选模板兼容性；不从模板反填场景或默认任务，也不把主题词等同于业务场景。详见 `skills/carto-agent/workflows/intent-contract.md`。

目录可识别业务用途，不表示具有执行能力。当前能力注册仍为空；意图缺项/歧义先拒绝，就绪但无注册能力才返回 `CAPABILITY_NOT_AVAILABLE`。

## 核心设计思想

| 原则 | 通俗解释 |
|---|---|
| **协议先行，代码后行** | 先用 JSON Schema 把每种文档的格式定死，再写代码。所有人（agent、CLI、测试、人）对"什么算合格"没有歧义 |
| **模型建议，程序执行** | 模型只能提交"类型化候选"，数值计算和门禁由确定性程序控制。模型不能直接执行 SQL、Shell 或动态代码 |
| **通用内核与场景分离** | 内核负责协议、安全和编排，场景负责数据语义、表达和布局构建 |
| **结构有效不等于能力开放** | 注册、实际实现、真实场景验收和精确审批缺一不可 |
| **共享内核，独立路由** | 两条路由（创建模板 / 生成地图）共享五模块内核，各有独立的作业、审批和产物生命周期 |
| **默认拒绝** | 未知字段拒、未注册能力拒、越权调用拒、路径越根拒——宁可阻断，不可放行 |

## 项目结构

```
carto-master-main/
├── skills/carto-agent/              ← 唯一运行实现根
│   ├── SKILL.md                      智能体入口文档（Agent 先读这个）
│   ├── workflows/                    路由 + 工作流文档（routing / create-template / generate-map）
│   ├── schemas/                      JSON Schema（Draft 2020-12，机器协议）
│   ├── policies/                     策略文件（工具绑定 / 安全 / 检查器 / 范围基线）
│   ├── scripts/
│   │   ├── carto.py                   CLI 入口（安装后命令名 carto）
│   │   ├── carto_core/                核心代码
│   │   │   ├── canonical.py           摘要 / 规范化
│   │   │   ├── errors.py              错误类型与码
│   │   │   ├── schema_registry.py     Schema 加载与校验
│   │   │   ├── workflow/              编排 / 状态机 / 审批 / 渲染 / 检查 / 交付
│   │   │   ├── compiler/              依赖解析 / 候选 / 锁
│   │   │   ├── validation/            检查器模型与注册
│   │   │   ├── adapters/              受控浏览器 / 工具网关 / MCP
│   │   │   ├── repository/            不可变存储 / 模板仓库 / 交付仓库
│   │   │   └── security/              路径安全 / 审批验签 / 授权 / 脱敏
│   │   └── tests/                     通用协议、安全与组件测试
│   └── requirements.txt              jsonschema + PyYAML（仅 2 个直接依赖）
├── tools/host/                       宿主环境工具集（PowerShell）
│   ├── Bootstrap-CartoHost.ps1       一键入口
│   ├── Set-CartoBaseEnv.ps1          基础环境配置
│   ├── Install-CartoSkill.ps1        装载到宿主 Agent
│   ├── Invoke-CartoPreflight.ps1     环境就绪门
│   ├── Invoke-CartoHostCases.ps1     CLI 契约用例执行器
│   └── New-CartoProjectSpace.ps1     项目空间脚手架
├── doc/                              设计文档与实施日志
│   ├── implement-plan.md             分阶段实施计划（U-P0~U-P6）
│   ├── impl-log/                      各阶段实施记录 + 架构图
│   └── dev-log/                       开发日志
├── pyproject.toml                    构建 / 依赖 / 测试配置
├── AGENTS.md                         通用智能体入口约束
└── CLAUDE.md
```

## 两条工作路由

### 1. create-template（模板创建 → 发布）

```
analyze → brief → author(T1) → validate → publish(TP) → 不可变模板仓库
```

把一份制图场景方案变成可复用的模板包，发布到不可变仓库供后续地图生成引用。`author` 和 `publish` 需要独立审批人签发 T1/TP 回执。

### 2. generate-map（地图生成 → 交付）

```
intake → brief → compile(G1) → preview → freeze(G2) → render → check → deliver(G3) → succeeded
```

场景启用后，从已发布模板与授权数据生成地图成果。G1（制图合同）、G2（实例冻结）、G3（成果交付）三道审批门，每道都绑定身份、动作、对象摘要、作用域和一次性 nonce。最终通过 `os.replace` 原子提交产出一个含 PDF/PNG + README + 清单 + 校验和的成果包。

> **U-P3 新增的 `render → check → deliver` 三步**：锁驱动正式渲染（不重新推理）→ 11 项成品确定性检查 → G3 + 原子目录提交。每步都有不可变回执和故障注入恢复窗口。

## 主要模块

| 模块 | 职责 | 通俗比喻 |
|---|---|---|
| **workflow** | 编排步骤、状态机、审批协调、意图解析、渲染/检查/交付 | 流水线调度中心 |
| **compiler** | 依赖解析、候选快照、MapSpecLock 独占生成 | 把图纸变成可执行的施工方案 |
| **validation** | 检查器注册、11 项成品 final-check | 出厂质检站 |
| **adapters** | 受控 Chromium 渲染、工具网关（deny-by-default）、MCP 边界 | 与外部世界打交道的安全门卫 |
| **repository** | 不可变产物存储、模板仓库、交付事务 | 只进不出的档案室 |
| **security**（横切） | PathGuard 路径安全、HMAC 审批验签、RBAC 授权、日志脱敏 | 贯穿全程的安全底座 |

## 协议层（schemas + policies）

`schemas/` 下 JSON Schema 是这套系统的**机器可读法律**：

- 每一份文档（请求、回执、模板包、审批单、渲染产物、交付包……）都有对应 Schema 规定字段、类型、枚举值
- `additionalProperties: false`——未知字段默认拒绝，不能偷偷加东西
- CLI 每接收输入/产出回执前都拿 Schema 校验，不过就报 `SCHEMA_VALIDATION_FAILED`、退出码 2
- 每份 Schema 配合法、非法、语义非法三种 Fixture，保证校验逻辑没退化

`policies/` 下 策略文件是**声明式规则**：工具绑定（哪些能力允许调用）、安全策略、检查器注册表、范围基线等——被代码读取执行，不是建议。

> Tests 是开发/验收阶段的产物，不是运行时协议。SKILL.md 已标注："scripts/tests/ 仅供开发与验收阶段使用，正式发布阶段不依赖。"

## 安全模型

| 机制 | 作用 |
|---|---|
| **PathGuard** | 所有文件访问必须在 `--allowed-root` 指定的允许根内；绝对路径、越根、alternate stream、符号链接逃逸均拒 |
| **审批门禁** | T1/TP/G1/G2/G3 用 HMAC 签名 + 一次性 nonce + 绑对象摘要；**模型无权签发审批回执** |
| **ToolGateway** | `default: deny`，未注册能力和越权调用直接拒；MCP 发现不等于授权 |
| **不可变产物** | 回执、MapSpecLock、DeliveryManifest 等按 digest 寻址、create-once；下游每步重校验摘要 |
| **类型化候选** | Agent 只能提交匹配 Schema 的候选，不能提交可执行代码（sql/shell/python/gis_expression 字段被扫描拒） |
| **预算阻断** | 修复有次数上限，提交本身也吃预算；超限 → `EXECUTION_BUDGET_EXCEEDED` 阻断 |
| **日志脱敏** | 密钥、行程、应急坐标不进普通日志 |

## 前置条件

| 依赖 | 要求 |
|---|---|
| Python | ≥ 3.11 |
| 直接依赖 | `jsonschema[format]>=4.23,<5` · `PyYAML>=6.0.2,<7`（仅 2 个） |
| 浏览器 | Chromium / Chrome / Edge（渲染步骤需要，缺失则相关用例 skip） |
| Node.js | 渲染步骤需要（MapLibre GL 3.6.0 已内置在仓库中，离线） |
| 中文字体 | Noto Sans SC / SimHei / SimSun 任一（渲染中文标注需要） |

> Windows 注意：PATH 中的 `python` 可能是微软商店占位符，需用真实解释器绝对路径。

## 运行方式

### VS Code + Codex / Claude Code（最小接入）

从 VS Code 打开**仓库根目录**，安装 Python 扩展并选择 Python 3.11+ 解释器，按需选择 Codex 或 Claude Code 扩展。确认该解释器已具备项目依赖后，执行 **Terminal → Run Task → `Carto: Check schemas`**；也可先运行 `Carto: CLI help`。

仓库共享任务不写死 Python 路径，不自动选择业务场景，也不自动审批。Codex 使用根目录 `AGENTS.md`；现有 `CLAUDE.md` 引用同一指令入口，两者均读取 `skills/carto-agent/SKILL.md` 并调用相同 CLI。此最小入口不要求先运行下方 Hermes bootstrap，也未注册宿主原生技能命令。

详细步骤、依赖安装、首条对话提示和验收边界见 [IDE 最小接入](doc/ide-minimal-integration.md)。

### CLI

```powershell
# 帮助
python skills/carto-agent/scripts/carto.py --help

# Schema 自检
python skills/carto-agent/scripts/carto.py schema check

# 渲染能力探测
python skills/carto-agent/scripts/carto.py environment probe-renderer
```

### 项目空间

项目路径由用户明确指定，脚手架不生成输入数据、不选择场景、不创建审批回执。可按需显式执行：

```powershell
powershell -ExecutionPolicy Bypass -File tools/host/New-CartoProjectSpace.ps1 -ProjectName <项目名>
```

当前没有可运行的默认业务请求。接入真实数据前，按 `skills/carto-agent/scripts/carto_core/scenarios/README.md` 实现场景；不要仅为了使请求通过而修改注册策略或审批设置。

### 一键装载与配置（宿主工具集）

```powershell
# 环境配置 + 装载 + 就绪门一条龙
powershell -ExecutionPolicy Bypass -File tools/host/Bootstrap-CartoHost.ps1

# 跑 26 条 CLI 契约用例
powershell -ExecutionPolicy Bypass -File tools/host/Invoke-CartoHostCases.ps1
```

## 开发测试

保留通用 Schema、安全、状态恢复、渲染器、宿主预检和布局契约测试；不附带业务示例端到端测试。`scripts/tests/fixtures/` 仅是隔离的协议/组件断言输入，不是运行时业务场景或用户数据。

只有在用户允许测试时才执行开发测试。

## 宿主 Agent 集成

Carto Agent 作为 Skill 装载到宿主 Agent（Hermes Agent / Claude Code / Qoder 等），宿主通过 shell 调用唯一 `carto` CLI：

```powershell
# 装载到 Hermes 全局（任意会话可见）
powershell -ExecutionPolicy Bypass -File tools/host/Install-CartoSkill.ps1 -HermesGlobal -Category creative

# 或注册为仓库本地技能（仅本仓库会话）
powershell -ExecutionPolicy Bypass -File tools/host/Install-CartoSkill.ps1 -HermesProjectLocal
```

装载后重启 Hermes 会话即可在 `/skills` 目录看到 `carto-agent`。Agent 的入口纪律：先读 `SKILL.md` → 读 `workflows/routing.md` 选定唯一路由 → 读工作流文件 → 用 shell 调 CLI。

## 实施阶段

| 阶段 | 名称 | 状态 |
|---|---|---|
| U-P0 | 规范收敛与安全底座 | ✅ 已完成 |
| U-P1 | 内核骨架与协议层 | ✅ 已完成 |
| U-P2.0~2.7 | 首个模板与地图生成最小内核 | ✅ 已完成 |
| U-P3.0~3.3 | 首个纵向工程闭环（正式渲染 + 成品检查 + 原子交付） | ✅ 已完成 |
| U-P4 | 三场景业务与生产闭环 | ⬜ 待启动 |
| U-P5 | 复杂数据、连接器与共享部署 | ⬜ 条件触发 |
| U-P6 | 新媒介与新路由 | ⬜ 待启动 |

当前能力边界：**通用框架保留、业务场景注册为空**。`scope-baseline.yaml` 版本 0.4.0，`production_tasks` 为空。上表记录历史阶段进度，不表示当前有默认场景可运行。

## 明确未实现

- 真实 CRS 变换与生产数据制图
- 三场景（政务专题、应急测绘、领导调研）生产业务验收
- 企业连接器、共享部署、外部对象存储或公网发布
- 生产 SLA、备份、运维指标与多主机事务
- `map-brand`、`map-style`、`map-layout` 的业务创建路由

## 开始接入真实场景

1. 读取 `AGENTS.md` 与 Skill，确认真实解释器、依赖及允许根。
2. 明确用户数据的格式、CRS、许可、敏感性、字段语义和输出要求，不生成替代业务数据。
3. 实现场景组件及严格协议，再注册能力，补充自动测试并用获准的真实场景验收。
4. 沿现有 CLI 工作流执行；审批、模板发布、冻结、检查和交付规则不变。

## 相关文档

- [实施计划](doc/implement-plan.md) — 分阶段实施路线（U-P0~U-P6）
- [U-P3 说明文档](doc/impl-log/U-P3说明文档.md) — 首个纵向闭环总结
- [AGENTS.md](AGENTS.md) — 通用智能体入口约束
- [SKILL.md](skills/carto-agent/SKILL.md) — Skill 入口文档

## 许可

内部项目，暂未声明开源许可。
