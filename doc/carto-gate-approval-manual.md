# generate-map 审批门禁操作手册（G1 / G2 / G3）

本手册面向 **操作者（operator）** 与 **独立审批人（approver）**，说明地图生成流程 `generate-map` 中三个需要人工确认的门禁（Gate）的确认对象、确认形式、签发方法与消费命令。

> 运行时只读取 Skill 内协议、策略与项目产物，不读取本文件；本文件是人读操作指南。机器协议以 `skills/carto-agent/schemas/` 与 `skills/carto-agent/workflows/` 为准。

---

## 1. 角色与职责

| 角色 | 身份字段 | 职责 |
|---|---|---|
| 操作者 / 请求发起人 | `subject.subject_id`（例 `operator-one`） | 准备请求与数据、逐步运行 CLI、把待确认对象与摘要交给审批人 |
| 独立审批人 | `subject.approver_subject_id`（例 `reviewer-one`） | 审阅对象、用 HMAC 密钥签发审批回执（ApprovalReceipt） |
| 宿主 Agent | — | **无权自签审批回执**；遇到 `compile / freeze / deliver` 必须停下来向审批人索取回执 |

**硬性约束**：审批人 `subject_id` 必须等于请求里的 `approver_subject_id`，且**不得**等于发起人。三个 Gate 各自独立绑定，不能跨 Gate / 跨对象 / 跨运行复用同一张回执。

---

## 2. 前置条件

### 2.1 密钥（环境变量）

| 变量 | 用途 | 要求 |
|---|---|---|
| `CARTO_APPROVAL_HMAC_KEY` | 审批回执签名 / 验签 | **≥ 32 字节**，否则报 `APPROVAL_KEY_WEAK` |
| `CARTO_RENDER_ATTESTATION_KEY` | 渲染回执签名（preview / freeze / render / check 需要） | 由受控渲染器使用 |

PowerShell 设置示例（当前会话有效）：

```powershell
$env:CARTO_APPROVAL_HMAC_KEY     = "<至少32字节的密钥>"
$env:CARTO_RENDER_ATTESTATION_KEY = "<至少32字节的密钥>"
```

### 2.2 路径约定（全绝对路径）

| 记号 | 含义 | 对应参数 |
|---|---|---|
| `$PS` | 项目空间（允许根） | `--allowed-root` |
| `$PR` | 项目根 | `--project-root` / `--allowed-root` |
| `$RUN` | generate-map 运行目录 | `--workdir`（相对按 `$PR` 解析） |
| `$REPO` | 共享不可变模板仓库根 | `--repository-root` |
| `$APP` | 审批目录（存放回执与 nonce 库） | `--approval` / `--nonce-db` |

CLI 入口：`python skills/carto-agent/scripts/carto.py`（安装后为 `carto`）。PowerShell 不支持 `&&`，多命令请用 `;` 分隔。

### 2.3 运行前提

`$REPO` 内必须已有 `generate-map` 要引用的**已发布模板**（例 `urban-flood-risk/1.0.0`）。模板由 `create-template ... publish` 写入，本手册不覆盖模板创建。

---

## 3. 三个 Gate 一览

| Gate | 等待点（步骤后进入 `waiting_approval`） | 消费步骤 | `action` | `object_type` | 确认对象 | `object_digest` 来源 |
|---|---|---|---|---|---|---|
| **G1** | `brief` | `compile` | `approve-map-brief` | `map-brief` | 地图简报（用途/受众/数据访问计划/输出目标/精确模板引用/允许能力） | `brief` 步骤输出 JSON 的 `.approval_object_digest` |
| **G2** | `preview` | `freeze` | `approve-freeze` | `resolved-map` | 预览通过的地图候选 + 预览证据 | `preview` 步骤输出 JSON 的 `.approval_object_digest` |
| **G3** | `check` | `deliver` | `approve-delivery` | `delivery-manifest` | 最终交付清单（成品+摘要/接收方/目的地/许可与限制） | `check` 步骤输出 JSON 的 `.g3.object_digest` |

流程与门禁位置：

```
intake → brief →[G1]→ compile → preview →[G2]→ freeze → render → check →[G3]→ deliver
```

---

## 4. 审批回执（ApprovalReceipt）统一格式

三个 Gate 的确认形式**完全一致**：一份符合 `approval-receipt.schema.json` 的 YAML/JSON，用 HMAC-SHA256 签名。字段如下：

| 字段 | 说明 | 示例 |
|---|---|---|
| `schema_version` | 固定 `1` | `1` |
| `receipt_id` | 回执唯一标识 | `approval-g1-run-flood-001` |
| `issuer` | 签发方，须与步骤 `--issuer` 一致 | `trusted-local` |
| `subject_id` | **审批人**身份，须等于 `approver_subject_id` | `reviewer-one` |
| `tenant_id` | 租户，须与请求一致 | `tenant-one` |
| `action` | 见第 3 节，须与 Gate 精确匹配 | `approve-map-brief` |
| `object_type` | 见第 3 节 | `map-brief` |
| `object_digest` | 被确认对象的精确摘要（`sha256:` + 64 hex） | `sha256:3f9c…` |
| `scope` | 须等于请求 `scope` | `project:project-flood-001` |
| `policy_id` | 须与步骤 `--policy-id` 一致 | `carto-security` |
| `environment` | 须与请求一致 | `local` |
| `issued_at` | 生效时间（含时区） | `2026-09-21T02:00:00+00:00` |
| `expires_at` | 失效时间，须 > `issued_at` 且消费时仍在窗口内 | `2026-09-21T02:10:00+00:00` |
| `nonce` | 随机串，**16–128 字符**，全局唯一，只消费一次 | `map-g1-flood-00000001` |
| `signature_algorithm` | 固定 `hmac-sha256` | `hmac-sha256` |
| `signature` | 对「除 signature 外全部字段的规范化 JSON」做 HMAC-SHA256，64 位小写 hex | `9a1b7c…` |

---

## 5. 审批人如何签发回执

仓库**没有** `approval sign` 命令，签名必须由持有密钥的审批人线下完成。以下脚本调用 Skill 内的 `sign_receipt`，把三个 Gate 的通用签发过程参数化。

将脚本保存为 `$APP/sign_gate.py`，在 `skills/carto-agent/scripts` 目录下运行（保证能 import `carto_core`）：

```python
# sign_gate.py —— 审批人线下签发 G1/G2/G3 回执
import os, sys, yaml
from dataclasses import asdict
from datetime import datetime, timedelta, UTC
from carto_core.security.approval import ApprovalReceipt, sign_receipt

# 用法: python sign_gate.py <action> <object_type> <object_digest> <scope> \
#                          <tenant_id> <environment> <issuer> <approver_subject_id> \
#                          <receipt_id> <nonce> <out_path> [有效分钟=10]
(action, object_type, object_digest, scope, tenant_id, environment, issuer,
 subject_id, receipt_id, nonce, out_path) = sys.argv[1:12]
minutes = int(sys.argv[12]) if len(sys.argv) > 12 else 10

key = os.environ["CARTO_APPROVAL_HMAC_KEY"].encode("utf-8")   # 必须 ≥ 32 字节
now = datetime.now(UTC)
receipt = ApprovalReceipt(
    schema_version=1,
    receipt_id=receipt_id,
    issuer=issuer,
    subject_id=subject_id,          # 审批人，不能等于发起人
    tenant_id=tenant_id,
    action=action,
    object_type=object_type,
    object_digest=object_digest,    # 原样粘贴步骤输出的摘要，不要自行计算
    scope=scope,
    policy_id="carto-security",
    environment=environment,
    issued_at=now.isoformat(),
    expires_at=(now + timedelta(minutes=minutes)).isoformat(),
    nonce=nonce,
)
signed = sign_receipt(receipt, key)
os.makedirs(os.path.dirname(out_path), exist_ok=True)
with open(out_path, "w", encoding="utf-8", newline="\n") as f:
    yaml.safe_dump(asdict(signed), f, allow_unicode=True, sort_keys=False)
print(f"written: {out_path}")
```

---

## 6. 逐 Gate 操作步骤

以下示例统一使用：`$PR=D:\carto\project-flood-001`、`$PS=D:\carto`、`$RUN=runs\gen`、`$REPO=D:\carto\template-repository`、`$APP=D:\carto\project-flood-001\approvals`；请求文件 `$REQ=$PR\generate-request.yaml`；发起人 `operator-one`、审批人 `reviewer-one`、`tenant-one`、`issuer=trusted-local`、`scope=project:project-flood-001`、`environment=local`。

### 6.1 G1 —— 批准地图简报

**① 操作者跑到 brief，取摘要：**

```powershell
cd D:\IdeaProjects\github\code-reviewer\carto-master-main
python skills/carto-agent/scripts/carto.py generate-map intake  $REQ --project-root $PR --workdir $RUN --repository-root $REPO --repository-scope local --allowed-root $PS --allowed-root $PR
python skills/carto-agent/scripts/carto.py generate-map brief   $REQ --project-root $PR --workdir $RUN --repository-root $REPO --repository-scope local --allowed-root $PS --allowed-root $PR
```

`brief` 返回 JSON（`{"ok":true,...}`）中的 `.approval_object_digest` 即 G1 的 `object_digest`；被确认对象落盘在 `$RUN\brief\map-brief.yaml`。

**② 审批人审阅 `map-brief.yaml`**（重点看：用途/受众、`source_plan` 的数据访问与字段语义、`targets`、`template_candidates` 的精确模板引用、`allowed_capabilities`、`scope`）。

**③ 审批人签发 `g1.yaml`：**

```powershell
cd skills\carto-agent\scripts
python $APP\sign_gate.py approve-map-brief map-brief "sha256:<粘贴.approval_object_digest>" `
  "project:project-flood-001" tenant-one local trusted-local reviewer-one `
  "approval-g1-run-flood-001" "map-g1-flood-00000001" "$APP\g1.yaml" 10
```

**④ 操作者用 G1 消费 compile：**

```powershell
python skills/carto-agent/scripts/carto.py generate-map compile $REQ --approval $APP\g1.yaml `
  --key-env CARTO_APPROVAL_HMAC_KEY --nonce-db $APP\nonces.sqlite3 --policy-id carto-security --issuer trusted-local `
  --project-root $PR --workdir $RUN --repository-root $REPO --repository-scope local --allowed-root $PS --allowed-root $PR
```

### 6.2 G2 —— 批准冻结（预览 → 不可变锁）

**① 操作者跑 preview，取摘要：**

```powershell
python skills/carto-agent/scripts/carto.py generate-map preview $REQ --attestation-key-env CARTO_RENDER_ATTESTATION_KEY `
  --project-root $PR --workdir $RUN --repository-root $REPO --repository-scope local --allowed-root $PS --allowed-root $PR
```

`preview` 返回 JSON 的 `.approval_object_digest` 即 G2 的 `object_digest`（它是 `freeze_object_digest`，绑定候选摘要、执行摘要、预览证据摘要、项目/作用域/环境与环境指纹）。预览产物（SVG/PNG/PDF）与证据落盘在 `$RUN\previews\` 与 `$RUN\candidates\`。

**② 审批人审阅预览成品**：打开 SVG/PNG/PDF 目视核对，并核对预览证据。签 G2 表示「我确认这份预览，同意冻结为不可变 `MapSpecLock`」。冻结后候选/场景/资源/环境任何漂移都会使摘要不匹配而被拒。

**③ 审批人签发 `g2.yaml`（注意 `object_type=resolved-map`）：**

```powershell
cd skills\carto-agent\scripts
python $APP\sign_gate.py approve-freeze resolved-map "sha256:<粘贴.approval_object_digest>" `
  "project:project-flood-001" tenant-one local trusted-local reviewer-one `
  "approval-g2-run-flood-001" "map-g2-flood-00000001" "$APP\g2.yaml" 10
```

**④ 操作者用 G2 消费 freeze（freeze 同时需要渲染证明密钥）：**

```powershell
python skills/carto-agent/scripts/carto.py generate-map freeze $REQ --approval $APP\g2.yaml `
  --key-env CARTO_APPROVAL_HMAC_KEY --attestation-key-env CARTO_RENDER_ATTESTATION_KEY `
  --nonce-db $APP\nonces.sqlite3 --policy-id carto-security --issuer trusted-local `
  --project-root $PR --workdir $RUN --repository-root $REPO --repository-scope local --allowed-root $PS --allowed-root $PR
```

### 6.3 G3 —— 批准交付

**① 操作者跑 render 与 check，取摘要：**

```powershell
python skills/carto-agent/scripts/carto.py generate-map render $REQ --attestation-key-env CARTO_RENDER_ATTESTATION_KEY `
  --project-root $PR --workdir $RUN --repository-root $REPO --repository-scope local --allowed-root $PS --allowed-root $PR

python skills/carto-agent/scripts/carto.py generate-map check $REQ --attestation-key-env CARTO_RENDER_ATTESTATION_KEY `
  --recipient-id reviewer-one --recipient-type project-user --destination deliveries\delivery-001 --idempotency-key delivery-001-00000001 `
  --project-root $PR --workdir $RUN --repository-root $REPO --repository-scope local --allowed-root $PS --allowed-root $PR
```

`check` 返回 JSON 的 `.g3` 对象即 G3 上下文，其中 `.g3.object_digest` = 整份不可变 `DeliveryManifest` 的摘要；清单落盘在 `$RUN\delivery-manifests\<manifest-id>.yaml`。只有 `check` 通过（无 blocker/error、warning 已处置）才会生成 Manifest 并进入 `waiting_approval / deliver`。

**② 审批人审阅 `DeliveryManifest`**：核对 `artifacts`（map.pdf/map.png 的路径、摘要、大小）、`recipient`、`destination`、`licenses`、`limitations`（含「合成数据演示，非真实风险研判」）、`idempotency_key`。签 G3 表示「我批准把这些经最终检查的成品交付给该接收方/目的地」。

**③ 审批人签发 `g3.yaml`（`object_type=delivery-manifest`）：**

```powershell
cd skills\carto-agent\scripts
python $APP\sign_gate.py approve-delivery delivery-manifest "sha256:<粘贴.g3.object_digest>" `
  "project:project-flood-001" tenant-one local trusted-local reviewer-one `
  "approval-g3-run-flood-001" "map-g3-flood-00000001" "$APP\g3.yaml" 10
```

**④ 操作者用 G3 消费 deliver（deliver 只需审批相关参数）：**

```powershell
python skills/carto-agent/scripts/carto.py generate-map deliver $REQ --approval $APP\g3.yaml `
  --key-env CARTO_APPROVAL_HMAC_KEY --nonce-db $APP\nonces.sqlite3 --policy-id carto-security --issuer trusted-local `
  --project-root $PR --workdir $RUN --repository-root $REPO --repository-scope local --allowed-root $PS --allowed-root $PR
```

交付成功后状态进入 `succeeded / deliver`；如需按幂等键查询提交结果，用 `generate-map delivery-status --idempotency-key delivery-001-00000001 ...`。

### 6.4 完整示例：G1 端到端（含真实取值）

下面用一组**自洽的具体取值**完整走一遍 G1，展示每一步产物到底长什么样。为便于对照，所有摘要/签名均为示例值（真实值由运行时计算）；`object_digest` 与 `g1.yaml` 中的取值必须逐字符一致。

**① 输入请求 `D:\carto\project-flood-001\generate-request.yaml`（关键字段）：**

```yaml
schema_version: 1
request_id: request-flood-001
run_id: run-flood-001
project_id: project-flood-001
goal: 制作城市洪涝风险专题图
audience: 应急管理人员
scene_hint: emergency_mapping
requested_outputs: [svg, png, pdf]
subject:
  subject_id: operator-one            # 发起人
  tenant_id: tenant-one
  namespace: local
  approver_subject_id: reviewer-one   # 独立审批人
scope: project:project-flood-001
environment: local
idempotency_key: generate-flood-001-00000001
template:
  namespace: local
  kind: map-scenario
  id: urban-flood-risk
  version: 1.0.0
  digest: sha256:7c9e2f51a8b306d47e19c05a2f8b63d04e7a1c9f52b8e063d17a4c9e05b2f871
allowed_capabilities: [read, filter, classify, render-preview]
source_bindings:
  - role: risk-area
    source_ref: {id: risk-source, version: 1.0.0, digest: "sha256:aa12f3c8d94e05b17a6c2f80e3d19b47c50a1f6e82b7d34091c5a8e07f2b6d13"}
    path: data\risk.geojson
    format: geojson
    field_bindings: [{semantic_role: risk-value, source_field: risk_col, value_type: number}]
  - role: shelter-point
    source_ref: {id: shelter-source, version: 1.0.0, digest: "sha256:bb34a7e1c05f92d8346b0e7a1f5c92b03e8d47a61c0f9b52e37a1c840f6b9d25"}
    path: data\shelters.geojson
    format: geojson
    field_bindings: [{semantic_role: count-value, source_field: people_col, value_type: integer}]
```

**② 运行 `intake` 与 `brief`，从 brief 输出取摘要：**

```powershell
python skills/carto-agent/scripts/carto.py generate-map brief `
  D:\carto\project-flood-001\generate-request.yaml `
  --project-root D:\carto\project-flood-001 --workdir runs\gen `
  --repository-root D:\carto\template-repository --repository-scope local `
  --allowed-root D:\carto --allowed-root D:\carto\project-flood-001
```

stdout（`_success` 按 key 排序输出，此处截取）：

```json
{
  "ok": true,
  "approval_object_digest": "sha256:3f9c1e427b8d0a51c9e2f634a1b7c8d0e5f1928374a6b0cd1e2f3a4b5c6d7e8f",
  "state": {"run_id": "run-flood-001", "step": "brief", "status": "waiting_approval"},
  "receipt": {"step": "brief", "status": "waiting_approval", "next_step": "compile"},
  "brief": {"brief_id": "brief-run-flood-001", "...": "..."}
}
```

这里的 `approval_object_digest`（`sha256:3f9c1e42…5c6d7e8f`）就是 G1 要填进回执的 `object_digest`。

**③ 被确认对象 `runs\gen\brief\map-brief.yaml`（审批人逐字段审阅）：**

```yaml
schema_version: 1
brief_id: brief-run-flood-001
revision: 1
intent_ref:
  id: map-intent
  version: 1.0.0
  digest: sha256:6b1f0a9c4e2d7813f5a0c6e9b2d47f18a3c5e7091b2d4f6a8c0e1b3d5f7a9c2e
  uri: D:\carto\project-flood-001\runs\gen\intent\map-intent.yaml
purpose: 制作城市洪涝风险专题图
audience: 应急管理人员
source_plan:
  - role: risk-area
    source_ref: {id: risk-source, version: 1.0.0, digest: "sha256:aa12f3c8d94e05b17a6c2f80e3d19b47c50a1f6e82b7d34091c5a8e07f2b6d13"}
    allowed_operations: [read, filter, classify]
    path_digest: sha256:aa12f3c8d94e05b17a6c2f80e3d19b47c50a1f6e82b7d34091c5a8e07f2b6d13
    field_bindings: [{semantic_role: risk-value, source_field: risk_col}]
  - role: shelter-point
    source_ref: {id: shelter-source, version: 1.0.0, digest: "sha256:bb34a7e1c05f92d8346b0e7a1f5c92b03e8d47a61c0f9b52e37a1c840f6b9d25"}
    allowed_operations: [read, filter, classify]
    path_digest: sha256:bb34a7e1c05f92d8346b0e7a1f5c92b03e8d47a61c0f9b52e37a1c840f6b9d25
    field_bindings: [{semantic_role: count-value, source_field: people_col}]
targets: [pdf, png, svg]
template_candidates:
  - {kind: map-scenario, id: urban-flood-risk, version: 1.0.0, digest: "sha256:7c9e2f51a8b306d47e19c05a2f8b63d04e7a1c9f52b8e063d17a4c9e05b2f871"}
delegation: {allow_data_agent: false, max_tool_calls: 0}
approval_required: true
project_id: project-flood-001
business_scene: emergency_mapping
scope: project:project-flood-001
environment: local
allowed_capabilities: [classify, filter, read, render-preview]
```

> 注意 `allowed_operations` 只取 `read/filter/join/classify/reproject` 与请求能力的交集，因此不含 `render-preview`；`targets` 与 `allowed_capabilities` 均已排序——这些都是 `brief()` 的确定性产物，摘要据此计算。

**④ 审批人签发 `D:\carto\project-flood-001\approvals\g1.yaml`（完整回执）：**

```powershell
cd skills\carto-agent\scripts
python D:\carto\project-flood-001\approvals\sign_gate.py `
  approve-map-brief map-brief `
  "sha256:3f9c1e427b8d0a51c9e2f634a1b7c8d0e5f1928374a6b0cd1e2f3a4b5c6d7e8f" `
  "project:project-flood-001" tenant-one local trusted-local reviewer-one `
  "approval-g1-run-flood-001" "map-g1-flood-00000001" `
  "D:\carto\project-flood-001\approvals\g1.yaml" 10
```

生成的 `g1.yaml`：

```yaml
schema_version: 1
receipt_id: approval-g1-run-flood-001
issuer: trusted-local
subject_id: reviewer-one            # = approver_subject_id，且 ≠ 发起人 operator-one
tenant_id: tenant-one
action: approve-map-brief
object_type: map-brief
object_digest: sha256:3f9c1e427b8d0a51c9e2f634a1b7c8d0e5f1928374a6b0cd1e2f3a4b5c6d7e8f
scope: project:project-flood-001
policy_id: carto-security
environment: local
issued_at: '2026-09-21T02:00:00+00:00'
expires_at: '2026-09-21T02:10:00+00:00'
nonce: map-g1-flood-00000001
signature_algorithm: hmac-sha256
signature: 9a1b7c03e5d28f4160ab9c2d7e1f30548b6a0d9c2e7f14035b8a6c9d0e2f1743
```

**⑤ 操作者用 `g1.yaml` 消费 `compile`：**

```powershell
python skills/carto-agent/scripts/carto.py generate-map compile `
  D:\carto\project-flood-001\generate-request.yaml `
  --approval D:\carto\project-flood-001\approvals\g1.yaml `
  --key-env CARTO_APPROVAL_HMAC_KEY `
  --nonce-db D:\carto\project-flood-001\approvals\nonces.sqlite3 `
  --policy-id carto-security --issuer trusted-local `
  --project-root D:\carto\project-flood-001 --workdir runs\gen `
  --repository-root D:\carto\template-repository --repository-scope local `
  --allowed-root D:\carto --allowed-root D:\carto\project-flood-001
```

成功时 stdout（截取），状态推进到 `preview`，并产出候选与场景：

```json
{
  "ok": true,
  "state": {"run_id": "run-flood-001", "step": "compile", "status": "succeeded"},
  "candidate": {"candidate_id": "candidate-run-flood-001", "...": "..."},
  "scene": {"scene_id": "scene-run-flood-001", "...": "..."}
}
```

**⑥ 负例（说明摘要绑定为何重要）：**

- 审批人误把 `object_digest` 填成**上一次运行**的 brief 摘要（或手误截断）→ `compile` 重算当前 brief 摘要不匹配：
  ```json
  {"ok": false, "code": "APPROVAL_OBJECT_MISMATCH", "message": "Approved object digest does not match"}
  ```
- 同一张 `g1.yaml` 被拿去**再消费一次**（例如重跑 compile 或用到另一条运行）→ nonce 已消费：
  ```json
  {"ok": false, "code": "APPROVAL_REPLAYED", "message": "Approval nonce has already been consumed"}
  ```
- 审批人把 `subject_id` 写成发起人 `operator-one`（≠ `approver_subject_id`）→
  ```json
  {"ok": false, "code": "APPROVAL_IDENTITY_MISMATCH", "message": "Approval issuer or subject does not match"}
  ```

G3 的走查与此完全同构，只需把 `action`/`object_type`/`object_digest` 换成第 3 节对应值，被确认对象换成 `DeliveryManifest`（摘要取自 `check` 输出的 `.g3.object_digest`）。G2 因摘要构成不同，单独在 6.5 展开。

### 6.5 完整示例：G2 端到端（预览 → 冻结）

G2 与 G1 最大的不同：`object_type` 虽为 `resolved-map`，但 `object_digest` **不是** `sha256(resolved-map.yaml)`，而是一个把候选、执行、预览证据与环境指纹全部绑在一起的**复合冻结摘要**（`freeze_object_digest`）。沿用 6.4 的同一运行（接 `compile` 之后，状态已为 `compile / succeeded`）。

**① 运行 `preview`（需渲染证明密钥）：**

```powershell
python skills/carto-agent/scripts/carto.py generate-map preview `
  D:\carto\project-flood-001\generate-request.yaml `
  --attestation-key-env CARTO_RENDER_ATTESTATION_KEY `
  --project-root D:\carto\project-flood-001 --workdir runs\gen `
  --repository-root D:\carto\template-repository --repository-scope local `
  --allowed-root D:\carto --allowed-root D:\carto\project-flood-001
```

stdout（截取；注意 `receipt` 字段是**渲染回执**，非步骤回执）：

```json
{
  "ok": true,
  "approval_object_digest": "sha256:d81f4a02e7b39c6501f8e2a47b3c05d961e8f47a02c19b653d87ea04f92b1c60",
  "state": {"run_id": "run-flood-001", "step": "preview", "status": "waiting_approval"},
  "receipt": {"receipt_id": "render-candidate-run-flood-001", "renderer_id": "maplibre-web", "status": "succeeded", "output_artifacts": ["...svg/png/pdf..."]},
  "evidence": {"evidence_id": "preview-run-flood-001", "status": "passed", "environment_fingerprint": "sha256:5b0e7a13c94f28d6037a1b5e82c09f47d16b3a05e8c7942f01b5d6a3c07e9184"},
  "profile": {"renderer_id": "maplibre-web", "maplibre_version": "3.6.0"}
}
```

这里的 `approval_object_digest`（`sha256:d81f4a02…f92b1c60`）就是 G2 要填进回执的 `object_digest`。

**② 复合冻结摘要的构成（为何能防漂移）：**

`freeze_object_digest(request, candidate, evidence)` = 对下面 7 项取 `sha256`：

```jsonc
{
  "candidate_digest":        "sha256:c2a9f1e07b4d3865a10c9e8f72b6d3405a1c8e97f02b4d63a85c1e097f2b4d61",  // = sha256(resolved-map.yaml)
  "execution_digest":        "sha256:e7d15a90c3f82b4601d9a7c5e30b18f247c60a91d835e2b07f14c6a90e5b2d38",  // = candidate.execution_digest
  "preview_evidence_digest": "sha256:a94c2e17f08b35d619e4a7c02b51f13d607a91c4e28f5b03a16c9d704e82b5f0",  // = evidence.evidence_digest
  "project_id":              "project-flood-001",
  "scope":                   "project:project-flood-001",
  "environment":             "local",
  "environment_fingerprint": "sha256:5b0e7a13c94f28d6037a1b5e82c09f47d16b3a05e8c7942f01b5d6a3c07e9184"   // 绑定渲染环境/浏览器
}
// → object_digest = sha256:d81f4a02e7b39c6501f8e2a47b3c05d961e8f47a02c19b653d87ea04f92b1c60
```

只要候选、执行计划、预览证据或渲染环境任一发生变化，该摘要就会变，旧回执自动失效。

**③ 审批人要审阅的产物（均在 `runs\gen\` 下）：**

| 文件 | 作用 |
|---|---|
| `previews\*.svg` / `*.png` / `*.pdf` | **目视核对**地图成品（分级设色、比例符号、图例、无数据） |
| `candidates\resolved-map.yaml` | 类型化地图候选（对应 `object_type=resolved-map`） |
| `candidates\render-scene.yaml` | 渲染场景（图层/资源/视口） |
| `candidates\preview-evidence.yaml` | 预览证据（四项 blocker 检查均 passed） |
| `candidates\render-receipt.yaml` | 签名渲染回执（环境指纹/输出摘要） |

签 G2 的含义：**“我已目视核对预览成品，同意把这一份精确候选冻结为不可变 `MapSpecLock`。”**

**④ 审批人签发 `D:\carto\project-flood-001\approvals\g2.yaml`（注意 `object_type=resolved-map`）：**

```powershell
cd skills\carto-agent\scripts
python D:\carto\project-flood-001\approvals\sign_gate.py `
  approve-freeze resolved-map `
  "sha256:d81f4a02e7b39c6501f8e2a47b3c05d961e8f47a02c19b653d87ea04f92b1c60" `
  "project:project-flood-001" tenant-one local trusted-local reviewer-one `
  "approval-g2-run-flood-001" "map-g2-flood-00000001" `
  "D:\carto\project-flood-001\approvals\g2.yaml" 10
```

生成的 `g2.yaml`：

```yaml
schema_version: 1
receipt_id: approval-g2-run-flood-001
issuer: trusted-local
subject_id: reviewer-one
tenant_id: tenant-one
action: approve-freeze
object_type: resolved-map
object_digest: sha256:d81f4a02e7b39c6501f8e2a47b3c05d961e8f47a02c19b653d87ea04f92b1c60
scope: project:project-flood-001
policy_id: carto-security
environment: local
issued_at: '2026-09-21T03:00:00+00:00'
expires_at: '2026-09-21T03:10:00+00:00'
nonce: map-g2-flood-00000001
signature_algorithm: hmac-sha256
signature: 7e0a19f5b3286c041d9e7a3f5028b6c14e07a9d3f1862b05c9e31f7a04d28b69
```

**⑤ 操作者用 `g2.yaml` 消费 `freeze`（同时需审批密钥与渲染证明密钥）：**

```powershell
python skills/carto-agent/scripts/carto.py generate-map freeze `
  D:\carto\project-flood-001\generate-request.yaml `
  --approval D:\carto\project-flood-001\approvals\g2.yaml `
  --key-env CARTO_APPROVAL_HMAC_KEY `
  --attestation-key-env CARTO_RENDER_ATTESTATION_KEY `
  --nonce-db D:\carto\project-flood-001\approvals\nonces.sqlite3 `
  --policy-id carto-security --issuer trusted-local `
  --project-root D:\carto\project-flood-001 --workdir runs\gen `
  --repository-root D:\carto\template-repository --repository-scope local `
  --allowed-root D:\carto --allowed-root D:\carto\project-flood-001
```

`freeze` 会重验候选/场景/模板/资源/预览产物/回执/环境，验证 G2 后创建 create-once 的 `MapSpecLock`（落盘 `runs\gen\locks\lock-run-flood-001\map-spec-lock.yaml`）。成功时 stdout（截取），状态推进到 `render / pending`：

```json
{
  "ok": true,
  "idempotent_replay": false,
  "state": {"run_id": "run-flood-001", "step": "render", "status": "pending"},
  "lock": {"lock_id": "lock-run-flood-001", "...": "..."}
}
```

**⑥ 负例（G2 特有）：**

- 预览通过后偷偷改了候选、场景或数据资源 → `freeze` 重算冻结摘要不匹配：
  ```json
  {"ok": false, "code": "APPROVAL_OBJECT_MISMATCH", "message": "Approved object digest does not match"}
  ```
- **换一台机器/浏览器重跑 `preview`** → `environment_fingerprint` 变化导致冻结摘要变化；拿旧 `g2.yaml` 同样报 `APPROVAL_OBJECT_MISMATCH`。因此 G2 必须在**与预览相同的受控渲染环境**下消费。
- 候选资源摘要被篡改 → `freeze` 可能先报 `CANDIDATE_RESOURCE_DRIFT` / `CANDIDATE_EXECUTION_DIGEST_MISMATCH`。
- 同一张 `g2.yaml` 重复消费 → `APPROVAL_REPLAYED`（中断后的恢复只能凭严格匹配的 workflow-local intent，普通重放不算恢复）。

---

## 7. 排错对照表

审批相关错误均来自 `verify_receipt_claims` / `verify_receipt`：

| 错误码 | 触发原因 | 处理 |
|---|---|---|
| `APPROVAL_KEY_WEAK` | HMAC 密钥 < 32 字节 | 换用 ≥ 32 字节密钥，签发与消费两端一致 |
| `APPROVAL_SIGNATURE_INVALID` | 签名不匹配 / 字段被改 | 用同一密钥重新签发；签发后不得手改任何字段 |
| `APPROVAL_ACTION_MISMATCH` | `action` 与 Gate 不符 | 按第 3 节填写精确 action |
| `APPROVAL_OBJECT_TYPE_MISMATCH` | `object_type` 与 Gate 不符 | G2=`resolved-map`、G3=`delivery-manifest` |
| `APPROVAL_OBJECT_MISMATCH` | `object_digest` ≠ 当前对象摘要 | 用步骤**当次**输出的摘要重签；对象变了要重走审批 |
| `APPROVAL_SCOPE_MISMATCH` | `scope` 或 `tenant_id` 不符 | 与请求保持一致 |
| `APPROVAL_POLICY_MISMATCH` | `policy_id` 与 `--policy-id` 不符 | 两端统一为 `carto-security` |
| `APPROVAL_IDENTITY_MISMATCH` | `issuer` 或 `subject_id` 不符 | `subject_id` 必须 = `approver_subject_id`；`issuer` 与 `--issuer` 一致 |
| `APPROVAL_ENVIRONMENT_MISMATCH` | `environment` 不符 | 与请求一致（例 `local`） |
| `APPROVAL_TIME_INVALID` | 未到 `issued_at` / 已过 `expires_at` / 时间无时区 | 校准时间；签发含时区的时间戳；在有效期内消费 |
| `APPROVAL_REPLAYED` | `nonce` 已被消费 | 每次审批用**新** nonce；见第 8 节的 verify 陷阱 |

---

## 8. 安全约束与注意事项

1. **摘要必须取自步骤当次输出**：G1/G2 用 `.approval_object_digest`，G3 用 `.g3.object_digest`；禁止手工推算或复用旧摘要。对象一旦漂移，旧回执自动失效。
2. **一 Gate 一 nonce**：`nonce` 16–128 字符、全局唯一，只消费一次。普通重放一律拒绝。
3. **`carto approval verify` 会消费 nonce（重要陷阱）**：该命令内部调用 `verify_receipt`，会向传入的 `--nonce-db` 写入消费记录。**不要**用正式步骤将使用的同一个 `nonces.sqlite3` 去做预校验，否则真正的 `compile/freeze/deliver` 会因 `APPROVAL_REPLAYED` 失败。如需干跑校验，请用一次性临时 nonce 库。
4. **审批人独立性**：审批人 `subject_id` 不得等于发起人；宿主 Agent 不能自签，必须停下索取回执。
5. **时效窗口**：`expires_at` 建议留足操作时间（示例 10 分钟）；过期需重签。
6. **中断恢复**：消费 nonce 后若中断，只有严格匹配的 workflow-local intent 或不可变事务证据才能恢复；漂移或无关内容一律拒绝，普通重放不构成恢复。
7. **交付边界**：G3 后 `deliver` 只接受项目内本地允许根交付；交付包白名单固定为 `map.pdf`、`map.png`、`README.md`、`delivery-manifest.yaml`、`checksums.sha256`，不含原始数据、内部锁、审批文件、密钥、RenderReceipt 或内部 ValidationReport。

---

## 9. 快速索引

- Gate 定义：`skills/carto-agent/scripts/carto_core/workflow/approvals.py`（`GATES`）
- 回执 Schema：`skills/carto-agent/schemas/approval-receipt.schema.json`
- 签名 / 校验：`skills/carto-agent/scripts/carto_core/security/approval.py`（`sign_receipt` / `verify_receipt`）
- G2 冻结摘要：`skills/carto-agent/scripts/carto_core/workflow/map_preview.py`（`freeze_object_digest`）
- G3 上下文与 Manifest：`skills/carto-agent/scripts/carto_core/workflow/map_final_check.py`（`g3_context` / `build_manifest`）
- 步骤编排：`skills/carto-agent/scripts/carto_core/workflow/map_generation.py`
- CLI：`skills/carto-agent/scripts/carto_core/cli.py`
- 工作流说明：`skills/carto-agent/workflows/generate-map.md`、`routing.md`
