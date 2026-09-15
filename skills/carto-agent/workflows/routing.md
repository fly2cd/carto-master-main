# 顶层路由

| 路由 | 请求目标 | 当前状态 |
|---|---|---|
| `create-template` | 创建可复用地图模板包 | 协议底座已实现，业务流程待 U-P1/U-P2 |
| `generate-map` | 从业务意图和数据生成地图成果 | 协议底座已实现，业务流程待 U-P1/U-P2 |
| `edit-native-map` | 保留原生 GIS 工程并编辑 | 未开放，返回 `CAPABILITY_NOT_AVAILABLE` |
| `curate-catalog` | 治理符号、标准和目录 | 未开放，返回 `CAPABILITY_NOT_AVAILABLE` |

路由不得互相降级。创建模板审批不等于地图生成审批；两条已详设路由只共享 Schema、安全组件和受信资源目录。
