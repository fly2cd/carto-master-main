# 领导调研用图 — 行程准备工具链补全方案

> 状态：**已批准实施**（2026-11-20）。前置：全链路 CLI E2E 已跑通
> （`doc/leadership-visit-e2e-plan.md`）；本方案解决"宿主现场即兴脚本"的职责错位。
> 设计依据：`doc/design-principles.md` 四层边界 + 场景边界棘轮 + 宿主薄化 +
> "仅能力语义进网关"的 ToolGateway 分层（详见方案正文三决策）。

## 0. 目标形态

```
用户放 DOCX → 宿主读摘要、写 data/itinerary-draft.json（唯一语义产物）
→ itinerary.check（校验→反馈→修正）→ request.scaffold（摘要+请求骨架）
→ generate-map intake → brief → [G1 用户批准]
→ geocode（歧义→用户确认）→ plan_route
→ itinerary.assemble（合并→校验→原子落盘+证据）
→ compile → preview → [G2] → freeze → render → check → review → [G3] → deliver
```

宿主全程只产出语义文件（draft）+ 调工具 + 4 个人机确认点。零组装、零摘要计算、零临时脚本。

## 1. 三个架构决策

1. **服务工具是"语义反馈层"，不是"权威校验层"**：权威在内核（intake 封闭
   Schema / compile 的 `data_preparer._from_contract` / G2 摘要绑定）。服务
   check/assemble 只做早期反馈与机械合并，允许有限重叠不产生双权威；服务保持
   `httpx+mcp` 零内核依赖。
2. **全部无状态**：不恢复旧框架修订状态机——防漂移已由内核 G2
   prepared-data-bundle 承担（"新框架已有逐行等价物"原则的延伸）。
3. **场景领域知识放服务合法**：场景边界棘轮只约束内核；services/ 是场景领域
   服务指定位置。

## 2. 四类工具安置拓扑（终态）

```
内核调用（执行链内，摘要绑定留证据）──── adapters/ + ToolGateway（不动）
宿主调用·领域确定性·零内核依赖 ──────── services/itinerary-tools（MCP，本方案扩展）
宿主/审批方调用·权威工具·复用内核加密 ─ skills/carto-agent/tools/host/
机器/项目事实 ────────────────────────── 项目目录 README + 密钥文件
```

- `approval-sign.py` 迁入 `tools/host/`（SKILL.md 已有该目录约定：宿主工具住
  此、只被显式执行）。理由：签名权威必须在内核外（D1）；必须 import 内核
  `sign_receipt` 保证与验签逐字节一致（无平行加密实现），故不能进零内核依赖的
  MCP 服务。权威 = 密钥持有 ≠ 脚本持有（负向测试已证）。随技能入库过
  steward 评审。
- 密钥仍在各项目目录（`--key-file` / 环境变量），工具与密钥分离。

## 3. 修改清单

### A. services/itinerary-tools 新增三工具

**A1 `itinerary_check.py`**：`itinerary_check(arguments, ctx) -> dict`
输入 `{draft_path, expected_digest?}`；输出 `{status: complete|invalid,
report{errors[{code,path,message}],warnings,summary}, draft_digest}`。
校验规则（内核将强制项的提前反馈）：
draft JSON 可解析（带行列号）；places 非空/place_id 唯一/name+geocoding_query；
stops 非空/stop_id 唯一/place_id∈places；activity type∈8 枚举/period∈2 枚举；
travel 腿端点∈stops、stay 腿同 place；route_mode∈4/metric_source∈3/
document_metrics 数值；链连通（warning）；expected_digest 漂移（error）；
place 已含 location（warning）。错误码 `ITINERARY_*`。

**A2 `itinerary_assemble.py`**：`itinerary_assemble(arguments, ctx) -> dict`
输入 `{draft_path, geocode_result, route_result, output_path?}`；输出
`{status: assembled, output_path, output_digest, counts, evidence[]}`。
逻辑：复用 check 校验 draft（须 complete）→ geocode_result 须 complete 且
draft 每个 place_id 有坐标（`ITINERARY_LOCATION_UNRESOLVED` 点名缺项）→
route_result 每条 travel 腿 complete 且 geometry≥2 折点 → deepcopy 合并
（place.location / leg.geometry+routing_metrics，stay 腿不动）→ 临时文件
+os.replace 原子写 → 输出与 draft 同路径拒绝（`ITINERARY_OUTPUT_COLLISION`）。
内联传参（route ~68KB 已实测 MCP 可承载）；`output_path` 参数位留文件式演进。

**A3 `request_scaffold.py`**：`request_scaffold(arguments, ctx) -> dict`
输入 `{draft_path, project_id, request_id?, run_id?, idempotency_key?,
tenant_id, subject_id, approver_subject_id, basemap_path?,
registration_path?, font_path?, font_family?, template_repo_path?, requested_at?}`。
逻辑：读 `<template_repo>/template-index.yaml` 取 published 的
leadership-visit-map 条目 digest（多版本取最高）→ 三类摘要（draft/registration
用规范 JSON 摘要=内核 `sha256_digest` 逐字节等价物；basemap 用原始字节
sha256；registration 以 JSON 解析）→ 按已两次 E2E 验证的固定模板
（pending/preparation/前瞻 digest/7 field_bindings/A3@200dpi/4 capabilities）
原子写 generate-request.yaml。advisory 定位：权威裁决在 intake 封闭 Schema；
`requested_at` 参数化供确定性测试。

### B. server.py 接线

工具函数签名统一 `f(arguments, ctx)`（ctx={allowed_root}；geocode/plan_route
忽略）；新增 `resolve_under_root(path, root, must_exist)` 路径守卫
（`PATH_OUTSIDE_ROOT`/`PATH_NOT_FOUND`）——`--allowed-root` 从摆设变真实边界；
list_tools 注册 3 工具（**完整类型化 inputSchema**——阶段 0 教训：属性类型
必须声明，否则宿主字符串化）；call_tool 分派表 +3。

### C. 协议合规（schemas/ + tests/，现空壳）

schemas/：`itinerary-draft-contract.schema.json` + 三工具的 request/response
Schema 对（Draft 2020-12）。
tests/（自包含、不 import carto_core、pytest 直跑）：
`test_itinerary_check.py`（真实 draft 金样→complete；8 非法样例各触发错误码
且 path 正确；漂移）；`test_itinerary_assemble.py`（真实 E2E 的
geocode/route 金样合并 → 输出与 `leadership-e2e/data/itinerary.json`
**逐字节一致**；缺坐标/缺折线/输出碰撞；原子性）；
`test_request_scaffold.py`（固定 requested_at + 身份 → 金样请求逐字段一致；
三类 digest 与已知值一致；模板索引缺条目报错）；`test_pathguard.py`。
金样取自 E2E 真实产物——把跑通事实固化为回归锚点。

### D. 配置与文档

- `.mcp.json`：`--allowed-root` → `D:/workspace/project_1/IGSA_1118`（父目录
  覆盖所有项目免重连；三新工具读写项目文件使授权首次有实际意义；让渡最小根
  到兄弟目录，单用户可接受，注释说明）。
- data-prep 手册：§二 两工具→五工具；§三 宿主职责改"写 draft → check →
  scaffold → 调 MCP → assemble"（删"手工组装"）；§四 保留（LLM 提取规范）；
  §六 追加 assemble 用法、删一次性脚本约定。
- usage doc §一：五工具序列。
- SKILL.md leadership 条目：两工具→行程准备工具链（**解冻 SKILL.md**，随
  Phase 7 steward 评审）。
- `leadership-e2e/README.md`：工具段改为仓库 tools/host 引用；删除
  approval-sign 散装副本（两处 e2e 目录）。
- `approval-sign.py` → `skills/carto-agent/tools/host/approval-sign.py`。

### 不动清单

carto_core 内核、scenarios/、adapters/、tool-bindings.yaml（非内核网关能力、
非场景内核组件）；审批流与 4 个人机确认点；D1 两层纪律。

## 4. 验收标准

1. 三新工具测试全绿（金样逐字节锚点）；
2. 新会话重跑完整 E2E：除 draft 外宿主零文件产出、零临时脚本（成败判据）；
3. 内核全量回归不变（684/7/0；服务测试单独 `pytest services/itinerary-tools/tests`）；
4. 手册与实现一致。

## 5. 风险与缓解

| 风险 | 缓解 |
|---|---|
| 服务模板/校验与内核 Schema 漂移 | advisory 定位 + 金样测试 + 手册明示；演进位=服务直读仓库 Schema |
| 规范 JSON 摘要两侧不一致 | 金样用真实材料锁死摘要值，不一致立即在测试暴露 |
| assemble 内联大参数 | 68KB 已实测；output_path 留演进位 |
| SKILL.md 解冻 | 纳入 Phase 7 评审批次 |

## 6. 实施顺序

A1→A2→A3（工具+测试同步）→ B 接线 → C 金样固化 → D 文档/迁移/配置 →
新会话 E2E 验收。
