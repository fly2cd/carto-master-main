# 第一阶段实施记录：Hermes 与工具预检

日期：2026-10-29。

## 1. 实施范围和结论

本次按实施方案第四章的**第一批：让 Hermes 说清“我现在有哪些工具”**实施，尚未开始第二批正式结果回传，也没有实施方案第六章所说的整个“第一轮（前两批）”。

**已落地：**可重复运行的本机预检、可选的 Hermes Skill 资源读取检查、严格报告格式、合成样例、自动测试，以及实际会话验收说明。

**已实测：**本机 Hermes 的 `skill_view` 在独立进程中成功读取本工作区的 `SKILL.md` 和合成 GeoJSON 资源。既比较了返回内容，也核对了来源路径，不能用另一个目录里的同内容副本冒充。检查没有重装 Hermes，也没有重新注册 Skill。

**尚未完成：**用户正在使用的 Hermes 会话工具盘点，以及该会话中 GIS 读取、分析、绘图和导出的实际调用验证。因此不能把第一批完整验收或阶段 A“接上了”标记为完成，更不能宣称已能处理真实 TIFF。

## 2. 做了哪些修改

除本记录和方案进度说明外，文件都位于唯一实现根 `skills/carto-agent/`。

| 文件 | 修改内容 |
|---|---|
| `scripts/carto_core/adapters/host_probe.py`（新增） | 检查安装、源码版本标记、Skill 注册目录和配置摘要；按需调用受控子进程；生成报告；限制报告输出位置和覆盖行为 |
| `scripts/carto_core/adapters/hermes_probe_worker.py`（新增） | 调用本机 Hermes 的指定文件查看接口，核对两份资源的来源和内容，不启用完整 Skill 凭据准备流程 |
| `scripts/carto_core/cli.py` | 在现有 CLI 中增加 `environment probe-host`，没有建立第二套入口 |
| `schemas/host-preflight.schema.json`（新增） | 限定报告字段和状态；拒绝未知字段及伪造的会话/阶段/生产通过标记 |
| `assets/host-probe/sample.geojson`（新增） | 两条完全合成的 Point 要素，作为资源读取和后续 GIS 工具验证样例，不依赖土地覆盖文件 |
| `scripts/tests/test_host_probe.py`（新增） | 22 项测试，覆盖安全边界、配置过滤、真实子进程行为、超时、输入变化、来源错误和报告状态 |
| `scripts/tests/fixtures/host-preflight.valid.json`、`host-preflight.invalid.json`（新增） | 合法和非法协议样例，仅含合成路径 |
| `scripts/tests/fixtures/schema_cases.py` | 将新增报告接入现有 Schema 全覆盖检查 |
| `workflows/host-preflight.md`（新增） | 给出运行方法、两层验证边界和实际会话中的工具盘点步骤 |
| `SKILL.md`、`workflows/routing.md`、`workflows/generate-map.md` | 指向辅助预检说明；明确不增加地图业务路由、不放宽原有生产限制和审批要求 |

没有修改工具授权策略、地图生成状态机、G1/G2/G3、模板发布、正式渲染或交付实现。没有新增 Python 依赖。

## 3. 本机真实检查结果

最终报告：`projects/host-preflight/hermes-20261029-verified.json`。

报告位于已忽略的项目运行目录，不作为可复用 Fixture 或模板提交。先前的 `hermes-20261029.json` 是更早一次检查，保留不覆盖；以 `-verified.json` 为本次最终检查依据。

| 项目 | 结果 |
|---|---|
| Hermes 启动文件 | 存在，未执行启动器的版本查询 |
| 本机源码版本标记 | `0.21.1`，不是“最新版”声明 |
| 全局 Skill 链接 | 存在，指向当前工作区 |
| 项目本地 Skill 链接 | 存在，指向当前工作区 |
| 当前检查 home 的终端配置 | `local` |
| 当前检查 home 的 MCP 配置项 | 0；不据此断言其他 profile 或正在运行的会话没有 MCP |
| 独立工具进程读取 Skill 文件 | 通过 |
| 独立工具进程读取合成资源 | 通过 |
| 用户正在使用的实际会话 | 未验证 |
| GIS 读取、空间分析、地图绘制、导出 | 未验证 |
| 总体报告状态 | `needs-session-verification` |

最终检查前后核对了 Hermes `config.yaml` 和原始 `landCover_reclassified.tif` 的文件摘要，二者均未改变。

## 4. 验证结果

- `carto schema check`：48 个 Schema 结构检查通过。
- 完整回归：162 项，160 项通过、2 项因 Windows 符号链接创建权限限制而跳过，0 失败。
- 随后补充“相同内容但来源路径错误”的校验与测试，最终预检专项重跑：22 项，21 项通过、1 项因同一 Windows 权限限制而跳过，0 失败。该补充没有重跑一遍全部浏览器回归；已有完整回归与最终专项结果分别记录，不混算数量。
- 最终版本再次调用本机真实 Hermes `skill_view`，两次资源读取均通过。模拟模块测试与这次真实调用分别进行，未把模拟测试当成真实 GIS 验收。
- `git diff --check`：通过。

测试命令：

```powershell
python skills/carto-agent/scripts/carto.py schema check
python -m unittest discover -s skills/carto-agent/scripts/tests -v
python -m unittest discover -s skills/carto-agent/scripts/tests -p test_host_probe.py -v
```

## 5. 安全和范围说明

- 默认静态检查不启动 Hermes，不连接 MCP；只有显式启用本机工具检查时才运行已安装的 Hermes Python。
- 不读取 `.env` 或 `auth.json`，不输出服务名称、URL、启动参数、环境变量密钥或外部异常堆栈。
- 子进程禁止网络、其他进程启动和文件写入，设置超时与无输入模式，不传递模型 API 密钥。该防护用于受信的已安装代码，不是任意代码安全沙箱。
- 读取外部路径使用原有允许根检查；报告只能保存到项目根内，不能覆盖已有报告。
- 没有新增土地覆盖渲染器、土地覆盖专用流程或固定类别字典；生产能力和工具授权策略未放开。
- 没有修改原始 TIFF，没有针对真实数据生成地图；完整回归中的地图仍来自既有合成测试。
- 本次没有改写已有 `doc/image-to-style-layout-implementation-plan.md`。

## 6. 下一步仍需在 Hermes 会话做什么

请在实际使用的 Hermes 会话中执行以下检查，不要只在另一个终端复述本报告：

> 请读取当前工作区的 carto-agent Skill，并按 skills/carto-agent/workflows/host-preflight.md 检查当前会话实际可用的工具。先用现有且获准的工具读取 skills/carto-agent/assets/host-probe/sample.geojson，列出文件读取、GIS 读取、分析、绘图、导出分别由哪个工具提供，以及哪些尚不可用。区分普通文本读取和 GIS 读取，不修改配置、不安装软件、不上传数据、不生成正式地图。保留实际调用结果，不把本机预检通过说成会话已经验证。

这一步完成后，再开展第二批“真实工具执行结果回传到 Carto”。第二批要延用现有授权和 ToolResult 等结构，不把本次诊断报告当作生产执行证据。
