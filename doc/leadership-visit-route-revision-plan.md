# 领导调研图"修改路线"实施方案（数据层变更通道）

- 状态：待用户确认（确认后按 Phase A 起步执行）
- 日期：2026-11-21
- 适用：用户在 preview 阶段提出"某条路线要经过某个点 / 走某条路 / 改行程"类请求
- 性质：本文档是开发与执行计划（`doc/` 只放开发记录，不作为运行时智能体协议；可长期固化的 SOP 归属 `skills/carto-agent/workflows/generate-map/leadership-visit-data-prep.md`，落地需用户批准）
- 前置事实：本方案**零内核代码改动**，唯一新增代码交付物是一组增量合并自动测试（§四）

## 〇、通道选择结论

"改路线"是数据事实变更，不走 `revision-brief/revise` 设计修订通道——修订词汇是封闭白名单
（`revision.py` 的 `rules()` 仅含 `map_title/annotation_layout/page_layout/style_overrides/
basemap/online_basemap`），行程三键 `source_bindings/sources/itinerary_structure` 被刻意排除：
它们喂给 prepared bundle，改它们 = 新运行（`revision.py` 模块 docstring 明文）。
`apply_changes` 对白名单外键抛 `LEADERSHIP_REVISION_UNKNOWN_KEY`，Schema 层
`additionalProperties: false` 同步封死。

因此通道为：**新运行 + 宿主级数据复用**（`leadership-visit-data-prep.md` §六）：

```
geocode(新增地点) → 改 draft → itinerary_check → request_scaffold(新请求/新 run)
→ intake → brief → [G1] → geocode(增量) → plan_route(增量+via_points) → itinerary_assemble
→ compile → preview → 用户目检 → [G2] → freeze → render → check → review → [G3] → deliver
```

## 一、语义分诊（执行第一步）

| 用户说法 | 层 | 通道 |
|---|---|---|
| 路线颜色/线宽 | 设计表达 | `style_overrides.route` → revise |
| 标题/版式/底图/在线底图 | 设计/编译资源 | revise |
| **路线经过 X / 走某条路** | **数据事实** | **本方案** |
| 在 X 加停靠点 | 数据事实（结构变化） | 本方案 + 草稿加 stop |

**途经 vs 停靠必须问用户**（工具链不替宿主判断）：

- **途经（不停留）**：X 体现在 `plan_route` 的 `via_points` 参数（`server.py` 输入契约），
  **不进 draft、图上不出现停靠标记**。因 `via_points` 不是 draft 合同字段，变更意图记录在
  请求 `goal` 字段 + 宿主工作日志（`work/host/`），审计线索由宿主补全；
- **停靠（要停留）**：draft 新增 place（`location` 留空）+ stop，原腿拆为两腿，图上多一个
  定位标记。

"走哪条路"若无法用途经点表达，可用 `strategy`（'0'-'6'）偏好塑形，或多个途经点串接。

## 二、复用边界

| 对象 | 复用方式 | 依据 |
|---|---|---|
| 未变更地点 geocode 结论 | 上轮 `confirmations` 原样带入 | geocode 输入契约显式接受 confirmations |
| 未变更腿道路折线 | 上轮 `results` 按 `leg_id` 保留 | plan_route 输出按腿组织 |
| 底图/配准/字体/模板仓库 | 原文件直用，**不重发 T1/TP** | 模板仓库跨项目复用先例（`--repository-root`） |
| 审批密钥 | 复用 `.approval-key`（回执绑新 scope 不互串） | e2e-2 实测方案 |
| 旧运行全部产物 | **不复用不触碰**，原路径不可变 | 证据链不可变原则 |

**必须重建**：`itinerary.json`（assemble）、generate-request（scaffold，新
run_id/request_id/idempotency_key 自动生成）、prepared bundle、G1、G2。重建全部为本地
机械步骤；唯一真实外部成本 = 新增地点 geocode（±1 轮歧义确认）+ 变更腿 plan_route。

## 三、阶段实施与逐阶段测试

### Phase A：数据事实层（G1 前，零外部调用）

| # | 步骤 | 要点 |
|---|---|---|
| A1 | （仅新增地点）`geocode({places:[X]})` | `needs_input` 多候选 → **候选摆给用户选，不默认第一项**；选定后带 confirmations 重调至 `complete`。X 为既有地点则跳过，坐标取上轮 confirmations |
| A2 | 改 `data/itinerary-draft.json` | 按分诊结果：途经不动 stops/legs；停靠加 place+stop 并拆腿。`geometry`/`location` 留空（工具产出） |
| A3 | `itinerary_check` 复检 | 按字段级错误报告修，复检至 `complete` |
| A4 | `request_scaffold` 生成新请求 | 身份四项必填；`--template-repo-path` 指既有仓库；`goal` 写修订意图（如 `修订：第N腿经停X`） |

**Phase A 测试：**

- **T-A1（交互）**：geocode 歧义路径实测——出现候选时必须完成"用户确认 →
  confirmations 重调 → complete"闭环；复用地点时核对该地点确在上轮结果 `resolved` 列表
  且坐标一致（防张冠李戴）。
- **T-A2（工具）**：`itinerary_check` 返回 `status: complete`，`draft_digest` 记录备查。
- **T-A3（一致性）**：`request_scaffold` 的 `bound_digests.draft` 必须等于 T-A2 的
  `draft_digest`（两者都是规范 JSON 摘要，逐字节一致，有内核等价金样锁定）；
  `registration/basemap` 摘要与上轮相同（材料未动的机械证明）。
- **T-A4（基线）**：`carto schema check` 全过（当前基线 100 个）。
- **T-A5（自动测试）**：跑 `services/itinerary-tools` 测试套件（§四新增用例必须全绿）。

### Phase B：新运行协议链

| # | 步骤 | 要点 |
|---|---|---|
| B1 | `carto generate-map intake / brief` | 全部绝对路径；`--allowed-root` 是 **append 参数**，同时含项目目录 + 模板仓库两根；**intake 后请求指纹锁定，任何改动触发 `JOB_INPUT_DRIFT`** |
| B2 | **[G1]** | 对话中出示审批面（含地名外发高德授权声明——geocode 歧义检测与路由 Plan B 均走 Amap 在线），用户明确批准后经 `tools/host/approval-sign.py` 签发 |
| B3 | MCP 链（增量） | `geocode`（仅新增/变更地点）→ `plan_route`（仅变更腿，带 `via_points`/`strategy`）→ 与上轮 `results` 按 `leg_id` 合并 → `itinerary_assemble`。**itinerary.json 只能由 assemble 原子落盘，宿主不手工改写** |
| B4 | `compile` → `preview` | 长步骤 stdout 混渲染日志（Windows GBK 已知问题）：**输出落文件再解析**；管道解析失败 ≠ 命令失败，先 `generate-map status` 查状态机 |
| B5 | 预览确认环 | 修订版预览路径交给**用户本人目检**（宿主 Read 工具无法显示预览图；且路线已变，上轮"逐字节比对等效验收"不适用）；用户明确答复后才可签 G2。用户提出过修改请求后，每道门恢复逐门确认 |
| B6 | **[G2]** → freeze → render → check → review → **[G3]** → deliver | 每道门先拿用户当次批准再签发；G2 摘要从落盘 `_step_out.json` 尾行 JSON 提取；`delivery-status` 需 `--idempotency-key` |

**Phase B 测试：**

- **T-B1（状态机）**：intake/brief 后 `carto generate-map status`（无 request 参数）确认
  状态就位；之后不触碰 generate-request.yaml（`JOB_INPUT_DRIFT` 由内核强制，验证方式是
  "不改"本身，无需故意触发）。
- **T-B2（回执验签）**：G1/G2/G3/review 回执逐张用顶层 `carto approval verify` 验签
  （注意：是顶层命令，需 `--action/--object-type/--object-digest` + 环境变量密钥）。
- **T-B3（增量正确性）**：plan_route 返回的 `results` 恰含变更 `leg_id`；assemble
  `counts.travel_legs` 与上轮一致（停靠拆腿场景为 N+1，须与分诊预期一致）；
  `geometry_points` 相对基线 2768 的差值应只来自变更腿（量级合理性人工核对）。
- **T-B4（数据级 delta 核对，替代整图字节比对）**：diff 新旧 `map-document.json`
  ——变更腿的 feature 几何必须不同，**未变更腿与停靠的 feature 必须逐字节一致**；
  这是"只有该变的变了"的机械证明。
- **T-B5（人工门）**：用户目检新预览并当次明确批准（G2 的存在意义）。
- **T-B6（终检与交付）**：`check` 11 项全过；交付包五件套齐（map.pdf/map.png/README/
  delivery-manifest/checksums）；`checksums.sha256` 校验通过；`delivery-status` 返回
  `committed`。

### Phase C：收尾

- 新旧运行 delta 报告（腿数/折线长度/停靠数、外部调用次数、审批次数）；
- 项目 README 与记忆更新；若用户批准，把可长期固化的 SOP 细则并入
  `leadership-visit-data-prep.md` §六。

**Phase C 测试：**

- **T-C1（全量回归）**：仓库全量 pytest（基线 684+ passed / 0 failed，含
  `services/itinerary-tools` 套件）+ `carto schema check`——证明零内核改动的声明成立。
- **T-C2（旧运行不可变性抽查）**：执行前后各记录一次旧运行 `previews/` 与 `delivery/`
  的文件摘要，逐一相同。
- **T-C3（delta 报告核对）**：报告中的每个数字可回溯到 T-B3/T-B4 的实测输出。

## 四、新增自动化测试（唯一代码交付物）

落位：`services/itinerary-tools/tests/test_itinerary_assemble.py`（沿用既有 E2E 金样夹具
模式：`fixtures/draft.json + geocode-result.json + route-result.json →
expected-itinerary.json` 逐字节金样，基线 counts = 6 places / 7 stops / 5 travel_legs /
2768 geometry_points）。

新增夹具 `route-result-revised.json`：从 `route-result.json` 派生，仅替换一条腿（如第 3
腿）的 `geometry.coordinates` 为另一条合法折线（同形状合同：LineString + distance/
duration/engine 字段齐全），模拟"plan_route 增量重跑 + 宿主按 leg_id 合并"的输入。

新增用例（`IncrementalRerouteTests`）：

1. **`test_incremental_merge_only_changed_leg_differs`**：用 revised route_result 组装 →
   `status: assembled`；产出按腿拆分比对——**未变更 4 腿的 geometry 与金样逐字节一致，
   变更腿等于新夹具几何**；`travel_legs` 计数不变。这是"增量复用不腐蚀未变更数据"的
   机器证明，也是本方案复用主张的核心锚点。
2. **`test_dropped_leg_in_merge_is_rejected`**：route_result 缺一条腿（模拟宿主合并时
   丢腿的错误）→ `ITINERARY_ROAD_GEOMETRY_REQUIRED` 拒绝且不落盘——把"合并漏项"从
   宿主失误升级为机械可测的失败。
3. **`test_revised_leg_requires_road_geometry`**：变更腿 geometry 换成空坐标/直线退化 →
   拒绝（沿用既有校验路径，防 via_points 输入错误产生假道路折线）。

**已有覆盖、无需新增**（修订通道拒绝行程键的三层守卫，本方案 §〇 的声明依据）：

- Schema 层：`tests/test_a12_revision.py` 的 `test_unknown_change_key_is_rejected` /
  `test_proposal_with_unknown_field_is_rejected`
- 修订图：`tests/test_revision_graph.py` 的 `test_unknown_change_key_rejected`
- 场景层：`tests/test_leadership_visit.py` 封闭 schema 拒绝未知修订键（约 L2146）

## 五、门禁对照（为何每道门不可省）

| 门 | 不可省的根 | 源码/测试依据 |
|---|---|---|
| 新 G1 | 外部事实获取（Amap 外发）+ 新数据摘要必须先进审批面；pending 模式即"G1 批计划 → G1 后产数据" | `request_contract.py` pending 分支；geocode/plan_route 外部调用约束 |
| G1 在 MCP 前 | 外部服务调用须 G1 授权 | SKILL.md leadership_visit 条目 |
| 新 G2 | 旧 G2 批的是旧预览；G2 意义就是审批人审过实际新预览 | 修订工作流规则 |
| 不走 revise | 白名单封闭 + 摘要门：行程键变 → bundle digest 破裂 → 强制重准备，复用红利自动归零 | §四已列三层测试 |

总成本公式：`新增地点 geocode（±1 轮歧义确认） + 变更腿 plan_route + 机械重装配 +
新 G1 + 新 G2`。

## 六、风险与已知运维坑

1. geocode 歧义 → 多一轮用户交互（预期内，非故障）；
2. Windows 代码页混编 → 长步骤输出落文件再解析（已登记已知问题）；
3. 宿主 Read 无法显示预览图 → 用户本人目检（B5 人工门）；
4. `--allowed-root` append 语义漏传模板仓库根 → intake 失败（e2e-2 实测）；
5. `via_points` 不进协议合同 → 审计线索依赖 `goal` 字段 + 宿主日志双记录；
6. 宿主手工改 itinerary.json → 禁止（assemble 是程序步骤，拒绝点名缺项不落盘）。

## 七、验收判据

- 交付：新运行五件套交付、`delivery-status committed`、终检 11 项全过；
- 增量正确性：T-B4 数据级 delta 证明"只有该变的变了"；
- 复用成立：外部调用次数 = 新增地点 geocode + 变更腿 plan_route，无其他；
- 零内核声明：T-C1 全量回归与基线一致；
- 新增测试：§四 3 用例全绿且随套件进入回归基线。

## 八、执行前待用户确认

1. 目标项目目录（`leadership-e2e-2` 或新目录）；
2. 变更腿 + 途经点（地名 + 城市）+ 途经/停靠定性；
3. 是否同步执行 §四新增测试（建议是——它是复用主张的唯一机器证明）；
4. Phase C 后是否把 SOP 细则并入工作流手册（治理文件改动，需单独点头）。
