# 真实栅格测试脚本与 Claude Code 接力测试

入口：`skills/carto-agent/scripts/tests/manual/real_raster_acceptance.py`。
这是开发验收脚本，不是新的制图入口或运行协议；地图执行仍走唯一 `carto.py`。

## 测试范围

| 步骤 | 检查内容 | 证据 / 限制 |
|---|---|---|
| 01 | 本进程实际 Python 版本 | 必须 3.11+；不猜 WindowsApps 或 IDE 选中的解释器 |
| 02 | `carto.py --help` | 检查退出码和真实帮助内容 |
| 03 | `carto.py schema check` | 检查 `ok`、退出码、数量及完整 Schema 集合 |
| 04 | 用户 TIFF 只读预检 | 允许根、大小、SHA256、TIFF 文件头；**不是**像元/CRS 有效性验收 |
| 05 | 用户 CSV 只读预检 | 允许根、大小、SHA256；**不**推断列名、类别名、颜色或 0/255 含义 |
| 06 | 能力策略快照 | 校验现有 Schema，记录 default 和 profile 数；不改策略 |
| 07 | 依赖导入探测 | NumPy、Rasterio、Matplotlib、Pillow、fontTools、MCP、pypdf、pypdfium2；不安装 |
| 08 | 可选隔离回归 | 只使用现有合成 Fixture；逐用例记录状态、时间和安全错误代码 |
| 09 | 前后摘要复核 | 已读取的真实 TIFF/CSV 和能力策略必须字节一致 |
| 10 | 真实 MCP 分类准备 | 本脚本未执行；需要显式配置、数据合同及身份，使用已有 data CLI |
| 11 | 真实地图正式链路 | 本脚本未执行；需要业务组件/模板准入和真实 G1/G2/G3 |
| 12 | 插件会话验收 | 脚本无法证明宿主；需要 Claude Code 会话操作记录或人工观察 |

**重要：**“预检通过”“合成回归通过”“真实制图交付”“插件端到端通过”是四个不同结论。
即使传 `--host vscode-claude-code`，也仅是自报标签，绝不自动把插件验收改为通过。
依赖探测成功表示探测执行成功，必须查看各依赖是否 `importable`；不等于真实 renderer 环境回执。
本脚本不会读取真实栅格像元/坐标、解释 CSV 数据行或生成用户地图。

## 从仓库根目录执行

先读 `AGENTS.md`、`skills/carto-agent/SKILL.md` 的“IDE 宿主最小接入”、
`workflows/routing.md` 和 `workflows/raster-classification.md`。
确认真实 Python 3.11+ 可执行文件后，将下面的 `$Python` 赋值为该路径。
不自动安装依赖、插件，不运行 bootstrap，不修改业务能力策略。

```powershell
# $Python 必须是本次确认的真实解释器；不要使用猜测的路径。
& $Python -B --version
& $Python -B skills/carto-agent/scripts/carto.py --help
& $Python -B skills/carto-agent/scripts/carto.py schema check

# 真实文件只读预检（默认输入就是用户指定的两个文件）
& $Python -B skills/carto-agent/scripts/tests/manual/real_raster_acceptance.py `
  --mode preflight --host vscode-claude-code
$PreflightExit = $LASTEXITCODE
# 必须先读取终端返回的 report_dir 下的 report.json，再决定后续操作。
```

如本机可选渲染/QA 依赖已经由用户安装到仓库内开发目录，可以显式复用；先确认目录存在，
缺失时停止并报告，不自动安装。环境变量只影响当前终端/子进程。

```powershell
$env:PYTHONUTF8 = '1'
$env:PYTHONPATH = (Join-Path $PWD 'skills/carto-agent/scripts') + ';' + `
  (Join-Path $PWD 'projects/.carto-dev/raster-rendering') + ';' + `
  (Join-Path $PWD 'projects/.carto-dev/pdf-qa')
$env:MPLCONFIGDIR = (Join-Path $PWD 'projects/.carto-dev/mplconfig')
# 只有显式确认独立 GIS 服务解释器和中文字体后才设置这两个变量：
# $env:CARTO_GEOSPATIAL_TEST_PYTHON = <已确认安装 geospatial-mcp 的解释器>
# $env:CARTO_TEST_CJK_FONT = <已确认存在且允许读取的中文字体文件>

# 聚焦栅格：Schema、MCP、分类准备、表达、图体、整页和正式链路
& $Python -B skills/carto-agent/scripts/tests/manual/real_raster_acceptance.py `
  --mode regression --suite raster --host vscode-claude-code
$RasterExit = $LASTEXITCODE

# 或完整回归（含安全底座、IDE 接入及本脚本自身的正反例）
& $Python -B skills/carto-agent/scripts/tests/manual/real_raster_acceptance.py `
  --mode regression --suite all --host vscode-claude-code
$AllExit = $LASTEXITCODE
```

回归会启动本地测试进程；配置了独立 GIS 测试解释器时，部分测试会启动该服务，
但输入是测试生成的小型合成 TIFF，**不是** `projects/dataset` 中的真实文件。
临时审批只用于隔离的合成测试，不能用于真实运行。
脚本不自动启用 `CARTO_RASTER_QA_DIR`；不要给回归继承未确认的输出环境配置。

### 退出码与结果

- `0`：本次所选阶段通过，不表示真实地图或插件验收通过。
- `2`：测试失败；后续依赖步骤不执行，最后仍复核已读取输入/策略摘要。
- `3`：回归有跳过，覆盖不完整；保留已通过/失败/跳过的真实数量，不把跳过算通过。
- 子进程超时：报告失败，不自动重试。
- 进程被中断：报告的 `completed_at` 仍为空/状态仍 running，不能当作完成。

每次创建独立目录，不覆盖历史结果：

```text
projects/landcover-acceptance/.carto/acceptance-tests/<时间-随机ID>/
  report.json       # 逐步骤起止时间、耗时、退出码、文件摘要、阻塞项
  report.md         # 可读步骤表
  regression.json   # 仅回归模式：逐用例状态及汇总；不保存原始 traceback
```

`--project-root` 可选择仓库 `projects/` 内独立项目，但不允许 `projects` 根、
`projects/dataset` 或 `projects/.carto-dev`；不能把真实验收报告写进源码或数据目录。
`--raster` / `--legend` 可指定其他明确授权的输入；仓库外输入还需重复提供
`--allowed-root <已存在的绝对目录>`，所有这些路径经过 `PathGuard`。
报告是本地开发记录，不是签名回执；不把它当作机器审批或生产工作流证据。

## 交给 VS Code Claude Code 的提示词

在真正的 VS Code 中打开本仓库，通过 Claude Code 插件新建对话，再粘贴：

```text
请在当前 VS Code Claude Code 会话执行 Carto 栅格测试。
先读 AGENTS.md、skills/carto-agent/SKILL.md 的 IDE 宿主最小接入、workflows/routing.md、
workflows/raster-classification.md，以及 skills/carto-agent/scripts/tests/manual/README.md。
可参考 projects/landcover-acceptance/session-notes.md 中“本机已验证配置”，但仍需重新确认路径与版本。

不要修改实现或策略，不要安装依赖，不要伪造或自动签发审批，不要调用内部渲染器绕过业务入口。
确认 Python 3.11+，执行唯一 carto.py 的 --help 和 schema check。
使用现有依赖运行 real_raster_acceptance.py --mode preflight --host vscode-claude-code，
查看本次 report.json；预检通过后运行 --mode regression --suite all --host vscode-claude-code。
真实输入仅使用 projects/dataset/landCover_reclassified.tif 和 projects/dataset/reclass_legend.csv，
不得把它们替换测试中的合成 Fixture。

请逐步报告：命令、实际退出码、通过/失败/跳过/阻塞、证据文件路径。
脚本退出 3 表示存在跳过，要说明具体用例和限制，不能写“全部通过”。
在本次结果目录另写 plugin-session.md，仅记录你在本插件会话实际执行和观察的步骤；
不要拷贝密钥、完整环境变量、业务行或坐标，也不要覆盖脚本报告。
宿主标签不是身份证明；这份补充说明也是会话记录，不是签名审批。
真实 MCP 分类准备缺少配置/语义时停止询问；真实制图未满足业务/模板准入时明确记为未执行。
```

## 真实数据后续验收（本脚本不自动执行）

补齐显式 MCP 配置、允许根、tenant/project/subject/run 身份、源许可/敏感性/CRS 声明，
以及 CSV 值/名称/颜色列和调色板合同后，读取 `workflows/geospatial-data.md`，
使用 `carto.py data inspect-raster` 的 info/statistics，再运行
`data analyze-classification`。若状态为 `needs-clarification`，向用户展示待澄清项，
不能默认把 0 和 255 都当背景；明确回答后经 `data clarify-classification` 产生新冻结引用。
这仍不是 G1/G2/G3；正式 A4 横版地图必须由获准的业务组件和模板进入 `generate-map`。
