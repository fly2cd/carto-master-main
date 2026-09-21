---
name: carto-agent
description: 地图制图智能体的创建模板与生成地图工作流入口。
version: 0.3.3
---

# Carto Agent Skill

本目录是地图制图智能体的唯一运行实现。当前已落地 U-P0 安全底座、U-P1 内核协议骨架、U-P2.0～U-P2.7 的 MapScenario 创建发布与地图候选冻结闭环，以及 U-P3.1～U-P3.3 的锁驱动正式渲染、成品检查、精确 G3 和原子本地交付；不得在仓库其他位置建立并行实现。

## 必读顺序

1. 阅读本文件。
2. 阅读 `workflows/routing.md`，选择且只选择一个顶层路由。
3. 读取所选路由拥有的工作流文件；尚未实现的路由必须返回明确的能力未开放错误。
4. 机器执行只读取 `schemas/`、`policies/`、注册表和项目产物，不读取 `doc/` 设计稿或 `scripts/tests/` 作为运行协议。`scripts/tests/` 仅供开发与验收阶段使用，正式发布阶段不依赖。

## 当前阶段边界

- 已实现：Schema 注册与结构校验、安全底座、五模块骨架、状态与回执、审批协调、固定数据准备、ToolGateway、MCP 授权边界、知识服务和编译/校验骨架；首个洪涝 MapScenario 的 `analyze → brief → author → validate → publish`，以及 `intake → brief → compile → preview → freeze → render → check → deliver` 的合成数据工程演示闭环。
- 模板发布边界：发布前重新验证模板包、依赖锁、合成 Fixture、检查器集合、RenderReceipt、预览成果和环境绑定；发布需要精确 TP，并写入不可变模板仓库和权威索引。
- 内置模板示例：`templates/map-scenario/urban-flood-risk/1.0.0/` 提供由当前作者实现确定性生成的 `draft` 合成示例包，仅用于开发、测试和文档说明；它不是权威发布仓库，不参与运行时模板发现，使用前仍必须经过正式 `validate → TP → publish`。
- 地图生成边界：只接受已发布的 `urban-flood-risk/1.0.0` 和合成 GeoJSON；G1 后创建类型化候选，真实浏览器预览通过后由精确 G2 创建不可变 MapSpecLock；`render` 只消费锁及摘要绑定输入；`check` 生成 Final ValidationReport 和不可变 DeliveryManifest；`deliver` 只接受精确 G3，并以 staging、完整校验、同文件系统原子目录提交和不可变 DeliveryReceipt 完成交付。
- 状态与恢复：两条工作流均具备运行级单写锁、revision/CAS、状态转换日志、不可变步骤回执、受限重试和恢复查询。T1、TP、G1、G2、G3 的消费中断只能凭严格匹配的 workflow-local intent 或不可变事务证据恢复，普通 nonce 重放仍被拒绝。
- U-P3.1：`freeze` 后进入 `pending / render`；正式 PDF/PNG 写入不可覆盖 attempt 目录，固定携带“合成数据演示，非真实风险研判”。
- U-P3.2：`check` 对 PDF/PNG、A3 横向、144 DPI、字体、版式、图例/无数据语义、声明链、锁/attempt/回执/环境绑定、敏感内容和 renderer warning 执行确定性检查；通过后进入 `waiting_approval / deliver`。
- U-P3.3：`deliver` 重新验证 Manifest、Final ValidationReport、锁、成功 attempt 和成果摘要，验证并消费精确 G3；项目内 DeliveryRepository 按幂等键记录事务，以隔离 staging 构建白名单交付包，原子提交最终目录，写不可变 DeliveryReceipt，并进入 `succeeded / deliver`。`delivery-status` 可按幂等键查询提交结果。
- 交付包只含 `map.pdf`、`map.png`、`README.md`、`delivery-manifest.yaml`、`checksums.sha256`；不包含原始数据、内部锁、审批密钥、RenderReceipt 或内部 ValidationReport。
- 当前能力仅为本地允许根内的“合成数据工程演示闭环”，不声明生产制图、三场景业务覆盖、共享服务、外部发布或公网发布能力。
- 尚未实现：真实 CRS 转换、生产数据制图，以及 `map-brand`、`map-style`、`map-layout` 的业务创建路由。
- CLI 入口：`python skills/carto-agent/scripts/carto.py --help`。
- 测试入口（仅开发与验收阶段，非运行协议）：`python -m unittest discover -s skills/carto-agent/scripts/tests -v`。

## 固定术语

- `map-brand`：地图身份模板。
- `map-style`：制图表达规范。
- `map-layout`：地图版式模板。
- `map-scenario`：制图场景方案。
- 规则语义：`hard_rule`、`forbidden`、`mandatory`、`binding`、`default`、`reference`。
- 结果严重度：`blocker`、`error`、`warning`、`info`。
