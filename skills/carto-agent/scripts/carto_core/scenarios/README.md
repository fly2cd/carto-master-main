# 场景实现扩展边界

当前目录没有可用业务实现，`scenario-capabilities.yaml` 的 `profiles` 和 `scenario_registry.py` 的代码白名单均为空。请求通过共享 Schema 并不代表场景可用；未知请求必须拒绝。

## 术语与契约

- 业务场景只用 `business_scene`，不新增业务域。它是业务用途分类；`scenario_id` 是模板方案 ID，`RenderScene.scene_id` 是渲染实例 ID，不互为别名。
- 新业务用途的 ID、用途识别词、任务和必需信息登记在 `policies/intent-profiles.yaml`。主题以独立 `themes` 词表登记 ID、显示名和内容词，不通过内容词自动推断业务用途。登记识别词表不会开放执行能力。
- 模板能力登记 `intent_constraints`：`business_scene`、`allowed_tasks`、`allowed_theme_tags`、`required_theme_tags`。允许的任务和主题须已在意图目录登记，必需主题必须是允许主题的子集；不用固定 `intent` 作为生成默认值。
- MapScenario 的业务场景须等于能力约束，任务集合须等于 `allowed_tasks`，模板 ID/版本须等于能力注册。当前仍需用户显式选模板；不自动找模板。
- `planner` 输出的 MapPlan 必须原样保留 Intent 的 `business_scene`、`theme_tags`、`tasks`，并绑定 Intent/已审批 Brief 摘要。通用层在调用组件前后验证，不接受组件改写语义。
- `candidate_compiler.compile` 返回 `{candidate, scene, preflight}`。其中 `candidate.execution` 保留 Intent 的业务场景、任务、`shared_semantics.theme_tags`，`profile_refs` 为 `[意图目录引用, 能力策略引用]`，`intent_ref` 固定完整 Intent；`data_nature` 必须符合能力策略。不得反向从模板构造 Intent。
- 详细输入协议见 `../../../workflows/intent-contract.md`。旧单值主题、旧提示字段和缺失目录绑定的旧产物不自动兼容。

## 接入顺序

1. 先确定获准的真实数据来源、许可、敏感性、CRS、字段角色、空间行为、输出目标与必要使用声明。
2. 在本目录下新增场景模块，在 `schemas/` 增加该场景的严格请求约束。共享协议不够表达新格式时需显式演进，不能塞入临时字段或绕过未知字段拒绝。
3. 实现下列组件，补充合法/非法协议用例、自动测试及真实场景验收证据。
4. 完成实现后再在代码白名单和版本化场景策略中登记准确身份、请求 Schema、输出规格、声明与许可。策略版本及摘要是锁的一部分，不能只修改策略来开放能力。

## 组件与职责

- `source_contract`：提供 `suggestions(profile_definition)`、`validate_role_bindings(request, summaries)`、`brief_roles(request)`；必须提供 `validate_source_profile(source, request)`，在读取源文件前判定来源声明、许可、敏感性及 CRS 是否允许，拒绝时抛出协议/安全错误。来源声明不是安全证明；具体场景还须验证实际内容。
- `author`：由 `workflow/template_author.py` 调用，按已审批简报确定性生成闭合 draft 包，不能携带隐式业务数据或默认示例。
- `validation_data_checker(package_root, snapshot, expected)`：模板静态校验的必需组件，解析声明的验证输入并校验格式、来源 CRS、字段类型、角色覆盖、许可及敏感性。不得把未经授权的业务数据嵌入待发布包。共享校验器不再假定输入为特定 FeatureCollection，也不计算默认 extent；失败必须阻断。
- `validation_scene(package_root, snapshot, targets, font, validator_version)`：按场景规则读取获准的验证输入、计算范围并构建 RenderScene；必须复用公共布局解析器，不得重建硬编码模块位置。
- `data_preparer`、`planner`、`candidate_compiler`：接口分别由 `workflow/map_data_preparation.py`、`workflow/map_planning.py`、`compiler/map_candidate.py` 定义；只映射获准字段，禁止把业务行写入普通日志。
- `legend_checker`：由 `workflow/map_final_check.py` 调用，检查实际实例的图例与业务表达一致性。

所有组件只能通过代码内白名单加载，不接受来自请求的导入路径。缺少来源准入或验证数据检查组件不是“跳过检查”，而是能力不可用。

## 保留的框架限制

- 通用来源摘要读取器目前只有有界 UTF-8 GeoJSON/CSV；GeoJSON 位置检查要求 EPSG:4326，不进行真实投影转换。共享 Schema 能声明某 CRS 不代表读取器支持转换。
- 共享布局支持毫米页面、单地图、DPR=1、无重叠框、地图 clip 与 overlay reject；浏览器/SVG 使用保守包络，静态栅格整页已采用实际字体测量。均不包含复合布局求解。
- 场景声明使用 `scenario_notice` / `final.scenario-notice`；输出必须与冻结场景策略、锁和证据相符。旧字段和缺失布局/策略绑定的旧产物不自动迁移。
- `production_enabled` / `production_ready` 的保守限制及空 `production_tasks` 是尚未完成生产认证的边界，不是可删除的临时开关。
- 场景注册与能力验收不替代 T1 / TP / G1 / G2 / G3。

## 数据类型、表达与后端不作为业务场景注册

分类栅格是数据类型；`raster/categorical` 是共享着色表达；Rasterio + Matplotlib 是静态渲染实现，SVG/PDF/PNG 是输出格式。不能为了接入栅格而添加同名业务场景或放开策略。

`compiler/raster_portrayal.py` 根据显式模板角色和已澄清类别显示定义生成 `resolved-raster-portrayal`。图体与内部整页渲染只消费该合同；它不提供业务来源准入、审批或正式渲染回执。场景组件可以复用共享表达，不得复制另一套类别颜色/图例实现。

第三批 C 已提供 `RasterBundlePreparer` / `RasterSceneCompiler` 与静态正式后端，详情见 `../../../workflows/raster-classification.md`。已准入场景可以复用：

- 数据组件继续从通用入口接收 PathGuard、可信 project_root、output_root 和 SchemaRegistry；在 G1 后，以经审批请求的 ExecutionContext 调用 `prepare_request`，不能把 ready 报告当作审批。
- 候选组件构造器现在接收 `(path_guard, registry, *, project_root, context)`，这两个关键字来自通用工作流，而不是从任意 artifact URI 推断。组件必须接受此接口，不增加旧接口兼容分派；栅格组件用它们构造共享准备/场景编译器。
- `RasterSceneCompiler.bind_execution` 只绑定显示、数据和渲染环境；意图、模板、策略和业务声明仍由场景组件负责。
- 图例检查器接收通用终检上下文；静态分支附有经重验的 `context["raster"]`（bundle/page/portrayal/body/output）。共性分类检查已执行，但仍必须提供用途相关的标签、类别和声明核验。

真正业务用途、模板创建/发布及真实数据的准入另行按上述顺序完成，不能从 TIFF 类型反推用途。
