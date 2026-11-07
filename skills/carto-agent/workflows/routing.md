# 顶层路由

| 路由 | 请求目标 | 当前状态 |
|---|---|---|
| `create-template` | 创建可复用地图模板包 | 保留 `analyze → brief → author → validate → publish` 编排；仅准入已注册的 `general_thematic_mapping` 场景（`general-thematic-map` 模板），其样张渲染分支未注册前 `validate` 失败关闭、不得发布；其余默认拒绝 |
| `generate-map` | 从业务意图和数据生成地图成果 | 保留 `intake → brief → compile → preview → freeze → render → check → deliver` 编排及状态查询；仅准入已注册的 `general_thematic_mapping` 场景（用户提供已分类栅格 → A4 横版 PDF+PNG），其余默认拒绝 |
| `edit-native-map` | 保留原生 GIS 工程并编辑 | 未开放，返回 `CAPABILITY_NOT_AVAILABLE` |
| `curate-catalog` | 治理符号、标准和目录 | 未开放，返回 `CAPABILITY_NOT_AVAILABLE` |

路由不得互相降级。创建模板审批不等于地图生成审批；两条已实现编排的路由只共享 Schema、安全组件和受信资源目录。模板 T1/TP 与地图 G1/G2/G3 均按动作、对象、摘要、身份、tenant、scope、environment、时效和 nonce 独立绑定，不能跨 gate、跨对象或跨运行复用。

## 运行闭环

两条工作流使用独立 run 目录和状态历史。可变步骤持有运行级单写锁；状态更新使用单调 revision、不可变步骤回执和可恢复 transition journal。`status`、`retry`、`receipts` 和 `delivery-status` 只通过现有 `carto` CLI 暴露。

`generate-map` 的正式渲染只消费不可变 MapSpecLock；最终检查冻结不可变 DeliveryManifest；G3 精确批准该 Manifest；交付在项目内 journal 中记录 DeliveryTransaction，先写同级隔离 staging，完整校验后以原子目录替换提交，最后写不可变 DeliveryReceipt。消费 G3 后的恢复必须持有完全匹配的 workflow-local intent；交付恢复必须重新验证最终包和事务绑定。

## 能力声明

当前执行能力策略（`policies/scenario-capabilities.yaml` v1.3.0）和代码实现白名单只注册 `general-thematic-mapping`（`general_thematic_mapping` / 实现 `general-thematic-raster` / 模板 `map-scenario/general-thematic-map@1.0.0`）；输入结构有效且意图就绪后，其余未注册能力返回 `CAPABILITY_NOT_AVAILABLE`，不选择默认场景。生成入口先验证并解析实际用户意图，缺项、歧义或不支持的意图先返回对应错误。`intent resolve` 只识别业务场景、主题与任务，不授权执行；其目录条目不代表业务场景已开放。输入边界见 `intent-contract.md`。通用编排存在不等于场景已启用。它不代表地图工作流内的真实 CRS 转换、生产数据处理、三场景业务验收、共享服务或公网发布能力。`formal_capability_boundary.production_tasks` 保持为空。

## 宿主辅助检查

检查 Hermes 接入和工具可用性时，先阅读 `host-preflight.md`，使用 `carto environment probe-host`。这不是新的地图业务路由；检查结果不修改现有能力策略、工具授权或审批状态。本机工具进程读取通过，也不能替代实际会话和 GIS 能力验证。


## 基础 GIS 数据辅助入口

`data inspect-raster` 通过显式配置的独立 MCP 服务读取分类 TIFF 元数据和精确类别统计，使用前阅读 `geospatial-data.md`。这不是第五条业务路由，也不代表 `generate-map` 已支持栅格。重投影仅有适配器能力，只读 CLI 拒绝变换；不能用单个工具结果替代场景、审批或地图成果证据。

分类准备辅助入口 `data analyze-classification` / `data clarify-classification` 见 `raster-classification.md`。它们只冻结数据与显示合同，不开放业务场景、地图导出或审批旁路。

内部整页 `RasterPageRenderer` 的 PDF/PNG/SVG 与字体/布局验收见同一 `raster-classification.md`；其页面报告不是正式渲染回执。第三批 C 的 `RasterFormalRenderer` 已将该内部组件接入现有预览、G2、锁驱动渲染、终检和 G3 交付链，但不新增路由、业务场景或审批旁路；仍须由独立准入的业务组件和模板使用。
