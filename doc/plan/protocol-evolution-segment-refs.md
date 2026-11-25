# 协议演进治理记录 — segment_refs（P4）

| 项目 | 内容 |
|---|---|
| 日期 | 2026-11-25 |
| 关联 | [ADR-001](ADR-001-composable-template-architecture.md)、[实施状态](composable-template-implementation-status.md) |
| 目的 | 闭合评估发现 3：公共协议扩展的显式版本决定、生产者—消费者清单、摘要影响分析与旧运行处理规则。"Schema 校验通过"不作为治理完成证据。 |

## 1. 变更清单与版本决定

| Schema | $id 版本 | 变更 | 版本决定 |
|---|---|---|---|
| `generate-request.schema.json` | v1 | 新增可选 `segment_refs`（style→map-style / layout→map-layout，精确钉住 templateRef） | **v1 内加性演进**，不升 $id |
| `design-revision-proposal.schema.json` | v1 | `changes` 闭合词表新增可选键 `segment_refs` | **v1 内加性演进**，不升 $id |

### 版本决定理由（显式，非默认）

1. **加性可选字段**：两处新增均为 optional。既有合法实例（不含该字段）形状与摘要不变，仍通过同一 v1 Schema；不产生旧实例失效。
2. **无并行兼容旁路**：不新增旧请求别名、旧锁兼容分支或自动迁移器（符合 SKILL.md doctrine）。新字段只有新代码消费；旧代码不识别该字段，按 doctrine 旧运行不自动迁移到新请求。
3. **闭合词表仍闭合**：`design-revision-proposal.changes` 与 `segment_refs` 自身均 `additionalProperties:false`；未知段/未知键拒绝。general-generate-request 的 `unevaluatedProperties:false` 现评估该字段，未知字段拒绝不变。
4. **不升 $id 的边界条件**：本决定仅适用于"加性可选 + 无消费者破坏 + 无旧实例漂移"。若未来 segment_refs 变为必填、改变既有字段语义、或要求旧代码识别，则必须升 $id 并成套交付消费者——届时本记录作废重审。

> 本决定是对 ADR-001 §5"P4 版本化"的具体落实：版本化 = 显式版本决定 + 消费者清单 + 摘要影响 + 旧运行规则，而非机械升号。ADR 中"P4 版本化"条目据此解释为"v1 内加性演进，决定见本记录"。

## 2. 生产者—消费者清单

### generate-request.segment_refs

| 角色 | 位置 | 职责 |
|---|---|---|
| 生产者 | LLM/用户构造请求；`request_scaffold`（领导调研，当前拒绝段替换） | 提供精确钉住的段引用 |
| 校验 | `SchemaRegistry.validate("generate-request"/"general-generate-request")` | 结构/种类/钉住 |
| 校验 | `GeneralRequestContract.validate_body` | 重复所有权（与 revised_cartography/output_profile/design_variants 冲突）拒绝 |
| 校验 | `ScenarioCapability.validate_suitability`（P3a，compile） | 种类绑定 + 精确钉住 + 能力上下文自洽 |
| 消费者 | `MapCandidateCompiler.load_contracts(segment_refs=)` | 经仓库 fetch_segment 替换 embedded；记录 segment_selection |
| 消费者 | `OwnershipResolver.validate_request_segment_refs` | 可替换权限/种类/钉住 |
| 消费者 | raster/vector `_execution_base` | 写入 execution.template_refs + ownership |
| 一致性门 | `MapCandidateCompiler._require_selection_binding`（check_candidate 内） | execution 引用 == 请求选择 + 安装包装身份；预检/预览/冻结/锁重验共用 |
| 回放者 | preview/freeze/render/check/review/deliver/recovery | 经 _verify_candidate_inputs → check_candidate 重验同一选择 |
| 失败条件 | 缺仓库 SEGMENT_REPOSITORY_REQUIRED；非可替换 SEGMENT_NOT_REPLACEABLE；种类 KIND_BOUNDARY_VIOLATION；未钉住 SEGMENT_REF_UNPINNED；摘要漂移 SEGMENT_DIGEST_MISMATCH/PUBLISHED_PACKAGE_CORRUPT；引用不一致 CANDIDATE_COMPONENT_SELECTION_MISMATCH；所有权 CANDIDATE_COMPONENT_OWNERSHIP_MISMATCH |

### design-revision-proposal.changes.segment_refs

| 角色 | 位置 | 职责 |
|---|---|---|
| 生产者 | 修订提案（LLM/用户） | 整体替换选择（wholesale，非合并） |
| 校验 | Schema changes.segment_refs.new_value | 闭合段词表 + 钉住 |
| 消费者 | `GeneralRevisionContract.rules()` | segment_refs → 失效 plan+compilation；数据证据可复用 |
| 消费者 | `apply_changes`（通用 else 分支） | revised["segment_refs"] = new_value |
| 消费者 | `compute_invalidation` | 未知键拒绝；失效图 |
| 回放者 | revise → compile（重验选择一致性门） | 新 G1/G2 绑定新选择 |

## 3. 摘要影响分析（四类案例）

| 案例 | 是否发生 | 影响 |
|---|---|---|
| 纯代码重构 | 是（P0/P2） | 代码指纹随被改源文件变化；业务合同/有效表达/布局/可见图面等价；旧内部快照按 doctrine 重新准备/编译 |
| 公共协议升级 | 是（segment_refs 加性） | 不含字段的旧请求/提案摘要不变；含字段的新请求摘要自然不同（内容 addressing）。execution 新增 template_refs 段引用 + ownership 段条目 → 仅"有选择"的运行 execution_digest 变化；无选择运行字节一致。锁经 candidate_digest/execution_digest 自动绑定新引用 |
| 策略语义变化 | **否** | 未改 scenario-capabilities.yaml 等任何语义字段；无 steward 触发；profile 目录摘要不变 |
| 仅披露字段变化 | 否 | notice/licenses 未改 |

### 既有冻结执行处置

- 无 segment_refs 的既有运行：execution 形状字节一致，候选/锁/回执摘要不变，可继续。
- 有 segment_refs 的新运行：须由新代码（含 _require_selection_binding 门）准备/审批/编译/冻结；旧代码不识别新字段，不得用于新请求。
- 不自动迁移旧锁；漂移由既有摘要门 + 新选择一致性门拒绝。

## 4. 尚未闭合的协议项（如实列出）

- ADR §5 表中 MapBrief / MapPlan / resolved-* / MapSpecLock 的"组合绑定配套演进"：当前组合身份经 execution.template_refs + ownership + 既有 candidate/scene/lock 摘要链绑定，**未**为这些对象新增独立组合字段或升版。若后续要求 Brief/Plan 显式携带组合选择字段，须另行版本决定并成套交付消费者。
- CapabilityContext 尚未作为公共协议产物持久化（当前为 compile 内部受信快照）；若需跨阶段持久化/回放，须版本化并定义摘要绑定。
- 多候选组合（design_variants + segment_refs）当前拒绝，属 P5；开放时须独立协议演进。