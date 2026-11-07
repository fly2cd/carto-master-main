# 业务场景与主题契约

## 一套业务分类，三个不同层面的身份

| 概念 | 协议字段 | 作用 |
|---|---|---|
| 业务场景 | `business_scene` | 业务用途分类；成员由意图目录管理，不再在多份 Schema 重复枚举 |
| 内容主题 | `theme_tags` | 零到多个主题机器 ID；不是业务用途层级，显示名不进入 ID 字段 |
| 模板方案 | MapScenario 的 `scenario_id` / 请求的 `template.id` | 可复用制图方案的身份与版本；一个业务场景可以对应多个模板 |
| 渲染实例 | RenderScene 的 `scene_id` | 某次候选/渲染输入实例的身份，不参与业务分类 |

不引入 `business_domain` 或业务域层级。业务场景与主题分别表达“为何制图”和“图上表达什么”，二者可以组合，但不相互替代。

## 统一输入

`carto intent resolve <请求文件> --allowed-root <允许根>` 读取 `intent-request.schema.json`：

- 根字段：必需 `schema_version: 1`、`text`、`selection`；可选 `intent_id`、`revision`。
- `selection` 使用 `common.intentSelection`，只有 `fields` 在结构上必需。其余项未提供时进入解析/就绪检查，不代表可以不经澄清直接生成地图。

`generate-request.schema.json` 则必需 `intent`，其结构与上述 `selection` **完全相同**；生成器把 `goal` 当作 `text` 交给同一解析器。生成请求原有的作用域、来源、模板、能力声明、输出与审批约束继续有效。

| 选择项 | 语义 |
|---|---|
| `business_scene` | 可显式提供已登记的用途 ID；未提供时仅依据用途词识别。显式 ID 未登记或与唯一识别用途冲突时不能生成 |
| `theme_tags` | 可显式提供已登记的 ID 数组，保留空数组的含义；未提供时依据内容词推断。最终按 ID 排序，不把显示名当 ID |
| `tasks` | 显式列出当前业务场景支持的任务，非空且不重复；省略时结果为 ambiguous，不自动填第一个任务 |
| `fields` | 场景要求的上下文信息，键必须属于当前场景 `required_information`，值为非空字符串；特殊项 `theme_tags` 从同级标签数组检查，不从 `fields` 读取 |
| `requested_actions` | 请求的附加动作，用于检查场景明确禁止的动作，不是可执行命令或授权 |
| `required_capabilities` | 本次意图所需能力 ID，用于就绪检查，不是能力授权 |

`available_capabilities` 不允许由独立意图请求自报；独立 CLI 没有可信能力集时保守报告缺少所需能力。生成链以原有 `allowed_capabilities` 作就绪约束，随后仍由 ExecutionContext、ToolGateway 和精确审批控制实际调用；任何请求字段都不能自行授予权限。

## 解析与能力准入顺序

1. 校验严格请求结构。拒绝 `scene_hint`、旧单值 `theme`、`fields.theme` 等并行语义入口。
2. 根据 `policies/intent-profiles.yaml` 分别识别业务用途和主题：`profiles[].purpose_terms` 只服务用途识别；`themes[].terms` 只服务内容识别。通用“专题”不作为用途判据。
3. 校验场景内任务、主题目录成员和上下文字段；缺任务/必需信息不补默认值。没有可确定业务场景时用 `business_scene: null` 表示未确定，不填应急或政务占位。
4. 得到 MapIntent 的独立状态：`intent_status` 表示 resolved / ambiguous / unsupported，`readiness_status` 表示信息和能力是否齐备。单独解析可返回未就绪结果；生成入口拒绝继续。
5. 就绪后，按请求明确给出的模板身份查询执行能力注册表，并校验该能力的请求 Schema 与 `intent_constraints`。不兼容返回 `SCENARIO_INTENT_MISMATCH`，无注册能力返回 `CAPABILITY_NOT_AVAILABLE`，不通过改写意图适配模板。

这是“先解析，再校验已选模板”，不是“自动模板检索/推荐”。当前能力策略 `profiles: []` 且组件白名单为空；意图目录保留的用途和主题词汇不能当作已开放场景或测试业务数据。

## 同一语义贯穿生成链

- 独立 MapIntent 的 `evidence_refs` 是 `[意图目录引用, 意图输入摘要引用]`；绑定模板能力后追加能力策略引用。目录引用包含整个目录的摘要；标签或用途词变化同样构成漂移。
- MapBrief 与 MapPlan 的 `business_scene`、`theme_tags`、`tasks` 必须与 MapIntent 一致，`intent_ref` 指向完整意图摘要。计划还必须绑定已审批简报摘要。
- execution 的 `business_scene`、`map_tasks`、`shared_semantics.theme_tags` 保留同一意图；`intent_ref` 固定完整意图，`profile_refs` 必须为 `[意图目录引用, 能力策略引用]`。
- 生成恢复重新从持久化请求解析，并与持久化意图精确比较。即使被改写的标签/任务仍在模板允许集合内，也不能当作原请求继续。
- 预览/冻结校验候选与意图的对应关系；锁驱动渲染、检查和交付重新检查目录与能力策略绑定。其余布局、环境、资源、数据和审批摘要规则不变。

## 演进与兼容性

本轮意图目录版本为 `2.0.0`，能力策略版本为 `1.2.0`。协议文件保持当前 Schema 命名，但输入形状和绑定要求已收紧：旧请求、旧 profile 的 `scene_id`/固定 `intent`、旧单值主题、缺失目录引用的旧候选/锁均不自动兼容。更新真实请求和模板契约后，须重新验证、发布、编译、预览和审批，不修改已有冻结产物。

新增用途只更新意图目录及相应组件/准入策略，不新增业务域。涉及新任务、字段、格式或模板能力时，仍须提供严格协议、合法/非法协议用例、自动测试及获准真实数据验收；不能只加一个目录词或注册项就宣称能力完成。
