# generate-map 工作流

## 当前能力

- 当前只开放已发布 `map-scenario` 中的合成洪涝风险切片。
- 工作流严格按 `intake → brief → compile → preview → freeze` 推进；不能跳过 G1、预览证据或 G2。
- `intake` 校验项目作用域、调用能力、精确模板引用、数据源引用和输出目标，并生成 `MapIntent`。
- `brief` 从权威模板索引发现精确版本，固定数据访问、字段语义、模板摘要和允许操作，随后等待 G1 `approve-map-brief`。
- `compile` 验证 G1，安装已发布模板，准备 `risk-area` 与 `shelter-point` 两类合成 GeoJSON，生成 `PreparedDataBundle`、`MapPlan`、`ResolvedMap`、`RenderScene` 和预检报告；该步骤不启动浏览器。
- `preview` 使用受控 Chromium 生成 SVG、PNG、PDF，验证 RenderReceipt、输出摘要、资源摘要、执行摘要和环境指纹，并生成 `map-preview-evidence`。
- `freeze` 重新验证候选、场景、模板、资源、预览产物、回执和环境，验证精确 G2 `approve-freeze` 后创建 create-once `MapSpecLock`。

## 固定语义

- 风险区域使用面分级表达：`choropleth/sequential@1.0.0`，当前分类方法为 quantile。
- 避难场所使用比例符号表达：`proportional-symbol/count@1.0.0`，符号面积与数量成比例。
- 模板中的语义字段不等同于业务数据列名；数据准备只把批准的源字段映射为 `risk_value` 和 `count_value`，不复制无关属性。
- 分类断点、图例项、实际范围、数据摘要、目标参数和渲染环境属于地图实例候选及锁，不回写模板包。

## 安全与冻结边界

- 所有请求、源数据、字体、模板、候选、预览和锁路径均须位于 `PathGuard` 允许根内。
- 当前数据仅允许 `synthetic=true`、GeoJSON、EPSG:4326；风险区域仅允许 Polygon/MultiPolygon，避难场所仅允许 Point。
- G1/G2 审批必须绑定身份、动作、对象摘要、项目作用域、环境、有效期和一次性 nonce。
- G2 对象摘要绑定 candidate digest、execution digest、preview evidence digest、项目、作用域、环境和渲染环境指纹。
- `MapSpecLock.execution` 必须与批准候选的 execution snapshot 完全一致；冻结阶段不得重新计算分类断点或重新设计图面。

## 尚未开放

- 真实 CRS 转换、生产数据、外部底图联网、G3、正式渲染、正式交付和外部发布。
- `map-brand`、`map-style`、`map-layout` 的业务创建与组合。
- 任意专题类型、任意字段表达式或任意动态代码执行。

CLI 入口为 `carto generate-map <intake|brief|compile|preview|freeze|status|retry|receipts>`。运行时只读取 Skill 内协议、策略、索引和项目产物，不读取 `doc/` 设计稿。


## U-P2.7 state operations

- `status` reports revisioned state and transition-recovery information.
- `receipts` returns validated immutable receipts for audit and replay diagnosis.
- `retry` is limited to a current `failed` state and never removes prior artifacts or receipts.
- Every mutating route step is protected by the same run-wide single-writer lock and stale revisions are rejected.
- G1 writes a claims-validated workflow-local approval intent before nonce consumption. Recovery must deterministically rebuild and exactly verify the installed template, prepared data, plan, resolved map, render scene, and preflight report.
- G2 recovery is accepted only when the existing immutable `MapSpecLock` and the full approval context exactly match the approved candidate, execution snapshot, preview evidence, scope, identity, environment, and renderer fingerprint.
- Recovery never consumes an approval nonce twice and does not permit ordinary approval replay.
