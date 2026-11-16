# Carto Agent 多人协作分工与治理方案

> 2+1 最小风险结构 · 接口即契约 · 机器强制优先于人约定

| 项目 | 内容 |
|---|---|
| 编写日期 | 2026-11-16（Asia/Shanghai） |
| 基线 | U-P3.7 分支（a8eb0f7）：612 项回归全绿、schema check 88 项通过 |
| 性质 | 协作治理方案；文件清单与依赖数据均为当日源码实测，标注【源码事实】/【设计推断】 |
| 配套文档 | [设计原则](../design-principles.md)、[全要素路线图](../全要素制图能力补齐路线图.md)、[双分支整合计划](dual-branch-tool-integration-plan.md)、[AGENTS.md](../../AGENTS.md) |

---

## 一、目标与第一性原理

多人协作不因为"人多"而混乱，只因为**并发修改共享可变状态**而混乱。本仓库有三类共享可变状态，对应三个治理维度：

| 共享状态 | 混乱形式 | 治理手段 |
|---|---|---|
| 代码文件 | 合并冲突、互相踩脚 | 所有权边界划分（第三节） |
| 契约（Schema/协议语义） | A 改字段 B 不知情，运行时炸 | 契约冻结 + 版本化（第二节） |
| 基线（测试/摘要） | "我以为好了" vs 实际烂了 | 守卫测试机器强制（第二节） |

**核心原则**：能被机器强制的绝不靠约定；必须靠人评审的绝不默许。跨域争议的最终裁决依据是守卫测试和 Schema 校验结果，不是讨论共识。

---

## 二、既有协作资产【源码事实】

以下机制已在代码中建成，是分工的起点而非待办：

1. **边界已由测试机器强制**。[test_layer_ports.py](../../skills/carto-agent/scripts/tests/test_layer_ports.py) 以 AST 遍历强制内核五层（compiler/contracts/validation/repository/security）对 workflow/adapters 的 import 归零——其自述："运行时没人拦你，这些测试就是执法者"。配套 [test_encapsulation.py](../../skills/carto-agent/scripts/tests/test_encapsulation.py)（封装棘轮，只紧不松）与 test_digest_coverage.py（摘要覆盖缺口）。
2. **契约即法律**。88 份 JSON Schema 全部 `additionalProperties: false`，未知字段默认拒绝；每个协议强制合法/非法样例 + 自动测试三件套。契约漂移在测试阶段即被拦截。
3. **脊柱实证**。errors.py 被 82/103 个文件引用，canonical.py、schema_registry.py 各 54——这三个文件改一行全仓重验，"脊柱冻结"是数据支撑的必然而非官僚流程。
4. **唯一入口纪律**。单一实现根 `skills/carto-agent/` + 单一 CLI + AGENTS.md 入口约束 + scenario_registry 白名单准入，机制上杜绝第二套并行实现。
5. **回归基线**。612 项测试全绿（geo313 环境）+ `schema check` 88 项，是任何 PR 的合并门槛。

---

## 三、三人分工表（2+1 结构）

### 3.1 总览

| | **P1 数据接入与准备** | **P2 版式·渲染·出图** | **P3 内核编排与集成（守门人）** |
|---|---|---|---|
| 使命 | 把原始数据变成冻结的 `prepared-data-bundle` | 把冻结 bundle 变成 PDF/PNG 成果 | 拥有脊柱与门禁，唯一合并权 |
| 核心交付 | 数据快照、准备报告、表达编码目录 | RenderScene、RenderReceipt、页面渲染 | 契约注册、审批协调、回归基线、发布 |
| 接口纪律 | 只写自己领地；产出以 Schema 冻结 | 只消费冻结产物，不回头读原始数据 | 全域只读 + 唯一 merge 权限 |
| 审批角色 | G1 前数据事实核验 | G2 前候选/预览质量 | T1/TP/G1/G2/G3 门禁协调与终验 |

### 3.2 P1 领地（写权限，文件级）

```
carto_core/workflow/   # 数据准备侧 10 文件
  data_preparation.py  map_data_preparation.py  preparation_bundle.py
  preparation_services.py  data_adoption.py  raster_preparation.py
  vector_preparation.py  thematic.py  material_extraction.py  material_evidence.py
carto_core/adapters/   # 外部数据接入 5 文件
  geospatial_mcp.py  mcp.py  mcp_stdio.py  tool_gateway.py  host_probe.py
carto_core/compiler/   # 表达编码侧 7 文件
  portrayal_resolver.py  raster_portrayal.py  vector_portrayal.py
  raster_legends.py  expression_validator.py  thematic_design.py  appearance.py
schemas/               # 数据契约
  raster-input / vector-input / prepared-data-bundle / bundle-inputs /
  raster-classification-{request,answers} / raster-prepared-data / vector-prepared-data /
  thematic-{design,attribute-join} / material-source / data-{facts,role,preparation-task}
policies/
  tool-bindings.yaml  data-preparation-policy.yaml  map-expression-catalog.yaml
tests/                 # 新增仅限本域命名
  test_raster_*  test_geospatial_*  test_vector_*  test_material_*
```

**P1 待办主线**：W6-A 表达扩展（quantile/jenks/diverging/graduated-symbol，现仅 3 种）；双分支整合批 C（geocoding/routing + W9 外部服务准入）；W4 文档/OCR（`material_extraction.py` 的 `BaseExtractor` 已预留）。

### 3.3 P2 领地（写权限，文件级）

```
carto_core/compiler/   # 版式与页面侧 8 文件
  layout.py  grid_layout.py  page_bindings.py  raster_page_contract.py
  vector_page.py  raster_scene.py  vector_scene.py  chart_core.py
carto_core/adapters/   # 渲染侧 9 文件
  page_renderer.py  raster_renderer.py  static_page_renderer.py
  webmap_renderer.py  formal_renderer.py  controlled_renderer.py
  render_backend.py  renderer_probe.py  svg_compositor.py
schemas/               # 页面与渲染契约
  page-{request,output} / render-{scene,receipt,attempt} /
  resolved-{layout,appearance,portrayal,map} / cartography /
  grid-parameters / page-bindings / chart / formal-render-evidence / encoding-ir
tests/                 # 新增仅限本域命名
  test_s1ab_*  test_s1cd_*  test_layout_*  test_chart_*  test_labels_*
```

**P2 待办主线**：W7-B 海报场景（自由构图/整版合成/CMYK——须先过 design-principles 评审）；双分支整合批 A/B/D（见第六节）；矢量正式准入的样张矩阵。

### 3.4 P3 领地（写权限 + 唯一合并权）

```
carto_core/            # 脊柱与注册表
  cli.py  errors.py  canonical.py  schema_registry.py  scenario_registry.py
  backend_registry.py  artifacts.py  roadmap.py  geospatial_deps.py
carto_core/security/   # 5 文件全量
carto_core/repository/ # 8 文件全量
carto_core/validation/ # 4 文件全量
carto_core/contracts/  # 端口契约包（4 文件）
carto_core/workflow/   # 编排与治理侧 19 文件
  map_generation.py  map_planning.py  map_render.py  map_preview.py
  map_final_check.py  map_delivery.py  state_machine.py  revision_graph.py
  budget_store.py  agent_runtime.py  approvals.py  intent.py  static_assets.py
  template_{workflow,analysis,brief,author,validation}.py
carto_core/scenarios/  # 场景准入（4 文件）
schemas/               # 脊柱契约（需会审）
  common / job-state / step-receipt / approval-receipt / state-transition /
  capability-roadmap / scenario-capabilities / manifest / delivery-* / template-*
policies/
  security-policy.yaml  intent-profiles.yaml  checker-registry.yaml
  scope-baseline.yaml  capability-roadmap.yaml  baselines/
tests/                 # 共享守卫与基建
  test_layer_ports.py  test_encapsulation.py  test_digest_coverage.py
  test_schemas.py  test_security.py  test_scenario_*  test_candidate_*
doc/  plan/  dev-log/  AGENTS.md  README.md（变更公告）
```

### 3.5 冻结资产（任何人不得单独改）

| 资产 | 证据（2026-11-16 实测） | 修改规则 |
|---|---|---|
| `errors.py` | 被 82/103 文件引用 | 全员会审 + 全量回归 |
| `canonical.py`、`schema_registry.py` | 各被 54 文件引用 | 全员会审 |
| `schemas/common.schema.json`、`cli.py` 骨架 | 脊柱契约 | P3 提案 + 会审 |
| 守卫三测试（layer_ports/encapsulation/digest_coverage） | 边界执法者 | 只紧不松（棘轮） |
| `policies/baselines/` | digest 基线 | 随契约升级同步，禁止单独动 |

### 3.6 三条铁律【设计推断，源自项目既有决策】

1. **接口即契约**：P1 与 P2 之间只通过冻结 Schema 交互（prepared-data-bundle / render-scene），禁止 import 对方内部模块——layer_ports 守卫会抓住违规。
2. **脊柱冻结**：高 fan-in 文件（3.5 节清单）修改需全员会审，禁止夹带在功能 PR 中。
3. **测试归属**：共享测试基建归 P3；P1/P2 只新增本域测试文件，避免测试文件互踩。

---

## 四、CODEOWNERS 落地

将 3.2-3.4 节的领地清单写入仓库根 `CODEOWNERS`（两个 GitHub 远程均原生支持），PR 自动要求对应域的负责人评审——把铁律变成机器强制。骨架：

```
# P3 脊柱（默认所有 PR 至少 P3 评审）
*                           @p3-owner
/skills/carto-agent/scripts/carto_core/{cli,errors,canonical,schema_registry,...}.py  @p3-owner
/skills/carto-agent/scripts/carto_core/{security,repository,validation,contracts}/    @p3-owner
/skills/carto-agent/scripts/tests/test_{layer_ports,encapsulation,digest_coverage}.py @p3-owner
/skills/carto-agent/schemas/{common,job-state,step-receipt,approval-receipt,manifest}.schema.json  @p1-owner @p2-owner @p3-owner

# P1 / P2 领地（按 3.2 / 3.3 节文件清单逐条展开）
...（同分工表）
```

---

## 五、开工前置任务

### 5.1 任务一：拆分 cli.py【开工第一件事，P3 主导】

**现状**（452 行单文件【源码事实】）：`build_parser()`（L34-212）一个函数注册全部 8 个命令组约 30 个子命令；`main()`（L215-442）一条巨型 if/elif 链分发。P1 加 `data geocode` 要同时改 L85-117 与 L260-321；P2 改 render 参数要碰 L151-212 与 L322-394——三人的改动全落在同一文件的两个函数体，每次合并都是文本级冲突。

**拆分的三层含义**：

1. **注册按域拆**：8 个命令组的 `add_parser` 段落拆成每域一个注册函数（`register_data_commands(sub)` / `register_generate_commands(sub)` / `register_template_commands(sub)` / `register_governance_commands(sub)`）。
2. **分发拆 handler**：main 里 230 行连续 `if...return` 改为"每域一个 handler 函数 + 映射表"（或 argparse 的 `set_defaults(func=...)` 惯用法）；异常处理壳保持唯一。
3. **物理拆文件**：彻底消除同文件编辑，`cli.py` 退化为约 60 行骨架：

```
carto_core/cli/
├── __init__.py      # build_parser 组装壳 + main 异常壳（P3 独占）
├── data.py          # register_data_commands + handle_data（P1）
├── generate.py      # generate-map 命令组（P3；P2 扩展渲染参数时改这里）
├── template.py      # create-template 命令组（P3）
└── governance.py    # schema/security/approval/intent/environment（P3）
```

**验证方式**（零行为变更的纯结构重构）：
- 拆分前后 `carto --help` 及各子命令 help 全树输出逐字节对比一致；
- 612 项全量回归 + `tools/host/Invoke-CartoHostCases.ps1`（26 条 CLI 契约用例）全绿；
- `pyproject.toml` 的 `carto = "carto_core.cli:main"` 入口不变。

### 5.2 任务二：分支与合并纪律

- 每人从 U-P3.7 拉短命分支：`feat/p1-<主题>`、`feat/p2-<主题>`、`feat/p3-<主题>`，PR 回 U-P3.7；避免长命分支漂移。
- P3 是唯一合并者；合并门槛 = `schema check` 88 ok + 全量回归（日常 .venv 597 项即可，合并前 P3 用 geo313 跑 612 项终验）。
- PR 须只碰本人领地路径（`git diff --stat` 路径前缀可机械检查）；跨界改动先在 PR 描述中声明并邀对方评审。

---

## 六、能力迁入与待办映射

### 6.1 双分支整合批 A（第一批，P2 主责）【源码事实，定义于双分支整合计划 P3 节】

**背景**：上游仓存在两个工作副本——主线（本仓库，准入模型 + Schema 契约）与 merge_20261109 分支（已实现领导调研/海报，if/elif 硬编码）。实测治理内核零差异、能力面正交，整合策略为插件化迁入（37 个候选文件三分类），不做文件级大合并。

**批 A 的七个文件**（全部来自 merge 分支 adapters/workflow 工具层，领导调研"影像底图叠加"能力的地基）：

| 文件 | 功能 |
|---|---|
| `basemap/metadata.py` | 配准底图元数据读取（尺寸/范围/配准信息） |
| `basemap/fit.py` | 底图缩放适配（DPI/尺度分档判定） |
| `basemap/transform.py` | 底图配准变换 |
| `image_display.py` | 图像显示边界计算 |
| `image_layout.py` | 图像版式 |
| `geo_to_image_pixels.py` | 地理坐标 → 配准后图像像素换算 |
| `geo_to_original_pixels.py` | 地理坐标 → 原始图像像素换算 |
| `notices.py` | NOTICE/来源许可声明的图面落版 |

**排第一的判据——"无外部依赖"**：四批按依赖类型划分，批 B 依赖标注求解器（退火算法）、批 C 依赖联网外部 API（高德 geocoding/routing，涉及凭据/超时/fail-closed 网络纪律）、批 D 依赖文档解析框架；批 A 全部是纯本地确定性计算，迁入后能最快跑通整合流程，给后续三批当模板。

**迁入标准动作（七步）**：注册 capability_id → 绑定 authorization_policy → 补合法/非法 fixture → 补单元测试 → 跑定向测试 → 跑全量回归 → 提交。

**两个前置注意**：
1. `basemap/fit.py` 迁入前先修 bug：`elif scaling_factor > 1.02` 分支永不可达（被前置 `>= 0.98` 覆盖），硬编码阈值（150 DPI / 0.5 偏差）移入 policy 声明。
2. 迁入后在 `capability-roadmap` 标 `not_implemented`、策略默认拒绝——**代码存在不等于能力开放**，正式可用须等 P4 接入场景准入。

### 6.2 其余批次与波次的角色映射

| 待办 | 内容 | 主责 |
|---|---|---|
| 整合批 B | 标注求解器（annotation_solver/annotation_layout 双层结构，禁止合并为单模块） | P2 |
| 整合批 C | 联网能力（geocoding/routing，须先修 artifact 落盘与 schema 放宽问题） | P1 |
| 整合批 D | 解析与显示（file_parser/geo_layer_builder/route_display，须清除静默默认） | P2 |
| W6 | A 场景表达扩展 + 符号版面 + 矢量正式准入 | P1（表达）+ P2（版式样张） |
| W7 | B 海报场景（自由构图/整版合成/印刷输出，须先过 design-principles 评审） | P2 |
| W8 | C 领导调研场景（行程语义/时间/披露） | P1（数据）+ P2（渲染）+ P3（准入） |
| W9 | G1 地理编码 + 求路（外部服务独立轨道） | P1 |

---

## 七、协作规则与检验信号

### 7.1 已知注意事项

- `map_generation.py`（1530 LOC）在 P3 领地但 P1/P2 高频触碰——改它一律走 PR，不直推。
- `scenarios/` 当前只有 general 场景；W6-W8 接入时新场景测试按 `test_<场景>_*` 命名。
- **横切点清单归 P3 维护**：W3 教训已写明"几何家族是全链贯穿约束，5 处隐藏横切 schema 同步"——新增几何/帧类型前先做横切点盘点。
- 每周一次同步会：脊柱文件清单 + 横切点清单过一遍。

### 7.2 检验信号（乱没乱，看这五条，可证伪）

- **守卫测试绿** = 分层边界没破（layer_ports/encapsulation）；
- **schema check 88 ok + 回归全绿** = 契约没漂移；
- **PR 只碰本人领地路径** = 所有权没侵蚀；
- **脊柱文件改动都有会审记录** = 命脉受控；
- 反向信号：merge 冲突频发、测试互相打红、"改策略让请求通过"——出现任何一个，说明上述某层失守，回到对应层修机制而不是加流程。

---

## 八、配速建议（前两周）

1. **Day 1-2（P3）**：拆分 cli.py（第 5.1 节方案）+ 落地 CODEOWNERS + 约定分支规范。
2. **并行开工**：P1 从 W6 表达扩展起步（纯增量、收益最快）；P2 从整合批 A 起步（无外部依赖、独立可回归）。
3. **周末检查点**：以 7.2 节五条信号做第一次协作健康度复盘。

---

**总结**：这套仓库的防混乱能力七成已建在代码里（守卫测试 + Schema 契约 + 白名单准入）。要做的只有三件事——开工前拆掉 cli.py 这个唯一必炸点、把分工表写成 CODEOWNERS、指定 P3 做唯一合并守门人。
