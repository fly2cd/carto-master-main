---
name: carto-agent
description: 地图制图智能体的创建模板与生成地图工作流入口。
version: 0.1.0
---

# Carto Agent Skill

本目录是地图制图智能体的唯一运行实现。当前已落地 U-P0 安全底座、U-P1 内核协议骨架，以及 U-P2.0～U-P2.7 的 MapScenario 创建发布、地图候选预览冻结与集成恢复闭环；后续阶段不得在仓库其他位置建立并行实现。

## 必读顺序

1. 阅读本文件。
2. 阅读 `workflows/routing.md`，选择且只选择一个顶层路由。
3. 读取所选路由拥有的工作流文件；尚未实现的路由必须返回明确的能力未开放错误。
4. 机器执行只读取 `schemas/`、`policies/`、注册表和项目产物，不读取 `doc/` 设计稿作为运行协议。

## 当前阶段边界

- 已实现：Schema 注册与结构校验、安全底座、五模块骨架、状态与回执、意图解析、类型化智能体提交、审批协调、固定数据准备、ToolGateway、MCP 授权边界、知识服务、编译器与校验器骨架，首个洪涝 MapScenario 的 `analyze → brief → author → validate → publish` 闭环，确定性 MapLibre Web + SVG overlay 的 SVG、PNG、PDF 渲染，以及 `intake → brief → compile → preview → freeze` 的合成数据地图候选与实例冻结闭环。
- 模板发布边界：发布前必须重新验证模板包、依赖锁、合成 Fixture、检查器集合、RenderReceipt、预览成果和渲染环境绑定；发布需要 TP 审批，并写入不可变模板仓库和权威索引。
- 地图生成边界：只接受已发布的精确 MapScenario 版本和合成 GeoJSON；G1 后生成 PreparedDataBundle、MapPlan、ResolvedMap 与 RenderScene，真实浏览器预览通过后由精确 G2 创建不可变 MapSpecLock。
- U-P2.7 集成收口已实现：两条工作流均具备运行级单写锁、revision/CAS、可恢复状态转换日志、不可变回执查询、受限重试和恢复状态报告；T1、TP、G1、G2 的审批消费中断仅可凭严格匹配的不可变恢复证据续跑，普通 nonce 重放仍被拒绝。
- Not implemented: real CRS transformation, G3, formal delivery transactions, production-data mapping, or business creation routes for `map-brand`, `map-style`, and `map-layout`.
- CLI 入口：`python skills/carto-agent/scripts/carto.py --help`。
- 测试入口：`python -m unittest discover -s skills/carto-agent/scripts/tests -v`。

## 固定术语

- `map-brand`：地图身份模板。
- `map-style`：制图表达规范。
- `map-layout`：地图版式模板。
- `map-scenario`：制图场景方案。
- 规则语义：`hard_rule`、`forbidden`、`mandatory`、`binding`、`default`、`reference`。
- 结果严重度：`blocker`、`error`、`warning`、`info`。
