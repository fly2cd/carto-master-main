# 2026-11-05 分类栅格第三批 A：内部整页输出与打印尺寸验收

## 目标和边界

在第二批分类冻结/图体基础上补齐整页输出，继续采用 Rasterio + Matplotlib。所有实现留在 `skills/carto-agent/`，没有改独立 GIS 项目，没有新增导出 CLI，没有注册未完成的业务场景，没有签发真实审批，没有修改用户 TIFF/CSV。

本批是可集成的内部页面适配器，不是整个 `generate-map` 已贯通。正式审批/锁/RenderReceipt 仍待下一小批接入，不把本批完成原因归结成“只差用户输入”。

## 实现

- `adapters/raster_page_renderer.py`：`RasterPageRenderer.render/load_verified`；复用现有准备服务、图体及 LayoutResolver，不重新实现像元着色或布局框求解。
- 严格协议 `raster-page-request` / `raster-page-output`，各自合法/非法合成 Fixture，注册到通用 Schema 测试。
- 显式字体允许根/字节身份、32 MiB/单字体 TrueType 限制、字体冻结、字形覆盖、技术嵌入标记检查。PDF 用嵌入子集字体，SVG 用字形路径；不回退缺字、不调用 TeX。
- 固定 pt 字号，实际文字测宽换行、标题与图例容量、全部 overlay 一一绑定、实测超框拒绝。复用一份分类颜色和图例定义。
- 297×210 mm 等物理页面支持；A4/300dpi PNG 为 3508×2480，PDF/SVG 保留物理尺寸。无 tight-bbox 裁纸，类别图体不平滑插值。
- 可选显式投影距离比例尺，正确转换线性 CRS 单位（包括 US survey foot）；仅支持格网北，不声称真北/磁北或大地线距离。
- 字体、请求、三格式资源和页面报告均进入项目内容寻址存储；重载重新渲染对比，拒绝代码、环境、布局、字体和输出漂移；用户原文件删除不影响冻结复现。
- 页面报告固定边界为 `internal-page-output-not-formal-render-receipt`，不伪装成 MapLibre 回执。
- `raster-rendering` 额外依赖显式声明 `fonttools>=4.40,<5`。只用于 PDF QA 的 pypdf/pypdfium2 不加入运行时依赖。

## 既有回归修正

上一批遗留四个失败均有确定根因，没有改变校验器：

1. `test_intent_semantics.py` 的 `projection` 从共享 Fixture 深拷贝后保留了引用别名；更新 `brief_ref.digest` 同时污染 `intent_ref.digest`。仅在测试构造器中独立建立 Intent 引用，保留运行时 `PLAN_INTENT_MISMATCH` 的严格检查。
2. `resolved-layout.valid.json` 的 resolved `frames` 未按 resolver 的 ID 顺序排序，造成三个测试失败。仅修正显式期望 Fixture 的顺序，不在运行时接受漂移快照。

追加处理全量回归中的一个偶发测试失败：`test_up27_integration.py` 的时间戳测试在 `complete_step` 之前休眠，但操作的起始时间是在该方法内记录，开始与完成可以落在同一毫秒。将该测试改为固定时钟并断言两端的准确值，另加同一时钟刻度完成的测试。未修改运行时时间记录、状态机、审批或校验器。最后一轮失败日志已用修复后的完整回归重新生成。

## 验证

确认解释器为独立 GIS 项目现有 Python 3.12.14；运行前仍执行 CLI help 和 schema check。没有向这个 venv 安装包。

已授权的可选渲染依赖位于忽略目录 `projects/.carto-dev/raster-rendering`；本批经单独许可将 pypdf/pypdfium2 安装到 `projects/.carto-dev/pdf-qa`，仅用于验收。测试使用临时合成 TIFF/CSV，未使用用户业务行。

- 全量：247 项，244 通过，3 跳过，0 失败/错误（见项目忽略目录 `stage3-final-tests.json`）。
- 新增页面测试 13 项，覆盖真实独立 MCP → 冻结 → 澄清 → 三格式页面/重载链。
- Schema：62 个自检通过；合法/非法 Fixture 均在全量测试中执行。
- Skill 下全部 86 个 Python 文件 AST 解析通过，`git diff --check` 通过。
- PDF 结构检查：单页、A4 MediaBox、中文文字可提取、TrueType FontFile2 嵌入。
- PDF 无可用 Poppler，使用经批准的 PDFium 独立渲染；150dpi 整页图已人工目视检查：十个合成中文类别、较长图例换行、标题、比例尺和格网北，无缺字、裁切或框间碰撞。
- 合成 QA 保存于 `projects/.carto-dev/qa/synthetic-a4-chinese.{pdf,png,svg}` 及独立 PDF 渲染图 `synthetic-a4-chinese-pdf.png`。均被 Git 忽略，明确标为非用户成果。

复现（先显式安装依赖/选择可用解释器和字体，不自动安装）：

```powershell
$env:PYTHONPATH="$RenderDependencyDir;$PdfQaDependencyDir"
$env:MPLCONFIGDIR="$ProjectRoot/projects/.carto-dev/mplconfig"
$env:CARTO_GEOSPATIAL_TEST_PYTHON=$TrustedGisPython
$env:CARTO_TEST_CJK_FONT=$ExplicitCjkTtf
$env:CARTO_RASTER_QA_DIR="$ProjectRoot/projects/.carto-dev/qa"
& $CartoPython -B -m unittest discover -s skills/carto-agent/scripts/tests -t skills/carto-agent/scripts -p 'test_*.py'
```

测试中需要主动清除 Matplotlib 的字体缓存，否则 Windows 会阻止临时字体目录清理；只在测试使用私有缓存释放方法，运行时不删除任何字体快照。

## 尚未完成的第三批 B

1. 场景来源准入/许可/敏感性、模板 author/validation、数据准备/规划/编译/图例检查组件；全部实现测试后才进行受信场景注册。
2. 在现有 PreparedDataBundle、候选、RenderScene、MapSpecLock 中显式绑定分类准备引用、页面请求和真实后端身份，不能塞临时字段或假报 `maplibre-web`。
3. 预览、冻结、正式渲染、检查和交付中的后端分派与可信环境/代码/字体证明；内部页面报告不能顶替 RenderReceipt。
4. 保留 G1/G2/G3 和已有回执验证；PDF/PNG 进入现有交付包，SVG 仍为内部产物。
5. 用户明确 0/255 的意义、隐藏策略及类名/配色合同后，才执行真实数据验收。该澄清不等于业务审批。

尚未做实体打印、CMYK/色彩管理、真北/子午线收敛角、旋转或地理 CRS 栅格、自动重投影及操作系统级渲染隔离。不对本批合成验收扩大能力声明。
