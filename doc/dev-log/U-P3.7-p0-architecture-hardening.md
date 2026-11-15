# U-P3.7 开发日志：架构客观评估与 P0 加固

更新日期：2026-11-15（Asia/Shanghai）
状态：**P0 三项全部完成并各自独立提交（`be0fe00` / `ec3d447` / `714074e`）；每项均带常驻守卫测试与证伪实验；P0 收口全量闸门 603/603 `OK (skipped=9)`、0 失败 0 错误；`schema check` 88/88 通过**

本篇分两部分：前半是**对当前代码结构的客观度量**（不引用任何既有架构文档的自述，全部来自 AST/正则/运行时打点的一手测量），后半是据此完成的 P0 加固。

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

## 五、承接分析的后续清单（本轮未做）

**P1**
1. `compiler→adapters` 剩 5 条（`PageRenderer` ×3、`RendererProfile` ×2）：根因是 `PageRenderer` 把"冻结+形式校验 page-request"（内核职责）与"光栅化/导出"（后端职责）揉在一个类；`RendererProfile.current()` 采集的是运行时环境事实，应由组装根推入而非内核拉取。
2. `BundlePreparer` 按 geometry 拆两个策略类（`BundlePreparerProtocol` 已就位）；验收：`self.geometry ==` 出现 0 次。
3. `_json_ref`（被 5 个模块 12 处调用，且已被迫写进 `RasterPreparationProtocol`）与 `_asset`（5 处）提升为正式公开端口成员；验收：跨模块 `._xxx` 引用为 0。协议里出现下划线方法本身就是接口未定型的信号。
4. 清 21 处 `workflow.models` 垫片引用后删除垫片。

**P2**
5. 拆 `map_generation`（1530 LOC / 1 类 / 42 方法 / 最长 181 行）为阶段协作对象；`cli.main`（228 行）改命令表；`map_final_check`(13 参)/`page_renderer`(14 参) 的长参数列收进参数对象。
6. EOL + `.gitattributes` 统一：26 个 LF 文件中 `material_extraction.py` 是 `reader_digest` 输入，导致矢量 `reader_digest` 跨检出不可复现；修复必然引发全量摘要重基线，须单独排期并配套重跑所有项目产物。
7. 指纹清单从"人肉维护"改为按导入/调用图自动派生（P0-2 已用行为断言兜住，但根因仍在）。

**不建议做**：强行统一 raster/vector 准备服务签名（违背既定约束且触发摘要雪崩）；为"可扩展"引入动态插件 import（与 `_COMPONENTS` 闭白名单的安全取舍冲突）；big-bang 分层重写。

## 六、本轮新增的常驻守卫（可复现的证据入口）

度量脚本本身是临时件，但其中表达"不变量"的部分已全部提升为受版本管理的测试：

| 测试 | 项数 | 守护的不变量 |
|---|---|---|
| `tests/test_layer_ports.py` | 11 | 内核层零 `workflow` import；`contracts` 叶子性；端口结构一致性；几何词表单源；失败关闭 |
| `tests/test_backend_registry.py` | 9 | `renderer_id` 字面量单一权威；派生常量为同一对象；家族分类等价 |
| `tests/test_digest_coverage.py` | 10 | 每个 digest 实际覆盖其输出成形代码 |
| `tests/test_component_protocols.py` | 7 | 场景组件的方法与构造签名与声明契约逐一相符 |
