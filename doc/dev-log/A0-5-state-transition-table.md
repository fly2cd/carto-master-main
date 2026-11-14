# A0-5：状态转移表冻结与版本切换策略

更新日期：2026-11-12（Asia/Shanghai）
状态：**D-A05-02 已确认，其余待确认**

### 确认记录

| # | 决策项 | 状态 |
|---|--------|------|
| D-A05-01 | 当前 8-step 转移表确认 | 待确认 |
| D-A05-02 | revise step 置于 compile→preview 之间 | ✅ 已确认（compile(failed) → revise → compile） |
| D-A05-03 | review step 置于 check→deliver 之间 | 待确认 |
| D-A05-04 | 启用 running 状态 | 待确认 |
| D-A05-05 | 版本切换策略 | 待确认 |
| D-A05-06 | cancelled 状态触发条件 | 待确认 |
| D-A05-07 | 模板工作流 revise/review | 待确认 |

## 一、当前状态转移表（代码实现基线）

### 1.1 JobState 核心字段

| 字段 | 类型 | 说明 |
|------|------|------|
| `schema_version` | int | job-state schema 版本号（当前=1） |
| `revision` | int ≥1 | 单调递增，每次 complete_step 或 retry 时 +1 |
| `status` | enum | 见 1.2 |
| `step` | string(1-64) | 当前工作流步骤名 |
| `attempt` | int ≥1 | 当前步骤的尝试次数 |
| `run_id` | string | 任务唯一标识 |
| `input_fingerprint` | string | 输入摘要，防止输入漂移 |
| `last_receipt` | string | 最近一次 StepReceipt 的相对路径 |

### 1.2 状态值定义

| status | 含义 | 进入方式 |
|--------|------|----------|
| `pending` | 等待执行 | 初始状态 / 步骤推进 |
| `running` | 执行中 | 定义但当前未使用 |
| `waiting_approval` | 等待外部审批 | complete_step 在需要审批的步骤 |
| `succeeded` | 已完成 | 最后一步完成 |
| `failed` | 执行失败 | 任意步骤失败 |
| `cancelled` | 已取消 | 定义但当前未使用 |

### 1.3 制图工作流状态转移（MapGenerationWorkflow）

```
                         ┌──────────┐
                         │  intake  │ G0: 初始化
                         │ pending  │
                         └────┬─────┘
                              │ complete_step(status=succeeded, next_step="brief")
                              ▼
                         ┌──────────┐
                         │  brief   │ 意图解析 + brief 构建
                         │ pending  │
                         └────┬─────┘
                              │ complete_step(status=waiting_approval, next_step="compile")
                              ▼
                    ┌───────────────────┐
                    │     compile       │ G1 审批 → 候选编译
                    │  waiting_approval │
                    └────┬──────┬───────┘
                         │      │
           preflight=ok  │      │ preflight=failed
                         │      ▼
                         │  ┌────────┐
                         │  │ failed │（终止）
                         │  └────────┘
                         │ complete_step(status=succeeded, next_step="preview")
                         ▼
                    ┌──────────┐
                    │ preview  │ G2-preview 审批 → 受控预览
                    │ pending  │
                    └────┬─────┘
                         │ complete_step(status=waiting_approval, next_step="freeze")
                         ▼
                    ┌───────────────────┐
                    │     freeze        │ G2-freeze 审批 → 冻结 + 渲染
                    │  waiting_approval │
                    └────┬──────────────┘
                         │ complete_step(status=succeeded, next_step="render")
                         ▼
                    ┌──────────┐
                    │  render  │ 正式渲染（可崩溃恢复）
                    │ pending  │
                    └────┬─────┘
                         │ complete_step(status=succeeded, next_step="check")
                         ▼
                    ┌──────────┐
                    │  check   │ 终检 + 生成 Manifest
                    │ pending  │
                    └────┬─────┘
                         │ complete_step(status=waiting_approval, next_step="deliver")
                         ▼
                    ┌───────────────────┐
                    │     deliver       │ G3 审批 → 交付
                    │ waiting_approval  │
                    └────┬──────────────┘
                         │ complete_step(status=succeeded)
                         ▼
                    ┌──────────┐
                    │ 终端状态  │
                    │succeeded │
                    └──────────┘

任一步骤失败 ──→ failed ──→ retry() ──→ 回到失败步骤（attempt+1, status=pending）
```

**转移规则**：

| # | 当前 step | 当前 status | 触发条件 | 新 step | 新 status |
|---|-----------|-------------|----------|---------|-----------|
| 1 | intake | pending | initialize() | intake | pending |
| 2 | intake | pending | complete_step(ok) | brief | pending |
| 3 | brief | pending | complete_step(waiting) | compile | waiting_approval |
| 4 | compile | waiting_approval | G1 approve + compile ok | preview | pending |
| 5 | compile | waiting_approval | G1 approve + preflight fail | compile | failed |
| 6 | preview | pending | complete_step(waiting) | freeze | waiting_approval |
| 7 | freeze | waiting_approval | G2 approve + freeze ok | render | pending |
| 8 | render | pending | complete_step(ok) | check | pending |
| 9 | render | pending | 渲染失败 | render | failed |
| 10 | check | pending | complete_step(waiting) | deliver | waiting_approval |
| 11 | check | pending | 终检失败 | check | failed |
| 12 | deliver | waiting_approval | G3 approve + deliver ok | deliver | succeeded |
| 13 | any | failed | retry() | 同步骤 | pending |

**已有崩溃恢复能力**：
- freeze 步骤内部：render 子步骤状态恢复
- check 步骤：从 waiting_approval 状态幂等重入
- deliver 步骤：从 succeeded 状态幂等重入
- state_machine 层：两阶段提交（transition → receipt → state → 删除 transition 标记）保证原子性

### 1.4 模板工作流状态转移（TemplateWorkflow）

```
analyze(pending) → brief(pending) → author(waiting_approval) → validate(pending)
                                                                    │
                                                    passed ─────────┼───────── failed
                                                       │                         │
                                                       ▼                         ▼
                                              publish(waiting_approval)      failed
                                                       │
                                                       ▼
                                                   succeeded
```

## 二、实施计划 A1–A5 需求的状态与当前差距

### 2.1 实施计划要求覆盖的状态

| 要求状态 | 当前状态 | 差距 |
|----------|----------|------|
| 新任务 | intake(pending) ✅ | — |
| 获准准备 | brief(pending) ✅ | — |
| 提交设计修订 | ❌ 不存在 | **G1：A1.2 新状态** |
| 编译 | compile(waiting_approval) ✅ | — |
| 预览 | preview(pending) ✅ | — |
| 待审阅 | ❌ 不存在 | **G1：A1.3 新状态** |
| 待 G2 | freeze(waiting_approval) ✅ | — |
| 已冻结 | render(pending) ✅ | — |
| 正式渲染 | render(pending) ✅ | — |
| 终检/成品审查 | check(pending) ✅ | — |
| 待 G3 | deliver(waiting_approval) ✅ | — |
| 已交付 | deliver(succeeded) ✅ | — |

### 2.2 需要新增的状态

实施计划 A1.2/A1.3 引入后，需要新增以下 step：

| 新 step | 来源 | 说明 |
|---------|------|------|
| `revise` | A1.2 设计修订 | 编译后发现问题 → 提交设计修订提案 → 重新编译 |
| `review` | A1.3 审图闭环 | 终检未通过 → 模型建议 → 业务审查 → 重新冻结 |

### 2.3 `running` 状态的启用时机

当前定义了 `running` 但未使用。应在以下场景启用：
- 长时间运行的渲染步骤（render）— 标记 running 让外部可观测进度
- 设计修订循环（revise）— running 表示 LLM 正在生成修订提案

## 三、版本切换策略

### 3.1 当前设计

`JobState.schema_version` 和 `ApprovalReceipt.schema_version` 均已定义，但当前均固定为 1，无迁移逻辑。

### 3.2 策略提议

| 升级场景 | 策略 |
|----------|------|
| job-state schema 升级 | 新增 forward-compatible 字段：默认值兼容旧格式；移除/重命名字段：需要显式迁移版本检查。`load()` 时检测 `schema_version`，若 old < current 则执行一次性迁移转换 |
| approval-receipt schema 升级 | 新版票据由新版代码签发，旧版票据在 expires_at 内仍可验证（宽松模式）；超过宽限期后仅接受当前版本。不自动转换已签发票据 |
| 策略/协议版本 | 在 `environment-fingerprint` 中记录完整协议栈版本，任何组件升级 → 环境指纹变更 → 要求重新 preview/freeze |

### 3.3 建议

- 当前 schema_version=1 保持不变，因为所有字段都是初始版本
- A1.2 引入设计修订后，可能需要在 `job-state` 中新增 `design_revision_id` 可选字段 → schema_version 升级到 2
- 升级时实现 `_migrate_state()` 方法，从旧 schema 自动转换

## 四、需要维护者确认的决策

| # | 决策项 | 选项 | 建议 |
|---|--------|------|------|
| D-A05-01 | 当前 8-step 制图工作流状态转移表是否确认？ | 确认 / 需要调整 | ✅ 确认（已通过 31+ 测试验证） |
| D-A05-02 | A1.2 新增 revise step，置于 compile → preview 之间？ | 是 / 放在其他位置 | 建议 compile(failed) → revise → compile |
| D-A05-03 | A1.3 新增 review step，置于 check → deliver 之间？ | 是 / 放在其他位置 | 建议 check(failed) 触发 review → freeze |
| D-A05-04 | 是否启用 running 状态用于长时间步骤（render）？ | 启用 / 暂不启用 | 建议 A1.2 时启用 |
| D-A05-05 | 版本切换策略采用"宽松过渡 + 宽限期"模式？ | 同意 / 其他方案 | 建议同意 |
| D-A05-06 | `cancelled` 状态触发条件？ | 用户主动取消 / 超时自动取消 / 暂不实现 | 建议暂不实现，A3 阶段再定义 |
| D-A05-07 | 模板工作流是否也需要对应的 revise/review 步骤？ | 是 / 模板用不同流程 | 模板已有 validate，审图逻辑不同，建议单独评估 |

---

*本文件待维护者逐项确认后，即为"冻结"版本。确认后更新日期和状态，后续 A1.2 阶段严格按此表实现状态转移。*