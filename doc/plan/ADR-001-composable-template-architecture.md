# ADR-001: 可组合模板架构 — 协议与职责决策记录

| 项目 | 内容 |
|---|---|
| ADR 编号 | ADR-001 |
| 日期 | 2026-11-24 |
| 状态 | 已采纳（P1 冻结） |
| 关联计划 | [composable-template-architecture-implementation-plan.md](composable-template-architecture-implementation-plan.md) |
| 前置 | P0 入口回归修复（已完成） |

## 决策 1：共享编译端口的提取边界

### 背景

通用专题制图（`general_thematic`）已具备组件化基础，但共享编译能力与场景特定代码混杂。P2 需要从通用专题中提取共享编译端口，供 P4 的组合闭环使用。

### 决策

**共享编译层提取以下能力，不提取场景特定逻辑：**

| 提取到共享层 (`compiler/`, `contracts/`) | 保留在场景内 (`scenarios/`) |
|---|---|
| 组件装载与有效合同解析 (`load_contracts` 核心) | 业务意图与数据角色合法性 |
| 类型化数据/表达/内容/页面绑定协议 | 业务必要内容、指标含义及表达语义条件 |
| 已声明外观参数解析和来源记录 | 来源数据准入与场景特定检查 |
| Layout 实例化、物理测量与容量检查 | 场景默认方案的声明 |
| 页面请求、RenderScene 和执行快照的共同装配 | 数据准备、几何处理的具体实现 |
| 候选验证、环境绑定和冻结服务调用 | 受信表达算法（Matplotlib 绘制等） |

### 强制约束

- 共享编译器 **不得** `import scenarios.general_thematic` 或 `scenarios.leadership_visit`
- 共享编译器 **不得** 固定依赖 general 场景名
- 边界棘轮 (`test_encapsulation`, `test_scenario_boundary`) 只紧不松

### 依赖方向

```
workflow → 注册表 → 场景端口（业务语义）
workflow → 组件解析端口 → 仓库/草稿解析器
workflow → 共享组合/页面编译端口
workflow → 已注册后端

共享内核 -X→ import 具体场景模块
```

---

## 决策 2：项目级组件选择协议

### 背景

当前生成请求通过 `design_variants` 提供同一场景模板下的样式/尺寸变体，Style/Layout 尚不能作为独立引用被选择和组合。

### 决策

**演进现有 `generate-request`、`MapPlan`、`resolved-*`，增加闭合的"组件选择"结构：**

```yaml
# 目标结构（P4 正式定型字段名与版本号）
component_selection:
  scenario:
    namespace: <string>
    kind: map-scenario
    id: <string>
    version: <string>
    digest: <string>
  style:              # 可选；省略则使用 Scenario 基线
    namespace: <string>
    kind: map-style
    id: <string>
    version: <string>
    digest: <string>
  layout:             # 可选；省略则使用 Scenario 基线
    namespace: <string>
    kind: map-layout
    id: <string>
    version: <string>
    digest: <string>
  parameters:         # 各组件的公开参数显式取值
    style: {}
    layout: {}
  bindings:           # 数据角色 → 表达角色 → Layout 插槽
    - data_role: <string>
      expression_role: <string>
      layout_slot: <string>
```

### 所有权规则

1. 每个段只有一个有效来源；基线、替换、实例参数不能重复拥有同一决定
2. 沿用既有 `style` / `layout` 段命名和语义；不增加别名
3. 引用必须明确 namespace、kind、id、version、digest 及受信库作用域
4. `embedded` 与段引用的所有权约束继续有效
5. 参数必须由组件声明（类型、单位、范围、作用域）；未知参数拒绝
6. 硬约束共同满足；默认值可显式实例化，不能被无限制补丁覆盖
7. 依赖闭包、资源、有效合同和参数进入执行摘要
8. 默认方案是显式可选预设，不是通用内核硬编码

### 三类绑定

| 绑定 | 例子 | 权威 |
|---|---|---|
| 数据语义绑定 | 哪一列代表类别、哪个对象代表停靠点 | 场景与本次数据证据 |
| 表达/视觉角色绑定 | 类别采用何种符号、调研点采用编号点与卡片 | 本次表达选择及 Style 适用合同 |
| 页面内容绑定 | 地图、图例、卡片列表放到哪个容器 | 本次内容计划与 Layout |

Layout 不读业务字段；Style 不保存具体地名；程序不能把字段名近似、角色缺失或空集合视为匹配成功。

---

## 决策 3：P3a 能力上下文与适用性校验（首期窄增量）

### 背景

当前能力通过模板 `(kind, id, version)` 查档案（`scenario_registry.py::for_template`），业务能力与模板身份绑定。首期（P3a）保留已登记 Scenario 身份集合，但分离能力上下文获取与适用性校验。

### 决策

**P3a 分两步但不解除身份绑定：**

1. **受信能力上下文**：保存业务场景、任务、显式几何、profile/策略引用及允许后端
2. **组合适用性校验**：核验所选 Scenario 与上下文一致 → 核验 Style/Layout 的替换权限、表达角色、输出与后端条件

**P3a 不做：**
- 不允许任意 Scenario ID（已登记身份集合不变）
- 不修改来源敏感性或生产准入
- 不将完全身份解耦伪装为窄增量

**P3b（P4 之后独立评审）：**
- 将业务实现分派改为明确的业务能力解析
- 模板身份保留完整性/发布/追溯职责
- 覆盖 `for_template`、`require_contract`、作者固定身份、冻结重验和 CLI 等所有相关入口

---

## 决策 4：联合检查条件

### 语义兼容

- Style 支持当前表达需要的视觉角色
- 不改变数据含义（分类颜色不隐式覆盖已批准分类）

### 接口兼容

- Scenario 需要的内容在 Layout 中有对应容器（插槽）
- 表达需要的符号在 Style 中有对应配置（角色）
- 缺失必需内容、悬挂引用或重复决定均拒绝

### 物理兼容

- 字号、卡片数量、地图框大小、图例容量等在实际内容下成立
- 容量冲突必须报告来源与责任组件，不偷偷缩字、删内容或改布局

### 执行兼容

- 后端能够实现所需符号、字体、裁剪、叠绘和输出
- 固定布局不因改画布自动缩放全部内容

---

## 决策 5：协议版本与摘要覆盖矩阵

> **版本治理落实（2026-11-25）**：本矩阵的"P4 版本化/扩展"指**显式版本决定 + 生产者—消费者清单 + 摘要影响 + 旧运行规则**，非机械升号。已实现部分的具体决定见 [protocol-evolution-segment-refs.md](protocol-evolution-segment-refs.md)；下表区分已落实与待办，避免文档超出实现。

### 受影响协议对象

| 现有对象 | 需表达或核验的变化 | 版本演进 | 落实状态 |
|---|---|---|---|
| `generate-request` / 场景请求 Schema | 精确组件选择（segment_refs） | v1 加性可选字段 | **已落实**（治理记录 §1–3） |
| `design-revision-proposal` | 组件修订键 segment_refs + 失效依赖 | v1 加性可选键 | **已落实**（治理记录 §2） |
| `resolved-map`（execution） | template_refs 段引用 + ownership 段条目 + 选择一致性门 | v1 内加性（有选择时形状扩展） | **已落实**（_require_selection_binding） |
| `MapBrief` | 请求摘要与组件依赖摘要绑定 | 待版本决定 | **未做**：组合身份暂经 execution+候选/锁摘要链绑定，Brief 未新增独立组合字段 |
| `MapPlan` | 每个候选的组件、参数、视图和绑定 | 待版本决定 | **未做**：plan.template_refs 仍仅 scenario；段绑定在 execution |
| `scenario` / `style` / `layout` Schema | 公开接口、可替换范围、所需角色/插槽 | P2 不变 | 不变（replaceable_segments 既有） |
| `dependency-lock` | 独立组件身份、跨库作用域 | 待扩展 | **未做**：请求级段引用经 execution 绑定，未进 dependency-lock |
| `resolved-appearance` / `resolved-layout` | 唯一有效值及来源 | 待版本决定 | **未做**：来源追踪经 segment_selection.superseded，未升 resolved-* |
| `RenderScene` / `MapSpecLock` | 组合选择、依赖摘要、后端环境绑定 | 经既有摘要链 | 部分：锁经 candidate/execution digest 绑定段引用；未新增独立组合字段 |

### 摘要覆盖

每个新增字段必须回答：**谁提供、谁消费、谁验证、谁拥有、是否影响摘要、失败时如何处理**。

---

## 决策 6：G1 前后数据范围与审批失效规则

### G1 前

- 检索可使用已允许的模板元数据和用户声明
- 读取、统计真实业务数据仍需对应授权
- 不能为了算卡片数或字段统计而私自预读未获准数据

### G1 后

- 初始组件选择、参数、资源及依赖摘要纳入请求和 Brief
- 需求只是建议时不得伪装为用户已确认
- 发现实际容量不满足：提出修订 → `revision-brief → 新G1 → revise`

### 失效矩阵

| 变化 | 默认失效范围 | 数据证据复用条件 |
|---|---|---|
| 换 Style 或公开视觉参数 | 有效外观、相关表达图形、布局测量、候选、预览、G2 | 数据语义/处理输入未变，运行时摘要复验通过 |
| 换 Layout / 内容插槽 / 页面参数 | 计划绑定、布局、候选、预览、G2 | 不隐式改变筛选、范围或数据准备 |
| 换表达方法或字段 | 表达计划、可能的数据处理、候选及后续全部 | 按依赖逐项证明 |
| 改数据文件、行程、路线 | 数据准备与受影响后续链 | 使用既有获准数据修订或新运行机制 |
| 改策略语义、表达定义、模板包或字体资源 | 所有受摘要影响的有效合同和冻结执行 | 漂移拒绝；重新准备/授权/编译/冻结 |

---

## 决策 7：单文件单写入人规则（合并防回退）

### 决策

按实施计划的 §18.3 文件归属矩阵执行：

| 文件 | P4 工作面 |
|---|---|
| `workflow/map_generation.py` | 共享生成内核集成人（P0 已完成修复窗口） |
| `scenario_registry.py` | 内核及策略 steward（P3a） |
| `compiler/map_candidate.py` | 共享编译器集成人（P2） |
| `compiler/appearance.py`, `layout.py`, `page_bindings.py` | 共享协议/编译集成人（P2） |
| `scenarios/general_thematic/` | 通用专题适配工作面（P2/P4） |
| `scenarios/leadership_visit/` | 领导调研/渲染工作面（P6） |

### 合并门

1. P0 修复合入后，相关重构分支同步
2. 两条线同改一文件时指定一名集成人
3. 最终合并结果运行 A29 和受影响回归
4. 验收记录同时列出原分支证据与合并树证据

---

## 决策 8：审批、摘要与冻结规则

### 权限与时序

1. G1 前不私自预读未获准数据
2. 初始组件选择、参数、资源及依赖摘要纳入请求和 Brief
3. G1 后发现实际容量不满足 → 修订 → 新 G1 → revise（不直接改冻结请求）
4. 组件或参数变化产生新候选与预览，新 G2 只批准对应精确对象
5. TP 只对应模板发布；不等于地图 G1/G2/G3
6. 正式渲染只消费冻结对象，不重新检索或按候选得分改选

### 冻结对象必须可回答

- 使用了哪个业务能力和哪些精确组件
- 组件来自哪个作用域和仓库/项目草稿
- 每个有效值来自基线、替换还是实例参数
- 使用了什么字体、资源、表达定义、布局实例、后端与环境
- 哪个数据证据、候选和预览被批准
- 任何上述对象漂移时，由哪个门拒绝继续执行

---

## 验收矩阵（P4 窄范围）

| ID | 场景 | 阶段 |
|---|---|---|
| A01 | 单候选使用 Style-only 段引用 | P0 ✅ |
| A02 | Layout-only、双段引用，栅格与矢量分别执行 | P0 |
| A04 | 纯重构前后等价 | P2 |
| A06 | 模板声明未注册实现或越过数据安全限制 | P3a/P4 |
| A07 | 2 Style × 2 Layout 合法子集 | P4 |
| A08 | embedded/ref 冲突、未知参数、重复所有权 | P4 |
| A09 | 字号下限与容器容量冲突 | P4 |
| A10 | 修改模板支持的颜色/字号/线宽 | P4 |
| A11 | 修改纸张、网格或合法内容绑定 | P4 |
| A12 | 相同底图在不同 DPI 输出 | P4 |
| A20 | G1 后未经修订直接改选择 | P4 |
| A21 | 锁后模板、字体、数据、策略变化 | P4 |
| A22 | 跨租户/跨项目引用、路径越界、nonce 重放 | P4 |
| A23 | 中断、retry、重复请求 | P4 |
| A28 | 合法形式但可读性差的样张 | P4 |
| A30 | P3a 使用未登记 Scenario 身份 | P3a/P4 |
| A31 | 代码/协议/策略/披露字段分别变化 | P3a/P3b/P4 |