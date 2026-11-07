# 宿主预检：第一阶段

## 用途与边界

用于用户要求检查 Hermes 接入、Skill 装载或可用工具的情况。这是现有地图工作流前的辅助检查，不是第五条地图业务路由，也不调用 `generate-map` 去处理尚未支持的真实数据。

第一阶段分两层：

1. **可以自动检查的本机事实**：指定 Hermes home 的安装、源码版本标记、Skill 链接、配置概况，以及可选的本机 Skill 工具读取。
2. **必须在实际会话核验的事实**：该会话是否加载正确 Skill，实际可调用哪些工具，以及工具能否完成对应的数据任务。

独立进程调用 Hermes 的工具，不等于接管或检查了用户正在使用的会话。不要混淆配置中出现的服务、工具可见、工具获准使用和真实任务成功。

## 一、先做静态检查

使用唯一 CLI 的 `environment probe-host` 子命令。指定真实的项目根、当前使用的 Hermes home 和允许读取的根目录，不要根据其他机器的默认值猜测。命令不执行 `hermes.exe`，不安装、不升级、不注册 Skill、不连接 MCP。

PowerShell 示例（先把变量设置为经过确认的实际目录）：

```powershell
$project = (Get-Location).Path
$hostHome = $env:HERMES_HOME
# 如果当前进程没有 HERMES_HOME，先确认实际 profile 的目录，不要直接继续。
python skills/carto-agent/scripts/carto.py environment probe-host `
  --host hermes --project-root $project --host-home $hostHome `
  --allowed-root $project --allowed-root $hostHome `
  --output ("projects/host-preflight/inspection-" + (Get-Date -Format 'yyyyMMdd-HHmmss') + ".json")
```

报告输出必须位于项目根内，已有文件不覆盖。`--allowed-root` 中包含 Hermes home 只是为了读取，不允许将报告写入其配置目录。

报告只保留配置结构的安全摘要：本地或远端终端方式、MCP 配置项数量及连接类型。不会输出服务名称、连接地址、启动参数、环境变量值或解析错误中的原始配置。配置缺失或读取失败不等于“会话没有工具”。

Skill 链接只检查目录元信息，并与获准的工作区 Skill 路径比较；不通过一个任意链接读取其目标。项目本地链接与全局链接可以同时存在，预检不会删除或重新创建它们。

## 二、可选的本机工具读取检查

只有明确提供 `--verify-local-tools` 和已安装 Hermes 的 Python 路径，才运行工具检查。不要默认把当前 Carto Python 当成 Hermes Python，也不要为了检查而重新安装解释器。

```powershell
# $hostPython 应为已确认的 Hermes Python 完整路径。
python skills/carto-agent/scripts/carto.py environment probe-host `
  --host hermes --project-root $project --host-home $hostHome `
  --allowed-root $project --allowed-root $hostHome `
  --verify-local-tools --host-python $hostPython --timeout 30 `
  --output ("projects/host-preflight/local-tools-" + (Get-Date -Format 'yyyyMMdd-HHmmss') + ".json")
```

该检查通过受控子进程调用本机 `tools.skills_tool.skill_view` 的指定文件读取方式：

- `SKILL.md`；
- `schemas/layout.schema.json`。

工具返回的文本必须与工作区文件一致，不能只依据“成功”字样判断。调用时关闭 Skill 内容预处理，避免执行内联命令；阻止凭据文件读取、联网、启动其他进程和文件写入，不传递模型密钥。超时只结束本次子进程，不重启、不终止用户原有 Hermes 会话。

这些防护用于减少受信安装代码的意外副作用，**不是运行任意不可信代码的安全沙箱**。Hermes 内部接口变化或触发禁止操作时，应报告未通过，不解除限制或临时换成 Carto 自己读取来伪装成功。

检查通过仅证明：**本机 Hermes 的 `skill_view` 可以读取正确 Skill 中的两个资源文件**。它不证明通用 `read_file`、GIS 读取、分析、渲染或导出可用。

## 三、在实际 Hermes 会话完成工具盘点

1. 确认当前会话的工作区和 profile。使用该会话真实提供的 Skill 查看工具读取当前 `carto-agent`；不只复述技能名称。
2. 根据当前会话实际暴露的工具列清单，区分文件读取、GIS 读取、空间处理、绘图和导出。不编造 `list_tools` 等并不存在的工具调用。
3. 用实际可用、已经获准的工具读取 `skills/carto-agent/schemas/layout.schema.json`；核对这是当前框架协议资源，不读取用户业务数据，也不把文件读取成功当作 GIS 能力通过。
4. 若工具只能返回文件文字，只确认“资源文本读取”；若声称 GIS 读取，应由 GIS 工具实际返回要素数、几何类型和字段等可核对结果。
5. 如要确认 TIFF 能力，还需对应栅格工具的独立读取验证。GeoJSON 测试通过不等于 TIFF 可用。先使用小型获准测试数据，再在业务读取授权范围内检查真实 TIFF。
6. 记录工具名称、实际运行位置、任务输入、调用结果依据和缺少的能力。远端工具不能自动取得本地 `D:\...` 文件；不要因此自动上传数据。
7. 缺少功能就明确列出。未得到许可，不安装 GIS 软件、不改 MCP 配置、不导入其他软件的服务、不运行任意新代码。

不要用临时绘图绕过当前 `generate-map` 的业务范围。`landCover_reclassified.tif` 不是此预检命令的默认输入。

## 四、如何判断报告

- CLI 的 `ok: true` 和退出码 0：表示检查正常结束，**不是阶段验收通过**。
- `local_probe.status: passed`：表示独立工具进程的两次资源读取通过。
- `status: needs-session-verification`：还需要实际会话核验；`attention-required` 表示另有安装、配置、注册或本机工具问题需要处理。
- `active_session_verified`、`stage_passed`、`production_ready` 在此版本的自动报告中固定为 `false`；一般制图能力固定为 `unverified`。报告不接受模型手填“已通过”来提升状态。
- 会话级工具记录仍由实际会话产生。第一阶段的完整验收需结合这些真实记录，不能只交这份自动报告。
- 本报告不是 `ToolResult`、审批回执或生产能力登记；不输入第二批尚未实施的正式结果接收路径。

第二批再实现“Carto 发出工作要求 → 宿主执行 → 可信结果接收 → 继续任务”。不要为这次预检新建一套并行的地图运行状态或审批格式。
