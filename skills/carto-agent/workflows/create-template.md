# create-template 工作流

当前仅注册 `general_thematic_mapping` 一个业务场景；其余场景默认拒绝。以下步骤对该场景是真实编排边界，不代表其他业务能力已开放。

## 当前编排（仅 general_thematic_mapping）

- 通过 `policies/scenario-capabilities.yaml` 选择创建策略；当前仅注册 `general-thematic-mapping`。请求必须同时通过通用 `general-template-create-request` 和场景专用约束。
- 通用分析、简报、作者和验证入口不固定业务字段；场景组件扩展位置为 `scripts/carto_core/scenarios/`，未知场景不能回退到其他实现。
- 工作流严格按 `analyze → brief → author → validate → prepare-publish → publish` 推进，不能跳过步骤或以独立渲染替代验证。
- 单一审批门为 TP（`approve-template-publish`）。`brief` 是设计意图记录而非审批对象；`author` 不再要求 T1 或审批密钥，只产生确定性草稿。唯一人工确认位于 `prepare-publish` 之后，批准的是固化的发布对象。
- `validate` 先执行模板包闭合、Schema、依赖锁、类型所有权、业务语义和目标能力校验；静态检查通过后，由注册场景的样张渲染分支生成预览及带签名的 RenderReceipt。已注册的 `general_thematic_mapping` 从包内图例样本派生确定性合成栅格（展示 CRS 为地理坐标系、缺栅格渲染依赖或缺可嵌入字体时失败关闭），经授权 MCP 网关测量统计后以 `rasterio-matplotlib-page` 后端渲染 PDF+PNG，并冻结渲染场景供发布复核。
- `prepare-publish` 是机器准备动作：核对已通过验证与作者输出一致后，固化 `template-publication` 对象（绑定 run、请求摘要、包、证据、目标库 scope 与规范化 root、幂等键），进入 `waiting_approval/publish`；不消费 nonce、不签署、不发布。重复准备复用同一对象。
- `publish` 从固化对象读取目标与幂等键（CLI 传入值仅作一致性断言），重新核验模板包、依赖锁、Fixture、检查器集合、RenderReceipt、预览成果和渲染器环境绑定；栅格样张还须按冻结的 `render_scene_ref` 复现并比对输出摘要，再验证 TP 签署的正是该对象，写入不可变模板仓库及权威索引。
- 已发布模板使用 `namespace + kind + id + version` 精确标识；同版本内容不可覆盖，发布请求必须携带幂等键。
- 段引用（S2）：创建请求可用可选 `segment_refs` 将 cartography/layout 逐段指向已发布段模板（cartography→map-style、layout→map-layout），作者只内嵌其余段并把引用段标记为 replaceable，引用同时钉入 `manifest.dependencies` 与依赖锁。`validate` 需额外提供 `--repository-root/--repository-scope`，从仓库按摘要拉取段包并复验完整性后物化为完整场景再走全部静态门禁与样张渲染；`publish` 复核时重新解析，段包篡改、摘要漂移或缺仓库一律失败关闭。引用段所有权归对应段类型；包本体不改写，全内嵌旧路径零改动。品牌段（map-brand/identity）已于 2026-11-18 经用户授权整体移除（无渲染消费者）。

## 能力边界

- `map-style`、`map-layout` 尚未开放业务创建流程。
- 不提供独立的 `create-template render`；Fixture 渲染只能在 `validate` 内受控执行。
- 验证渲染不代表生产数据地图生成，也不提供真实 CRS 转换或正式交付。
- 地图候选生成与冻结由独立的 `generate-map` 路由负责，不得复用模板创建审批或暂存包。

具体 MapScenario 约束见 `create-template/map-scenario.md`。运行时只读取 Skill 内协议，不读取 `doc/` 设计稿。


## U-P2.7 state operations

- `carto create-template status` returns the current revisioned state, transition-recovery status, receipt count, and staging-package presence.
- `carto create-template receipts` reads and validates immutable step receipts without modifying them.
- `carto create-template retry` is accepted only when the current state is `failed`; it increments the attempt and revision without deleting prior evidence. Validation retries write to `validation/attempt-N/`, and publish resolves the successful evidence through its immutable step receipt.
- An interrupted receipt/state commit is recovered from `.state-transition.json`; a missing or drifted receipt blocks recovery rather than guessing.
- `prepare-publish` 不消费审批 nonce；中断后重复准备复用同一固化对象。TP 恢复仅接受不可变发布事务及其保留的已认证审批与发布对象；索引中断仅在对象/审批/包树全部核验且索引仍等于 `index_digest_before`、重建结果等于 `index_digest_after` 时受限恢复。
- Recovery never consumes an approval nonce twice and does not permit ordinary approval replay.

## S1 参数化布局验证

当前 general 作者输出单个 `general-thematic-map@3.0.0` 包。Layout 声明 1×1、1×2、2×2 与 independent/shared 的六种组合；生成时只选参数，不改包也不复制五份固定模板。`validate` 对每种组合构建合成样张、冻结场景并取得真实 PDF/PNG 渲染回执；首组合保留主证据字段，另外五项记录于 `template-validation-evidence.grid_cases`。`publish` 根据包内声明重新检查完整集合、每个场景的模板/参数/外观、回执和输出；缺失、重复、交换或篡改均拒绝。

旧模板版本及旧验证证据不自动升级；旧（v1、含 T1）未完成运行不被静默迁移，需以新请求与新运行重新开始；旧已发布模板仍按现有安装与完整性检查使用。模板检索或无匹配时自动创建尚未实现；有限参数化不意味着任意布局求解、独立 Layout 创建路由或生产能力已开放。
