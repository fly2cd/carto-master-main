# VS Code + Codex / Claude Code：最小接入

日期：2026-10-30。本文的 IDE 指 **Visual Studio Code**，不是 Visual Studio。

## 1. 这次接入了什么

```text
VS Code 中的 Codex / Claude Code
  → AGENTS.md（Claude 沿用 CLAUDE.md 中的 @AGENTS.md）
  → skills/carto-agent/SKILL.md → routing → 对应工作流
  → 宿主终端调用 skills/carto-agent/scripts/carto.py
  → 原有 Schema / 策略 / 路径校验 / 审批 / 回执
```

这是**仓库指令入口 + 本地 CLI 调用**，不是另外搭建一个宿主服务。地图实现、协议和测试仍只有 `skills/carto-agent/` 一套。无需先装载 Hermes，也不调用模型 API，不添加密钥或自动审批配置。

- `.vscode/tasks.json`：五个显式运行的任务，使用 VS Code Python 扩展所选解释器。
- `.vscode/extensions.json`：Python、Codex、Claude Code 的推荐项；推荐不等于安装，也不要求同时安装两个 Agent。
- `AGENTS.md` / `SKILL.md`：共同调用规则，包含解释器确认、CLI 自检、能力与审批边界。
- `CLAUDE.md`：保留已有 `@AGENTS.md` 引用，不复制项目规则。
- `.gitignore`：仅开放两个共享 IDE 配置；个人 `settings.json`、`launch.json` 等仍忽略。

本轮**没有**创建 `.agents/skills`、`.claude/skills` 或全局技能副本。因此不保证原生技能选择器中出现 `carto-agent`，也不保证 `$carto-agent` / `/carto-agent` 可用。直接使用下面的自然语言提示即可；需要原生发现时可另行做受控链接与真实会话验收，不另写地图实现。

## 2. 首次使用

1. 用 VS Code 的 **Open Folder** 打开仓库根目录，不要只打开一个 Markdown 文件或 `skills/carto-agent/` 子目录。
2. 在扩展面板查看工作区推荐，安装 **Python（`ms-python.python`）**；Codex（`openai.chatgpt`）或 Claude Code（`anthropic.claude-code`）按需任选，并自行完成其登录/授权。
3. 执行命令面板 **Python: Select Interpreter**，选择真实的 **Python 3.11+**。仓库不提交你机器的解释器路径；Windows 上不要选 Microsoft Store 的 `WindowsApps` 占位符。
4. 确认**该解释器**装有根目录 `pyproject.toml` 声明的依赖。缺依赖时，先决定使用已有环境或自行创建的虚拟环境，再显式执行安装；任务不会自动安装。不要把虚拟环境或密钥提交到 Git。
5. 运行 **Terminal → Run Task → `Carto: CLI help`**，再运行 **`Carto: Check schemas`**。查看实际终端输出和退出码。
6. 新建所选 Agent 的会话，使用第 4 节提示检查其实际读取和执行情况。宿主的工作区信任、命令权限继续由你确认，不启用绕过审批模式。

例如在 Windows PowerShell 中，在仓库根目录把路径替换为你选定的解释器：

```powershell
$Python = 'C:\path\to\python.exe'  # 占位符，必须替换；不要求此固定位置
& $Python --version
& $Python -c "import sys; print(sys.executable)"
# 仅当你同意在这个环境中安装依赖时执行：
& $Python -m pip install -e .
& $Python skills/carto-agent/scripts/carto.py --help
& $Python skills/carto-agent/scripts/carto.py schema check
```

任务以 `process` 启动所选解释器，脚本路径作为独立参数传入，避免将含空格的工作区路径拼成 Shell 命令。工作目录固定为 `${workspaceFolder}`，`PYTHONUTF8=1` 保持中文输出一致；没有机器专属路径、`runOn: folderOpen`、API Key 或业务审批环境配置。

> **Agent 终端与 VS Code Tasks 不是同一个解释器选择机制。** Tasks 通过 `${command:python.interpreterPath}` 获取选择；Agent 发起的终端命令仍需核对 `sys.executable`。必要时把刚确认的路径告诉 Agent，不能仅因任务成功就认定其终端环境也可用。

## 3. 可用任务与通过标准

| VS Code 任务 | 实际执行 | 如何判断 |
|---|---|---|
| `Carto: CLI help` | `carto.py --help` | 返回当前 CLI 帮助、退出码 0 |
| `Carto: Check schemas` | `carto.py schema check` | 退出码 0，JSON `ok: true`，`checked` 与 `schemas` 一致；不把数量写死 |
| `Carto: Probe renderer` | `carto.py environment probe-renderer` | 显式启动本机工具/字体与无头浏览器探测；还需看 `environment.status` 和能力项 |
| `Carto: Test IDE integration` | 仅发现并运行 `test_ide_integration.py` | 配置契约及真实 CLI 正常 / 非法参数用例通过 |
| `Carto: Run tests` | 运行现有测试目录全部 `unittest` | 检查结果与 skip 原因；部分测试会启动无头浏览器、创建临时产物 |

`probe-renderer` 的退出码 0 表示“成功生成报告”，**不等于**渲染可用；若 `environment.status` 是 `unavailable`，要报告缺项而不是继续出图或自动安装 GIS 工具。

本轮没有“一键生成地图 / 一键交付”任务。项目路径、请求、允许根、可信审批与当前场景能力仍必须按真实任务准备，不能把它们写死在共享配置中。测试中自建的模拟数据和审批只用于回归，不是用户项目的执行授权。

## 4. 在 Codex / Claude 中直接输入

先做不接触业务数据的最小自检：

```text
请按当前仓库的 AGENTS.md，读取 skills/carto-agent/SKILL.md。
这次只做 IDE 最小自检，不生成地图，不自动选择场景或运行 Hermes bootstrap。
请先确认当前工作目录和真实 Python 3.11+ 解释器，执行：
  skills/carto-agent/scripts/carto.py --help
  skills/carto-agent/scripts/carto.py schema check
请列出读取的入口文件、使用的解释器、两条命令的退出码和结果摘要。
若缺依赖或权限，先告诉我，不自动安装，不读取凭据文件或输出完整环境变量。
```

后续真正执行任务时，可以给出明确路径和目标：

```text
请按 carto-agent 处理我指定的请求文件，先检查当前能力是否支持。
请求、项目目录和允许根以我本次明确给出的路径为准；缺项先问我。
读取 routing 和对应工作流，用现有 carto.py 逐步执行。
不要自动替换成其他任务，不自动签发审批；到审批门禁时停下并说明需要的精确回执。
```

第二段是交互模板，不是可以不填参数就直接运行的 Shell 命令。已有明确输入后，Agent 再用相应子命令 `--help` 核对参数，不从测试代码复制业务输入。

## 5. 故障与边界

- **找不到任务**：确认打开仓库根目录、工作区已获信任，两个共享 JSON 未被个人配置替换。
- **无法解析 `python.interpreterPath`**：确认 Python 扩展在当前 VS Code 窗口启用，并重新选择解释器。
- **Tasks 成功但 Agent 报缺模块**：核对两边解释器；不要自动切换到一个猜测的全局 Python。
- **看不到原生 Skill 名称**：本轮只做仓库入口，不是 Skill 注册失败；显式让 Agent 读取唯一 `SKILL.md` 即可。
- **渲染不可用**：保留真实报告，检查当前系统的 Node、浏览器、WebGL、字体等缺项；不自动改为外部上传或别的渲染实现。
- **在 WSL / Remote 窗口运行**：Python、工作区、浏览器和依赖必须在同一个实际执行环境中可见，不能直接套用本机 Windows 路径。
- **不支持的地图请求**：当前场景注册为空，业务入口默认拒绝；结构校验成功不代表生产数据、TIFF、真实 CRS 或任意地图场景已开放。宿主换成 Codex / Claude 不会改变这一点。
- **审批与安全**：IDE 的执行许可不是 T1 / TP / G1 / G2 / G3，不能由 Agent 代签业务审批。保持允许根、锁摘要、受控渲染和回执校验不变。
- **Hermes 预检**：现有 `environment probe-host --host hermes` 不适用于 Codex / Claude；本轮没有修改该报告 Schema，也没有补出虚假的会话工具结果。

## 6. 验收声明

自动测试只证明共享配置和本地 CLI 契约，不证明扩展已安装、账号已登录、Agent 已实际加载指令，或会话拥有 GIS 工具。必须在你实际使用的 VS Code 窗口中运行任务与第 4 节提示，才能补上会话验收。可信宿主 ToolResult 回传仍是后续工作，不因本次入口落地而完成。

## 7. 官方依据（2026-10-30 核对）

- OpenAI Docs：`https://developers.openai.com/codex/guides/agents-md`（仓库指令）；`https://developers.openai.com/codex/ide`（IDE 与扩展）；`https://developers.openai.com/codex/skills`（原生 Skill 发现与链接，与本轮仓库入口区分）。
- Claude Code：`https://code.claude.com/docs/en/memory`（`CLAUDE.md` 的 `@` 导入）；`https://code.claude.com/docs/en/vs-code`（VS Code 入口）。
- VS Code：`https://code.visualstudio.com/docs/debugtest/tasks`（工作区任务、`process`、`${command:python.interpreterPath}`）。

本文是人类接入说明，不是运行时机器协议；执行规则在根目录入口与唯一 Skill，业务校验仍以 Schema / 策略 / 程序为准。
