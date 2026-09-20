# 顶层路由

| 路由 | 请求目标 | 当前状态 |
|---|---|---|
| `create-template` | 创建可复用地图模板包 | U-P2.4 已开放 MapScenario 的 `analyze → brief → author → validate → publish` 闭环 |
| `generate-map` | 从业务意图和数据生成地图成果 | U-P2.5/U-P2.6 已开放合成洪涝数据的 `intake → brief → compile → preview → freeze` 闭环 |
| `edit-native-map` | 保留原生 GIS 工程并编辑 | 未开放，返回 `CAPABILITY_NOT_AVAILABLE` |
| `curate-catalog` | 治理符号、标准和目录 | 未开放，返回 `CAPABILITY_NOT_AVAILABLE` |

路由不得互相降级。创建模板审批不等于地图生成审批；两条已开放路由只共享 Schema、安全组件和受信资源目录；`generate-map` 不包含 G3 或正式交付。


## U-P2.7 operational closure

Both open routes use an independent run directory and state history. A complete mutating step holds a run-wide single-writer lock. State updates use monotonically increasing revisions, immutable receipts, and a recoverable transition journal. `status`, `retry`, and `receipts` are exposed only through the existing `carto` CLI. Template T1/TP approvals and map G1/G2 approvals remain action-, object-, scope-, identity-, environment-, expiry-, and nonce-bound and cannot be reused across routes. T1 and G1 recover only from claims-validated workflow-local intent plus exact deterministic artifacts; TP recovers only from its immutable publication transaction and retained approval; G2 recovers only from an exact immutable `MapSpecLock`. These recovery paths verify an already-consumed nonce and never turn nonce replay into a normal retry mechanism.
