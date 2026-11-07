# 2026-11-05 栅格开发验收脚本及 Claude Code 接力记录

## 用户目标与边界

用户要求生成测试脚本，在 VS Code Claude Code 插件中测试并逐步记录。
当前会话可控应用/浏览器及 MCP 资源均为空，不能直接操作插件；命令别名 `code`
实际指向 Qoder。因此本批完成脚本与当前终端验证，**插件内执行仍未完成**。
不把终端结果、宿主自报标签或 IDE 集成单测冒充真实插件会话证据。

## 新增文件

- `skills/carto-agent/scripts/tests/manual/real_raster_acceptance.py`
- `skills/carto-agent/scripts/tests/manual/__init__.py`
- `skills/carto-agent/scripts/tests/manual/README.md`
- `skills/carto-agent/scripts/tests/test_real_raster_acceptance.py`

均为开发测试代码/文档；没有新增运行时 CLI、业务场景、模板或审批旁路。
没有修改原有业务实现、能力策略、源 TIFF/CSV 或 IDE 配置。

## 能力

- 真实文件只读 PathGuard/大小/SHA256/TIFF 文件头预检；不解释像元、CRS 或 CSV 行。
- 真实 Python、唯一 CLI 与完整 Schema 集合自检。
- 依赖导入探测和业务能力策略快照，不安装依赖或修改策略。
- 通过独立子进程运行现有 raster/all 合成回归，逐用例记录状态与耗时。
- JSON/Markdown 分步报告；每次唯一目录，不覆盖历史；原始 stderr/traceback 不入普通日志。
- 输入与策略前后摘要一致性复核；超时不自动重试；跳过不计入通过。
- 明确区分所选阶段、真实地图和插件会话状态；真实准备/正式交付未满足条件时保持未执行。

## 本次实测

- 实际 Python：3.12.14；CLI 帮助退出 0；64 个 Schema 通过。
- 脚本正反例：20/20 通过，覆盖路径越界、输出目录、错误退出、摘要变更、超时、跳过及宿主不冒认。
- 完整回归：**303 个，300 通过、0 失败、3 跳过**；3 个跳过为本机符号链接创建权限限制。
- 回归耗时约 205 秒；unittest 子进程退出 0，验收脚本保守返回 3（存在跳过，覆盖不完整）。
- 真实输入预检通过；TIFF/CSV/能力策略前后摘要一致。
- 真实 MCP 准备、真实用户地图生成/G2/G3 交付、Claude Code 插件端到端测试均未执行。
- 既有栅格正式链路测试覆盖的是合成候选之后的路径，不补足真实业务组件/模板准入。

本机配置、逐步结果和回归分组见 gitignore 范围内的
`projects/landcover-acceptance/session-notes.md`。
每次机器可读记录在同项目 `.carto/acceptance-tests/<run>/`。
插件交接提示词见新增 manual/README.md；由用户在实际插件会话接力执行。
