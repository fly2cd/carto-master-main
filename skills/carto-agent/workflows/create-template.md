# create-template 工作流

当前仅注册 `general_thematic_mapping` 一个业务场景；其余场景默认拒绝。以下步骤对该场景是真实编排边界，不代表其他业务能力已开放。

## 当前编排（仅 general_thematic_mapping）

- 通过 `policies/scenario-capabilities.yaml` 选择创建策略；当前仅注册 `general-thematic-mapping`。请求必须同时通过通用 `template-create-request` 和该场景的专用约束 `general-thematic-template-create-request`。
- 通用分析、简报、作者和验证入口不固定业务字段；场景组件扩展位置为 `scripts/carto_core/scenarios/`，未知场景不能回退到其他实现。
- 工作流严格按 `analyze → brief → author → validate → publish` 推进，不能跳过步骤或以独立渲染替代验证。
- `author` 必须验证独立审批人的 T1 `approve-template-brief` 回执，且不得复用地图生成 G1 审批。
- `validate` 先执行模板包闭合、Schema、依赖锁、类型所有权、业务语义和目标能力校验；静态检查通过后，由注册场景的样张渲染分支生成预览及带签名的 RenderReceipt。已注册的 `general_thematic_mapping` 从包内图例样本派生确定性合成栅格（展示 CRS 为地理坐标系、缺栅格渲染依赖或缺可嵌入字体时失败关闭），经授权 MCP 网关测量统计后以 `rasterio-matplotlib-page` 后端渲染 PDF+PNG，并冻结渲染场景供发布复核。
- `publish` 会重新核验模板包、依赖锁、Fixture、检查器集合、RenderReceipt、预览成果和渲染器环境绑定；栅格样张还须按冻结的 `render_scene_ref` 从冻结页面复现并比对输出摘要（不依赖作者宿主字体），再验证 TP `approve-template-publish` 回执并写入不可变模板仓库及权威索引。
- 已发布模板使用 `namespace + kind + id + version` 精确标识；同版本内容不可覆盖，发布请求必须携带幂等键。

## 能力边界

- `map-brand`、`map-style`、`map-layout` 尚未开放业务创建流程。
- 不提供独立的 `create-template render`；Fixture 渲染只能在 `validate` 内受控执行。
- 验证渲染不代表生产数据地图生成，也不提供真实 CRS 转换或正式交付。
- 地图候选生成与冻结由独立的 `generate-map` 路由负责，不得复用模板创建审批或暂存包。

具体 MapScenario 约束见 `create-template/map-scenario.md`。运行时只读取 Skill 内协议，不读取 `doc/` 设计稿。


## U-P2.7 state operations

- `carto create-template status` returns the current revisioned state, transition-recovery status, receipt count, and staging-package presence.
- `carto create-template receipts` reads and validates immutable step receipts without modifying them.
- `carto create-template retry` is accepted only when the current state is `failed`; it increments the attempt and revision without deleting prior evidence. Validation retries write to `validation/attempt-N/`, and publish resolves the successful evidence through its immutable step receipt.
- An interrupted receipt/state commit is recovered from `.state-transition.json`; a missing or drifted receipt blocks recovery rather than guessing.
- T1 writes a claims-validated workflow-local approval intent before nonce consumption. If interruption occurs after consumption, recovery must reconstruct and exactly verify the deterministic staging package; an unrelated existing package or a missing intent is rejected.
- TP recovery is accepted only from the immutable publication transaction and its retained authenticated approval.
- Recovery never consumes an approval nonce twice and does not permit ordinary approval replay.
