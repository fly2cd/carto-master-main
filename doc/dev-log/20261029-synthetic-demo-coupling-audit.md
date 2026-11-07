# 合成洪涝演示耦合审计与通用内核拆分

日期：2026-10-29  
范围：Carto Master 当前仓库；本文件用于人工审计，运行时不得读取它作为协议。

## 1. 结论

原来的洪涝限制不仅在示例中，还进入了通用请求、模板简报、地图意图、数据准备、候选编译、正式渲染、成品检查和交付包校验。

本次将实现分为 **通用工作流 + 显式场景策略 + 默认拒绝的能力注册表**。没有删除示例，也没有通过取消合成数据/审批限制来假装支持生产制图。

**当前仍只有一个正式开放的策略：合成洪涝演示。** 通用性指后续场景无需复制工作流或修改其中的洪涝分支；不等于任意模板、TIFF、真实 CRS、生产数据或任意版式已经能运行。

以下实现路径如无特别说明，均相对 `skills/carto-agent/`。

## 2. 原耦合位置与处理

| 原位置 | 原先写死的内容 | 本次处理 |
| --- | --- | --- |
| `schemas/template-create-request.schema.json` | `urban-flood-risk`、`1.0.0`、`flood-risk-overview` 和两类源绑定名 | 通用层保留结构约束，业务常量移入 `synthetic-flood-template-request.schema.json` |
| `schemas/generate-request.schema.json` | 固定模板身份、两类角色、风险/人数语义和单位 | 通用角色和单位采用标识符；原限制由 `synthetic-flood-generate-request.schema.json` 叠加 |
| `scripts/carto_core/workflow/template_analysis.py` | `risk_pct`/`capacity` 检查、分级设色/比例符号和 A3 建议 | 委托场景 `source_contract.py` |
| `scripts/carto_core/workflow/template_brief.py` | 固定风险区、避难点的数据角色描述 | 委托场景 `source_contract.py` |
| `scripts/carto_core/workflow/template_author.py` | 整套洪涝模板、Fixture、原型和合同构造 | 移到场景 `author.py`；原入口保留为通用分派器 |
| `scripts/carto_core/workflow/template_validation.py` | 指定 `prototypes/risk-overview.yaml`、洪涝专属验证 RenderScene | 按包内原型声明验证；场景构造移到 `validation.py`；依赖验证不再强制用尽整个表达目录 |
| `scripts/carto_core/workflow/map_generation.py` | 固定 `emergency_mapping`、`flood-risk`、`hazard-result-map`；Brief 同样固定应急场景 | 从注册策略生成 Intent；Brief 使用 Intent 场景；恢复时重验能力及策略证据 |
| `scripts/carto_core/workflow/map_data_preparation.py` | `FloodDataPreparer`、风险/人数内部字段、固定双角色准备 | 移到场景 `data_preparation.py`；通用层保留原子文件操作及 `MapDataPreparer` 分派器 |
| `scripts/carto_core/workflow/map_planning.py` | 固定双图层、分位数分级、面积比例符号 | 移到场景 `planning.py` |
| `scripts/carto_core/compiler/map_candidate.py` | 洪涝色带、字段表达式、避难标签、固定画布与演示内容 | 移到场景 `candidate.py`；通用层继续验证已安装模板的完整性 |
| `scripts/carto_core/workflow/map_render.py` | 强制声明的中文常量 | 声明读取绑定的场景策略；仍要求场景恰好包含一次，且证据必须匹配 |
| `scripts/carto_core/workflow/map_final_check.py` | A3 PDF 尺寸、许可、声明、风险/人数内部字段；图例必须含避难人数符号 | 尺寸来自锁定目标；许可/声明/内部字段来自策略；业务图例判断移到 `final_checks.py` |
| `scripts/carto_core/repository/delivery_repository.py` | README 必须包含洪涝中文常量 | 按权威 Manifest 的许可和限制核对 README；服务层在消费 G3 前对照锁定策略核验 Manifest |
| `schemas/formal-render-evidence.schema.json`、`delivery-manifest.schema.json` | 在通用 Schema 内固定中文声明 | 结构层要求非空声明；精确内容由运行时绑定策略验证，不能用其他非空文本替代 |

## 3. 有意保留的洪涝相关文件

这些属于明确的示例/场景/阶段边界，不应通过删除它们来“通用化”：

- `scripts/carto_core/scenarios/synthetic_flood/`：该演示场景的唯一实现位置，包含源契约、作者、数据准备、规划、候选、验证场景和图例检查。
- `policies/scenario-capabilities.yaml`：当前已验收场景的显式允许列表，`default: deny`、`production_enabled: false`。
- `schemas/synthetic-flood-*.schema.json`：只收紧该场景的身份/角色限制，不复制另一套通用协议。
- `templates/map-scenario/urban-flood-risk/1.0.0/`：合成示例包；保持其内容及逐字节回归断言，不加入自动发现或绕过发布。
- `scripts/tests/fixtures/` 及现有洪涝流程测试：合法的样例和回归数据，不作为运行时输入来源。
- 仓库根下 `tools/host/generate_flood_sample.py`：明确命名的示例脚本，而非通用流程；本次不修改。
- `policies/scope-baseline.yaml`：保留现有首个切片及未开放生产能力的阶段基线，不改写为通用生产授权；模板对它的现有摘要绑定保持不变。
- `policies/map-expression-catalog.yaml`、`checker-registry.yaml`：保留当前实现/验收过的表达与检查器范围；它们不是“所有场景必须使用同一份洪涝实现”的理由。
- `scripts/carto_core/workflow/intent.py`：在多业务关键词表中包含“洪涝/洪水”是正常路由词汇，不是把所有请求改写为洪涝。
- README、工作流与历史设计文档中的洪涝说明：描述当前能力和示例，不作为机器协议读取。

## 4. 新边界如何工作

```text
用户请求
  → 通用结构 Schema
  → ScenarioRegistry 精确查找模板类型 / ID / 版本
  → 场景专用请求约束
  → 已注册代码组件
  → 通用状态机、路径/数据摘要校验、审批和产物流程
  → 冻结策略引用
  → 正式渲染、成品检查、G3 与交付
```

- 注册表只从 Skill 固定策略路径加载，不从业务请求读取模块路径，不读取 `doc/` 或测试 Fixture。
- Python 组件由代码内白名单指定。给策略文件填写任意模块名不会触发动态导入。
- Intent 的 `evidence_refs`、候选和 MapSpecLock 的 `execution.profile_refs` 包含策略 ID、版本和完整定义的规范摘要。
- 策略声明、许可、主题或输出规格发生变化时，原锁的引用不再匹配，后续操作拒绝继续。
- 未绑定策略的既有锁不自动兼容：需要新运行并重新经过所需审批，不补写/伪造摘要。
- `synthetic_data_notice` 协议字段和既有 `final.synthetic-notice` 检查器 ID 暂时保留；它们不再固定洪涝文案，也没有新增一套旧命名兼容协议。
- 普通日志、交付包白名单、允许根、模板摘要、审批主体/对象/作用域/时效/nonce 校验均保持。

## 5. 仍未通用化的能力边界

以下不是本次放开的功能，调用者仍须得到明确拒绝或能力不足：

- 生产数据、安全敏感业务数据、外部发布。
- TIFF/Shapefile/GeoPackage/数据库等其他制图输入，以及真实 CRS 重投影。
- 多场景生产覆盖、任意模板 ID 或任意版本自动接入。
- 任意多视图布局、任意字体组合、任意输出目标。当前通用校验器仍有单页 PDF/PNG、现有 SVG 组件版式和安全边距等技术契约。
- 仅改注册配置不会生成新场景的算法、数据适配器、表达方案或安全验收结果。

## 6. 新增场景的工程路径

1. 在 `scripts/carto_core/scenarios/<new_scenario>/` 增加场景实现，复用通用状态机和安全组件；不要在 `workflow/` 增加 `if 场景名` 分支。
2. 实现源语义与简报、模板作者、数据准备、规划、候选编译、验证场景、业务图例检查等对应组件。
3. 基于通用 Schema 叠加专用约束，提供合法样例、非法样例和自动测试；不通过放宽旧演示策略冒充新能力。
4. 将组件加入代码白名单并登记版本化能力策略。需要更丰富的通用技术契约时，应单独扩展协议并验收。
5. 经模板 `validate → TP → publish`，再跑地图 `intake → … → G1 → … → G2 → … → G3 → deliver` 的完整链路。
6. 生产能力必须另行完成正式能力与安全验收；本次注册协议仍禁止设置 `production_enabled: true`。

## 7. 验证范围

新增 `scripts/tests/test_scenario_registry.py` 覆盖：

- 非洪涝模板身份/单角色/语义单位的通用结构校验。
- 未注册场景/版本无回退、业务角色限制仍生效。
- 未知实现/未知 Schema/重复注册/生产声明被拒绝。
- 策略定义防御性复制、Intent 和执行绑定、策略漂移、目标尺寸漂移。
- 通用 Intent/数据准备/规划使用替代策略时不注入洪涝语义（测试替身，不是新增实际开放场景）。
- PDF 检查使用锁定的 A4 竖向尺寸而不是硬编码 A3。
- 通用模块业务常量回归扫描，以及多个数据源各自保留完整来源证据的回归。

新增集成负例覆盖：即使重算摘要，替换正式渲染声明或移除交付限制/许可，也必须在证据验证或 G3 消费前被拒绝。保留已有模板包逐字节一致性测试。

全量测试命令：

```powershell
python -m unittest discover -s skills/carto-agent/scripts/tests -q
```

最终验证（2026-10-29）：Python 3.14.7，181 项测试，`OK (skipped=2)`，耗时约 284 秒；另通过 `git diff --check`。跳过项不得视为已验收能力。

只读 AST 对比确认：数据准备和规划的既有算法方法未改变；作者策略仅调整相对策略文件路径；候选策略的变化集中在策略引用、业务主题、声明与画布规格绑定。
