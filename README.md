# Carto Agent

> 地图制图智能体——用协议驱动、安全可控的方式，从意图到成图全链路打通。

Carto Agent 是一个**协议先行**的地图制图智能体。它不是"一个会画图的 LLM 插件"，而是一套有 Schema 把关、有审批门禁、有崩溃恢复、有审计链的确定性工程管线。模型负责提建议，程序负责执行——每一份输入、产物、审批都要过 Schema 校验，不合规当场拒，绝不"将就着通过"。

## 这是什么

用一句话说：**给 Agent 一份制图意图 + 一份合成 GeoJSON 数据，它走完"规划 → 编译 → 预览 → 冻结 → 正式渲染 → 成品检查 → 原子交付"全链路，产出一套带审计回执的 A3 横版地图成果包。**

目前已用"城市洪涝风险研判图"（合成数据）打通了完整闭环——从模板创建到最终交付，每一步都有不可变回执、可恢复、可审计。

## 核心设计思想

| 原则 | 通俗解释 |
|---|---|
| **协议先行，代码后行** | 先用 JSON Schema 把每种文档的格式定死，再写代码。所有人（agent、CLI、测试、人）对"什么算合格"没有歧义 |
| **模型建议，程序执行** | 模型只能提交"类型化候选"，数值计算和门禁由确定性程序控制。模型不能直接执行 SQL、Shell 或动态代码 |
| **纵向打通优先** | 先用一种场景（洪涝）走通从创建到交付的完整链路，再扩展场景宽度 |
| **演示证据与生产证据分离** | 合成数据负责可重复边界测试，不据此宣称生产适用性已通过 |
| **共享内核，独立路由** | 两条路由（创建模板 / 生成地图）共享五模块内核，各有独立的作业、审批和产物生命周期 |
| **默认拒绝** | 未知字段拒、未注册能力拒、越权调用拒、路径越根拒——宁可阻断，不可放行 |

## 项目结构

```
carto-master-main/
├── skills/carto-agent/              ← 唯一运行实现根
│   ├── SKILL.md                      智能体入口文档（Agent 先读这个）
│   ├── workflows/                    路由 + 工作流文档（routing / create-template / generate-map）
│   ├── schemas/                      47 份 JSON Schema（Draft 2020-12，机器协议）
│   ├── policies/                     9 份策略文件（工具绑定 / 安全 / 检查器 / 范围基线）
│   ├── scripts/
│   │   ├── carto.py                   CLI 入口（安装后命令名 carto）
│   │   ├── carto_core/                核心代码（55 个 Python 模块，~9200 行）
│   │   │   ├── canonical.py           摘要 / 规范化
│   │   │   ├── errors.py              错误类型与码
│   │   │   ├── schema_registry.py     Schema 加载与校验
│   │   │   ├── workflow/              编排 / 状态机 / 审批 / 渲染 / 检查 / 交付
│   │   │   ├── compiler/              依赖解析 / 候选 / 锁
│   │   │   ├── validation/            检查器模型与注册
│   │   │   ├── adapters/              受控浏览器 / 工具网关 / MCP
│   │   │   ├── repository/            不可变存储 / 模板仓库 / 交付仓库
│   │   │   └── security/              路径安全 / 审批验签 / 授权 / 脱敏
│   │   └── tests/                     11 个测试文件，137 个用例
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

从已发布模板 + 合成数据生成地图成果。G1（制图合同）、G2（实例冻结）、G3（成果交付）三道审批门，每道都绑定身份、动作、对象摘要、作用域和一次性 nonce。最终通过 `os.replace` 原子提交产出一个含 PDF/PNG + README + 清单 + 校验和的成果包。

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

`schemas/` 下 47 份 JSON Schema 是这套系统的**机器可读法律**：

- 每一份文档（请求、回执、模板包、审批单、渲染产物、交付包……）都有对应 Schema 规定字段、类型、枚举值
- `additionalProperties: false`——未知字段默认拒绝，不能偷偷加东西
- CLI 每接收输入/产出回执前都拿 Schema 校验，不过就报 `SCHEMA_VALIDATION_FAILED`、退出码 2
- 每份 Schema 配合法、非法、语义非法三种 Fixture，保证校验逻辑没退化

`policies/` 下 9 份策略文件是**声明式规则**：工具绑定（哪些能力允许调用）、安全策略、检查器注册表、范围基线等——被代码读取执行，不是建议。

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
| Python | ≥ 3.11（实测 3.14.7） |
| 直接依赖 | `jsonschema[format]>=4.23,<5` · `PyYAML>=6.0.2,<7`（仅 2 个） |
| 浏览器 | Chromium / Chrome / Edge（渲染步骤需要，缺失则相关用例 skip） |
| Node.js | 渲染步骤需要（MapLibre GL 3.6.0 已内置在仓库中，离线） |
| 中文字体 | Noto Sans SC / SimHei / SimSun 任一（渲染中文标注需要） |

> Windows 注意：PATH 中的 `python` 可能是微软商店占位符，需用真实解释器绝对路径。

## 运行方式

### CLI

```powershell
# 帮助
python skills/carto-agent/scripts/carto.py --help

# Schema 自检（47 个）
python skills/carto-agent/scripts/carto.py schema check

# 渲染能力探测
python skills/carto-agent/scripts/carto.py environment probe-renderer
```

### 项目空间（真实 CLI 运行）

carto CLI 不像单元测试用临时目录自动清理——`intake` 起就要求显式指定 `--project-root`、`--workdir`、`--repository-root`，所有产物落在你指定的位置：

```powershell
# 生成项目空间脚手架
powershell -ExecutionPolicy Bypass -File tools/host/New-CartoProjectSpace.ps1

# 生成合成洪涝样例数据
& "D:\ProgramData\miniconda3\python.exe" tools/host/generate_flood_sample.py "projects/carto-flood-a3/project"

# 跑模板创建前两步（不需审批）
python skills/carto-agent/scripts/carto.py create-template analyze <request> --project-root <project> --workdir <runs> --allowed-root <root>
python skills/carto-agent/scripts/carto.py create-template brief <request> --project-root <project> --workdir <runs> --allowed-root <root>
```

到 `author` 需要审批回执——这是设计如此，不是 bug。

### 一键装载与配置（宿主工具集）

```powershell
# 环境配置 + 装载 + 就绪门一条龙
powershell -ExecutionPolicy Bypass -File tools/host/Bootstrap-CartoHost.ps1

# 跑 26 条 CLI 契约用例
powershell -ExecutionPolicy Bypass -File tools/host/Invoke-CartoHostCases.ps1
```

## 测试

```powershell
# 全量回归（137 用例，约 264 秒）
python -m unittest discover -s skills/carto-agent/scripts/tests -v

# 单个测试文件
python -m unittest skills/carto-agent/scripts/tests/test_up33_delivery.py -v

# 宿主 CLI 契约用例（26 条，PowerShell）
powershell -ExecutionPolicy Bypass -File tools/host/Invoke-CartoHostCases.ps1
```

测试覆盖：Schema 结构校验、安全底座、五模块内核、模板创建发布闭环、地图生成预览冻结闭环、正式渲染、成品检查、原子交付、集成恢复、宿主 CLI 契约。唯一 skip 为 Windows 符号链接权限用例（需开发者模式）。

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

当前能力边界：**本地允许根内的合成数据工程演示闭环**。`scope-baseline.yaml` 版本 0.3.3，`production_tasks` 为空。

## 明确未实现

- 真实 CRS 变换与生产数据制图
- 三场景（政务专题、应急测绘、领导调研）生产业务验收
- 企业连接器、共享部署、外部对象存储或公网发布
- 生产 SLA、备份、运维指标与多主机事务
- `map-brand`、`map-style`、`map-layout` 的业务创建路由

> U-P3 的完成只表示合成数据工程演示闭环成立，**不构成生产能力声明**。所有输出物全程携带"合成数据演示，非真实风险研判"标识。

## 快速开始

```powershell
# 1. 环境配置 + 装载 + 就绪门（一条命令搞定）
powershell -ExecutionPolicy Bypass -File tools/host/Bootstrap-CartoHost.ps1

# 2. 跑测试用例
powershell -ExecutionPolicy Bypass -File tools/host/Invoke-CartoHostCases.ps1

# 3. 生成项目空间 + 样例数据，跑 analyze
powershell -ExecutionPolicy Bypass -File tools/host/New-CartoProjectSpace.ps1
& "D:\ProgramData\miniconda3\python.exe" tools/host/generate_flood_sample.py "projects/carto-flood-a3/project"
python skills/carto-agent/scripts/carto.py create-template analyze "projects/carto-flood-a3/project/request-template.yaml" --project-root "projects/carto-flood-a3/project" --workdir "projects/carto-flood-a3/runs/template-one" --allowed-root "projects"
```

## 相关文档

- [实施计划](doc/implement-plan.md) — 分阶段实施路线（U-P0~U-P6）
- [U-P3 说明文档](doc/impl-log/U-P3说明文档.md) — 首个纵向闭环总结
- [宿主 Agent 形态一测试清单](doc/dev-log/0920宿主Agent形态一测试清单.md) — CLI 契约 26 条用例 + 5 条漂移
- [AGENTS.md](AGENTS.md) — 通用智能体入口约束
- [SKILL.md](skills/carto-agent/SKILL.md) — Skill 入口文档

## 许可

内部项目，暂未声明开源许可。
