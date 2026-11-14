# generate-map 工作流

更新：2026-11-13，A3.1 专题核心重构。本文描述当前可执行边界，不代表全部目标能力已经实现。

## 1. 一条主流程，两种数据策略

```text
intake → brief → [G1] compile → preview → [G2] freeze
                         ↑       │
                         └─ revision-brief → [新 G1] revise
freeze → render → check → 成品 review → 冻结 DeliveryManifest → [G3] deliver
```

- `general_thematic_mapping` 是一个业务场景，栅格和矢量共用状态机、审批、预览、冻结、检查和交付。
- 策略 `scenario-capabilities.yaml` v1.7.0 只登记一个能力档案 `general-thematic-mapping@5.0.0`；栅格与矢量是它的 `geometry_variants` 数据适配变体，共享段只声明一遍。请求声明 `geometry`，变体声明 `template_geometry` 和 `renderer_id`，不根据版本号猜几何类型。
- 当前模板资产为 `general-thematic-map@3.0.0`（栅格变体）与 `@4.0.0`（矢量变体）。版本号只是已登记资产的身份，不是运行分派规则。两者均为非生产准入，`production_enabled: false`；撤销某几何的准入就是删除对应变体。
- 模板提供可复用布局、样式和支持的表达，不替用户选择本次指标、单位、分级方法。已有适配模板直接复用，不要求每次先创建模板。自动模板检索、无模板项目设计仍未实现。

## 2. 输入分清事实、设计和执行

`goal` 表示业务任务；`map_title` 表示实际页面标题，不再强制二者相同。每个面板必须有 `design`。旧 `vector_panels[].encoding` 请求不再接受，不自动补默认表达。

### 栅格

- 用户提供已分类 TIFF、精确源绑定、`prepared_raster_bindings` 和就绪分类合同。
- 面板显式选择 `{"geometry":"raster","kind":"categorical","measurement":"nominal","palette_source":"prepared"}`。
- 本期只消费准备合同中已确认的类别与配色。连续栅格任意分级、独立栅格配色修订尚未开放，不能描述为完整的事实/表达拆分。
- 单图使用 `main-view`；多图使用 `view-r{row}-c{column}`。面板标题和页面 `map_title` 职责不同。

### 矢量

- `vector_sources` 声明 GeoJSON 或完整 Shapefile 文件组、原生 CRS、摘要、编码、许可。
- `vector_panels` 声明 `source_id`、`extent`、标题和 `design`。当前支持点/面，不隐式重投影、不做栅矢混排。
- `design` 显式选择字段、度量类型、单位、符号和缺失处理。程序只验证和机械计算，不替用户挑业务指标。

| 表达 | 本期执行范围 | 拒绝的情况 |
|---|---|---|
| 单一符号 / 类别表达 | 明确类别、标签、颜色；图例来自实际表达 | 重复类别、歧义图例、未声明值、类型不匹配 |
| 分级设色 | 面数据；比率、密度、归一化指标；等距或手工断点 | 原始总量冒充密度、断点未覆盖、非有限值、符号数不匹配 |
| 比例符号 | 点数据总量；按面积比例推导半径 | 负数、越界、未明确零值策略、通过钳位伪造可读性 |

归一化声明 `normalization: {denominator_field, scale}`，或 `null` 表示输入字段已经是所声明度量。分母必须有限且大于零。程序不能凭字段名字证明业务含义，仍需业务核实。

### 属性表和普通素材

- 可选 `vector_sources[].attribute_join` 声明 CSV 摘要/大小、两端键、所选字段/类型和缺失策略；需 G1 范围包含 `join`。
- 本期只做字符串键一对一、完全匹配连接。重复键、孤立行、字段覆盖和非有限数值拒绝，不做模糊匹配或任意 SQL。
- CSV 解析复用 A2 提取器，冻结表格字节和连接证据。变更 CSV 必须形成新的源声明和授权对象。
- A2 普通文本/CSV 素材冻结字节、提取、采用结果及事实引用。材料里的文字不是智能体指令。图片、OCR、文档版式解析不因本期接入而自动开放。

## 3. 各步骤负责什么

1. **intake**：核验请求、意图、能力和项目范围，保存不可变初始请求。
2. **brief**：列明数据访问、字段、允许操作、模板和输出；完整请求摘要纳入 MapBrief，返回 G1 批准对象。
3. **compile**：验证 G1 后准备数据，将显式设计解析为 MapPlan v4，编译候选、场景和预检报告；不启动渲染器。
4. **preview**：用确定后端渲染整页，核验签名回执、资源、页面和环境指纹。矢量/栅格静态后端均不经过浏览器。
5. **freeze**：重验完整候选和预览，消费绑定精确对象的 G2，创建不可变 MapSpecLock。
6. **render**：只按锁输出，不重新选指标、分级、配色或布局。
7. **check**：自动终检，保存最终 ValidationReport。通过后进入 `waiting_approval / review`，此时还没有交付清单。
8. **review**：审阅与终检报告绑定的实际成品，签署 `approve-product-review / validation-report`；保存 ProductReview，再冻结包含 `review_ref` 的 DeliveryManifest。这不是 G2，也不是新增 G4。
9. **deliver**：验证审查依据、Manifest、实际成果及精确 G3，执行本地原子交付，保存回执。

成品 review 是明确签署的审查结论，不是程序自动宣称“人工已看图”。多专业会签、印刷打样、业务采用仍需后续专用协议。

## 4. 如何修改设计

冻结前的 compile / preview / freeze 状态可提交 DesignRevisionProposal，允许修改页面标题、面板 design、网格参数、显式 cartography。

1. `revision-brief` 输出完整修订 MapBrief 及摘要，不代签审批、不修改状态。
2. 对该 MapBrief 签新 G1，再调用 `revise`；G1 只签提案摘要会被拒绝。
3. `revise` 返回新的 `request_path`；后续 compile / preview / freeze 使用新路径和新 G1。
4. 新请求、简报、计划、候选和预览写入 `revisions/rN/`。旧路径与旧回执保持有效；当前版本由状态事务确定，不通过覆盖工作文件切换。
5. 受累计修订预算约束；同一暂存修订中断恢复不重复计费，冲突提案拒绝。旧 G2 不批准新预览。
6. 冻结后不在原运行上修改设计。新建运行并重新形成候选、G2、锁和交付依据，不能用 retry 当设计修订。

CLI 只有一个入口，公共参数以 `--help` 为准：

```text
carto generate-map <intake|brief|compile|preview|revision-brief|revise|freeze|render|check|review|deliver|status|retry|receipts|delivery-status>
```

## 5. 布局、渲染和交付边界

- A4 横版 300 dpi、PDF+PNG；网格 1×1 / 1×2 / 2×2，独立或共享图例。任意自由布局、自动删类/缩字或偷偷改色不开放。
- 共享图例须有一致的完整表达、度量和比例，不能把不同密度区间当成同一图例。各图范围可不同，但必须匹配请求。
- 模板创建/发布仍需独立 T1/TP；结构合法不等于场景准入，终端命令许可不等于业务审批。
- 回执的 subject_id 必须匹配独立审批人 approver_subject_id，不能等于操作者。G1/G2 回执保存内容寻址快照，锁引用真实文件，不依赖用户原始回执文件持续存在。
- G1/G2/G3 核验身份、tenant、scope、environment、动作、对象摘要及时效；运行内 nonce 精确绑定审批事务。相同事务可恢复，换对象/运行/回执拒绝。
- 外部路径经 PathGuard。密钥、原始业务行、敏感位置不能进入普通日志、模板或交付包。
- 最终包仅包含 `map.pdf`、`map.png`、`README.md`、`delivery-manifest.yaml`、`checksums.sha256`；内部审查记录由清单的精确引用绑定。
- 隔离 staging、校验、同文件系统原子提交、不可变回执；冲突目的地和同幂等键换对象拒绝。提交结果未知先查询 delivery-status。
- 不开放生产任务、在线底图/路线、真实 CRS 转换、海报/调研业务、任意字段表达式或外部发布。

运行时只读取 Skill 协议、策略、索引及项目产物，不读取 doc 或测试代码。
