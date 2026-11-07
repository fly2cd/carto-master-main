# geospatial-mcp 选择性集成方案

日期：2026-11-05  
状态：静态审查与实施建议；尚未接入 MCP、迁移算法或启用业务能力。

## 1. 结论与范围

可以选择性集成，但应集成受控 GIS 能力，不应将 GABench 的 133 个函数整体搬入 Carto Master，也不应将迁移建议清单直接当作运行时工具注册表。

推荐方案：保留独立 geospatial-mcp 服务，Carto Master 在唯一运行根 `skills/carto-agent/` 内增加受信客户端适配、工具契约映射、成果接收及场景编排。通用 GIS 算法在服务中维护；业务语义、分类图例、页面布局、审批、锁定和正式交付继续由 Carto Master 管理。

本次只新增本文档，没有修改外部仓库、安装依赖、运行开发测试、调用业务工具或开放能力。

## 2. 审查基线与已验证事实

源项目：

- geospatial-mcp：`D:/IdeaProjects/github/code-reviewer/geospatial-mcp`。
- 迁移规划：该项目 `docs/工具迁移清单.md` 及配套 JSON。
- 原始算法参考：`D:/IdeaProjects/IdeaProjects/GABench/toolbox/`。
- GABench 内还有一份 geospatial-mcp 子目录，本方案不将两份服务实现混为同一基线。

对清单中的 7 个源文件做了 SHA-256 对比和 Python AST 静态统计；全部摘要与清单匹配，公开顶层函数合计 133。未导入或执行旧算法。

| 模块 | 实际公开函数数 | 清单源文件摘要匹配 |
|---|---:|---|
| Data | 23 | 是 |
| Vector | 18 | 是 |
| Raster | 31 | 是 |
| Spatial | 17 | 是 |
| Network | 25 | 是 |
| GeoAI | 10 | 是 |
| Visual | 9 | 是 |

迁移清单自身明确：E=5、P1=20、P2=20、X=32、M=34、N=22，属于迁移规划，不是功能发布清单。

服务源码当前仅显式注册 9 个工具：未配置工作区时只有 2 个元数据工具；配置工作区后增加目录、任务、成果及矢量操作入口。`server.py` 当前仅开放 stdio。

## 3. 现有 9 个工具的 Carto 筛选结果

“优先接入”表示源码已有服务入口，但仍须完成 Carto 适配及验收，不代表即插即用。

| 工具 | 现有边界 | Carto 处理建议 |
|---|---|---|
| geo_raster_info | 已注册 GeoTIFF 的元数据；不扫描像元类别 | 首批接入，作为栅格探测；补输入快照/摘要绑定 |
| geo_vector_info | 图层、CRS、字段、几何与范围 | 首批接入，作为通用矢量探测 |
| geo_list_datasets | 操作者注册的数据目录；仅工作区模式注册 | 首批接入，但返回列表限定到当前项目已授权子集 |
| geo_get_task_info | 同步任务持久状态、输入摘要和参数 | 首批接入；不能替代 Carto 工作流状态、幂等与审批 |
| geo_get_artifact_info | 成果元数据和完整性检查 | 首批接入；联合 resources/read 构造成果接收链 |
| geo_vector_clip | 同 CRS 裁剪，输出 GPKG | 按矢量场景需求启用，不是当前单 TIFF 出图的前置项 |
| geo_vector_buffer | 投影平面缓冲及显式单位处理 | 按需接入，不默认用于土地覆盖制图 |
| geo_spatial_join | left/inner，intersects/within/contains | 按需接入；不宣称 nearest 或聚合支持 |
| geo_render_vector_map | 单矢量 PNG、有限数值样式、ASCII 标题 | 不纳入正式制图替代链；如有需求仅作单独标识的诊断预览 |

resources/read 是资源读取协议端点，不作为额外 GIS 算法工具计数。

## 4. 围绕 landCover.tif 的新增能力选择

用户要求处理的是原始 `projects/dataset/landCover.tif`，不是重分类文件。不得默认使用 `reclass_legend.csv`，也不得未经明确需求进行重分类。

| 候选能力 | 来源 | 首轮优先级与边界 |
|---|---|---|
| geo_raster_statistics（暂定新名称） | 现有 geo_raster_info 未实现；需要新增或严格扩展契约 | 核心：分块类别统计、NoData/掩膜、未映射值、扫描预算；区分精确与采样结果 |
| geo_raster_reproject | 迁移清单 P1 / Data.reproject_raster | 核心：真实 CRS 转换；输出网格、重采样、有效掩膜、目标大小和类别域受控 |
| 栅格显示资源生成（名称待定） | 参考 P1 geo_render_raster_map / Visual.visualize_raster | 核心：输入明确类别配色，输出带空间定位的显示资源；不负责最终标题、版式和审批 |
| geo_raster_mask | P1 / Raster.apply_mask_to_raster | 用户提供研究区边界时增加；无边界裁剪需求则不作为第一张图的前置项 |
| geo_raster_align | P1 / Data.align_raster_to_reference | 多栅格叠加/计算时增加；单文件制图不强制执行 |
| geo_raster_reclassify | P1 / Raster.reclassify_raster | 用户明确要求重分类时再增加；制图着色不等于改写类别值 |
| geo_raster_polygonize | P1 / Data.raster_to_polygons | 仅在选择矢量渲染路径时增加；保留类别和合法 0 类，限制要素/顶点/输出大小 |

后续按实际需求再选：geo_vector_reproject、geo_table_info、geo_table_to_points、geo_table_join、geo_rasterize、geo_zonal_statistics、geo_raster_sample、有限的 geo_raster_calculate 和矢量筛选/叠加。

首轮不引入 Network、GeoAI 的整套依赖，不引入模型训练、pickle、任意表达式求值或灾损等特定业务规则。

## 5. 不能直接复制的具体实现

以下为静态源码发现，不是已执行的数值测试结果：

1. `GABench/toolbox/Data.py:807-833` 的 raster_to_polygons 用 `arr != 0` 决定有效像元，且构造 `properties: {}`。用于分类栅格时会排除合法 0 类并丢失类别属性，必须重写此部分。
2. `GABench/toolbox/Raster.py:261-313` 的 reclassify_raster 在未声明 NoData 时指定 255，并最终强制 uint8。通用接口必须明确未映射值、有效掩膜、输出 dtype 和溢出策略，不能把 255 固定当作通用无数据值。
3. `GABench/toolbox/Data.py:703` 的 align_raster_to_reference 对未知重采样名称静默回退 nearest。受控工具应拒绝未知枚举，不静默改变请求。
4. `GABench/toolbox/Data.py:589-660` 的 reproject_raster 已调用真实重投影，但使用旧路径/全局输出目录接口，目标网格和重采样策略没有完整暴露；不能仅包一层装饰器当作可验收服务。
5. 现有 geo_render_vector_map 限 ASCII 标题、输出 PNG，不能直接交付中文题名的 A4 PDF，也不能替代 Carto 的锁驱动渲染及交付回执。

## 6. 必须先解决的接口差距

### 6.1 栅格成果闭环尚不存在

服务 `schemas.py::ArtifactInfo` 当前仅允许：

- kind：vector / image；
- format：gpkg / png；
- MIME：GeoPackage / PNG。

`workspace.py::publish` 也只接受 gpkg/png；`operations.py` 的输入加载路径只处理矢量。现有 geo_raster_info 只接受 dataset_id，不能读取前一步生成的栅格 artifact_id。

因此新增重投影前，必须同步实现栅格成果类型、GeoTIFF 发布与读取、RasterSourceRef/等效类型约束、CRS/网格元数据、输入/输出摘要、可链接成果以及资源限制。不能只在 Schema 枚举中加 tif。

现有默认成果大小限制为 16 MiB，输入默认限制为 256 MiB。重投影可能改变输出规模；后续须按实测制定限额，不自动无限提高限制。

### 6.2 Carto 不应直接相信外部输出

调用路径建议：

```text
carto CLI / 场景 data_preparer
  -> ToolGateway（白名单、作用域、预算）
  -> 受信 MCP 客户端适配（固定服务、工具与版本）
  -> 独立 geospatial-mcp stdio 进程
  -> 严格结果校验 + 成果接收
  -> PreparedDataBundle / tool_receipts / quality_evidence
  -> 既有候选、预览、审批、冻结、渲染、检查、交付
```

接收器须检查结构、服务/工具绑定、输入和参数摘要、任务状态、内容长度/媒体类型/文件摘要，并在 Carto 项目允许根内创建受控本地快照。对 GIS 输出还须检查实际 CRS、范围、网格、类别域及 NoData，不以服务返回“成功”替代验收。

既有 RasterInfo/VectorInfo 本身没有内容摘要绑定，元数据读取也需补快照身份方案。元数据 JSON 的摘要不等于源 TIFF 的摘要。

GPKG 矢量成果也不能原样进入当前只支持 GeoJSON 的 Carto 生成路径，需要受控规范化或正式扩展格式协议。TIFF/PNG 显示成果同理：必须显式扩展渲染入口，或者经过经验证的面化/规范化路径。

### 6.3 依赖与进程边界

- geospatial-mcp 的 pyproject 声明 Python >=3.12,<3.13，并固定 fastmcp、mcp、rasterio、pyproj 等依赖。
- Carto 声明 Python >=3.11；此前确认的本机 Carto 解释器为 Python 3.14.7。
- 不将服务 GIS 依赖直接塞进当前 Carto 解释器；建议服务独立 Python 3.12 环境，通过 stdio 通信。存在 .venv 不等于环境已通过本次验证。
- Carto 客户端所需依赖也须明确声明并验证，不假定仅有 McpAdapter 就已经有真实 MCP 传输能力。
- 不自动安装或启动外部服务，不读取 GABench .env、模型凭据或完整进程环境。

### 6.4 授权、路径和任务约束

- Dataset ID 是引用，不是授权凭据；目录绑定限定项目、来源许可和敏感性，不能由模型提供任意路径。
- 服务现有身份隔离边界为 single-operator，不宣称多租户授权。项目隔离宜使用独立目录/进程和受信会话绑定。
- data_root 与 workspace_root 在服务配置中不允许互相包含。建议分别使用项目数据目录与独立的 GIS 工作子目录；接收目录由 Carto 单独管理。
- 服务生成的 artifact:// URI 只能由固定受信连接解析；不得当作任意网络下载地址。
- 工具注册、调用许可、MCP 注解、命令执行许可均不替代 T1/TP/G1/G2/G3。
- 需定义超时、取消、进程退出、结果截断和崩溃恢复。不能在提交结果未知时盲目重试写操作；现有同步服务任务不是 Carto 的幂等协议。
- 不将业务数据行、敏感坐标或凭据写入普通日志。转换语义与必要空间元数据只进入受控业务产物/证据。

## 7. 推荐实施批次和验收门槛

### A：元数据接入和成果接收底座

Carto 内新增受信 stdio 适配、工具映射和项目目录绑定；先接 geo_raster_info、geo_vector_info，再接目录/任务/成果查询及资源接收。

验收：工具选择白名单、严格入参/出参、坏 schema、未知工具、未知 dataset_id、越界/符号链接、输入摘要漂移、失败/超时/截断、资源超限、成果篡改均有正反例。此阶段只声明“接入与探测”，不声明已能出土地覆盖图。

### B：栅格成果契约与最小处理链

先扩展服务端栅格成果闭环，再实现统计、重投影及分类显示资源。掩膜/对齐仅在任务需要时加入。算法代码与成果契约均需在服务侧实施，外部目录改动须按工作区权限流程执行。

验收：小型可手算分类栅格、合法 0 类、NoData/掩膜、非法波段、未知 CRS、已知控制点、网格参数、类别域、超出预算及多步栅格 artifact 复用。

### C：Carto 土地覆盖场景与 A4 横版

用户确认原始数据的类别编码/标签依据、用途与来源信息；实现并注册土地覆盖场景、类别图例、A4 297×210 mm、中文标题“用地分类数据”、适当 DPI、比例尺和来源说明。

按选定的栅格或矢量路径扩展 RenderScene 和实际渲染执行器，不只放宽共享 Schema；完成模板发布和 G1/G2/G3 等必要审批。

验收：像元/类别语义保真、图例一致、中文字体、空间范围与比例尺、PDF 页面尺寸、PNG 尺寸、渲染/锁/成果/回执全链绑定，以及不泄露原始数据的本地交付。新协议必须同时有合法/非法样例和自动测试。

### D：需求驱动的通用增强

有具体地图场景后再增加矢量裁剪/连接、CSV 落图、栅格计算、分区统计等。不是将原清单 P1/P2 整包启用。

## 8. 代码归属与不做事项

Carto 新增适配代码只能位于 `skills/carto-agent/scripts/carto_core/adapters/`；必要的共享协议在 `skills/carto-agent/schemas/`，版本化绑定在 `skills/carto-agent/policies/`，验收代码在 `skills/carto-agent/scripts/tests/`，业务场景在 `scripts/carto_core/scenarios/`。

服务侧通用算法继续在独立 geospatial-mcp 项目维护。GABench 为算法参考源，不导入其评测/Agent/模型配置和全局运行环境，不把整个 toolbox 加进 Carto 的 sys.path。

本文档及外部迁移清单只用于设计审查；运行时不得读取它们决定工具授权、审批或场景能力。没有实现、验收和精确审批时，不修改 production_enabled 或直接开放场景策略。

## 9. 关键源码索引

以下路径分别相对各仓库根目录：

- geospatial-mcp：`docs/工具迁移清单.md`、`docs/工具迁移清单.json`、`pyproject.toml`。
- geospatial-mcp：`src/geospatial_mcp/server.py`、`tools/data.py`、`tools/analysis.py`（后两项相对 src/geospatial_mcp）。
- geospatial-mcp：`src/geospatial_mcp/schemas.py`、`settings.py`、`workspace.py`、`operations.py`（后三项相对 src/geospatial_mcp）。
- GABench：`toolbox/Data.py:589`、`:663`、`:807`，`toolbox/Raster.py:261`。
- Carto：`skills/carto-agent/scripts/carto_core/adapters/mcp.py`、`tool_gateway.py`（后者相对同目录）。
- Carto：`skills/carto-agent/scripts/carto_core/workflow/map_data_preparation.py`、`skills/carto-agent/policies/tool-bindings.yaml`。
