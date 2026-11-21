# 领导调研用图 — G1 后数据准备（场景操作手册）

> 宿主智能体读本文执行领导调研用图的数据准备段。机器协议以
> `schemas/leadership-visit-generate-request.schema.json` 和 MCP 服务的 Schema 为准；
> 本文只承载"与其他场景不一样的操作指引"。

## 一、与其他场景的差异化操作

| 差异点 | 通用专题图 | 领导调研用图 |
|---|---|---|
| G1 前数据 | 数据文件已就绪，brief 绑定摘要 | **DOCX 摘要 + 底图 + 配准参数**（无 itinerary.json） |
| 请求 source_bindings | `path` 指向已有文件 | `pending: true` + `path` 指向将产出文件的位置 |
| G1 后首步 | compile 直接读数据 | **先调 MCP 工具链（geocode + plan_route → itinerary_assemble），再 compile** |
| 外部调用 | 无 | 地理编码 + 路径规划（须经 G1 授权） |
| 用户交互 | 无 | 地理编码歧义须询问用户并等待回复 |
| 敏感边界 | 无 | 行程地点外发第三方前须 G1 授权 |

## 二、MCP 工具链（五个工具）

使用 `services/itinerary-tools/`（新框架内的轻量 MCP 服务，pip 依赖
httpx+mcp+PyYAML，零内核依赖）。前两个是算法工具，后三个是行程准备工具——
确定性机械步骤已工具化（**程序负责确定性处理，宿主只负责事实语义**；
准备工具是 advisory 层，权威校验在内核）。

### 工具 1：geocode（地理编码，含歧义检测）

```
输入: {
  "places": [{"place_id": "place-a", "name": "临安区行政中心", "city": "杭州"}],
  "confirmations": [...]  // 可选：歧义确认后传入
}
输出: {
  "status": "complete" | "needs_input" | "error",
  "resolved": [{"place_id", "location": {"lon", "lat"}, "formatted_address"}],
  "ambiguous": [{"place_id", "block_reason", "candidates": [...]}]  // needs_input 时
}
```

**操作流程**：
1. 首次调用 → 返回 `needs_input` + 候选列表
2. **向用户展示候选，等待真实回复**（不能自行选定或默认第一项）
3. 用户确认后，带 `confirmations` 重调 → 返回 `complete`

### 工具 2：plan_route（路径规划，三级回退）

```
输入: {
  "legs": [{"leg_id": "leg-01",
            "origin": {"lon": 120.150, "lat": 30.267},
            "destination": {"lon": 119.748, "lat": 30.257}}],
  "allow_straight_line": false  // 可选
}
输出: {
  "status": "complete",
  "results": [{"leg_id", "geometry": {"type": "LineString", "coordinates": [...]},
               "distance_km", "duration_min", "engine"}]
}
```

**三级回退**（自动选择，无需手动指定）：
- Plan A: 离线对偶图（本地浙江路网，免费快速）
- Plan B: 高德在线路由（需要 CARTO_AMAP_KEY）
- Plan C: 直线回退（仅当 `allow_straight_line=true`）

### 工具 3：itinerary_check（草稿校验，语义反馈层）

```
输入: {"draft_path": "data/itinerary-draft.json", "expected_digest": "sha256:…"}  // digest 可选
输出: {"status": "complete" | "invalid",
       "report": {"errors": [{"code", "path", "message"}], "warnings": [...]},
       "draft_digest": "sha256:…"}
```

G1 前调一次：错误定位到字段路径，按提示修正草稿后复检至 `complete`。

### 工具 4：request_scaffold（请求骨架 + 摘要计算）

```
输入: {"draft_path": "...", "project_id": "...", "tenant_id": "...",
       "subject_id": "...", "approver_subject_id": "...",   // 身份四项必填（审批绑定面）
       "request_id" / "run_id" / "idempotency_key": 可选（缺省自动生成）,
       "basemap_path" / "registration_path" / "font_path" / "template_repo_path": 可选有默认}
输出: {"status": "built", "request_path": "generate-request.yaml",
       "bound_digests": {draft, basemap, registration, template}, "identity": {...}}
```

draft / registration / basemap / 模板仓库位置非默认时显式传参。

### 工具 5：itinerary_assemble（合并组装 + 原子落盘，G1 后、compile 前）

```
输入: {"draft_path": "...",
       "geocode_result": {…geocode 工具 complete 时的完整输出…},
       "route_result":   {…plan_route 工具的完整输出…},
       "output_path": "data/itinerary.json"}  // 可选
输出: {"status": "assembled", "output_path", "output_digest",
       "counts": {...}, "evidence": [{uri, digest} × 2]}
```

校验每个地点有用户确认坐标、每条 travel 腿有道路折线，任一缺失即拒绝
（点名缺项，不落盘）。**宿主不要手工改写 itinerary.json**——组装是程序步骤。

## 三、你的职责（宿主语义工作 + 工具编排）

1. 生成数据目录摘要（唯一 CLI，经 data-summary 网关能力，只读、留证据回执）：
   `carto data summarize data-summary-request.yaml --project-root . --allowed-root . --run-id <id> --tenant-id <id> --project-id <id> --subject-id <id>`
   （请求文档：`{"schema_version": 1, "data_dir": "data"}`；Markdown 摘要在
   `.carto/data/evidence/tool-data-summary/1.0.0/` 证据 artifact 内，`summary_md` 字段）
2. 从摘要提取行程事实 → 维护 `data/itinerary-draft.json`
   （合同格式：places + stops + activities + legs + source_blocks，字段指南见 §四）
3. 调 `itinerary_check`：按错误报告修正草稿，复检至 `complete`
4. 调 `request_scaffold`：产出 `generate-request.yaml`（摘要绑定全部由工具计算）
5. `carto generate-map intake / brief`，等待 [G1]
6. G1 后：调 `geocode`（歧义必须问用户）→ `plan_route` →
   把两次工具调用的完整输出传给 `itinerary_assemble` → 得到 `data/itinerary.json`
7. 直接调用 `carto generate-map compile`
   - **不要修改 generate-request.yaml**：请求在 intake 时已被指纹锁定，
     G1 后任何改动都会触发 `JOB_INPUT_DRIFT`
   - pending 绑定里的 `source_ref.digest` 是**前瞻声明**（scaffold 绑定的
     draft 摘要）；实际数据的绑定发生在
     G2，经 prepared-data-bundle 摘要锁定真正渲染的数据

## 四、从 data-summary.md 提取事实草稿（字段指南）

### places（唯一地点）

```json
{
  "place_id": "place-linan",
  "name": "临安区行政中心",
  "source_refs": ["src-docx"],
  "geocoding_query": {"name": "临安区行政中心", "city": "杭州"}
}
```

- `place_id` 全局唯一，格式建议 `place-<地名简称>`
- `name` 保持原文地名，不增删字
- `location` **不要填**——留给 MCP geocode 产出
- `geocoding_query` 是对象（非字符串），包含 `name` 和 `city`

### stops（按顺序的停留片段）

- `stop_id` 全局唯一，顺序 = 行程物理顺序
- 同一地点连续两个活动（如先用餐后调研）→ 拆为两个 stop，用 `kind: "stay"` 的 leg 连接

### activities

`type` 枚举：`departure` / `visit` / `meeting` / `meal` / `rest` / `meal_and_rest` / `transfer` / `end`
`period`：`morning` 或 `afternoon`（不确定则省略，不猜）

### legs（相邻停靠连接）

- `kind`：`travel`（跨地点）或 `stay`（同地点）
- `route_mode`：`road_network`（默认）
- `metric_source`：`document`（用原文值）、`routing`（用工具值）、`none`
- `geometry` **不要填**——留给 MCP plan_route 产出

## 五、关键约束

1. **地点歧义必须问用户**：不能自行选定候选、不能默认第一项
2. **G1 前只做初读**：不调用 geocode/plan_route（外部服务调用须 G1 授权）
3. **不写日志**：原始 DOCX 路径、完整行程、敏感坐标不写普通日志
4. **MCP 不调大模型**：你负责事实语义，程序负责确定性处理
5. **`map_role`、分组由程序生成**：新框架的 `data_preparer._from_contract` 自动处理
6. **用户提出修改后，每版预览必须回到确认环**（2026-11-21 实测教训）：首轮连续推进可
   凭用户的一次性总授权（"完整测试"类指令）；**一旦用户提出修改请求（样式修订、标题、
   任何设计层变更），后续每道门恢复逐门确认**——重编译/`revise` 后把新版预览（注意落位
   `work/revisions/rN/previews/`，旧版在原路径保持不可变，属框架规定）**展示给用户并
   停下，问"这版可以吗？还要再改吗？"，获得当次明确答复后才签 G2**。不要凭先前的
   总授权连续签 G2/review/G3 一路走到交付——G2 门的存在意义就是审批人审过实际预览。
7. **修订版预览路径**：修订产物按框架规定写入 `work/revisions/rN/`（含 previews），
   原设计的候选/预览/回执在原路径**保持不可变**，当前版本由状态事务确定；交付包
   （`delivery/`）才是最终交付物。不要试图把旧预览覆盖成新设计。

## 六、数据变更重跑（宿主级复用，零代码）

> **2026-11-21 更新**：`revision-brief/revise` 的修订词汇已扩展——`map_title/
> annotation_layout/page_layout/style_overrides` 四个设计层键之外，新增
> `basemap`/`online_basemap` 两个 **compile 资源层键**（换底图、加/撤在线底图绑定
> 走 revise，bundle 复用、零 MCP 重跑；冻结后 lock 已存在时不可修订，须新运行）。
> 本节其余内容对**行程数据**（改路线/改点位）继续成立。

用户在 G2 前后提出**改路线 / 改行程数据**时，这些是数据层变更，**不走设计修订
通道**（修订词汇不含行程三键：`source_bindings/sources/itinerary_structure` 留在
bundle_input_keys 守卫内），必须开新运行。新运行 ≠ 从零开始——按工具 I/O 契约复用
上一轮结论，把成本压到"变更部分的真实计算 + 新 G1 + 新 G2"：

1. **地理编码不重新盘问用户**：上一轮 `geocode` 的确认结论（`confirmations`）对未变更
   地点直接可复用；仅新增/改名地点需要新的歧义确认。
2. **路径规划只跑变更腿**：`plan_route` 按腿输入，未变更腿沿用上一轮 `results`，与新结果
   合并成完整的 `route_result` 传给 `itinerary_assemble`（其校验"每条 travel 腿有道路
   折线"，合并结果满足）。
3. **请求重建是机械步骤**：改完 `itinerary-draft.json` → `itinerary_check` 复检至
   `complete` → `request_scaffold` 自动重算全部摘要绑定。
4. 之后走新运行标准链：`intake → brief → 新 G1 → MCP 链 → compile → preview → 新 G2`。

对比：**样式变更**（颜色/字号/图框边线）走 `style_overrides` + 修订通道
（见 `doc/leadership-visit-usage.md` "三"），MCP 数据链整体跳过。

## 七、CLI 运维要点（宿主实测）

1. **长步骤 stdout 混渲染日志**：`preview` / `render` / `validate` 的输出流可能混入
   渲染器日志，管道直接 `json.load` 会失败——输出落文件（`> <step>.out 2>&1`）再解析。
   管道解析失败 ≠ 命令失败：先用 `generate-map status`（无 request 参数）查状态机确认。
   **根因（2026-11-21 实测确认）**：Windows 宿主控制台默认 GBK 代码页，CLI 的 UTF-8
   JSON 输出与渲染器日志经 codepage 混编后产生无效字节——属**已登记的已知问题**，
   正式部署前应将 CLI stdout 统一为 UTF-8（`-X utf8` / 重配置 stdout 编码）；
   当前的文件落盘 + 二次解析是宿主侧规避，不是长期方案。
2. **全部参数用绝对路径**：`--project-root` / `--allowed-root` / `--workdir` / 请求路径，
   相对路径报 `RELATIVE_PATH_WITHOUT_ROOT` / `ALLOWED_ROOT_NOT_ABSOLUTE`。
3. **G2 对象摘要可复算**：`freeze_object_digest(request, work/candidates/resolved-map.yaml,
   work/candidates/preview-evidence.yaml)` 从持久化 artifacts 加载后用内核同源函数计算，
   不依赖一次性 stdout。
4. **`delivery-status` 需要 `--idempotency-key`**。
5. **审批签发**：回执由持有 `CARTO_APPROVAL_HMAC_KEY` 的审批方签发（或按两层纪律：
   宿主先在对话中获得用户明确批准、再凭密钥代签）。验签命令是顶层
   `carto approval verify`（不是 `security` 子命令）；回执 `receipt_id` 须为
   小写 kebab-case。
6. **宿主不写组装脚本**：draft 校验/请求组装/itinerary 组装已由服务工具承载
   （itinerary_check / request_scaffold / itinerary_assemble）；宿主只产出
   `itinerary-draft.json` 这一个语义文件。审批回执签发用仓库
   `skills/carto-agent/tools/host/approval-sign.py`（密钥在项目目录或环境变量，
   签发前必须已获用户对话批准）。
