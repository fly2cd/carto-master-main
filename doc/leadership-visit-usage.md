# 领导调研用图 — 使用说明

> 人类可读的操作入口。机器协议以 `skills/carto-agent/schemas/leadership-visit-generate-request.schema.json`
> 与 CLI `--help` 为准；本文不承载编排逻辑（编排在场景组件 + 内核管线中）。

## 前置条件

1. Python 3.11+ 解释器可用，且已确认：`carto.py --help`、`carto.py schema check` 通过。
2. 渲染依赖可用（matplotlib / PIL / numpy / pyproj）：`carto.py environment probe-renderer`。
3. 模板 `leadership-visit-map@1.0.0` 已发布进项目模板仓库：`create-template` 路由已开放，
   按正式流程（analyze → brief → [T1] → author → validate → [TP] → publish）发布，
   或由项目模板仓库管理员放置。
4. 行程 MCP 工具（`services/itinerary-tools/`）已接线：geocode 需要
   `CARTO_AMAP_KEY`（歧义检测走高德在线）；plan_route 可离线回退。

> 2026-11-20：本文 §三 的 CLI 命令序列已按文字逐字全链路执行通过
> （DOCX → 底图/配准 → G1 → MCP 两工具 → 交付包，六道审批真实签发）。

## 一、准备数据（按目标架构：G1 后执行）

数据准备分两段：**G1 前**只需底图和配准参数（用户直接提供的材料）；**G1 后**、
compile 前由宿主智能体执行 MCP 行程工具链产出 `data/itinerary.json`。

详细操作见场景手册：`skills/carto-agent/workflows/generate-map/leadership-visit-data-prep.md`

### G1 前（用户直接提供）

| 文件 | 来源与要求 |
|---|---|
| 行程 DOCX | 原始行程文件。宿主用 `carto data summarize`（data-summary 网关能力，只读留证据）提取文本 → 从中提取事实草稿 `data/itinerary-draft.json` |
| `basemap.png` | 已配准底图，8-bit PNG。**图片本身不做变形纠正** |
| `registration.yaml` | 底图配准参数：`work_crs`/`origin_m`/`local_km_y_down_to_pixel`/`source_size` |
| `fonts/*.ttf` | 可嵌入 TTF 字体（含 CJK） |

请求的 `source_bindings` 设 `pending: true` + `preparation: "mcp-itinerary-chain"`，
`path` 指向将产出的文件位置（G1 前不要求文件存在）。

### G1 后、compile 前（宿主智能体执行）

1. 调 MCP 工具链（`services/itinerary-tools`，共五个工具）：
   `geocode`（地理编码，**歧义必须询问用户并等待真实回复**，
   不得自行选定或默认第一项）→ `plan_route`（逐腿路径规划，三级回退自动选择）
   → `itinerary_assemble`（把两工具的完整输出合并进 draft，校验齐全后
   原子写出 `data/itinerary.json`；缺坐标/缺折线点名拒绝）；
   工具输入输出与操作流程见场景手册
   `skills/carto-agent/workflows/generate-map/leadership-visit-data-prep.md`
   （G1 前另有 `itinerary_check` 草稿校验与 `request_scaffold` 请求组装两工具，
   摘要计算全部由工具承担）
2. **不得修改 `generate-request.yaml`**：请求在 intake 时已被指纹锁定，
   G1 后任何改动都会触发 `JOB_INPUT_DRIFT`；pending 绑定里的 `source_ref.digest`
   是前瞻声明（scaffold 绑定 draft 摘要，绑定已提取的事实），
   实际数据绑定发生在 G2，经 prepared-data-bundle 摘要锁定真正渲染的数据
3. 进入 compile（内核自动消费合同格式，含 stay 合并/双来源指标/道路折线直通）

**敏感数据边界**：真实领导行程属敏感数据。地理编码涉及向第三方服务发送地点名称，
须在 G1 简报中明确声明后才能执行。真实数据须先完成独立敏感准入送审，或使用脱敏数据。

## 二、组装请求

参照 `skills/carto-agent/schemas/leadership-visit-generate-request.schema.json`（封闭校验：
字段缺失/多余/非法值在 intake 直接拒绝）。要点：

- `geometry: vector`；`template: {kind: map-scenario, id: leadership-visit-map, version: 1.0.0, digest: <包摘要>}`
- `allowed_capabilities` 必须包含 `read, render-preview, geo-to-image-pixels, image-display-bounds`；请求含 `annotation_layout` 时还须包含 `annotation-layout`（编译期注记求解经 ToolGateway 授权执行并留证据回执）
- `itinerary_structure.source_ref` → `data/itinerary.json`；`basemap.image_ref/parameters_ref` → 底图与配准（摘要绑定）
- `source_bindings`：角色 `route-stops` + 字段绑定（`stop-label/visit-date/arrival-time/distance-km/duration-min/itinerary-group`）
- 可选：`page_layout`（纸张/DPI，上限 420×297mm、144–300dpi）、
  `annotation_layout`（注记退火求解参数：`seed/iterations/gap_px`，固定 seed 保证可复现）、
  `style_overrides`（样式补丁：按 group id 改分组颜色、改注记/线宽等表达参数、
  `page_furniture` 改标题/正文字号与图框边线——模板合同仍是缺省来源，补丁只覆盖提及的字段）

## 三、进入制图（唯一入口，内核自动编排）

```bash
COMMON="--project-root . --workdir work --repository-root <模板仓库> --repository-scope local:templates --allowed-root ."
C="python skills/carto-agent/scripts/carto.py generate-map"

$C intake   data/generate-request.yaml $COMMON     # 意图解析 + 请求登记
$C brief    data/generate-request.yaml $COMMON     # 简报 + 源计划
#   [G1] 审批人对 brief 摘要签发 approve-map-brief 回执
$C compile  data/generate-request.yaml $COMMON --approval g1.yaml
$C preview  data/generate-request.yaml $COMMON     # PDF+PNG 预览 + 前端文档
#   [G2] 审批人签发 approve-freeze 回执
$C freeze   data/generate-request.yaml $COMMON --approval g2.yaml
$C render   data/generate-request.yaml $COMMON     # 锁驱动正式渲染
$C check    data/generate-request.yaml $COMMON     # 11 项终检
$C review   data/generate-request.yaml $COMMON --approval review.yaml \
            --recipient-id <收件人> --recipient-type project-user \
            --destination delivery/<批次> --idempotency-key <交付幂等键>
#   [G3] 审批人签发 approve-delivery 回执
$C deliver  data/generate-request.yaml $COMMON --approval g3.yaml
```

**G2 确认阶段的样式修订**（改颜色/字号/图框边线，不碰数据与路线）：preview 后、freeze 前
可走设计修订通道——数据证据复用，只重编译与重预览，须换签 G1 与 G2：

```bash
# 1. 编写 design-revision-proposal（changes.style_overrides.new_value 为样式补丁；
#    map_title/annotation_layout/page_layout 同为合法修订键）
$C revision-brief data/generate-request.yaml $COMMON --proposal restyle-proposal.yaml
# 2. 审批人对修订后 brief 摘要签发新 G1（旧 G1 不批准新修订）
$C revise      data/generate-request.yaml $COMMON --proposal restyle-proposal.yaml --approval g1-rev.yaml
# 3. 用返回的新 request_path 继续 compile → preview → 新 G2 → freeze → render …
```

修订产物写入 `revisions/rN/`，旧候选/预览/回执保持不可变；旧 G2 会被
`APPROVAL_OBJECT_MISMATCH` 拒绝。**路线、底图、行程数据属数据层变更，不走修订通道**，
须开新运行（宿主级复用指引见 `workflows/generate-map/leadership-visit-data-prep.md`）。

中断/失败恢复：`generate-map status / retry / receipts / delivery-status`。
审批说明：G1/G2/G3 由持有审批密钥（`CARTO_APPROVAL_HMAC_KEY`）的审批方对**精确对象摘要**
签发回执；终端命令确认或聊天中的"同意"不构成业务审批。

## 四、产出

```
delivery/<批次>/        正式交付包：map.pdf + map.png + README.md
                        + delivery-manifest.yaml + checksums.sha256
work/previews/<会话>/   预览三件套：map.pdf + map.png + map-document.json（前端成果本体）
.carto/image/   不可变原件：map-documents（前端文档权威版）、page-requests
work/                   可审计链：意图/简报/计划/候选/场景/锁/回执/终检报告
```

样式（分组配色、信息框、注记、页面装饰）来自模板 portrayal 合同的 `image_itinerary` 段；
如需沿用旧框架 1.2.0 的实测参数（偏移 2/8、信息框偏移 45/-135、标题字号等），由模板管理员
在发布时写入合同，不在请求中逐次传参。本次运行想改其中任何样式字段，用请求的
`style_overrides`（首轮即生效）或 G2 前的设计修订通道（见"三"），不需要换模板。

## 五、当前边界

- `production_enabled: false`：合成验收状态，真实数据需完成敏感准入；
- 样式修订通道已开放：颜色/字号/图框边线等设计层参数走 `revision-brief → revise`
  （数据证据复用）；**路线/底图/行程数据修改须新运行**，不进修订通道；
- 模板发布：`create-template` 路由已开放——按"三、进入制图"之前的模板准备流程
  （analyze → brief → [T1] → author → validate → [TP] → publish）把
  `leadership-visit-map@1.0.0` 发布进项目模板仓库后，生成路由即可消费
  （样式合同由 RouteAuthor 内置的旧框架 1.2.0 实测样式值生成，不在请求中逐次传参）；
- 前端 `map-document.json` 已落位 `work/previews/`，正式对外消费随 Part II 产品回路解禁。
