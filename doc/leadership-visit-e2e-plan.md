# 领导调研用图 — 全链路执行跟踪清单

> 目标：在 Claude 宿主会话内，仅通过唯一 CLI（`carto.py`）+ MCP 两工具
> （`geocode` / `plan_route`），从 DOCX 行程文件、底图、配准参数出发，
> 产出带有效审批回执的正式交付包（PDF+PNG+manifest），全程不伪造任何审批。
>
> 状态：**执行中**（2026-11-20 建立）。
> 前置背景见 `doc/leadership-visit-migration-plan.md`；操作细节以
> `skills/carto-agent/workflows/generate-map/leadership-visit-data-prep.md`
> 与 CLI `--help` 为准，本文不承载机器协议。

## 决策记录（2026-11-20 定案）

| # | 问题 | 决定 | 理由 |
|---|---|---|---|
| D1 | 审批签发途径（T1/TP/G1/G2/G3/review 共 6 类回执） | **仓库外审批方辅助脚本**（项目目录内 `approval-sign.py`，读 CLI 输出的 `approval_object_digest` + `CARTO_APPROVAL_HMAC_KEY` 产出回执 YAML） | 不动内核、不违反"不新增审批旁路 CLI"；密钥只在审批方手里；产物用 `carto security approval verify` 验证 || D2 | 首跑数据 | **脱敏数据先跑通**；真实数据后补独立敏感准入送审 | `production_enabled: false`；先闭环验证链路，敏感外发事项仍照常在 G1 简报声明 |
| D3 | 模板来源 | **正式走 create-template 路由发布** `leadership-visit-map@1.0.0`（analyze → brief → [T1] → author → validate → [TP] → publish） | L6 已实现，样式合同由 RouteAuthor 内置旧框架 1.2.0 实测值生成；demo `template-repo/` 仅用于排障，不作为验收产物 |

### D1 两层关系说明（脚本不替代用户确认）

审批分两层，都不可省：

1. **人机决策层**（对话内，agent ↔ 用户）：每到一道门（T1/TP/G1/G2/G3/review），
   agent 停下，向用户展示对象要点 + `approval_object_digest`，明确提问并**等待真实回复**。
   用户的"同意"是决策发生的地方——这层完整保留，与 geocode 歧义确认同构。
2. **签名层**（`approval-sign.py`）：内核不认聊天记录，只认对精确摘要做 HMAC
   签名的回执文件（`--approval g1.yaml`）。脚本把"用户的同意"转成机器可验证的回执。

```
agent: brief 完成 → 展示简报要点 + approval_object_digest → 提问"是否批准 G1？" → 等待
用户:  回复"同意"                                  ← 决策在这里发生
agent: （仅在收到同意后）签发 g1.yaml → compile --approval g1.yaml（内核验签）
```

**密钥纪律（防 agent 跳过询问自行签发）**，按数据敏感度分两档：

- **真实数据**：`CARTO_APPROVAL_HMAC_KEY` 不交给 agent。用户在自己的终端跑
  `approval-sign.py`；agent 只负责给出 digest 和现成命令。签名权威 = 密钥持有者。
- **脱敏数据（首跑，D2）**：允许 agent 代跑签发脚本，但必须先在对话中拿到用户
  明确的批准回复，且该回复（引用 + 时间）记入执行日志后才可签发。

纪律：`tests.test_general_thematic.sign` 与 demo 签发代码**不作为生产审批路径**；
agent 在任何情况下不得未经用户明确批准回复就调用签发脚本。
如需变更任一决策，直接改本表并同步受影响阶段。

## 总体顺序

先修误导文档 → 补审批签发途径 → 跑通 E2L → 跑通后修入口文档 → steward 评审 → 一次性提交。
策略文件（`scenario-capabilities.yaml` / `tool-bindings.yaml` / `SKILL.md`）在 steward 评审前冻结不动。

---

## 阶段 0：环境预检（约 0.5h）— 2026-11-20 执行完毕

- [x] `carto.py --help`、`carto.py schema check` 通过（**100 个** Schema 全过，
  超出预期 92——工作区新增的 8 个 image/data Schema 已计入）
- [x] `carto.py environment probe-renderer`：`status: available`；CJK 字体
  （Noto Sans SC/SimHei/SimSun）、PDF/PNG/SVG 导出、16k 画布上限全绿；
  Python 3.13.15
- [x] python-docx 可导入（matplotlib 3.11.0 / PIL / pyproj / numpy 同步确认）
- [x] MCP 服务 `services/itinerary-tools` 可达并实测：geocode 歧义检测正常
  （西湖 → needs_input 同名多址）、plan_route 走离线 dual_graph 正常（16.3s 首载）
- [ ] **改 `.mcp.json` 的 `--allowed-root`**：→ **顺延到阶段 3**（真实项目数据目录
  尚未建立，建目录时一并改）
- [x] AMAP key 结论（修正原假设）：**`CARTO_AMAP_KEY` 是 geocode 的必需项**
  （歧义检测本身走高德在线，不只是路由 Plan B）；plan_route 可离线回退。
  key 已在本地 `.mcp.json`（gitignore 已忽略，不入库）

**阶段 0 发现并修复的宿主接入 bug（2026-11-20）**：MCP server 两工具的
`inputSchema` 只声明了 `{"type": "object"}`（无属性类型），Claude 宿主客户端
对无类型声明的数组参数会序列化成 JSON 字符串发送，服务端 `geocode()` 报
`string indices must be integers, not 'str'`（demo 用 mcp SDK 直传 dict 故未暴露）。
修复（[server.py](../services/itinerary-tools/server.py)）：① 声明完整带类型的
inputSchema（主修复）；② `call_tool` 入口防御性反序列化字符串参数。
已验证：原生 dict 形态无回归（geocode 歧义 + dual_graph 路由均正常）；
字符串形态现在返回明确的 Schema 校验错误而非崩溃。
**待办**：宿主会话内 MCP 连接仍跑旧代码，需在 VS Code 里 `/mcp` 重连
`itinerary-tools` 后由宿主端再次真实调用 geocode 验证修复闭环（阶段 5 前完成即可）。

解释器：`D:/software/anaconda/python.exe`（3.13.15）。

## 阶段 1：修正 usage doc 两处误导（约 0.5h）— 2026-11-20 执行完毕

- [x] `doc/leadership-visit-usage.md` §一"G1 后、compile 前"：旧四工具链
  （`itinerary.check → geocoding.resolve → routing.plan → itinerary.finalize`）
  改为两工具模式（geocode 歧义必须问用户 + plan_route + 宿主手工组装
  `itinerary.json`），与 data-prep 手册对齐
- [x] 同节"更新请求的 `source_ref.digest`"改为：G1 后**不得**修改
  generate-request.yaml（`JOB_INPUT_DRIFT`）；digest 是前瞻声明（填 draft 摘要），
  实际数据绑定发生在 G2 的 prepared-data-bundle
- [x] 全文复查：无四工具链/digest 更新说法残留（grep 验证）

SKILL.md / routing.md 的"只注册一个场景"过时描述留到阶段 6（steward 领地，等跑通后描述已验证的事实）。

## 阶段 2：审批签发途径（D1：仓库外辅助脚本）— 2026-11-20 执行完毕

**脚本位置**：`d:/workspace/project_1/IGSA_1118/leadership-e2e/approval-sign.py`
（项目目录 `leadership-e2e/`，仓库外，已定案）。

**用法**（审批方或经用户批准的 agent 执行）：

```bash
cd d:/workspace/project_1/IGSA_1118/leadership-e2e
python approval-sign.py <gate> <approval_object_digest> --request data/generate-request.yaml
# gate ∈ {g1, g2, g3, review, t1, tp}；产出 <gate>.yaml
# --request 自动提取 approver_subject_id / tenant_id / scope / environment
# 密钥：环境变量 CARTO_APPROVAL_HMAC_KEY 优先；否则 ./.approval-key（已生成）
# 验签：carto.py approval verify <gate>.yaml --allowed-root <绝对路径> --action …
```

**实现要点**：直接 import 仓库 `carto_core` 的 `ApprovalReceipt` / `sign_receipt` /
`atomic_yaml` / `load_document`——不自建平行加密实现，保证与内核验签逐字节一致。
门与动作绑定复用内核 `workflow/approvals.py` 的 GATES 定义（g1→approve-map-brief/
map-brief、g2→approve-freeze/resolved-map、g3→approve-delivery/delivery-manifest、
review→approve-product-review/validation-report、t1→approve-template-brief/
template-brief、tp→approve-template-publish/template-publication）。

- [x] `approval-sign.py` 实现（含 `--request` 身份自动提取、TTL 可配、
      重签覆盖确认、nonce uuid4 防重放）
- [x] `CARTO_APPROVAL_HMAC_KEY`：已生成 32 字节随机密钥 →
      `leadership-e2e/.approval-key`（不入库；真实数据期移至用户私有位置）
- [x] 验签闭环：`carto approval verify` 对签发产物返回 `{"ok": true, "verified": true}`
- [x] 负向测试：错误密钥验签被拒（`APPROVAL_SIGNATURE_INVALID`）——HMAC 绑定有效
- [x] 交互协议落地：脚本头部与 D1 两层关系说明写明纪律（签发前必须有用户明确批准）
- [x] 脚本位置与用法记录于本节
- [ ] `--request` 自动提取路径待阶段 5 用真实请求实测（无请求文件时用手动参数）

## 阶段 3：项目与模板准备 — 2026-11-20 执行完毕

- [x] 项目目录 `leadership-e2e/` 建立：`data/杭州测试输入1.docx`、
      `basemap.png`（6083×4490 RGBA，36.5MB）、`registration.yaml`（transform.json
      五字段直拷）、`fonts/simhei.ttf + simkai.ttf`（用户材料中的 .ttc 集合不可嵌入，
      经确认换用 C:\Windows\Fonts 单面 TTF，fsType 可嵌入、CJK 无缺字）
- [x] **像素摘要逐字节匹配**：`source_pixel_digest(basemap.png)` ==
      transform.json 声明的 `ede3d1d0…`（底图与配准参数为配对原件）
- [x] `.mcp.json` `--allowed-root` 已改为 `leadership-e2e`（宿主重连后生效）
- [x] 按 D3 走 create-template 路由发布 `leadership-visit-map@1.0.0`：
      - `analyze`：合成 3 停靠点 fixture + source-manifest（合成验收声明）
      - `brief` → **[T1]** 用户批准（对话确认）→ `approval-sign.py` 签发 →
        `author`（RouteAuthor 内置旧框架 1.2.0 实测样式）
      - `validate`：**passed**（真实 `image-itinerary-page` 渲染器，合成样张
        PDF+PNG，7 项静态检查过）
      - **[TP]** 用户批准（对话确认）→ 签发 → `publish` 成功，
        `template-repo/` 已有 `template-index.yaml`
- [x] 渲染 attestation 密钥 `.attestation-key` 已生成（`CARTO_RENDER_ATTESTATION_KEY`）
- [x] 验证：发布条目 `leadership-visit-map@1.0.0`（digest `sha256:05613990…`）

## 阶段 4：数据准备与请求组装 — 2026-11-20 执行完毕

- [x] `carto data summarize`：DOCX → `data-summary.md`（evidence artifact 已留证据，
      `.carto/data/evidence/tool-data-summary/1.0.0/`）
- [x] 宿主读摘要提取事实草稿 `data/itinerary-draft.json`：6 places（含 geocoding_query）/
      7 stops（淳安拆 meal+visit 两个 stop，stay 腿连接）/6 legs（5 travel + 1 stay，
      document_metrics 从原文提取：43km/45min、113km/120min、41.5km/45min、44km/35min、87km/75min）
- [x] 组装 `generate-request.yaml`（pending 模式：`source_bindings[0].pending=true` +
      `preparation: "mcp-itinerary-chain"`，digest=前瞻声明填 draft 摘要；
      basemap/registration 摘要绑定；A3 420×297 @200dpi；4 个 allowed_capabilities）
- [x] 封闭校验自查：`carto schema validate leadership-visit-generate-request` 通过
- [x] `generate-map intake`：意图 `leadership_visit` ready，请求指纹锁定
- [x] `generate-map brief`：source_plan 的 route-stops 为 pending（无 path_digest，
      pending 生效）；basemap 摘要 `sha256:4447db3c…` 绑定；状态 `compile waiting_approval`

## 阶段 5：CLI 全链路执行 — 2026-11-20 执行完毕 ✅

- [x] `intake`：意图解析为 `leadership_visit`，请求指纹锁定
- [x] `brief`：source_plan route-stops 为 pending（无 path_digest）
- [x] **[G1]**：用户对话批准（含 6 地点名外发高德的敏感事项声明）→
      `approval-sign.py --request` 签发（自动提取身份实测通过）
- [x] MCP `geocode`：宿主端真实调用——**阶段 0 修复闭环验证**（/mcp 重连后
      类型化 Schema 生效）；6 地点全歧义 → 展示候选 → 用户确认"全部按推荐" →
      confirmations 重调 complete
- [x] MCP `plan_route`：5 travel 腿全部 dual_graph 离线路网（2768 折点）
- [x] 宿主组装 `data/itinerary.json`（6 places / 7 stops / 5 折线；
      `_phase5_assemble.py`）；**generate-request.yaml 未改动**
- [x] `compile`（G1 消费）→ `preview`：预览三件套（PDF+PNG+map-document.json），
      agent 目检通过（标记/路线/信息框/图例/标题正常）
- [x] **[G2]**：用户对话批准 → 签发（摘要经 `freeze_object_digest` 从持久化
      artifacts 复算）→ `freeze` → `render`（锁驱动，3307×2339 正式渲染）
- [x] `check`：**终检 passed**
- [x] `review`：用户对话批准 approve-product-review → 交付清单冻结
- [x] **[G3]**：用户对话批准 → 签发 → `deliver`：**原子交付成功**
- [x] 验收产物：`delivery/leadership-e2e/` 五件套（map.pdf 33.6MB + map.png
      10.4MB + README.md + delivery-manifest.yaml + checksums.sha256）；
      `work/previews/` 三件套；`delivery-status` 查询 `committed`/`receipt-written`，
      事务/回执/manifest 摘要链完整

**成功标准达成**：从 DOCX 到交付包全程只经 CLI + MCP 两工具，
T1/TP/G1/G2/review/G3 共 6 道审批回执全部经用户对话批准后真实签发，终检全过。

**执行备注**：
- render/preview 等长步骤的 stdout 会混入渲染日志——CLI 输出落文件再解析
  （首次 preview 因管道解析失败误判，实际已成功，状态机可查）；
- G2 摘要可从持久化 artifacts（generate-request + resolved-map + preview-evidence）
  用内核同源函数 `freeze_object_digest` 复算，无需依赖一次性 stdout。

## 阶段 6：跑通后收口 — 2026-11-20 执行完毕 ✅

- [x] `skills/carto-agent/SKILL.md` §"当前阶段边界"："只注册一个场景"→"已注册两个业务场景"
      （更正策略版本 v1.7.0→v1.8.0），新增 `leadership_visit` 条目（能力档案、pending
      模式、MCP 两工具、敏感边界）；§"业务场景"末行登记表同步
- [x] `skills/carto-agent/workflows/routing.md`：路由表 create-template/generate-map
      两行登记 leadership_visit；能力声明节新增第二场景段落（v1.8.0）
- [x] usage doc：前置条件 3 更新（create-template 路由已开放的正式发布流程）+ 新增
      前置条件 4（MCP 工具与 AMAP key 依赖）+ E2E 实测标注（2026-11-20 CLI 序列
      逐字跑通）；§五边界段落精简去 L6 挂账
- [x] `schema check`：100 个全过
- [x] 全量回归：**684 passed / 7 skipped / 0 失败**（与基线完全一致，零新增失败；
      警告均为弃用 FutureWarning），耗时 18 分 12 秒
- [x] **冻结策略文件**：scenario-capabilities / tool-bindings / SKILL.md 自此刻起
      到提交前不再改动（阶段 7 挂起，用户暂不提交）

## 阶段 7：steward 评审 + 一次性提交（约 0.5 天）

- [ ] 向策略 steward（`.github/CODEOWNERS`：`@liudakemgslab`）提交评审包：
  85 行策略 diff（按"进 digest 的语义字段 vs 披露字段"分列）+ SKILL.md diff +
  测试与 E2E 证据索引
- [ ] 评审通过后一次性提交全部工作区改动（94+ 文件），分支 `feat/p3-框架调整`，
  提交信息按仓库惯例（中文、主题标注）
- [ ] 治理提示：评审范围小且干净——仓库内无既有冻结运行（真实运行在仓库外 demo 目录），
  本次评审只判断新 profile 语义，无迁移成本

---

## 执行日志

| 日期 | 事项 | 结果 |
|---|---|---|
| 2026-11-20 | 建立本清单；定案 D1（仓库外签发脚本）/ D2（脱敏先跑）/ D3（正式发布模板） | — |
| 2026-11-20 | 阶段 0 环境预检执行 | 6/7 项通过；schema check 100 个全过；renderer available；MCP 实测 geocode 歧义+dual_graph 路由正常；`.mcp.json` allowed-root 顺延阶段 3 |
| 2026-11-20 | 阶段 0 抓到并修复宿主接入 bug：MCP inputSchema 无类型 → 宿主字符串化数组参数 → `string indices` 崩溃；server.py 已声明完整 Schema + 防御性反序列化，原生形态无回归 | 待 `/mcp` 重连后宿主端复验（阶段 5 前完成即可） |
| 2026-11-20 | 阶段 1 usage doc 修正：§一改为两工具模式（歧义必须问用户、宿主手工组装 itinerary.json）、G1 后禁改请求（JOB_INPUT_DRIFT）、digest=前瞻声明；grep 复查无残留 | 完成 |
| 2026-11-20 | 定案项目目录 `leadership-e2e/`（新建）+ 全新生成审批密钥 | — |
| 2026-11-20 | 阶段 2 签发脚本 `approval-sign.py` 实现并验证：正/负向验签均通过（内核 `carto approval verify`）；密钥已生成 .approval-key；--request 提取留待阶段 5 实测 | 完成（1 项留阶段 5） |
| 2026-11-20 | 阶段 3 完成：项目结构建立（.ttc→TTF 换字体）、registration.yaml 五字段 + 像素摘要逐字节匹配、.mcp.json allowed-root 改指 leadership-e2e、create-template 全路由走通（T1/TP 均经用户对话批准后签发），模板 leadership-visit-map@1.0.0 发布进 template-repo | 完成 |
| 2026-11-20 | 阶段 4 完成：data summarize → 宿主提取 draft（6 places/7 stops/6 legs）→ pending generate-request 组装 → schema validate 通过 → intake（leadership_visit ready）→ brief（route-stops pending 生效） | 完成 |
| 2026-11-20 | 阶段 5 完成：/mcp 重连后宿主端 geocode 修复闭环验证（6 地点全歧义→用户确认→complete）；plan_route 5 腿 dual_graph 2768 折点；组装 itinerary.json（请求未改）；G1/G2/review/G3 均经用户对话批准后签发；compile→preview→freeze→render→check(passed)→review→deliver 原子交付成功 | **全链路跑通** |
| 2026-11-20 | 阶段 6 完成：SKILL.md/routing.md/usage doc 三文档登记第二场景（含 v1.8.0 版本更正、L6 挂账清除）；schema check 100；全量回归 684 passed/7 skipped/0 失败（与基线一致）；策略文件冻结 | 完成 |
| 2026-11-20 | 阶段 7 挂起：用户暂不提交（steward 评审与提交等提交意愿明确后再执行；评审条件干净——仓库内无既有冻结运行） | 挂起 |
