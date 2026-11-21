# Design B：同运行数据修订通道（data-revision）实施方案

- 状态：**M1 完成（2026-11-21）**——Schema/场景合同/内核机制/CLI/协议声明/测试全部落地：
  定向 129 项 + 组件协议 7 项（123 subtests）全绿；**全量回归 732 passed / 7 skipped /
  0 failed**（721 基线 + 11 个新测试，增量完全可归因）。实现期新增：组件协议声明
  `DataRevisionContract`（component_protocols.py，COMPONENT_PROTOCOLS 已注册）——
  修复 ComponentContractTests 四方法的未声明组件失败。
- 日期：2026-11-21
- 前置分析：`doc/leadership-visit-route-revision-plan.md`（新运行通道 e2e 已闭环，
  其产物构成本方案的验收金样）
- 设计定论：同运行 rN 修订（与样式 revise 同构 UX、正式谱系），复用 revise 暂存/
  状态机/预算机制与 compile 重准备分叉

## 〇、实现期设计修正（相对原方案的两处演进，均已测试锁定）

1. **G1D 独立门取消，并入 G1-on-revised-brief**：compile 的门校验消费 rN 修订版
   brief 摘要（`require("G1", …)`），提案式回执会被拒——若保留独立 G1D 用户需签
   两张回执。而数据修订的修订版 brief 在事实产出前就完全可计算（只含前瞻声明，
   pending 形状），故 `data-revision-brief` 直接返回修订版 brief 的 G1 审批对象，
   提案（含 `outbound_declaration`）经 `revision_proposal_ref` 摘要链绑定。
   **结果：零新门语义，原方案的"G1D 教义决策点"消失**，`require_attestation`
   机制未使用，approval-sign 无需新档位。
2. **请求侧变化载体 = `source_ref.digest` 声明升级**：框架产物寻址以请求摘要为键
   （map-document 路径等），请求零变化会与旧设计的 create-once 产物冲突
   （`IMMUTABLE_ARTIFACT_CONFLICT`）；而 goal 注记会漂移意图绑定
   （`MAP_INTENT_INPUT_DRIFT`）。正解：数据修订把 `itinerary_structure.source_ref.digest`
   从前瞻声明（draft 摘要）升级为已绑定事实声明（实际证据摘要）——语义诚实
   （事实已在手并暂存）、产物寻址分离、可被依赖图交叉验证、不触碰 goal/intent。

## 〇、范围裁定（v1）

**v1 只开放腿级路线修订**：`route_legs`（变更腿 + `via_points[]`/`strategy`）——
即 2026-11-21 e2e 验证过的语义。**停靠增删（加地点/改行程结构）列为 v2**：
它牵动 draft 合同与请求前瞻声明 digest 的联动改写（`request_contract` 的
`itinerary_structure.source_ref.digest` 是 draft 摘要，stop 变更 = draft 变更 =
请求声明变更），复杂度不同量级。v1 的请求侧改写仅 `goal` 注记，机械面最小。

## 一、总原则（每条都有源码依据）

1. **词汇在场景、机制在内核**：数据修订词汇经场景合同组件进入（镜像
   `revision_contract` 的 I-5 模式），内核零场景知识——`test_scenario_boundary.py`
   Guard A/B 是硬边界，新增组件不得让内核 import scenarios 或读请求体词汇。
2. **不改既有 GATE 含义**：数据修订门用 `require_attestation`（
   [approvals.py:62-66](skills/carto-agent/scripts/carto_core/workflow/approvals.py#L62-L66)，
   "verify a typed record without reassigning the meaning of a workflow gate"）——
   这正是为"审批一个类型化对象但不占用工作流门语义"预留的机制，**无需新增 GATES 条目**。
3. **digest 门独立复核**：`bundle_input_digest` 只哈希请求键（
   [revision_graph.py:19-21](skills/carto-agent/scripts/carto_core/workflow/revision_graph.py#L19-L21)），
   对"途经点修订请求零变化"的场景是盲的。方案在依赖图新增 `evidence_digest`
   （实际数据文件摘要）字段，`_reusable_bundle` 复用条件三重化——堵死
   "声称改了数据、实际复用旧 bundle"的静默错误。
4. **走 generate-map 子命令**：`data-revision-brief` / `data-revise` 挂在
   generate-map 下（如 `revise`/`revision-brief` 先例），**不新增策略 route**——
   争取零策略语义字段变更（见 §五治理评估）。

## 二、分阶段实施

### Phase 0：词汇与协议（Schema + 场景合同）

**P0-1 新 Schema `skills/carto-agent/schemas/data-revision-proposal.schema.json`**

镜像 `design-revision-proposal.schema.json` 的封闭结构（`additionalProperties: false`，
changes 1-8 键），差异点：

```jsonc
{
  "required": ["schema_version", "proposal_id", "run_id", "parent_revision",
               "changes", "outbound_declaration", "justification"],
  "properties": {
    "changes": {
      "properties": {
        "route_legs": {
          // 每项：leg_id + via_points（坐标数组，geocode 产物）+ strategy?
          // 声明式变更词汇；草案到坐标的转换由宿主在 G1D 后执行
          "type": "array", "minItems": 1,
          "items": { "required": ["leg_id", "via_points"], ... }
        }
      }
    },
    "outbound_declaration": {
      // G1D 审批面的外发材料：新地名（地名+城市）——机械推导自 changes
      // 中以地名表达的途经点；坐标型途经点（既有地点）则为空数组
      "type": "array",
      "items": { "required": ["name", "city"] }
    }
  }
}
```

要点：`outbound_declaration` 是**协议字段**而非宿主日志——G1D 批准面对外发
内容的覆盖从"对话纪律"升级为"摘要绑定"。

**P0-2 场景组件 `scenarios/leadership_visit/data_revision.py`（新文件）**

`RouteDataRevisionContract`，接口与 `REVISION_CONTRACT` 同构：

- `rules()`：`{"route_legs": ("data-evidence",) + _COMPILATION_NODES}` ——
  `data-evidence` 是新保留节点名（见 P1-1）；
- `apply_changes(request, changes)`：v1 仅注记 `goal`（追加修订说明），其余键
  原样返回；未识别键抛 `LEADERSHIP_REVISION_UNKNOWN_KEY`（镜像
  [revision.py:102-104](skills/carto-agent/scripts/carto_core/scenarios/leadership_visit/revision.py#L102-L104)）；
- `expected_outbound(changes)`：供内核在 data-revision-brief 时机械拼 G1D 面。

**P0-3 注册**：`scenarios/leadership_visit/manifest.py` 增
`"data_revision_contract": (_DREV, "DATA_REVISION_CONTRACT")`。
**不进 `scenario_registry.REQUIRED_COMPONENTS`**（
[scenario_registry.py:68](skills/carto-agent/scripts/carto_core/scenario_registry.py#L68)）——
保持可选组件：general-thematic 未提供时经组件查找失败给出
not_implemented 类拒绝（准入语义须按 AGENTS.md 在 capability-roadmap 声明，
见 §五）。

### Phase 1：内核机制（map_generation + revision_graph）

**P1-1 `revision_graph.py` 泛化（两处小改）**

- `compute_invalidation`：删除 `data_evidence_reusable: True` 硬编码
  （[revision_graph.py:38](skills/carto-agent/scripts/carto_core/workflow/revision_graph.py#L38)），
  改为 `"data_evidence_reusable": "data-evidence" not in invalidated`——
  设计修订的规则不含 `data-evidence` 节点，行为逐字节不变（回归锁保护）；
- 新函数 `evidence_digest(evidence_path)`：计算实际数据文件的规范摘要，
  供依赖图新字段 `evidence_digest` 使用。

**P1-2 `map_generation.py` 新增三个方法（镜像 revise 族，约 120 行）**

- `data_revision_documents(request, proposal)`（镜像 `_revision_documents`
  [map_generation.py:983-1002](skills/carto-agent/scripts/carto_core/workflow/map_generation.py#L983-L1002)）：
  校验 `data-revision-proposal` schema、run_id/parent_revision 匹配、合同
  `apply_changes`、重验证 `generate-request`；**额外校验新证据就位**——
  `data/itinerary.json` 存在（MCP 链已跑完，错误文案镜像
  [data_preparer.py:199-207](skills/carto-agent/scripts/carto_core/scenarios/leadership_visit/data_preparer.py#L199-L207)
  的引导式报错）；
- `data_revision_brief()`：返回 G1D 审批对象——
  `approval_object_digest = sha256_digest(proposal + outbound_declaration)`，
  `action: "approve-data-revision"`, `object_type: "data-revision-proposal"`；
- `data_revise()`（镜像 `revise` [map_generation.py:1011-1079](skills/carto-agent/scripts/carto_core/workflow/map_generation.py#L1011-L1079)）：
  ① 门校验用 `require_attestation("approve-data-revision",
  "data-revision-proposal", ...)`（非 `require("G1")`——不重定义门）；
  ② 暂存 `revisions/rN/`：`proposal.yaml` + **证据快照**
  `evidence/itinerary.json`（+ geocode/route 结果副本，见 P2）+
  `request/generate-request.yaml`（goal 注记版）+ `dependency-graph.yaml`
  （含 `evidence_digest` = 快照实际摘要、`data_evidence_reusable: false`）；
  ③ CAS 中断恢复语义镜像既有 `REVISION_STAGING_CONFLICT`
  （[map_generation.py:1023-1024](skills/carto-agent/scripts/carto_core/workflow/map_generation.py#L1023-L1024)）：
  已暂存且 evidence_digest 不同 → 拒绝（防"MCP 重跑后悄悄换数据"）；
  ④ 预算：复用 revisions 计数与中断不重复计费模式
  （[map_generation.py:1026-1031](skills/carto-agent/scripts/carto_core/workflow/map_generation.py#L1026-L1031)）；
  ⑤ 状态迁移 `next_step="compile"`（与 revise 相同落点）。

**P1-3 `_reusable_bundle` 三重门 + compile 漂移校验（两处小改）**

- [map_generation.py:1100-1108](skills/carto-agent/scripts/carto_core/workflow/map_generation.py#L1100-L1108)：
  复用条件在 `data_evidence_reusable` 与 `bundle_input_digest` 之外增加
  `evidence_digest` 匹配（图里无该字段时跳过——设计修订行为不变，向后兼容）；
- compile 的重准备分支前校验：`data/itinerary.json` 实际摘要 == 当前依赖图
  `evidence_digest`，不一致 → 新错误 `DATA_EVIDENCE_DRIFT`——封死
  "data-revise 之后、compile 之前文件再被改"的窗口。

**P1-4 CLI**：`generate_cmd.py` 增两个子命令（镜像
[generate_cmd.py:105-110](skills/carto-agent/scripts/carto_core/cli/generate_cmd.py#L105-L110)
的 revision-brief/revise 接线）+ `tools/host/approval-sign.py` 增 `g1d` 门映射。

### Phase 2：MCP 证据化（itinerary-tools，两方案共享前置）

`itinerary_assemble.py` 扩展：原子写 `data/itinerary.json` 的同时，把
`geocode_result` / `route_result` 两个输入完整快照落
`work/data-evidence/`（含规范摘要），返回值 `evidence` 数组从 2 项变 3 项。
此后"复用未变更腿"的素材是**内核可见的一等证据**（data_revise 把它们一并
暂存进 rN），不再是 `work/host/` 宿主自建目录。

### Phase 3：文档与工作流

- `workflows/generate-map.md`：命令表 + 数据修订条目（pending 语义说明：
  G1D 批计划与外发 → 宿主 MCP → data-revise → compile 重准备 → G2 绑事实）；
- `doc/leadership-visit-usage.md` 与数据准备工作流同步；
- 记忆更新。

## 三、阶段测试

| 阶段 | 测试 | 断言要点 |
|---|---|---|
| **P0** | `schema_cases.py` 增合法/非法样例（镜像 design-revision-proposal 既有样例模式，[test_leadership_visit.py:2146](skills/carto-agent/scripts/tests/test_leadership_visit.py#L2146) 附近） | 合法：route_legs+outbound 完整形状；非法：未知 changes 键、缺 outbound_declaration、via_points 空数组、leg_id 不在当前行程 |
| **P0** | `test_scenario_boundary.py` 全量重跑 | 新组件零内核场景知识：内核不 import scenarios、不出现 route_legs/via_points 字面量（Guard B 词表同步登记禁词） |
| **P1** | `test_revision_graph.py` 增 4 用例 | ① 数据键 → `data_evidence_reusable: false`；② 设计键 → 仍为 true（**回归锁**：旧行为逐字节不变）；③ 未知键拒绝不变；④ `evidence_digest` 计算与内核规范摘要逐字节一致 |
| **P1** | 新 `test_data_revision.py`（内核级，镜像 test_leadership_visit 的合成运行模式） | ① data_revise 暂存后 rN 五件齐（proposal/证据快照/请求/图）；② 门校验：错 action（approve-map-brief 回执）被拒；③ evidence_digest 漂移（暂存后改文件再入）→ STAGING_CONFLICT；④ 中断恢复不重复扣预算；⑤ 状态落 compile；⑥ G2 绑定的 prepared-bundle 反映新数据（数据级 delta：仅变更腿几何不同） |
| **P1** | compile 漂移校验专用用例 | data-revise 后改 `data/itinerary.json` → compile 报 `DATA_EVIDENCE_DRIFT` 且不产出 |
| **P2** | `test_itinerary_assemble.py` 增 2 用例 | ① evidence 三件落盘且摘要正确；② 金样锁定：既有 e2e 夹具的 evidence 摘要与内核摘要等价 |
| **P3** | **端到端金样验收（最强锚点）** | 用 2026-11-21 e2e 同一输入（leg-01 途经紫金港）走 data-revision 通道：新预览的 map-document 与 run-20261121081928 做 T-B4 同口径数据级 delta（仅 leg-01 几何不同、停靠全同）——**协议化通道与人工宿主编排产出等价** |
| **P3** | 全量回归 + 四棘轮（boundary/layer_ports/encapsulation/digest_coverage） | 721 基线只增不减；`compute_invalidation` 设计路径回归是重点盯防对象 |

## 四、治理影响评估

| 项 | 影响 | 依据/处置 |
|---|---|---|
| 策略语义字段（scenario-capabilities routes/request_schemas） | **争取零变更**——子命令挂 generate-map 下，不加 route | `revise`/`revision-brief` 先例：未加 route 未加 request_schema |
| capability-roadmap not_implemented 声明 | 可能需加一条（general-thematic 未提供 data_revision_contract 时的拒绝类） | 须 steward 确认该条目是否属语义字段；若是，走漂移评审 |
| 内核代码指纹 | map_generation/revision_graph/approvals CLI 变化 → 旧快照按现行 doctrine 重准备 | 既有规则，不自动迁移 |
| 协议三件套 | 合法/非法样例 + 自动测试（§三已列） | AGENTS.md 硬性要求 |
| 审批语义决策 | G1D = 计划+外发批准，事实绑定后置 G2 | pending 首跑同构先例；**须 steward 拍板确认**（本方案唯一教义决策点） |

## 五、风险表（按严重度）

| # | 风险 | 缓解 |
|---|---|---|
| 1 | digest 门盲区（请求零变化型数据修订被静默复用旧 bundle） | `evidence_digest` 三重门 + compile 漂移校验（P1-3）——本方案最核心的正确性设计 |
| 2 | `compute_invalidation` 泛化破坏设计修订回归 | 回归锁用例（§三 P1-②）+ 全量基线盯防 |
| 3 | MCP 非确定性破坏 rN 重放 | 证据快照冻结进 rN（Amap 结果变更不影响已批准修订的重放） |
| 4 | 歧义环（geocode needs_input 交互） | v1 约束：坐标型 via_points 或既有地点；新地名经 outbound_declaration 声明、确认结果随证据快照冻结 |
| 5 | 场景边界泄漏（内核出现腿词汇） | Guard B 禁词登记 + boundary 棘轮 |
| 6 | stop 增删需求提前涌入 | v1 范围裁定（§〇），v2 另立方案 |
| 7 | 治理评审成本被低估 | §四逐项列明；steward 两个决策点（G1D 教义 + roadmap 条目）前置确认后再动工 |

## 六、工作量估计

| 模块 | 规模 | 备注 |
|---|---|---|
| Schema + 场景合同 + 注册 | 小（~200 行含测试） | 镜像既有合同模式 |
| revision_graph 泛化 | 极小（~15 行） | 两函数 |
| map_generation 三方法 + 三重门 | 中（~150 行） | 复用暂存/预算/状态机 |
| CLI + approval-sign | 小（~40 行） | 镜像接线 |
| itinerary_assemble 证据化 | 小（~60 行） | 原子写扩展 |
| 测试全套 | 中（~400 行） | §三清单 |
| **合计** | **约 900 行（含测试）** | 无架构性新建，全部镜像既有模式 |

## 七、执行顺序与里程碑

1. **M1（P0+P1 内核）✅ 完成（2026-11-21）**：schema + 合同 + 泛化 + data_revise 机制
   + CLI；定向测试 129 项全绿（含 7 个数据修订 e2e：主链路/错门拒绝/漂移拒绝/
   CAS 冲突与恢复/证据缺失/未知腿拒绝）；全量回归见收尾记录；
2. **M2（P2 证据化）→ 推迟（范围裁定）**：内核通道的审计/重放由 rN 证据快照
   （itinerary.json + `evidence_digest`）完整覆盖；MCP 中间结果（geocode/route
   原始输出）只服务宿主增量复用便利，且 MCP 工具不感知内核 workdir（落盘位置
   存在接线难题）。宿主侧沿用 `work/host/route-revision/` 固化模式（route-revision
   e2e 已验证）。待真实需求出现再立项；
3. **M3（P3 金样验收）✅ 完成（2026-11-21）**：真实项目
   `leadership-e2e-2/run-20261121110148`（未冻结基线，零外部调用——复用既有
   v0/r1 证据）→ `data-revision-brief`（r2，G1 `6299f927…`）→ 换 r1 证据 →
   `data-revise`（证据 `9a49ad0d…` 冻结于 r2）→ compile 重准备 → preview →
   G2（`80b65194…`）→ freeze。**金样比对：r2 预览的 11 条折线与 6 个停靠点
   与新运行通道金样（run-20261121081928）逐字节一致——两通道对同一修改请求
   产出数据级等价结果**。执行顺序教训（已修入工作流 §4a）：brief 必须在换证据
   之后调用（`source_ref.digest` 绑定实际事实，顺序错了 G1 校验
   `APPROVAL_OBJECT_MISMATCH` 拒绝——这是摘要绑定对执行顺序的强制）。
