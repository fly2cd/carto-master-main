# 分类栅格准备、共享表达、整页输出与正式链路

## 状态与职责

本文覆盖数据辅助 CLI、共享表达/整页组件及第三批 C 的正式链路适配。不是新的顶层路由；正式交付仍由已有 `generate-map` 的业务准入和 G1/G2/G3 控制。

```text
显式 TIFF + CSV 输入合同
  → geospatial-mcp / ToolGateway 精确统计
  → Carto 分类表匹配与动态澄清
  → 不可变 TIFF、CSV 快照 + 待绑定的类别显示定义
  → 显式 portrayal 图层 + 受信 raster/categorical 表达引用
  → RasterPortrayalCompiler → resolved-raster-portrayal 冻结表达
  → Rasterio 解码快照、核验统计证据
  → Matplotlib 离散颜色映射 → 图体 PNG
  → LayoutResolver 的共享页面/框合同
     ├─ RasterMapBodyRenderer.compose + SvgCompositor → 既有内部 SVG 挂接
     └─ RasterPageRenderer + Matplotlib → 物理字号的整页 PDF / PNG / SVG
```

- MCP 不处理类别含义、颜色、图例、纸张或渲染。
- MapLibre、QGIS 均不在这条静态图体路径中；不把它包装为 `maplibre-web` 回执。
- 场景策略与实现白名单当前仅登记 `general-thematic-mapping`（实现 `general-thematic-raster`）。共享正式工作流已接通静态后端，由该已准入场景组件（含模板样张渲染分支）使用；不把数据类型注册为业务场景。
- 准备报告的 `ready` 只表示分类合同完整，绝不表示 G1/G2/G3 已批准或完成地图验收。
- 原始 TIFF 的 NoData、像元、掩膜不修改。用户回答 `semantic=nodata` 也是显示合同，不是数据重写操作。

## 依赖与入口

阅读 `geospatial-data.md`，使用已确认的 Python 3.11+。基础准备只需要原有协议依赖和 MCP 客户端；可选图体依赖见 `requirements-raster-rendering.txt` / 根 `pyproject.toml` 的 `raster-rendering` extra。由操作员显式安装，不自动安装或回退其他后端。

唯一 CLI 新增：

```powershell
& $CartoPython -B skills/carto-agent/scripts/carto.py data analyze-classification $RequestFile `
  --mcp-config $ConfigFile --project-root $ProjectRoot `
  --allowed-root $ProjectRoot --allowed-root $DataRoot --allowed-root $ServicePythonRoot `
  --run-id $RunId --tenant-id $TenantId --project-id $ProjectId --subject-id $SubjectId

& $CartoPython -B skills/carto-agent/scripts/carto.py data clarify-classification $PreparedRefFile `
  --answers $AnswersFile --project-root $ProjectRoot --allowed-root $ProjectRoot `
  --run-id $RunId --tenant-id $TenantId --project-id $ProjectId --subject-id $SubjectId
```

路径/配置/catalog/数据根仍走允许根校验；服务配置中的 tenant/project 必须匹配调用上下文。
`$PreparedRefFile` 是只含 `id/version/digest/uri` 的 **artifact-ref JSON**，不是整份准备报告或 CLI stdout。
CLI 仅输出 `prepared_ref/status/class_count/question_count` 等摘要；宿主在授权项目中读取报告展示 `questions`，不把类别行/地理范围写到普通日志。
澄清阶段**不需要 MCP 配置或可用的原始数据路径**，仅使用冻结快照。

## 请求合同

`raster-classification-request` 所有字段显式指定，不猜列名或同名文件：

| 字段 | 规则 |
|---|---|
| `source` | 既有严格 `raster-input`，绑定路径、SHA256、大小、CRS、band、来源声明等 |
| `legend.path/digest/size_bytes` | CSV 原始字节身份；支持 UTF-8（含 BOM），最多 1 MiB |
| `legend.encoding` | `utf-8-sig` |
| `legend.value_column` | 精确整数码列；拒绝小数、重复类别、越界值 |
| `legend.label_column` | 显式类别名称列；未映射的说明/推断列不作为执行指令 |
| `legend.color_column` | 六位 HEX 色列，或显式 `null` |
| `palette` | `null` 或显式选择 `carto-categorical-v1`；后者仅为 12 色版本化候选，不代表国家标准/业务语义 |
| `legend_policy` | `observed`：仅原始有效像元中出现的类别进入图例；`all`：包含表中未出现的类别 |

CSV 与统计值取并集，最多 256 类。即使 `legend_policy=observed`，CSV 中未出现类别的名称/颜色仍要求完整，以保持整份分类合同可重现；它们不自动进入图例。
超过候选调色板容量的缺色类别继续澄清，不循环复用颜色。不会从类别名称推断颜色，不自动把未知值分配成背景。

## 澄清协议

`raster-prepared-data` 的 `status=needs-clarification` 时，任何图体渲染都必须拒绝。
动态问题包括：未定义像元值、缺类别名称、缺颜色。**0、255 和其他未定义值采用同一规则，没有特殊硬编码。**
源文件已有的内部 NoData/掩膜由统计排除；被源掩膜屏蔽的像元不要求用户重新命名。

回答使用 `raster-classification-answers`：

- `based_on_digest`：**最初无回答基线报告**的 canonical digest，不是 request digest、CLI stdout digest 或上一次回答报告 digest。
- `entries`：需要覆盖的类别完整定义，包含 `value/semantic/display/label/color/order/include_in_legend`。
- `semantic` 可为 `class/background/nodata`；`display` 为 `color/hidden`，二者分开。
- `display=color` 必须有名称和 HEX 颜色；`hidden` 必须 `color=null` 且 `include_in_legend=false`。
- `order` 在所有类别中唯一，不能与未覆盖的 CSV 类别顺序冲突。重复/无关类别、未知字段、陈旧摘要、跨 run/tenant/project/subject 回答全部拒绝。
- 允许逐步补全；**再次提交是完整替换 overrides，不是与上次答案合并**。再次提交保留之前仍需生效的 entries，并仍绑定最初基线 digest。
- 每次生成新的不可变报告；旧报告不改写，也不签发审批。

## 冻结与渲染边界

项目内受保护存储：

- `.carto/geospatial/evidence/tool-gis-raster-statistics/1.0.0/`：网关统计证据。
- `.carto/raster/source/`、`legend/`：以原始字节 SHA256 命名的自包含源快照。
- `.carto/raster/raster-prepared-data/`：绑定输入、算法摘要、上下文、证据、澄清与分类行。
- `.carto/raster/resolved-raster-portrayal/`：绑定模板表达、类别显示定义、源快照与上下文的不可变表达。
- `.carto/raster/map-body/`、`raster-map-body/`：PNG 与类型化图体产物。

发布采用原子 create-only；相同内容复用，冲突拒绝。不是跨文件事务，失败可能留下无成功报告引用的快照；不自动删除或导入残留。
重载会核验所有摘要、项目内固定命名空间、算法版本，并从冻结 CSV/统计重新计算分类，不能靠手写 `ready` 绕过。
这些是可信本机存储下的内容完整性保护，**不是对任意本机恶意写入者的签名认证或 OS 沙箱**。

底层 API 位于 `workflow/raster_preparation.py`、`compiler/raster_portrayal.py`、`adapters/raster_renderer.py`，不是单独宿主实现：

- `RasterPreparationService.analyze / clarify / load_verified`。
- `RasterPortrayalCompiler.compile(portrayal, layer_id, prepared_ref, context)` → 不可变 `resolved-raster-portrayal`。
- `RasterMapBodyRenderer.render(portrayal_ref, resolved_layout, context)` → 不可变 `raster-map-body`。
- `.compose(body_ref, resolved_layout, overlays, output_path, context, inline_fonts=...)` → 内部 SVG；重新渲染比对产物，拒绝图体/布局/环境漂移。
- 调用方提供一个分类图例 overlay；条目从冻结分类合同填充。调用方若给出冲突条目则拒绝，绝不独立生成第二份色表。
- 继续使用现有 `LayoutResolver`，不是硬编码 A4 特例。SVG 图像矩形必须位于 map frame 内，PNG 尺寸必须一致；保留实际图体比例，不撑满异形框。
- 图体坐标变换 `ground_to_image` 是投影坐标 → PNG 局部像素（左上原点）；页面坐标需加 `image_rect` 的 x/y。

第一版只支持自包含 GTiff、已知 EPSG 投影坐标、单波段 8/16/32 位整数、north-up 且无旋转。拒绝外部 `.msk/.aux.xml/.ovr`、未知/地理 CRS、多波段、连续值、旋转和自动重投影。
TIFF 最多 256 MiB、源像元最多 1600 万；页面/图体最长边 4096 px、最多 1600 万像素。这是应用层界限，**不是解码器内存沙箱**；GDAL/NumPy 中间数组仍可能消耗数百 MiB。

Rasterio 从快照字节的 MemoryFile 全分辨率解码，检查真实元数据、有效值/计数和掩膜与 MCP 证据一致，不把 Carto 的核验变成另一个 GIS 统计服务。
稀疏/负数/大类别码先做精确索引，再用 `ListedColormap + BoundaryNorm` 映射；缩放仅对类别索引用最近邻，不读取内置 overview，不做双线性插值。
原始掩膜和显式隐藏像元透明；所有源像元都被掩膜、全部显式隐藏，或缩图后没有任何可见像元时均拒绝空图。
`observed` 指源分辨率的出现统计，不保证小类别在最近邻缩图后仍可见；图例不会按缩图抽样悄悄删类。

## 共享表达编译（第三批 B1）

四个概念分开：分类栅格是**数据类型**，`raster/categorical` 是**类别着色表达**，Rasterio + Matplotlib 是**当前实现后端**，业务场景描述**用途**。SVG/PDF/PNG 是成果格式。表达合同不含业务场景、后端选择或代码导入路径。

`compiler/raster_portrayal.py` 留在 Carto：它解析用户明确绑定的 CSV 显示定义、处理澄清、生成显示查找表和图例，不执行重分类、重投影或 GIS 分析。原 `raster_classification.py` 已更名，不保留并行兼容模块。

- 共享 `map-expression` 和 `portrayal` 协议增加 raster 分支，受信目录固定为 `policies/map-expression-catalog.yaml`。新增目录 Schema；已有两种矢量表达定义不变。
- 模板 `portrayal` 只声明图层 ID、数据角色、精确表达引用及固定策略：唯一值匹配、未知值拒绝、源掩膜保留、nearest、NoData 透明；类别名称和颜色来自项目内已澄清定义，不把实际类别行写入模板。
- `MapExpressionCatalog` 验证目录、重复身份、active 状态、引用摘要、图层唯一 ID 与几何兼容性；模板静态校验和候选编译共用同一校验器。目录登记表达不是场景准入或后端开放。
- `resolved-raster-portrayal` 冻结模板合同、准备引用、表达引用、源快照、上下文和编译器摘要；`lookup_table` 仅含 value/display/label/color/order/include_in_legend，图例从同表派生。不携带统计计数或把 `semantic=nodata` 变成源 NoData。
- 每次消费重新验证源证据和目录，并重建合同比对；不能通过手改类别颜色、隐藏状态、图例或来源字段绕过。图体和整页都只接受 `portrayal_ref`，不再直接接收准备引用。
- 当前编译器只执行一个栅格图层，无规则执行器；多图层/混合图层、非空 rules、双线性插值、Jenks 等均拒绝，不悄悄遗漏。

内部调用方必须显式提供已选的模板表达，不能根据 TIFF 后缀自动选择业务用途：

```python
portrayal_compiler = RasterPortrayalCompiler(preparation_service)
expression_artifact = portrayal_compiler.compile(
    template_portrayal, raster_layer_id, ready_prepared_ref, execution_context
)
body_artifact = RasterMapBodyRenderer(preparation_service).render(
    expression_artifact.ref(), resolved_layout, execution_context
)
# 整页请求改为 page_request["portrayal_ref"] = expression_artifact.ref()。
# 上述为内部组件 API；正式链路由第三批 C 适配，不是独立导出或审批入口。
```

**旧产物处理**：本次内部合同删除页面/图体上的 `prepared_ref`，更名也改变准备算法与渲染代码摘要。旧内部快照不能原样重放，需重新准备、绑定新的澄清摘要并编译；不迁移旧锁或伪造旧审批。准备 CLI 输出与表达产物内部的 `prepared_ref` 仍指向准备报告。

## 内部整页输出（第三批 A）

新增 `adapters/raster_page_renderer.py`。它消费同一个冻结图体和 `LayoutResolver`，不重新计算版式框、不另建颜色合同，也不经 MapLibre/浏览器。**SVG 是一种输出格式，不是本分支必须经过的中间渲染引擎。** 旧 `RasterMapBodyRenderer.compose` 保持原固定像素 SVG 挂接；物理字号页面使用新的 Matplotlib 页面适配器，两者不能混称。

```python
renderer = RasterPageRenderer(preparation_service)
page_artifact = renderer.render(page_request, execution_context)
page = renderer.load_verified(page_artifact.ref(), execution_context)
# page["outputs"]["pdf"|"png"|"svg"] 为项目内的不可变资源引用。
# 不是 RenderReceipt，不可用于替代预览、G2、成品检查或交付。
```

### 严格输入：`raster-page-request`

- `portrayal_ref`：同 run/tenant/project/subject 的 `resolved-raster-portrayal` 引用；其类别定义必须来自 ready 准备报告。页面重新核验表达、目录摘要和源快照，未澄清时在页面依赖加载前拒绝；不再直接接受 `prepared_ref`。
- `resolved_layout`：由现有 `LayoutResolver` 产生并重新验证的完整快照；纸张不硬编码为 A4。
- `font`：显式绝对路径、字节 SHA256、大小；先允许根校验，再冻结到 `.carto/raster/font/`。最多 32 MiB，只支持单字体 TrueType TTF，不支持 TTC/OTF/WOFF。
- `texts`：`content_id + text`，只能绑定 title/marginalia；必须恰好一个标题。`legend`：`content_id + title`，条目只来自图体的冻结分类，禁止请求传入另一套颜色。
- `typography`：显式 `title_pt/body_pt/legend_pt/legend_heading_pt/padding_mm/line_spacing`。字体单位为 pt，不是 px；默认值由调用方决策，组件不补写。
- `scale_bar`、`grid_north`：必须显式传对象或 `null`。所有非地图框必须且只能被绑定一次；多余、不支持的框拒绝。
- 图例遵守布局的 `capacity.legend_items`，标题遵守 `capacity.title_characters`。实际字形测宽后换行，不省略类别名、不缩小字号、不默默裁剪；实测边界超框则拒绝。

### 字体与输出

检查所有文字的字形覆盖和字体的技术嵌入标记。拒绝 restricted/no-subsetting/bitmap-only 模式；这些标记**不代替字体授权来源或正式许可检查**。缺字不会回退系统字体或继续输出方框。禁用 TeX、数学解释和 tight bbox 裁纸。

- PDF：使用真实毫米页面（A4 横版为 297×210 mm），TTF 子集嵌入，不把整页压成一张图片；图体仍为栅格，文字保留文本。
- PNG：页面像素按既有规则四舍五入，A4/300dpi 为 3508×2480；白色页底，隐藏区域透出页底。图体不做平滑分类插值。
- SVG：物理 pt 页面，栅格图体内嵌、字形路径化，不依赖查看端字体或外部 URL。
- 原始字体删除后仍可从冻结字体复现；输出、来源、字体、布局、代码或环境漂移均被重载验证拒绝。重复导出不含当前时钟或随机 SVG ID。
- 内部页面报告 `raster-page-output` 记录请求/图体/字体引用、环境、三格式资源与测量结果；`capability_boundary` 固定为 `internal-page-output-not-formal-render-receipt`。
- 新增命名空间 `.carto/raster/raster-page-request/`、`raster-page-output/`、`page-pdf/`、`page-png/`、`page-svg/`、`font/`。依然不是跨文件事务：失败可留孤立的源/字体/图体快照，不发布成功页面报告。用户原文件不改写。

### 比例尺和北向

`scale_bar={content_id,distance_m,label_language}` 按已拟合图体的投影坐标→页面比例和 CRS 线性单位换算长度（含美制测量英尺）。标注“投影距离”/“Grid distance”，**不是大地线真地面距离，不承诺整图处处相同的地面比例尺**。过短或超过专属框的距离必须更换，组件不猜值。

`grid_north={content_id,label}` 仅接受“格网北”或“Grid north”，针对当前仅支持的 north-up 投影栅格。**未实现真北、子午线收敛角或磁北**，不得标成单独 N/True north。

### 验收边界

`content-fit` 是 Matplotlib/Agg 对文字、色块、箭头的测量检查，不是正式 `FinalMapCheckService` 的签名验收。应用层像元/文件上限并非 OS 解码沙箱。Matplotlib 会缓存字体文件句柄，项目内字体快照须保持不可变；临时测试主动释放缓存以便 Windows 清理。

## 已验证与尚未完成

自动测试使用临时合成 TIFF/CSV，覆盖动态澄清、严格 Schema、路径/摘要/作用域、真正的 Rasterio/Matplotlib PNG、alpha、稀疏值、掩膜、方向、图例一致性，以及 A4 297×210 mm / 300 dpi / 3508×2480 px 的版面与图体位置。
显式设置 `CARTO_GEOSPATIAL_TEST_PYTHON` 后可运行真实 MCP→冻结→澄清→共享表达编译→渲染→SVG 集成。

```powershell
& $CartoPython -B -m unittest discover -s skills/carto-agent/scripts/tests -t skills/carto-agent/scripts -p 'test_raster_*.py' -v
```

未安装可选渲染依赖时相关测试会跳过，不能把 skip 称为渲染通过。`test_general_thematic.py` 的模板发布链测试同样需要上述渲染依赖与可嵌入 CJK TTF（可用 `CARTO_TEST_CJK_FONT` 显式指定，macOS 默认尝试 Arial Unicode.ttf），无依赖或字体时跳过。

第三批 A 的合成测试另覆盖整页三格式、PDF MediaBox/嵌入字体/文字提取、十类中文图例换行、图体颜色不插值、格网北、投影比例尺、冻结复现及篡改拒绝。中文与独立 PDF 渲染验收需显式 `CARTO_TEST_CJK_FONT`，开发环境另装 `pypdf` / `pypdfium2`；它们不是运行时渲染依赖。`CARTO_RASTER_QA_DIR` 如设置，只允许仓库 `projects/.carto-dev/` 内保存合成 QA 图，不导出用户数据到测试目录。整页 PDF 已经独立光栅化目视核对；未做实体打印、CMYK/色彩管理或真实用户地图验收。

## 共享正式链路（第三批 C）

### 1. 正式数据与场景契约

`generate-request` 新增可选 `prepared_raster_bindings`，静态后端要求恰好一项，角色与 `source_bindings` 一致，引用同 run/tenant/project/subject 的 ready 报告。示意片段（不是真实可执行引用）：

```json
{"prepared_raster_bindings": [{"role": "land-cover", "prepared_ref": {
  "id": "ready-preparation", "version": "1.0.0",
  "digest": "sha256:0000000000000000000000000000000000000000000000000000000000000000",
  "uri": "fixture-project/.carto/raster/raster-prepared-data/example.json"
}}]}
```

- `RasterBundlePreparer` 验证准备报告后生成正式 `PreparedDataBundle`：类型化 raster role、band、实际 CRS/bbox/宽高、源快照和 GIS/质量证据；不虚构 vector feature_count/join_coverage/观测时间，不声称发生重投影。
- `RasterSceneCompiler` 冻结页面请求及 TTF，生成独立 `rasterio-matplotlib-page` RenderScene；保存项目上下文、bundle/page 引用、布局、DPI、输出与精确资源集，无 browser camera/map/overlays 字段。
- `bind_execution` 向场景已构造的业务 execution 绑定 `raster_inputs`、数据/字体引用、视图、目标参数和真实后端环境。调用方仍须传入已核验的意图、模板/依赖和策略，不由共享编译器替用户决定。
- 资源集闭合到 bundle、准备请求、ready 报告、MCP 证据、portrayal、page、TIFF、CSV、TTF。引用按其类别分别校验规范 JSON 或原始字节摘要，重新构建后必须精确匹配；不从 URI 反推可信项目范围。
- `MapCandidateCompiler` 和正式工作流再校验生成请求的源/准备报告、输出目标、数据性质、图层、范围及 CRS；不允许静默换源、换配色或重投影。

已准入场景组件可复用以下 API（示意，不是跳过 G1/G2 的调用入口）：

```python
prepared = RasterBundlePreparer(preparation_service).prepare_request(request, context)
scene = RasterSceneCompiler(preparation_service).compile(
    bundle_ref=prepared["bundle_ref"], page_request=page_request,
    context=context, scene_id=scene_id, targets=request["requested_outputs"],
)
execution = RasterSceneCompiler(preparation_service).bind_execution(
    admitted_business_execution, scene, context,
)
```

### 2. 后端、正式回执与锁

`adapters/render_backend.py` 是预览、正式渲染及回执重放的闭合分派：只接纳 `maplibre-web` 与 `rasterio-matplotlib-page`，无 `auto`、未知后端或失败后隐式回退。栅格路径不探测/启动 Chromium。

`RasterFormalRenderer` 包装内部页面输出，复制经过摘要校验的成果到精确 session/attempt 目录，并签发独立严格分支的正式 RenderReceipt：

- 绑定 scene/revision/digest、session、资源集、执行摘要、随机种子、renderer profile/code digest。
- 环境包含 Python、Rasterio/GDAL、NumPy、Matplotlib、Pillow、FreeType、fonttools、zlib 的实际版本；fingerprint 还绑定平台和架构。不填写虚假的浏览器/MapLibre 版本。
- 绑定内部 page_output_ref 与 PDF/PNG（可附 SVG）的精确路径、格式、大小和原始字节摘要；HMAC 验证后仍重新校验场景、页面、资源和成果，不能仅凭签名放行错误绑定。
- 回执如实声明 `process_isolation=in-process`、`network_isolation=not-provided`，以及源/页像素上限。项目路径约束不等于 OS/网络沙箱；HMAC 不是远程可信执行或硬件证明。

候选预览证据进入既有 G2 对象摘要，`MapSpecLock` 保留同一 execution，无第二套 raster lock。冻结之后删除原字体路径仍可从受验证快照复现；修改冻结字体、输入、布局、环境或代码必须拒绝旧候选/锁。

### 3. 终检、G3 与交付

复用 `RenderAttempt` / `FormalRenderEvidence`、11 项最终检查、完整 Manifest 的精确 G3 和原子本地交付事务。静态分支核验真实 PDF 毫米页面、PNG 像素/DPI、字体嵌入与字形覆盖、实际测量布局、共用图例合同及 nearest/掩膜策略；业务图例检查、声明和许可依然必须由准入场景提供。敏感标记同时检查成果字节和实际使用的冻结文字，不把压缩 PDF/字形 SVG 的原始字节扫描当作充分检查。

交付只包含 `map.pdf`、`map.png`、`README.md`、`delivery-manifest.yaml`、`checksums.sha256`。错误摘要/scope、环境变化或成果篡改均拒绝；同 G3 的重放只允许匹配原恢复意图的幂等恢复，原子提交后中断可继续落回执而不覆盖成果。

### 4. 验收范围与下一步

- `fixtures/raster-formal/` 提供 6 组合法/非法结构样例；不能当作运行产物或审批。
- `test_raster_formal.py` 使用临时真实合成 TIFF/TTF 和测试密钥，覆盖共享 bundle/scene、正式回执、工作流预览→G2→渲染→终检→G3→交付、中断恢复、冻结字体、摘要/作用域/环境及输出篡改。
- 工作流测试从合成候选边界开始，仅在测试里替代能力/已安装模板发现安装；模板创建侧的合成测试真实走完 T1 → author → validate（合成样张渲染并冻结场景）→ 篡改拒绝 → TP → 发布与幂等重放，但全部使用合成数据与合成审批密钥，不假称真实用户数据、真实审批身份或用户地图已经验收。
- **仍待独立完成**：真实业务用途和模板组件的准入、实际数据类别含义/配色确认、用户地图验收；不创建“分类栅格业务场景”来代替。没有新增直接导出地图的 CLI 或审批旁路。

不得把合成测试、内部 PDF/PNG/SVG 或页面报告称为用户数据已完成正式 A4 制图交付。
