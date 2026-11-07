# 业务场景与主题契约统一

日期：2026-11-04

## 本轮范围

按“不要新增业务域，用业务场景即可”修正当前运行框架中的概念与消费链。保留既有布局契约第一阶段以及业务示例清理结果；不添加业务域字段、业务数据、可执行示例场景、默认模板或临时准入配置。不改 `projects/dataset/`、`doc/reference/`、`skills/ppt-master/`。

## 修正项

1. **单一业务分类**：统一 `business_scene`，通过公共 `businessSceneId` 表达类型，成员、任务及用途词由 `intent-profiles.yaml` 管理。移除 MapBrief 固定应急场景及多处重复三场景枚举；未确定场景的 MapIntent 使用 null，不伪造默认任务。
2. **主题单一入口**：统一为 `theme_tags` ID 数组，可多值；展示名存于主题目录。删除旧单值 `theme`、`fields.theme`、`scene_hint` 入口。用途识别词与主题内容词分离，不因“洪涝”或泛化的“专题”一词切换业务场景。
3. **解析器实际接入生成**：新增严格 `intent-request`，独立解析使用 `text + selection`；生成请求必需 `intent`，与 `goal` 一起交给同一解析器。先要求意图就绪，再校验显式模板身份与 `intent_constraints`，不再由模板构造用户意图。当前不实现自动模板检索。
4. **语义不随步骤漂移**：Brief、Plan、execution 保留同一业务场景、主题和任务；计划绑定已审批 Brief，候选绑定原 Intent。恢复时重新从请求解析并精确比较，模板允许集合内的意图改写也不能继续。
5. **版本绑定**：独立 Intent 固定 `[目录, 输入]`，选定模板后追加能力策略引用；execution 的 `profile_refs` 固定 `[目录, 能力策略]`。意图目录版本 2.0.0，能力策略版本 1.2.0；目录完整内容或能力策略漂移均拒绝。
6. **术语区分**：MapScenario.scenario_id 是模板方案身份，RenderScene.scene_id 是渲染实例身份，二者不是业务分类。知识服务的技术命名不新增任何业务域分类层级。

## 主要文件

- `skills/carto-agent/schemas/common.schema.json`、`intent-request.schema.json`、`map-intent.schema.json`、`intent-profiles.schema.json`、`generate-request.schema.json`、`map-brief.schema.json`、`map-plan.schema.json`、`scenario.schema.json`、`scenario-capabilities.schema.json`。
- `skills/carto-agent/scripts/carto_core/workflow/intent.py`、`scenario_registry.py`、`workflow/map_generation.py`、`workflow/map_planning.py`、`compiler/map_candidate.py`、`workflow/template_validation.py`、`cli.py`。
- `skills/carto-agent/workflows/intent-contract.md`：输入结构、用途/主题/模板身份、状态、准入与迁移说明。
- `skills/carto-agent/scripts/tests/test_intent_semantics.py` 及对应协议 Fixture；既有意图测试和共享 Schema Fixture 同步更新。

## 验证记录与边界

**遵守用户限制，没有运行测试代码，也没有运行项目 CLI、渲染器或宿主探针。**

仅完成静态检查：

- `ast.parse` 读取 75 个 Python 文件，无语法错误；未导入项目或测试模块。
- JSON 解析 59 个文件、安全 YAML 解析 10 个文件，无解析错误。
- 本地解析 559 个 Schema `$ref`，未发现缺失目标。
- 通过 AST 读取 Fixture 键声明，覆盖 50 个实例 Schema；没有执行 Fixture 模块或断言。
- 运行代码没有三场景 ID 的硬编码字符串；相关产物复用公共业务场景类型。
- 执行能力策略仍为 `default: deny`、`profiles: []`；组件白名单未启用业务实现。
- `git diff --check` 未报空白错误；仅有既有文件的 LF/CRLF 提示。

新增测试定义覆盖：主题不误判用途、主题多值、旧字段拒绝、缺任务不补默认值、目录扩展与漂移、独立/生成意图一致性、模板不兼容、意图篡改、非应急简报构建、计划和候选语义绑定。上述为**已编写但未执行**，不是测试通过或真实业务验收结论。

本轮收紧输入与冻结绑定，旧 profile 的 scene_id/固定 intent、旧请求、旧候选与旧锁不自动兼容。接入真实场景需按新协议提交意图，完成对应实现、严格 Schema、注册和用户授权的真实数据验收；不修改既有发布包/冻结锁来迁就新协议。
