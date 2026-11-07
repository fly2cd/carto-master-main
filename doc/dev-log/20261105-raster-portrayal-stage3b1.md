# 2026-11-05 第三批 B1：共享分类着色表达与冻结引用接入

## 结论与边界

本批实现“数据类型、制图表达、渲染后端、业务用途”分离，不创建“分类栅格业务场景”。分类栅格是输入数据类型，`raster/categorical` 是唯一值着色表达，Rasterio + Matplotlib 是当前静态后端，SVG/PDF/PNG 是输出格式。

本批完成表达合同与内部消费者接入，不等于正式 `generate-map` 全链路完成。场景能力策略和实现白名单保持为空，没有新导出 CLI，没有签发审批，没有修改用户 TIFF/CSV，没有改独立 geospatial-mcp 项目或安装依赖。

## 实现

1. `compiler/raster_classification.py` 更名为 `compiler/raster_portrayal.py`，更新运行时、渲染摘要和测试引用，不保留兼容别名。CSV 显式匹配、动态澄清、颜色/图例属于 Carto 的显示编译；不进行 GIS 重分类或重投影。
2. 共享 `map-expression` 与 `portrayal` 增加 raster 分支，目录版本 1.1.0，新增 `raster/categorical@1.0.0`。本批保留已有两种矢量表达规则，不以数据格式增加用途词。
3. 新 `map-expression-catalog` 严格 Schema 和 `MapExpressionCatalog`：只读固定受信目录，检查重复身份、active 状态、精确摘要、图层 ID 唯一和几何兼容；无请求指定代码导入或外部目录发现。
4. 新 `RasterPortrayalCompiler`：将显式模板图层、数据角色和 ready 类别显示定义绑定为 `resolved-raster-portrayal`。冻结准备引用、源快照、目录表达、调用作用域与编译器摘要，生成 display-only lookup_table 和唯一图例，不混入统计计数或改写源 NoData。
5. `RasterMapBodyRenderer` 与 `RasterPageRenderer` 改为消费 `portrayal_ref`；颜色和图例都来自冻结表达。重载重新核验源证据、受信表达目录和编译结果，拒绝篡改、作用域不符及旧准备引用直连。
6. 模板静态校验与候选编译复用 `MapExpressionCatalog`，即使伪造表达摘要与伪造依赖锁相互匹配，也不能绕过目录身份校验。
7. 新协议均有合法/非法样例；共享 portrayal/map-expression 有 raster 分支正反例，测试覆盖字段组合、精确引用、未知字段和不支持的策略。README、Skill、栅格工作流和场景扩展说明同步更新。

## 明确的限制和旧产物处理

- 当前表达编译器只执行一个栅格图层、空 rules、nearest、源掩膜保留、未知值拒绝。多图层/混合图层、非空规则、Jenks、双线性插值等明确拒绝，不会悄悄丢掉内容。
- 模板声明数据角色和表达策略；真实类别行留在项目冻结产物，不进入可复用模板。
- 页面/图体请求的旧 `prepared_ref` 已删除，改为 `portrayal_ref`；准备 CLI 的输出及表达产物内部仍引用准备报告。更名和新增协议使代码/算法摘要改变，旧内部快照须重新准备和编译，澄清绑定新基线摘要，不迁移旧锁或伪造审批。
- 0/255 不默认隐藏，不默认作 NoData；真实用户数据的类别含义与配色仍需显式确认。
- `raster-page-output` 仍是内部页面报告，不是正式 RenderReceipt。未增加浏览器/WebGL 伪字段来冒充 MapLibre 环境。

## 验证

沿用已确认的 Python 3.12.14 和已授权的项目内可选依赖，不向独立 GIS venv 安装包。

- 全量 **269 项：266 通过、3 跳过、0 失败/错误**，耗时约 103 秒。
- 3 项跳过均为 Windows 无符号链接创建权限；栅格渲染、真实 MCP 链路及中文 PDF 检查未跳过。
- 新 `test_raster_portrayal.py` 20 项通过；图体/页面各增一个准备引用旁路拒绝测试，已有集成测试均改为显式编译表达。
- 首轮全量仅旧“目录只有两种矢量表达且版本为 1.0.0”断言失败；更新为实际受信目录 1.1.0/三种表达后，重新执行完整回归通过，没有放宽运行时校验。
- 64 个 Schema 自检通过，88 个 Python 文件 AST 解析通过；`git diff --check` 无空白错误（另有既有文件的 LF/CRLF 提示）。
- 真实独立 MCP → 数据冻结 → 澄清 → 共享表达编译 → 图体/整页复现链通过，编译与渲染未增加 MCP 分析调用。
- 合成 A4 横版 PDF 独立光栅化后目视检查：中文标题、十类图例、长类别名换行、格网北和投影距离比例尺均完整，未见叠压、裁剪或缺字。PNG 3508×2480、PDF 297×210 mm 等结构检查通过。没有实体打印或真实用户成果验收。

开发证据只保存在被忽略的 `projects/.carto-dev/`：`stage3b-full-tests.log`、`stage3b-full-tests.json`、`qa/synthetic-a4-chinese-pdf.png`。全部是合成测试数据，不是用户地图交付。

## 尚未完成的正式接入

1. PreparedDataBundle、execution/MapSpecLock 冻结栅格数据、表达和页面请求引用。
2. RenderScene 与预览/正式渲染的后端分派，栅格专属可信环境和真实回执字段，不伪装浏览器后端。
3. 正式 RenderReceipt、成品检查、G2/G3 与交付链接入。
4. 按真实业务用途和模板完成独立准入，以及用户数据类别与颜色确认；不是注册“分类栅格场景”代替上述工作。

不得把上述剩余工程工作归结为“只差用户回答”，也不得把内部测试 PDF 当作正式交付。
