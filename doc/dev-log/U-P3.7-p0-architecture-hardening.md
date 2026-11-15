# U-P3.7 开发日志：架构客观评估、P0 加固与 P1 跨层解耦

更新日期：2026-11-15（Asia/Shanghai）
状态：**P0 三项（`be0fe00` / `ec3d447` / `714074e`）与 P1 五步（`f45d44b` / `210ce13` / `4b45062` / `f06d98a` / `d7b65a0`）全部完成，各步独立提交；每项均带常驻守卫测试与证伪实验；P0 收口全量闸门 603/603、P1 收口全量闸门 612/612，均 0 失败 0 错误；`schema check` 88/88 通过**

本篇分三部分：**§一–§四** 是对当前代码结构的客观度量与据此完成的 P0 加固（不引用任何既有架构文档的自述，全部来自 AST/正则/运行时打点的一手测量）；**§七** 是承接 §五 清单执行的 P1 跨层解耦（含"是否值得改"的测量式判定）。

## 一、取数方法

| 手段 | 产出 | 脚本（`projects/.carto-dev/`，未纳入版本管理的临时件） |
|---|---|---|
| AST 全量建图（含模块级 / 函数内惰性 / `TYPE_CHECKING` 三类 import，相对导入解析为绝对名） | 层×层边矩阵、SCC 环检测、fan-in/fan-out/Martin 不稳定度 | `_arch_metrics.py` |
| AST 度量每个模块 | LOC、类数、函数数、最长函数、最大参数数 | 同上 |
| 正则扫描分支点 | `geometry==` / `renderer_id==` / `kind==` / `is_vector` 散布 | 同上 |
| 运行时打点（插桩 `Path.read_bytes`） | 每个 digest 函数**实际读取**的文件集 → 摘要影响面与覆盖缺口 | `_p0_digest_impact.py`、`_arch_digest_coverage.py` |
| `inspect.signature` 比对 | 声明契约 vs 真实组件签名 | `_p0_3_*` |

**方法学教训（已记忆）**：涉及按字节哈希的量，禁止用"另开 worktree 检出旧提交"做前后比对——本仓 `core.autocrlf=true` 且无 `.gitattributes`，同一提交在不同检出下字节不同，会制造假变化。正确做法是**同一工作树内**用打点法判定"某 digest 是否读取了本次改动的文件"。

## 二、实测架构基线

### 2.1 依赖方向与环

层×层边数（行=引用方，节选）：

| | adapters | compiler | contracts | repository | scenario_reg | scenarios | validation | workflow |
|---|---|---|---|---|---|---|---|---|
| adapters | 30 | 12 | – | 4 | – | – | – | **14** |
| compiler | **6→5** | 33 | 9 | 4 | 2 | – | 1 | **0** |
| repository | – | **1** | – | 7 | – | – | – | – |
| scenario_registry | – | – | – | 2 | – | **1** | – | 1 |
| scenarios | 3 | 13 | – | 4 | 2 | 3 | – | 16 |
| validation | – | **3** | – | – | – | – | 4 | **0** |
| workflow | **18** | 20 | 4 | 8 | 10 | – | 4 | **63** |

- **模块级 import 的 SCC = 0**（Tier-2 成果，import 期无环）。
- 惰性 import 层面剩 2 个 SCC：`adapters.formal_renderer ↔ compiler.raster_scene ↔ compiler.vector_scene`、`adapters.controlled_renderer ↔ adapters.webmap_renderer`。
- 层级小环 3 处：`validation↔compiler`（3 惰性 / 1 模块级）、`repository→compiler`（`staging_package:13`，模块级）、`scenario_registry↔scenarios`。
- `compiler→adapters` 5 条（P0-1 前为 6）：`PageRenderer` ×3、`RendererProfile` ×2 —— 这是当前最主要的分层倒置，属 P1。

### 2.2 稳定依赖（Martin 指标）

| 模块 | Ca | Ce | I |
|---|---|---|---|
| `errors` | 83 | 0 | **0.00** |
| `canonical` | 55 | 1 | 0.02 |
| `schema_registry` | 54 | 1 | 0.02 |
| `security.paths` | 30 | 1 | 0.03 |
| `artifacts` | 29 | 3 | 0.09 |
| `workflow.models`（垫片） | **21** | 1 | 0.05 |
| `adapters.page_renderer` | 7 | 15 | 0.68 |

spine 的稳定依赖做得很好；`contracts` 实测 Ce=2（只 `errors` + `schema_registry`），是真叶子。**异常项**：`workflow.models` 只是 Tier-1 留下的 re-export 垫片，却仍有 21 个引用方（adapters 7 / workflow 10 / scenarios 3 / cli 1），只有 3 处直连 `contracts.execution` —— 迁移只搬了定义没搬引用。

### 2.3 复杂度集中度

`carto_core` 合计 19023 LOC，top-5 模块占 24.4%。

| 模块 | LOC | 类 | 方法 | 最长函数 | 最大参数 |
|---|---|---|---|---|---|
| `workflow.map_generation` | 1530 | 1 | 42 | 181（`review`） | 10 |
| `scenarios.general_thematic` | 966 | 5 | 43 | 136 | 9 |
| `adapters.controlled_renderer` | 858 | 9 | 39 | 112 | 6 |
| `workflow.template_validation` | 710 | 1 | 28 | 66 | 11 |
| `workflow.map_final_check` | 569 | 1 | 24 | 68 | **13** |
| `adapters.page_renderer` | 485 | 1 | 21 | 60 | **14** |
| `cli`（`main` 228 行） | 451 | 0 | 5 | 228 | 2 |

### 2.4 扩展点实测

| 扩展维度 | 机制 | 新增一个要动几处 | 评价 |
|---|---|---|---|
| 新业务场景 | `scenario_registry._COMPONENTS` 闭白名单 + `scenario-capabilities.yaml` 准入 | 代码 1 处 + 策略 1 处 | 良好；闭白名单是刻意的安全取舍（不接受请求/策略提供的 import 路径），不应改为动态插件 |
| 新渲染后端 | `backend_registry._BACKENDS` 表 + `create_render_backend` 按 `descriptor.impl` 分派 | 同族 1 行；新族 1 行 + 1 分支 | P0-1 后**真正**表驱动（此前 renderer_id 字面量散落 10 个文件） |
| 新检查项 | `policies/checker-registry.yaml` + `CheckerRegistry` | 纯数据 | 最好 |
| **新几何** | `BundlePreparer` 内 6/17 方法 `if self.geometry`；`page_renderer`+`preparation_bundle` 共 9 处 geometry 分支；`formal_renderer` 8 处 renderer_id 比较 + 5 处 `is_vector/is_static` | **~5 文件 15+ 处** | 最贵：统一发生在类内部而非策略层面，属 P1 |

## 三、P0 三项：证据、改动、守卫、证伪

### P0-1 `renderer_id` 单一权威（`be0fe00`）

**证据**：字面量在 `carto_core` 内 26 处（`rasterio-matplotlib-page` 9、`matplotlib-vector-page` 10、`maplibre-web` 7），真实代码副本分布在 **10 个文件**；而 `backend_registry` 只有 4 个引用方。自称"单一权威表"，实为散弹式修改。

**改动**：① `backend_registry.py` 从 `adapters/` 提到包根（`git mv` 保留血缘；它是零内部依赖叶子，留在 adapters 会迫使 compiler 为一个常量 import 渲染适配器包并触发 `adapters/__init__` 级联）；② 10 个文件的副本全部改为派生（`RASTER_PAGE.renderer_id` 等），`compiler/layout.py` 的 `renderer_id in {两个字面量}` 改为 `is_static(...)`（对 `None`/未知 id 同为 False，逐字等价并补测试锚定）。

**守卫**：`tests/test_backend_registry.py` 新增 AST 扫描——遍历 `carto_core` 全量字符串常量（跳过 docstring 与裸字符串表达式），`renderer_id` 字面量出现在 `backend_registry.py` 之外即失败；并以 `assertIs`（而非 `assertEqual`）断言派生常量与 registry 是**同一对象**，等值断言挡不住重新硬编码。

**证伪**：向 `compiler/layout.py` 注入 `PROBE_DUPLICATE_ID = "rasterio-matplotlib-page"` → 守卫 FAIL 且点名文件与字面量；字节级还原后 PASS，注入痕迹为零。

**摘要影响（打点法）**：变 `raster.renderer_digest`、`raster/vector.page_renderer_digest`、`raster/vector.formal_renderer_digest`；**不变** `raster.algorithm_digest`、`raster.portrayal_compiler_digest`、`vector.reader_digest`、`vector.compiler_digest` → 数据准备与 portrayal 产物不受影响，仅渲染侧需重渲染。

### P0-2 补齐三处指纹覆盖缺口（`ec3d447`）

**证据（先红后绿）**：先写 `tests/test_digest_coverage.py` 并在修清单**之前**运行，实测 3 处失败：

1. `compiler/chart_core.py` **不在任何指纹清单**，但 `static_page_renderer.py:201` 绘制页面时调 `validate_chart`、`vector_page.py:77` 冻结页面时调 `bind_chart_slots`/`validate_chart` → 改图表绑定或校验数学，页面输出变而 `page_renderer_digest` 不变（静默漂移）。
2. `compiler/layout.py` 不在 `page_renderer_digest` 的 common 段 → **矢量页面摘要完全未覆盖 LayoutResolver**（决定 frame/viewport 几何）；栅格侧只是通过内嵌的 `renderer_digest` 间接覆盖。
3. `compiler/thematic_design.py` 不在 `algorithm_digest`，而栅格 continuous 断点来自 `equal_interval_edges`（`raster_preparation.py:154` 经垫片调用）。此为 Tier-2 之前的既存缺口（该函数原住 `workflow/thematic.py`，同样未被收录）。

**改动**：`layout.py` 与 `chart_core.py` 加入 `page_renderer_digest` 的 common 段；`algorithm_digest` 新增 `"derivation"` 键收录 `thematic_design.py`。

**守卫设计**：断言方式是**观察 digest 函数实际读了哪些文件**（插桩 `Path.read_bytes`），不是解析清单字面量——清单将来重构或改为自动派生，测试依然有效。

**摘要影响**：9 个 digest 中 7 个变化（栅格 5 个全变 + 矢量页面/回执 2 个），矢量 `reader_digest`/`compiler_digest` 不变。栅格侧需自准备报告起重跑——这正是补缺口的目的：这些产物本就应绑定这些代码，此前是漏检而非"稳定"。

### P0-3 `component_protocols` 从文档升级为强制契约（`714074e`）

**证据**：用 `inspect.signature` 逐个比对注册组件，8 个协议里 **6 个已漂移**：

| 组件 | 协议原声明 | 真实契约 |
|---|---|---|
| `data_preparer` | `prepare_request(request, context)` | `prepare(request, request_ref)` |
| `planner` | `plan(request, intent, template, context, registry)` | `build(request, intent, brief, bundle, installation, contracts)` |
| `candidate_compiler` | `compile(plan, prepared, context, registry)` | `compile(request, intent, plan, bundle, installation, contracts, font_path)` |
| `legend_checker` | `__call__(context, candidate, resolved_map) -> dict` | `__call__(context) -> tuple[bool, dict, None]` |
| `author` | `author(request, template_ref)` | `author(request, brief)` + `verify_existing(request, brief)`（`template_workflow:155` 实际调用） |
| `validation_scene` | 缺 `validation_expression` | 含（`template_validation:605` 条件传入） |

即这份自称"参数名与返回形状的单一事实来源"的文件，若被新场景作者照抄，六个组件会全部写错——而它的 docstring 明确宣称"NOT enforced at runtime"。

**改动**：按真实调用点重写 8 个协议；补上此前完全未声明的**构造契约**（`DataPreparerFactory` / `PlannerFactory` / `CandidateCompilerFactory` / `AuthorFactory`）——方法对但构造签名漂移同样会在框架调用点崩；全部加 `@runtime_checkable`；新增 `COMPONENT_PROTOCOLS` / `COMPONENT_CONSTRUCTORS` 两张可遍历的表。

**守卫**：`tests/test_component_protocols.py`（7 项）遍历 `_COMPONENTS` 每个组件，断言 ①有协议 ②`isinstance` 结构满足 ③每个方法的（参数名, 参数种类, 是否有默认值）三元组与协议逐一相等 ④类值组件构造签名与工厂协议相等 ⑤类值/实例值与 `COMPONENT_CONSTRUCTORS` 双向一致 ⑥协议表与注册表词表完全相同。

**为什么必须比签名**：`runtime_checkable` 的 `isinstance` 只校验同名成员存在，`compile` 从 4 参漂到 7 参它照样通过。

**证伪（两档）**：① `DataPreparer.prepare` 改回 `prepare_request` → 结构测试 + 签名测试同时红（2/2）；② 仅把 `compile` 的 `font_path` 改名 `font` → `isinstance` 仍通过、签名测试红（1/1）。两次均字节级还原、套件复绿。

**摘要影响**：打点法实测 9 个 digest 全部 unchanged（`component_protocols.py` 不在任何清单内），零产物失效。

## 四、闸门

| 阶段 | fast | full |
|---|---|---|
| P0-1 | 554/586 ✅ 0失败0错误 | — |
| P0-2 | 564/596 ✅ 0失败0错误 | — |
| P0-3 | 571/603 ✅ 0失败0错误 | — |
| P0 收口 | — | **603/603 ✅ `OK (skipped=9)`，failures=0 errors=0，1010.4s** |

9 项跳过恒为外部依赖（独立 GIS 服务解释器、符号链接权限），与本轮改动无关。603 = Tier-2 收口时的 584 + P0 新增 19 项守卫（backend_registry +2、digest_coverage +10、component_protocols +7）。

**CLI 校验**：`carto.py schema check` 88 个 schema 全通过。

## 五、承接分析的后续清单

**P1**（1/3/4 已于本轮完成，见 §七；2 仍待做）
1. ~~`compiler→adapters` 剩 5 条（`PageRenderer` ×3、`RendererProfile` ×2）~~ → **已完成（P1-D1/D2，§7.4）**：页面契约与环境快照改为注入端口，实测归零。
2. `BundlePreparer` 按 geometry 拆两个策略类（`BundlePreparerProtocol` 已就位）；验收：`self.geometry ==` 出现 0 次。
3. ~~`_json_ref`（5 模块 12 处调用，且已被迫写进 `RasterPreparationProtocol`）与 `_asset`（5 处）提升为公开端口成员~~ → **已完成（P1-A/B，§7.2）**：跨对象私有属性 24 处/9 名 → 2 处/2 名，公开端口内下划线成员 0。
4. ~~清 21 处 `workflow.models` 垫片引用后删除垫片~~ → **已完成（P1-C，§7.3）**：实测全仓引用为 36 处（§2.2 的 21 是 `carto_core` 内的引用方数，未计 tests），已全部改指叶子并删除垫片文件。

**P2**
5. 拆 `map_generation`（1530 LOC / 1 类 / 42 方法 / 最长 181 行）为阶段协作对象；`cli.main`（228 行）改命令表；`map_final_check`(13 参)/`page_renderer`(14 参) 的长参数列收进参数对象。
6. EOL + `.gitattributes` 统一：26 个 LF 文件中 `material_extraction.py` 是 `reader_digest` 输入，导致矢量 `reader_digest` 跨检出不可复现；修复必然引发全量摘要重基线，须单独排期并配套重跑所有项目产物。
7. 指纹清单从"人肉维护"改为按导入/调用图自动派生（P0-2 已用行为断言兜住，但根因仍在）。
8. 同层私有共享 4 个导入名（`_dependencies` 在 adapters 内 4 处；`_number`/`_key`/`_size_symbol` 为 compiler 内共享的 IR 原语）：属**同层**而非跨层，风险等级低，故留在 `test_encapsulation` 的冻结 allowlist 内；若要清除，做法是提为该层的公开模块级 helper，而非改名。
9. `PageRenderer` 仍同时承担"冻结 + 形式校验"与"光栅化/导出"；P1-D2 只把前半暴露为 `PageContractPort`（刻意不含绘制能力），完整拆分（把校验搬进 compiler）单独成步。

**不建议做**：强行统一 raster/vector 准备服务签名（违背既定约束且触发摘要雪崩）；为"可扩展"引入动态插件 import（与 `_COMPONENTS` 闭白名单的安全取舍冲突）；big-bang 分层重写；把 `formal_renderer`/`page_renderer` 构造准备服务与 `BundlePreparer` 的 5 条边也注入化（组装根职责，注入只会把同样的耦合推给它们的调用方）；`workflow→adapters` 23 条（编排调 I/O，是正常方向）。

## 六、常驻守卫（可复现的证据入口）

度量脚本本身是临时件，但其中表达"不变量"的部分已全部提升为受版本管理的测试。P1 结束时五个套件合计 **46 项**：

| 测试 | 项数 | 守护的不变量 |
|---|---|---|
| `tests/test_layer_ports.py` | 11 → **15** | 内核层零 `workflow`/`adapters` import（P1-D2 扩展）；`contracts` 叶子性；端口结构一致性（含页面契约与环境快照端口）；几何词表单源；失败关闭；垫片不得复活且包级 re-export 为同一对象（P1-C 新增 3 项） |
| `tests/test_encapsulation.py` | **5**（P1-A 新建） | 跨对象私有属性访问与跨模块私有名 import 为 0 或在冻结 allowlist 内（**双向棘轮**：新增违规会红，修好却不删条目也会红）；任何 Protocol 不得声明私有成员；`document` 只声明在公共基座 |
| `tests/test_backend_registry.py` | 9 | `renderer_id` 字面量单一权威；派生常量为同一对象；家族分类等价 |
| `tests/test_digest_coverage.py` | 10 | 每个 digest 实际覆盖其输出成形代码 |
| `tests/test_component_protocols.py` | 7 | 场景组件的方法与构造签名与声明契约逐一相符 |

## 七、P1：跨层耦合三项的必要性判定与执行

提出的三项质疑：`compiler→adapters` 6 条、`adapters↔workflow` 32 条双向、跨层调用私有成员 `_json_ref` 12 处。**先测量该不该改，再决定改哪些**（脚本 `_p1_necessity.py` / `_p1_necessity2.py`）。

### 7.1 判定：三项都该改，但"32 条双向"里有 23 条不该动

| 质疑 | 实测拆解 | 判定 |
|---|---|---|
| `compiler→adapters` 6 条 | P0-1 后为 **5** 条，全部惰性：`PageRenderer` ×3（`raster_scene:31,51`、`vector_scene:52`）、`RendererProfile` ×2（`raster_scene:85`、`vector_scene:83`）。最严重处不是 import 本身，而是 `raster_scene.py:32` 调**适配器的私有方法** `PageRenderer(...)._validate`。注：三条边都是函数内惰性导入，故内核模块 **import 期不会**拉入 matplotlib；但只要调用 `_inputs()` / `compile()` / `bind_execution()`，绘图栈（matplotlib / rasterio / fontTools）就进入内核的执行路径——惰性只推迟了耦合、没有消除它，还让它在静态依赖图上不可见（模块级 SCC 早已为 0，正是这个原因） | **改**。"冻结 + 形式校验页面请求"按 design-principles §2.2 属内核职责，却与光栅化同住一个类，于是内核被迫依赖渲染栈并穿透其私有成员 |
| `adapters↔workflow` 32 条双向 | 按方向拆：`workflow→adapters` 16 条是编排调 I/O，**正常方向**；`adapters→workflow` 14 条 = **7 条垫片幻影**（`workflow.models` 只是 `contracts.execution` 的 re-export）+ **2 条** `dependencies()`（GIS 依赖访问器，叶子关注点）+ **5 条实质**（组装根构造准备服务/BundlePreparer） | **改 9 条（7+2），保留 5+16 条**。把"32 条双向"当成一个数会得出错误结论——其中 21 条本就合法 |
| 跨层私有 `_json_ref` 12 处 | 12 处生产调用横跨 **4 个层**（compiler / adapters / scenarios / workflow），另有 10 处测试调用；且 Tier-2 时被迫写进 `contracts.protocols.RasterPreparationProtocol`——**公开端口里出现下划线成员**。同族：`_asset` 5 处跨对象 + 4 处子类自调用；`_publish_bytes` 被 3 个模块以私有名导入，其中 2 个来自 workflow（编排层为一个 spine 级工具去依赖适配器）；`PageRenderer._validate` 被内核调用；`_scale_label` 被 `map_final_check:559` 跨层调用 | **改**。私有名出现在跨层端口上，等于"契约里包含一个声明自己不是契约的东西"；且两个几何对同一操作取了两个名字（栅格 `_json_ref`、矢量 `document`） |

**时机论据（决定"现在做"而非"以后做"）**：这三项要动的文件——`raster_preparation.py`、`vector_preparation.py`、`static_assets.py`、`page_renderer.py`、`static_page_renderer.py`、`raster_scene.py`、`vector_scene.py`、`map_candidate.py`、`formal_renderer.py`——其代码摘要在 Tier-2 / P0-1 / P0-2 之后**已全部失效**，且此后没有任何项目产物重跑过。此时做改名与搬家不会**额外**作废任何产物；等产物重跑完再单独做，就要再作废一次。P1 不影响任何功能行为，本可无限期推迟，唯一的排期理由就是这个失效窗口。

### 7.2 P1-A / P1-B：跨层私有成员正名（`f45d44b`、`210ce13`）

| 原名 | 新名 | 为什么是这个新位置 |
|---|---|---|
| `RasterPreparationService._json_ref` | `document` | 矢量服务同一契约早已叫 `document`，且额外提供 `_json_ref` 别名委托给它；正名后两个几何同名，`document(ref, kind)` 上提到 `PreparationServiceProtocol` **公共基座**（`load_verified` 与持久化方法仍留在各自子协议——返回形状确实不同，按既定约束不强行统一） |
| `StaticAssetStore._asset` | `store_asset` | 它是 `snapshot_bytes` 的写入对偶（后者读回同一描述符并重新校验字节），docstring 已注明这层关系 |
| `adapters.geospatial_mcp._publish_bytes` | `artifacts.publish_bytes` | **搬家 + 正名**：它是"PathGuard 下原子创建、已存在则逐字节校验"的通用工具，与 GIS/MCP 无关；归位 spine 后 `workflow/static_assets.py` 不再依赖 adapters（`workflow→adapters` −1） |
| `PageRenderer._validate` | `validate_request` | 它承担"页面请求的形式校验"，本就是对外契约的一部分；D2 会把它声明到注入端口上，故先正名（改名而非加别名，不为旧命名保留并行实现） |
| `MeasuredPageRenderer._scale_label` | `scale_label` | 被 `workflow/map_final_check.py:559` 跨层调用以复算比例尺文字 |

顺带清掉 Tier-2 Step4 自己引入的垫片噪音：`workflow/thematic.py` 对 `_domain` / `_design_to_ir` 的 re-export 与 `__all__` 条目——实测 `compiler/thematic_design.py` 之外的消费者为 **0**，re-export 无人使用的私有 helper 是噪音不是兼容。

**新建守卫 `tests/test_encapsulation.py`（5 项，AST 扫描，无渲染）**：
- 跨对象私有属性访问（`obj._x`，其中 `obj` 既不是裸 `self`/`cls`、也不是所在类自身）必须为 0 或在**冻结 allowlist** 内；跨模块私有名 import 同理。
- **双向棘轮**：新增违规会红；修好后不删 allowlist 条目也会红——allowlist 只能收缩，不会沦为杂物抽屉。每条 allowlist 都写明"为什么还在 + 由哪一步清除"。
- 判定基于**直接父节点**而非根节点，故 `self.renderer._directory_size` 仍算违规（私有成员属于另一个对象）。初版按根节点判定会漏掉它，已修正。
- 专项断言：任何 Protocol 不得声明私有成员；`document` 只声明在公共基座、两个子协议不得重复。

### 7.3 P1-C：垫片退役与 GIS 依赖访问器下沉（`4b45062`）

`carto_core/workflow/models.py` 自 Tier-1 Step1 起就只是 `contracts.execution` 的 re-export，但实测**全仓 36 处** import 仍走它（adapters 7 / scenarios 3 / cli 1 / workflow 内 10 / tests 15）。后果是可测量的：`adapters→workflow` 的 14 条边里 **7 条纯属垫片幻影**——它们语义上是"依赖一个叶子契约"，却被记成"依赖执行层"。36 处全部改指 `carto_core.contracts.execution`，垫片文件删除；`carto_core.workflow` 包仍 re-export 这四个 dataclass，故 `from carto_core.workflow import ExecutionContext` 这一公开面不变（新增测试断言其为**同一对象**而非副本）。

同时把 `dependencies()`（Fiona/Shapely 访问器，缺失即 `VECTOR_DEPENDENCY_MISSING` 失败关闭）从 `workflow/vector_preparation.py` 移到新的包根叶子 `carto_core/geospatial_deps.py`（只 import `carto_core.errors`），消掉 `formal_renderer`、`page_renderer`、`general_vector` 的 2 条向上边。**未**加入 `reader_digest`：该函数只做导入与抛错，不成形任何输出字节。

新增守卫 3 项（`RetiredShimTests`）：垫片文件不得复活；全仓（含 tests）不得 import `carto_core.workflow.models`；包级 re-export 必须与 `contracts.execution` 中为同一对象。

### 7.4 P1-D：内核不再向上依赖渲染适配器（`f06d98a`、`d7b65a0`）

内核为两件事向上依赖渲染栈，处置方式不同：

1. **页面契约**（`PageRenderer(...).freeze_request/.validate_request`）：按 design-principles §2.2 属形式验证层职责，但它与"光栅化/导出"同住一个类。做法是**只把前半暴露为端口**——`contracts.protocols` 新增 `PageContractPort`（仅 `freeze_request` + `validate_request`，**刻意不含任何绘制方法**，使内核在类型层面就拿不到光栅化能力）与 `PageContractFactory`。完整拆分（把校验逻辑搬进 compiler）留在 P2 清单第 9 项。
2. **环境快照**（`RendererProfile.current().environment_snapshot()`）：把运行时环境事实（库版本、`renderer_code_digest`、平台指纹）绑进 execution。`RendererProfile` **无法**像 `backend_registry` 那样下沉为叶子——`current()` 需要 numpy/rasterio/matplotlib/fontTools 并计算 formal_renderer 摘要，因此只能**注入**。在 `adapters/formal_renderer.py` 新增组装根实现 `environment_snapshot(renderer_id=None)`（行为与原调用逐字等价），并声明 `EnvironmentSnapshotProvider` 端口。

两个场景编译器的 `bundles` 改为**关键字限定**，并新增 `pages` / `environment` 两个必填关键字端口——三个协作者都是可调用对象，关键字限定杜绝静默错位传参。`MapCandidateCompiler` 增同名两个可选端口，未注入即 `COMPILER_PORT_NOT_INJECTED` **失败关闭**；14 个构造点全部同步（formal_renderer×2、map_candidate×2、map_generation×3、map_final_check×2、general_thematic×2、general_vector×2、测试×4）。scenarios 内沿用函数内惰性导入，模块加载期依赖图不变。

守卫升级：内核边界从"不得 import `workflow`"扩为"不得 import `workflow` **或 `adapters`**"（五个内核层实测均已满足）；新增端口一致性断言（`PageRenderer` 满足 `PageContractFactory`、其实例满足 `PageContractPort`、`environment_snapshot` 满足 `EnvironmentSnapshotProvider`，且 `object()` 不满足工厂端口——防止 `runtime_checkable` 退化为恒真）。

### 7.5 前后对比（同一脚本、同一规则，分别检出 `b50161a` 与 `d7b65a0` 重测）

计数规则：AST 遍历，模块级 / 函数内惰性 / `TYPE_CHECKING` 三类 import 全计，按 **import 站点**计数（非去重模块对）。

| 量 | P0 收口 `b50161a` | P1 收口 `d7b65a0` |
|---|---|---|
| `compiler→workflow` | 0 | 0 |
| `compiler→adapters` | 5 | **0** |
| `adapters→workflow` | 14（7 幻影 + 2 访问器 + 5 实质） | **5**（全部为组装根实质边） |
| `workflow→adapters` | 16 | 23（**+7**，见下方说明） |
| `scenarios→workflow` | 16 | **12** |
| 模块级 SCC | 0 | 0 |
| 惰性 SCC | 1 个 / 3 模块（`formal_renderer ↔ raster_scene ↔ vector_scene`） | 1 个 / 2 模块（`controlled_renderer ↔ webmap_renderer`，同在 adapters 内） |
| 跨对象私有属性访问 | 21 处 / 6 名 | **2 处 / 2 名**（`_handle` 为 subprocess 的 stdlib 私有；`_directory_size` 为 adapters 同层） |
| 跨模块私有名 import | 12 处 / 7 名 | **7 处 / 4 名**（全部同层） |
| Protocol 内的私有成员 | 1（`RasterPreparationProtocol._json_ref`） | **0**（10 个端口，仅 `__call__` 这类 dunder） |
| `workflow.models` 垫片 | 存在，36 处引用 | **文件已删除，0 处引用** |
| `contracts.execution` 的 Ca | 3（另 21 个引用方走垫片） | **23** |
| `compiler.raster_scene` / `vector_scene` 的 Ce | 11 / 11 | **8 / 9** |
| `adapters.page_renderer` 不稳定度 I | 0.70 | 0.59 |

**`workflow→adapters` 的 +7 必须诚实说明**：这不是回退，是依赖**搬家**。逐项归因：P1-B **−1**（`static_assets.py` 不再为 `_publish_bytes` import `adapters.geospatial_mcp`）；P1-D2 **+8**（`map_generation` 三个构造点各 +2：`PageRenderer` + `environment_snapshot`；`map_final_check` 两个构造点各 +1：`environment_snapshot`）。依赖没有消失，它从"内核自己向上抓"变成"组装根取出后向下递"——方向合法，且现在有守卫：内核那条线一旦被重新越过，`test_layer_ports` 会红。

**与 §2.1 基线表的口径对账**：§2.1 记的 `workflow→adapters = 18`、`compiler→adapters = 6` 是 **P0 之前**的测量。P0-1 把 `backend_registry` 从 `adapters/` 提到包根，消掉 2 条 `workflow→adapters`（`map_generation:8`、`template_validation:9`）与 1 条 `compiler→adapters`，故 P1 起点为 16 与 5。§2.2 记的"`workflow.models` 有 21 个引用方"是 `carto_core` 内的 import 站点数，全仓含 tests 为 36 处。

### 7.6 闸门

| 阶段 | fast | full |
|---|---|---|
| P1-A | 576/608 ✅ 0失败0错误 | — |
| P1-B | 576/608 ✅ 0失败0错误 | — |
| P1-C | 579/611 ✅ 0失败0错误 | — |
| P1-D1 | 579/611 ✅ 0失败0错误 | — |
| P1-D2 | 580/612 ✅ 0失败0错误 | — |
| P1 收口 | — | **612/612 ✅ `OK (skipped=9)`，failures=0 errors=0，1039.4s（17.3 min），EXIT=0** |

每步 9 项跳过恒为外部依赖（独立 GIS 服务解释器、符号链接权限）。612 = P0 收口 603 + P1 新增 9 项守卫（`test_encapsulation` 5 + `RetiredShimTests` 3 + 页面/环境端口一致性 1）。五个守卫套件合计 46 项全绿。

摘要影响：P1-A 9 个 digest 全变、P1-B 8 个、P1-C 7 个、P1-D1/D2 各 4 个（两侧 `page_renderer_digest` 与 `formal_renderer_digest`），但**边际失效面为零**——它们全部已被 Tier-2 / P0-1 / P0-2 失效且尚未重跑，这正是 §7.1 时机论据的兑现。

### 7.7 过程记录（诚实）

1. **P1-B 补丁在 leftover 自检处正确中止**：它发现 `raster_preparation.py` 还有 3 处 `self._asset` 未列入清单（原扫描按**接收者名**匹配，漏掉子类自调用），中止时树处于半改状态（`_publish_bytes` 已移走但 2 个 workflow 文件仍按旧路径导入 → 树不可用），由续做脚本补齐后才跑闸门。**教训：改名类操作必须按"符号全量引用"清点，不能只按"违规调用点"清点。**
2. **新建的 `geospatial_deps.py` 最初误用两点相对导入**（`from ..errors`，从子包模块 `vector_preparation` 照抄），导致 8 个模块级联 ImportError。是"逐个 import 全部 96 个模块"的烟测抓到的，早于 fast 闸门。**教训：包根模块与子包模块的相对导入层级不同，移动/新建文件时必须改点数；烟测比闸门更早、更便宜。**
3. **`test_encapsulation` 初版扫描规则有漏洞**：按"根 Name 是否 `self`"判定，导致 `self.renderer._directory_size` 被误放行。改为按直接父节点判定后，allowlist 才必须如实包含这一条。
4. **`compiler→adapters` 归零的代价被明确记录而非隐藏**：+8 条 `workflow→adapters`（§7.5）。若只看"内核干净了"而不报组装根的变化，这份日志就失去可核查性。
5. **未做的部分**：`BundlePreparer` 的 geometry 分支（§五 P1-2）、`PageRenderer` 的完整职责拆分（§五 P2-9）、同层私有共享 4 个导入名（§五 P2-8）——都在 allowlist 或清单里留了名，不是遗漏。

## 八、复现入口

`projects/.carto-dev/` 下的度量脚本是临时件（该目录整体被 `.gitignore` 排除），但结论都可复现：

| 脚本 | 产出 |
|---|---|
| `_p1_final_metrics.py` | §7.5 全部行：层×层边矩阵、五个关键边数、模块级/惰性 SCC、垫片引用数、跨对象私有属性与跨模块私有名（按守卫规则：直接父节点）、Protocol 私有成员、Martin 不稳定度 |
| `_p1_edge_detail.py` | `workflow↔adapters` 双向逐站点清单（文件:行 + 模块级/惰性 + 源码行），用于把 ±边数归因到具体站点 |
| `_p1_necessity.py` / `_p1_necessity2.py` | §7.1 的必要性判定原始输出 |
| `_p1_private_scan.py` | 私有访问扫描（注意：它按**根节点**规则，比守卫多报本类静态私有，故数字略高于 §7.5） |

前后对比的做法：`git worktree add --detach <tmp> b50161a`，把同一脚本复制进 `<tmp>/projects/.carto-dev/` 后运行（脚本用 `__file__` 定位仓库根，故无需改路径），测完 `git worktree remove --force <tmp>`。**AST 计数不受 §8.10 记录的 EOL 陷阱影响**（该陷阱只影响按字节哈希的量），故跨检出比对在这里是安全的。



