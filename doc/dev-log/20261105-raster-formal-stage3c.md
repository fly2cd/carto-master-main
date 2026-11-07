# 2026-11-05：栅格正式链路接入（第三批 C）

## 目标与结论

本批完成上一批 B1 留下的共享 PreparedDataBundle / MapSpecLock / RenderScene 接入、后端分派、正式 RenderReceipt 和 G2/G3 交付链适配。没有把“分类栅格”注册为业务场景，没有修改空的场景准入策略或签发真实审批。

分类栅格是数据类型，`raster/categorical` 是共享表达，Rasterio + Matplotlib 是静态后端；GIS 基础读取/分析仍属于独立 MCP，显示定义、冻结、排版、渲染与交付属于 Carto。

## 实现

### 1. 正式数据和冻结引用

- 新增 `workflow/raster_bundle.py` 的 `RasterBundlePreparer`：只接纳同项目、租户、运行和主体的 ready 准备报告，将已冻结源数据、MCP 证据与质量报告封装为正式 PreparedDataBundle。
- raster role binding 显式记录数据类型、band、CRS、bbox、宽高和准备引用；不伪造矢量 feature_count/join_coverage/观测时间，不声称进行过重投影。
- `generate-request.prepared_raster_bindings` 显式绑定唯一 ready 报告；请求、来源及输出目标必须精确一致，不按文件名猜测准备产物。`prepare_request` 在任何 I/O 前校验完整请求 Schema。
- 新增 `compiler/raster_scene.py` 的 `RasterSceneCompiler`：`compile` 冻结页面/字体而不绘制；`bind_execution` 向已有业务 execution 绑定栅格引用和环境，不选择用途或改写意图。
- 场景重建并逐一核验九项资源：bundle、准备请求、ready 报告、MCP 证据、表达合同、页面请求、TIFF、CSV、TTF。JSON 文档使用规范摘要，二进制使用原始字节摘要，调用方不能自行选择摘要算法语义。
- 候选编译器构造接口为 `(path_guard, registry, *, project_root, context)`，信任范围由通用工作流注入，不从任意 artifact URI 推断。
- 复用原 MapSpecLockCompiler 和相同 execution Schema；没有另造栅格锁或迁移旧锁。

### 2. 后端分派与真实回执

- 新增 `adapters/render_backend.py`，只接纳 `maplibre-web` 和 `rasterio-matplotlib-page`。未知 ID 拒绝，无自动回退；栅格不探测或启动 Chromium。
- RenderScene、RenderReceipt 和 execution environment 均有严格的浏览器/静态分支。栅格不携带虚假的浏览器版本、WebGL、camera 或浏览器交互字段。
- 新增 `adapters/raster_formal_renderer.py`：将经过校验的内部页面产物发布到精确 session/attempt 目录，签发绑定运行依赖、代码摘要、资源集、页面报告、环境、会话、时间和输出摘要的 HMAC RenderReceipt。
- 回执重验同时核对签名和完整重建结果。错误后端、资源/作用域/环境漂移、会话不符、路径或成果篡改均拒绝。失败通过既有 RenderAttempt 记录，不伪造成功回执。
- 后端明确是受项目路径约束的进程内实现，`network_isolation=not-provided`、`process_isolation=in-process`。HMAC 只证明持钥本地组件签发和对象绑定，不是 OS/网络沙箱、远程/硬件证明或逐像元语义认证。

### 3. 正式 G2/G3 链路

```text
已准入场景的候选
  → 按冻结后端预览与正式 RenderReceipt
  → 精确 G2 / MapSpecLock
  → 锁驱动正式渲染 / RenderAttempt / FormalRenderEvidence
  → 11 项成品检查 / 不可变 DeliveryManifest
  → 精确 G3
  → staging / 原子提交 / DeliveryReceipt / 状态恢复
```

- `map_preview.py`、`map_render.py`、`map_generation.py` 接入分派与栅格资源复验；保留意图、模板、候选、审批、环境和摘要验证。
- `map_final_check.py` 复用全部 11 项终检，补充静态页面的毫米尺寸、PNG/DPI、真实字体、测量布局、共享分类图例、nearest/掩膜和输出绑定检查。共性检查不能替代用途相关的业务图例检查器、声明与许可。
- 敏感文本检查除成品字节外，还检查实际绘制的冻结标题/图例/格网北标签及比例尺文字，避免 PDF 压缩、字体编码或 SVG 字形路径导致直接字节扫描漏检。
- G2/G3 的身份、动作、对象摘要、scope、environment、issuer、policy、时效和 nonce 约束不变。已消费 G3 仅在完全匹配的工作流 intent 下恢复，普通重放或篡改审批拒绝。
- 复用既有原子交付事务与恢复；最终包仍只有 `map.pdf`、`map.png`、`README.md`、`delivery-manifest.yaml`、`checksums.sha256`，不包含 TIFF/CSV、内部锁/回执或审批密钥。

## 协议与测试

- 新增 `test_raster_formal.py` 的 13 项测试，以临时合成 TIFF、字体副本及测试密钥覆盖共享 bundle/scene、候选组件信任范围、正式回执、预览到 G2/G3 交付、输出篡改、冻结字体、环境漂移、不可变 attempt、原子提交后中断与 nonce 恢复。
- 工作流测试只注入合成能力发现、候选边界和已安装模板校验；真实请求/意图投影、数据、布局、后端、G2/G3 签名与 nonce、状态、锁、终检、交付和恢复逻辑实际执行。不是 T1/TP/G1/模板发布端到端验收。
- `fixtures/raster-formal/` 提供六组合法/非法结构样例：PreparedDataBundle、RenderScene、RenderReceipt、ResolvedMap、MapSpecLock、GenerateRequest。全部是合成、项目相对引用，签名清零；不能作为可运行项目或真实回执。
- 样例路径脱敏后新增防止开发机绝对路径残留的断言。样例摘要仅用于结构演示，不声称脱敏后仍可通过运行时完整性校验。
- 调整旧意图单测中不满足完整合同的 mock，改用合法候选/场景并保持意图与执行摘要一致，没有削弱运行时验证。

## 验证结果

使用已确认的 Python 3.12.14、已有项目内可选依赖与显式中文测试字体，没有安装新依赖或向独立 GIS venv 写入包。

- 全量 **283 项：280 通过、3 跳过、0 失败/错误**，约 205 秒。
- 3 项跳过均因 Windows 不允许创建符号链接；真实 MCP→页面、中文 PDF 提取/独立光栅化、栅格正式工作流、真实浏览器 SVG/PNG/PDF 渲染测试均已运行通过。
- 最终样例路径脱敏及防回归断言更新后，补跑 Schema 专项 **16 项通过**；运行时代码未再修改。
- 唯一 CLI `--help` 正常；`schema check` 校验 **64 个 Schema**；**93 个 Python 文件** AST 解析通过；`git diff --check` 无空白错误，仅有既有文件 LF/CRLF 提示。
- 全量日志位于忽略目录 `projects/.carto-dev/stage3c-full-tests-final.log`，不作为运行协议或生产交付证据。

## 未开放边界

- `scenario-capabilities.yaml` 仍为 `profiles: []`，受信实现白名单仍为空，`production_tasks: []` 不变。不能仅通过修改策略开放能力。
- 实际业务用途、来源许可/安全准入、模板创建/发布与真实业务验收仍需独立完成；当前正式链路接入不表示这些步骤已完成。
- 没有制作或交付用户的 `landCover_reclassified.tif` 地图。类别语义（含 0/255）、名称/颜色须按真实输入与显式澄清确定，不能用合成测试答案替代。
- 新合同和代码指纹与旧内部产物不同，需重新编译、预览和审批；不新增旧格式兼容或审批旁路。
- 当前共享静态分支仍是单分类栅格图层、冻结 CRS、有限页面/像元预算；多图层混合、工作流内重投影、外部发布、CMYK/实体打印验收不在本批范围。
