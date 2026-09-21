# generate-map 工作流

## 当前能力

- 当前只开放已发布 `map-scenario` 中的合成洪涝风险切片，唯一模板身份为 `urban-flood-risk/1.0.0`。
- 工作流严格按 `intake → brief → compile → preview → freeze → render → check → deliver` 推进；不能跳过 G1、预览证据、G2、正式渲染证据、最终检查或 G3。
- `intake` 校验项目作用域、调用能力、精确模板引用、数据源引用和输出目标，并生成 `MapIntent`。
- `brief` 从权威模板索引发现精确版本，固定数据访问、字段语义、模板摘要和允许操作，随后等待 G1 `approve-map-brief`。
- `compile` 验证 G1，安装已发布模板，准备 `risk-area` 与 `shelter-point` 两类合成 GeoJSON，生成 `PreparedDataBundle`、`MapPlan`、`ResolvedMap`、`RenderScene` 和预检报告；该步骤不启动浏览器。
- `preview` 使用受控 Chromium 生成 SVG、PNG、PDF，验证 RenderReceipt、输出摘要、资源摘要、执行摘要和环境指纹，并生成预览证据。
- `freeze` 重新验证候选、场景、模板、资源、预览产物、回执和环境，验证精确 G2 `approve-freeze` 后创建 create-once `MapSpecLock`，推进到 `pending / render`。
- `render` 只消费 `MapSpecLock` 及其摘要绑定输入，在 `output/<lock-id>/formal-map/<attempt-id>/` 创建不可覆盖 PDF/PNG、正式 RenderReceipt、`RenderAttempt` 和 `FormalRenderEvidence`；成功后进入 `pending / check`。
- `check` 对成功 attempt 执行注册且版本化的最终检查，写入 Final ValidationReport；通过后冻结不可变 DeliveryManifest，返回精确 G3 上下文并进入 `waiting_approval / deliver`。
- `deliver` 重新验证 Manifest、Final ValidationReport、锁、成功 attempt 和 PDF/PNG 摘要，验证并消费精确 G3，执行项目内可恢复交付事务，成功后进入 `succeeded / deliver`。
- `delivery-status` 按 Manifest 中的幂等键查询 DeliveryTransaction 和已存在的 DeliveryReceipt，用于提交结果未知后的确定性查询。

## 固定语义

- 风险区域使用 `choropleth/sequential@1.0.0`，当前分类方法为 quantile。
- 避难场所使用 `proportional-symbol/count@1.0.0`，符号面积与数量成比例。
- 模板语义字段不等同于业务数据列名；数据准备只把批准的源字段映射为 `risk_value` 和 `count_value`，不复制无关属性。
- 分类断点、图例项、实际范围、数据摘要、目标参数和渲染环境属于地图实例候选及锁，不回写模板包。
- 正式交付候选固定为 A3 横向、144 DPI、2381×1684 PNG，并在场景、证据、Manifest 与最终 README 中携带“合成数据演示，非真实风险研判”。

## 成品检查与 G3

- 检查集合绑定 `checker-registry.yaml` 的规范摘要，未知 checker 拒绝。
- Final ValidationReport 检查 PDF/PNG 的文件、媒体签名、大小、摘要、A3 页面、PNG 尺寸/DPI、字体、版式元素、图例/无数据/比例符号语义、声明链、lock/attempt/receipt/evidence 绑定、敏感内容和 renderer warning 处置。
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
- 当前能力仅为“合成数据工程演示闭环”，不声明生产数据制图、真实风险研判或三场景生产能力。

## 尚未开放

- 真实 CRS 转换、生产数据、外部底图联网和外部发布。
- `map-brand`、`map-style`、`map-layout` 的业务创建与组合。
- 任意专题类型、任意字段表达式或任意动态代码执行。

CLI 入口为：

```text
carto generate-map <intake|brief|compile|preview|freeze|render|check|deliver|status|retry|receipts|delivery-status>
```

运行时只读取 Skill 内协议、策略、索引和项目产物，不读取 `doc/` 设计稿。
