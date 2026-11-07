# generate-map 工作流

## 宿主检查与本工作流的关系

首次核对 Hermes 接入或更换宿主工具时，按 `host-preflight.md` 做辅助检查。缺少能力如实报告；`probe-host` 成功不意味着本工作流可以处理真实 TIFF，不替代 G1/G2/G3，也不代表第二批结果回传已实现。

## 场景分派约束

- 通用请求 Schema 只负责结构；运行入口还必须验证注册能力及该场景明确注册的请求约束。
- 数据准备、规划、候选编译和业务图例检查由注册的场景组件承担，实现入口保留在 `scripts/carto_core/scenarios/`，当前无启用实现。
- 先以 `goal + intent` 解析实际用户意图，再检查明确选定模板的 `intent_constraints` 是否兼容；绝不从模板策略反填业务场景、主题或默认任务。Intent 与 Brief/Plan 的业务场景、主题和任务一致，execution 使用同一语义。
- Intent 的 `evidence_refs` 按顺序绑定意图目录、用户意图输入、模板能力策略；execution 的 `profile_refs` 为 `[意图目录引用, 能力策略引用]`，并通过 `intent_ref` 绑定完整 Intent。旧格式或任一摘要漂移均拒绝。
- 输入与术语规范见 `intent-contract.md`；本阶段仍要求显式模板引用，没有自动模板检索或候选排序。
- 正式渲染与交付使用绑定策略的输出规格、声明和许可；合法的任意字符串不能替代该场景的强制声明。旧锁缺少策略绑定或策略发生漂移时应开始新运行并重新审批，不自动迁移。
- 仍未开放生产数据、任意输入格式、真实 CRS 转换或任意版式；结构参数化不代表已实现这些能力。

## 当前能力

- `policies/intent-profiles.yaml` 是意图识别目录，`policies/scenario-capabilities.yaml` 是独立的执行能力准入策略；后者当前 `profiles: []` 且代码实现白名单为空。意图未就绪先报意图错误；就绪后无匹配能力返回 `CAPABILITY_NOT_AVAILABLE`，不存在备用场景。
- 工作流严格按 `intake → brief → compile → preview → freeze → render → check → deliver` 推进；不能跳过 G1、预览证据、G2、正式渲染证据、最终检查或 G3。
- `intake` 先解析 `MapIntent` 并检查所选模板兼容性，再校验项目作用域、调用能力、精确模板引用、数据源引用和输出目标；缺场景、任务或该场景所需主题时不通过模板补齐。
- `brief` 从权威模板索引发现精确版本，固定数据访问、字段语义、模板摘要和允许操作，随后等待 G1 `approve-map-brief`。
- `compile` 验证 G1，安装已发布模板，调用注册场景的数据准备器，生成 `PreparedDataBundle`、`MapPlan`、`ResolvedMap`、`RenderScene` 和预检报告；该步骤不启动浏览器。
- `preview` 按候选中冻结的 `renderer_id` 选择后端：`maplibre-web` 使用受控 Chromium，`rasterio-matplotlib-page` 使用 Rasterio + Matplotlib；验证正式 RenderReceipt、输出/资源/执行摘要和环境指纹，生成预览证据。栅格不经过浏览器，也不接受浏览器回执。
- `freeze` 重新验证候选、场景、模板、资源、预览产物、回执和环境，验证精确 G2 `approve-freeze` 后创建 create-once `MapSpecLock`，推进到 `pending / render`。
- `render` 只消费 `MapSpecLock` 及其摘要绑定输入，在 `output/<lock-id>/formal-map/<attempt-id>/` 创建不可覆盖 PDF/PNG、正式 RenderReceipt、`RenderAttempt` 和 `FormalRenderEvidence`；成功后进入 `pending / check`。
- `check` 对成功 attempt 执行注册且版本化的最终检查，写入 Final ValidationReport；通过后冻结不可变 DeliveryManifest，返回精确 G3 上下文并进入 `waiting_approval / deliver`。
- `deliver` 重新验证 Manifest、Final ValidationReport、锁、成功 attempt 和 PDF/PNG 摘要，验证并消费精确 G3，执行项目内可恢复交付事务，成功后进入 `succeeded / deliver`。
- `delivery-status` 按 Manifest 中的幂等键查询 DeliveryTransaction 和已存在的 DeliveryReceipt，用于提交结果未知后的确定性查询。

## 静态分类着色栅格接入

共享实现及输入例子见 `raster-classification.md` 的“第三批 C”。这不是独立顶层路由。

- 已准入场景的数据组件在 G1 后可调用 `RasterBundlePreparer.prepare_request`；请求必须包含唯一 GeoTIFF source binding 和精确 `prepared_raster_bindings`。准备报告只证明数据/显示定义已澄清，不代替 G1。
- 候选组件调用 `RasterSceneCompiler.compile` 和 `bind_execution`，保留业务意图、模板、策略引用；通用 `MapCandidateCompiler` 再核对请求、bundle、execution 和场景。共享模块不会生成业务模板或选择场景。
- 候选和锁通过 bundle/page 引用冻结 TIFF、CSV、MCP 证据、类别表达、布局和 TTF；JSON 文档用规范摘要，二进制用原始字节摘要，模式由实现确定而非调用方任选。
- 正式回执绑定真实运行依赖、渲染代码、session、资源集、页面报告和成果。HMAC 只证明持钥本地渲染器签发及绑定，不宣称硬件证明、OS/网络沙箱或逐像元遥感语义正确。
- 终检继续要求场景图例检查器、声明与许可；增加静态分支的毫米页面、像素/DPI、真实字体、测量布局、共用分类表与 nearest/掩膜策略检查。失败不发 G3 Manifest。
- G2/G3 仍校验精确对象、身份、scope、environment、issuer、policy、时效和 nonce；原子交付包仍仅含 PDF/PNG、说明和清单，不打包原始 TIFF/CSV、内部回执或审批。
- 当前场景策略为空。测试只对候选边界注入合成场景/模板准入，验证真实预览到交付链；不声称已打通真实 T1/TP/G1 或已制作用户地图。

## 场景语义

- 输入角色、字段映射、表达方法和范围计算由场景组件定义，不由通用流程填入默认业务字段。
- 分类断点、图例项、实际范围、数据摘要、目标参数和渲染环境属于候选与锁，不回写模板包。
- 页面规格从冻结布局及场景输出策略获取；声明来自同一场景策略，通过 `scenario_notice` 和 `final.scenario-notice` 核验完整链路。
- 共享协议描述的结构不等于读取器或场景已经支持相应数据；新格式和真实 CRS 转换须单独实现和验收。

## 成品检查与 G3

- 检查集合绑定 `checker-registry.yaml` 的规范摘要，未知 checker 拒绝。
- Final ValidationReport 检查 PDF/PNG 的文件、媒体签名、大小、摘要、锁定的页面规格、PNG 尺寸/DPI、字体、版式元素、图例/无数据/比例符号语义、声明链、lock/attempt/receipt/evidence 绑定、敏感内容和 renderer warning 处置。
- 任一 `blocker/error` 失败或 warning 未被接受，运行进入 `failed / check`，不生成 DeliveryManifest；普通 `retry` 不允许绕过成品失败。
- G3 必须为 `approve-delivery / delivery-manifest`，`object_digest` 必须等于完整不可变 DeliveryManifest 的规范摘要，并严格绑定 approver、tenant、scope、environment、policy、issuer、时效和 nonce。
- G3 消费前写入 workflow-local intent；nonce 已消费时，仅当该 intent 与当前审批文件完全一致才允许恢复。缺失或漂移均拒绝，普通 replay 不构成恢复。

## 原子交付事务

固定顺序为：

```text
验证 Manifest/报告/成果与 G3
  → 创建 DeliveryTransaction intent
  → 在最终目录同级隔离 staging 构建成果包
  → 校验白名单、摘要、清单、许可和限制
  → os.replace 原子提交最终目录
  → 写不可变 DeliveryReceipt
  → 写步骤回执并完成 succeeded/deliver
```

- 事务 journal 位于 `<project>/.carto/delivery/transactions/`，回执位于 `<project>/.carto/delivery/receipts/`；运行时通过显式引用和幂等键查询，不依赖目录计数推断 ID。
- 最终包白名单固定为 `map.pdf`、`map.png`、`README.md`、`delivery-manifest.yaml`、`checksums.sha256`。
- 最终目录已存在时不覆盖；只有文件集合、Manifest、checksum 和成果摘要完全一致时才作为已提交事务恢复。
- 同幂等键同对象返回已有事务/回执；同幂等键绑定不同 Manifest、接收方、目的地、项目或运行时返回 `IDEMPOTENCY_CONFLICT`。
- staging、原子提交后、回执写入后和步骤回执前的中断均可依据不可变事务事实恢复；不得通过逐文件写入最终目录宣称原子成功。

## 安全与能力边界

- 所有项目输入、输出、回执、attempt、报告、Manifest、staging 和最终路径均经过 `PathGuard`，symlink/junction 和受保护目录被拒绝。
- 交付包不包含原始数据、内部锁、审批文件或密钥、RenderReceipt、FormalRenderEvidence、内部 ValidationReport。
- 当前只支持项目根/允许根内的本地目录交付；不支持外部连接器、网络发布或共享服务提交。
- 当前无启用业务场景，不声明生产数据制图或三场景生产能力。

## 尚未开放

- 真实 CRS 转换、生产数据、外部底图联网和外部发布。
- `map-brand`、`map-style`、`map-layout` 的业务创建与组合。
- 任意专题类型、任意字段表达式或任意动态代码执行。

CLI 入口为：

```text
carto generate-map <intake|brief|compile|preview|freeze|render|check|deliver|status|retry|receipts|delivery-status>
```

运行时只读取 Skill 内协议、策略、索引和项目产物，不读取 `doc/` 设计稿。
