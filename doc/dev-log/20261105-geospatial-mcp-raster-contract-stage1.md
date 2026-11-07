# 2026-11-05 Carto 侧 MCP 接入与栅格输入契约（第一批）

## 本批范围

在 Carto 唯一实现根 `skills/carto-agent/` 增加独立 GIS 数据服务接入，不迁入 MCP 的渲染功能，不修改外部 geospatial-mcp 项目，也不处理用户真实 landCover.tif。

分工：geospatial-mcp 负责基础数据读取、统计和坐标转换；Carto 负责分类语义/颜色/图例、布局、渲染、导出及审批。本批没有制作 A4 地图。

## 实现

- `adapters/mcp_stdio.py`：惰性可选官方 MCP SDK，固定隔离解释器启动、stdio 握手、受限分页工具发现、类型化工具结果、严格二进制资源接收、会话超时和错误收敛；不重试、不接受动态 Shell/URL。
- `adapters/geospatial_mcp.py`：三个固定 ToolGateway 能力（info/statistics/reproject），配置/catalog/source/project/tenant/能力及预算绑定；单 dataset catalog 快照；任务/产物验证与原子只增发布。
- 五份新 Schema：raster-input、geospatial-mcp-config、geospatial-request、geospatial-wire、geospatial-result；每份有合法/非法 Fixture。generate-request 新增栅格结构分支，原 GeoJSON 分支保持。
- `data inspect-raster`：仅 info/statistics，reproject 在创建适配器前拒绝；stdout 只有 ToolResult 摘要和证据引用，不展开类别/坐标数据。
- ImmutableArtifactStore 增加可选 PathGuard，供新适配器限制证据写入项目根；不改变原有调用方接口。
- tool-bindings 增加三项受控数据能力；可选依赖由 pyproject 的 geospatial extra 和 requirements-geospatial.txt 声明。
- 接入说明位于 `workflows/geospatial-data.md`；README、SKILL、routing 同步标注数据能力与地图业务能力的区别。

## 验证中修正

实际安装环境为 Python 3.12.14、MCP SDK 2.2.0、独立服务 0.3.0。未安装或升级依赖。

首次真实 stdio 联调暴露 SDK 2.x 接口变化：模型属性为 snake_case，工具分页使用 PaginatedRequestParams，而不是旧的 camelCase 属性/cursor 参数。已按声明的 2.x 客户端契约修正，并增加分页测试。

SDK 默认会校验远端提供的输出 Schema；本适配器通过公开 validate_tool_result 钩子只核验类型化结果，业务内容统一由本地固定 geospatial-wire 验证。实际子进程测试也断言没有调用远端 Schema 校验路径，不把远端 Schema 当授权或执行协议。

## 测试与基线

执行命令均使用已确认的独立 GIS 环境解释器和 `-B`。合成集成测试显式设置 CARTO_GEOSPATIAL_TEST_PYTHON；只使用临时 4×3 整数 TIFF，未读取业务像元。

| 检查 | 结果 |
|---|---|
| CLI --help | 通过 |
| schema check | 56 份 Schema 通过 |
| 新增单元/契约测试 | 37 项：36 通过、1 跳过（Windows 无符号链接创建权限） |
| 实际 MCP stdio 集成 | 4 项全部通过 |
| 全量 unittest（开启集成） | 199 项：192 通过、3 跳过、2 failures、2 errors |
| git diff --check | 通过（既有文件有行尾转换提示） |

集成覆盖：元数据、全量类别统计、EPSG:4326 重投影与资源下载、独立 rasterio 打开输出验证、同网格转换保留内部掩膜及有效 0/255、只读 CLI 输出回执。新增拒绝测试覆盖越权/路径、配置/源漂移、类值域和计数不一致、任务/二进制篡改、输出超限、超时不重试及关闭失败无成功证据。

**全量测试不是全绿。** 改动前已记录的基线是 158 项、2 failures + 2 errors、2 跳过；本批后仍是同四个失败，没有新增失败：

1. test_intent_semantics：test_planner_and_compiler_enforce_projection_and_preserve_envelope，PLAN_INTENT_MISMATCH。
2. test_layout_contract：test_compositor_places_map_image_in_frame_and_binds_print_size，LAYOUT_SNAPSHOT_MISMATCH。
3. test_layout_contract：test_final_check_uses_same_snapshot_and_detects_anchor_drift，frame 顺序不一致。
4. test_layout_contract：test_resolution_matches_explicit_fixture_and_does_not_mutate_inputs，同上。

仓库本来已有多项未提交修改/删除。本批没有还原、清理或修复无关基线问题；没有提交 Git commit。

## 保留限制

- 场景策略 profiles 仍为空，代码 `_COMPONENTS` 仍为空；未放宽 T1/TP/G1/G2/G3 或生产标志。
- 重投影只有能力适配器，尚无授权业务场景编排或任务恢复 CLI；只读检查不能变换数据。
- SDK 解码后限制不等于恶意进程的硬内存隔离；解释器/服务安装/配置/目录须可信。版本声明不是代码签名。普通运行校验摘要并信任服务元数据，不内嵌第二套 GIS 解码器。
- 会话退出失败可能留下 TIFF/任务文件，但不产生网关成功证据；不自动把残留当成成功，不自动重复变换。
- 尚未接入 source-manifest、模板分析、栅格准备、冻结、图例或渲染。未自动推断类别含义，也不使用 reclass_legend.csv。

下一批应在 Carto 内实现栅格数据准备与冻结引用、分类语义/颜色合同、图例、栅格渲染及 A4 横版布局，再通过真实数据和已有审批验收。
