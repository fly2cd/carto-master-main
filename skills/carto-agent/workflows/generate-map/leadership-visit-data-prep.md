# 领导调研用图 — G1 后数据准备（场景操作手册）

> 宿主智能体读本文执行领导调研用图的数据准备段。机器协议以
> `schemas/leadership-visit-generate-request.schema.json` 和 MCP 服务的 Schema 为准；
> 本文只承载"与其他场景不一样的操作指引"。
>
> **宿主接入契约（§八）**：任意具备"shell 执行 + MCP 客户端 + 文件读写 + 用户交互"
> 四能力的宿主，按本文操作即完成全链路，全程无需编写任何程序（shell 命令、MCP 调用、
> draft JSON 撰写、回执签发调用不属于"程序"）。

## 一、与其他场景的差异化操作

| 差异点 | 通用专题图 | 领导调研用图 |
|---|---|---|
| G1 前数据 | 数据文件已就绪，brief 绑定摘要 | **DOCX 摘要 + 底图 PNG + 五字段 registration.yaml（用户直供）**（无 itinerary.json） |
| 请求 source_bindings | `path` 指向已有文件 | `pending: true` + `path` 指向将产出文件的位置 |
| G1 后首步 | compile 直接读数据 | **先调 MCP 工具链（geocode + plan_route → itinerary_assemble，大结果走引用）**，再 compile |
| 外部调用 | 无 | 地理编码 + 路径规划（须经 G1 授权） |
| 用户交互 | 无 | 地理编码歧义须询问用户并等待回复 |
| 敏感边界 | 无 | 行程地点外发第三方前须 G1 授权 |

**registration.yaml 输入合同**：五字段（`work_crs` / `origin_m` / `local_km_y_down_to_pixel` /
`source_size` / `source_pixel_sha256`），由用户提供（配准工具产出什么就供什么）。
`source_pixel_sha256` 是图片**像素阵列**摘要（BGR 解码，见内核 geo_to_image_pixels），
不是文件字节摘要；编译时内核复算比对，图/配准错位即失败关闭。旧框架 transform.json
不是本框架输入（多字段会进入冻结摘要面，非数学字段改动即摘要漂移）。

## 二、MCP 工具链（六个工具）

使用 `services/itinerary-tools/`（新框架内的轻量 MCP 服务，pip 依赖
httpx+mcp+PyYAML，零内核依赖）。前两个是算法工具，后四个是行程准备工具——
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

### 工具 2：plan_route（路径规划，三级回退 + 结果引用）

```
输入: {
  "legs": [{"leg_id": "leg-01",
            "origin": {"lon": 120.150, "lat": 30.267},
            "destination": {"lon": 119.748, "lat": 30.257},
            "via_points": [{"lon": ..., "lat": ...}],       // 可选
            "strategy": "2"}],                               // 可选
  "allow_straight_line": false,                              // 可选，默认 false
  "base_result_ref": {"uri": "route-results/…", "digest": "sha256:…"}  // 可选：增量重跑
}
输出: {
  "status": "complete" | "partial" | "error",
  "results": [...],                                          // 每腿结果（小结果可直接用）
  "result_ref": {"uri": "route-results/plan-<时间戳>-<N>legs.json",
                 "digest": "sha256:…"}                       // 服务端落盘凭证
}
```

**三级回退（契约已三层强制）**：
- Plan A: 离线对偶图（本地浙江路网，免费快速）
- Plan B: 高德在线路由（需要 CARTO_AMAP_KEY；**缺 key 报 `AMAP_KEY_MISSING` 命名错误，不静默降级**）
- Plan C: 直线回退（**仅当显式 `allow_straight_line=true`**；否则直线结果一律 `status: failed`，组装亦拒绝）

**结果引用协议（宿主零脚本的关键）**：结果由服务端原子落盘 `route-results/`，返回
`result_ref {uri, digest}`。**宿主把 result_ref 原样传给 itinerary_assemble 即可，
不要把折线内联重述**（LLM 转抄无法保证逐字节一致）。**增量重跑**：只传变更腿 +
`base_result_ref`（上一轮的 result_ref），未变更腿由服务端从持久化文件 verbatim
搬运（不重路由），返回新的合并 result_ref。

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
       "route_result": {…plan_route 完整输出…},                // 路线 A：内联（小结果）
       "route_result_ref": {"uri": "...", "digest": "sha256:…"}, // 路线 B：引用（与 A 互斥）
       "output_path": "data/itinerary.json"}  // 可选
输出: {"status": "assembled", "output_path", "output_digest",
       "counts": {...}, "evidence": [{uri, digest} × 2]}
```

校验每个地点有用户确认坐标、每条 travel 腿有道路折线（且**引擎非降级直线、
距离非零**），任一缺失即拒绝（点名缺项，不落盘）。**宿主不要手工改写
itinerary.json**——组装是程序步骤。引用输入会被服务端字节级摘要复验，篡改即
`ROUTE_RESULT_DIGEST_MISMATCH`。

### 工具 6：basemap_snapshot（在线底图快照固化）

从当前配准/底图推导取景范围，拉取天地图瓦片（vec_w 矢量 / img_w 影像 / cia_w 影像注记），
固化为配准底图 PNG + registration（同窗口配准）。外发取景范围须经 G1 审批面声明。
详见 SKILL.md 的 online_basemap 段；正式修订走 `basemap` 修订键。

### 错误码表（宿主应对）

| 错误码 | 含义 | 宿主应对 |
|---|---|---|
| `PATH_OUTSIDE_ROOT` / `PATH_NOT_FOUND` | 路径越界 / 不存在 | 修正路径（须在 allowed-root 内） |
| `ROUTE_RESULT_DIGEST_MISMATCH` | 引用文件与声明摘要不符 | 文件被改动过；重跑 plan_route 取新 ref |
| `ROUTE_RESULT_REF_INVALID` / `BASE_RESULT_INVALID` | 引用形状/内容非法 | 检查 ref 字段或 base 文件 |
| `INPUT_CONFLICT` | route_result 与 ref 同传 | 二选一 |
| `AMAP_KEY_MISSING` | shell/MCP 环境缺 CARTO_AMAP_KEY | 检查 .mcp.json env 或 shell 导出 |
| `ROUTE_ENGINE_DEGRADED` | 直线降级结果被组装拒绝 | 按 message 修根因（通常是缺 key/网络），重跑 plan_route |
| `ROUTE_METRICS_INVALID` | 引擎返回零/缺失距离 | 重跑 plan_route |
| `ITINERARY_*` / `GEOCODE_INCOMPLETE` / `LEGS_REQUIRED` / `CTX_REQUIRED` | 草稿/输入不完整 | 按 message 定位修正后重调 |

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
6. G1 后：调 `geocode`（歧义必须问用户）→ `plan_route`（得到 `result_ref`）→
   **把 `result_ref` 原样传给 `itinerary_assemble`** → 得到 `data/itinerary.json`
   （**不要把道路折线内联重述**——引用协议保证字节一致，转述不保证）
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
8. **大结果走引用，不内联重述**（2026-11-22 协议）：`plan_route` 的折线结果经
   `result_ref {uri, digest}` 传递，宿主不得把折线 JSON 内联重述给下一个工具——
   转述无法保证逐字节一致，任何一位数字漂移即证据漂移；增量改线用
   `base_result_ref` 让服务端合并。

## 六、数据变更重跑（服务端增量合并，宿主零合并）

> **2026-11-22 更新**：增量合并已进服务端（`base_result_ref`），宿主不再做
> 任何结果合并操作；`revision-brief/revise` 的修订词汇另含
> `basemap`/`online_basemap` 两个 **compile 资源层键**（换底图、加/撤在线底图
> 绑定走 revise，bundle 复用、零 MCP 重跑；冻结后 lock 已存在时不可修订，须新运行）。
> 行程数据（改路线/改点位）仍须走数据修订通道或新运行（见 SKILL.md）。

用户在 G2 前后提出**改路线 / 改行程数据**时，这些是数据层变更，**不走设计修订
通道**（修订词汇不含行程三键：`source_bindings/sources/itinerary_structure` 留在
bundle_input_keys 守卫内），走同运行数据修订通道（v1 仅 `route_legs`）或新运行。
增量成本由工具契约压到"变更部分的真实计算 + 新 G1 + 新 G2"：

1. **地理编码不重新盘问用户**：上一轮 `geocode` 的确认结论（`confirmations`）对未变更
   地点直接可复用；仅新增/改名地点需要新的歧义确认。
2. **路径规划只跑变更腿（服务端合并）**：
   `plan_route({legs: [仅变更腿], base_result_ref: 上一轮 result_ref})` ——
   未变更腿由服务端从持久化文件 verbatim 搬运，返回新的合并 `result_ref`，
   直接传 `itinerary_assemble`。宿主不合并、不转述、不落盘中间结果。
3. **请求重建是机械步骤**：改完 `itinerary-draft.json` → `itinerary_check`
   复检至 `complete` → `request_scaffold` 自动重算全部摘要绑定。
4. 之后走标准链：`intake → brief → 新 G1 → MCP 链 → compile → preview → 新 G2`。

对比：**样式变更**（颜色/字号/图框边线）走 `style_overrides` + 修订通道
（见 `doc/leadership-visit-usage.md` "三"），MCP 数据链整体跳过。

## 七、CLI 运维要点（宿主实测）

1. **长步骤 stdout 混渲染日志**：`preview` / `render` / `validate` 的输出流可能混入
   渲染器日志，管道直接 `json.load` 会失败——输出落文件（`> <step>.out 2>&1`）再解析。
   管道解析失败 ≠ 命令失败：先用 `generate-map status`（无 request 参数）查状态机确认。
   **编码已修复（2026-11-22）**：CLI 入口（carto.py / approval-sign.py）已锁定
   stdout/stderr 为 UTF-8，任何代码页/管道下宿主按 UTF-8 读即可，无须 `-X utf8`
   （带上作双保险亦可）。落盘再解析仍是长步骤日志混流的规避（结构性修复
   `--json-out` 见零脚本方案 §7 搁置表）。
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
6. **宿主不写程序**：draft 校验/请求组装/结果合并/itinerary 组装全部由服务工具
   承载（itinerary_check / request_scaffold / plan_route 的 base_result_ref 合并 /
   itinerary_assemble——大结果一律走 `result_ref` 引用，不内联重述）。宿主产出的
   语义文件只有 `itinerary-draft.json` 一个。审批回执签发用仓库
   `skills/carto-agent/tools/host/approval-sign.py`（密钥在项目目录或环境变量，
   签发前必须已获用户对话批准）。**修订预算**（默认 max_revisions=3、运行时长上限
   1200s，2026-11-22 调宽以容纳人工门节奏）超出时由项目所有者决策调整
   `work/.budget-state.json`（运行级状态，非策略）。

## 八、宿主接入契约（任意宿主零脚本接入）

**宿主四能力**（缺一不可，均为宿主平台原生能力，无需编程）：

| 能力 | 用途 |
|---|---|
| shell 执行 | 调唯一 CLI（`python skills/carto-agent/scripts/carto.py …`）与 `approval-sign.py` |
| MCP 客户端 | 消费六个类型化工具（geocode / plan_route / itinerary_check / request_scaffold / itinerary_assemble / basemap_snapshot） |
| 文件读写 | 摆放材料、撰写 `itinerary-draft.json`、读取步骤输出文件 |
| 用户交互 | 地名歧义确认、G1/G2/review+G3 审批呈请（含外发声明） |

**MCP 服务挂载**（`.mcp.json`，allowed-root = 项目根）：

```json
{
  "mcpServers": {
    "itinerary-tools": {
      "command": "cmd",
      "args": ["/c", "<python.exe>", "-X", "utf8",
               "<repo>/services/itinerary-tools/server.py",
               "--allowed-root", "<项目根绝对路径>"],
      "env": {
        "CARTO_AMAP_KEY": "<高德 key>",
        "CARTO_TIANDITU_KEY": "<天地图 key>",
        "PYTHONPATH": "<repo>/services/itinerary-tools"
      }
    }
  }
}
```

（`--allowed-root` **可选**：不传时默认用进程 cwd 作根——宿主以 cwd=项目根启动即可，
或显式传参钉住项目；路径围栏不变，越界仍拒绝。AMAP key 供 geocode 歧义检测与路由 Plan B。）

**Hermes 宿主专项**（2026-11-22 test3 实测教训）：

1. **MCP 挂载方式不同**：Hermes 不用 `.mcp.json`，用 `hermes mcp add itinerary-tools
   --command <python.exe> --env CARTO_AMAP_KEY=… CARTO_TIANDITU_KEY=… PYTHONPATH=…
   --args -X utf8 <repo>/services/itinerary-tools/server.py --allowed-root <项目根>`
   （`--args` 必须最后；交互提示用 `echo Y |` 应答）。`hermes mcp test itinerary-tools`
   验证连接与六工具发现。`--allowed-root` 可选（默认 cwd）；显式钉住项目时换项目根
   须 `hermes mcp remove` 后重 add。
2. **MCP 工具默认被延迟，必须经 tool_search 发现**：Hermes 的 `tool_search` 分层把
   MCP 工具（toolset 以 `mcp-` 开头）从模型直接工具表撤下，换成 `tool_search`/
   `tool_call` 桥接按需发现（token 预算优化，`tool_search.py` 硬编码）。**宿主须先
   `tool_search` 搜 `itinerary`/`mcp` 找到 `mcp__itinerary_tools__*`，再 `tool_call`
   调用——绝不自写 stdio 客户端脚本**（test3 宿主臆断“no MCP client wired”写了脚本，
   违反零脚本目标；工具其实已注册，只是被延迟）。四能力中的“MCP 客户端”在 Hermes
   即体现为 tool_search/tool_call 桥接。
3. **可选兜底**：若要求 MCP 工具常驻可见、不依赖宿主自觉，设 Hermes config
   `tools.tool_search.enabled: "off"`（全部工具 eager，代价是延迟工具全进提示词）。
4. **Skill 装载**：`tools/host/Install-CartoSkill.ps1 -HermesGlobal -Category creative`
   （全局，任意 cwd 会话可见，须 curator adopt）；`-HermesProjectLocal` 仅 cwd=仓库的
   会话加载（桌面端会话 cwd 通常非仓库，会看不到——test3 即此因，改用全局）。
   装载后须重启会话。CLI 一律从仓库绝对路径跑（经 junction 路径跑 carto.py 会报错）。

**密钥约定**：`.approval-key` / `.attestation-key` 放项目根（32 字节随机 hex，各一
行）；CLI 侧经环境变量 `CARTO_APPROVAL_HMAC_KEY` / `CARTO_RENDER_ATTESTATION_KEY`
注入；MCP 侧 key 在 `.mcp.json` env。真实数据期密钥由审批人持有。

**材料摆放清单**（项目根 = MCP allowed-root）：

```
<项目根>/
  杭州市.png                      # 底图（名字任意，scaffold 传参）
  registration.yaml               # 五字段配准（用户直供）
  data/杭州测试输入1.docx          # 行程 DOCX（data summarize 读 data/）
  fonts/simhei.ttf                 # 可嵌入单面 TTF（fsType 允许嵌入）
  template-repo/                   # 已发布 leadership-visit-map 模板仓库副本
  .approval-key / .attestation-key
```

宿主职责序列（全链路，无一步需要编程）：
`data summarize（CLI）→ 提取草稿（语义）→ itinerary_check → request_scaffold →
intake → brief → G1（用户批准+签发）→ geocode（歧义问用户）→ plan_route →
itinerary_assemble（result_ref）→ compile → preview（呈用户）→ G2 → freeze →
render → check → review（用户批准+签发）→ G3（用户批准+签发）→ deliver。`
