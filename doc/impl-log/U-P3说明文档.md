# U-P3 说明文档：首个纵向工程闭环

## 文档信息

| 项目 | 内容 |
|---|---|
| 阶段 | U-P3：首个纵向工程闭环（城市洪涝风险研判图，合成数据演示） |
| 日期 | 2026-09-21 |
| 状态 | U-P3.0～U-P3.3 已完成；自动化实现与全量回归通过，人工业务验收按项目流程单独执行 |
| 唯一实现根 | `skills/carto-agent/` |
| 子阶段 | U-P3.0 前置缺口收敛 → U-P3.1 锁驱动正式渲染 → U-P3.2 成品检查与 G3 事前对象冻结 → U-P3.3 G3 原子交付与全链路收口 |
| 依据 | [实施计划 v2.2](../implement-plan.md) 第五章、`doc/u-p3-implementation-plan.md`、四份 U-P3.x 实施记录 |
| 能力边界 | 本地允许根内的合成数据工程演示闭环；**不构成生产能力声明** |
| 本文性质 | 说明文档（实施总结），不是运行时协议；运行时仍只读取 Skill 内 Schema、Policy、注册表和项目产物 |

---

## 一、U-P3 的目标与定位

U-P3 以"城市洪涝风险研判图"为纵向样例，打通从模板创建到地图生成、正式渲染、成品检查、原子交付的**完整工程链路**，验证交接、恢复与修复边界。本阶段全程使用合成数据，产出可重复的工程演示证据，不据此宣称生产业务适用性已经通过。

U-P3 的四个子阶段**严格串行**，每个子阶段独立提交、独立验收并运行全量回归；前一子阶段未满足退出门槛时不得合入后续代码。

- **U-P3.0**：开工前基线收敛，修复 U-P2.7 遗留的身份、状态、交付对象拆分与能力声明缺口。
- **U-P3.1**：锁驱动正式渲染，把已冻结的 `MapSpecLock` 变成正式 PDF/PNG 成品。
- **U-P3.2**：成品确定性检查、Final ValidationReport 落盘、不可变 DeliveryManifest 冻结，停在 G3 之前。
- **U-P3.3**：精确 G3、可恢复 DeliveryTransaction、同文件系统原子目录提交、不可变 DeliveryReceipt，全链路收口。

---

## 二、子阶段总览与完整状态机

### 2.1 子阶段总览

| 子阶段 | 目标 | 入口状态 | 出口状态 | 新增协议 |
|---|---|---|---|---|
| U-P3.0 | 基线收敛（身份/状态/交付对象/能力声明） | `succeeded / freeze`（U-P2.7 旧） | `pending / render` | `delivery-receipt`（新增）；`delivery-manifest`（强化） |
| U-P3.1 | 锁驱动正式渲染 | `pending / render` | `pending / check` | `render-attempt`、`formal-render-evidence` |
| U-P3.2 | 成品检查 + G3 事前对象冻结 | `pending / check` | `waiting_approval / deliver` | `validation-report`（强化） |
| U-P3.3 | G3 + 原子交付 + 收口 | `waiting_approval / deliver` | `succeeded / deliver` | `delivery-transaction`、`delivery-receipt`（消费） |

### 2.2 完整状态机（地图生成侧）

```text
intake → brief → compile → preview → freeze   (U-P2.5 / U-P2.6)
                                              │
                                              ▼
                                         pending / render   (U-P3.0 修正后)
                                              │
                ┌─────────────────────────────┼─────────────────────────────┐
                ▼                             ▼                             ▼
          成功渲染                       暂时性失败                     漂移/语义失败
       pending / check              failed / render                 failed / render
                                     │ retry（新 attempt）           （不可普通 retry）
                                     ▼
                                pending / render
                                              │
                                              ▼  (U-P3.2)
                                         pending / check
                                              │
                ┌─────────────────────────────┴────────────────────────────┐
                ▼                                                            ▼
          检查通过                                                    检查失败
       waiting_approval / deliver                              failed / check
              │                                               （不可绕过 retry）
              ▼  (U-P3.3) G3 + 原子提交
         succeeded / deliver
```

关键不变量：每个 mutating 步骤都受 run 级单写锁保护，状态更新用单调递增 revision + 不可变回执，恢复凭严格匹配的已消费审批与确定性产物，**普通 nonce 重放不转换为恢复**。

---

## 三、U-P3.0 前置缺口收敛

U-P3.1 开工前先修复 U-P2.7 遗留的基线缺口，避免在错误基础上写正式渲染。

### 3.1 已关闭的缺口

| 缺口 | 修正 |
|---|---|
| 模板身份双轨 | MapScenario 唯一身份统一为 `urban-flood-risk/1.0.0`；`flood-risk-overview` 仅为作者 profile；旧 `flood-scenario` ID 由 Schema 明确拒绝，不加双轨兼容 |
| freeze 后状态 | freeze 成功创建 `MapSpecLock` 后不再标 `succeeded`，改为 `pending / render`，准确表达下一安全步骤；已写锁未推进的崩溃窗口仍可凭严格匹配的已消费 G2 恢复；`pending / render` 下重复 freeze 幂等返回 |
| 交付事前/事后对象 | `DeliveryManifest` 收敛为 G3 不可变事前批准对象，**不含 `delivered_at`**；新增 `DeliveryReceipt` 承载提交后的事务标识、最终路径、`committed` 状态与 `delivered_at` |
| 能力范围声明 | `scope-baseline.yaml` 更新到 `0.3.0 / u-p3-prerequisites-aligned`；正式交付仅声明为 `planned-u-p3-local-synthetic-only`，不宣称已实现或具备生产能力 |

### 3.2 协议与测试覆盖

新增/强化的拒绝用例：旧 `flood-scenario` ID（模板/生成请求各一）、DeliveryManifest 携带 `delivered_at`、缺 PNG 成果、缺固定合成数据限制声明、DeliveryReceipt 缺 `delivered_at`、状态非 `committed`、freeze 后状态非 `pending / render`、写锁后状态写入失败的恢复与重复 freeze 幂等。

### 3.3 未提前开放

锁驱动正式 `render`、PDF/PNG 成品 `check`、DeliveryManifest 业务生成与 G3 等待、G3 nonce 消费、原子交付事务与 DeliveryReceipt 业务写入——均继续按 U-P3.1/3.2/3.3 串行实施。

---

## 四、U-P3.1 锁驱动正式渲染

把已验证的 `MapSpecLock` + 锁定 `RenderScene` + 锁定资源变成正式 PDF/PNG 成品，**不重新调用规划器或模型、不读"最新"模板、不重算分类与字段绑定**。

### 4.1 实现要点

- 新增 `FormalMapRenderService`，只从已验证 `MapSpecLock` 与锁定 RenderScene 执行正式渲染。
- 正式 PDF/PNG 写入**不可覆盖**目录 `output/<lock-id>/formal-map/<attempt-id>/`。
- 同时保留业务执行摘要与 renderer execution digest，绑定 Renderer Profile、环境、资源集合、回执与输出摘要。
- RenderScene 与证据固定携带"合成数据演示，非真实风险研判"。

### 4.2 漂移与语义阻断

| 失败类别 | 错误码 | 是否可普通 retry |
|---|---|---|
| 锁后输入漂移（候选/预览证据/模板安装/字体/数据/资源） | `LOCK_INPUT_DRIFT` | 否 |
| 环境漂移 | `RENDER_ENVIRONMENT_DRIFT` | 否 |
| 场景语义错误 | `ENCODING_SEMANTICS_INVALID` | 否 |
| 暂时性浏览器/worker 错误 | （attempt 失败） | 是，同锁新建 attempt，原失败记录不覆盖 |

### 4.3 attempt 生命周期与恢复

成功与失败 attempt 独立记录；暂时性错误允许同锁新建 attempt。覆盖"attempt/evidence 已写、步骤回执未写"窗口的验证恢复；重复成功命令验证 attestation 与文件摘要后幂等返回。新增 `carto generate-map render`，成功状态推进到 `pending / check`。

---

## 五、U-P3.2 成品检查与 G3 事前对象冻结

完成正式 PDF/PNG 的确定性检查、Final ValidationReport 落盘、不可变 DeliveryManifest 冻结与精确 G3 上下文生成。**严格停在 G3 之前**：不消费 G3 nonce，不开放 `generate-map deliver`，不创建交付目的目录，不复制成果，不写 DeliveryReceipt。

### 5.1 注册且版本化的最终检查（11 项）

`checker-registry.yaml` 更新至 `1.1.0`，`FinalMapCheckService` 执行：

| # | 检查 | 内容 |
|---|---|---|
| 1 | `final.artifact-integrity` | 成果存在、非空、摘要与媒体签名一致 |
| 2 | `final.required-targets` | PDF/PNG 必需目标齐全且来自选定 attempt |
| 3 | `final.pdf-page-contract` | PDF 单页、MediaBox、A3 横向合同 |
| 4 | `final.png-raster-contract` | PNG 2381×1684、144 DPI、bit depth、color type |
| 5 | `final.font-policy` | 字体资源绑定与 PDF 字体证据 |
| 6 | `final.layout-elements` | 标题/图例/比例尺/指北针/来源署名/安全边距，按 SVG compositor 规则估算 overlay 边界 |
| 7 | `final.legend-semantics` | 分级图例、无数据项、比例符号语义 |
| 8 | `final.synthetic-notice` | "合成数据演示，非真实风险研判"声明链 |
| 9 | `final.render-binding` | lock/attempt/RenderReceipt/FormalRenderEvidence/环境绑定 |
| 10 | `final.sensitive-content` | 密钥、未授权路径、业务原始行、敏感调试内容扫描 |
| 11 | `final.renderer-warnings` | 已知 warning 明确接受，未知 warning 以 `disposition: blocked` 阻断 |

任一 blocker/error 失败或 warning 未被接受 → 报告 failed → `failed / check`，**不生成 DeliveryManifest**；普通 `retry` 返回 `JOB_RETRY_NOT_ALLOWED`，不能绕过成品失败。

### 5.2 成品合同

- PDF：单页 A3 横向，420 mm × 297 mm
- PNG：2381 × 1684，144 DPI
- 必需格式：PDF、PNG
- 必需声明：合成数据演示，非真实风险研判
- 验收浏览器：Chromium `152.0.7977.83`

### 5.3 Final ValidationReport 与 DeliveryManifest

- 报告写入 `final-checks/<attempt-id>/validation-report.yaml`，绑定 `phase: final-check`、被检 attempt/lock、checker-registry 规范摘要、每个 checker 的版本/严重度/状态/详情、成果路径格式大小摘要、计数与 warning disposition。
- 检查通过后写不可变 `delivery-manifests/<manifest-id>.yaml`，精确绑定 tenant/project/run/scope/environment、MapSpecLock + execution digest、选定 RenderAttempt + renderer execution digest、Final ValidationReport 引用与摘要、已检 PDF/PNG 路径格式大小摘要、recipient、项目根内规范化 destination、licenses/限制/合成声明、idempotency key。
- G3 上下文：`action: approve-delivery` / `object_type: delivery-manifest` / `object_digest: sha256_digest(DeliveryManifest)`。**G3 绑定完整 Manifest 摘要**，不绑简化 lock 摘要、目录名或文件数量。

### 5.4 路径与零副作用保证

`destination` 必须是项目根内相对路径并先经 PathGuard 规范化。U-P3.2 仅把规范化路径冻结进 Manifest：不创建 destination、不创建 staging、不复制/移动成果、不写交付事务、不写 DeliveryReceipt。绝对路径、逃离项目根或逃离允许根分别被明确拒绝。

### 5.5 状态、幂等与恢复

- 成功：`pending/check` → 执行检查 → 写 Final ValidationReport → 冻结 DeliveryManifest → `waiting_approval/deliver`。完全相同的 check 调用幂等返回已有报告/Manifest/G3 上下文；recipient/destination/idempotency key 变化返回 `DELIVERY_MANIFEST_INPUT_MISMATCH`。
- 失败：写 failed Final ValidationReport → `failed/check`，不生成 Manifest。
- 恢复窗口：覆盖"Final ValidationReport 与 DeliveryManifest 已 create-once 写入，但 check step receipt/状态未提交"的中断；恢复时重新验证正式成果、报告和 Manifest，只在内容完全一致时补写步骤回执并推进状态，不靠文件存在性猜测成功。

---

## 六、U-P3.3 G3 原子交付与全链路收口

把 U-P3.2 冻结的 DeliveryManifest 接入精确 G3，增加可恢复 DeliveryTransaction、同文件系统原子目录提交、不可变 DeliveryReceipt 与按幂等键查询。

### 6.1 G3 验证与消费

`MapDeliveryService` 在任何交付副作用前重新验证：generate request 与项目/tenant/run/scope/environment、不可变 DeliveryManifest 及引用摘要、passed Final ValidationReport 及文件、MapSpecLock、成功 RenderAttempt、execution/renderer execution 摘要、PDF/PNG 路径格式大小摘要与报告绑定，以及 G3 的 issuer/approver/action/object type/Manifest digest/scope/tenant/environment/policy/有效期/nonce。

G3 固定为 `action: approve-delivery` / `object_type: delivery-manifest` / `object_digest: sha256_digest(DeliveryManifest)`。消费前保留 workflow-local intent `<workdir>/approvals/g3/<manifest-id>.yaml`；nonce 已消费时，只有 intent 存在且内容与审批文件完全一致才能恢复——缺失返回 `APPROVAL_RECOVERY_EVIDENCE_MISSING`，漂移返回 `APPROVAL_RECOVERY_EVIDENCE_CONFLICT`，普通重放不转换为恢复。

### 6.2 DeliveryTransaction 与 Repository

新增 `delivery-transaction` 协议与项目内 `DeliveryRepository`。事务 journal：

```text
<project>/.carto/delivery/transactions/<sha256(idempotency-key)>.yaml
<project>/.carto/delivery/receipts/<delivery-id>.yaml
```

状态序列：`intent-created → staged → committed → receipt-written`。事务精确绑定 Manifest、G3、recipient、destination、project、tenant、run、幂等键与 PDF/PNG 摘要；同幂等键的任何绑定变化返回 `IDEMPOTENCY_CONFLICT` 或事务绑定冲突。

### 6.3 staging、完整校验与原子提交

最终目录同级创建隐藏 staging `.<delivery-name>.staging-<manifest-digest-prefix>`，固定顺序：

1. 创建事务 intent
2. 在 staging 复制经摘要验证的 PDF/PNG
3. 写 DeliveryManifest、README 和 checksums
4. 校验目录类型、link/junction、文件白名单、Manifest、checksum、成果摘要、许可与限制
5. `os.replace(staging_path, final_path)` 完成同文件系统原子目录提交
6. 重新验证最终包
7. 写不可变 DeliveryReceipt
8. 更新事务并完成 workflow 步骤回执

最终目录存在时不覆盖；只有其内容与当前 Manifest 完全一致时才作为提交后恢复，任何外来文件或摘要漂移均拒绝。

### 6.4 最终包白名单

成果包仅含：`map.pdf`、`map.png`、`README.md`、`delivery-manifest.yaml`、`checksums.sha256`。**不包含**原始 GeoJSON、MapSpecLock、RenderAttempt、RenderReceipt、FormalRenderEvidence、内部 ValidationReport、审批文件或密钥。README 含许可、限制与"合成数据演示，非真实风险研判"。

### 6.5 CLI 与查询

新增 `carto generate-map deliver` 与 `carto generate-map delivery-status --idempotency-key <key>`。`deliver` 成功后状态 `succeeded / deliver`；重复调用验证 G3 恢复证据与事务绑定，返回同一 DeliveryReceipt，不写第二份步骤回执；提交结果未知时可按幂等键查询 transaction/receipt。

### 6.6 恢复窗口（故障注入覆盖）

自动测试覆盖 6 个窗口：`after-approval-consumed`、`after-transaction-intent`、`after-staging`、`after-atomic-commit`、`after-receipt`、`before-step-complete`。恢复原则：G3 已消费但事务未创建→依赖精确 workflow-local intent；staging 已完整→重新校验后提交（损坏 staging 删除并安全重建）；最终目录已提交但事务/回执未补记→严格验证最终包后补记；回执已写但 transaction 或步骤回执未完成→验证不可变回执绑定后补记；最终目录竞争或外来内容→不覆盖、不误报成功；同幂等键不同对象→拒绝，不产生第二份成果。

---

## 七、贯穿全程的安全与数据边界

| 边界 | 实现 |
|---|---|
| 路径安全 | 所有输入、输出、回执、attempt、staging、最终包路径继续经 PathGuard；绝对路径/越根/alternate stream/符号链接逃逸均拒 |
| 不可变 + 摘要寻址 | 回执、MapSpecLock、DeliveryManifest、DeliveryReceipt、RenderAttempt、FormalRenderEvidence 均 create-once、digest 寻址；下游每步重校验摘要与 Schema，漂移拒绝 |
| 审批门禁 | T1/TP/G1/G2/G3 均 HMAC + 一次性 nonce + 绑对象摘要/作用域/身份/环境/有效期；模型无权签发；恢复只认已消费且严格匹配的不可变证据 |
| 默认 deny | ToolGateway `default: deny`、`unregistered_capability: reject`；未注册能力与越权调用拒绝 |
| 合成数据标识 | RenderScene、FormalRenderEvidence、Final ValidationReport、DeliveryManifest、最终包 README 全程携带"合成数据演示，非真实风险研判" |
| 日志脱敏 | 日志与协议不新增密钥、完整业务数据行、完整行程或应急敏感坐标 |

---

## 八、协议资产清单（U-P3 新增/强化）

| 协议 | 阶段 | 作用 |
|---|---|---|
| `delivery-receipt` | U-P3.0 新增 | 提交后不可变回执：事务标识、最终路径、G3 引用、`committed`、`delivered_at` |
| `delivery-manifest` | U-P3.0 强化、U-P3.2 冻结 | G3 不可变事前批准对象（不含 `delivered_at`），绑定 lock/attempt/报告/成果/recipient/destination |
| `render-attempt` | U-P3.1 新增 | 单次正式渲染 attempt 记录 |
| `formal-render-evidence` | U-P3.1 新增 | 正式渲染证据：环境、资源、回执、输出摘要、合成声明 |
| `validation-report` | U-P3.2 强化 | Final ValidationReport，final-check 字段强制、未知字段拒绝 |
| `delivery-transaction` | U-P3.3 新增 | 交付事务 journal：intent→staged→committed→receipt-written |

Schema 注册表从 U-P2.7 的 43 个增长到 **47 个**（`carto schema check` 实测）。所有新协议均 Draft 2020-12、`additionalProperties: false`、配合法/通用非法/语义非法 Fixture。

---

## 九、验证与回归

### 9.1 各子阶段专项测试

| 子阶段 | 专项测试 | 结果 |
|---|---|---|
| U-P3.0 | test_schemas / test_up2_template / test_up24 / test_up25_up26 | OK |
| U-P3.1 | test_up31_formal_render（8） | OK |
| U-P3.2 | test_up32_final_check（7） | OK |
| U-P3.3 | test_up33_delivery（含 schemas，24） | OK |

### 9.2 全量回归演进

| 节点 | 测试数 | 结果 |
|---|---|---|
| U-P2.7 | 110 | OK (skipped=1) |
| U-P3.0 | 110 | OK (skipped=1) |
| U-P3.1 | 118 | OK (skipped=1) |
| U-P3.2 | 127 | OK (skipped=1) |
| U-P3.3 | 137 | OK (skipped=1) |

唯一 skip 为 Windows 符号链接权限用例（需开发者模式或管理员权限）。`git diff --check` 无空白错误，仅 Windows 工作区的 LF→CRLF 提示。

### 9.3 验证命令

```powershell
python skills/carto-agent/scripts/carto.py schema check          # 47 schemas
python -m unittest discover -s skills/carto-agent/scripts/tests -v
```

---

## 十、明确未实现范围

U-P3 完成**只表示合成数据工程演示闭环成立**，以下仍不开放：

- 真实 CRS 转换与生产数据制图；
- 三场景（政务专题、应急测绘、领导调研）生产业务验收；
- 企业连接器、共享部署、外部对象存储或公网发布；
- 生产 SLA、备份、运维指标与多主机事务；
- `map-brand`、`map-style`、`map-layout` 的业务创建路由；
- G3 之外的其他外部审批集成。

`scope-baseline.yaml` 已更新为 `0.3.3 / u-p3-local-synthetic-delivery-enabled`，`production_tasks` 继续为空。

---

## 十一、与上层计划的衔接

对照 [implement-plan.md](../implement-plan.md) 第五章 U-P3 退出标准：

- [x] 洪涝模板创建、发布到地图生成、交付全链路可运行（合成数据）。
- [x] 交接与修复边界有效，单条链路可恢复可追踪（G1/G2/G3 恢复窗口 + 6 个交付故障注入窗口）。
- [x] 不宣称三场景已覆盖。
- [x] 演示输出带醒目标识"合成数据演示，非真实风险研判"。
- [x] 模板 Fixture 与生成项目数据相互独立，均可固定重放。
- [x] 本阶段结果明确标记为工程演示证据，不能去除演示标识后作为生产成果。

U-P3 闭环成立后，后续进入 U-P4（三场景业务与生产闭环），按真实/脱敏业务数据与正式能力矩阵验收；U-P3 的合成演示证据**不代替**生产适用性证明。
