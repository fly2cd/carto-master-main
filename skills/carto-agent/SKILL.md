---
name: carto-agent
description: 地图制图智能体的创建模板与生成地图工作流入口。
version: 0.1.0
---

# Carto Agent Skill

本目录是地图制图智能体的唯一运行实现。当前已落地 U-P0 安全底座和 U-P1 内核协议骨架；后续阶段不得在仓库其他位置建立并行实现。

## 必读顺序

1. 阅读本文件。
2. 阅读 `workflows/routing.md`，选择且只选择一个顶层路由。
3. 读取所选路由拥有的工作流文件；尚未实现的路由必须返回明确的能力未开放错误。
4. 机器执行只读取 `schemas/`、`policies/`、注册表和项目产物，不读取 `doc/` 设计稿作为运行协议。

## 当前阶段边界

- 已实现：Schema 注册与结构校验、安全底座、五模块骨架、状态与回执、意图解析、类型化智能体提交、审批协调、固定数据准备、ToolGateway、MCP 授权边界、知识服务、编译器与校验器骨架。
- 暂缓实现：生产级 QGIS/API/MCP 适配器，以及真实 CRS 转换、A3 PDF/PNG 和中文字体渲染冒烟；当前只提供结构化环境探测骨架。
- 尚未实现：U-P2 模板创建与地图生成业务闭环、候选渲染、实例冻结和发布事务。
- CLI 入口：`python skills/carto-agent/scripts/carto.py --help`。
- 测试入口：`python -m unittest discover -s skills/carto-agent/scripts/tests -v`。

## 固定术语

- `map-brand`：地图身份模板。
- `map-style`：制图表达规范。
- `map-layout`：地图版式模板。
- `map-scenario`：制图场景方案。
- 规则语义：`hard_rule`、`forbidden`、`mandatory`、`binding`、`default`、`reference`。
- 结果严重度：`blocker`、`error`、`warning`、`info`。
