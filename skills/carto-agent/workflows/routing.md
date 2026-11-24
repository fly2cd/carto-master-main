# 顶层路由

| 路由 | 请求目标 | 当前状态 |
|---|---|---|
| `create-template` | 创建可复用地图模板包 | 保留 `analyze → brief → author → validate → publish` 编排；仅准入已注册的 `general_thematic_mapping` 场景（`general-thematic-map` 模板）。静态检查通过后 `validate` 在受信验证上下文内渲染合成样张并冻结场景/回执/预览证据，`publish` 重新核验冻结证据并消费精确 TP；缺少栅格渲染依赖、可嵌入字体或投影展示 CRS 时失败关闭；其余默认拒绝 |
| `generate-map` | 从业务意图和数据生成地图成果 | 保留 `intake → brief → compile → preview → freeze → render → check → review → deliver` 编排及状态查询；仅准入已注册的 `general_thematic_mapping` 场景（已分类栅格或受限点/面矢量，显式 design → 单图/1×2/2×2 → A4 横版 PDF+PNG；非生产准入），其余默认拒绝 |
| `edit-native-map` | 保留原生 GIS 工程并编辑 | 未开放，返回 `CAPABILITY_NOT_AVAILABLE` |
| `curate-catalog` | 治理符号、标准和目录 | 未开放，返回 `CAPABILITY_NOT_AVAILABLE` |

路由不得互相降级。创建模板审批不等于地图生成审批；两条已实现编排的路由只共享 Schema、安全组件和受信资源目录。模板 TP 与地图 G1/G2/G3 均按动作、对象、摘要、身份、tenant、scope、environment、时效和 nonce 独立绑定，不能跨 gate、跨对象或跨运行复用。

## 运行闭环

两条工作流使用独立 run 目录和状态历史。可变步骤持有运行级单写锁；状态更新使用单调 revision、不可变步骤回执和可恢复 transition journal。`status`、`retry`、`receipts` 和 `delivery-status` 只通过现有 `carto` CLI 暴露。

`generate-map` 的正式渲染只消费不可变 MapSpecLock；最终检查通过后由成品 review 形成审查记录，冻结包含 review_ref 的不可变 DeliveryManifest；G3 精确批准该 Manifest；交付在项目内 journal 中记录 DeliveryTransaction，先写同级隔离 staging，完整校验后以原子目录替换提交，最后写不可变 DeliveryReceipt。消费 G3 后的恢复必须持有完全匹配的 workflow-local intent；交付恢复必须重新验证最终包和事务绑定。

## 能力声明

当前策略为 `scenario-capabilities.yaml` v1.7.0；`general_thematic_mapping` / `general-thematic` 只登记**一个**能力档案 `general-thematic-mapping@5.0.0`，栅格与矢量是它的 `geometry_variants` 数据适配变体，业务语义、意图约束、输出与版式上限只声明一遍。几何由请求与变体元数据显式声明，不按模板版本推断；撤销某几何即删除对应变体。矢量包括一对一 CSV 属性连接、类别、等距/手工分级设色、面积比例符号。`production_enabled: false`，`formal_capability_boundary.production_tasks` 仍为空。

意图缺项/歧义先返回澄清错误，未注册场景失败关闭。`intent resolve` 不授权执行。模板复用优先；项目设计、自动模板检索、海报、调研、OCR、真实 CRS 转换和外部发布不能由已存在的通用接口推定开放。详见 `generate-map.md`。

## 宿主辅助检查

检查 Hermes 接入和工具可用性时，先阅读 `host-preflight.md`，使用 `carto environment probe-host`。这不是新的地图业务路由；检查结果不修改现有能力策略、工具授权或审批状态。本机工具进程读取通过，也不能替代实际会话和 GIS 能力验证。


## 基础 GIS 数据辅助入口

`data inspect-raster` 通过显式配置的独立 MCP 服务读取分类 TIFF 元数据和精确类别统计，使用前阅读 `geospatial-data.md`。这不是第五条业务路由；工具可读栅格不等于任意场景可生成地图，general 的受限组合须走正式工作流。重投影仅有适配器能力，只读 CLI 拒绝变换；不能用单个工具结果替代场景、审批或地图成果证据。

类别码栅格 + CSV 的准备辅助入口 `data analyze-classification` / `data clarify-classification` 见 [分类栅格准备与澄清](raster-classification.md)，仅在任务需要该能力时读取。就绪报告只冻结数据与显示合同，不开放业务场景、地图导出或审批旁路；continuous 请求不套用这条 CSV 澄清流程。

准备就绪后的预览、G2 冻结、正式渲染、终检、成品 review 和 G3 交付统一见 [generate-map](generate-map.md)。内部页面报告不是正式渲染回执；宿主只调用已准入工作流，不将内部渲染组件作为独立导出入口。
