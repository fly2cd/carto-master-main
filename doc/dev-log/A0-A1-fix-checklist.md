# A0/A1 待修复与优化清单

更新日期：2026-11-12（Asia/Shanghai）
来源：A0/A1 阶段代码审计报告（已完成独立验证）

## P0：必须修复（阻断性，当前阶段无法发布）

| 编号 | 问题 | 状态 |
|------|------|------|
| R1 | NonceStore 零调用，防重放未实现 | ✅ 已修复 |
| R3 | 身份校验自我印证（subject_id 来自票据自身） | ✅ 已修复 |
| R4 | revive() 写回不可变请求，必抛 IMMUTABLE_ARTIFACT_CONFLICT | ✅ 已修复 |
| R5 | revive() 改写原请求导致 JOB_INPUT_DRIFT 死锁 | ✅ 已修复 |
| R6 | _design_overrides 零消费者，cartography 变更不可达 | ✅ 已修复 |
| R7 | check(failed) 无合法出口，终检失败即死路 | ✅ 已修复 |
| R8 | general_thematic.py schema_version=3 vs raster_page_contract v4 冲突 | ✅ 已修复 |
| R10 | BudgetStore 持久化 time.monotonic() 跨进程无意义 | ✅ 已修复 |

### P0 修复详情

- **R1**: NonceStore 通过 ApprovalGateCoordinator 接入审批流。MapGenerationWorkflow.__init__ 创建 NonceStore 实例（`.nonce-ledger.db`），`_gate_coordinator()` 将其注入每个审批协调器。`verify_and_consume()` 支持幂等重放（相同 intent_digest 的已消费 nonce 静默接受）。NonceStore 连接使用 contextmanager 确保 Windows 下 WAL 文件可清理。
- **R3**: `ApprovalGateCoordinator` 接受 `trusted_subject_id`/`trusted_tenant_id`/`trusted_scope`，从 ExecutionContext 派生，不再使用票据自身字段做比较。`_gate_coordinator()` 辅助方法统一派生受信身份。
- **R4/R5**: `revise()` 重写：修订产物写入 `revisions/r{N}/` 目录（create_once=True，不可变）；工作副本用 create_once=False 更新；`state.input_fingerprint` 在 complete_step 前更新为修订请求摘要。
- **R6**: cartography 变更存储为 `revised_cartography`（非 `_design_overrides`）；`_compile_approved_candidate` 在加载 contracts 后合并 `revised_cartography`；generate-request schema 新增 `revised_cartography` 可选属性。
- **R7**: `revise()` 接受 `step=check, status=failed` 状态入口（check 失败后可修订）。
- **R8**: `general_thematic.py:193` schema_version 3→4。
- **R10**: `ExecutionBudget.started_monotonic` → `started_at`（使用 `time.time()`）；BudgetStore 和 budget-state schema 同步更新。

## P1：当前阶段应该修

| 编号 | 问题 | 状态 |
|------|------|------|
| R2 | after-approval-consumed 钩子不消费 nonce（R1 修好后可缓解） | 待修复 |
| Y1 | review 复用 G2 票据，批准对象语义不匹配 | 待修复 |
| Y2 | 版本化未落地：预览 ID 只取 run_id，无选定版本指针 | 待优化 |
| Y4 | 修订提案缺 parent_revision 校验、layout_parameters 无约束 | 待修复 |

## P2：后续阶段修（不阻塞当前）

| 编号 | 问题 | 状态 |
|------|------|------|
| R9 | A1 端到端测试跳过 compile，无全链路验收测试（属 A5 任务） | 推迟 |
| Y3 | BoundedAgentRuntime 未接入主链 | 推迟 |
| Y5 | 中断注入仅覆盖 1/5 相位 | 推迟 |
| Y6 | A0 退出条件未满足即推进 A1（工程管理问题，非代码缺陷） | 记录 |
| Y7 | map-plan 代码 v3 vs SKILL.md 声明 v4 | 待修复 |
| G1 | _classify_check_failure 永不返回 MANIFEST_ISSUE | 待优化 |
| G2 | verify_and_consume 只 reserve 不 consume | 待修复 |
| G3 | review 的 deliver 重入分支忽略审批参数 | 待修复 |
| G4 | 预览证据四条检查恒为 passed | 推迟 |
| G5 | approval-receipt Schema signature 不在 required | 待修复 |

## 修复原则

1. 每批修改对应一个明确协议变化或可验收行为
2. 不把"先改 Schema、后面再补消费者"作为可发布中间状态
3. 修改后运行全部核心回归测试确认零退化
4. 每完成一批更新本清单状态并记录 dev-log

## 测试结果（2026-11-12）

- 全部核心测试：382 passed, 8 failed (均为预存 page-contract v4 不匹配及其他已知问题)
- raster formal 测试：16 passed (P0 修复后全部通过)
- A1.2 revision 测试：16 passed (NonceStore Windows 文件锁定问题已修复)
- A2 material 测试：34 passed