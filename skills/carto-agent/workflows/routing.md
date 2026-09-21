# 顶层路由

| 路由 | 请求目标 | 当前状态 |
|---|---|---|
| `create-template` | 创建可复用地图模板包 | U-P2.4 已开放 MapScenario 的 `analyze → brief → author → validate → publish` 闭环 |
| `generate-map` | 从业务意图和数据生成地图成果 | U-P3.3 已开放合成洪涝数据的 `intake → brief → compile → preview → freeze → render → check → G3 → deliver` 本地工程演示闭环，并支持 `delivery-status` 查询 |
| `edit-native-map` | 保留原生 GIS 工程并编辑 | 未开放，返回 `CAPABILITY_NOT_AVAILABLE` |
| `curate-catalog` | 治理符号、标准和目录 | 未开放，返回 `CAPABILITY_NOT_AVAILABLE` |

路由不得互相降级。创建模板审批不等于地图生成审批；两条已开放路由只共享 Schema、安全组件和受信资源目录。模板 T1/TP 与地图 G1/G2/G3 均按动作、对象、摘要、身份、tenant、scope、environment、时效和 nonce 独立绑定，不能跨 gate、跨对象或跨运行复用。

## 运行闭环

两条开放路由使用独立 run 目录和状态历史。可变步骤持有运行级单写锁；状态更新使用单调 revision、不可变步骤回执和可恢复 transition journal。`status`、`retry`、`receipts` 和 `delivery-status` 只通过现有 `carto` CLI 暴露。

`generate-map` 的正式渲染只消费不可变 MapSpecLock；最终检查冻结不可变 DeliveryManifest；G3 精确批准该 Manifest；交付在项目内 journal 中记录 DeliveryTransaction，先写同级隔离 staging，完整校验后以原子目录替换提交，最后写不可变 DeliveryReceipt。消费 G3 后的恢复必须持有完全匹配的 workflow-local intent；交付恢复必须重新验证最终包和事务绑定。

## 能力声明

当前开放能力仅为本地允许根内的合成数据工程演示闭环。它不代表真实 CRS 转换、生产数据处理、三场景业务验收、共享服务、外部连接器或公网发布能力。`formal_capability_boundary.production_tasks` 保持为空。
