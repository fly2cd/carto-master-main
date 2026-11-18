# AGENTS.md

本文件是 Carto Master 仓库的通用智能体入口。

## 执行入口

- 地图能力的唯一实现根目录是 `skills/carto-agent/`。
- 修改地图工作流、Schema、策略、脚本或测试前，必须先阅读 `skills/carto-agent/SKILL.md`。
- 历史占位目录 `skills/carto-master/` 已于 2026-11-16 移除；不得重新创建该目录或在仓库其他位置建立并行地图实现。
- 架构和 TRD 位于 `doc/`，运行时不得把这些设计文档当作机器协议读取。
- **设计原则**：[`doc/design-principles.md`](doc/design-principles.md) 定义了 LLM 设计自由与程序形式验证的四层决策边界（创意设计层 / 形式验证层 / 机械推导层 / 灰色地带）；所有新增或修改的制图能力实现必须符合该原则中声明的职责归属。

## IDE 宿主入口（Codex / Claude Code）

- 在仓库根目录打开 VS Code；两种宿主共用本文件和 `skills/carto-agent/SKILL.md`，Claude 的入口由根目录 `CLAUDE.md` 引用本文件。
- 执行制图任务前，读取 Skill 的“IDE 宿主最小接入”及 `workflows/routing.md`，再读取所选工作流；使用宿主的终端工具调用唯一 CLI，不新建宿主专用地图实现。
- 首次执行先确认真实 Python 3.11+ 解释器，再运行 `python skills/carto-agent/scripts/carto.py --help` 和 `python skills/carto-agent/scripts/carto.py schema check`。这里的 `python` 必须替换为确认可用的解释器；不得猜测本机绝对路径或默认使用 WindowsApps 占位符。
- VS Code Tasks 使用 Python 扩展选定的解释器；Agent 的终端不保证继承该选择，须单独确认。不自动安装依赖、扩展或注册全局 Skill。
- 不因用户只说“运行项目”就自动选择场景、调用宿主 bootstrap 或自动签发审批。IDE 命令执行许可不等于 T1 / TP / G1 / G2 / G3；不得改能力策略或伪造回执来继续。
- 本次入口是“读取仓库指令 + 执行 CLI”，不保证技能选择器或 `/carto-agent` 命令可见；`environment probe-host` 当前只检查 Hermes，不用于证明 Codex / Claude 的会话能力。

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
- 本仓库与 PPT 体系（外部仓库的 `skills/ppt-master/`）相互独立；不引用其文件路径、不为旧命名或旧锁格式新增并行兼容实现。

## 策略治理与场景登记

- `policies/*.yaml` 的语义字段经摘要绑定进入冻结意图/锁/回执（`scenario-capabilities` 的 profile 语义、`intent-profiles` 全文目录摘要）。修改任一语义字段会使全部既有冻结执行漂移，必须由唯一策略 steward（见 `.github/CODEOWNERS`）评审；`notice`/`licenses` 等披露字段不计入 digest。
- 代码与 Schema 重构不得改变策略语义字段；请求/提案等协议文档必须保持形状不变以维持产物摘要稳定。代码指纹随被改源文件变化，旧内部快照按现行 doctrine 重新准备/编译，不自动迁移。
- 登记新场景 = 场景包（`scenarios/<name>/`）+ 代码白名单一行 + 策略 profile + 严格 Schema + 合法/非法样例与自动测试；除此之外不得修改内核文件。内核不得 import 具体场景模块或直读场景请求体词汇，由 `tests/test_scenario_boundary.py` 棘轮强制。
- 新增 intent profile 会改变整目录摘要，既有冻结运行须先完成或按现行 doctrine 重新冻结，不自动迁移。这是目录绑定设计的固有治理成本。
- 边界守护测试（`test_layer_ports`/`test_encapsulation`/`test_digest_coverage`/`test_scenario_boundary`）只紧不松；修复一处违规必须同步删除其允许清单条目。
