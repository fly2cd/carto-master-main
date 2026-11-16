# 分类栅格工作流历史验收声明归档

整理日期：2026-11-16（Asia/Shanghai）。

**性质：历史记录，不是当前操作指南、机器协议或本次测试结果。** 以下段落从原 `skills/carto-agent/workflows/raster-classification.md` 的验收章节迁出，保留原有阶段称谓、命令和结果声明。归档不重新证明这些结果；本次文档整理未运行其中的 GIS/MCP、渲染或业务验收测试。历史“已实现 / 尚未完成”须结合当前代码、策略及实际验证重新判断。

- 当前分类准备操作：[分类栅格准备与澄清](../../skills/carto-agent/workflows/raster-classification.md)。
- 当前研发职责与核验位置：分类栅格与静态页面研发参考 raster-rendering-development.md（已移除，可从 git 历史取回）。
- 不得依据下列命令或测试说明安装依赖、使用业务数据、签发真实审批或修改能力开关；执行测试仍需用户允许。

## 原“已验证与尚未完成”章节

自动测试使用临时合成 TIFF/CSV，覆盖动态澄清、严格 Schema、路径/摘要/作用域、真正的 Rasterio/Matplotlib PNG、alpha、稀疏值、掩膜、方向、图例一致性，以及 A4 297×210 mm / 300 dpi / 3508×2480 px 的版面与图体位置。
显式设置 `CARTO_GEOSPATIAL_TEST_PYTHON` 后可运行真实 MCP→冻结→澄清→共享表达编译→渲染→SVG 集成。

```powershell
& $CartoPython -B -m unittest discover -s skills/carto-agent/scripts/tests -t skills/carto-agent/scripts -p 'test_raster_*.py' -v
```

未安装可选渲染依赖时相关测试会跳过，不能把 skip 称为渲染通过。`test_general_thematic.py` 的模板发布链测试同样需要上述渲染依赖与可嵌入 CJK TTF（可用 `CARTO_TEST_CJK_FONT` 显式指定，macOS 默认尝试 Arial Unicode.ttf），无依赖或字体时跳过。

第三批 A 的合成测试另覆盖整页三格式、PDF MediaBox/嵌入字体/文字提取、十类中文图例换行、图体颜色不插值、格网北、投影比例尺、冻结复现及篡改拒绝。中文与独立 PDF 渲染验收需显式 `CARTO_TEST_CJK_FONT`，开发环境另装 `pypdf` / `pypdfium2`；它们不是运行时渲染依赖。`CARTO_RASTER_QA_DIR` 如设置，只允许仓库 `projects/.carto-dev/` 内保存合成 QA 图，不导出用户数据到测试目录。整页 PDF 已经独立光栅化目视核对；未做实体打印、CMYK/色彩管理或真实用户地图验收。

## 原“共享正式链路：验收范围与下一步”章节

- `fixtures/raster-formal/` 提供 6 组合法/非法结构样例；不能当作运行产物或审批。
- `test_raster_formal.py` 使用临时真实合成 TIFF/TTF 和测试密钥，覆盖共享 bundle/scene、正式回执、工作流预览→G2→渲染→终检→G3→交付、中断恢复、冻结字体、摘要/作用域/环境及输出篡改。
- 工作流测试从合成候选边界开始，仅在测试里替代能力/已安装模板发现安装；模板创建侧的合成测试真实走完 T1 → author → validate（合成样张渲染并冻结场景）→ 篡改拒绝 → TP → 发布与幂等重放，但全部使用合成数据与合成审批密钥，不假称真实用户数据、真实审批身份或用户地图已经验收。
- **仍待独立完成**：真实业务用途和模板组件的准入、实际数据类别含义/配色确认、用户地图验收；不创建“分类栅格业务场景”来代替。没有新增直接导出地图的 CLI 或审批旁路。

不得把合成测试、内部 PDF/PNG/SVG 或页面报告称为用户数据已完成正式 A4 制图交付。

### S1-C/D 补充验证

`test_s1cd_grid.py` 验证六种实例化参数、不同合成 TIFF、同源复用、独立/共享图例、独立范围、全部图体与篡改拒绝；`test_general_thematic.py` 还覆盖四图真实生成工作流、G3 原子提交后的恢复，以及模板声明组合缺失/交换时拒绝发布。测试密钥和工具统计适配器仅存在于测试，不构成真实授权或独立 GIS 服务验收。
