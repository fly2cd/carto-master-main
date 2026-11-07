# 2026-11-05 分类栅格准备 / Rasterio + Matplotlib 静态图体（第二批）

## 实施范围

用户已确认 Rasterio + Matplotlib，未知值语义作为用户澄清内容，并明确开始实现。
本批不变更独立 geospatial-mcp 项目，不注册业务场景，不签发审批，不把内部图体冒充正式 RenderReceipt。

新增：
- `raster-classification-request / raster-classification-answers / raster-prepared-data / raster-map-body` 四份严格 Schema、各自合法/非法合成样例。
- `compiler/raster_classification.py`：显式 CSV 列匹配，名称/颜色/图例合同，动态澄清，显式版本化候选色表。
- `workflow/raster_preparation.py`：真实 ToolGateway/MCP 统计证据绑定，源/CSV 不可变快照，身份/摘要绑定回答，加载时重新推导验证。
- `adapters/raster_renderer.py`：Rasterio MemoryFile、全分辨率读取/核验、稀疏类别索引、Matplotlib ListedColormap + BoundaryNorm、透明掩膜、最近邻缩放、图体冻结。
- 既有 `SvgCompositor` 增加可选实际图像矩形；在 map frame 内像素精确放置，拒绝越界和拉伸。既有调用未传新参数时保持原行为。
- 同一 CLI 下 `data analyze-classification / clarify-classification`；后者不再调用 MCP。
- 可选 `raster-rendering` 依赖及 Skill、README、工作流说明。

实现/测试均在 `skills/carto-agent/`；根目录仅维护既有 README、依赖元数据及本开发日志。
原始 TIFF/CSV 未改写，未生成用户最终地图。测试只使用临时合成数据。

## 关键语义

- 0/255 没有特殊硬编码。所有观测到但分类表未覆盖的值一律澄清。
- `semantic` 与 `display` 独立，用户将某类视为 NoData 不会改写文件 NoData。
- 缺名称/颜色继续澄清，不从文件名/说明文字推断。
- `ready` 不等于任何审批或业务场景就绪。
- 替换回答绑定最初无回答基线 digest，重新提交完整 overrides；不暗中合并旧答案。
- 图例和图体使用同一合同；`observed` 指源分辨率实际出现，不按缩图抽样删图例。
- 全掩膜、全隐藏或缩放后全透明均拒绝输出空图。
- 自包含、投影 EPSG、单整数波段、north-up；不做自动 CRS 转换/旋转支持/连续栅格。

## 测试环境

确认 Python 3.12.14。起初 GIS 解释器没有 Matplotlib，也没有 pip；经安装许可，用现有 uv 将可选依赖安装到被忽略的 `projects/.carto-dev/raster-rendering`，未修改独立 GIS venv。
测试通过 `PYTHONPATH` 引用该项目内目录，`MPLCONFIGDIR` 也位于 `projects/.carto-dev/`。该目录不是产品的自动环境发现机制；正式环境仍需操作员显式安装声明的 extra。

实际渲染环境：Rasterio 1.5.2 / GDAL 3.12.2 / Matplotlib 3.11.2 / NumPy 2.5.4 / Pillow 12.3.0。
真实 stdio 服务使用显式 `CARTO_GEOSPATIAL_TEST_PYTHON` 指向独立服务解释器。

## 验证结果

- 初始基线：199 项；2 failures + 2 errors，7 skipped。
- 本批最终全量：233 项；同样 2 failures + 2 errors，3 skipped；即 226 项通过。
- 新增 34 项全部通过，含真正 MCP → 冻结 → 澄清 → Matplotlib → SVG 合成测试，不是把 mock 当成实际服务验证。
- 60 份 Schema 自检通过；新 Schema 均进入全量合法/非法 fixture 测试。
- 两个新增 CLI 的 `--help`、7 个变更 Python 文件的 AST 检查、`git diff --check` 通过；Git 有既有文件的 LF/CRLF 提示，不是 whitespace 错误。
- A4 横版 297×210 mm、300dpi、3508×2480 px；验证图体颜色/alpha、方向、稀疏负数/大整数、内置掩膜、NoData、矩形等比例放置、图例一致性。
- 对合成图体 PNG 作了有限目视核对；**未完成整页中文字体/印刷视觉验收**。

既有四项失败保留，未放松检查器：
1. `IntentSemanticsTests.test_planner_and_compiler_enforce_projection_and_preserve_envelope`：`PLAN_INTENT_MISMATCH`。
2. `LayoutContractTests.test_compositor_places_map_image_in_frame_and_binds_print_size`：`LAYOUT_SNAPSHOT_MISMATCH`。
3. `LayoutContractTests.test_final_check_uses_same_snapshot_and_detects_anchor_drift`：fixture frame 顺序不同。
4. `LayoutContractTests.test_resolution_matches_explicit_fixture_and_does_not_mutate_inputs`：同一 fixture 顺序漂移。

## 仍需后续批次

- 分类栅格场景组件、准入/检查器、受信注册。
- MapSpecLock 的 prepared raster 引用及渲染环境证明，RenderScene 后端分派和正式回执。
- G2/G3 与成品检查接入、PDF/整页 PNG 导出验收。
- 中文字体、物理字号、图例密度、比例尺与真北/格网北的正确语义及打印视觉验收。
- 再以用户明确的未知值语义/颜色合同执行真实专题图验收。

`profiles: []` 与代码 `_COMPONENTS = {}` 保持不变；底层图体可运行不代表 `generate-map` 已支持分类栅格。
