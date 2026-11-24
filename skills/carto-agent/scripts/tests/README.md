# 测试目录与清理原则

本目录仅用于开发回归与验收工具自测，不是制图运行协议，不提供真实数据或审批证据。

## 按功能组织，而不是按开发阶段组织

2026-11-19 清理时，未发现可因“阶段已经结束”而整份丢弃的测试模块。
旧阶段脚本中的预算、防重放、不可变产物、网格、渲染与恢复断言仍在保护现行实现。
因此采用合并、功能命名和有依据的去重，而不是批量删除 `a*` / `up*` / `s1*` 文件。

| 原模块 | 当前归属 | 保留的职责 |
|---|---|---|
| `test_a12_revision.py`、`test_revision_graph.py` | `test_design_revision.py` | 修订提案、持久预算、失效传播和 bundle 输入摘要 |
| `test_slim_core.py` | `test_framework_contracts.py` | 原子写入、不可变存储、检查器门禁，与既有框架合同测试合并 |
| `test_a2_material.py` | `test_material_extraction.py` | 文本/CSV 提取、数据采纳、来源追溯和输入安全 |
| `test_up1.py` | `test_core_protocols.py` | 状态、工具、知识、意图、审批、回执与 SVG 合成 |
| `test_up23_renderer.py` | `test_webmap_renderer.py` | 受控浏览器渲染、资源绑定与执行限制 |
| `test_up27_integration.py` | `test_workflow_recovery.py` | 中断恢复、不可变回执、单写锁和跨路由审批隔离 |
| `test_s1ab_contracts.py` | `test_page_bindings.py` | 页面显式绑定、版本拒绝与单页归一 |
| `test_s1cd_grid.py` | `test_grid_layout.py` | 有限网格、多源数据、全部面板证据与共享图例 |

历史 `doc/dev-log/` 保留当时的文件名；查找当前测试时使用上表，不添加旧模块兼容壳。

## 已删除的冗余与阶段性约束

- 原 `test_up1.StateAndRepositoryTests.test_immutable_store_is_content_addressed`：
  重复的寻址断言已由 `test_framework_contracts.ArtifactUtilityTests.test_content_addressed_store_keeps_canonical_bytes_and_rejects_conflicts`
  覆盖；原测试独有的 `store.get()` 回读断言一并移入，未丢失该行为覆盖。
- `test_capability_roadmap.RoadmapTaxonomyTest.test_schema_cases_registered`：
  仅重复验证 `VALID_CASES` / `INVALID_CASES` 中的同一对象，已由
  `test_schemas.SchemaTests.test_every_instance_schema_has_valid_and_invalid_fixture` 统一覆盖。
- 模板资产“必须恰好 13 份”的迁移批次数量断言：改为非空检查，继续检查目录与迁移记录一一对应、
  全部合同符合当前 Schema、原件摘要和来源记录完整。不把某次导入数量当成永久协议。
- `test_template_single_approval.py` 不再将 `PublishLineTests` 类导入模块全局，避免 unittest 把两项发布测试再执行一遍。
  共享 fixture 通过模块引用复用；新增发现检查拒绝重复用例 ID 和导入失败。
- 修订测试去掉未声明的 pytest 依赖，改用 unittest 异常断言；预算测试的临时目录注册清理。
- `run_tests.py` 删除早期固定用例数量/耗时描述。计时基线仅同步模块和用例 ID、移除已合并用例，不伪造重新测量数据。

## 必须保留的测试

- `test_layer_ports.py`、`test_encapsulation.py`、`test_digest_coverage.py`、`test_scenario_boundary.py`：
  架构边界棘轮，不因重构或“历史阶段”减弱断言、扩大允许清单。
- `test_security.py`、`test_schemas.py`、审批、锁、摘要、恢复和交付相关测试：安全与协议回归，不是一次性验收。
- `test_a31_thematic.py`、`test_general_thematic.py`、`test_raster_formal.py` 等：分别覆盖表达/属性连接、
  业务工作流和正式渲染，虽有集成范围重叠但验证边界不同，不能按文件名或执行耗时删除。
- `test_template_assets.py`：资产仍随仓库分发，合同有效性和来源完整性仍须验证。
- `manual/real_raster_acceptance.py` 与 `test_real_raster_acceptance.py`：前者是显式手工验收入口，后者以合成输入自测
  该工具的拒绝路径和报告行为。前者不参与 `test_*.py` 自动发现，不是重复测试。
- `helpers.py`、`fixtures/`、`regression-baseline.json`：共享构造器、严格协议样例和分层计时依据，不按“不是 test 文件”清除。

## 执行与后续维护

从仓库根目录执行。下例 `python` 必须替换为已确认的 Python 3.11+ 解释器，不使用 WindowsApps 占位符，
不为运行测试自动安装依赖。

```text
python skills/carto-agent/scripts/tests/run_tests.py --tier fast
python skills/carto-agent/scripts/tests/run_tests.py --tier full
python skills/carto-agent/scripts/tests/run_tests.py --module test_design_revision
python skills/carto-agent/scripts/tests/run_tests.py --tier slow --list
```

- `fast` 只是开发加速；完整合并门禁仍是 `full`。新用例未计时时进入所有层，不能因此假定 fast 一定不渲染。
- `--measure` 会执行全部测试并重写基线。缺少可选 GIS/渲染依赖的主机不适合重测：否则昂贵渲染测试的 skip 耗时会污染分层。
- 缺依赖、测试失败、运行缓慢都不是删除测试的理由；验证报告应区分通过、失败/错误与跳过，不能把跳过当作验收通过。
- 新测试按能力或模块命名；若某个测试只有迁移阶段意义，删除前指出现行替代覆盖，或确认被测实现已移除且无安全回归价值。
