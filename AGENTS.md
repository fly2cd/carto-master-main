# AGENTS.md

本文件是 Carto Master 仓库的通用智能体入口。

## 执行入口

- 地图能力的唯一实现根目录是 `skills/carto-agent/`。
- 修改地图工作流、Schema、策略、脚本或测试前，必须先阅读 `skills/carto-agent/SKILL.md`。
- `skills/carto-master/` 是空的历史占位目录，不是运行入口，不得在其中新增实现。
- 架构和 TRD 位于 `doc/`，运行时不得把这些设计文档当作机器协议读取。

## 代码与测试位置

- Python 运行代码：`skills/carto-agent/scripts/carto_core/`。
- 单一 CLI：`skills/carto-agent/scripts/carto.py`，安装后命令名为 `carto`。
- JSON Schema：`skills/carto-agent/schemas/`。
- 版本化策略：`skills/carto-agent/policies/`。
- 测试与 Fixture：`skills/carto-agent/scripts/tests/`。
- 不在仓库根目录创建第二套 `src/`、`schemas/` 或 `tests/`。

## 工程约束

- 使用 Python 3.11 及以上版本，依赖由根目录 `pyproject.toml` 和 Skill 内 `requirements.txt` 共同声明。
- Schema 使用 JSON Schema Draft 2020-12；业务实例可以是 JSON 或安全解析的 YAML。
- 所有外部路径先经过允许根校验；所有审批先验证身份、动作、对象摘要、作用域、时效和防重放标识。
- 不得把密钥、完整行程、应急敏感坐标或业务数据行写入普通日志、Fixture 或模板包。
- 新增协议必须同时提供合法样例、非法样例和自动测试；未知字段默认拒绝。
- 不修改 `skills/ppt-master/`，不为旧命名或旧锁格式新增并行兼容实现。
