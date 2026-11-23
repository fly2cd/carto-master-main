# 宿主零脚本制图接入方案（itinerary-tools + skill 手册）

> 制定：2026-11-22。目标：`skills/carto-agent`（SKILL.md + workflows 手册）与 `services/itinerary-tools`（MCP 服务）加载到**任意宿主智能体**后，从三件套材料到交付包全程**宿主零自编程序**。
> 本方案不改动内核（carto_core）与策略语义字段，不触发 steward digest 轨道。

---

## 0. 目标与验收判据

**宿主四能力假设**（文档化为"宿主接入契约"，见 §4）：
① 执行 shell 命令（调唯一 CLI 与 `tools/host/approval-sign.py`）；② MCP 客户端（消费类型化工具）；③ 文件读写（撰写 `itinerary-draft.json` 等语义文件、摆放材料）；④ 用户交互（地名歧义确认、T1/G1/G2/G3 审批呈请）。

在此假设下，以下判据全部可判定地通过即验收：

| # | 判据 |
|---|---|
| A1 | 新宿主仅凭仓库 + 材料走完 `材料摆放 → data summarize → draft → check → scaffold → intake → brief → G1 → geocode → plan_route → assemble → compile → preview → G2 → freeze → render → check → review → G3 → deliver`，**全程不编写任何程序**（shell 命令、MCP 调用、draft JSON 撰写、回执签发调用不算程序） |
| A2 | 增量修订（改线/途经点）同样零脚本：`plan_route(仅变更腿, base_result_ref) → assemble(引用)` |
| A3 | 直线/退化路由结果**不可能**以 `complete` 状态存活到 `data/itinerary.json`（三层门禁 + 负向测试证明） |
| A4 | 协议等价性金样：同一输入下，内联组装与引用组装产出的 `data/itinerary.json` **逐字节一致** |
| A5 | `services/itinerary-tools` 全测试绿（含新增用例）；全仓回归零新增失败；`scenario-capabilities.yaml`、`tool-bindings.yaml` 与内核工作流/策略语义零改动（唯一例外：CLI 入口 stdout UTF-8 锁定，见 CS-3 代码项，合计 ≤12 行、不触碰工作流逻辑） |
| A6 | 在中文 Windows（cp936 管道/重定向）下，`carto.py` 与 `approval-sign.py` 的 stdout 机器输出**逐字节为 UTF-8**，宿主不带 `-X utf8` 直接解析成功（2026-11-21 会话已实证：带 `-X utf8` 的调用全部干净，未带的 `approval-sign.py` 即乱码） |

## 1. 现状缺口（2026-11-21 Desktop/test 全链路运行实证）

1. **宿主被迫当数据总线**：`itinerary_assemble` 的 `route_result` 只接受内联对象（[itinerary-assemble-request.schema.json](../services/itinerary-tools/schemas/itinerary-assemble-request.schema.json)，无引用形式）。75KB 级道路折线无法经 LLM 上下文逐字节重述 → 宿主写脚本直调工具函数（两次）；LLM 转抄存在字节失真风险且框架无法验证"传入结果 ≡ plan_route 产出"。
2. **回退契约三层失守**：`allow_straight_line=false` 时直线结果仍可达落盘——[router_amap.py:199](../services/itinerary-tools/routing/router_amap.py#L199)（Amap 内部直线回退，key 缺失时静默）、[plan_route.py:63-88](../services/itinerary-tools/plan_route.py#L63-L88)（flag 只管自构造回退，不管引擎吐回的）、[itinerary_assemble.py](../services/itinerary-tools/itinerary_assemble.py)（只查 LineString≥2 点）。本次实测：shell 缺 `CARTO_AMAP_KEY` → leg-01 降级为 2 点 0km 直线并**以 complete 落盘污染证据**。
3. **工具 schema 类型不全**：`server.py` 的 `_PLAN_ROUTE_SCHEMA.via_points` 是无类型数组（`{"type":"array"}`）——与已修复的宿主字符串化 bug 同类隐患。
4. **输入合同含混**：旧框架 `transform.json` 与五字段 `registration.yaml` 的关系只活在宿主经验里。**本方案定案（用户决策）**：输入合同 = 底图 PNG + **五字段 registration.yaml（用户直供）** + 行程 DOCX；`transform.json` 退出输入合同，五字段抽取属旧材料迁移，不再由框架/宿主承担。

## 2. 变更集 CS-1：路由回退契约修复（预估 0.5 天）

### 改动

| 文件 | 改动 |
|---|---|
| `services/itinerary-tools/routing/router_amap.py` | ① `__init__` 处 key 为空 → 首次调用时抛 `AMAP_KEY_MISSING`（命名错误，不静默）；② 删除 [line 199](../services/itinerary-tools/routing/router_amap.py#L199) 起的内部直线回退——请求失败抛 `AMAP_REQUEST_FAILED`，不构造 `engine: straight_line` 结果 |
| `services/itinerary-tools/routing/route_engine.py` | [line 145-149](../services/itinerary-tools/routing/route_engine.py#L145-L149) `not allow_online` 分支的直线返回加 `degraded: true` 标记（保留但可辨识） |
| `services/itinerary-tools/plan_route.py` | 结果落袋前统一门禁：某腿 `engine == "straight_line"` 且 `allow_straight_line` 为 False → 该腿 `status: "failed"`，`message` 透传根因链（dual_graph 失败原因 + Plan B 失败原因，不允许吞） |
| `services/itinerary-tools/itinerary_assemble.py` | travel 腿校验段新增两道：① `engine == "straight_line"` 且草稿 `route_mode != "straight_line"` → `ROUTE_ENGINE_DEGRADED` 拒绝（草稿显式声明 `route_mode: straight_line` 的腿是合法直线，放行）；② travel 腿 `distance_km` 缺失/为 0 → `ROUTE_METRICS_INVALID` 拒绝 |
| `services/itinerary-tools/server.py` | `_PLAN_ROUTE_SCHEMA` 的 `via_points` 补全 items 类型（对象 + lon/lat number，对齐 route_engine 已支持的 name-only 形态） |

### 测试（新增 `tests/test_plan_route.py`——该文件此前不存在）

1. 清空 `CARTO_AMAP_KEY` + via 腿 → 腿 `status: failed` 且 message 含 `AMAP_KEY_MISSING`（复现本次事故的负向用例）；
2. `allow_straight_line=False` + 引擎返回直线（mock）→ 腿 failed；
3. `allow_straight_line=True` → 直线放行（正向）；
4. assemble：喂 2 点 0km "complete" 结果 → `ROUTE_ENGINE_DEGRADED` / `ROUTE_METRICS_INVALID` 拒绝、不落盘；
5. assemble：草稿 `route_mode: straight_line` + 直线结果 → 放行。

## 3. 变更集 CS-2：结果引用协议（预估 1–1.5 天，核心）

**设计依据**：MCP 服务无状态 ⇒ 结果字节只在 `plan_route` 执行那一刻存在于服务端——**持久化必须发生在 plan_route 内部**，任何"事后保存工具"都要求宿主再内联一次大对象（等于没修）。

### 3.1 协议形状

```jsonc
// plan_route 输出（向后兼容：内联 results 保留）
{
  "status": "complete",
  "results": [ /* 每腿 {leg_id, status, geometry, distance_km, duration_min, engine} */ ],
  "result_ref": {                          // 新增：服务端落盘凭证
    "uri": "route-results/plan-20261122T093000Z-5legs.json",
    "digest": "sha256:..."                 // 文件字节摘要（与底图 digest 同约定）
  }
}

// plan_route 输入新增（均可选）
{
  "legs": [ /* 只传变更腿 */ ],
  "base_result_ref": { "uri": "...", "digest": "sha256:..." }
  // 服务端：加载 base → raw_file_digest 复算 == 声明（不符→ROUTE_RESULT_DIGEST_MISMATCH）
  //        → base 中与本次请求同 leg_id 的腿被重路由替换，其余腿从文件原样搬运
  //        → 合并结果落盘 → 返回新 result_ref
}

// itinerary_assemble 输入改为二选一
{
  "draft_path": "data/itinerary-draft.json",
  "geocode_result": { /* 保持内联：约 1KB，无需引用 */ },
  "route_result": { ... },                                   // 路线 A：内联（兼容既有调用/测试）
  "route_result_ref": { "uri": "...", "digest": "sha256:..." } // 路线 B：引用
}
// 两样都传 → INPUT_CONFLICT；引用先复算文件字节摘要，不符 → ROUTE_RESULT_DIGEST_MISMATCH
```

### 3.2 改动

| 文件 | 改动 |
|---|---|
| `services/itinerary-tools/plan_route.py` | ① 结果原子写 `route-results/plan-<UTC时间戳>-<N>legs.json`（`resolve_under_root` 约束于 allowed_root，`atomic_write_text` 复用）；② `base_result_ref` 加载/校验/合并逻辑；③ 返回 `result_ref` |
| `services/itinerary-tools/itinerary_assemble.py` | `route_result` / `route_result_ref` 二选一分支 + 字节摘要校验；其余校验管线不变 |
| `services/itinerary-tools/schemas/` | 新增 `plan-route-request.schema.json`、`plan-route-response.schema.json`（含 `result_ref`）；`itinerary-assemble-request.schema.json` 加 oneOf 分支。**全部字段类型化声明**（含 items）——无类型数组会被宿主字符串化（既有教训） |
| `services/itinerary-tools/server.py` | 两工具 inputSchema 同步新字段（带类型）；工具描述更新 |

### 3.3 兼容性

- 内联路径保留：既有调用方与全部既有测试不动即绿；
- `data/itinerary.json` 输出格式与摘要计算方式**零变化**（A4 金样证明）；
- 未变更腿从持久化文件原样搬运 ⇒ **字节级复用，不重路由**——顺带消除 Amap 在线非确定性对"复用"的破坏。

### 3.4 测试（金样锁定，仿 `test_itinerary_assemble.py` 既有模式）

1. **协议等价**：同一 draft + geocode + 路由结果，内联 vs 引用两条路 → `data/itinerary.json` 逐字节相同；
2. **增量合并**：`base_result_ref` + 仅变更腿 → 合并结果中未变更腿与全量结果**逐腿数据等同**（"只有该变的变了"）；
3. **摘要防篡改**：引用文件被改一字节 → `ROUTE_RESULT_DIGEST_MISMATCH`；
4. **输入冲突**：`route_result` 与 `route_result_ref` 同传 → `INPUT_CONFLICT`；
5. base 引用路径越界/不存在 → 既有 `PATH_OUTSIDE_ROOT` / `PATH_NOT_FOUND`；
6. 落盘文件在 allowed_root 之外不可达（PathGuard 负向）。

## 4. 变更集 CS-3：宿主接入契约文档化（预估 0.5 天）

| 文件 | 改动 |
|---|---|
| [skills/carto-agent/workflows/generate-map/leadership-visit-data-prep.md](../skills/carto-agent/workflows/generate-map/leadership-visit-data-prep.md) | §一：输入合同改为"底图 PNG + **五字段 registration.yaml（直供）** + DOCX"，删除 transform.json 相关叙述；§二：两工具 I/O 更新（`result_ref`/`base_result_ref`、回退契约语义、**错误码表**——ServiceError 全枚举及宿主应对）；§三：宿主步骤收敛为"传引用 + 语义确认"；§六：增量重跑简化为 `plan_route(变更腿, base_ref) → assemble(ref)`；§七：删除"宿主不写组装脚本"的例外辩解，改为可遵守的事实陈述；**新增"宿主接入契约"一节**：四能力清单、`.mcp.json` 模板（含 `--allowed-root` 约定 = 项目根）、密钥约定（`.approval-key`/`.attestation-key` 项目内文件 + `.mcp.json` env 的 AMAP/TIANDITU key）、材料摆放清单 |
| `skills/carto-agent/SKILL.md` | `leadership_visit` 段工具链描述同步（I/O 演进，非策略语义，不触发 digest 轨道） |

### CS-3 代码项：CLI 入口 stdout UTF-8 锁定（≤12 行，2026-11-22 定案并入）

根因：`carto.py` 入口无任何编码处理（[carto.py](../skills/carto-agent/scripts/carto.py) 全文 4 行），中文 Windows 下 stdout 被管道捕获时 Python 默认 cp936(GBK)，UTF-8 JSON 被重编码 → 宿主按 UTF-8 读取即乱码（手册 §七.1 已登记）。

| 文件 | 改动 |
|---|---|
| `skills/carto-agent/scripts/carto.py` | 入口处 `sys.stdout`/`sys.stderr` `reconfigure(encoding="utf-8")`（流存在性判空后执行）——此后无论宿主是否带 `-X utf8`、何种平台/代码页，机器输出恒为 UTF-8 字节 |
| `skills/carto-agent/tools/host/approval-sign.py` | 同样处理（2026-11-21 会话实证其未带 `-X utf8` 时即乱码） |

- 调用层 `python -X utf8` 作为**过渡性双保险**写入宿主接入契约（`.mcp.json` 对 MCP 服务已有先例）；入口层落地后不依赖宿主纪律；
- 交互式控制台人读中文需 `chcp 65001` / Windows Terminal——stdout JSON 的受众是宿主不是人，属可接受代价；
- 验证：以 `PYTHONIOENCODING=gbk` 子进程调用 `carto.py schema check`，断言输出按 UTF-8 解码且含完整 JSON（判据 A6）；跑全量回归兜底（测试 stdout 捕获不受影响）；
- 结构层 `--json-out`（协议与日志彻底分离）**仍留 §7**，此项不替代它，只消除编码维度脆弱性。

## 5. 实施顺序

```
CS-1（回退契约）→ CS-1 测试绿
  → CS-2（引用协议）→ CS-2 金样绿
    → CS-3（文档）→ 全量回归
      → 终验（§0 判据 A1–A5）
```

变更集相互独立、可单独回退；CS-2 依赖 CS-1 的错误码语义（`AMAP_KEY_MISSING` 等会出现在合并结果 message 里）。

## 6. 边界与治理

- **零内核改动**：不触碰 `carto_core/`、`scenario-capabilities.yaml`、`tool-bindings.yaml`、Schema 目录（`skills/carto-agent/schemas/`）——MCP 服务是 advisory 层，本就是"宿主调领域工具"职责区；
- 服务保持**零 `carto_core` import** 与单一 MCP 入口（既有边界测试继续覆盖）；
- 棘轮测试（`test_image_tool_boundary` 等）只紧不松、全绿；
- 新协议按仓库纪律配**合法/非法样例 + 自动测试**（§3.4 即非法样例集）。

## 7. 明确不在本期（含触发条件）

| 项 | 理由 | 再触发条件 |
|---|---|---|
| P1 预算治理（elapsed 排除门等待 / budget extend 回执 / max_revisions 入 profile） | **默认值已调宽**（2026-11-22：max_revisions 2→3、max_elapsed_seconds 600→1200，用户决策）；治理重设计（门等待豁免/延期回执/profile 化）仍搁置 | 再次发生人工门等待导致超时，或需要预算变更审计 |
| prepare_project 工具 | 用户直供五字段 registration.yaml 后，项目初始化只剩文件摆放（非程序） | 材料来自无 registration 的新管线 |
| CLI `--json-out` 机器可读输出 | 编码维度已由 CS-3 代码项（入口 UTF-8 锁定）消除；剩余为"日志混入 stdout 致管道解析失败"的结构问题，需内核侧改动 + steward 轨道 | 渲染日志较长步骤的管道解析失败复现 |
| MCP 多 allowed-root / geocode 结果持久化 | 单根约定 + 项目根即 MCP 根已文档化；geocode 结果约 1KB 内联无压力 | 频繁跨项目复用 / 跨会话确认复用需求 |

## 8. 验收清单

- [x] CS-1：`tests/test_plan_route.py` 新增 ≥5 用例全绿；assemble 拒绝用例全绿（2026-11-22 完成：7 + 3 用例，服务套件 56 passed；真实事故复现——无 key + via 腿 → leg failed、message 含 AMAP_KEY_MISSING 与 dual_graph 根因链，无直线降级、无落盘；全仓回归 732 passed / 7 skipped / 0 失败）
- [x] CS-2：协议等价金样（A4）逐字节一致；增量合并金样；防篡改/冲突/越界负向全绿（2026-11-22 完成：服务套件 66 passed（新增 10）；**真实链路验证**——真实 dual-graph 路由 5 腿 → `route-results/` 落盘 + result_ref 摘要校验 → 引用组装输出与 E2E 金样 `expected-itinerary.json` 逐字节一致；合并金样证明只有变更腿变化（leg-01 == revised fixture，其余腿 verbatim 搬运））
- [ ] `services/itinerary-tools` 原有测试零回归
- [ ] 全仓 pytest 零新增失败（预期不受影响，兜底跑一遍）
- [x] CS-3 手册改写完成，错误码表与宿主契约入册（2026-11-22：§一五字段输入合同/§二六工具+错误码表/§三引用传递/§五约束8/§六服务端增量合并/§七编码已修+宿主不写程序/新增§八宿主接入契约；SKILL.md leadership_visit 段同步）
- [x] CS-3 代码项：`PYTHONIOENCODING=gbk` 子进程验证 `carto.py` / `approval-sign.py` 输出逐字节 UTF-8（A6，严格解码通过、中文完整）；全量回归 732 passed / 7 skipped / 0 失败
- [x] 终验：新会话宿主按手册从三件套走全链路 + 一次增量改线，全程零自编程序（A1/A2）（2026-11-22 Desktop/test2 实测闭环：run-202611221535，r2 数据修订 leg-01 途经紫金港，交付 delivery/leadership-test2-r2 五件套 checksums OK、committed；正式产物与已确认预览逐字节一致；A6 野外实证——不带 -X utf8 管道直读干净。备注：①半冷启动口径——草稿复用既往批次、读了记忆/既往产物，从零撰写 draft 路径未覆盖；②dual-graph 跨进程非确定性实测存在（同进程确定），base_result_ref verbatim 搬运已使其无害化，根因待查；③预算 600s 擦线通过（约 8 分钟），P1 搁置项风险仍在）
