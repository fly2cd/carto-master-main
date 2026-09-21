# U-P3 分阶段实施计划

## 文档信息

| 项目 | 内容 |
|---|---|
| 阶段 | U-P3：首个纵向工程闭环 |
| 版本 | 1.2 |
| 日期 | 2026-09-21 |
| 状态 | U-P3.0～U-P3.3 已完成；当前形成合成数据工程演示闭环 |
| 上位计划 | [地图制图智能体分阶段实施计划](implement-plan.md) |
| 技术依据 | [模板创建 TRD](carto-create-template-TRD.md)、[地图生成 TRD](carto-generate-map-TRD.md) |
| 前置阶段 | [U-P2 分阶段实施细化计划](u-p2-implementation-plan.md)、[U-P3.0 前置缺口收敛实施记录](impl-log/U-P3.0-prerequisite-closure.md) |
| 唯一实现根 | `skills/carto-agent/` |

本文将 U-P3 拆分为三个可串行实施、独立提交、独立验收的子阶段。本文只规定实施顺序、阶段边界、协议演进和退出门槛，不替代 Schema、Policy、注册表或两份 TRD，也不得在运行时被当作机器协议读取。

---

## 一、拆分原则与总体路线

U-P2 已完成首个洪涝 MapScenario 的创建、验证、发布，以及地图生成侧的 `intake → brief → compile → preview → freeze`。U-P3 的剩余工作同时涉及锁后执行、正式成果检查、G3 审批、带副作用的交付事务、恢复与幂等。如果一次性实现，将难以区分渲染失败、质量失败、审批失败和提交结果未知，也会使尚未验证的交付能力被提前暴露。

因此 U-P3 严格拆为：

```text
U-P3.1 锁驱动正式渲染与 Attempt 生命周期
  → U-P3.2 成品检查、交付对象冻结与 G3 等待
  → U-P3.3 G3、原子交付事务与全链路收口
```

### 1.1 实施纪律

1. 三个子阶段必须串行推进，前一阶段退出门槛全部通过后才能进入下一阶段。
2. 每个子阶段独立提交；不得在当前阶段顺带加入后续阶段的伪实现、自动批准、空检查或假交付。
3. 可提前定义下一阶段需要的窄协议，但不得通过固定成功值、测试专用分支或降级路径绕过门禁。
4. 新增或实质修改协议时，必须同时提供合法样例、非法样例和自动测试；JSON Schema 使用 Draft 2020-12，未知字段默认拒绝。
5. 所有外部路径必须经过允许根校验；交付目的地即使是本地路径也不能绕过 `PathGuard`。
6. 所有审批必须验证签发身份、动作、对象类型、对象摘要、项目/租户/作用域、环境、时效和 nonce；模型不能签发审批。
7. 每个阶段结束都运行全量回归，不能只运行新增测试。
8. 正式渲染、检查和交付都必须保留不可变证据；普通日志不得记录密钥、完整业务数据行、完整行程或应急敏感坐标。
9. U-P3 只形成“合成数据工程演示闭环”，不得据此声明生产业务能力、三场景覆盖或公网发布能力。
10. 不在 `skills/carto-master/`、仓库根级 `src/`、`schemas/` 或 `tests/` 建立并行实现，不修改 `skills/ppt-master/`。

---

## 二、当前基线、已关闭前置缺口与剩余工作

### 2.1 已有能力

- 创建模板路由已具备 `analyze → brief → author → validate → publish`。
- 地图生成路由已具备 `intake → brief → compile → preview → freeze`。
- 已有不可变 `MapSpecLock`、候选执行摘要、预览证据和渲染回执基础协议。
- 已有受控 MapLibre Web + SVG overlay 渲染适配器，可生成 SVG、PNG、PDF 工程预览。
- 已有运行单写锁、revision/CAS、状态转换日志、步骤回执、有限重试和审批消费恢复机制。
- `ApprovalGateCoordinator.GATES` 已声明 G3：`approve-delivery / delivery-manifest`。

### 2.2 U-P3.0 前置基线已关闭（2026-09-21）

1. 洪涝 MapScenario 唯一身份已统一为 `urban-flood-risk/1.0.0`；`flood-risk-overview` 仅保留为作者 profile，旧 `flood-scenario` 由 Schema 拒绝，不建立别名兼容。
2. `freeze` 创建不可变 `MapSpecLock` 后，新运行进入 `pending / render`；不再把冻结误标为全链路 `succeeded`。历史 `succeeded / freeze` 运行不做就地迁移或续跑。
3. `DeliveryManifest` 已收敛为不含 `delivered_at` 的 G3 事前批准对象；`DeliveryReceipt` 已定义为未来事务提交成功后的事后回执。两类对象目前只有窄协议和测试，尚无业务生成、消费或写入实现。
4. `scope-baseline.yaml` 已更新为 `u-p3-prerequisites-aligned`，正式交付仅声明 `planned-u-p3-local-synthetic-only`，没有提前开放生产能力。
5. 上述收敛已提供语义拒绝 Fixture、状态/恢复测试，并通过 110 项全量回归（`OK (skipped=1)`）。

### 2.3 U-P3 实施前基线中的阶段缺口

> 本节保留 2026-09-21 制定分阶段计划时的基线，用于说明拆分依据；其中 render、check 与 deliver 缺口已分别由 U-P3.1、U-P3.2、U-P3.3 关闭。

1. CLI 当前只开放 `intake`、`brief`、`compile`、`preview`、`freeze`，没有 `render`、`check`、`deliver`。
2. 现有受控渲染器只用于模板验证和候选预览，尚未建立“只消费锁”的正式渲染边界和独立 attempt 生命周期。
3. G3 虽已在审批协调器中声明，但尚未接入地图生成业务流程。
4. `checker-registry.yaml` 只有少量通用检查器，尚无正式 PDF/PNG 成品检查集合。
5. DeliveryManifest/DeliveryReceipt 虽已完成职责拆分，但 Manifest 的业务生成、最终检查绑定、G3 等待、交付事务和 Receipt 写入尚未实现。
6. 历史 U-P2 运行在 `freeze` 后结束属于当时已验收行为。完整 U-P3 验收必须创建新运行，历史运行只保留为证据。
---

## 三、U-P3 固定范围与非目标

### 3.1 固定纵向样例

| 项目 | U-P3 固定值 |
|---|---|
| 场景 | 城市洪涝风险研判图 |
| 模板唯一身份 | `urban-flood-risk/1.0.0`，已在 U-P3.0 完成收敛 |
| 数据性质 | 合成数据，模板 Fixture 与生成项目数据相互独立 |
| 风险面表达 | `choropleth/sequential` |
| 避难点表达 | `proportional-symbol/count` |
| 符号资源 | `point-symbol/shelter` |
| 页面 | A3 横向，420 × 297 mm |
| 正式成果 | 必需 PDF、PNG |
| 执行环境 | 受控单机、拒绝外部网络、固定字体与渲染环境 |
| 交付目的地 | 允许根内的本地演示目录 |
| 强制标识 | “合成数据演示，非真实风险研判” |

“正式渲染/正式成果”在本文中表示相对于候选预览的锁后交付候选，不表示生产级地图资质。所有成果仍必须声明工程演示性质。

### 3.2 明确非目标

- 不接入真实生产数据，不处理真实应急敏感坐标。
- 不实现真实 CRS 转换；仍受当前已声明的输入和显示 CRS 边界约束。
- 不扩展政务、应急、调研三场景生产验收，不声称 U-P4 已完成。
- 不实现 GeoPackage、QGIS 工程、数据库、在线 API 或公网发布。
- 不实现全矢量 PDF，不改变当前地图主体栅格、SVG overlay 矢量的组成声明。
- 不开放 `map-brand`、`map-style`、`map-layout` 的业务创建路由。
- 不自动调用模板创建/发布来修复地图运行；发现模板缺陷时应明确失败。
- 不允许在 G3 前产生外部提交副作用，也不允许用复制到任意路径冒充事务交付。

---

## 四、三阶段总览

| 子阶段 | 核心目标 | 入口状态 → 出口状态 | 主要新增命令 | 可独立验收的成果 |
|---|---|---|---|---|
| U-P3.1 | 从不可变锁生成正式 PDF/PNG，并建立 attempt、重试和漂移检测 | `pending / render` → `pending / check` | `carto generate-map render` | 正式渲染目录、RenderAttempt、正式 RenderReceipt/证据 |
| U-P3.2 | 检查正式成果，冻结 G3 批准对象 | `pending / check` → `waiting_approval / deliver` | `carto generate-map check` | Final ValidationReport、不可变 DeliveryManifest |
| U-P3.3 | 验证 G3，执行可查询、幂等、原子的本地交付 | `waiting_approval / deliver` → `succeeded / deliver` | `carto generate-map deliver`，必要时 `delivery-status` | DeliveryTransaction、DeliveryReceipt、完整成果包和端到端证据 |

状态名称沿用现有 `job-state` 的 `status + step` 组合。若实现中需要增加协议字段或状态约束，必须在 U-P3.1 先完成 Schema 与状态机迁移测试，不能依赖自由字符串的隐含语义。

---

## 五、U-P3.1：锁驱动正式渲染与 Attempt 生命周期

### 5.1 目标

从 U-P3.0 已建立的 `pending / render` 安全入口实现正式渲染。正式渲染只能消费已经通过 G2 的不可变 `MapSpecLock`，不能重新读取可变 MapPlan、重新调用模型、重算分类断点、重做字段绑定或静默替换资源。每次渲染执行建立独立 attempt，使超时、崩溃和重试都有明确证据。

### 5.2 U-P3.0 已确定的前置决策

1. 洪涝模板唯一身份已收敛为 `urban-flood-risk/1.0.0`；旧 `flood-scenario/1.0.0` 已从请求 Schema 与测试引用中移除，不提供别名兼容。
2. U-P3 新运行的状态路径已确定：`freeze` 成功后进入可继续的 `pending / render`，不再直接 `succeeded`。
3. 明确两个不同摘要的命名和作用：
   - `MapSpecLock.execution_digest`：冻结的业务执行输入摘要；
   - renderer execution digest：由 scene、资源、Renderer Profile、环境等形成的渲染执行摘要。

两者必须同时保留并显式关联，不能都以含糊的 `execution_digest` 互相覆盖。

### 5.3 工作项

#### A. 协议与目录

1. 新增 `render-attempt` 协议，至少包含：
   - `attempt_id`、`lock_ref`、`lock_digest`、`target_id`；
   - MapSpecLock 业务执行摘要；
   - Renderer Profile、环境指纹、资源集和 RenderScene 摘要；
   - attempt 序号、状态、开始/结束时间、错误分类和前一 attempt 引用；
   - 输出引用及其摘要；
   - 是否可重试和重试原因。
2. 新增或收紧 `formal-render-evidence` 协议，明确绑定锁摘要、业务执行摘要、renderer execution digest、RenderReceipt、输出摘要集合和 attempt。
3. 正式输出采用不可覆盖目录：

   ```text
   output/<lock-id>/<target-id>/<attempt-id>/
   ```

4. 成功和失败 attempt 均保留不可变记录；新 attempt 不覆盖旧 attempt。
5. 所有引用使用受控相对路径或通过允许根验证后的规范化路径。

#### B. 锁后验证

1. 加载并校验 MapSpecLock Schema、候选摘要、预览证据摘要、锁内执行摘要和审批引用。
2. 重新计算锁本身及所有被锁定本地输入的摘要；任何快照、字体、表达资源、模板依赖或 RenderScene 漂移返回 `LOCK_INPUT_DRIFT`。
3. 字段语义、单位、几何和表达绑定在正式渲染前再次验证；错误返回 `ENCODING_SEMANTICS_INVALID` 并停止，不启动浏览器。
4. 环境、浏览器、字体或 Renderer Profile 与锁定环境不一致时返回明确的环境漂移错误；不得把实质漂移当作普通超时重试。
5. 正式渲染不读取根级“最新” MapPlan，也不自动安装新模板版本。

#### C. 正式渲染编排

1. 新增 `carto generate-map render`。
2. 在 `MapGenerationWorkflow` 中增加锁驱动 render 步骤，复用受控渲染器的可信底座，但使用独立的正式运行配置和输出目录。
3. 只生成锁内声明的必需目标；U-P3 固定要求 PDF、PNG，SVG 可作为内部中间证据但不是交付必需成果。
4. 正式成果必须包含醒目标识“合成数据演示，非真实风险研判”。标识内容及其布局证据必须进入锁或正式渲染证据，不能在渲染后手工追加。
5. RenderReceipt 必须验证 attestation、输出媒体类型、大小、摘要、组成、环境、资源集合、网络策略和时间范围。
6. 渲染成功后推进到 `pending/check`；渲染失败保持可诊断状态，不得标记运行成功。

#### D. 重试与恢复

1. 仅对已分类为暂时性的 worker 超时、受控进程崩溃等错误允许同锁创建新 attempt。
2. 重试必须复用同一锁、RenderScene、Renderer Profile、资源集合和环境要求，不重新调用规划器或模型。
3. 输入漂移、语义错误、未授权能力、资源摘要变化和环境实质变化不可作为同锁普通 retry。
4. 进程在“已写成果、未写步骤回执”窗口中断时，恢复逻辑必须验证 attempt 和成果摘要后再补记，不得盲目重渲染。
5. 并发旧写者、重复命令和相同 attempt 创建竞争必须由现有单写锁与 CAS 拒绝或幂等返回。

### 5.4 主要代码范围

- `skills/carto-agent/schemas/`
- `skills/carto-agent/policies/scope-baseline.yaml`
- `skills/carto-agent/scripts/carto_core/workflow/map_generation.py`
- 新增窄职责的正式渲染工作流组件，如 `workflow/map_render.py`
- `skills/carto-agent/scripts/carto_core/adapters/controlled_renderer.py`
- `skills/carto-agent/scripts/carto_core/repository/` 中的 attempt/证据存储组件
- `skills/carto-agent/scripts/carto_core/cli.py`
- `skills/carto-agent/scripts/tests/` 及对应 Fixture

### 5.5 禁止提前实现

- 不实现 G3 验证。
- 不向交付目的地复制或提交文件。
- 不把渲染成功等同于交付成功。
- 不在本阶段用空检查报告提前生成可批准的 DeliveryManifest。

### 5.6 必测用例

- 同一锁、同一环境生成可验证的 PDF/PNG 和正式渲染证据。
- 锁后修改数据快照、字体、RenderScene 或表达资源返回 `LOCK_INPUT_DRIFT`。
- 字段语义错误返回 `ENCODING_SEMANTICS_INVALID`，浏览器未启动。
- 首次超时保留失败 attempt，第二次在同锁下创建新 attempt，不覆盖第一次记录。
- renderer execution digest 与 MapSpecLock 业务执行摘要均被保留且用途不混淆。
- 缺字体、浏览器版本漂移、网络越权、必需目标缺失和回执 attestation 错误均失败。
- 历史 U-P2 已结束运行不被静默续跑；新 U-P3 运行从冻结后继续。

### 5.7 退出门槛

- [x] `generate-map render` 只消费有效 MapSpecLock。
- [x] 正式 PDF/PNG 位于不可覆盖 attempt 目录并有摘要和回执。
- [x] 锁后输入漂移、环境漂移和语义错误被确定性阻断。
- [x] 暂时性超时可以在同一锁下新建 attempt，且不重新规划。
- [x] `freeze` 对新 U-P3 运行不再提前标记全链路成功（U-P3.0 已完成）。
- [x] 新协议正反 Fixture、单元测试、恢复测试和全量回归通过。

### 5.8 建议提交

`U-P3.1: 实现锁驱动正式渲染与 attempt 生命周期`

---

## 六、U-P3.2：成品检查、交付对象冻结与 G3 等待

### 6.1 目标

对 U-P3.1 的正式 PDF/PNG 执行确定性成品检查。只有必需目标齐全、文件和视觉规则通过、`blocker/error` 为零后，才能冻结 G3 的批准对象，并将运行置于 `waiting_approval / deliver`。本阶段不消费 G3，也不产生交付副作用。

### 6.2 工作项

#### A. 成品检查器集合

在 `checker-registry.yaml` 中注册并版本化 U-P3 实际执行的检查器。最小集合包括：

1. 文件存在、非空、媒体类型和摘要一致。
2. 必需目标 PDF、PNG 齐全，均来自同一锁和被选定的成功 attempt。
3. PDF 页面尺寸、方向和页数符合 A3 横向合同。
4. PNG 像素尺寸、DPI 推导和色彩/栅格声明符合目标配置。
5. 字体解析/嵌入策略符合当前受控环境，不出现缺字或替代字体漂移。
6. 页面安全边距、裁剪、标题、图例、比例尺、指北针和来源署名符合锁定布局。
7. 图例分类与地图表达一致；比例符号语义、无数据表达和必要标签可验证。
8. “合成数据演示，非真实风险研判”在 PDF 和 PNG 中均醒目存在。
9. RenderReceipt attestation、环境指纹、资源摘要、锁摘要及成果摘要链一致。
10. 输出中不包含业务原始数据、内部密钥、未授权路径或敏感调试信息。

视觉类检查必须定义可重复的机器证据；若当前能力需要人工审查，应明确人工审查对象、身份和回执，不能以“已查看”自由文本代替。

#### B. 最终检查报告

1. 扩展或收紧 `validation-report`，使正式成品检查阶段和检查对象可明确表达。
2. 报告必须包含检查器精确版本、subject digest、每项严重度、结构化详情、生成时间及所检查成果摘要。
3. `blocker` 或 `error` 任一失败即不能生成可批准的 DeliveryManifest。
4. `warning` 必须有处置结论：接受、修复后重检或明确阻断；未处置 warning 不能静默通过。
5. 修复需要改变锁定输入时必须回到新候选/新锁；只允许对暂时性渲染故障创建同锁新 attempt。

#### C. 使用已拆分的事前清单与事后回执协议

U-P3.0 已完成窄协议职责拆分：

- **DeliveryManifest**：交付前不可变批准对象，不含事后提交时间；U-P3.2 负责在最终检查通过后生成并冻结该业务对象。
- **DeliveryReceipt**：U-P3.3 提交成功后的事实回执，包含 `delivered_at`、事务标识、最终路径和提交结果；U-P3.2 不写入业务回执。

DeliveryManifest 至少绑定：

- `manifest_id`、项目、运行和 lock 引用；
- lock digest 与 MapSpecLock 业务执行摘要；
- 被选定正式 attempt 及 renderer execution digest；
- 已检查成果的路径、格式、大小和摘要集合；
- 最终检查报告引用及摘要；
- 接收方标识；
- 允许根内的规范化本地目的地；
- 项目/租户/作用域与执行环境；
- 许可、限制和“合成数据演示，非真实风险研判”声明；
- 固定的幂等上下文或幂等键；
- 创建时间和协议版本。

G3 的 `object_digest` 必须是该不可变 DeliveryManifest 的规范摘要，不能只绑定 lock、目录名或文件数量。

#### D. 工作流与 CLI

1. 新增 `carto generate-map check`。
2. check 只接受成功且完整的正式 render attempt。
3. 检查通过后原子写入 ValidationReport 和 DeliveryManifest。
4. 将状态推进到 `waiting_approval / deliver`，并向调用方返回应提交给审批系统的 G3 对象摘要和上下文。
5. 重复 check 在输入完全相同时幂等返回已有结果；成果或报告变化时必须重新检查并形成新对象，不能覆盖原 Manifest。

### 6.3 主要代码范围

- `skills/carto-agent/schemas/validation-report.schema.json`
- `skills/carto-agent/schemas/delivery-manifest.schema.json`（使用 U-P3.0 已收敛协议，必要时仅作兼容性收紧）
- `skills/carto-agent/schemas/delivery-receipt.schema.json`（使用 U-P3.0 已定义的窄协议；业务写入仍在 U-P3.3 实现）
- `skills/carto-agent/policies/checker-registry.yaml`
- 新增成品检查器及注册实现
- 新增 `workflow/map_final_check.py` 或等价窄职责组件
- `workflow/map_generation.py`、`cli.py`
- 对应正反 Fixture、检查器测试、集成和恢复测试

### 6.4 禁止提前实现

- 不消费 G3 nonce。
- 不创建交付目录中的最终提交结果。
- 不生成带 `delivered_at` 的成功回执。
- 不允许“检查失败但用户批准后继续”的绕过分支。

### 6.5 必测用例

- 合格 PDF/PNG 生成 passed 报告和稳定 DeliveryManifest 摘要。
- PDF 成功但 PNG 缺失时不能进入 G3 等待。
- 文件在渲染后被修改时摘要校验失败。
- 页面尺寸、裁剪、字体、图例、署名或演示标识错误时按严重度阻断。
- RenderReceipt、环境或锁绑定不一致时阻断。
- warning 未处置时不能生成可批准对象。
- DeliveryManifest 不含 `delivered_at`，DeliveryReceipt 才拥有事后字段。
- Manifest 的接收方、目的地或成果集合任一变化都会改变 G3 对象摘要。

### 6.6 退出门槛

- [x] `generate-map check` 能对正式 PDF/PNG 执行注册且版本化的成品检查。
- [x] 必需目标、演示标识、锁/环境/回执绑定均被验证。
- [x] `blocker/error` 为零且 warning 已处置后才能冻结 DeliveryManifest。
- [x] G3 事前批准对象与事后 DeliveryReceipt 的 Schema 职责已分离，Manifest 业务生成已实现。
- [x] 状态准确停在 `waiting_approval / deliver`，无交付副作用。
- [x] 新协议正反 Fixture、检查器测试、恢复测试和全量回归通过。

### 6.7 建议提交

`U-P3.2: 实现成品检查与 G3 交付对象冻结`

---

## 七、U-P3.3：G3、原子交付事务与全链路收口

### 7.1 目标

验证精确绑定 DeliveryManifest 的 G3 回执，在允许根内完成可恢复、可查询、幂等且原子可见的本地演示交付。提交成功后写不可变 DeliveryReceipt，并完成 U-P3 洪涝纵向样例从模板创建到成果交付的全链路验收。

### 7.2 工作项

#### A. G3 验证与恢复

1. 新增 `carto generate-map deliver`，要求提供 G3 审批回执。
2. 使用已有 `ApprovalGateCoordinator` 验证：
   - gate 为 G3；
   - action 为 `approve-delivery`；
   - object type 为 `delivery-manifest`；
   - object digest 与当前 Manifest 完全一致；
   - 签发方、审批主体、项目/租户/作用域、环境、policy、有效期和 nonce 有效。
3. 模板简报审批、TP、G1、G2 均不得复用为 G3；G3 也不得复用于另一个 Manifest 或目的地。
4. 在“G3 nonce 已消费但本地事务结果尚未落盘”的窗口，采用与 TP/G2 同等级的 workflow-local intent 和不可变恢复证据；普通 nonce 重放仍必须拒绝。
5. Manifest 或成果在批准后发生任何变化都必须拒绝，不能自动重新摘要后沿用旧 G3。

#### B. 本地原子交付事务

交付只支持允许根内的本地演示目的地，事务顺序固定为：

```text
创建事务意图
  → 写入隔离 staging
  → 校验 staging 文件集合、摘要、限制说明和清单
  → 原子提交到最终 delivery 目录
  → 写不可变 DeliveryReceipt
  → 完成步骤回执与状态
```

具体要求：

1. 新增 `delivery-transaction` 协议，记录事务 ID、Manifest 摘要、幂等键、staging/final 引用、状态、恢复阶段和错误分类。
2. 新增本地不可变 DeliveryRepository；最终目录不能覆盖既有交付。
3. 交付包只包含批准的 PDF、PNG、面向接收方的说明、许可/限制和必要清单；不附带业务原始数据、内部锁、密钥或敏感内部报告。
4. staging 完整校验通过前，最终目的地不可见半成品。
5. 最终提交使用同文件系统内的原子重命名或等价原子操作；若平台无法保证，必须明确失败，不能以逐文件复制宣称原子提交。
6. DeliveryReceipt 至少包含：delivery/transaction ID、Manifest 引用和摘要、幂等键、最终路径、成果摘要集合、提交时间、G3 引用和结果状态。
7. DeliveryReceipt 和事务记录均不可变，可按 delivery ID 和幂等键查询。

#### C. 幂等与结果未知处理

1. 同一幂等键 + 同一 Manifest 摘要：返回既有事务/回执，不产生第二份成果。
2. 同一幂等键 + 不同 Manifest 摘要、接收方或目的地：返回幂等冲突并拒绝。
3. 客户端在提交后超时，不得盲目再次复制；先按幂等键查询事务和回执。
4. 可新增 `carto generate-map delivery-status --idempotency-key ...`；若复用现有状态/回执查询入口能完整满足要求，可不增加第二套查询机制。
5. staging 已完成但尚未提交时可依据事务证据继续；最终目录已存在但回执缺失时，必须核验其完整摘要后补记，不能覆盖或创建重复 delivery。
6. 中断、磁盘满、权限失败、并发旧写者和部分 staging 都应保持可诊断、可清理但不误报成功的状态。

#### D. 全链路收口

1. 使用独立数据集重放：
   - 创建并发布洪涝 MapScenario；
   - 使用另一份合成项目数据执行地图生成；
   - G1 → compile → preview → G2 → freeze；
   - render → check → G3 → deliver。
2. 验证审批彼此独立，摘要绑定精确，历史回执不能跨 gate、跨运行或跨对象复用。
3. 更新 `skills/carto-agent/SKILL.md`、工作流说明和路由文档，只声明实际通过的 U-P3 工程演示能力。
4. 更新 `scope-baseline.yaml`：移除过时的 `not-in-u-p2` 描述，改为准确的 U-P3 本地合成演示边界；`production_tasks` 仍不得因此开放。
5. 形成可审计验收证据，明确 U-P3 不代表 U-P4 三场景生产闭环。

### 7.3 主要代码范围

- `skills/carto-agent/schemas/delivery-transaction.schema.json`
- `skills/carto-agent/schemas/delivery-receipt.schema.json`
- 必要的审批、步骤回执和状态协议收紧
- `skills/carto-agent/scripts/carto_core/repository/` 的 DeliveryRepository
- 新增 `workflow/map_delivery.py` 或等价窄职责组件
- `workflow/map_generation.py`、`workflow/approvals.py`、`cli.py`
- `skills/carto-agent/policies/scope-baseline.yaml`
- `skills/carto-agent/SKILL.md` 与 `skills/carto-agent/workflows/`
- 端到端、故障注入、恢复、幂等和宿主 Agent 测试

### 7.4 必测用例

- 正确 G3 可将批准成果原子提交并写不可变 DeliveryReceipt。
- TP、G1、G2 回执不能代替 G3；另一个 Manifest 的 G3 不能复用。
- G3 批准后篡改成果、目的地或限制说明会被拒绝。
- 同幂等键同对象重复调用返回同一 delivery，不复制第二份成果。
- 同幂等键不同对象返回冲突。
- 提交后客户端超时可按幂等键查询已有 delivery。
- G3 nonce 消费后中断可凭严格恢复证据继续，普通 nonce 重放仍失败。
- staging 中断、磁盘满、最终目录竞争和回执落盘前崩溃均不产生半成品成功状态。
- 最终成果包含醒目演示标识，不包含原始数据、内部锁和敏感报告。
- 全链路使用的模板 Fixture 与生成项目数据相互独立。

### 7.5 退出门槛

- [x] `generate-map deliver` 只接受精确绑定当前 DeliveryManifest 的有效 G3。
- [x] 交付遵循 staging、完整校验、原子提交、不可变回执的固定顺序。
- [x] 幂等重复、幂等冲突和提交结果未知均有确定行为。
- [x] G3 消费窗口具备严格、可测试的恢复证据。
- [x] 洪涝模板创建、发布、独立项目数据生成、冻结、正式渲染、检查、G3、交付全链路通过。
- [x] 文档和 Skill 只声明“合成数据工程演示闭环”，未声明三场景或生产能力。
- [ ] 全量自动测试已通过（137 项，跳过 1 项）；宿主 Agent 与人工验收证据仍待独立确认。

### 7.6 建议提交

`U-P3.3: 实现 G3 原子交付并收口洪涝纵向闭环`

---

## 八、协议与持久化规划

### 8.1 计划中的核心对象

| 对象 | 首次落地阶段 | 作用 | 不得混入的职责 |
|---|---|---|---|
| `MapSpecLock` | 已有，U-P3.1 收紧使用 | 冻结业务执行输入和 G2 证据 | 不记录某次正式渲染的瞬时结果 |
| `RenderAttempt` | U-P3.1 | 记录一次正式 worker 执行及恢复状态 | 不作为 G3 批准对象 |
| `FormalRenderEvidence` | U-P3.1 | 关联 lock、attempt、RenderReceipt 和输出摘要 | 不表示成品质量已通过 |
| `ValidationReport` | 已有，U-P3.2 扩展 | 记录正式成品检查结果 | 不表示已经交付 |
| `DeliveryManifest` | U-P3.0 收敛 Schema，U-P3.2 生成 | G3 事前批准的不可变成果集合 | 不包含 `delivered_at` 或虚构提交成功 |
| `DeliveryTransaction` | U-P3.3 | 记录 staging、commit、恢复和幂等状态 | 不替代最终事实回执 |
| `DeliveryReceipt` | U-P3.0 定义 Schema，U-P3.3 写入 | 记录已提交的事实结果 | 不参与事前 G3 对象摘要 |

### 8.2 建议项目目录

```text
<project-root>/
├─ locks/<lock-id>/
│  └─ map-spec-lock.yaml
├─ output/<lock-id>/<target-id>/<attempt-id>/
│  ├─ render-attempt.yaml
│  ├─ formal-render-evidence.yaml
│  ├─ render-receipt.json
│  ├─ <artifact>.pdf
│  └─ <artifact>.png
├─ reports/<validation-id>/
│  └─ validation-report.json
└─ deliveries/<delivery-id>/
   ├─ delivery-manifest.json
   ├─ transaction.json
   ├─ receipt.json
   └─ package/
      ├─ <artifact>.pdf
      ├─ <artifact>.png
      └─ README/limitations
```

实际命名可在 Schema 落地时收敛，但对象职责、不可变性和层级关系不得退化。运行时不能通过扫描目录数量推测 ID，所有 ID 必须由受信组件生成并通过显式引用关联。

---

## 九、审批与摘要绑定

| 门禁 | 批准对象 | 最小绑定内容 | U-P3 禁止复用 |
|---|---|---|---|
| 模板 T1 | TemplateBrief | 模板创建合同 | G1/G2/G3 |
| 模板 TP | TemplatePublication | 待发布包、依赖、验证和环境证据 | G1/G2/G3 |
| G1 | MapBrief | 意图、任务、数据范围、模板选择、输出合同 | T1/TP/G2/G3 |
| G2 | ResolvedMap/候选冻结对象 | 候选执行摘要、数据包、预览和剩余风险 | T1/TP/G1/G3 |
| G3 | DeliveryManifest | lock、已检查成果、报告、接收方、目的地、限制和幂等上下文 | 所有其他 gate |

G3 只能在成果摘要确定且成品检查通过后签发。若任何批准对象字段变化，必须形成新 Manifest 和新 G3，不得仅更新目录中的可变文件。

---

## 十、失败、重试与恢复矩阵

| 故障 | 是否同锁重试 | 是否新 attempt/transaction | 处理原则 |
|---|---|---|---|
| worker 暂时性超时 | 是 | 新 RenderAttempt | 保留失败 attempt，不重新规划 |
| 浏览器崩溃 | 条件允许 | 新 RenderAttempt | 环境与资源仍须完全匹配锁 |
| 锁后输入/资源漂移 | 否 | 否 | `LOCK_INPUT_DRIFT`，建立新候选/锁 |
| 字段/单位/表达语义错误 | 否 | 否 | `ENCODING_SEMANTICS_INVALID`，停止渲染 |
| 渲染环境实质漂移 | 否 | 否 | 明确环境漂移错误，不伪装 timeout |
| PDF 成功、必需 PNG 失败 | 可修复后重渲染 | 新 RenderAttempt | 未齐全前不得 check/G3 |
| 成品检查 blocker/error | 视原因而定 | 通常新 attempt 或新锁 | 不得由 G3 绕过 |
| G3 无效、过期或对象不匹配 | 否 | 否 | 重新签发精确 G3 |
| staging 写入中断 | 是 | 恢复同一 transaction | 按事务证据继续或安全失败 |
| 原子提交后客户端超时 | 不盲重试 | 查询原 transaction | 按幂等键返回已有回执 |
| 同幂等键不同对象 | 否 | 否 | 幂等冲突，拒绝 |
| G3 nonce 消费后中断 | 严格条件下恢复 | 同一 transaction | 只凭 workflow-local intent 和不可变证据恢复 |

所有恢复都必须验证输入指纹、前置摘要、revision/CAS 和不可变证据。不能因为“文件看起来存在”就推断步骤成功。

---

## 十一、测试、提交与验收门禁

### 11.1 每阶段通用测试层级

1. **Schema 测试**：合法/非法 Fixture、未知字段拒绝、跨对象摘要字段完整性。
2. **单元测试**：摘要、PathGuard、状态转换、错误分类、幂等判定和审批绑定。
3. **集成测试**：真实受控浏览器、真实文件产物、真实仓库写入和不可变回执。
4. **故障注入**：超时、崩溃、磁盘满、权限失败、回执落盘窗口中断和并发旧写者。
5. **端到端测试**：独立模板 Fixture 与项目数据跑通完整洪涝链路。
6. **安全测试**：路径逃逸、跨项目/租户引用、审批重放、日志泄漏和目的地越权。
7. **全量回归**：U-P0～U-P2 两条既有工作流保持通过。
8. **宿主 Agent 验收**：CLI 真实入口、能力声明、恢复查询和失败信息与 Skill 文档一致。

### 11.2 阶段提交要求

每个子阶段提交记录至少说明：

- 实际实现范围和未实现范围；
- 新增/修改的 Schema、Policy 和注册项；
- 状态迁移和恢复窗口；
- 安全与数据边界；
- 测试命令、测试数量和结果；
- 真实浏览器/文件系统环境信息；
- 已知限制及其后续归属。

不得把三个子阶段压成一个不可审查的大提交，也不得在测试中使用生产数据或真实敏感坐标。

---

## 十二、U-P3 总体验收标准

只有同时满足下列条件，U-P3 才能标记完成：

- [x] `urban-flood-risk/1.0.0` 的唯一身份已收敛，模板创建和发布可重放（U-P3.0 已完成）。
- [x] 模板 Fixture 与地图生成项目数据相互独立。
- [x] G1/G2/G3 与模板 T1/TP 相互独立，不能跨 gate 复用。
- [x] G2 与候选执行摘要严格一致，冻结不重算。
- [x] 正式渲染只消费 MapSpecLock，锁后快照变化返回 `LOCK_INPUT_DRIFT`。
- [x] 字段语义错误返回 `ENCODING_SEMANTICS_INVALID` 并停止渲染。
- [x] 渲染超时能在同锁下建立新 attempt，失败证据不被覆盖。
- [x] 正式 PDF/PNG 均通过文件、页面、字体、裁剪、标签、图例、署名和绑定检查。
- [x] 所有正式渲染成果醒目标注“合成数据演示，非真实风险研判”。
- [x] G3 精确绑定不可变 DeliveryManifest。
- [x] 交付采用 staging、完整校验、原子提交和不可变 DeliveryReceipt。
- [x] 交付提交超时能按幂等键查询已有 delivery，不产生重复副作用。
- [x] 全链路状态、步骤回执、attempt、检查报告、事务和审批均可追踪、可恢复。
- [x] 普通日志、Fixture 和成果包无密钥、生产数据、完整业务数据行或应急敏感坐标。
- [x] `SKILL.md` 和工作流文档只声明真实通过的合成数据工程演示能力。
- [ ] 全量自动测试已通过且未破坏 U-P0～U-P2；宿主 Agent 与人工验收仍待独立确认。

仅完成冻结、仅生成一张 PNG、仅准备好待 G3 的 Manifest，或仅把文件复制到目录，都不构成 U-P3 完成。

---

## 十三、与 U-P4 的边界

U-P3 交付的是一个可恢复的洪涝合成数据工程样例，用于证明锁后渲染、成品检查和原子交付机制可以闭环。以下事项继续归 U-P4 或后续阶段：

- 政务专题、应急专题、领导调研三场景的正式业务验收；
- 真实数据访问、真实 CRS 转换及生产数据隔离；
- 多灾种、点线组合、可信地点/路线和专业法定审查；
- 正式生产能力矩阵、服务级隔离、备份与运维指标；
- 企业连接器、共享部署、在线服务和公网发布；
- 全矢量 PDF、原生 GIS 编辑、多图册及 Web/移动端输出。

U-P3 的完成不得自动修改 `formal_capability_boundary.production_tasks` 为已开放。任何生产能力声明都必须在 U-P4 以独立场景、真实证据和对应审批重新验收。
