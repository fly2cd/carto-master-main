# MapScenario 创建、验证与发布

## 输入边界

- 请求必须通过 `template-create-request`。
- 来源清单必须通过 `source-manifest`，来源路径必须位于允许根内。
- 当前只接受受控大小的 UTF-8 GeoJSON/CSV；首个 profile 的风险面和避难点输入必须为显式声明的合成数据。
- 来源摘要不得保留业务数据行、原始坐标或包围盒。

## 步骤

1. `analyze`：验证请求、来源摘要、摘要值、角色与 CRS，生成 `template-analysis` 和来源清单快照。
2. `brief`：区分来源事实、用户决定、系统建议和推导值，生成严格的 `template-brief`。
3. `author`：验证绑定审批人、动作、对象摘要、作用域、时效和 nonce 的 T1 回执，生成不可覆盖的暂存模板包。
4. `validate`：先执行静态校验，再用纯合成 Fixture 进行受控浏览器渲染，生成 SVG、PNG、PDF、RenderReceipt 和 `template-validation-evidence`；存在 blocker 或 error 时不得进入发布步骤。
5. `publish`：重新验证证据与全部绑定，验证 TP 发布审批，将精确版本写入不可变模板仓库并原子更新权威 `template-index.yaml`。

## 审批消费中断恢复

- T1 在消费 nonce 前保存已完成 claims 校验的工作流本地审批意图；中断后只允许按请求和简报确定性重建并精确核对暂存包。
- TP 只允许从不可变发布事务及其中保留的已认证审批恢复。
- 恢复必须证明原 nonce 已消费且动作、对象摘要、作用域、身份、环境和时效仍完全匹配；普通重放和漂移内容均被拒绝。

## 模板包与发布边界

暂存包包含 Manifest、Design Spec、六份业务契约、纯合成 Fixture、原型描述、依赖锁和闭合校验和。`author` 产出的原型声明 `renderer_execution: not-run`；只有 `validate` 可以生成验证渲染证据。

发布身份由 `namespace + kind + id + version` 唯一确定。同一版本不得覆盖；发现操作只读取权威索引，不通过扫描仓库目录推断模板。U-P2.4 只完成模板验证与发布，不生成业务地图候选。