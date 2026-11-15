# U-P3.7 开发日志：Tier-2 去环（compiler ↔ workflow 运行时环彻底断开）

更新日期：2026-11-15（Asia/Shanghai）
状态：**Tier-2 完成——`compiler` 层对 `workflow` 的引用为 0（运行时与类型层同时归零）；边界固化为常驻守卫测试并通过证伪实验；每步 fast 闸门 + 两次 full 闸门全绿**

## 前置

- Tier-1 Step1（`67ffa21`）：抽出 `carto_core/contracts` 中立叶子包，迁移 `ExecutionContext` / `bundle_core` / `context_snapshot`
- Tier-1 Step2（`5dcf5ac`）：compiler 侧改指 contracts，反向边 17→13
- 方案选择：本轮执行既定决策"方案 A—Protocol 下沉 + 构造注入"（方案 B 纯注入不加 Protocol 已否决，因 compiler 仍需 TYPE_CHECKING 引用 workflow 类，断环不彻底）

## 目标与判据

| 项 | 判据 |
|---|---|
| 结构 | `compiler/*` 对 `carto_core.workflow.*` 的 import 条数 = 0（含模块级、函数内惰性、`TYPE_CHECKING` 三类） |
| 行为 | 每步 fast 闸门零回归；关键步骤与收尾跑 full 闸门（含真实渲染端到端） |
| 等价 | 搬迁代码可客观证明等价（AST 逐语句比对），注入对象即原类本体，无包装/无默认值/无新增分支 |
| 常驻 | 边界由测试强制，而非靠约定；且守卫本身经过证伪实验（能被真实违规触发） |
| 诚实 | 每步如实记录代码摘要（digest）影响面与失效恢复方式，不掩盖产物失效 |

## 起点盘点（AST 实测，非文档转述）

审计口径：遍历 `carto_core/**.py` 的 AST，解析相对导入为绝对模块名，统计所有内核层（compiler/contracts/validation/repository/security）指向 `workflow` 的边。实测 `compiler→workflow` **13 条**：

| # | 源 | 目标 | 类别 |
|---|---|---|---|
| 1 | `map_candidate.py:153` | `workflow.material_evidence`（`verify_material_facts`） | 运行时·惰性 |
| 2 | `map_candidate.py:161` | `workflow.raster_preparation`（构造服务） | 运行时·惰性 |
| 3 | `map_candidate.py:178` | `workflow.vector_preparation`（构造服务） | 运行时·惰性 |
| 4 | `raster_page_contract.py:12` | `workflow.preparation_bundle`（`BundlePreparer`） | 运行时·惰性 |
| 5 | `raster_scene.py:8` | `workflow.preparation_bundle` | 运行时·模块级 |
| 6 | `raster_scene.py:9` | `workflow.raster_preparation`（仅类型注解） | 运行时·模块级 |
| 7 | `vector_page.py:107` | `workflow.preparation_bundle`（`crs_contract`，依赖 Fiona） | 运行时·惰性 |
| 8 | `vector_page.py:108` | `workflow.thematic`（`expression_reference`） | 运行时·惰性 |
| 9 | `vector_portrayal.py:83` | `workflow.thematic`（`metric_value`，且在 feature 循环内） | 运行时·惰性 |
| 10 | `vector_scene.py:6` | `workflow.preparation_bundle` | 运行时·模块级 |
| 11 | `vector_scene.py:100` | `workflow.thematic`（`resolve_design`） | 运行时·惰性 |
| 12 | `raster_portrayal.py:24` | `workflow.models`（`ExecutionContext`，已是垫片） | 仅 TYPE_CHECKING |
| 13 | `raster_portrayal.py:25` | `workflow.raster_preparation`（`RasterPreparationService`） | 仅 TYPE_CHECKING |

另：`scenarios→workflow` 16 条。场景层位于执行层之上，属允许方向，**不在去环范围**（见"遗留"）。

## 方案 A 的落地形态

### 一、端口下沉（`contracts/protocols.py`，叶子只依赖 stdlib + `schema_registry`）

| 端口 | 具体实现（仍在 workflow） | 注入方式 |
|---|---|---|
| `PreparationServiceProtocol` | 两个准备服务的公共成员（`registry` / `snapshot_bytes`） | 基座协议 |
| `RasterPreparationProtocol` | `RasterPreparationService`（`_json_ref` / `save_document` / `load_verified(ref)->(report, evidence)`） | 原构造参数，注解改指协议 |
| `VectorPreparationProtocol` | `VectorPreparationService`（`document` / `save` / `load_verified(ref, ctx)` / `crs_contract`） | 同上 |
| `BundlePreparerProtocol` | `preparation_bundle.BundlePreparer`（`build_many` / `load_verified` / `validate_request`） | — |
| `BundlePreparerFactory` | `BundlePreparer` **类本体**（结构化满足 `(preparation, geometry) -> preparer`） | 场景编译器必填构造参数；页面契约函数必填参数；`MapCandidateCompiler.bundles` |
| `PreparationServiceFactory` | 新增 `workflow/preparation_services.py::preparation_service` | `MapCandidateCompiler.preparations` |
| `MaterialFactsVerifier` | `material_evidence.verify_material_facts` | `MapCandidateCompiler.material_facts` |

两个准备服务的运行期 API **故意不统一**（`load_verified` 签名与返回不同、`save`/`save_document` 语义不同），故按既定约束分立为两个协议 + 小公共基座，不做强行归一。

工厂注入选择"传类本体 + 由组件决定 geometry"，而非"传已绑定实例"：栅格场景编译器恒传 `"raster"`，组装根无法把绑错几何的 preparer 塞进来，也不需要在 40 余个调用点重复声明几何。

### 二、机械推导下沉（依据 `doc/design-principles.md` §2.3）

| 搬迁项 | 从 | 到 | 理由 |
|---|---|---|---|
| `metric_value` / `finite` / `expression_reference` | `workflow/thematic.py` | `compiler/portrayal_resolver.py` | IR 域求值与目录引用解析，属 IR 级机械推导 |
| `equal_interval_edges` / `_domain` / `_design_to_ir` / `resolve_design` | `workflow/thematic.py` | `compiler/thematic_design.py`（新增） | 语义参数→编码 IR 的确定性推导 |
| `crs_contract` | `workflow/preparation_bundle.py` | `workflow/vector_preparation.py` + 同名服务方法 | 依赖 Fiona CRS 权威（非叶子），不能进内核；改为经**已注入的 service 端口**调用 |

`workflow/thematic.py` 保留 re-export 垫片，既有 `from .thematic import ...` 路径零改动，自身只剩 `vector_views` / `raster_views` / `join_attributes` 三项确属编排层的职责。顺带把 `_number` 与 `finite` 两份同义实现收敛为一份（一方委托另一方）。

**关键取舍：`resolve_design` 为何是"下沉"而非原记录的"注入已解析 IR"**

| 方案 | 断环 | 职责归位 | 代价 |
|---|---|---|---|
| 注入 DesignResolver 协议（实现留在 workflow） | ✅ | ❌ 机械推导仍留在编排层 | 多一个端口，倒置未解 |
| 由 request 携带已解析 IR | ✅ | ❌ 把 §2.3 的程序职责推给请求侧，触碰 §4"排他性领域" | 改 `generate-request` schema + fixtures + 审批摘要，爆炸半径最大 |
| **下沉到 `compiler/thematic_design.py`（采纳）** | ✅ | ✅ 推导归内核，验证仍由内核独立重算（不削弱） | 零签名改动；仅 `thematic.py` 字节变化引发指纹更新 |

原记录写的是第二种表述，实测代码后改为下沉，已于本轮开工前经确认。

## 逐步记录

| Step | commit | 内容 | compiler→workflow | fast | full |
|---|---|---|---|---|---|
| 3 | `b347ab7` | 新增 `contracts/protocols.py` 端口叶子（纯加法，无调用方改动） | 13 | 541/573 ✅ | — |
| 4 | `efd91f8` | 机械推导下沉 + 指纹清单同步 | 10 | 541/573 ✅ | 573/573 ✅ |
| 5 | `a243651` | `crs_contract` 归位矢量准备服务并经端口暴露 | 9 | 541/573 ✅ | — |
| 6 | `6b34afe` | `map_candidate` 三端口注入（`preparations` / `material_facts`） | 6 | 541/573 ✅ | — |
| 7 | `3e2341f` | 栅格侧 `BundlePreparer` 注入（含页面契约函数签名） | 3 | 541/573 ✅ | — |
| 8 | `e7125aa` | 矢量侧 `BundlePreparer` 注入 | 2（仅注解） | 541/573 ✅ | — |
| 9 | `b1e3b55` | `raster_portrayal` 注解改指 contracts | **0** | 541/573 ✅ | — |
| 10 | 本次 | 守卫测试 + 全量闸门 + 文档 | **0** | — | 584/584 ✅ |

fast = 541/573（9 项外部依赖跳过），full = 全量。9 项跳过为 GIS 独立解释器与符号链接权限所致，与本轮改动无关，基线一致。Step10 的 584 = 原 573 + 新增 11 项守卫测试，`OK (skipped=9)`、failures=0、errors=0、1009.7s。

## 等价性证据

1. **AST 逐语句比对**（剥离 docstring 后 `ast.unparse` 对比 HEAD 与工作树）：7 个搬迁函数中 6 个完全一致；`resolve_design` 唯一差异是删去函数内 `from ..compiler.vector_portrayal import resolve_features`（已提为顶层导入）。
2. **`crs_contract`**：`preparation_bundle` 垫片与 `vector_preparation` 原体为同一对象（`is` 为真）；服务方法委托同一函数；EPSG:4326 实测输出一致。
3. **注入即原体**：组装根传入的是 `BundlePreparer` 类、`RasterPreparationService` / `VectorPreparationService`（经 `preparation_service` 工厂）与 `verify_material_facts` 函数本体，无包装层、无默认值、无新增分支。
4. **闸门**：每步 fast，Step4 后与 Step10 各一次 full（含真实渲染端到端 `test_a31_thematic` / `test_general_thematic`）。

## 代码摘要（digest）影响矩阵

用打点法实测（对每个 digest 函数插桩 `Path.read_bytes`，核对其实际读取的文件集合），而非按清单推断：

| digest | 变化于 | 失效对象 | 恢复方式（既定 fail-closed 语义） |
|---|---|---|---|
| `vector.reader_digest` | Step4、Step5 | `vector-prepared-data` | `VECTOR_READER_CHANGED`：以当前 reader 重跑 prepare |
| `vector.compiler_digest` | Step4 | 矢量 `resolved-portrayal` | `VECTOR_PORTRAYAL_CHANGED`：重编译 portrayal |
| `vector.page_renderer_digest` | Step4、Step5 | 矢量 `page-request` / `page-output` | `VECTOR_PAGE_CHANGED`：重编译页面并重渲染 |
| `raster.algorithm_digest` | Step9 | `raster-classification/continuous-preparation` | 重跑 analyze |
| `raster.portrayal_compiler_digest` | Step9 | 栅格 `resolved-portrayal` | `RASTER_PORTRAYAL_CHANGED` |
| `raster.renderer_digest` / `page_renderer_digest` / `formal_renderer_digest` | Step7、Step8、Step9 | map body / page-output / render 回执 | `RASTER_MAP_BODY_CHANGED` / `RASTER_PAGE_CHANGED`：重渲染 |

- 全部为 **fail-closed 失效**，不存在静默沿用旧产物。
- 回归测试均在临时目录内自建产物，两侧摘要在同一次运行内自洽，故不受影响；`projects/` 下既有开发产物按需重跑。
- **指纹清单同步（横切点）**：`reader_digest` 增列 `compiler/portrayal_resolver.py`（`finite` 搬迁后 `join_attributes` 的实际依赖）；`vector_portrayal.compiler_digest` 增列 `compiler/thematic_design.py`（frozen encoding 的推导来源）；`crs_contract` 落入 `vector_preparation.py` 后，页面 `bindings.views[].crs` **首次**获得代码指纹覆盖（此前缺失，属补齐而非放宽）。

## 守卫与证伪

新增 `tests/test_layer_ports.py`（11 项，0.32s，合成 fixture，无渲染）：

1. **AST 边界**：五个内核层零 `workflow` import，覆盖模块级、函数内惰性与 `TYPE_CHECKING` 三类；`from pkg import name` 同时展开 `pkg` 与 `pkg.name`，故 `from .. import workflow` 形式也拦得住。
2. **contracts 叶子性**：只允许 spine（`errors` / `canonical` / `schema_registry` / `contracts` 自身）。
3. **反空洞守卫**：断言 `map_candidate` / `raster_scene` / `vector_scene` 确实引用了 `contracts.protocols`——防止端口模块被架空后边界测试"空过"。
4. **端口一致性**：真实服务实例 `isinstance` 各自协议；栅格服务不满足矢量端口（矢量服务因带 `save_document`/`_json_ref` 别名而是栅格端口的结构超集，故不反向断言，并在测试中写明原因）。
5. **几何词表单源**：`protocols.GEOMETRIES == preparation_bundle.GEOMETRIES`，且 `== preparation_services.SERVICES` 键集。
6. **失败关闭**：未知 geometry → `PREPARATION_GEOMETRY_UNKNOWN`；端口缺失 → `COMPILER_PORT_NOT_INJECTED` 并点名缺失端口；`BundlePreparer` 未知几何 → `BUNDLE_GEOMETRY_UNKNOWN`。

**证伪实验**（`projects/.carto-dev/_t2_guard_falsify.py`）：向 `compiler/layout.py` 临时注入 `from ..workflow.thematic import resolve_design` → 守卫 **FAIL** 且点名 `layout.py` 与 `carto_core.workflow.thematic`；字节级还原后恢复 **PASS**，`git status` 显示该文件干净。守卫不是空转。

## 遗留与后续（本轮不做）

1. **EOL 与摘要可复现性（既存隐患，本轮实测发现）**：`core.autocrlf=true` 且无 `.gitattributes`；本工作树 227 个受版本管理的文本源文件中 **26 个为 LF**，而新检出会得到 CRLF。其中 `workflow/material_extraction.py` 恰是 `reader_digest` 的输入之一 → **矢量 `reader_digest` 与检出方式相关、跨机器不可复现**。修复必然引发全量摘要重基线，须单独排期并配套重跑所有项目产物；本轮未触碰（也未借去环顺手改 EOL）。
2. **`scenarios→workflow` 16 条边**：方向允许，不属去环范围。
3. **`raster.algorithm_digest` 的既存覆盖缺口**：`equal_interval_edges` 参与栅格 continuous 编码，但从未被 `algorithm_digest` 收录；搬迁前后同样未覆盖，本轮既未扩大也未顺手修复（修复会波及栅格摘要，应与下一次栅格链改动合并）。
4. **`tests/regression-baseline.json` 未重测**：新增 11 项守卫属 unknown，按 runner 设计在每个 tier 都跑；需要时用 `run_tests.py --measure` 重测分层。
5. **垫片清理**：`workflow/models.py`、`workflow/thematic.py` 的 re-export 与 `preparation_bundle.crs_contract` 转发按 Strangler Fig 保留；确认无外部引用后可单独清理。

## 改动文件清单（Step3–Step10，均在 `skills/carto-agent/scripts/`）

| # | 文件 | 类型 | 步骤 |
|---|---|---|---|
| 1 | `carto_core/contracts/protocols.py` | 新增→扩展 | 3、7、10 |
| 2 | `carto_core/compiler/thematic_design.py` | 新增 | 4 |
| 3 | `carto_core/compiler/portrayal_resolver.py` | 修改（接收 `metric_value`/`finite`/`expression_reference`） | 4 |
| 4 | `carto_core/workflow/thematic.py` | 修改（改为垫片 + 保留编排职责） | 4 |
| 5 | `carto_core/compiler/vector_portrayal.py` | 修改（同层引用 + 指纹增列） | 4 |
| 6 | `carto_core/compiler/vector_page.py` | 修改（`expression_reference` 同层、`crs_contract` 走端口） | 4、5 |
| 7 | `carto_core/compiler/vector_scene.py` | 修改（`resolve_design` 同层、注入 `bundles`） | 4、8 |
| 8 | `carto_core/workflow/vector_preparation.py` | 修改（接收 `crs_contract` + 服务方法 + 指纹增列） | 4、5 |
| 9 | `carto_core/workflow/preparation_bundle.py` | 修改（`crs_contract` 转发垫片、删两处死导入） | 5 |
| 10 | `carto_core/workflow/preparation_services.py` | 新增（geometry→服务工厂） | 6 |
| 11 | `carto_core/compiler/map_candidate.py` | 修改（三端口注入 + `_require_port` 失败关闭） | 6、7、8 |
| 12 | `carto_core/workflow/map_generation.py` | 修改（`_candidate_compiler` 收敛三处组装 + 注入） | 6、7、8 |
| 13 | `carto_core/compiler/raster_scene.py` | 修改（注入 `bundles`、注解改指协议） | 7 |
| 14 | `carto_core/compiler/raster_page_contract.py` | 修改（三个函数增 `bundles` 参数） | 7 |
| 15 | `carto_core/adapters/formal_renderer.py` | 修改（组装根注入） | 7、8 |
| 16 | `carto_core/adapters/page_renderer.py` | 修改（组装根注入） | 7 |
| 17 | `carto_core/workflow/map_final_check.py` | 修改（组装根注入） | 7、8 |
| 18 | `carto_core/scenarios/general_thematic.py` | 修改（组装根注入 ×4） | 7 |
| 19 | `carto_core/scenarios/general_vector.py` | 修改（组装根注入 ×2） | 8 |
| 20 | `carto_core/compiler/raster_portrayal.py` | 修改（TYPE_CHECKING 注解改指 contracts） | 9 |
| 21 | `tests/test_layer_ports.py` | 新增（边界守卫 11 项） | 10 |
| 22 | `tests/helpers.py`、`tests/test_general_thematic.py`、`tests/test_raster_formal.py`、`tests/test_s1ab_contracts.py`、`tests/test_s1cd_grid.py`、`tests/test_intent_semantics.py` | 修改（构造点同步） | 6、7 |
